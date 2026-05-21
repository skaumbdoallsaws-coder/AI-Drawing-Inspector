"""Tests for the Library Intake visual-enrichment endpoint
(POST /api/library/intake/enrich-visuals).

Covers:
- Rename helper produces canonical {pn}_* filenames from arbitrary
  source stems (the OLD SolidWorksExtractor names outputs from
  GetDeterministicPartNumber which falls back to SLDPRT filename
  stem when no PART_NUMBER custom property is set).
- Endpoint input validation (400 / 404 / 409 paths).
- Bridge active-doc cross-check enforced.
- Subprocess invocation mocked end-to-end; tests verify the
  rename + sidecar-copy pipeline lands files in the right place
  with the right names.
- Single-flight lock enforces one enrichment at a time.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterator
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402


# ── _intake_rename_visuals_to_pn unit tests ───────────────────────────


def test_rename_visuals_renames_stem_to_target_pn(tmp_path: Path):
    """Standard case: extractor emitted 'Vintage Plane_*' (fell back
    to filename stem because no PART_NUMBER custom property), the
    operator chose 1030034. All known suffix patterns rename."""
    work = tmp_path / "work"
    work.mkdir()
    for fn in (
        "Vintage Plane_view_front.png",
        "Vintage Plane_view_top.png",
        "Vintage Plane_view_right.png",
        "Vintage Plane_view_isometric.png",
        "Vintage Plane_colored.glb",
        "Vintage Plane_feature_colors.json",
        "Vintage Plane.STL",
    ):
        (work / fn).write_bytes(b"x")

    out = server._intake_rename_visuals_to_pn(work, "1030034")
    out_names = sorted(p.name for p in out)
    assert out_names == sorted([
        "1030034_view_front.png",
        "1030034_view_top.png",
        "1030034_view_right.png",
        "1030034_view_isometric.png",
        "1030034_colored.glb",
        "1030034_feature_colors.json",
        "1030034.STL",
    ])
    # Original-stem files should NOT remain on disk
    leftovers = [p.name for p in work.iterdir() if p.is_file() and not p.name.startswith("1030034")]
    assert leftovers == []


def test_rename_visuals_already_correct_is_noop(tmp_path: Path):
    """Idempotent: when extractor already produced files matching the
    target PN (operator set PART_NUMBER custom property correctly),
    the helper returns the same paths and leaves filenames untouched."""
    work = tmp_path / "work"
    work.mkdir()
    for fn in ("1030034_colored.glb", "1030034.stl"):
        (work / fn).write_bytes(b"x")
    out = server._intake_rename_visuals_to_pn(work, "1030034")
    out_names = sorted(p.name for p in out)
    assert out_names == ["1030034.stl", "1030034_colored.glb"]


def test_rename_visuals_preserves_stl_case(tmp_path: Path):
    """ExportSolidWorksFormats writes .STL (uppercase). Some SLDPRT
    sources may have produced .stl historically. Helper preserves
    whichever case the source used."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "ABC.STL").write_bytes(b"x")
    (work / "DEF.stl").write_bytes(b"y")
    out = server._intake_rename_visuals_to_pn(work, "9999999")
    names = sorted(p.name for p in out)
    assert names == ["9999999.STL", "9999999.stl"]


