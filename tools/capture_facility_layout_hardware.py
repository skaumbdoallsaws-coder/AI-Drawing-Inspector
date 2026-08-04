#!/usr/bin/env python3
"""Capture a reproducible Facility Layout reference-hardware profile."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EDGE = Path(
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
)
DEFAULT_OUTPUT_DIR = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "performance"
)


class HardwareCaptureError(RuntimeError):
    """Raised when required hardware identity cannot be measured."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _powershell_json(script: str) -> Any:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        (
            "$ErrorActionPreference='Stop';"
            + script
            + " | ConvertTo-Json -Depth 8 -Compress"
        ),
    ]
    result = None
    for attempt in range(3):
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            break
        if attempt < 2:
            time.sleep(0.2 * (attempt + 1))
    if result is None or result.returncode != 0:
        detail = (result.stderr if result else "").strip()
        raise HardwareCaptureError(
            "The Windows hardware probe failed"
            + (f": {detail}" if detail else ".")
        )
    text = result.stdout.strip()
    if not text:
        raise HardwareCaptureError("The Windows hardware probe returned no data.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise HardwareCaptureError(
            "The Windows hardware probe returned invalid JSON."
        ) from error


def _record(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, list) and value and isinstance(value[0], Mapping):
        return value[0]
    return {}


def capture_windows_hardware(
    *,
    edge_path: Path,
    probe: Callable[[str], Any] = _powershell_json,
) -> dict[str, Any]:
    if platform.system() != "Windows":
        raise HardwareCaptureError(
            "The current reference-hardware capture supports Windows only."
        )
    computer = _record(
        probe(
            "Get-CimInstance Win32_ComputerSystem | "
            "Select-Object Manufacturer,Model,TotalPhysicalMemory"
        )
    )
    processor = _record(
        probe(
            "Get-CimInstance Win32_Processor | Select-Object "
            "Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed"
        )
    )
    operating_system = _record(
        probe(
            "Get-CimInstance Win32_OperatingSystem | "
            "Select-Object Caption,Version,BuildNumber"
        )
    )
    display = _record(
        probe(
            "Get-CimInstance Win32_VideoController | Select-Object -First 1 "
            "Name,AdapterRAM,DriverVersion,CurrentHorizontalResolution,"
            "CurrentVerticalResolution,CurrentRefreshRate"
        )
    )
    if not edge_path.is_file():
        raise HardwareCaptureError(f"Microsoft Edge was not found: {edge_path}")
    browser = _record(
        probe(
            "(Get-Item "
            + json.dumps(str(edge_path))
            + ").VersionInfo | Select-Object ProductName,ProductVersion,"
            "FileVersion"
        )
    )
    required = {
        "manufacturer": computer.get("Manufacturer"),
        "model": computer.get("Model"),
        "ramBytes": computer.get("TotalPhysicalMemory"),
        "cpu": processor.get("Name"),
        "gpu": display.get("Name"),
        "browserVersion": browser.get("ProductVersion"),
    }
    missing = sorted(key for key, value in required.items() if not value)
    if missing:
        raise HardwareCaptureError(
            "Required hardware fields were unavailable: " + ", ".join(missing)
        )
    return {
        "machine": {
            "manufacturer": str(required["manufacturer"]).strip(),
            "model": str(required["model"]).strip(),
        },
        "cpu": {
            "name": str(required["cpu"]).strip(),
            "physicalCores": int(processor.get("NumberOfCores") or 0),
            "logicalProcessors": int(
                processor.get("NumberOfLogicalProcessors") or 0
            ),
            "maximumClockMHz": int(processor.get("MaxClockSpeed") or 0),
        },
        "memory": {"ramBytes": int(required["ramBytes"])},
        "gpu": {
            "name": str(required["gpu"]).strip(),
            "adapterRamBytesReported": int(display.get("AdapterRAM") or 0),
            "driverVersion": str(display.get("DriverVersion") or "").strip(),
        },
        "display": {
            "width": int(display.get("CurrentHorizontalResolution") or 0),
            "height": int(display.get("CurrentVerticalResolution") or 0),
            "refreshHz": int(display.get("CurrentRefreshRate") or 0),
        },
        "operatingSystem": {
            "caption": str(operating_system.get("Caption") or "").strip(),
            "version": str(operating_system.get("Version") or "").strip(),
            "buildNumber": str(
                operating_system.get("BuildNumber") or ""
            ).strip(),
        },
        "browser": {
            "name": str(browser.get("ProductName") or "Microsoft Edge").strip(),
            "productVersion": str(required["browserVersion"]).strip(),
            "fileVersion": str(browser.get("FileVersion") or "").strip(),
            "executable": str(edge_path),
        },
    }


def build_hardware_profile(
    *,
    role: str,
    machine_label: str,
    measured: Mapping[str, Any],
    captured_at_utc: str | None = None,
    source_path: Path | None = None,
) -> dict[str, Any]:
    if role not in {"standard", "minimum"}:
        raise HardwareCaptureError("Hardware role must be standard or minimum.")
    label = str(machine_label or "").strip()
    if not label:
        raise HardwareCaptureError("A stable machine label is required.")
    source = source_path or Path(__file__).resolve()
    return {
        "schemaVersion": "facility-layout-reference-hardware-v1",
        "role": role,
        "status": "measured",
        "machineLabel": label,
        "capturedAtUtc": captured_at_utc or _utc_now(),
        "measurement": dict(measured),
        "source": {
            "path": str(source.relative_to(ROOT)).replace("\\", "/")
            if source.is_relative_to(ROOT)
            else str(source),
            "sha256": _sha256_file(source),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture exact Windows hardware for Facility Layout budgets."
    )
    parser.add_argument("--role", choices=("standard", "minimum"), required=True)
    parser.add_argument("--machine-label", required=True)
    parser.add_argument("--edge-path", type=Path, default=DEFAULT_EDGE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or (
        DEFAULT_OUTPUT_DIR / f"{args.role}-hardware-profile.json"
    )
    try:
        measured = capture_windows_hardware(
            edge_path=args.edge_path.resolve()
        )
        profile = build_hardware_profile(
            role=args.role,
            machine_label=args.machine_label,
            measured=measured,
        )
    except (HardwareCaptureError, OSError, subprocess.SubprocessError) as error:
        print(f"ERROR\t{error}", file=sys.stderr)
        return 2
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
