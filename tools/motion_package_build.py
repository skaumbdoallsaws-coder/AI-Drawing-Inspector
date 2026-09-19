#!/usr/bin/env python3
"""Build an InspectorPro motion package from raw SolidWorks motion samples.

The raw sampler writes SolidWorks IComponent2.Transform2 arrays. This builder
turns those arrays into a render-oriented package:

* exact GLB node bindings for rendered component instances
* GLB/Three.js-compatible poses as position + quaternion
* semantic crank-slider groups and a compact agent summary

The script intentionally does not call SolidWorks. It is deterministic and
safe to run in CI once the raw export exists.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


EPS = 1e-12
MOVE_EPS = 1e-5
WARN_CLOSURE_EPS = 1e-3
REST_POSE_MAX_DELTA_EPS = 1e-3
LOOP_CLOSURE_WARN_DEG = 0.05
LOOP_CLOSURE_FAIL_DEG = 0.5
LOOP_CLOSURE_TRANSFORM_FAIL_EPS = 0.01
DEFAULT_RAW_PATH = "generated/engine_motion/motion_exports/engine_motion_crank_cycle_trimmed_45_raw.json"
DEFAULT_ASSEMBLY_PATH = "generated/engine_motion/glb_assets_sample0/Engine_Motion_Study_sample0_assembly.json"
DEFAULT_GLB_PATH = "generated/engine_motion/glb_assets_sample0/Engine_Motion_Study_sample0_colored.glb"


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_glb_json(path: Path) -> Dict[str, Any]:
    with path.open("rb") as f:
        magic, version, _length = struct.unpack("<III", f.read(12))
        if magic != 0x46546C67 or version != 2:
            raise ValueError(f"{path} is not a GLB 2.0 file")
        chunk_len, chunk_type = struct.unpack("<II", f.read(8))
        if chunk_type != 0x4E4F534A:
            raise ValueError(f"{path} first GLB chunk is not JSON")
        return json.loads(f.read(chunk_len).decode("utf-8"))


def _glb_nodes(path: Path) -> List[str]:
    gltf = _read_glb_json(path)
    return [str(n.get("name") or "") for n in gltf.get("nodes", []) if n.get("name")]


def _round_float(value: float, ndigits: int = 10) -> float:
    if abs(value) < 10 ** (-(ndigits - 1)):
        return 0.0
    return round(float(value), ndigits)


def _round_vec(values: Iterable[float], ndigits: int = 10) -> List[float]:
    return [_round_float(v, ndigits) for v in values]


def _sw_row_matrix(transform: Sequence[float]) -> List[List[float]]:
    """Return SolidWorks row-vector affine matrix as a 4x4 row-major list.

    SolidWorks ArrayData layout:
      [r00 r01 r02 r10 r11 r12 r20 r21 r22 tx ty tz scale ...]

    Existing GLB exporter comments confirm row-vector use:
      P' = P * R * scale + T
    """

    if len(transform) < 13:
        raise ValueError("SolidWorks transform must have at least 13 values")
    s = float(transform[12])
    return [
        [float(transform[0]) * s, float(transform[1]) * s, float(transform[2]) * s, 0.0],
        [float(transform[3]) * s, float(transform[4]) * s, float(transform[5]) * s, 0.0],
        [float(transform[6]) * s, float(transform[7]) * s, float(transform[8]) * s, 0.0],
        [float(transform[9]), float(transform[10]), float(transform[11]), 1.0],
    ]


def _quat_from_col_rotation_values(
    r00: float,
    r01: float,
    r02: float,
    r10: float,
    r11: float,
    r12: float,
    r20: float,
    r21: float,
    r22: float,
) -> List[float]:
    """Convert a column-vector rotation matrix to glTF order [x, y, z, w]."""

    trace = r00 + r11 + r22
    if trace > 0.0:
        s = 0.5 / math.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (r21 - r12) * s
        y = (r02 - r20) * s
        z = (r10 - r01) * s
    elif r00 > r11 and r00 > r22:
        s = 2.0 * math.sqrt(max(0.0, 1.0 + r00 - r11 - r22))
        w = (r21 - r12) / s
        x = 0.25 * s
        y = (r01 + r10) / s
        z = (r02 + r20) / s
    elif r11 > r22:
        s = 2.0 * math.sqrt(max(0.0, 1.0 + r11 - r00 - r22))
        w = (r02 - r20) / s
        x = (r01 + r10) / s
        y = 0.25 * s
        z = (r12 + r21) / s
    else:
        s = 2.0 * math.sqrt(max(0.0, 1.0 + r22 - r00 - r11))
        w = (r10 - r01) / s
        x = (r02 + r20) / s
        y = (r12 + r21) / s
        z = 0.25 * s
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm < EPS:
        return [0.0, 0.0, 0.0, 1.0]
    return [x / norm, y / norm, z / norm, w / norm]


def _quat_from_sw_row_rotation(transform: Sequence[float]) -> List[float]:
    """Convert a SolidWorks row-vector rotation to a Three.js/glTF quaternion.

    SolidWorks uses row-vector rotation. Three.js/glTF uses column-vector
    rotation. The equivalent column-vector matrix is the transpose of the
    SolidWorks 3x3 rotation block.
    """

    return _quat_from_col_rotation_values(
        float(transform[0]),
        float(transform[3]),
        float(transform[6]),
        float(transform[1]),
        float(transform[4]),
        float(transform[7]),
        float(transform[2]),
        float(transform[5]),
        float(transform[8]),
    )


def _hemisphere_continuous(quats: List[List[float]]) -> List[List[float]]:
    out: List[List[float]] = []
    prev: Optional[List[float]] = None
    for q in quats:
        q2 = list(q)
        if prev is not None:
            dot = sum(prev[i] * q2[i] for i in range(4))
            if dot < 0.0:
                q2 = [-v for v in q2]
        out.append(_round_vec(q2))
        prev = q2
    return out


def _component_metadata(assembly: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    by_name: Dict[str, Dict[str, Any]] = {}
    for comp in assembly.get("components", []):
        name = str(comp.get("name") or "")
        props = comp.get("properties") or {}
        part_number = props.get("PartNo") or props.get("PART_NUMBER") or props.get("ID")
        description = props.get("DESCRIPTION") or props.get("Description") or ""
        transform = comp.get("transform") or {}
        rotation = transform.get("rotation") or []
        translation = transform.get("translation") or []
        rest_transform = None
        if len(rotation) == 9 and len(translation) == 3:
            rest_transform = [float(v) for v in rotation] + [float(v) for v in translation] + [
                float(transform.get("scale", 1.0))
            ]
        by_name[name] = {
            "name": name,
            "displayName": description or name,
            "partNumber": str(part_number) if part_number else None,
            "sourceFile": comp.get("referencedFileName"),
            "type": comp.get("type"),
            "level": comp.get("level"),
            "parentName": comp.get("parentName"),
            "restTransform": rest_transform,
        }
    return by_name


def _raw_by_component(raw: Dict[str, Any]) -> Dict[str, List[List[float]]]:
    by_comp: Dict[str, List[List[float]]] = {}
    for sample in raw.get("samples", []):
        for comp in sample.get("components", []):
            name = str(comp.get("name") or "")
            transform = comp.get("transform")
            if name and isinstance(transform, list) and len(transform) >= 13:
                by_comp.setdefault(name, []).append([float(v) for v in transform])
    return by_comp


def _max_transform_delta(transforms: Sequence[Sequence[float]]) -> float:
    if not transforms:
        return 0.0
    first = transforms[0]
    max_delta = 0.0
    for t in transforms[1:]:
        max_delta = max(max_delta, max(abs(float(a) - float(b)) for a, b in zip(first, t)))
    return max_delta


def _sample_positions(transforms: Sequence[Sequence[float]]) -> List[List[float]]:
    return [_round_vec([t[9], t[10], t[11]]) for t in transforms]


def _sample_quaternions(transforms: Sequence[Sequence[float]]) -> List[List[float]]:
    quats = [_quat_from_sw_row_rotation(t) for t in transforms]
    return _hemisphere_continuous(quats)


def _duplicate_first_endpoint(values: List[Any]) -> List[Any]:
    if len(values) >= 2:
        values = list(values)
        values[-1] = values[0]
    return values


def _duplicate_quat_endpoint(quats: List[List[float]]) -> List[List[float]]:
    if len(quats) < 2:
        return quats
    out = [list(q) for q in quats]
    q0 = list(out[0])
    prev = out[-2]
    if sum(prev[i] * q0[i] for i in range(4)) < 0.0:
        q0 = [-v for v in q0]
    out[-1] = _round_vec(q0)
    return out


def _event_for_extreme(
    samples: List[Dict[str, Any]],
    transforms: Sequence[Sequence[float]],
    axis_index: int,
    component_id: str,
    label_prefix: str,
    max_event: bool,
) -> Dict[str, Any]:
    values = [float(t[9 + axis_index]) for t in transforms]
    idx = max(range(len(values)), key=lambda i: values[i]) if max_event else min(range(len(values)), key=lambda i: values[i])
    return {
        "angleDeg": _round_float(float(samples[idx]["crankAngleDeg"]), 6),
        "id": f"{label_prefix}_{'tdc' if max_event else 'bdc'}",
        "label": f"{label_prefix.upper()} {'TDC' if max_event else 'BDC'}",
        "componentIds": [component_id],
    }


def _quat_angle_deg(a: Sequence[float], b: Sequence[float]) -> float:
    dot = abs(sum(float(a[i]) * float(b[i]) for i in range(4)))
    dot = min(1.0, max(-1.0, dot))
    return math.degrees(2.0 * math.acos(dot))


def _rest_pose_metrics(
    rendered: Sequence[str],
    samples_by_comp: Dict[str, List[List[float]]],
    meta: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    top: List[Tuple[float, str]] = []
    missing: List[str] = []
    for name in rendered:
        rest = meta.get(name, {}).get("restTransform")
        sample0 = samples_by_comp.get(name, [None])[0]
        if not rest or sample0 is None:
            missing.append(name)
            continue
        delta = max(abs(float(a) - float(b)) for a, b in zip(rest, sample0))
        top.append((delta, name))
    top.sort(reverse=True)
    worst_delta = top[0][0] if top else 0.0
    compared_count = len(top)
    return {
        "restPoseMaxTransformDelta": _round_float(worst_delta, 12),
        "restPoseWorstComponent": top[0][1] if top else None,
        "restPoseComparedCount": compared_count,
        "restPoseExpectedCount": len(rendered),
        "restPoseMissingComponents": missing[:20],
        "restPoseOk": compared_count == len(rendered) and worst_delta <= REST_POSE_MAX_DELTA_EPS,
        "restPoseTop": [{"componentId": n, "maxTransformDelta": _round_float(d, 10)} for d, n in top[:8]],
    }


def _screws_mated_to_rod(assembly: Dict[str, Any], rod_name: str, moving_names: Sequence[str]) -> List[str]:
    moving = set(moving_names)
    screws: set[str] = set()
    cap_name = "connecting rod cap-" + rod_name.rsplit("-", 1)[-1] if "-" in rod_name else ""
    for mate in assembly.get("mates", []):
        names = [
            str((mate.get("entity1") or {}).get("componentName") or ""),
            str((mate.get("entity2") or {}).get("componentName") or ""),
        ]
        if rod_name not in names and cap_name not in names:
            continue
        for name in names:
            if name in moving and name.lower().startswith("socket head cap screw-"):
                screws.add(name)
    return sorted(screws)


def _build_semantic_groups(
    moving_names: Sequence[str],
    meta: Dict[str, Dict[str, Any]],
    assembly: Dict[str, Any],
) -> List[Dict[str, Any]]:
    names = set(moving_names)
    piston_nodes = sorted([n for n in names if "/piston-1" in n and n.startswith("Piston Assembly-")])

    def asm_suffix(piston_node: str) -> str:
        return piston_node.split("/", 1)[0].rsplit("-", 1)[-1]

    groups: List[Dict[str, Any]] = []
    if "crankshaft-1" in names:
        groups.append(
            {
                "id": "crankshaft_drive",
                "label": "Crankshaft drive",
                "componentIds": ["crankshaft-1"],
                "function": "Rotary driver that converts reciprocating piston loads into crankshaft rotation.",
            }
        )

    cyl_components: List[str] = []
    for idx, piston in enumerate(piston_nodes, start=1):
        suffix = asm_suffix(piston)
        rod = f"connecting rod-{suffix}"
        cap = f"connecting rod cap-{suffix}"
        pin = f"piston pin-{suffix}"
        rings = sorted([n for n in names if n.startswith(f"Piston Assembly-{suffix}/piston ring-")])
        screws = _screws_mated_to_rod(assembly, rod, moving_names)
        component_ids = [n for n in [rod, cap, pin, piston] + rings + screws if n in names]
        cyl_components.extend(component_ids)
        groups.append(
            {
                "id": f"crank_slider_instance{suffix}",
                "label": f"Cylinder {idx} crank-slider (SW instance {suffix})",
                "componentIds": component_ids,
                "function": "Converts crankshaft rotation into piston reciprocation through the connecting rod and piston pin.",
            }
        )

    reciprocating = sorted({n for n in cyl_components if "crankshaft" not in n})
    if reciprocating:
        groups.append(
            {
                "id": "reciprocating_group",
                "label": "Reciprocating components",
                "componentIds": reciprocating,
                "function": "Pistons, piston pins, rings, rods, and caps that translate or articulate during the crank cycle.",
            }
        )

    pin_bore_related = sorted(
        {
            n
            for n in reciprocating
            if "piston pin" in n or "/piston-1" in n or "connecting rod-" in n or "connecting rod cap-" in n
        }
    )
    if pin_bore_related:
        groups.append(
            {
                "id": "pin_bore_fai_affected",
                "label": "Pin bore affected motion group",
                "componentIds": pin_bore_related,
                "function": "Components whose fit or articulation is affected by piston pin bore alignment and diameter.",
            }
        )
    return groups


def _validation_metrics(
    moving: Sequence[str],
    fixed: Sequence[str],
    samples_by_comp: Dict[str, List[List[float]]],
    sample_count: int,
) -> Dict[str, Any]:
    quat_norm_max_error = 0.0
    scale_max_error = 0.0
    closure_top: List[Tuple[float, str]] = []
    closure_angle_top: List[Tuple[float, str]] = []
    for name in moving:
        transforms = samples_by_comp[name]
        quats = _sample_quaternions(transforms)
        for q in _sample_quaternions(transforms):
            quat_norm_max_error = max(quat_norm_max_error, abs(1.0 - math.sqrt(sum(v * v for v in q))))
        for t in transforms:
            scale_max_error = max(scale_max_error, abs(float(t[12]) - 1.0))
        first, last = transforms[0], transforms[-1]
        closure_top.append((max(abs(a - b) for a, b in zip(first, last)), name))
        closure_angle_top.append((_quat_angle_deg(quats[0], quats[-1]), name))
    closure_top.sort(reverse=True)
    closure_angle_top.sort(reverse=True)
    fixed_top: List[Tuple[float, str]] = []
    for name in fixed:
        fixed_top.append((_max_transform_delta(samples_by_comp[name]), name))
    fixed_top.sort(reverse=True)
    return {
        "ok": True,
        "sampleCount": sample_count,
        "movingCount": len(moving),
        "fixedCount": len(fixed),
        "quatNormMaxError": _round_float(quat_norm_max_error, 12),
        "scaleMaxError": _round_float(scale_max_error, 12),
        "loopClosureMaxTransformDelta": _round_float(closure_top[0][0] if closure_top else 0.0, 12),
        "loopClosureWorstComponent": closure_top[0][1] if closure_top else None,
        "loopClosureMaxAngleDeg": _round_float(closure_angle_top[0][0] if closure_angle_top else 0.0, 8),
        "loopClosureAngleWorstComponent": closure_angle_top[0][1] if closure_angle_top else None,
        "loopClosureWarning": bool(
            (closure_top and closure_top[0][0] > WARN_CLOSURE_EPS)
            or (closure_angle_top and closure_angle_top[0][0] > LOOP_CLOSURE_WARN_DEG)
        ),
        "loopClosureFailure": bool(
            (closure_angle_top and closure_angle_top[0][0] > LOOP_CLOSURE_FAIL_DEG)
            or (closure_top and closure_top[0][0] > LOOP_CLOSURE_TRANSFORM_FAIL_EPS)
        ),
        "loopClosureTop": [{"componentId": n, "maxTransformDelta": _round_float(d, 10)} for d, n in closure_top[:8]],
        "loopClosureAngleTop": [{"componentId": n, "angleDeg": _round_float(d, 8)} for d, n in closure_angle_top[:8]],
        "fixedMaxTransformDelta": _round_float(fixed_top[0][0] if fixed_top else 0.0, 12),
        "fixedWorstComponent": fixed_top[0][1] if fixed_top else None,
    }


def _component_record(name: str, meta: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    info = meta.get(name, {})
    record = {
        "id": name,
        "displayName": str(info.get("displayName") or name),
        "swInstancePath": name,
        "sourceFile": str(info.get("sourceFile") or name),
        "glbNodes": [name],
    }
    if info.get("partNumber"):
        record["partNumber"] = str(info["partNumber"])
    return record


def _part_numbers_for_components(component_ids: Sequence[str], meta: Dict[str, Dict[str, Any]]) -> List[str]:
    return sorted({str(meta.get(n, {}).get("partNumber")) for n in component_ids if meta.get(n, {}).get("partNumber")})


def _mat3_from_quat(q: Sequence[float]) -> List[List[float]]:
    x, y, z, w = (float(q[0]), float(q[1]), float(q[2]), float(q[3]))
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def _solve_normal_6x6(rows: List[List[float]], rhs: List[float]) -> List[float]:
    # Least squares via normal equations with a tiny ridge. A revolute joint
    # leaves the along-axis component of the solution free (rank 5), so the
    # plain system is singular by design; the ridge picks the minimum-norm
    # member without disturbing the residual.
    n = 6
    m = [[0.0] * n for _ in range(n)]
    v = [0.0] * n
    for row, b in zip(rows, rhs):
        for i in range(n):
            v[i] += row[i] * b
            for j in range(n):
                m[i][j] += row[i] * row[j]
    for i in range(n):
        m[i][i] += 1e-9
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        v[col], v[piv] = v[piv], v[col]
        d = m[col][col]
        for j in range(col, n):
            m[col][j] /= d
        v[col] /= d
        for r in range(n):
            if r != col and m[r][col]:
                f = m[r][col]
                for j in range(col, n):
                    m[r][j] -= f * m[col][j]
                v[r] -= f * v[col]
    return v


def _joint_pair_residual_mm(track_a: Dict[str, Any], track_b: Dict[str, Any]) -> Tuple[float, float]:
    """(max_mm, rms_mm) distance between best-fit FIXED local points on two
    tracks across the whole cycle. For bodies that share a physical joint
    (rod big end on crank pin, pin in rod small end) this reads ~0; a wrong
    rotation convention, swapped track, or desynced sampling reads tens of
    millimetres."""
    rots_a = [_mat3_from_quat(q) for q in track_a["q"]]
    rots_b = [_mat3_from_quat(q) for q in track_b["q"]]
    pos_a, pos_b = track_a["p"], track_b["p"]
    rows: List[List[float]] = []
    rhs: List[float] = []
    for ra, pa, rb, pb in zip(rots_a, pos_a, rots_b, pos_b):
        for i in range(3):
            rows.append([ra[i][0], ra[i][1], ra[i][2], -rb[i][0], -rb[i][1], -rb[i][2]])
            rhs.append(float(pb[i]) - float(pa[i]))
    u = _solve_normal_6x6(rows, rhs)
    ca, cb = u[:3], u[3:]
    worst_sq = 0.0
    sum_sq = 0.0
    count = 0
    for ra, pa, rb, pb in zip(rots_a, pos_a, rots_b, pos_b):
        wa = [sum(ra[i][j] * ca[j] for j in range(3)) + float(pa[i]) for i in range(3)]
        wb = [sum(rb[i][j] * cb[j] for j in range(3)) + float(pb[i]) for i in range(3)]
        d_sq = sum((wa[i] - wb[i]) ** 2 for i in range(3))
        worst_sq = max(worst_sq, d_sq)
        sum_sq += d_sq
        count += 1
    return (math.sqrt(worst_sq) * 1000.0, math.sqrt(sum_sq / max(1, count)) * 1000.0)


JOINT_CLOSURE_LIMIT_MM = 1.0


def _joint_closure_metrics(sample_payload: Dict[str, Any], moving: Sequence[str]) -> Dict[str, Any]:
    """Mate-equivalent joint-closure canary over the SHIPPED tracks.

    Every revolute joint of the crank-slider must admit fixed local points on
    both bodies that stay coincident across the cycle -- the same physical
    constraint the SolidWorks Concentric mates enforce. Checked pairs:
    rod/cap big end vs crankshaft, piston pin vs rod small end, piston vs
    its pin. The build fails above JOINT_CLOSURE_LIMIT_MM."""
    names = set(moving)

    def _digit_suffix(name: str, prefix: str) -> Optional[str]:
        if name.startswith(prefix) and name[len(prefix):].isdigit():
            return name[len(prefix):]
        return None

    pairs: List[Tuple[str, str]] = []
    for name in sorted(names):
        if _digit_suffix(name, "connecting rod-") or _digit_suffix(name, "connecting rod cap-"):
            if "crankshaft-1" in names:
                pairs.append((name, "crankshaft-1"))
        sfx = _digit_suffix(name, "piston pin-")
        if sfx and f"connecting rod-{sfx}" in names:
            pairs.append((name, f"connecting rod-{sfx}"))
        if "/piston-1" in name and name.startswith("Piston Assembly-"):
            sfx = name.split("/", 1)[0].rsplit("-", 1)[-1]
            if f"piston pin-{sfx}" in names:
                pairs.append((name, f"piston pin-{sfx}"))

    results: List[Dict[str, Any]] = []
    worst = 0.0
    for a, b in pairs:
        track_a = sample_payload.get(a)
        track_b = sample_payload.get(b)
        if not track_a or not track_b:
            continue
        max_mm, rms_mm = _joint_pair_residual_mm(track_a, track_b)
        worst = max(worst, max_mm)
        results.append({"a": a, "b": b, "maxMm": _round_float(max_mm, 4), "rmsMm": _round_float(rms_mm, 4)})
    results.sort(key=lambda r: -r["maxMm"])
    return {
        "jointClosurePairs": results,
        "jointClosurePairCount": len(results),
        "jointClosureMaxMm": _round_float(worst, 4),
        "jointClosureLimitMm": JOINT_CLOSURE_LIMIT_MM,
        "jointClosureOk": worst <= JOINT_CLOSURE_LIMIT_MM,
    }


def _build(args: argparse.Namespace) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    raw_path = Path(args.raw)
    assembly_path = Path(args.assembly)
    glb_path = Path(args.glb)
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw motion export not found: {raw_path}")
    if not assembly_path.exists():
        raise FileNotFoundError(
            f"Sample-0 assembly metadata not found: {assembly_path}. "
            "Generate it from raw sample 0 or re-run extraction at the motion sample-0 pose."
        )
    if not glb_path.exists():
        raise FileNotFoundError(
            f"Pinned sample-0 GLB not found: {glb_path}. "
            "Run MotionPoseGlbExporter at the raw sample-0 motion-study time, then rebuild."
        )
    raw = _load_json(raw_path)
    assembly = _load_json(assembly_path)
    expected_glb_file = (assembly.get("motionRestPose") or {}).get("expectedGlbFileName")
    if expected_glb_file and glb_path.name != str(expected_glb_file):
        raise ValueError(
            f"Assembly metadata expects GLB {expected_glb_file}, but builder was given {glb_path.name}."
        )
    meta = _component_metadata(assembly)
    glb_nodes = set(_glb_nodes(glb_path))
    samples_by_comp = _raw_by_component(raw)
    sample_count = int(raw.get("sampleCount") or len(raw.get("samples", [])))
    samples = raw.get("samples", [])
    if not samples:
        raise ValueError("raw export has no samples")

    rendered = sorted(name for name in samples_by_comp if name in glb_nodes)
    skipped = sorted(name for name in samples_by_comp if name not in glb_nodes)
    skipped_leaf_moving = [
        name
        for name in skipped
        if _max_transform_delta(samples_by_comp[name]) > MOVE_EPS and (meta.get(name, {}).get("type") != "Assembly")
    ]
    if skipped_leaf_moving:
        raise ValueError(f"Moving leaf components missing exact GLB nodes: {', '.join(skipped_leaf_moving)}")

    moving = [name for name in rendered if _max_transform_delta(samples_by_comp[name]) > MOVE_EPS]
    fixed = [name for name in rendered if name not in moving]

    components = {
        "moving": [_component_record(name, meta) for name in moving],
        "fixed": [_component_record(name, meta) for name in fixed],
    }

    sample_payload: Dict[str, Any] = {}
    for name in moving:
        transforms = samples_by_comp[name]
        sample_payload[name] = {
            "p": _duplicate_first_endpoint(_sample_positions(transforms)),
            "q": _duplicate_quat_endpoint(_sample_quaternions(transforms)),
        }

    piston_nodes = sorted([n for n in moving if "/piston-1" in n and n.startswith("Piston Assembly-")])
    stroke_m: Dict[str, float] = {}
    events: List[Dict[str, Any]] = []
    for idx, name in enumerate(piston_nodes, start=1):
        transforms = samples_by_comp[name]
        ys = [float(t[10]) for t in transforms]
        stroke_m[name] = _round_float(max(ys) - min(ys), 10)
        events.append(_event_for_extreme(samples, transforms, 1, name, f"cyl{idx}", True))
        events.append(_event_for_extreme(samples, transforms, 1, name, f"cyl{idx}", False))

    semantic_groups = _build_semantic_groups(moving, meta, assembly)
    validation = _validation_metrics(moving, fixed, samples_by_comp, sample_count)
    validation.update(_rest_pose_metrics(rendered, samples_by_comp, meta))
    validation.update(_joint_closure_metrics(sample_payload, moving))
    validation["packageEndpointDuplicatedFromStart"] = True
    validation["measuredEndpointKeptInDiagnosticsOnly"] = True
    if not validation.get("jointClosureOk"):
        worst_pair = (validation.get("jointClosurePairs") or [{}])[0]
        raise ValueError(
            "Joint closure exceeds tolerance: "
            f"{validation['jointClosureMaxMm']} mm (limit {JOINT_CLOSURE_LIMIT_MM} mm) "
            f"at {worst_pair.get('a')} <-> {worst_pair.get('b')}. "
            "The exported tracks do not keep the crank-slider joints coincident."
        )
    if validation.get("loopClosureFailure"):
        raise ValueError(
            "Loop closure exceeds tolerance: "
            f"{validation['loopClosureMaxAngleDeg']} deg at {validation['loopClosureAngleWorstComponent']}; "
            f"max transform delta {validation['loopClosureMaxTransformDelta']} at {validation['loopClosureWorstComponent']}"
        )
    if not getattr(args, "skip_rest_pose_check", False) and not validation.get("restPoseOk"):
        raise ValueError(
            "Rest-pose mismatch between assembly metadata and raw sample 0: "
            f"{validation['restPoseMaxTransformDelta']} at {validation['restPoseWorstComponent']} "
            f"({validation['restPoseComparedCount']}/{validation['restPoseExpectedCount']} components compared). "
            "Re-export the GLB and assembly metadata at the raw sample-0 motion-study pose, then rebuild."
        )

    exported_at = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    package: Dict[str, Any] = {
        "contractVersion": 1,
        "motionId": args.motion_id,
        "name": args.name,
        "description": "One crankshaft-driven cycle for the four-cylinder piston, rod, and crank assembly.",
        "source": {
            "system": "solidworks_motion",
            "assemblyFile": str(raw.get("assemblyFile") or ""),
            "configuration": str(raw.get("configuration") or ""),
            "motionStudyName": str(raw.get("motionStudyName") or "Motion Study"),
            "studyType": "basic_motion",
            "exportedAt": exported_at,
            "exporterVersion": "MotionStudySampler + tools/motion_package_build.py",
        },
        "glbAsset": {
            "fileName": glb_path.name,
            "sha256": _sha256(glb_path),
            "byteLength": glb_path.stat().st_size,
        },
        "frame": {
            "space": "glb_asset_root",
            "convention": "y_up_right_handed",
            "units": {"length": "m", "angle": "deg"},
            "sourceConvention": "solidworks_assembly",
            "sourceToPackageMatrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        },
        "driver": {
            "kind": "rotary",
            "componentId": "crankshaft-1",
            "axis": {"origin": [0.0, 0.0, 0.0], "direction": [-1.0, 0.0, 0.0]},
            "cycleDegrees": 360,
            "defaultRpm": 90,
            "rpmRange": [10, 600],
        },
        "components": components,
        "sampling": {
            "parameter": "crank_angle_deg",
            "startDeg": 0,
            "endDeg": 360,
            "stepDeg": _round_float(float(raw.get("stepDegrees") or 360.0 / max(1, sample_count - 1)), 10),
            "count": sample_count,
            "endpointDuplicatesStart": True,
        },
        "samples": sample_payload,
        "events": sorted(events, key=lambda e: (e["angleDeg"], e["id"])),
        "semanticGroups": semantic_groups,
        "derived": {"strokeM": stroke_m, "pistonTravelAxis": [0, 1, 0]},
    }

    component_by_id = {c["id"]: c for c in components["moving"] + components["fixed"]}
    agent_summary = {
        "available_motions": [
            {
                "motion_id": args.motion_id,
                "name": args.name,
                "driver": "crankshaft-1, rotary, 360 degree cycle",
                "default_rpm": 90,
                "rpm_range": [10, 600],
                "moving_component_count": len(moving),
                "groups": [
                    {
                        "id": g["id"],
                        "label": g["label"],
                        "component_ids": g["componentIds"],
                        "part_numbers": _part_numbers_for_components(g["componentIds"], meta),
                        "function": g["function"],
                    }
                    for g in semantic_groups
                ],
                "events": [{"id": e["id"], "angle_deg": e["angleDeg"], "label": e["label"]} for e in events],
                "stroke_m": stroke_m,
            }
        ],
        "playback": {"active_motion_id": None, "playing": False, "rpm": None, "angle_deg": None},
    }
    diagnostics = {
        "rawExport": str(raw_path.as_posix()),
        "rawExportSha256": _sha256(raw_path),
        "assemblyMetadata": str(assembly_path.as_posix()),
        "glbAssetPath": str(glb_path.as_posix()),
        "glbNodeCount": len(glb_nodes),
        "sourceStartTimeSeconds": raw.get("sourceStartTimeSeconds"),
        "sourceEndTimeSeconds": raw.get("sourceEndTimeSeconds"),
        "sourceDurationSeconds": raw.get("durationSeconds"),
        "skippedUnbound": [
            {
                "id": name,
                "displayName": meta.get(name, {}).get("displayName") or name,
                "partNumber": meta.get(name, {}).get("partNumber"),
                "sourceFile": meta.get(name, {}).get("sourceFile"),
                "type": meta.get(name, {}).get("type"),
                "reason": "No exact GLB node; allowed only because this is a non-rendered assembly wrapper.",
            }
            for name in skipped
        ],
        "validation": validation,
        "componentCount": len(component_by_id),
    }
    return package, agent_summary, diagnostics


def build_package(args: argparse.Namespace) -> Dict[str, Any]:
    package, _agent_summary, _diagnostics = _build(args)
    return package


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=DEFAULT_RAW_PATH)
    ap.add_argument("--assembly", default=DEFAULT_ASSEMBLY_PATH)
    ap.add_argument("--glb", default=DEFAULT_GLB_PATH)
    ap.add_argument("--out", default="generated/engine_motion/motion/engine4cyl_crank_cycle.json")
    ap.add_argument("--summary-out", default="generated/engine_motion/motion/engine4cyl_crank_cycle_summary.json")
    ap.add_argument("--diagnostics-out", default="generated/engine_motion/motion/engine4cyl_crank_cycle_diagnostics.json")
    ap.add_argument("--motion-id", default="engine4cyl_crank_cycle")
    ap.add_argument("--name", default="Four-cylinder crank-slider cycle")
    ap.add_argument(
        "--skip-rest-pose-check",
        action="store_true",
        help="Debug only: build even when raw sample 0 does not match the pinned assembly rest pose.",
    )
    args = ap.parse_args()

    package, agent_summary, diagnostics = _build(args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(package, indent=2), encoding="utf-8")

    summary_out = Path(args.summary_out)
    summary_out.parent.mkdir(parents=True, exist_ok=True)
    summary_out.write_text(json.dumps(agent_summary, indent=2), encoding="utf-8")

    diagnostics_out = Path(args.diagnostics_out)
    diagnostics_out.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_out.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")

    validation = diagnostics["validation"]
    print(f"Wrote motion package: {out}")
    print(f"Wrote agent summary:   {summary_out}")
    print(f"Wrote diagnostics:     {diagnostics_out}")
    print(
        "Validation: "
        f"moving={validation['movingCount']} fixed={validation['fixedCount']} "
        f"closure={validation['loopClosureMaxTransformDelta']} "
        f"worst={validation['loopClosureWorstComponent']}"
    )
    if validation.get("loopClosureWarning"):
        print("Warning: measured loop closure exceeded the recommended threshold; package duplicates the first endpoint for seamless playback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
