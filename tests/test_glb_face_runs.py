"""CAD faces in library GLBs (docs/assembly-face-selection-plan.md, F0): the re-exported machines carry, on every
mesh, the runs of triangles that make each SOLIDWORKS face, and the runs cover every triangle once, in order."""
from __future__ import annotations

import json
from pathlib import Path
import struct

import pytest

REPO = Path(__file__).resolve().parents[1]
LIBRARY = REPO / "generated" / "industrial_assets" / "local_library"
# Re-exported with face runs on 2026-10-26.
FACE_MACHINES = ("asset-abb-irb6650-robot", "asset-mobile-lift-mmle-50d", "asset-forklift-telescopic-red",
                 "asset-fanuc-14tes2-robot")
KINDS = {"plane", "cylinder", "cone", "sphere", "torus", "other"}


def _gltf(path: Path) -> dict:
    with path.open("rb") as stream:
        magic, version, _ = struct.unpack("<III", stream.read(12))
        assert (magic, version) == (0x46546C67, 2)
        length, kind = struct.unpack("<II", stream.read(8))
        assert kind == 0x4E4F534A
        return json.loads(stream.read(length))


def _artifact(asset_id: str) -> Path:
    catalog = json.loads((LIBRARY / "catalog.json").read_text(encoding="utf-8"))
    row = next(row for row in catalog["assets"] if row["assetId"] == asset_id)
    return REPO / row["artifact"]


def face_run_problems(document: dict) -> list:
    """What is wrong with a GLB's face runs; empty when every mesh has runs tiling its triangles."""
    problems = []
    for index, mesh in enumerate(document.get("meshes") or []):
        for primitive in mesh.get("primitives") or []:
            extras = (primitive.get("extras") or {}).get("inspectorpro")
            if not extras:
                problems.append(f"mesh {index}: no face runs")
                continue
            if extras.get("faceVersion") != 1:
                problems.append(f"mesh {index}: faceVersion {extras.get('faceVersion')!r}")
            kinds, features = extras.get("faceKinds") or [], extras.get("faceFeatures") or []
            if not set(kinds) <= KINDS:
                problems.append(f"mesh {index}: unknown kinds {sorted(set(kinds) - KINDS)}")
            triangles = document["accessors"][primitive["indices"]]["count"] // 3
            expected = 0
            for first, count, kind, feature, radius in extras.get("faces") or []:
                if first != expected or count <= 0:
                    problems.append(f"mesh {index}: a run starts at {first}, expected {expected}")
                    break
                if not 0 <= kind < len(kinds) or not 0 <= feature < len(features) or radius < 0:
                    problems.append(f"mesh {index}: a bad face row at triangle {first}")
                    break
                expected = first + count
            else:
                if expected != triangles:
                    problems.append(f"mesh {index}: runs cover {expected} of {triangles} triangles")
    return problems


def test_the_check_finds_gaps_and_overlaps() -> None:
    def document(faces):
        extras = {"inspectorpro": {"faceVersion": 1, "faceKinds": ["plane", "cylinder"], "faceFeatures": ["Boss"],
                                   "faces": faces}}
        return {"accessors": [{"count": 30}], "meshes": [{"primitives": [{"indices": 0, "extras": extras}]}]}

    assert face_run_problems(document([[0, 4, 0, 0, 0], [4, 6, 1, 0, 0.012]])) == []
    assert face_run_problems(document([[0, 4, 0, 0, 0], [5, 5, 1, 0, 0]])) == ["mesh 0: a run starts at 5, expected 4"]
    assert face_run_problems(document([[0, 4, 0, 0, 0], [4, 5, 1, 0, 0]])) == ["mesh 0: runs cover 9 of 10 triangles"]
    assert face_run_problems(document([[0, 10, 2, 0, 0]])) == ["mesh 0: a bad face row at triangle 0"]
    assert face_run_problems({"accessors": [{"count": 3}], "meshes": [{"primitives": [{"indices": 0}]}]}) \
        == ["mesh 0: no face runs"]


@pytest.mark.parametrize("asset_id", FACE_MACHINES)
def test_re_exported_machines_carry_face_runs(asset_id: str) -> None:
    document = _gltf(_artifact(asset_id))
    assert document["asset"].get("generator") == "SolidWorksExtractor"
    assert face_run_problems(document) == []
    faces = [row for mesh in document["meshes"] for row in mesh["primitives"][0]["extras"]["inspectorpro"]["faces"]]
    assert len(faces) > 100


def test_the_exporter_writes_face_runs() -> None:
    source = (REPO / "SolidWorksExtractor" / "Services" / "GlbExporter.cs").read_text(encoding="utf-8")
    assert "AppendFaceExtras(sb, meshes[i]);" in source
    assert source.count("faces.Add(DescribeFace(face,") == 3
