#!/usr/bin/env python3
# CI Gate: Dynamic VRAM Budget Check
import os
import argparse
import sys
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional
import re

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_CONFIG_ERROR = 2

"""Default fraction of total GPU memory to use as VRAM budget (90%).
Leaves 10% headroom for system/other processes."""
DEFAULT_VRAM_BUDGET_RATIO = 0.9


@dataclass(frozen=True)
class MemoryUnit:
    """
    Typed representation of a memory quantity with unit conversion.

    Encapsulates parsing, validation, and conversion logic for memory values
    expressed in various units (MiB, GiB, MB, GB, etc.).
    """
    value_mib: int

    @classmethod
    def parse(cls, val_str: str) -> "MemoryUnit":
        """
        Parse a memory string into a MemoryUnit.

        Args:
            val_str: String containing a memory value, typically in formats like
                     "16384 MiB", "8 GiB", "1024", "  2048 MB  ", etc.

        Returns:
            MemoryUnit instance with value normalized to MiB.

        Raises:
            ValueError: If the input string cannot be parsed as a valid memory value.
        """
        if not val_str or not val_str.strip():
            raise ValueError("Empty memory value string")

        parts = val_str.strip().split()
        if not parts:
            raise ValueError("No tokens in memory value string")

        num_str = parts[0]
        unit = parts[1] if len(parts) > 1 else ''

        # Handle cases where the unit is attached to the number without a space
        if not unit and any(c.isalpha() for c in num_str):
            m = re.match(r'(?P<num>[0-9]*\.?[0-9]+)\s*(?P<unit>[a-zA-Z]+)?', num_str)
            if m:
                num_str = m.group('num')
                unit = m.group('unit') or ''

        try:
            value = float(num_str)
        except ValueError as e:
            raise ValueError(f"Invalid numeric value in '{val_str}': {e}")

        unit = unit.lower()
        if unit in ('gib', 'gb', 'g'):
            value *= 1024
        elif unit in ('kib', 'kb', 'k'):
            value /= 1024
        # For 'mib', 'mb', 'm', or no unit, keep the value as-is (assumed MiB)

        return cls(value_mib=int(value))

    def to_mib(self) -> int:
        """Return the value in MiB."""
        return self.value_mib

    def __str__(self) -> str:
        return f"{self.value_mib} MiB"

    def __int__(self) -> int:
        return self.value_mib


@dataclass
class VramCheckResult:
    """Result of VRAM budget check."""
    success: bool
    used_mb: int
    budget_mb: int
    message: str
    exit_code: int


def get_gpu_info() -> Optional[ET.Element]:
    """
    Execute nvidia-smi --query-gpu=memory.total,memory.used --format=xml and return the parsed XML root element.

    Returns:
        ET.Element | None: Root element of the parsed XML from nvidia-smi query,
                           containing GPU memory information (total, used).
                           Returns None if nvidia-smi is not found, fails to execute,
                           or returns invalid XML that cannot be parsed.

    This function queries the NVIDIA System Management Interface for
    GPU memory information in XML format, which is then parsed for
    VRAM budget checking.
    """
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.total,memory.used', '--format=xml'],
            capture_output=True,
            text=True,
            check=True
        )
        return ET.fromstring(result.stdout)
    except (subprocess.CalledProcessError, FileNotFoundError, ET.ParseError):
        return None