def test_rename_visuals_skips_unrelated_files(tmp_path: Path):
    """Helper must NOT touch files that don't match any known visual
    suffix (the OLD extractor also drops a .json next to the visuals;
    ExportSolidWorksFormats drops .stp and .STEP)."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "abc_view_front.png").write_bytes(b"x")     # known
    (work / "abc.json").write_bytes(b"{}")              # unrelated
    (work / "abc.stp").write_bytes(b"step1")            # unrelated
    (work / "abc.STEP").write_bytes(b"step2")           # unrelated
    out_paths = server._intake_rename_visuals_to_pn(work, "1030034")
    out_names = sorted(p.name for p in out_paths)
    assert out_names == ["1030034_view_front.png"]
    # Unrelated files still present, untouched
    for fn in ("abc.json", "abc.stp", "abc.STEP"):
        assert (work / fn).exists(), f"{fn} should be left alone"


# ── Endpoint fixture ──────────────────────────────────────────────────


def _seed_sidecar(library: Path, pn: str, package_id: str,
                  source_path: Path) -> Path:
    """Drop a minimal sidecar that points back at `source_path`
    (which the test creates as a fake SLDPRT). Returns the sidecar
    package-root path."""
    pkg_root = library / "_bridge_imports" / "part" / pn / package_id
    (pkg_root / "part").mkdir(parents=True)
    (pkg_root / "part" / "part.json").write_text(json.dumps({
        "schemaVersion": "1.0",
        "partNumber":    pn,
        "name":          "Test Part",
        "sourcePath":    str(source_path),
        "features":      [],
    }), encoding="utf-8")
    (pkg_root / "manifest.json").write_text(json.dumps({
        "packageId":  package_id,
        "partNumber": pn,
        "kind":       "part",
    }), encoding="utf-8")
    return pkg_root


@pytest.fixture
def enrich_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Spin up a fresh library with a sidecar for 1030034 that
    references a fake on-disk SLDPRT. Tests can monkey-patch the
    subprocess + bridge-client to simulate enrichment runs."""
    library = tmp_path / "enrich_lib"
    library.mkdir()
    sldprt = tmp_path / "Vintage Plane v2.SLDPRT"
    sldprt.write_bytes(b"FAKE SLDPRT")
    pkg_id = "abc123pkg"
    sidecar = _seed_sidecar(library, "1030034", pkg_id, sldprt)

    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    monkeypatch.setattr(server, "assembly_profiles", {}, raising=False)
    monkeypatch.setattr(server, "inspector", None)
    # Pretend both extractor binaries exist (we mock the subprocess
    # runner, so the actual exe is never invoked).
    monkeypatch.setattr(server, "_solidworks_extractor_exe_path", lambda: r"C:\fake\SolidWorksExtractor.exe")
    monkeypatch.setattr(server, "_export_formats_exe_path",       lambda: r"C:\fake\ExportSolidWorksFormats.exe")
    yield {
        "library":     library,
        "sldprt":      sldprt,
        "package_id":  pkg_id,
        "sidecar":     sidecar,
    }


# ── Validation paths ──────────────────────────────────────────────────


def test_endpoint_rejects_empty_part_number(enrich_library: dict):
    client = TestClient(server.app)
    r = client.post("/api/library/intake/enrich-visuals",
                    json={"partNumber": "!!!", "partPackageId": enrich_library["package_id"]})
    assert r.status_code == 400
    assert "invalid part number" in r.json()["detail"].lower()


def test_endpoint_rejects_empty_package_id(enrich_library: dict):
    client = TestClient(server.app)
    r = client.post("/api/library/intake/enrich-visuals",
                    json={"partNumber": "1030034", "partPackageId": ""})
    assert r.status_code == 400
    assert "package" in r.json()["detail"].lower()


def test_endpoint_404_when_sidecar_missing(enrich_library: dict):
    client = TestClient(server.app)
    r = client.post("/api/library/intake/enrich-visuals",
                    json={"partNumber": "1030034", "partPackageId": "no-such-pkg"})
    assert r.status_code == 404
    assert "sidecar not found" in r.json()["detail"].lower()


def test_endpoint_409_when_sourcepath_missing_on_disk(enrich_library: dict,
                                                      monkeypatch: pytest.MonkeyPatch):
    """sidecar's sourcePath references a file that has been moved or
    deleted -- endpoint must surface a clean 409 with the missing
    path so the operator knows what to fix."""
    enrich_library["sldprt"].unlink()  # remove the fake SLDPRT
    client = TestClient(server.app)
    r = client.post("/api/library/intake/enrich-visuals",
                    json={"partNumber": "1030034", "partPackageId": enrich_library["package_id"]})
    assert r.status_code == 409
    assert "does not exist on disk" in r.json()["detail"].lower()


