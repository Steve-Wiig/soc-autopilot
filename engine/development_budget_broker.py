"""Parent-process broker for shared development API-budget admission.

The broker owns the APIBudgetManager instance and therefore the authoritative
budget ledger. Sandboxed development workers never receive filesystem access
to the ledger itself.

Protocol: newline-delimited JSON over a Unix-domain socket.

Request:
    {"op":"reserve","provider":"openrouter","model":"..."}

Response:
    {"ok":true,"reserved":true}
    {"ok":true,"reserved":false,"reason":"BUDGET_EXHAUSTED"}
    {"ok":false,"error":"..."}
"""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType

from overnight.budget_manager import APIBudgetManager

# Maximum number of pending connections the broker's listening socket will
# queue before the OS starts refusing new ones.
_LISTEN_BACKLOG = 8

# How long (seconds) `accept()` blocks before looping back to check the stop
# event. Keeps the serve loop responsive to `stop()` without busy-waiting.
_ACCEPT_POLL_INTERVAL_SECONDS = 0.25

# How long (seconds) a per-connection socket will block on `recv()` before
# giving up on a slow/stalled client.
_CONNECTION_RECV_TIMEOUT_SECONDS = 5.0

# How long (seconds) `stop()` waits for the serve thread to exit before
# giving up on a clean join.
_SERVE_THREAD_JOIN_TIMEOUT_SECONDS = 2.0

# Hard cap on the size of a single request line, to avoid unbounded memory
# growth from a misbehaving or malicious client.
_MAX_REQUEST_LINE_BYTES = 65536

# Chunk size used when draining a client connection's socket buffer.
_RECV_CHUNK_BYTES = 4096


