"""Private OCP worker; run only by step_import in a new disposable directory."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys
import sysconfig

# -S keeps sitecustomize/.pth out of the disposable worker. Python 3.11's
# no-site venv prefix points at the base interpreter, so use the selected exe.
if __name__ == '__main__':
    executable = Path(sys.executable)
    prefix = executable.parent.parent if executable.parent.name.lower() in {'scripts', 'bin'} else executable.parent
    for key in ('purelib', 'platlib'):
        dependency = sysconfig.get_path(key, vars={'base': str(prefix), 'platbase': str(prefix)})
        if dependency not in sys.path:
            sys.path.append(dependency)


_JOB = None


class Rejected(Exception):
    pass


def _limits(limits):
    """Fail closed if OS-enforced memory and CPU limits cannot be installed."""
    global _JOB
    if os.name != "nt":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (limits["memory_limit_bytes"],) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (limits["cpu_seconds"],) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits["max_glb_bytes"],) * 2)
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        return
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                    ("processes", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                    ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(key, ctypes.c_uint64) for key in (
            "read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t),
                    ("peak_job", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    job = kernel.CreateJobObjectW(None, None)
    info = Extended()
    info.basic.flags = 0x2 | 0x8 | 0x100 | 0x2000  # CPU, process count, memory, kill-on-close.
    info.basic.process_time = limits["cpu_seconds"] * 10000000
    info.basic.processes = 1
    info.process_memory = limits["memory_limit_bytes"]
    if (not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
            or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess())):
        if job:
            kernel.CloseHandle(job)
        raise Rejected("step_resource_limits_unavailable")
    _JOB = job


def _unit_name(value):
    normalized = value.strip().lower()
    aliases = {"millimeter": "millimetre", "millimetre": "millimetre", "mm": "millimetre",
               "centimeter": "centimetre", "centimetre": "centimetre", "cm": "centimetre",
               "meter": "metre", "metre": "metre", "m": "metre", "inch": "inch", "in": "inch",
               "foot": "foot", "ft": "foot", "micrometer": "micrometre", "micrometre": "micrometre"}
    if normalized not in aliases:
        raise Rejected("step_units_unknown")
    return aliases[normalized]


def convert(limits):
    if importlib.metadata.version("cadquery-ocp-novtk") != "7.9.3.1.1":
        raise Rejected("step_runtime_unavailable")
    from OCP.Bnd import Bnd_Box
    from OCP.BRep import BRep_Tool
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepCheck import BRepCheck_Analyzer, BRepCheck_NoError, BRepCheck_Shell
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.GProp import GProp_GProps
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.Message import Message_ProgressRange
    from OCP.RWGltf import RWGltf_CafWriter
    from OCP.RWMesh import RWMesh_CoordinateSystem_Yup
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.STEPConstruct import STEPConstruct_ExternRefs
    from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
    from OCP.TColStd import TColStd_IndexedDataMapOfStringString, TColStd_SequenceOfAsciiString
    from OCP.TDF import TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_COMPSOLID, TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS, TopoDS_Iterator
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    source = Path("input.step")
    if not 0 < source.stat().st_size <= limits["max_input_bytes"] or source.is_symlink():
        raise Rejected("step_invalid")
    if Path("model.glb").exists() or Path("result.json").exists():
        raise Rejected("step_invalid")
    with source.open("rb") as stream:
        revision = hashlib.file_digest(stream, "sha256").hexdigest()
    reader = STEPCAFControl_Reader()
    if not Interface_Static.SetCVal_s("xstep.cascade.unit", "MM"):
        raise Rejected("step_units_unknown")
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    reader.SetMatMode(False)
    reader.SetPropsMode(False)
    reader.SetGDTMode(False)
    reader.SetSHUOMode(False)
    reader.SetViewMode(False)
    reader.SetMetaMode(False)
    reader.SetProductMetaMode(False)
    if reader.ReadFile(str(source.resolve())) != IFSelect_RetDone:
        raise Rejected("step_invalid")
    # OCCT's transfer would otherwise resolve external references on disk.
    # Inspect the parsed model before Transfer, in addition to upload preflight.
    references = STEPConstruct_ExternRefs(reader.Reader().WS())
    references.LoadExternRefs()
    if references.NbExternRefs():
        raise Rejected("step_external_reference")
    lengths, angles, solid_angles = (TColStd_SequenceOfAsciiString() for _ in range(3))
    reader.Reader().FileUnits(lengths, angles, solid_angles)
    if not 1 <= lengths.Length() <= 8:
        raise Rejected("step_units_unknown")
    units = sorted({_unit_name(lengths.Value(i).ToCString()) for i in range(1, lengths.Length() + 1)})
    reader.Reader().SetSystemLengthUnit(1.0)
    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    if not reader.Transfer(doc):
        raise Rejected("step_invalid")
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    labels = TDF_LabelSequence()
    tool.GetFreeShapes(labels)
    if not 1 <= labels.Length() <= limits["max_nodes"]:
        raise Rejected("step_geometry_limit")
    roots = [tool.GetShape_s(labels.Value(i)) for i in range(1, labels.Length() + 1)]
    pending = [(shape, 0) for shape in roots]
    solids, visits = [], 0
    while pending:
        shape, depth = pending.pop()
        visits += 1
        if depth > limits["max_depth"] or visits > limits["max_nodes"]:
            raise Rejected("step_geometry_limit")
        if shape.IsNull():
            raise Rejected("step_invalid")
        kind = shape.ShapeType()
        if kind == TopAbs_SOLID:
            solids.append(shape)
            if len(solids) > limits["max_solids"]:
                raise Rejected("step_geometry_limit")
        elif kind in (TopAbs_COMPOUND, TopAbs_COMPSOLID):
            # Cumulative locations/orientations preserve every placed occurrence,
            # including repeated instances of the same underlying shape.
            children = TopoDS_Iterator(shape, True, True)
            while children.More():
                pending.append((children.Value(), depth + 1))
                if len(pending) + visits > limits["max_nodes"]:
                    raise Rejected("step_geometry_limit")
                children.Next()
        else:
            raise Rejected("step_open_geometry")
    if not solids:
        raise Rejected("step_open_geometry")
    volume_mm3 = 0.0
    face_count = 0
    for solid in solids:
        if not BRepCheck_Analyzer(solid).IsValid():
            raise Rejected("step_invalid")
        shells = TopExp_Explorer(solid, TopAbs_SHELL)
        shell_count = 0
        while shells.More():
            shell_count += 1
            shell = TopoDS.Shell_s(shells.Current())
            if BRepCheck_Shell(shell).Closed() != BRepCheck_NoError or not BRep_Tool.IsClosed_s(shell):
                raise Rejected("step_open_geometry")
            shells.Next()
        if not shell_count:
            raise Rejected("step_open_geometry")
        properties = GProp_GProps()
        BRepGProp.VolumeProperties_s(solid, properties, True, False, False)
        volume = properties.Mass()
        if not math.isfinite(volume) or volume <= 0:
            raise Rejected("step_invalid")
        volume_mm3 += volume
        faces = TopExp_Explorer(solid, TopAbs_FACE)
        while faces.More():
            face_count += 1
            if face_count > limits["max_faces"]:
                raise Rejected("step_geometry_limit")
            faces.Next()
    box = Bnd_Box()
    for root in roots:
        BRepBndLib.AddOptimal_s(root, box, False, False)
    if box.IsVoid() or box.IsOpen():
        raise Rejected("step_invalid")
    bounds = list(box.Get())
    dimensions = [(bounds[i + 3] - bounds[i]) * 0.001 for i in range(3)]
    if (not all(math.isfinite(v) and abs(v) <= 10000000 for v in bounds)
            or not all(1e-9 <= d <= limits["max_dimension_m"] for d in dimensions)):
        raise Rejected("step_geometry_limit")
    triangle_count = 0
    for root in roots:
        mesher = BRepMesh_IncrementalMesh(root, 0.2, False, 0.25, False)
        if not mesher.IsDone():
            raise Rejected("step_mesh_failed")
        faces = TopExp_Explorer(root, TopAbs_FACE)
        while faces.More():
            triangulation = BRep_Tool.Triangulation_s(TopoDS.Face_s(faces.Current()), TopLoc_Location())
            if triangulation is None or triangulation.NbTriangles() <= 0:
                raise Rejected("step_mesh_failed")
            triangle_count += triangulation.NbTriangles()
            if triangle_count > limits["max_triangles"]:
                raise Rejected("step_geometry_limit")
            faces.Next()
    writer = RWGltf_CafWriter(TCollection_AsciiString(str(Path("model.glb").resolve())), True)
    writer.SetMergeFaces(True)
    converter = writer.ChangeCoordinateSystemConverter()
    converter.SetInputCoordinateSystem(RWMesh_CoordinateSystem_Yup)
    converter.SetOutputCoordinateSystem(RWMesh_CoordinateSystem_Yup)
    converter.SetInputLengthUnit(0.001)
    converter.SetOutputLengthUnit(1.0)
    if not writer.Perform(doc, TColStd_IndexedDataMapOfStringString(), Message_ProgressRange()):
        raise Rejected("step_export_failed")
    if not 0 < Path("model.glb").stat().st_size <= limits["max_glb_bytes"]:
        raise Rejected("step_geometry_limit")
    return {
        "format": "step", "source_revision": revision, "dimensions_m": dimensions,
        "bounds_m": [[v * 0.001 for v in bounds[:3]], [v * 0.001 for v in bounds[3:]]],
        "volume_m3": volume_mm3 * 1e-9, "solid_count": len(solids), "root_count": len(roots),
        "face_count": face_count, "triangle_count": triangle_count,
        "physical_evidence": {"volume_basis": "closed_solid_brep", "material": None,
            "density_kg_m3": None, "mass_kg": None, "mass_basis": "unknown"},
        "warnings": ["material_density_unknown", "assembly_constraints_not_imported",
                     "solid_volume_sum_not_boolean_union"],
        "units": {"authority": "STEP_declared_units_via_OCCT", "source_length_units": units,
            "kernel_length_unit": "mm", "kernel_meters_per_unit": 0.001,
            "output_length_unit": "m", "output_meters_per_unit": 1.0, "coordinate_system": "Y-up"},
    }


def main():
    try:
        limits = json.loads(sys.argv[1])
        try:
            _limits(limits)
        except Exception:
            raise Rejected("step_resource_limits_unavailable") from None
        result = convert(limits)
        encoded = json.dumps(result, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > limits["max_metadata_bytes"]:
            raise Rejected("step_geometry_limit")
        status = 0
    except Rejected as exc:
        encoded = json.dumps({"error": str(exc)}).encode("ascii")
        status = 2
    except (ImportError, importlib.metadata.PackageNotFoundError):
        encoded = b'{"error":"step_runtime_unavailable"}'
        status = 2
    except BaseException:
        encoded = b'{"error":"step_worker_failed"}'
        status = 2
    with Path("result.json").open("xb") as stream:
        stream.write(encoded)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