def test_endpoint_503_when_bridge_unavailable(enrich_library: dict,
                                              monkeypatch: pytest.MonkeyPatch):
    """Bridge status returns None -> 503."""
    async def _fake_status(self):
        return None
    monkeypatch.setattr(server.BridgeClient, "status", _fake_status)
    client = TestClient(server.app)
    r = client.post("/api/library/intake/enrich-visuals",
                    json={"partNumber": "1030034", "partPackageId": enrich_library["package_id"]})
    assert r.status_code == 503
    assert "bridge" in r.json()["detail"].lower()


def test_endpoint_409_when_bridge_active_doc_mismatch(enrich_library: dict,
                                                      monkeypatch: pytest.MonkeyPatch):
    """Bridge active doc path != sidecar sourcePath -> 409 with
    explicit instructions. This is the load-bearing safety check:
    without it the operator could enrich the wrong part."""
    async def _fake_status_wrong_doc(self):
        m = MagicMock()
        m.active_doc = MagicMock(type="Part", title="WrongPart.SLDPRT",
                                  path=r"C:\elsewhere\WrongPart.SLDPRT")
        return m
    monkeypatch.setattr(server.BridgeClient, "status", _fake_status_wrong_doc)
    client = TestClient(server.app)
    r = client.post("/api/library/intake/enrich-visuals",
                    json={"partNumber": "1030034", "partPackageId": enrich_library["package_id"]})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "does not match" in detail.lower()
    assert "wrongpart" in detail.lower()


def test_endpoint_409_when_no_active_doc(enrich_library: dict,
                                         monkeypatch: pytest.MonkeyPatch):
    async def _fake_status_no_doc(self):
        m = MagicMock()
        m.active_doc = None
        return m
    monkeypatch.setattr(server.BridgeClient, "status", _fake_status_no_doc)
    client = TestClient(server.app)
    r = client.post("/api/library/intake/enrich-visuals",
                    json={"partNumber": "1030034", "partPackageId": enrich_library["package_id"]})
    assert r.status_code == 409
    assert "no active document" in r.json()["detail"].lower()


# ── Happy path with mocked subprocess ─────────────────────────────────


def _stub_extractor_run(work_dir: Path, source_stem: str = "Vintage Plane v2"):
    """Drop fake outputs that the renamer will pick up. Simulates what
    the OLD extractor would produce: filenames carry the SLDPRT stem
    because the test SLDPRT has no PART_NUMBER custom property."""
    work_dir.mkdir(parents=True, exist_ok=True)
    for sfx in ("_view_front.png", "_view_top.png", "_view_right.png",
                "_view_isometric.png", "_colored.glb", "_feature_colors.json"):
        (work_dir / f"{source_stem}{sfx}").write_bytes(b"PNG-FAKE" if sfx.endswith(".png") else b"X")
    # The extractor also writes a part.json next to the visuals --
    # tests confirm the rename helper IGNORES it.
    (work_dir / f"{source_stem}.json").write_text("{}", encoding="utf-8")


def _stub_stl_run(work_dir: Path, source_stem: str = "Vintage Plane v2"):
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / f"{source_stem}.STL").write_bytes(b"STL-FAKE")
    # ExportSolidWorksFormats also writes .stp and .STEP -- tests
    # confirm those are NOT copied into the sidecar (the user opted
    # to keep only .STL).
    (work_dir / f"{source_stem}.stp").write_bytes(b"STP")
    (work_dir / f"{source_stem}.STEP").write_bytes(b"STEP")


