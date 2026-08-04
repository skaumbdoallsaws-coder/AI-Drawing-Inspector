from __future__ import annotations

from pathlib import Path

import pytest

from tools.capture_facility_layout_hardware import (
    HardwareCaptureError,
    build_hardware_profile,
    capture_windows_hardware,
)


def test_build_hardware_profile_is_explicitly_named_and_role_bound(
    tmp_path: Path,
):
    source = tmp_path / "capture.py"
    source.write_text("print('capture')\n", encoding="ascii")
    profile = build_hardware_profile(
        role="minimum",
        machine_label="pilot-low-end-01",
        measured={"cpu": {"name": "Example CPU"}},
        captured_at_utc="2026-07-30T00:00:00Z",
        source_path=source,
    )
    assert profile["role"] == "minimum"
    assert profile["status"] == "measured"
    assert profile["machineLabel"] == "pilot-low-end-01"
    assert len(profile["source"]["sha256"]) == 64

    with pytest.raises(HardwareCaptureError, match="stable machine label"):
        build_hardware_profile(
            role="standard",
            machine_label="",
            measured={},
            source_path=source,
        )


def test_windows_capture_requires_all_release_identity_fields(
    monkeypatch,
    tmp_path: Path,
):
    edge = tmp_path / "msedge.exe"
    edge.write_bytes(b"edge")
    responses = iter(
        [
            {
                "Manufacturer": "Dell",
                "Model": "Reference",
                "TotalPhysicalMemory": 8_000_000_000,
            },
            {
                "Name": "CPU",
                "NumberOfCores": 4,
                "NumberOfLogicalProcessors": 8,
                "MaxClockSpeed": 3000,
            },
            {
                "Caption": "Windows",
                "Version": "10",
                "BuildNumber": "1",
            },
            {
                "Name": "GPU",
                "AdapterRAM": 1_000_000_000,
                "DriverVersion": "1",
                "CurrentHorizontalResolution": 1366,
                "CurrentVerticalResolution": 768,
                "CurrentRefreshRate": 60,
            },
            {
                "ProductName": "Microsoft Edge",
                "ProductVersion": "150.0.1",
                "FileVersion": "150.0.1",
            },
        ]
    )
    monkeypatch.setattr(
        "tools.capture_facility_layout_hardware.platform.system",
        lambda: "Windows",
    )
    measured = capture_windows_hardware(
        edge_path=edge,
        probe=lambda _script: next(responses),
    )
    assert measured["display"] == {
        "width": 1366,
        "height": 768,
        "refreshHz": 60,
    }
    assert measured["cpu"]["logicalProcessors"] == 8

    broken = iter([{}, {}, {}, {}, {}])
    with pytest.raises(HardwareCaptureError, match="unavailable"):
        capture_windows_hardware(
            edge_path=edge,
            probe=lambda _script: next(broken),
        )
