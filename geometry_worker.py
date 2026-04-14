"""Geometry Diff Worker — separate FastAPI service running in conda geo-env.
Computes solid-body boolean diffs between STEP revision pairs.
Listens on localhost:8001. Main server proxies to this."""

import json
import time
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.StlAPI import StlAPI_Writer
from OCC.Core.IFSelect import IFSelect_RetDone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("geometry-worker")

app = FastAPI(title="Geometry Diff Worker")


class DiffRequest(BaseModel):
    step_a: str
    step_b: str
    output_dir: str
    part_number: str
    revA: str
    revB: str


def _load_step(path: str):
    """Load a STEP file and return the shape."""
    reader = STEPControl_Reader()
    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"Failed to read STEP: {path} (status={status})")
    reader.TransferRoots()
    return reader.OneShape()


def _count_solids(shape) -> int:
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    count = 0
    while explorer.More():
        count += 1
        explorer.Next()
    return count


def _get_volume(shape) -> float:
    props = GProp_GProps()
    brepgprop.VolumeProperties(shape, props)
    return props.Mass()


def _get_bbox(shape):
    box = Bnd_Box()
    brepbndlib.Add(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return {
        "min": [round(xmin, 3), round(ymin, 3), round(zmin, 3)],
        "max": [round(xmax, 3), round(ymax, 3), round(zmax, 3)],
        "extents": [round(xmax - xmin, 3), round(ymax - ymin, 3), round(zmax - zmin, 3)],
    }


def _get_centroid(shape):
    box = Bnd_Box()
    brepbndlib.Add(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return [round((xmin + xmax) / 2, 3), round((ymin + ymax) / 2, 3), round((zmin + zmax) / 2, 3)]


def _extract_change_regions(shape, change_type: str) -> list:
    """Extract per-solid change regions with centroid + bbox.

    Boolean diff results can contain multiple disconnected solids. Exporting each
    solid separately lets downstream drawing projection show advisory regions
    instead of only a single centroid dot.
    """
    regions = []
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        solid = explorer.Current()
        volume = _get_volume(solid)
        if abs(volume) > 0.001:
            regions.append({
                "type": change_type,
                "centroid": _get_centroid(solid),
                "bbox": _get_bbox(solid),
                "volume_mm3": round(volume, 3),
            })
        explorer.Next()

    if not regions:
        total_volume = _get_volume(shape)
        if abs(total_volume) > 0.001:
            regions.append({
                "type": change_type,
                "centroid": _get_centroid(shape),
                "bbox": _get_bbox(shape),
                "volume_mm3": round(total_volume, 3),
            })

    regions.sort(key=lambda r: (-abs(r.get("volume_mm3", 0.0)), r["type"]))
    for idx, region in enumerate(regions, start=1):
        region["region_index"] = idx
    return regions


def _save_stl(shape, path: str, linear_deflection: float = 0.1):
    mesh = BRepMesh_IncrementalMesh(shape, linear_deflection)
    mesh.Perform()
    writer = StlAPI_Writer()
    writer.Write(shape, path)


def _validate_import(shape, sidecar_path: Optional[str], label: str) -> list:
    """Validate imported shape against sidecar metadata. Returns list of warnings."""
    warnings = []
    if not sidecar_path or not Path(sidecar_path).exists():
        return warnings

    with open(sidecar_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # Body count
    expected_bodies = meta.get("body_count")
    if expected_bodies is not None:
        actual_bodies = _count_solids(shape)
        if actual_bodies != expected_bodies:
            warnings.append(f"{label}: body count mismatch (expected {expected_bodies}, got {actual_bodies})")

    # Volume
    expected_vol = meta.get("volume_mm3")
    if expected_vol is not None and expected_vol > 0:
        actual_vol = _get_volume(shape)
        delta_pct = abs(actual_vol - expected_vol) / expected_vol * 100
        if delta_pct > 0.01:
            warnings.append(f"{label}: volume mismatch {delta_pct:.4f}% (expected {expected_vol:.1f}, got {actual_vol:.1f})")

    # Bounding box
    expected_bbox = meta.get("bounding_box_mm")
    if expected_bbox and len(expected_bbox) == 3:
        bbox = _get_bbox(shape)
        for i, axis in enumerate(["X", "Y", "Z"]):
            if abs(bbox["extents"][i] - expected_bbox[i]) > 0.01:
                warnings.append(f"{label}: bbox {axis} extent mismatch (expected {expected_bbox[i]:.3f}, got {bbox['extents'][i]:.3f})")

    return warnings


@app.post("/diff")
async def compute_diff(req: DiffRequest):
    """Compute solid-body boolean diff between two STEP files."""
    t_start = time.time()

    step_a = Path(req.step_a)
    step_b = Path(req.step_b)
    if not step_a.exists():
        raise HTTPException(status_code=404, detail=f"STEP file not found: {step_a}")
    if not step_b.exists():
        raise HTTPException(status_code=404, detail=f"STEP file not found: {step_b}")

    out_dir = Path(req.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load shapes
    logger.info(f"Loading Rev {req.revA}: {step_a}")
    shape_a = _load_step(str(step_a))
    logger.info(f"Loading Rev {req.revB}: {step_b}")
    shape_b = _load_step(str(step_b))

    # Import validation
    sidecar_a = step_a.parent / f"{req.part_number}_step_meta.json"
    sidecar_b = step_b.parent / f"{req.part_number}_step_meta.json"
    import_warnings = []
    import_warnings.extend(_validate_import(shape_a, str(sidecar_a), f"Rev {req.revA}"))
    import_warnings.extend(_validate_import(shape_b, str(sidecar_b), f"Rev {req.revB}"))
    if import_warnings:
        logger.warning(f"Import warnings: {import_warnings}")

    # Stats
    vol_a = _get_volume(shape_a)
    vol_b = _get_volume(shape_b)
    bbox_a = _get_bbox(shape_a)
    bbox_b = _get_bbox(shape_b)
    solids_a = _count_solids(shape_a)
    solids_b = _count_solids(shape_b)

    logger.info(f"Rev {req.revA}: {solids_a} solid(s), {vol_a:.1f} mm³")
    logger.info(f"Rev {req.revB}: {solids_b} solid(s), {vol_b:.1f} mm³")

    # Boolean diffs
    logger.info("Computing A - B (removed material)...")
    t_bool = time.time()
    cut_removed = BRepAlgoAPI_Cut(shape_a, shape_b)
    cut_removed.Build()
    if not cut_removed.IsDone():
        raise HTTPException(status_code=500, detail="Boolean A-B failed")
    removed_shape = cut_removed.Shape()

    logger.info("Computing B - A (added material)...")
    cut_added = BRepAlgoAPI_Cut(shape_b, shape_a)
    cut_added.Build()
    if not cut_added.IsDone():
        raise HTTPException(status_code=500, detail="Boolean B-A failed")
    added_shape = cut_added.Shape()
    t_bool_end = time.time()
    logger.info(f"Boolean ops completed in {t_bool_end - t_bool:.1f}s")

    vol_removed = _get_volume(removed_shape)
    vol_added = _get_volume(added_shape)
    identical = abs(vol_removed) < 0.001 and abs(vol_added) < 0.001

    result = {
        "identical": identical,
        "volume_a_mm3": round(vol_a, 3),
        "volume_b_mm3": round(vol_b, 3),
        "removed_volume_mm3": round(vol_removed, 3),
        "added_volume_mm3": round(vol_added, 3),
        "net_change_mm3": round(vol_added - vol_removed, 3),
        "solids_a": solids_a,
        "solids_b": solids_b,
        "bbox_a": bbox_a,
        "bbox_b": bbox_b,
        "changed_centroids": [],
        "changed_regions": [],
        "import_warnings": import_warnings,
        "computation_time_s": round(time.time() - t_start, 2),
        "removed_stl": None,
        "added_stl": None,
    }

    # Save diff volumes as STL (diagnostic + future GLB conversion)
    if abs(vol_removed) > 0.001:
        stl_path = out_dir / "removed.stl"
        _save_stl(removed_shape, str(stl_path))
        result["removed_stl"] = str(stl_path)
        removed_regions = _extract_change_regions(removed_shape, "removed")
        result["changed_regions"].extend(removed_regions)
        result["changed_centroids"].extend({
            "type": region["type"],
            "centroid": region["centroid"],
            "volume_mm3": region["volume_mm3"],
        } for region in removed_regions)
        logger.info(f"Saved removed volume: {stl_path}")

    if abs(vol_added) > 0.001:
        stl_path = out_dir / "added.stl"
        _save_stl(added_shape, str(stl_path))
        result["added_stl"] = str(stl_path)
        added_regions = _extract_change_regions(added_shape, "added")
        result["changed_regions"].extend(added_regions)
        result["changed_centroids"].extend({
            "type": region["type"],
            "centroid": region["centroid"],
            "volume_mm3": region["volume_mm3"],
        } for region in added_regions)
        logger.info(f"Saved added volume: {stl_path}")

    # Save result JSON
    result_path = out_dir / "diff_result.json"
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)
    logger.info(f"Saved result: {result_path}")

    logger.info(f"Diff complete: removed={vol_removed:.1f}mm³, added={vol_added:.1f}mm³, time={result['computation_time_s']}s")
    return result


@app.get("/health")
async def health():
    return {"status": "ok", "service": "geometry-worker"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info")
