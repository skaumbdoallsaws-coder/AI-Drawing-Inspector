#!/usr/bin/env python3
"""Resolve the SolidWorks -> GLB coordinate transform for the facility layout and
record it inside facility_layout_semantic.json's ``layoutMap.coordinateFrame``.

Why this exists
---------------
The facility GLB (``Assem3_colored.glb``) is produced by SolidWorks' *native* glTF
export, which recenters the model on its bounding box. The semantic JSON keeps the
*raw* SolidWorks component transforms. The two artifacts therefore live in different
frames, and any overlay/route/clearance drawn from raw semantic coordinates is
shifted relative to what the viewer shows.

SolidWorks does not report the offset it applied, so the transform cannot simply be
"emitted by the extractor". This tool reconciles the two artifacts deterministically:
it matches each rack component to its GLB meshes, solves the rigid SolidWorks->GLB
transform, validates it against the GLB geometry, and writes it as part of a formal
coordinate contract. Raw SolidWorks coordinates are left untouched.

The matrix is emitted column-major (three.js ``Matrix4.fromArray`` compatible), applied
as ``v_glb = M . [x, y, z, 1]^T``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A

DEFAULT_SEMANTIC = Path("facility_layout_semantic.json")
DEFAULT_GLB = Path("generated/training/facility-layout/Assem3_colored.glb")

TRANSFORM_SCHEMA_VERSION = "facility-coordinate-frame-v1"
ROTATION_TOL_DEG = 0.5      # treat rotation below this as identity (emit translation-only)
SCALE_TOL = 0.002           # |scale - 1| must be under this
RESIDUAL_TOL_M = 0.50       # max per-rack residual after transform
CONTAINMENT_EPS_M = 0.10    # transformed SW center must sit within GLB bbox + this
IDENTITY_TOL_M = 0.10       # |translation| below this is noise -> emit exact identity

VIEWER_RECENTER_NOTE = (
    "The semantic JSON and the GLB asset share this frame (transform is identity). The "
    "three.js viewer separately recenters the model on its bounding-box center for framing "
    "(_fitCameraToGroup: group.position.sub(center)); that display shift is NOT a property "
    "of the data and must be applied by the renderer (e.g. parent overlays under the "
    "recentered group, or add group.position), not by transforming the semantic coordinates."
)


# --------------------------------------------------------------------------- GLB

def read_glb_json(path: Path) -> dict:
    """Read only the JSON chunk of a .glb (never touches the binary geometry)."""
    with path.open("rb") as fh:
        magic, version, _length = struct.unpack("<III", fh.read(12))
        if magic != GLB_MAGIC:
            raise ValueError(f"{path} is not a binary glTF (bad magic)")
        clen, ctype = struct.unpack("<II", fh.read(8))
        if ctype != CHUNK_JSON:
            raise ValueError(f"{path} first chunk is not JSON")
        return json.loads(fh.read(clen).decode("utf-8"))


def _node_local_matrix(node: dict) -> np.ndarray:
    if "matrix" in node:                       # glTF stores matrices column-major
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T  # -> row-major for numpy
    m = np.eye(4)
    t = node.get("translation")
    r = node.get("rotation")        # quaternion x,y,z,w
    s = node.get("scale")
    sm = np.eye(4)
    if s:
        sm[0, 0], sm[1, 1], sm[2, 2] = s
    rm = np.eye(4)
    if r:
        x, y, z, w = r
        rm[:3, :3] = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w),     2 * (x * z + y * w)],
            [2 * (x * y + z * w),     1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w),     2 * (y * z + x * w),     1 - 2 * (x * x + y * y)],
        ])
    tm = np.eye(4)
    if t:
        tm[:3, 3] = t
    return tm @ rm @ sm @ m


def node_world_aabbs(gltf: dict) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """World-space AABB (min, max) per named node, walking the scene hierarchy.

    Local AABBs come from each primitive's POSITION accessor min/max (glTF requires
    them), so no vertex data is read. Works whether transforms are baked (flat nodes)
    or carried as node matrices/TRS.
    """
    nodes = gltf.get("nodes", [])
    meshes = gltf.get("meshes", [])
    accessors = gltf.get("accessors", [])
    scenes = gltf.get("scenes", [])
    roots: List[int] = []
    for sc in scenes:
        roots.extend(sc.get("nodes", []))
    if not roots:
        roots = list(range(len(nodes)))

    out: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}

    def mesh_local_aabb(mesh_idx: int) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        lo = np.full(3, np.inf)
        hi = np.full(3, -np.inf)
        found = False
        for prim in meshes[mesh_idx].get("primitives", []):
            pa = prim.get("attributes", {}).get("POSITION")
            if pa is None:
                continue
            acc = accessors[pa]
            if "min" not in acc or "max" not in acc:
                continue
            lo = np.minimum(lo, np.array(acc["min"], dtype=float))
            hi = np.maximum(hi, np.array(acc["max"], dtype=float))
            found = True
        return (lo, hi) if found else None

    def walk(idx: int, parent: np.ndarray) -> None:
        node = nodes[idx]
        world = parent @ _node_local_matrix(node)
        if "mesh" in node:
            local = mesh_local_aabb(node["mesh"])
            if local is not None:
                lo, hi = local
                corners = np.array([[x, y, z, 1.0]
                                    for x in (lo[0], hi[0])
                                    for y in (lo[1], hi[1])
                                    for z in (lo[2], hi[2])])
                wc = (world @ corners.T).T[:, :3]
                wlo, whi = wc.min(axis=0), wc.max(axis=0)
                name = node.get("name")
                if name:
                    if name in out:
                        wlo = np.minimum(wlo, out[name][0])
                        whi = np.maximum(whi, out[name][1])
                    out[name] = (wlo, whi)
        for child in node.get("children", []):
            walk(child, world)

    for r in roots:
        walk(r, np.eye(4))
    return out


# ----------------------------------------------------------------- correspondence

def _match(node_name: str, comp: str) -> bool:
    n, c = node_name.lower(), comp.lower()
    return n == c or n.startswith(c + "/") or n.startswith(c + "\\") or n.startswith(c + "-")


def rack_glb_center(comp: str, aabbs: Dict[str, Tuple[np.ndarray, np.ndarray]]):
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    found = False
    for name, (nlo, nhi) in aabbs.items():
        if _match(name, comp):
            lo = np.minimum(lo, nlo)
            hi = np.maximum(hi, nhi)
            found = True
    if not found:
        return None
    return (lo + hi) / 2.0, lo, hi


def _sw_center(instance: dict) -> Optional[np.ndarray]:
    env = (instance.get("rackEnvelopeEstimate") or {})
    c = ((env.get("centerlineBoundsMeters") or {}).get("center"))
    if not c:
        c = instance.get("positionMeters")
    if not c:
        return None
    try:
        return np.array([float(c["x"]), float(c["y"]), float(c["z"])])
    except (TypeError, KeyError, ValueError):
        return None


def build_correspondences(semantic: dict, aabbs: dict):
    pairs = []  # (componentName, sw_center, glb_center, glb_lo, glb_hi)
    for row in semantic.get("rackRows", []):
        for inst in row.get("rackInstances", []):
            comp = inst.get("componentName")
            if not comp:
                continue
            sw = _sw_center(inst)
            glb = rack_glb_center(comp, aabbs)
            if sw is None or glb is None:
                continue
            center, lo, hi = glb
            pairs.append((comp, sw, center, lo, hi))
    return pairs


# ----------------------------------------------------------------------- solve

def kabsch(sw: np.ndarray, glb: np.ndarray):
    """Optimal rigid transform mapping sw->glb (no scale). Returns (R, t, rot_deg)."""
    cs, cg = sw.mean(axis=0), glb.mean(axis=0)
    H = (sw - cs).T @ (glb - cg)
    U, _S, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    D = np.diag([1.0, 1.0, d])
    R = Vt.T @ D @ U.T
    t = cg - R @ cs
    angle = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0))))
    return R, t, angle


def fit_scale(sw: np.ndarray, glb: np.ndarray, R: np.ndarray) -> float:
    cs, cg = sw.mean(axis=0), glb.mean(axis=0)
    num = float(np.sum((glb - cg) * ((R @ (sw - cs).T).T)))
    den = float(np.sum((sw - cs) ** 2))
    return num / den if den else 1.0


def matrix_to_colmajor16(R: np.ndarray, t: np.ndarray) -> List[float]:
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = t
    return [round(float(v), 9) for v in M.T.reshape(-1)]  # column-major flat


# -------------------------------------------------------------------- contract

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def resolve(semantic: dict, glb_path: Path, *, now_iso: str) -> dict:
    gltf = read_glb_json(glb_path)
    aabbs = node_world_aabbs(gltf)
    pairs = build_correspondences(semantic, aabbs)
    if len(pairs) < 3:
        raise SystemExit(f"Only {len(pairs)} rack correspondences found; need >= 3.")

    sw = np.array([p[1] for p in pairs])
    glb = np.array([p[2] for p in pairs])

    R, t_rigid, rot_deg = kabsch(sw, glb)
    scale = fit_scale(sw, glb, R)

    rotation_negligible = rot_deg <= ROTATION_TOL_DEG and abs(scale - 1.0) <= SCALE_TOL
    measured_t = np.median(glb - sw, axis=0)  # robust best-fit translation (resists per-rack noise)
    if rotation_negligible and float(np.max(np.abs(measured_t))) <= IDENTITY_TOL_M:
        # GLB and semantic are the same frame; the residual is sub-noise. Emit exact identity.
        R_emit, t_emit = np.eye(3), np.zeros(3)
        transform_class = "identity"
    elif rotation_negligible:
        R_emit, t_emit = np.eye(3), measured_t
        transform_class = "translation"
    else:
        R_emit, t_emit = R, t_rigid
        transform_class = "rigid"

    # Validate: apply emitted transform to SW centers, compare to GLB centers/bboxes.
    transformed = (R_emit @ sw.T).T + t_emit
    residuals = np.linalg.norm(transformed - glb, axis=1)
    within = []
    for (comp, _sw, _c, lo, hi), tp in zip(pairs, transformed):
        ok = bool(np.all(tp >= lo - CONTAINMENT_EPS_M) and np.all(tp <= hi + CONTAINMENT_EPS_M))
        within.append(ok)
    all_within = all(within)
    max_res = float(residuals.max())
    mean_res = float(residuals.mean())
    rms_res = float(np.sqrt(np.mean(residuals ** 2)))

    validation = {
        "correspondenceKind": "rack_component_geometric_centers",
        "rackCorrespondences": len(pairs),
        "maxResidualMeters": round(max_res, 5),
        "meanResidualMeters": round(mean_res, 5),
        "rmsResidualMeters": round(rms_res, 5),
        "rotationDegFromIdentity": round(rot_deg, 5),
        "scale": round(scale, 6),
        "allTransformedCentersWithinGlbBounds": all_within,
        "residualToleranceMeters": RESIDUAL_TOL_M,
        "containmentEpsilonMeters": CONTAINMENT_EPS_M,
    }
    passed = all_within and max_res <= RESIDUAL_TOL_M and abs(scale - 1.0) <= SCALE_TOL
    validation["passed"] = passed

    matrix = matrix_to_colmajor16(R_emit, t_emit)
    contract = {
        "transformSchemaVersion": TRANSFORM_SCHEMA_VERSION,
        "transformSource": "resolved_from_glb_semantic_alignment",
        "transformClass": transform_class,
        "matrixOrder": "column-major; v_glb = M . [x,y,z,1]^T",
        "units": "meters",
        "transformSolidWorksToGlb": matrix,
        "translationMeters": {"x": round(float(t_emit[0]), 6), "y": round(float(t_emit[1]), 6), "z": round(float(t_emit[2]), 6)},
        "measuredBestFitTranslationMeters": {"x": round(float(measured_t[0]), 6), "y": round(float(measured_t[1]), 6), "z": round(float(measured_t[2]), 6)},
        "alignmentNote": VIEWER_RECENTER_NOTE,
        "glbAsset": {
            "path": str(glb_path).replace("\\", "/"),
            "byteLength": glb_path.stat().st_size,
            "sha256": sha256(glb_path),
        },
        "resolvedAt": now_iso,
        "validation": validation,
    }
    return contract


# ----------------------------------------------------------------------- check

def check_existing(semantic: dict, glb_path: Path) -> bool:
    """Re-validate a coordinateFrame already present in the semantic (the canary)."""
    frame = (semantic.get("layoutMap") or {}).get("coordinateFrame") or {}
    mat = frame.get("transformSolidWorksToGlb")
    if not mat or len(mat) != 16:
        print("CHECK FAIL: no transformSolidWorksToGlb present")
        return False
    M = np.array(mat, dtype=float).reshape(4, 4).T  # column-major -> row-major
    R, t = M[:3, :3], M[:3, 3]
    asset = frame.get("glbAsset") or {}
    if asset.get("sha256") and asset.get("sha256") != sha256(glb_path):
        print("CHECK FAIL: glbSha256 does not match the GLB on disk (asset/transform mismatch)")
        return False
    aabbs = node_world_aabbs(read_glb_json(glb_path))
    pairs = build_correspondences(semantic, aabbs)
    sw = np.array([p[1] for p in pairs])
    glb = np.array([p[2] for p in pairs])
    transformed = (R @ sw.T).T + t
    residuals = np.linalg.norm(transformed - glb, axis=1)
    within = all(bool(np.all(tp >= lo - CONTAINMENT_EPS_M) and np.all(tp <= hi + CONTAINMENT_EPS_M))
                 for (_c, _s, _ce, lo, hi), tp in zip(pairs, transformed))
    ok = within and residuals.max() <= RESIDUAL_TOL_M
    print(f"CHECK {'PASS' if ok else 'FAIL'}: {len(pairs)} racks, "
          f"maxResidual={residuals.max():.4f}m, within_bounds={within}")
    return ok


# ------------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--semantic", type=Path, default=DEFAULT_SEMANTIC)
    ap.add_argument("--glb", type=Path, default=DEFAULT_GLB)
    ap.add_argument("--output", type=Path, default=None, help="defaults to in-place")
    ap.add_argument("--check", action="store_true", help="re-validate existing transform, do not write")
    ap.add_argument("--report-only", action="store_true", help="resolve and print, do not write")
    ap.add_argument("--now", default=None, help="ISO timestamp override (for reproducible output)")
    args = ap.parse_args()

    semantic = json.loads(args.semantic.read_text(encoding="utf-8-sig"))

    if args.check:
        return 0 if check_existing(semantic, args.glb) else 1

    now_iso = args.now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    contract = resolve(semantic, args.glb, now_iso=now_iso)

    print(json.dumps({k: v for k, v in contract.items() if k != "glbAsset"}, indent=1))
    print("glbSha256:", contract["glbAsset"]["sha256"][:16], "...", "bytes:", contract["glbAsset"]["byteLength"])

    if not contract["validation"]["passed"]:
        print("VALIDATION FAILED - refusing to write.")
        return 1
    if args.report_only:
        print("(report-only: not written)")
        return 0

    layout = semantic.setdefault("layoutMap", {})
    existing = layout.get("coordinateFrame") or {}
    # Preserve existing descriptive fields; add/overwrite the transform contract fields.
    existing.update(contract)
    layout["coordinateFrame"] = existing

    out = args.output or args.semantic
    out.write_text(json.dumps(semantic, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote coordinateFrame transform into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
