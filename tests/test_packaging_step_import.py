"""Offline STEP acceptance: runtime-generated CAD, real isolated OCP, bounded failures.

Set PACKAGING_STEP_TEST_PYTHON to the geometry venv Python, or provision the
worktree's .runtime/step-venv. PACKAGING_STEP_SAMPLE optionally enables the
read-only user assembly check; no proprietary fixture is copied into git.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading

import pytest

from ai_inspector.packaging_shipping import step_import as importer
from ai_inspector.packaging_shipping.step_import import StepImportError, StepRuntime, import_step


ROOT = Path(__file__).resolve().parents[1]
SIMPLE_STEP = b"ISO-10303-21;\nHEADER;ENDSEC;DATA;ENDSEC;END-ISO-10303-21;"
GENERATOR = r'''
import math,sys
from pathlib import Path
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.TopoDS import TopoDS_Compound,TopoDS_Shell,TopoDS_Solid
from OCP.TopLoc import TopLoc_Location
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.gp import gp_Ax1,gp_Dir,gp_Pln,gp_Pnt,gp_Trsf,gp_Vec

directory=Path(sys.argv[1])
def document():
    doc=TDocStd_Document(TCollection_ExtendedString('MDTV-XCAF'))
    XCAFDoc_DocumentTool.SetLengthUnit_s(doc,.001)
    return doc,XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

def save(doc,name,unit='MM'):
    writer=STEPCAFControl_Writer()
    assert Interface_Static.SetCVal_s('xstep.cascade.unit','MM')
    assert Interface_Static.SetCVal_s('write.step.unit',unit)
    assert writer.Transfer(doc,STEPControl_AsIs)
    assert writer.Write(str(directory/name)) == IFSelect_RetDone

for unit in ('MM','INCH','M'):
    doc,tool=document()
    tool.AddShape(BRepPrimAPI_MakeBox(25.4,50.8,76.2).Shape(),False)
    save(doc,unit+'.step',unit)

doc,tool=document()
part=tool.AddShape(BRepPrimAPI_MakeBox(10,20,30).Shape(),False)
TDataStd_Name.Set_s(part,TCollection_ExtendedString('Repeated measured block'))
sub=tool.NewShape()
TDataStd_Name.Set_s(sub,TCollection_ExtendedString('Nested pair'))
def location(x,y,z,angle=0):
    t=gp_Trsf()
    t.SetRotation(gp_Ax1(gp_Pnt(0,0,0),gp_Dir(0,0,1)),angle)
    t.SetTranslationPart(gp_Vec(x,y,z))
    return TopLoc_Location(t)
tool.AddComponent(sub,part,location(5,0,0))
tool.AddComponent(sub,part,location(25,0,0))
root=tool.NewShape()
tool.AddComponent(root,sub,location(100,200,0,math.pi/2))
tool.AddComponent(root,sub,location(-50,0,50))
tool.UpdateAssemblies()
save(doc,'nested.step')

face=BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0,0,0),gp_Dir(0,0,1)),0,10,0,20).Face()
doc,tool=document()
tool.AddShape(face,False)
save(doc,'open.step')
doc,tool=document()
compound=TopoDS_Compound()
builder=BRep_Builder()
builder.MakeCompound(compound)
builder.Add(compound,BRepPrimAPI_MakeBox(10,20,30).Shape())
builder.Add(compound,face)
tool.AddShape(compound,False)
save(doc,'mixed.step')
doc,tool=document()
shell=TopoDS_Shell()
builder.MakeShell(shell)
builder.Add(shell,face)
solid=TopoDS_Solid()
builder.MakeSolid(solid)
builder.Add(solid,shell)
tool.AddShape(solid,False)
save(doc,'invalid.step')
'''


@pytest.fixture(scope="module")
def geometry_python():
    configured = os.environ.get("PACKAGING_STEP_TEST_PYTHON")
    python = Path(configured) if configured else ROOT / ".runtime" / "step-venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        if configured:
            pytest.fail("PACKAGING_STEP_TEST_PYTHON must point to an installed geometry runtime")
        pytest.skip("Optional geometry runtime not installed; run tools/setup_packaging_geometry.py")
    return python.resolve()


@pytest.fixture(scope="module")
def cad(geometry_python, tmp_path_factory):
    folder = tmp_path_factory.mktemp("cad")
    runtime = StepRuntime(geometry_python, folder)
    result = subprocess.run([str(geometry_python), "-I", "-B", "-c", GENERATOR, str(folder)],
        cwd=folder, env=importer._environment(runtime, folder), capture_output=True,
        timeout=60, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return {file.stem: file.read_bytes() for file in folder.glob("*.step")}


@pytest.fixture
def runtime(tmp_path):
    return StepRuntime(Path(sys.executable).resolve(), tmp_path / "jobs")


def run(data, runtime, cancel_event=None):
    return asyncio.run(import_step(data, runtime=runtime, cancel_event=cancel_event))


def assert_clean(runtime):
    assert not runtime.work_root.exists() or list(runtime.work_root.iterdir()) == []


def assert_unknown(metadata):
    assert metadata["physical_evidence"] == {
        "volume_basis": "closed_solid_brep", "material": None,
        "density_kg_m3": None, "mass_kg": None, "mass_basis": "unknown"}
    assert "assembly_constraints_not_imported" in metadata["warnings"]


def glb_scene(result):
    import trimesh
    return trimesh.load_scene(BytesIO(result.glb_bytes), file_type="glb", process=False)


@pytest.mark.parametrize("unit,source_name", [("MM", "millimetre"), ("INCH", "inch"), ("M", "metre")])
def test_declared_units_exact_volume_and_metre_glb(geometry_python, cad, tmp_path, unit, source_name):
    runtime = StepRuntime(geometry_python, tmp_path / "jobs")
    data = cad[unit]
    result = run(data, runtime)
    metadata = result.metadata
    assert metadata["format"] == "step"
    assert metadata["source_revision"] == hashlib.sha256(data).hexdigest()
    assert metadata["dimensions_m"] == pytest.approx([.0254, .0508, .0762], abs=1e-9)
    assert metadata["volume_m3"] == pytest.approx(.0254 * .0508 * .0762, rel=1e-9)
    assert metadata["solid_count"] == 1
    assert metadata["units"]["source_length_units"] == [source_name]
    assert metadata["units"]["authority"] == "STEP_declared_units_via_OCCT"
    assert metadata["units"]["coordinate_system"] == "Y-up"
    assert glb_scene(result).extents == pytest.approx(metadata["dimensions_m"], abs=1e-8)
    assert_unknown(metadata)
    metadata["physical_evidence"]["density_kg_m3"] = 1000
    assert result.metadata["physical_evidence"]["density_kg_m3"] is None
    assert_clean(runtime)


def test_nested_rotated_repeated_instances_survive_measurement_and_export(geometry_python, cad, tmp_path):
    runtime = StepRuntime(geometry_python, tmp_path / "jobs")
    result = run(cad["nested"], runtime)
    metadata = result.metadata
    assert metadata["solid_count"] == 4 and metadata["root_count"] == 1
    assert metadata["bounds_m"][0] == pytest.approx([-.045, 0, 0], abs=1e-9)
    assert metadata["bounds_m"][1] == pytest.approx([.1, .235, .08], abs=1e-9)
    assert metadata["volume_m3"] == pytest.approx(24000e-9, rel=1e-9)
    scene = glb_scene(result)
    assert len(scene.graph.nodes_geometry) == 4
    assert scene.bounds[0] == pytest.approx(metadata["bounds_m"][0], abs=1e-8)
    assert scene.bounds[1] == pytest.approx(metadata["bounds_m"][1], abs=1e-8)
    # Shared meshes are allowed, but every transformed instance must be present.
    assert scene.extents == pytest.approx([.145, .235, .08], abs=1e-8)
    assert_unknown(metadata)
    assert_clean(runtime)


@pytest.mark.parametrize("fixture", ["open", "mixed", "invalid"])
def test_open_or_invalid_geometry_does_not_claim_physical_volume(geometry_python, cad, tmp_path, fixture):
    runtime = StepRuntime(geometry_python, tmp_path / "jobs")
    with pytest.raises(StepImportError) as error:
        run(cad[fixture], runtime)
    assert error.value.code in {"step_open_geometry", "step_invalid"}
    assert_clean(runtime)


@pytest.mark.parametrize("limit,value", [("max_faces", 5), ("max_solids", 3),
                                       ("max_triangles", 2), ("max_dimension_m", .01)])
def test_real_geometry_limits(geometry_python, cad, tmp_path, limit, value):
    runtime = replace(StepRuntime(geometry_python, tmp_path / "jobs"), **{limit: value})
    with pytest.raises(StepImportError) as error:
        run(cad["nested"], runtime)
    assert error.value.code == "step_geometry_limit"
    assert_clean(runtime)


def test_selected_user_sample_is_one_pair_and_source_is_unchanged(geometry_python, tmp_path):
    configured = os.environ.get("PACKAGING_STEP_SAMPLE")
    if not configured:
        pytest.skip("Set PACKAGING_STEP_SAMPLE for the optional read-only proprietary assembly check")
    sample = Path(configured)
    before = sample.read_bytes()
    runtime = StepRuntime(geometry_python, tmp_path / "jobs")
    result = run(before, runtime)
    metadata = result.metadata
    assert metadata["solid_count"] == 5
    assert metadata["dimensions_m"] == pytest.approx([.508, .029743171352155, .079254559727021], abs=1e-9)
    assert metadata["volume_m3"] == pytest.approx(362637.479651e-9, rel=1e-9)
    scene = glb_scene(result)
    assert len(scene.graph.nodes_geometry) == 5
    assert scene.extents == pytest.approx(metadata["dimensions_m"], abs=.0002)
    assert sample.read_bytes() == before
    assert_unknown(metadata)
    assert_clean(runtime)


@pytest.mark.parametrize("data,code", [(b"", "step_upload_limit"), (b"/private/model.step", "step_invalid"),
    (b"not STEP", "step_invalid"), (SIMPLE_STEP.replace(b"HEADER", b"HE\x00ADER"), "step_invalid")])
def test_bytes_only_preflight(runtime, data, code):
    with pytest.raises(StepImportError) as error:
        run(data, runtime)
    assert error.value.code == code
    assert_clean(runtime)


def test_upload_cap_and_no_path_input(runtime):
    for data in (Path("input.step"), bytearray(SIMPLE_STEP), SIMPLE_STEP * 2):
        with pytest.raises(StepImportError, match="upload"):
            run(data, replace(runtime, max_input_bytes=len(SIMPLE_STEP)))
    assert_clean(runtime)


@pytest.mark.parametrize("token", ["DOCUMENT_FILE", "EXTERNAL_SOURCE", "REFERENCE",
    "PRODUCT_DEFINITION_WITH_ASSOCIATED_DOCUMENTS", "APPLIED_EXTERNAL_IDENTIFICATION_ASSIGNMENT"])
def test_external_file_admission(runtime, token):
    data = SIMPLE_STEP.replace(b"DATA;", b"DATA;#1=" + token.encode() + b"('file:///private/secret.step');")
    with pytest.raises(StepImportError) as error:
        run(data, runtime)
    assert error.value.code == "step_external_reference"
    assert "secret" not in error.value.message
    assert_clean(runtime)


def test_names_and_comments_are_not_external_references(runtime):
    data = SIMPLE_STEP.replace(b"DATA;", b"DATA;/* DOCUMENT_FILE */#1=PRODUCT('EXTERNAL_SOURCE','a''b','',());")
    importer._preflight(data, runtime)


def test_a_worker_without_its_geometry_component_is_reported_as_unavailable(runtime):
    """The test interpreter has no OCP: STEP is unavailable in this installation, not a bad or unsafe file."""
    with pytest.raises(StepImportError) as error:
        run(SIMPLE_STEP, runtime)
    assert (error.value.code, error.value.status_code) == ("step_runtime_unavailable", 503)
    assert "not available in this installation" in error.value.message
    assert "Manual dimensions still work" in error.value.message and "safely" not in error.value.message
    assert_clean(runtime)


def test_explicit_runtime_configuration_and_no_credentials(runtime, monkeypatch):
    with pytest.raises(StepImportError) as error:
        StepRuntime.from_environment({})
    assert error.value.code == "step_runtime_unavailable"
    with pytest.raises(StepImportError):
        StepRuntime(Path("python.exe"))
    configured = StepRuntime.from_environment({
        "INSPECTORPRO_PACKAGING_GEOMETRY_PYTHON": str(runtime.python_executable),
        "INSPECTORPRO_PACKAGING_GEOMETRY_TMP": str(runtime.work_root)})
    assert configured.python_executable == runtime.python_executable
    for key in ("OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "PYTHONPATH", "HTTP_PROXY", "PIP_INDEX_URL"):
        monkeypatch.setenv(key, "NEVER_INHERIT")
    environment = importer._environment(runtime, runtime.work_root)
    assert "NEVER_INHERIT" not in json.dumps(environment)
    assert environment["HOME"] == str(runtime.work_root)


@pytest.fixture
def fake_worker(tmp_path, monkeypatch):
    processes = []
    original = asyncio.create_subprocess_exec

    async def observe(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", observe)

    def install(program):
        worker = tmp_path / "fixture_worker.py"
        worker.write_text(program, encoding="ascii")
        monkeypatch.setattr(importer, "_WORKER", worker)
        return processes

    return install


@pytest.mark.parametrize("mode", ["timeout", "event", "task", "repeated_task"])
def test_timeout_and_cancellation_reap_worker_and_remove_files(runtime, fake_worker, mode):
    processes = fake_worker("import time\ntime.sleep(60)\n")
    runtime = replace(runtime, timeout_seconds=.3 if mode == "timeout" else 20)

    async def exercise():
        event = threading.Event()
        task = asyncio.create_task(import_step(SIMPLE_STEP, runtime=runtime, cancel_event=event))
        while not processes:
            await asyncio.sleep(.01)
        if mode == "event":
            event.set()
        elif mode in {"task", "repeated_task"}:
            task.cancel()
            if mode == "repeated_task":
                asyncio.get_running_loop().call_later(.001, task.cancel)
        if mode == "timeout":
            with pytest.raises(StepImportError) as error:
                await task
            assert error.value.code == "step_timeout"
        else:
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(exercise())
    assert processes and all(process.returncode is not None for process in processes)
    assert_clean(runtime)


def test_cancelled_before_start_does_not_launch(runtime, fake_worker):
    processes = fake_worker("raise RuntimeError('must not start')")
    event = threading.Event()
    event.set()
    with pytest.raises(asyncio.CancelledError):
        run(SIMPLE_STEP, runtime, event)
    assert processes == []
    assert_clean(runtime)


def test_cancellation_during_process_creation_recovers_and_reaps_handle(runtime, fake_worker, monkeypatch):
    processes = fake_worker("import time\ntime.sleep(60)")
    original = asyncio.create_subprocess_exec

    async def exercise():
        spawned, release = asyncio.Event(), asyncio.Event()

        async def delayed(*args, **kwargs):
            process = await original(*args, **kwargs)
            spawned.set()
            await release.wait()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
        task = asyncio.create_task(import_step(SIMPLE_STEP, runtime=runtime))
        await spawned.wait()
        task.cancel()
        await asyncio.sleep(.01)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert processes and all(process.returncode is not None for process in processes)
    assert_clean(runtime)


def test_oversized_glb_at_worker_exit_is_rejected(runtime, fake_worker):
    value = metadata()
    value["source_revision"] = hashlib.sha256(SIMPLE_STEP).hexdigest()
    program = ("from pathlib import Path\n"
               "Path('result.json').write_text(" + repr(json.dumps(value)) + ")\n"
               "Path('model.glb').write_bytes(b'x'*4096)\n")
    processes = fake_worker(program)
    with pytest.raises(StepImportError) as error:
        run(SIMPLE_STEP, replace(runtime, max_glb_bytes=2048))
    assert error.value.code == "step_output_limit"
    assert processes and all(process.returncode is not None for process in processes)
    assert_clean(runtime)


def test_cancellation_arriving_only_during_cleanup_is_not_swallowed(runtime, fake_worker, monkeypatch):
    processes = fake_worker("pass")
    original = importer._stop

    async def exercise():
        stopped, release = asyncio.Event(), asyncio.Event()

        async def delayed(process, readers):
            await original(process, readers)
            stopped.set()
            await release.wait()

        monkeypatch.setattr(importer, "_stop", delayed)
        task = asyncio.create_task(import_step(SIMPLE_STEP, runtime=runtime))
        await stopped.wait()
        task.cancel()
        await asyncio.sleep(.01)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert processes and all(process.returncode is not None for process in processes)
    assert_clean(runtime)


def test_exporter_temporary_file_disappearing_during_size_check_is_safe(runtime, fake_worker, monkeypatch):
    processes = fake_worker("from pathlib import Path\nimport time\n"
        "Path('model.bin.tmp').write_bytes(b'x')\ntime.sleep(.2)\n"
        "Path('result.json').write_text('{\"error\":\"step_invalid\"}')\nraise SystemExit(2)")
    original = Path.lstat
    raced = []

    def disappearing(path, *args, **kwargs):
        if path.name == "model.bin.tmp" and not raced:
            raced.append(path)
            path.unlink()
            raise FileNotFoundError("Exporter removed its temporary file")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", disappearing)
    with pytest.raises(StepImportError) as error:
        run(SIMPLE_STEP, runtime)
    assert raced and error.value.code == "step_invalid"
    assert processes and all(process.returncode is not None for process in processes)
    assert_clean(runtime)


@pytest.mark.parametrize("program,code", [
    ("import sys,time\nsys.stdout.write('PRIVATE' * 20000);sys.stdout.flush();time.sleep(5)", "step_output_limit"),
    ("from pathlib import Path\nPath('result.json').write_bytes(b'x'*20000)", "step_worker_failed"),
    ("from pathlib import Path\nPath('result.json').write_text('{\"error\":\"PRIVATE_PATH\"}');raise SystemExit(2)", "step_worker_failed"),
    ("from pathlib import Path\nPath('result.json').write_text('{\"error\":\"step_invalid\"}');raise SystemExit(2)", "step_invalid"),
    ("raise SystemExit(3)", "step_worker_failed"),
])
def test_worker_failure_and_output_caps_are_sanitized(runtime, fake_worker, program, code):
    processes = fake_worker(program)
    with pytest.raises(StepImportError) as error:
        run(SIMPLE_STEP, runtime)
    assert error.value.code in {code, "step_output_limit"}
    assert "PRIVATE" not in error.value.message
    assert processes and all(process.returncode is not None for process in processes)
    assert_clean(runtime)


def metadata():
    return {"format": "step", "dimensions_m": [.01, .02, .03], "bounds_m": [[0, 0, 0], [.01, .02, .03]],
        "volume_m3": .000006, "solid_count": 1, "root_count": 1, "face_count": 6, "triangle_count": 12,
        "source_revision": "a" * 64, "physical_evidence": deepcopy(importer._PHYSICAL),
        "warnings": list(importer._WARNINGS),
        "units": {"authority": "STEP_declared_units_via_OCCT", "source_length_units": ["millimetre"],
            "kernel_length_unit": "mm", "kernel_meters_per_unit": .001, "output_length_unit": "m",
            "output_meters_per_unit": 1.0, "coordinate_system": "Y-up"}}


@pytest.mark.parametrize("mutation", ["density", "mass", "nan", "negative", "revision", "path",
    "warning", "count", "bounds", "units", "boolean_unit", "huge_count"])
def test_untrusted_worker_metadata_cannot_become_physical_evidence(runtime, mutation):
    value = metadata()
    if mutation == "density":
        value["physical_evidence"]["density_kg_m3"] = 1180
    elif mutation == "mass":
        value["physical_evidence"]["mass_kg"] = 1
    elif mutation == "nan":
        value["dimensions_m"][0] = float("nan")
    elif mutation == "negative":
        value["volume_m3"] = -1
    elif mutation == "revision":
        value["source_revision"] = "b" * 64
    elif mutation == "path":
        value["path"] = "PRIVATE_PATH"
    elif mutation == "warning":
        value["warnings"] = ["PRIVATE_PATH"]
    elif mutation == "count":
        value["solid_count"] = True
    elif mutation == "bounds":
        value["bounds_m"][1][0] = .5
    elif mutation == "units":
        value["units"]["source_length_units"] = ["made-up"]
    elif mutation == "boolean_unit":
        value["units"]["output_meters_per_unit"] = True
    else:
        value["triangle_count"] = 100000000
    with pytest.raises(StepImportError) as error:
        importer._metadata(json.dumps(value).encode(), "a" * 64, runtime)
    assert error.value.code == "step_result_invalid"
    assert "PRIVATE" not in error.value.message


def test_duplicate_metadata_fields_rejected(runtime):
    raw = json.dumps(metadata()).encode().replace(b'"format": "step"', b'"format":"step","format":"step"')
    with pytest.raises(StepImportError):
        importer._metadata(raw, "a" * 64, runtime)


def _small_glb(extra=None):
    document = {"asset": {"version": "2.0"}, "nodes": [{"mesh": 0}], "meshes": [{}]}
    document.update(extra or {})
    encoded = json.dumps(document).encode()
    encoded += b" " * (-len(encoded) % 4)
    return struct.pack("<4sII", b"glTF", 2, 28 + len(encoded)) + struct.pack("<II", len(encoded), 0x4E4F534A) + encoded + struct.pack("<II", 0, 0x004E4942)


@pytest.mark.parametrize("extra", [{"animations": [{}]}, {"skins": [{}]},
    {"buffers": [{"uri": "file:///private/secret"}]}, {"extensionsRequired": ["unsafe"]},
    {"nodes": []}, {"asset": {"version": "1.0"}}])
def test_glb_must_be_static_bounded_and_self_contained(runtime, extra):
    with pytest.raises(StepImportError) as error:
        importer._glb(_small_glb(extra), runtime)
    assert error.value.code == "step_result_invalid"


def test_bounded_concurrency_rejects_without_launch(runtime, fake_worker):
    processes = fake_worker("raise RuntimeError('must not start')")
    assert importer._SLOTS.acquire(blocking=False)
    assert importer._SLOTS.acquire(blocking=False)
    try:
        with pytest.raises(StepImportError) as error:
            run(SIMPLE_STEP, runtime)
        assert error.value.code == "step_busy"
        assert processes == []
    finally:
        importer._SLOTS.release()
        importer._SLOTS.release()
    assert_clean(runtime)