def check_vram_budget(gpu_data: Optional[ET.Element] = None) -> VramCheckResult:
    """
    Check GPU VRAM usage against a budget.

    Reads VRAM_BUDGET_MB environment variable (optional, positive integer MiB).
    If not set, defaults to 90% of total GPU memory.

    Args:
        gpu_data: Optional pre-fetched GPU XML data. If None, calls get_gpu_info().

    Returns:
        VramCheckResult: Object containing check outcome, memory values,
                         human-readable message, and suggested exit code.
    """
    if gpu_data is None:
        gpu_data = get_gpu_info()

    if gpu_data is None:
        return VramCheckResult(
            success=False,
            used_mb=0,
            budget_mb=0,
            message="FAIL: GPU unavailable or nvidia-smi failed",
            exit_code=EXIT_FAIL
        )

    try:
        gpu = gpu_data.findall('.//gpu')  # Use .// to handle potential XML namespaces and get all GPUs
        if gpu is None:
            raise ValueError("No GPU device found in nvidia-smi output")

        fb_memory = gpu.find('fb_memory_usage')
        total_mb = MemoryUnit.parse(fb_memory.find('total').text if fb_memory.find('total') is not None else 'Unknown').to_mib()
        used_mb = MemoryUnit.parse(fb_memory.find('used').text if fb_memory.find('used') is not None else '0').to_mib()

        # Handle VRAM_BUDGET_MB override with validation
        env_budget = os.getenv('VRAM_BUDGET_MB')
        if env_budget:
            try:
                budget_mb = int(env_budget)
                if budget_mb <= 0:
                    raise ValueError
            except ValueError:
                return VramCheckResult(
                    success=False,
                    used_mb=used_mb,
                    budget_mb=0,
                    message="CONFIG ERROR: VRAM_BUDGET_MB must be a positive integer",
                    exit_code=EXIT_CONFIG_ERROR
                )
        else:
            budget_mb = int(total_mb * DEFAULT_VRAM_BUDGET_RATIO)

    except (AttributeError, ValueError, TypeError) as e:
        return VramCheckResult(
            success=False,
            used_mb=0,
            budget_mb=0,
            message=f"CONFIG ERROR: Failed to parse or validate GPU memory metrics: {e}",
            exit_code=EXIT_CONFIG_ERROR
        )

    if used_mb > budget_mb:
        return VramCheckResult(
            success=False,
            used_mb=used_mb,
            budget_mb=budget_mb,
            message=f"FAIL: VRAM usage {used_mb}MB exceeds budget {budget_mb}MB",
            exit_code=EXIT_FAIL
        )

    return VramCheckResult(
        success=True,
        used_mb=used_mb,
        budget_mb=budget_mb,
        message=f"PASS: VRAM usage {used_mb}MB within budget {budget_mb}MB",
        exit_code=EXIT_PASS
    )


def create_mock_gpu_xml(total_mb: int = 16384, used_mb: int = 8192, unit: str = "MiB") -> ET.Element:
    """
    Create mock nvidia-smi XML output for dry-run testing.

    Args:
        total_mb: Total GPU memory in MiB.
        used_mb: Used GPU memory in MiB.
        unit: Memory unit string to use in the mock XML (e.g., "MiB", "GiB", "MB", "GB").

    Returns:
        ET.Element: Mock XML root element simulating nvidia-smi -q -x output.
    """
    root = ET.Element('nvidia_smi_log')
    gpu = ET.SubElement(root, 'gpu')
    fb_memory = ET.SubElement(gpu, 'fb_memory_usage')
    ET.SubElement(fb_memory, 'total').text = f"{total_mb} {unit}"
    ET.SubElement(fb_memory, 'used').text = f"{used_mb} {unit}"
    ET.SubElement(fb_memory, 'free').text = f"{total_mb - used_mb} {unit}"
    return root


def main(dry_run: bool = False) -> int:
    """
    CLI entry point for VRAM budget check.

    Args:
        dry_run: If True, mock nvidia-smi and run full validation logic.

    Returns:
        int: Exit code (EXIT_PASS=0, EXIT_FAIL=1, EXIT_CONFIG_ERROR=2).
    """
    if dry_run:
        mock_gpu_data = create_mock_gpu_xml(total_mb=16384, used_mb=8192)
        result = check_vram_budget(gpu_data=mock_gpu_data)
        print(f"DRY-RUN: {result.message}")
        return result.exit_code

    result = check_vram_budget()
    print(result.message)
    return result.exit_code

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dynamic VRAM Budget Check")
    parser.add_argument("--dry-run", action="store_true", help="Mock nvidia-smi and run full validation")
    args = parser.parse_args()

    sys.exit(main(dry_run=args.dry_run))