class DevelopmentBudgetBroker:
    """Threaded Unix-socket broker backed by the shared API budget.

    Listens on a Unix-domain socket and serves newline-delimited JSON
    "reserve" requests from sandboxed development workers, forwarding
    admission decisions to the underlying `APIBudgetManager`. Optionally
    restricts which provider/model combination callers may request.
    """

    def __init__(
        self,
        *,
        budget: APIBudgetManager | None = None,
        socket_path: Path | None = None,
        allowed_provider: str | None = None,
        allowed_model: str | None = None,
    ) -> None:
        self.budget = budget or APIBudgetManager()
        self.socket_path = Path(socket_path) if socket_path else None
        self.allowed_provider = (
            allowed_provider.strip()
            if isinstance(allowed_provider, str) and allowed_provider.strip()
            else None
        )
        self.allowed_model = (
            allowed_model.strip()
            if isinstance(allowed_model, str) and allowed_model.strip()
            else None
        )
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> Path:
        """Bind the broker's Unix socket and start serving in a background thread.

        Returns:
            The filesystem path of the bound Unix-domain socket.

        Raises:
            RuntimeError: If the broker is already running.
            ValueError: If no `socket_path` was configured.
        """
        if self._server is not None:
            raise RuntimeError("Budget broker already running")

        if self.socket_path is None:
            raise ValueError("socket_path is required")

        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        self.socket_path.chmod(0o600)
        server.listen(_LISTEN_BACKLOG)
        server.settimeout(_ACCEPT_POLL_INTERVAL_SECONDS)

        self._server = server
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._serve,
            name="development-budget-broker",
            daemon=True,
        )
        self._thread.start()

        return self.socket_path

    def stop(self) -> None:
        """Signal the serve loop to stop, join its thread, and remove the socket file.

        Safe to call multiple times; subsequent calls are no-ops once the
        broker has already been stopped.
        """
        self._stop_event.set()

        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None

        if self._thread is not None:
            self._thread.join(timeout=_SERVE_THREAD_JOIN_TIMEOUT_SECONDS)
            self._thread = None

        if self.socket_path is not None:
            try:
                self.socket_path.unlink()
            except FileNotFoundError:
                pass

    def _serve(self) -> None:
        """Accept and handle connections until `stop()` is called.

        Runs on the background thread started by `start()`. Uses a short
        accept timeout so the stop event is checked regularly.
        """
        server = self._server
        if server is None:
            return

        while not self._stop_event.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            with conn:
                conn.settimeout(_CONNECTION_RECV_TIMEOUT_SECONDS)
                self._handle_connection(conn)

    def _handle_connection(self, conn: socket.socket) -> None:
        """Read one newline-delimited JSON request and reply on the given socket.

        Args:
            conn: The accepted client connection. Left open/closed by the
                caller (the `with conn:` block in `_serve`).
        """
        buffer = b""

        # Read until we have a full request line, the client disconnects, or
        # the request exceeds the configured size limit.
        while b"\n" not in buffer and len(buffer) < _MAX_REQUEST_LINE_BYTES:
            try:
                chunk = conn.recv(_RECV_CHUNK_BYTES)
            except socket.timeout:
                return

            if not chunk:
                return

            buffer += chunk

        if len(buffer) >= _MAX_REQUEST_LINE_BYTES:
            self._send(
                conn,
                {"ok": False, "error": "REQUEST_TOO_LARGE"},
            )
            return

        # Parse only the first line; anything after the first newline is
        # ignored (the protocol is strictly one request per connection).
        try:
            request = json.loads(buffer.split(b"\n", 1)[0])
        except json.JSONDecodeError:
            self._send(conn, {"ok": False, "error": "INVALID_JSON"})
            return

        if not isinstance(request, dict):
            self._send(conn, {"ok": False, "error": "INVALID_REQUEST"})
            return

        if request.get("op") != "reserve":
            self._send(conn, {"ok": False, "error": "UNSUPPORTED_OPERATION"})
            return

        provider = request.get("provider")
        model = request.get("model")

        if not isinstance(provider, str) or not provider.strip():
            self._send(conn, {"ok": False, "error": "INVALID_PROVIDER"})
            return

        if model is not None and not isinstance(model, str):
            self._send(conn, {"ok": False, "error": "INVALID_MODEL"})
            return

        provider = provider.strip()

        if (
            self.allowed_provider is not None
            and provider != self.allowed_provider
        ):
            self._send(
                conn,
                {
                    "ok": False,
                    "error": "PROVIDER_NOT_AUTHORIZED",
                },
            )
            return

        if (
            self.allowed_model is not None
            and model != self.allowed_model
        ):
            self._send(
                conn,
                {
                    "ok": False,
                    "error": "MODEL_NOT_AUTHORIZED",
                },
            )
            return

        try:
            reserved = self.budget.reserve_call(provider, model)
        except Exception:
            self._send(conn, {"ok": False, "error": "BUDGET_CONTROL_FAILURE"})
            return

        self._send(
            conn,
            {
                "ok": True,
                "reserved": bool(reserved),
                **({} if reserved else {"reason": "BUDGET_EXHAUSTED"}),
            },
        )

    @staticmethod
    def _send(conn: socket.socket, payload: dict[str, object]) -> None:
        """Serialize `payload` as JSON and write it, newline-terminated, to `conn`."""
        conn.sendall(
            (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        )


class DevelopmentBudgetBrokerContext:
    """Context manager that runs a `DevelopmentBudgetBroker` on a temporary socket.

    Creates a private temporary directory for the Unix-domain socket file so
    callers don't need to manage socket path lifecycle themselves, and
    guarantees the broker is stopped and the directory cleaned up on exit.
    """

    def __init__(
        self,
        budget: APIBudgetManager,
        *,
        allowed_provider: str | None = None,
        allowed_model: str | None = None,
    ) -> None:
        self.budget = budget
        self.allowed_provider = allowed_provider
        self.allowed_model = allowed_model
        self._tmp: TemporaryDirectory[str] | None = None
        self.broker: DevelopmentBudgetBroker | None = None

    def __enter__(self) -> DevelopmentBudgetBroker:
        """Create the temporary socket directory, start the broker, and return it."""
        self._tmp = TemporaryDirectory(prefix="soc-autopilot-budget-")
        path = Path(self._tmp.name) / "budget.sock"
        self.broker = DevelopmentBudgetBroker(
            budget=self.budget,
            socket_path=path,
            allowed_provider=self.allowed_provider,
            allowed_model=self.allowed_model,
        )
        self.broker.start()
        return self.broker

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Stop the broker and remove the temporary socket directory."""
        if self.broker is not None:
            self.broker.stop()
        if self._tmp is not None:
            self._tmp.cleanup()
        self.broker = None
        self._tmp = None