def test_endpoint_happy_path_renames_and_copies_visuals(enrich_library: dict,
                                                        monkeypatch: pytest.MonkeyPatch):
    """End-to-end: mock both subprocess calls to produce stem-named
    outputs, verify the renamer converts them to {pn}_* and the
    copy step drops 7 visuals (6 from extractor + STL) into the
    sidecar's part/ subdirectory. Stray .stp / .STEP / .json files
    are NOT copied."""
    # Mock bridge status to match the sourcePath
    sldprt = enrich_library["sldprt"]
    async def _fake_status_ok(self):
        m = MagicMock()
        m.active_doc = MagicMock(type="Part", title=sldprt.name, path=str(sldprt))
        return m
    monkeypatch.setattr(server.BridgeClient, "status", _fake_status_ok)

    # Mock the sync subprocess runner. The runner is called once per
    # binary; we dispatch on the FIRST argv element (the exe path).
    call_log = []
    def _fake_run(argv, timeout_s=180.0):
        call_log.append(list(argv))
        # Figure out which output dir to populate by sniffing argv
        if argv[0].endswith("SolidWorksExtractor.exe"):
            # --output <path>/<stem>.json -> outputs to dirname(path)
            out_idx = argv.index("--output")
            out_dir = Path(argv[out_idx + 1]).parent
            _stub_extractor_run(out_dir, source_stem="Vintage Plane v2")
            return {"argv": list(argv), "rc": 0, "stdout": "ok",
                    "stderr": "", "timedOut": False}
        if argv[0].endswith("ExportSolidWorksFormats.exe"):
            # <sldprt> <out_dir>
            out_dir = Path(argv[2])
            _stub_stl_run(out_dir, source_stem="Vintage Plane v2")
            return {"argv": list(argv), "rc": 0, "stdout": "ok",
                    "stderr": "", "timedOut": False}
        return {"argv": list(argv), "rc": -1, "stdout": "", "stderr": "unknown binary", "timedOut": False}
    monkeypatch.setattr(server, "_intake_enrich_run_subprocess_sync", _fake_run)

    client = TestClient(server.app)
    r = client.post("/api/library/intake/enrich-visuals",
                    json={"partNumber": "1030034", "partPackageId": enrich_library["package_id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert sorted(body["filesAdded"]) == sorted([
        "1030034_colored.glb",
        "1030034_feature_colors.json",
        "1030034_view_front.png",
        "1030034_view_top.png",
        "1030034_view_right.png",
        "1030034_view_isometric.png",
        "1030034.STL",
    ])
    assert body["filesMissing"] == []

    # Files actually present in the sidecar's part/ subdir
    part_dir = enrich_library["sidecar"] / "part"
    actual = sorted(p.name for p in part_dir.iterdir() if p.is_file())
    # part.json was already there + the 7 new visuals
    for expected in body["filesAdded"]:
        assert expected in actual, f"{expected} missing from sidecar"
    # .stp / .STEP / OLD-extractor .json were NOT copied
    for stray in ("Vintage Plane v2.stp", "Vintage Plane v2.STEP", "Vintage Plane v2.json"):
        assert stray not in actual

    # Both subprocesses were invoked exactly once
    extractor_calls = [c for c in call_log if c[0].endswith("SolidWorksExtractor.exe")]
    formats_calls   = [c for c in call_log if c[0].endswith("ExportSolidWorksFormats.exe")]
    assert len(extractor_calls) == 1
    assert len(formats_calls)   == 1
    # Extractor argv includes --part-glb + --views
    assert "--part-glb" in extractor_calls[0]
    assert "--views"    in extractor_calls[0]
    # STL argv passes the source SLDPRT
    assert formats_calls[0][1] == str(sldprt)


def test_endpoint_partial_extraction_surfaces_missing_files_warning(enrich_library: dict,
                                                                    monkeypatch: pytest.MonkeyPatch):
    """If the OLD extractor produced only SOME of the expected visuals
    (e.g. ViewExporter SaveBMP failed for the iso view), the endpoint
    returns success=true with a warning naming the missing files."""
    sldprt = enrich_library["sldprt"]
    async def _fake_status_ok(self):
        m = MagicMock()
        m.active_doc = MagicMock(type="Part", title=sldprt.name, path=str(sldprt))
        return m
    monkeypatch.setattr(server.BridgeClient, "status", _fake_status_ok)

    def _fake_run_partial(argv, timeout_s=180.0):
        if argv[0].endswith("SolidWorksExtractor.exe"):
            out_idx = argv.index("--output")
            out_dir = Path(argv[out_idx + 1]).parent
            out_dir.mkdir(parents=True, exist_ok=True)
            # Produce only 3 of the 6 expected outputs
            (out_dir / "Vintage Plane v2_view_front.png").write_bytes(b"PNG")
            (out_dir / "Vintage Plane v2_colored.glb").write_bytes(b"GLB")
            (out_dir / "Vintage Plane v2_feature_colors.json").write_bytes(b"{}")
            return {"argv": list(argv), "rc": 0, "stdout": "", "stderr": "iso view failed", "timedOut": False}
        if argv[0].endswith("ExportSolidWorksFormats.exe"):
            out_dir = Path(argv[2])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "Vintage Plane v2.STL").write_bytes(b"STL")
            return {"argv": list(argv), "rc": 0, "stdout": "", "stderr": "", "timedOut": False}
        return {"argv": list(argv), "rc": -1, "stdout": "", "stderr": "", "timedOut": False}
    monkeypatch.setattr(server, "_intake_enrich_run_subprocess_sync", _fake_run_partial)

    client = TestClient(server.app)
    r = client.post("/api/library/intake/enrich-visuals",
                    json={"partNumber": "1030034", "partPackageId": enrich_library["package_id"]})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert sorted(body["filesAdded"]) == sorted([
        "1030034_view_front.png",
        "1030034_colored.glb",
        "1030034_feature_colors.json",
        "1030034.STL",
    ])
    # Top, right, iso views missing -- surfaced via filesMissing AND warning
    assert "1030034_view_top.png"       in body["filesMissing"]
    assert "1030034_view_right.png"     in body["filesMissing"]
    assert "1030034_view_isometric.png" in body["filesMissing"]
    assert any(w["code"] == "incomplete_extraction" for w in body["warnings"])


