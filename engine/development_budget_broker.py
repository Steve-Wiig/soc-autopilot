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

from overnight.budget_manager import APIBudgetManager


class DevelopmentBudgetBroker:
    """Threaded Unix-socket broker backed by the shared API budget."""

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
        self._stop = threading.Event()

    def start(self) -> Path:
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
        server.listen(8)
        server.settimeout(0.25)

        self._server = server
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._serve,
            name="development-budget-broker",
            daemon=True,
        )
        self._thread.start()

        return self.socket_path

    def stop(self) -> None:
        self._stop.set()

        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None

        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        if self.socket_path is not None:
            try:
                self.socket_path.unlink()
            except FileNotFoundError:
                pass

    def _serve(self) -> None:
        server = self._server
        if server is None:
            return

        while not self._stop.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            with conn:
                conn.settimeout(5.0)
                self._handle_connection(conn)

    def _handle_connection(self, conn: socket.socket) -> None:
        buffer = b""

        while b"\n" not in buffer and len(buffer) < 65536:
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                return

            if not chunk:
                return

            buffer += chunk

        if len(buffer) >= 65536:
            self._send(
                conn,
                {"ok": False, "error": "REQUEST_TOO_LARGE"},
            )
            return

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
    def _send(conn: socket.socket, payload: dict) -> None:
        conn.sendall(
            (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        )


class DevelopmentBudgetBrokerContext:
    """Create a temporary broker socket and clean it up deterministically."""

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

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.broker is not None:
            self.broker.stop()
        if self._tmp is not None:
            self._tmp.cleanup()
        self.broker = None
        self._tmp = None