def test_endpoint_500_when_no_visuals_produced(enrich_library: dict,
                                               monkeypatch: pytest.MonkeyPatch):
    """Both binaries succeed but produce zero recognised visuals
    (e.g. SOLIDWORKS crashed silently mid-export). Endpoint returns
    500 with the captured subprocess logs so the operator can
    diagnose."""
    sldprt = enrich_library["sldprt"]
    async def _fake_status_ok(self):
        m = MagicMock()
        m.active_doc = MagicMock(type="Part", title=sldprt.name, path=str(sldprt))
        return m
    monkeypatch.setattr(server.BridgeClient, "status", _fake_status_ok)
    def _fake_run_empty(argv, timeout_s=180.0):
        return {"argv": list(argv), "rc": 0, "stdout": "ran but produced nothing", "stderr": "", "timedOut": False}
    monkeypatch.setattr(server, "_intake_enrich_run_subprocess_sync", _fake_run_empty)

    client = TestClient(server.app)
    r = client.post("/api/library/intake/enrich-visuals",
                    json={"partNumber": "1030034", "partPackageId": enrich_library["package_id"]})
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False
    assert body["filesAdded"] == []
    # Subprocess captures are still present so the operator can diagnose
    assert "ran but produced nothing" in body["extractorRun"]["stdout"]


# ── Single-flight lock ────────────────────────────────────────────────


def test_endpoint_409_when_concurrent_enrich_in_flight(enrich_library: dict,
                                                       monkeypatch: pytest.MonkeyPatch):
    """Two concurrent enrich runs -> 409 'one at a time'. Same gate
    pattern as /api/library/intake/promote."""
    import asyncio

    async def _acquire():
        await server._library_intake_enrich_lock.acquire()
    loop = asyncio.new_event_loop()
    loop.run_until_complete(_acquire())
    try:
        client = TestClient(server.app)
        r = client.post("/api/library/intake/enrich-visuals",
                        json={"partNumber": "1030034", "partPackageId": enrich_library["package_id"]})
        assert r.status_code == 409
        assert "in progress" in r.json()["detail"].lower()
    finally:
        server._library_intake_enrich_lock.release()
        loop.close()
