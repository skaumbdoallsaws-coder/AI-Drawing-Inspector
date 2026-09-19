"""Revision-bound render artifacts for illustrated parts manual pages."""

from __future__ import annotations

import copy
import hashlib
import math
import io
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from PIL import Image

from .version import (
    PARTS_MANUAL_DEFAULT_END_CONDITION,
    PARTS_MANUAL_RENDER_PIPELINE_VERSION,
)


_ASSEMBLY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
_PAGE_ID_RE = re.compile(r"^page-[A-Za-z0-9_-]{1,160}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PartsManualRenderArtifactError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _artifact_paths(
    root: str | Path,
    assembly_number: str,
    document_revision: str,
    page_id: str,
) -> Tuple[Path, Path]:
    assembly = str(assembly_number or "").strip().lower()
    revision = str(document_revision or "").strip().lower()
    page = str(page_id or "").strip()
    if _ASSEMBLY_RE.fullmatch(assembly) is None:
        raise PartsManualRenderArtifactError("invalid assembly number")
    if _SHA256_RE.fullmatch(revision) is None:
        raise PartsManualRenderArtifactError("invalid document revision")
    if _PAGE_ID_RE.fullmatch(page) is None:
        raise PartsManualRenderArtifactError("invalid page ID")
    base = Path(root).resolve()
    directory = (base / assembly / "renders" / revision).resolve()
    try:
        directory.relative_to(base)
    except ValueError as exc:
        raise PartsManualRenderArtifactError("invalid render artifact path") from exc
    return directory / f"{page}.png", directory / f"{page}.json"


def _native_atomic_path(path: Path) -> str:
    """Return a Windows extended path for atomic moves with long revision paths."""

    value = str(path.resolve())
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=".tmp-",
            suffix=path.suffix,
            dir=str(path.parent),
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(6):
            try:
                os.replace(
                    _native_atomic_path(temporary),
                    _native_atomic_path(path),
                )
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.03 * (2**attempt))
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _page_for_render(document: Mapping[str, Any], page_id: str) -> Mapping[str, Any]:
    page = next(
        (
            candidate
            for candidate in document.get("pages") or []
            if isinstance(candidate, Mapping) and candidate.get("pageId") == page_id
        ),
        None,
    )
    if page is None or not isinstance(page.get("renderRequest"), Mapping):
        raise PartsManualRenderArtifactError("manual page does not accept a 3D render")
    return page


def _normalized_point(value: Any, *, field: str) -> Dict[str, float]:
    if not isinstance(value, Mapping):
        raise PartsManualRenderArtifactError(f"balloon {field} must be a normalized point")
    try:
        x = float(value.get("x"))
        y = float(value.get("y"))
    except (TypeError, ValueError) as exc:
        raise PartsManualRenderArtifactError(f"balloon {field} must be a normalized point") from exc
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise PartsManualRenderArtifactError(f"balloon {field} must be inside the image")
    return {"x": round(x, 6), "y": round(y, 6)}


def _normalized_bounds(value: Any, *, field: str) -> Dict[str, float]:
    if not isinstance(value, Mapping):
        raise PartsManualRenderArtifactError(f"balloon {field} must be normalized bounds")
    try:
        result = {key: float(value.get(key)) for key in ("left", "top", "right", "bottom")}
    except (TypeError, ValueError) as exc:
        raise PartsManualRenderArtifactError(f"balloon {field} must be normalized bounds") from exc
    if not all(0.0 <= result[key] <= 1.0 for key in result):
        raise PartsManualRenderArtifactError(f"balloon {field} must be inside the image")
    if result["right"] <= result["left"] or result["bottom"] <= result["top"]:
        raise PartsManualRenderArtifactError(f"balloon {field} must have positive area")
    return {key: round(value, 6) for key, value in result.items()}


def _callout_segments(row: Mapping[str, Any]) -> List[tuple[Dict[str, float], Dict[str, float]]]:
    points = [
        row["target"],
        *(row.get("leaderPath") or []),
        row.get("balloonAttachment") or _balloon_attachment(row),
    ]
    return list(zip(points, points[1:]))


def _callout_leader_length(row: Mapping[str, Any]) -> float:
    return sum(
        math.hypot(end["x"] - start["x"], end["y"] - start["y"])
        for start, end in _callout_segments(row)
    )


def _is_orthogonal(start: Mapping[str, float], end: Mapping[str, float]) -> bool:
    return abs(start["x"] - end["x"]) <= 0.00001 or abs(start["y"] - end["y"]) <= 0.00001


def _segments_cross(
    first: tuple[Mapping[str, float], Mapping[str, float]],
    second: tuple[Mapping[str, float], Mapping[str, float]],
) -> bool:
    a, b = first
    c, d = second
    rx, ry = b["x"] - a["x"], b["y"] - a["y"]
    sx, sy = d["x"] - c["x"], d["y"] - c["y"]
    denominator = rx * sy - ry * sx
    qpx, qpy = c["x"] - a["x"], c["y"] - a["y"]
    epsilon = 0.001
    if abs(denominator) <= 1e-10:
        if abs(qpx * ry - qpy * rx) > 1e-10:
            return False
        length_squared = rx * rx + ry * ry
        if length_squared <= 1e-12:
            return False
        t0 = (qpx * rx + qpy * ry) / length_squared
        t1 = t0 + (sx * rx + sy * ry) / length_squared
        overlap = min(1.0, max(t0, t1)) - max(0.0, min(t0, t1))
        return overlap > epsilon
    t = (qpx * sy - qpy * sx) / denominator
    u = (qpx * ry - qpy * rx) / denominator
    return epsilon < t < 1.0 - epsilon and epsilon < u < 1.0 - epsilon


def _segment_intersects_bounds(
    segment: tuple[Mapping[str, float], Mapping[str, float]],
    bounds: Mapping[str, float],
    *,
    padding: float = 0.002,
) -> bool:
    start, end = segment
    left = bounds["left"] - padding
    right = bounds["right"] + padding
    top = bounds["top"] - padding
    bottom = bounds["bottom"] + padding
    dx = end["x"] - start["x"]
    dy = end["y"] - start["y"]
    p = (-dx, dx, -dy, dy)
    q = (start["x"] - left, right - start["x"], start["y"] - top, bottom - start["y"])
    lower, upper = 0.0, 1.0
    for direction, distance in zip(p, q):
        if abs(direction) <= 1e-12:
            if distance < 0:
                return False
            continue
        ratio = distance / direction
        if direction < 0:
            lower = max(lower, ratio)
        else:
            upper = min(upper, ratio)
        if lower > upper:
            return False
    return True


def _balloon_bounds(point: Mapping[str, float]) -> Dict[str, float]:
    return {
        "left": float(point["x"]) - 0.025,
        "right": float(point["x"]) + 0.025,
        "top": float(point["y"]) - 0.030,
        "bottom": float(point["y"]) + 0.030,
    }


def _balloon_attachment(row: Mapping[str, Any]) -> Dict[str, float]:
    balloon = row["balloon"]
    previous = (row.get("leaderPath") or [])[-1] if row.get("leaderPath") else row["target"]
    dx = float(previous["x"]) - float(balloon["x"])
    dy = float(previous["y"]) - float(balloon["y"])
    radius_x, radius_y = 0.022, 0.027
    denominator = math.sqrt((dx / radius_x) ** 2 + (dy / radius_y) ** 2)
    if denominator <= 1e-12:
        return {"x": float(balloon["x"]), "y": float(balloon["y"])}
    return {
        "x": float(balloon["x"]) + dx / denominator,
        "y": float(balloon["y"]) + dy / denominator,
    }


def _leader_detour_ratio(row: Mapping[str, Any]) -> float:
    attachment = row.get("balloonAttachment") or _balloon_attachment(row)
    direct = math.hypot(
        row["target"]["x"] - attachment["x"],
        row["target"]["y"] - attachment["y"],
    )
    return _callout_leader_length(row) / max(0.025, direct)


def _segments_nearly_parallel(
    first: tuple[Mapping[str, float], Mapping[str, float]],
    second: tuple[Mapping[str, float], Mapping[str, float]],
    *,
    clearance: float = 0.012,
) -> bool:
    a, b = first
    c, d = second
    first_dx, first_dy = b["x"] - a["x"], b["y"] - a["y"]
    second_dx, second_dy = d["x"] - c["x"], d["y"] - c["y"]
    first_length = math.hypot(first_dx, first_dy)
    second_length = math.hypot(second_dx, second_dy)
    if first_length <= 1e-9 or second_length <= 1e-9:
        return False
    ux, uy = first_dx / first_length, first_dy / first_length
    vx, vy = second_dx / second_length, second_dy / second_length
    angular_delta = math.degrees(math.acos(min(1.0, max(-1.0, abs(ux * vx + uy * vy)))))
    if angular_delta > 12.0:
        return False
    second_projection = (
        (c["x"] - a["x"]) * ux + (c["y"] - a["y"]) * uy,
        (d["x"] - a["x"]) * ux + (d["y"] - a["y"]) * uy,
    )
    overlap = min(first_length, max(second_projection)) - max(0.0, min(second_projection))
    if overlap <= 0.025:
        return False
    distances = (
        abs((c["x"] - a["x"]) * uy - (c["y"] - a["y"]) * ux),
        abs((d["x"] - a["x"]) * uy - (d["y"] - a["y"]) * ux),
    )
    return min(distances) < clearance


PARTS_MANUAL_MIN_BALLOON_GAP = 0.075
PARTS_MANUAL_TINY_ANCHOR_AREA = 0.00035
PARTS_MANUAL_LEADER_STYLES = frozenset({"straight", "orthogonal"})
# Automatic generation emits one balloon, one leader and one representative
# anchor for a repeated part. "branched" stays a supported layout, reachable
# only through an explicit user-authored documentation override.
PARTS_MANUAL_DEFAULT_REPEATED_PART_STRATEGY = "representative_with_count"
PARTS_MANUAL_REPEATED_PART_STRATEGIES = frozenset(
    {"representative_with_count", "branched"}
)
PARTS_MANUAL_TARGET_BALLOON_GAP = 0.105
PARTS_MANUAL_FRAME_MARGIN_X = 0.030
PARTS_MANUAL_FRAME_MARGIN_Y = 0.035
PARTS_MANUAL_SOFT_PARALLEL_DEGREES = 15.0
PARTS_MANUAL_SOFT_PARALLEL_CLEARANCE = 0.060
PARTS_MANUAL_LANE_TOLERANCE = 0.006


def _segment_angle_degrees(segment) -> float:
    start, end = segment
    angle = math.degrees(math.atan2(end["y"] - start["y"], end["x"] - start["x"]))
    return angle % 180.0


def _segment_length(segment) -> float:
    start, end = segment
    return math.hypot(end["x"] - start["x"], end["y"] - start["y"])


def _minimum_balloon_gap(manifest: Sequence[Mapping[str, Any]]) -> float:
    smallest = 1.0
    for index, left in enumerate(manifest):
        for right in manifest[index + 1:]:
            smallest = min(
                smallest,
                math.hypot(
                    float(left["balloon"]["x"]) - float(right["balloon"]["x"]),
                    float(left["balloon"]["y"]) - float(right["balloon"]["y"]),
                ),
            )
    return round(smallest, 6)


def _frame_clip_balloon_count(manifest: Sequence[Mapping[str, Any]]) -> int:
    total = 0
    for row in manifest:
        x = float(row["balloon"]["x"])
        y = float(row["balloon"]["y"])
        if (
            x < PARTS_MANUAL_FRAME_MARGIN_X
            or x > 1 - PARTS_MANUAL_FRAME_MARGIN_X
            or y < PARTS_MANUAL_FRAME_MARGIN_Y
            or y > 1 - PARTS_MANUAL_FRAME_MARGIN_Y
        ):
            total += 1
    return total


def _soft_parallel_pair_count(manifest: Sequence[Mapping[str, Any]]) -> int:
    """Graded companion to the strict axis-aligned congestion counter."""
    total = 0
    for index, left in enumerate(manifest):
        for right in manifest[index + 1:]:
            for left_segment in _callout_segments(left):
                if _segment_length(left_segment) < 0.020:
                    continue
                for right_segment in _callout_segments(right):
                    if _segment_length(right_segment) < 0.020:
                        continue
                    delta = abs(
                        _segment_angle_degrees(left_segment)
                        - _segment_angle_degrees(right_segment)
                    )
                    delta = min(delta, 180.0 - delta)
                    if delta > PARTS_MANUAL_SOFT_PARALLEL_DEGREES:
                        continue
                    left_mid = (
                        (left_segment[0]["x"] + left_segment[1]["x"]) / 2,
                        (left_segment[0]["y"] + left_segment[1]["y"]) / 2,
                    )
                    right_mid = (
                        (right_segment[0]["x"] + right_segment[1]["x"]) / 2,
                        (right_segment[0]["y"] + right_segment[1]["y"]) / 2,
                    )
                    if math.dist(left_mid, right_mid) < PARTS_MANUAL_SOFT_PARALLEL_CLEARANCE:
                        total += 1
    return total


def _elbow_count(row: Mapping[str, Any]) -> int:
    segments = _callout_segments(row)
    elbows = 0
    for index in range(1, len(segments)):
        delta = abs(
            _segment_angle_degrees(segments[index - 1])
            - _segment_angle_degrees(segments[index])
        )
        delta = min(delta, 180.0 - delta)
        if delta > 1.0:
            elbows += 1
    return elbows


def _maximum_elbow_count(manifest: Sequence[Mapping[str, Any]]) -> int:
    return max((_elbow_count(row) for row in manifest), default=0)


def _balloon_lane_aligned_count(manifest: Sequence[Mapping[str, Any]]) -> int:
    """Evidence only. Lane sharing is optimised for, never required."""
    total = 0
    for index, row in enumerate(manifest):
        for other_index, other in enumerate(manifest):
            if index == other_index:
                continue
            if (
                abs(float(row["balloon"]["x"]) - float(other["balloon"]["x"]))
                < PARTS_MANUAL_LANE_TOLERANCE
                or abs(float(row["balloon"]["y"]) - float(other["balloon"]["y"]))
                < PARTS_MANUAL_LANE_TOLERANCE
            ):
                total += 1
                break
    return total


def _repeated_items_without_indication(manifest: Sequence[Mapping[str, Any]]) -> List[int]:
    """Any qty>1 item must carry branches or an explicit count badge."""
    offenders: List[int] = []
    for row in manifest:
        if int(row.get("representativeCount") or 1) <= 1:
            continue
        if row.get("branches"):
            continue
        if str(row.get("calloutType") or "") == "representative_with_count":
            continue
        offenders.append(int(row.get("itemNumber") or 0))
    return sorted(offenders)


def _requested_repeated_strategy(
    request: Mapping[str, Any], expected_row: Mapping[str, Any]
) -> str:
    """The repeated-part strategy this callout is actually entitled to use.

    Automatic generation gets the contract default. Only an explicit
    user-authored leader override may request "branched", so the server can
    reject a branched layout that no user asked for instead of trusting the
    client's word for it.
    """
    contract = request.get("calloutContract")
    default = PARTS_MANUAL_DEFAULT_REPEATED_PART_STRATEGY
    if isinstance(contract, Mapping):
        candidate = str(contract.get("defaultRepeatedPartStrategy") or "")
        if candidate in PARTS_MANUAL_REPEATED_PART_STRATEGIES:
            default = candidate
    composition = request.get("composition")
    if not isinstance(composition, Mapping):
        return default
    leader_overrides = composition.get("leaderOverrides")
    if not isinstance(leader_overrides, Mapping):
        return default
    callout_id = str(
        expected_row.get("calloutId")
        or f"callout-item-{int(expected_row.get('itemNumber') or expected_row.get('item') or 0)}"
    )
    override = leader_overrides.get(callout_id)
    if not isinstance(override, Mapping):
        return default
    requested = str(override.get("repeatedPartStrategy") or "")
    return requested if requested in PARTS_MANUAL_REPEATED_PART_STRATEGIES else default


def _leader_override(
    request: Mapping[str, Any], expected_row: Mapping[str, Any]
) -> Mapping[str, Any]:
    composition = request.get("composition")
    if not isinstance(composition, Mapping):
        return {}
    overrides = composition.get("leaderOverrides")
    if not isinstance(overrides, Mapping):
        return {}
    callout_id = str(
        expected_row.get("calloutId")
        or f"callout-item-{int(expected_row.get('itemNumber') or expected_row.get('item') or 0)}"
    )
    value = overrides.get(callout_id)
    return value if isinstance(value, Mapping) else {}


def _anchor_normal(value: Any) -> Optional[Dict[str, float]]:
    """Screen-space outward normal at the anchor, when the client supplied one."""
    if not isinstance(value, Mapping):
        return None
    try:
        x = float(value.get("x"))
        y = float(value.get("y"))
    except (TypeError, ValueError):
        return None
    magnitude = math.hypot(x, y)
    if not magnitude or not math.isfinite(magnitude):
        return None
    return {"x": round(x / magnitude, 6), "y": round(y / magnitude, 6)}


def _validate_balloons(
    request: Mapping[str, Any],
    balloons: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    expected_rows = [
        row for row in request.get("calloutItems") or [] if isinstance(row, Mapping)
    ]
    expected = {int(row.get("itemNumber") or 0): row for row in expected_rows}
    def normalize_anchor(value: Any, *, field: str) -> Dict[str, Any]:
        if not isinstance(value, Mapping):
            raise PartsManualRenderArtifactError(f"balloon {field} is invalid")
        try:
            raycast_distance = float(value.get("anchorRaycastDistance") or 0.0)
            sample_count = int(value.get("visibleSampleCount") or 0)
        except (TypeError, ValueError) as exc:
            raise PartsManualRenderArtifactError(f"balloon {field} QA is invalid") from exc
        return {
            "occurrenceId": str(value.get("occurrenceId") or ""),
            "target": _normalized_point(value.get("target"), field=f"{field} target"),
            "targetBounds": _normalized_bounds(
                value.get("targetBounds"), field=f"{field} target bounds"
            ),
            "anchorMethod": str(value.get("anchorMethod") or ""),
            "anchorRaycastDistance": round(raycast_distance, 6),
            "visibleSampleCount": sample_count,
            "anchorValidated": value.get("anchorValidated") is True,
            "primary": value.get("primary") is True,
        }

    def normalize_branch(value: Any) -> Dict[str, Any]:
        if not isinstance(value, Mapping):
            raise PartsManualRenderArtifactError("balloon branch is invalid")
        branch = normalize_anchor(value, field="branch anchor")
        branch["leaderPath"] = [
            _normalized_point(point, field="branch leader point")
            for point in value.get("leaderPath") or []
        ]
        try:
            branch["geometryIntersectionCount"] = int(
                value.get("geometryIntersectionCount") or 0
            )
            branch["leaderCrossingCount"] = int(value.get("leaderCrossingCount") or 0)
            branch["routeRaycastSampleCount"] = int(
                value.get("routeRaycastSampleCount") or 0
            )
        except (TypeError, ValueError) as exc:
            raise PartsManualRenderArtifactError("balloon branch QA values are invalid") from exc
        branch["routeValidationMethod"] = str(value.get("routeValidationMethod") or "")
        branch["routeObstructingItemNumbers"] = sorted(
            set(int(item) for item in value.get("routeObstructingItemNumbers") or [])
        )
        branch["routingValidated"] = value.get("routingValidated") is True
        return branch

    supplied_rows = [row for row in balloons if isinstance(row, Mapping)]
    supplied: Dict[int, Dict[str, Any]] = {}
    for row in supplied_rows:
        try:
            item_number = int(row.get("itemNumber") or 0)
        except (TypeError, ValueError) as exc:
            raise PartsManualRenderArtifactError("balloon item number is invalid") from exc
        if item_number < 1 or item_number in supplied:
            raise PartsManualRenderArtifactError("balloon item numbers must be unique positive integers")
        occurrence_ids = sorted(
            set(str(value) for value in row.get("occurrenceIds") or [] if value)
        )
        target = _normalized_point(row.get("target"), field="target")
        target_bounds = _normalized_bounds(row.get("targetBounds"), field="target bounds")
        projected_regions = []
        for region in row.get("projectedRegions") or []:
            if not isinstance(region, Mapping):
                raise PartsManualRenderArtifactError("balloon projected region is invalid")
            projected_regions.append(
                {
                    "occurrenceId": str(region.get("occurrenceId") or ""),
                    "bounds": _normalized_bounds(region.get("bounds"), field="projected region"),
                }
            )
        leader_path = [
            _normalized_point(value, field="leader point")
            for value in row.get("leaderPath") or []
        ]
        balloon = _normalized_point(row.get("balloon"), field="position")
        attachment_source = {
            "target": target,
            "leaderPath": leader_path,
            "balloon": balloon,
        }
        expected_attachment = _balloon_attachment(attachment_source)
        balloon_attachment = _normalized_point(
            row.get("balloonAttachment") or expected_attachment,
            field="balloon attachment",
        )
        if math.hypot(
            balloon_attachment["x"] - expected_attachment["x"],
            balloon_attachment["y"] - expected_attachment["y"],
        ) > 0.003:
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} leader does not terminate on its circumference"
            )
        try:
            visible_sample_count = int(row.get("visibleSampleCount") or 0)
            anchor_raycast_distance = float(row.get("anchorRaycastDistance") or 0.0)
            geometry_intersections = int(row.get("geometryIntersectionCount") or 0)
            leader_crossings = int(row.get("leaderCrossingCount") or 0)
            route_sample_count = int(row.get("routeRaycastSampleCount") or 0)
            branch_sample_count = int(row.get("branchRouteRaycastSampleCount") or 0)
            representative_count = int(row.get("representativeCount") or 1)
        except (TypeError, ValueError) as exc:
            raise PartsManualRenderArtifactError("balloon callout QA values are invalid") from exc
        sampling_value = row.get("samplingEvidence") or {}
        if not isinstance(sampling_value, Mapping):
            raise PartsManualRenderArtifactError("balloon anchor sampling evidence is invalid")
        try:
            sampling_evidence = {
                "adaptive": sampling_value.get("adaptive") is True,
                "passCount": max(0, int(sampling_value.get("passCount") or 0)),
                "probeCount": max(0, int(sampling_value.get("probeCount") or 0)),
                "maxDivisions": max(0, int(sampling_value.get("maxDivisions") or 0)),
                "maxProbeCountPerOccurrence": max(
                    0, int(sampling_value.get("maxProbeCountPerOccurrence") or 0)
                ),
            }
        except (TypeError, ValueError) as exc:
            raise PartsManualRenderArtifactError(
                "balloon anchor sampling evidence is invalid"
            ) from exc
        supplied[item_number] = {
            "itemNumber": item_number,
            "occurrenceIds": occurrence_ids,
            "target": target,
            "balloon": balloon,
            "balloonAttachment": balloon_attachment,
            "leaderPath": leader_path,
            "anchorNormal": _anchor_normal(row.get("anchorNormal")),
            "anchorSalience": float(row.get("anchorSalience") or 0.0),
            "anchorOnSilhouette": bool(row.get("anchorOnSilhouette")),
            "samplingEvidence": sampling_evidence,
            "targetBounds": target_bounds,
            "projectedRegions": projected_regions,
            "anchorMethod": str(row.get("anchorMethod") or ""),
            "anchorOccurrenceId": str(row.get("anchorOccurrenceId") or ""),
            "anchorRaycastDistance": round(anchor_raycast_distance, 6),
            "visibleSampleCount": visible_sample_count,
            "anchorValidated": row.get("anchorValidated") is True,
            "anchorScope": str(row.get("anchorScope") or ""),
            "manualGroupId": str(row.get("manualGroupId") or ""),
            "calloutType": str(row.get("calloutType") or ""),
            "anchors": [normalize_anchor(value, field="anchor") for value in row.get("anchors") or []],
            "branches": [normalize_branch(value) for value in row.get("branches") or []],
            "representativeCount": representative_count,
            "quantityLabel": str(row.get("quantityLabel") or ""),
            "repeatedStrategyValidated": row.get("repeatedStrategyValidated") is True,
            "repeatedPartStrategySource": str(row.get("repeatedPartStrategySource") or ""),
            "routeSide": str(row.get("routeSide") or ""),
            "leaderStyle": str(row.get("leaderStyle") or ""),
            "endCondition": str(
                row.get("endCondition") or PARTS_MANUAL_DEFAULT_END_CONDITION
            ),
            "geometryIntersectionCount": geometry_intersections,
            "leaderCrossingCount": leader_crossings,
            "routeValidationMethod": str(row.get("routeValidationMethod") or ""),
            "routeRaycastSampleCount": route_sample_count,
            "branchRouteRaycastSampleCount": branch_sample_count,
            "routeObstructingItemNumbers": sorted(
                set(int(value) for value in row.get("routeObstructingItemNumbers") or [])
            ),
            "routingValidated": row.get("routingValidated") is True,
        }
    if set(supplied) != set(expected):
        missing = sorted(set(expected) - set(supplied))
        extra = sorted(set(supplied) - set(expected))
        detail = []
        if missing:
            detail.append("missing " + ", ".join(map(str, missing)))
        if extra:
            detail.append("unexpected " + ", ".join(map(str, extra)))
        raise PartsManualRenderArtifactError(
            "balloon manifest does not match the page BOM/group index (" + "; ".join(detail) + ")"
        )
    for item_number, expected_row in expected.items():
        expected_ids = sorted(
            set(str(value) for value in expected_row.get("occurrenceIds") or [] if value)
        )
        if supplied[item_number]["occurrenceIds"] != expected_ids:
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} does not reference the expected component occurrences"
            )
        callout = supplied[item_number]
        expected_end_condition = str(
            expected_row.get("endCondition") or PARTS_MANUAL_DEFAULT_END_CONDITION
        )
        if callout["endCondition"] not in {"arrow", "dot", "none"}:
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} uses an unsupported leader end condition"
            )
        if callout["endCondition"] != expected_end_condition:
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} does not use its authored leader end condition"
            )
        expected_scope = str(
            expected_row.get("anchorScope")
            or ("manual_group" if expected_row.get("sectionId") else "component_instance")
        )
        if callout["anchorScope"] != expected_scope:
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} uses the wrong semantic anchor scope"
            )
        if expected_scope == "manual_group":
            if (
                callout["calloutType"] != "group"
                or callout["manualGroupId"] != str(expected_row.get("sectionId") or "")
            ):
                raise PartsManualRenderArtifactError(
                    f"balloon {item_number} does not identify its complete manual group"
                )
        elif len(expected_ids) > 1:
            if callout["calloutType"] not in PARTS_MANUAL_REPEATED_PART_STRATEGIES or not callout[
                "repeatedStrategyValidated"
            ]:
                raise PartsManualRenderArtifactError(
                    f"balloon {item_number} has no validated repeated-part strategy"
                )
            if callout["representativeCount"] != len(expected_ids):
                raise PartsManualRenderArtifactError(
                    f"balloon {item_number} repeated-part count does not match the BOM quantity"
                )
            # A split leader is only ever legitimate when a user asked for one.
            # Without this the client could still hand back a branched layout and
            # the server would take its word for it.
            if (
                callout["calloutType"] == "branched"
                and _requested_repeated_strategy(request, expected_row) != "branched"
            ):
                raise PartsManualRenderArtifactError(
                    f"balloon {item_number} uses a branched leader that no documentation "
                    f"override requested; automatic generation must use "
                    f"{PARTS_MANUAL_DEFAULT_REPEATED_PART_STRATEGY}"
                )
        elif callout["calloutType"] != "single":
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} must use a single-component callout"
            )
        if callout["anchorMethod"] != "frontmost_camera_raycast" or not callout["anchorValidated"]:
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} does not have a validated visible-geometry anchor"
            )
        if callout["anchorOccurrenceId"] not in expected_ids:
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} anchor is not tied to an expected component occurrence"
            )
        if callout["visibleSampleCount"] < 1 or callout["anchorRaycastDistance"] < 0:
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} visible-geometry proof is invalid"
            )
        bounds = callout["targetBounds"]
        target = callout["target"]
        if not (
            bounds["left"] - 0.002 <= target["x"] <= bounds["right"] + 0.002
            and bounds["top"] - 0.002 <= target["y"] <= bounds["bottom"] + 0.002
        ):
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} endpoint floats outside its projected target geometry"
            )
        matching_region = any(
            region["occurrenceId"] == callout["anchorOccurrenceId"]
            and all(abs(region["bounds"][key] - bounds[key]) <= 0.002 for key in bounds)
            for region in callout["projectedRegions"]
        )
        if not matching_region:
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} target bounds do not match its projected component"
            )
        if not callout["anchors"]:
            raise PartsManualRenderArtifactError(f"balloon {item_number} has no structured anchor")
        primary_anchors = [anchor for anchor in callout["anchors"] if anchor["primary"]]
        if len(primary_anchors) != 1:
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} must have exactly one primary anchor"
            )
        if (
            primary_anchors[0]["occurrenceId"] != callout["anchorOccurrenceId"]
            or primary_anchors[0]["target"] != callout["target"]
            or primary_anchors[0]["targetBounds"] != callout["targetBounds"]
        ):
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} primary anchor does not match its leader endpoint"
            )
        if callout["leaderStyle"] not in PARTS_MANUAL_LEADER_STYLES:
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} uses an unsupported leader style"
            )
        if callout["routeSide"] not in {"left", "right", "top", "bottom"}:
            raise PartsManualRenderArtifactError(f"balloon {item_number} route side is invalid")
        route_override = _leader_override(request, expected_row)
        requested_style = str(route_override.get("leaderStyle") or "auto")
        if requested_style in {"straight", "orthogonal"} and callout[
            "leaderStyle"
        ] != requested_style:
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} does not use its authored leader style"
            )
        if callout["leaderStyle"] == "straight":
            if callout["leaderPath"]:
                raise PartsManualRenderArtifactError(
                    f"balloon {item_number} straight leader must not contain elbows"
                )
        else:
            if not 1 <= len(callout["leaderPath"]) <= 2:
                raise PartsManualRenderArtifactError(
                    f"balloon {item_number} must use a bounded orthogonal leader"
                )
            if not all(_is_orthogonal(start, end) for start, end in _callout_segments(callout)):
                raise PartsManualRenderArtifactError(
                    f"balloon {item_number} orthogonal leader contains a diagonal segment"
                )
            manual_corridor = isinstance(route_override.get("corridorTranslation"), list)
            maximum_elbows = 2 if manual_corridor or requested_style == "orthogonal" else 1
            if _elbow_count(callout) > maximum_elbows:
                raise PartsManualRenderArtifactError(
                    f"balloon {item_number} automatic orthogonal fallback exceeds one elbow"
                )
        callout["visibleLeaderLength"] = round(_callout_leader_length(callout), 6)
        callout["leaderDetourRatio"] = round(_leader_detour_ratio(callout), 6)
        callout["leaderBalloonCollisionCount"] = 0
        callout["nearParallelCongestionCount"] = 0
        callout["edgeLaneFallback"] = bool(
            callout["balloon"]["x"] <= 0.055
            or callout["balloon"]["x"] >= 0.945
            or callout["balloon"]["y"] <= 0.055
            or callout["balloon"]["y"] >= 0.945
        )
        if callout["visibleLeaderLength"] < 0.08:
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} leader is too short to remain visible"
            )
        if callout["visibleLeaderLength"] > 0.55:
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} leader is too long for a readable technical callout"
            )
        if callout["leaderDetourRatio"] > 2.25:
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} leader takes an excessive detour"
            )
        if (
            callout["routeValidationMethod"] != "frontmost_raycast_sampling"
            or callout["routeRaycastSampleCount"] < 2
            or callout["routeObstructingItemNumbers"]
            or callout["geometryIntersectionCount"] != 0
        ):
            raise PartsManualRenderArtifactError(
                f"balloon {item_number} leader does not have a clear camera-raycast route "
                f"(hits {callout['routeObstructingItemNumbers']}; side {callout['routeSide']}; "
                f"path {[callout['target'], *callout['leaderPath'], callout['balloonAttachment']]})"
            )
        if callout["calloutType"] == "branched":
            anchor_ids = sorted(anchor["occurrenceId"] for anchor in callout["anchors"])
            branch_ids = sorted(branch["occurrenceId"] for branch in callout["branches"])
            if anchor_ids != expected_ids or branch_ids != sorted(
                set(expected_ids) - {callout["anchorOccurrenceId"]}
            ):
                raise PartsManualRenderArtifactError(
                    f"balloon {item_number} branches do not account for every repeated component"
                )
            main_segments = _callout_segments(callout)
            for branch in callout["branches"]:
                branch_segments = list(
                    zip(
                        [branch["target"], *branch["leaderPath"]][:-1],
                        [branch["target"], *branch["leaderPath"]][1:],
                    )
                )
                if not branch_segments or not 1 <= len(branch["leaderPath"]) <= 5:
                    raise PartsManualRenderArtifactError(
                        f"balloon {item_number} branch must contain 1 to 5 routed points"
                    )
                if not all(_is_orthogonal(start, end) for start, end in branch_segments):
                    raise PartsManualRenderArtifactError(
                        f"balloon {item_number} branch contains a diagonal segment"
                    )
                branch["visibleLeaderLength"] = round(
                    sum(
                        abs(start["x"] - end["x"]) + abs(start["y"] - end["y"])
                        for start, end in branch_segments
                    ),
                    6,
                )
                branch_direct = abs(
                    branch["target"]["x"] - branch["leaderPath"][-1]["x"]
                ) + abs(branch["target"]["y"] - branch["leaderPath"][-1]["y"])
                branch["leaderDetourRatio"] = round(
                    branch["visibleLeaderLength"] / max(0.025, branch_direct),
                    6,
                )
                if branch["visibleLeaderLength"] > 0.55:
                    raise PartsManualRenderArtifactError(
                        f"balloon {item_number} branch is too long for a readable technical callout"
                    )
                if branch["leaderDetourRatio"] > 2.25:
                    raise PartsManualRenderArtifactError(
                        f"balloon {item_number} branch takes an excessive detour"
                    )
                branch_anchor = next(
                    (anchor for anchor in callout["anchors"] if anchor["occurrenceId"] == branch["occurrenceId"]),
                    None,
                )
                if not branch_anchor or branch_anchor["target"] != branch["target"]:
                    raise PartsManualRenderArtifactError(
                        f"balloon {item_number} branch is detached from its structured anchor"
                    )
                matching_branch_region = any(
                    region["occurrenceId"] == branch["occurrenceId"]
                    and all(
                        abs(region["bounds"][key] - branch["targetBounds"][key]) <= 0.002
                        for key in branch["targetBounds"]
                    )
                    for region in callout["projectedRegions"]
                )
                if not matching_branch_region:
                    raise PartsManualRenderArtifactError(
                        f"balloon {item_number} branch endpoint floats outside its intended component"
                    )
                if (
                    branch["anchorMethod"] != "frontmost_camera_raycast"
                    or not branch["anchorValidated"]
                    or branch["visibleSampleCount"] < 1
                    or branch["routeValidationMethod"] != "frontmost_raycast_sampling"
                    or branch["routeRaycastSampleCount"] < 2
                    or branch["routeObstructingItemNumbers"]
                    or branch["geometryIntersectionCount"] != 0
                    or branch["leaderCrossingCount"] != 0
                    or not branch["routingValidated"]
                ):
                    raise PartsManualRenderArtifactError(
                        f"balloon {item_number} branch does not have a clear validated route"
                    )
                junction = branch["leaderPath"][-1]
                if not any(
                    _segment_intersects_bounds(
                        segment,
                        {
                            "left": junction["x"] - 0.00001,
                            "right": junction["x"] + 0.00001,
                            "top": junction["y"] - 0.00001,
                            "bottom": junction["y"] + 0.00001,
                        },
                        padding=0.00002,
                    )
                    for segment in main_segments
                ):
                    raise PartsManualRenderArtifactError(
                        f"balloon {item_number} branch does not join the shared leader trunk"
                    )
        elif callout["calloutType"] == "representative_with_count":
            if callout["quantityLabel"] != f"{len(expected_ids)}X" or len(callout["anchors"]) != 1:
                raise PartsManualRenderArtifactError(
                    f"balloon {item_number} representative count label is invalid"
                )
    ordered_balloons = [supplied[item_number] for item_number in sorted(supplied)]
    for index, left in enumerate(ordered_balloons):
        for right in ordered_balloons[index + 1 :]:
            if (
                abs(left["balloon"]["x"] - right["balloon"]["x"]) < 0.045
                and abs(left["balloon"]["y"] - right["balloon"]["y"]) < 0.05
            ):
                raise PartsManualRenderArtifactError(
                    f"balloons {left['itemNumber']} and {right['itemNumber']} overlap"
                )
            left_segments = [*_callout_segments(left)]
            right_segments = [*_callout_segments(right)]
            left_segments.extend(
                segment
                for branch in left.get("branches") or []
                for segment in zip(
                    [branch["target"], *branch["leaderPath"]][:-1],
                    [branch["target"], *branch["leaderPath"]][1:],
                )
            )
            right_segments.extend(
                segment
                for branch in right.get("branches") or []
                for segment in zip(
                    [branch["target"], *branch["leaderPath"]][:-1],
                    [branch["target"], *branch["leaderPath"]][1:],
                )
            )
            left_balloon_bounds = _balloon_bounds(left["balloon"])
            right_balloon_bounds = _balloon_bounds(right["balloon"])
            left_hits_right_balloon = any(
                _segment_intersects_bounds(segment, right_balloon_bounds, padding=0.001)
                for segment in left_segments
            )
            right_hits_left_balloon = any(
                _segment_intersects_bounds(segment, left_balloon_bounds, padding=0.001)
                for segment in right_segments
            )
            if left_hits_right_balloon or right_hits_left_balloon:
                left["leaderBalloonCollisionCount"] += int(left_hits_right_balloon)
                right["leaderBalloonCollisionCount"] += int(right_hits_left_balloon)
                raise PartsManualRenderArtifactError(
                    f"balloon leaders {left['itemNumber']} and {right['itemNumber']} "
                    "intersect another balloon"
                )
            if any(
                _segments_cross(left_segment, right_segment)
                for left_segment in left_segments
                for right_segment in right_segments
            ):
                raise PartsManualRenderArtifactError(
                    f"balloon leaders {left['itemNumber']} and {right['itemNumber']} cross; "
                    f"paths {[left['target'], *left['leaderPath'], left['balloon']]} and "
                    f"{[right['target'], *right['leaderPath'], right['balloon']]}"
                )
            near_parallel = sum(
                1
                for left_segment in left_segments
                for right_segment in right_segments
                if _segments_nearly_parallel(left_segment, right_segment)
            )
            if near_parallel:
                left["nearParallelCongestionCount"] += near_parallel
                right["nearParallelCongestionCount"] += near_parallel
                raise PartsManualRenderArtifactError(
                    f"balloon leaders {left['itemNumber']} and {right['itemNumber']} "
                    "run too closely in parallel"
                )
    for row in ordered_balloons:
        if row["leaderCrossingCount"] != 0 or not row["routingValidated"]:
            raise PartsManualRenderArtifactError(
                f"balloon {row['itemNumber']} submitted routing status is inconsistent with its geometry"
            )
    return ordered_balloons


def validate_balloon_manifest(
    request: Mapping[str, Any],
    balloons: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Validate a technical-illustration callout manifest for document reuse."""

    return _validate_balloons(request, balloons)


def _render_quality(image: Image.Image, expected: Mapping[str, Any]) -> Dict[str, Any]:
    sample = image.convert("RGB")
    sample.thumbnail((512, 384), Image.Resampling.LANCZOS)
    width, height = sample.size
    pixels = sample.load()
    corners = [
        pixels[0, 0],
        pixels[max(0, width - 1), 0],
        pixels[0, max(0, height - 1)],
        pixels[max(0, width - 1), max(0, height - 1)],
    ]
    background = tuple(sorted(value[index] for value in corners)[len(corners) // 2] for index in range(3))
    if str(expected.get("background") or "") == "technical_white" and min(background) < 225:
        raise PartsManualRenderArtifactError(
            "technical illustration background must be white or near-white"
        )
    points: List[tuple[int, int]] = []
    foreground_pixels = 0
    colored_foreground_pixels = 0
    for y in range(height):
        for x in range(width):
            red, green, blue = pixels[x, y]
            difference = abs(red - background[0]) + abs(green - background[1]) + abs(blue - background[2])
            if difference > 42:
                foreground_pixels += 1
                points.append((x, y))
                if max(red, green, blue) - min(red, green, blue) > 18:
                    colored_foreground_pixels += 1
    foreground_fraction = foreground_pixels / max(1, width * height)
    minimum_pixel_percent = float(expected.get("minimumForegroundPixelPercent") or 0.2)
    foreground_pixel_policy = str(
        expected.get("foregroundPixelPolicy") or "minimum_foreground_pixel_percent"
    )
    if not points or foreground_fraction * 100 < minimum_pixel_percent:
        raise PartsManualRenderArtifactError("technical illustration is blank or contains too little visible geometry")
    illustration_style = str(expected.get("illustrationStyle") or "SHADED_COLOR").upper()
    colored_fraction = colored_foreground_pixels / max(1, foreground_pixels)
    if illustration_style == "HIDDEN_LINES_REMOVED" and colored_fraction > 0.02:
        raise PartsManualRenderArtifactError(
            "hidden-lines-removed illustration contains shaded or colored model pixels "
            f"({colored_fraction:.1%}; maximum 2.0%)"
        )
    left = min(point[0] for point in points)
    top = min(point[1] for point in points)
    right = max(point[0] for point in points)
    bottom = max(point[1] for point in points)
    width_fraction = (right - left + 1) / width
    height_fraction = (bottom - top + 1) / height
    # Publication occupancy is the area of the visible-geometry bounding box,
    # not its longest axis. The old longest-axis score allowed a tall, narrow
    # render to pass while leaving most of the illustration region empty.
    occupancy = width_fraction * height_fraction
    minimum = float(expected.get("minimumForegroundOccupancy") or 0.0)
    maximum = float(expected.get("maximumForegroundOccupancy") or 1.0)
    maximum_axis = float(expected.get("maximumForegroundAxisOccupancy") or 1.0)
    axis_tolerance = max(
        0.0,
        min(0.10, float(expected.get("axisConstrainedFillTolerance") or 0.02)),
    )
    uniform_axis_scale = min(
        maximum_axis / max(width_fraction, 1e-9),
        maximum_axis / max(height_fraction, 1e-9),
    )
    axis_limited_maximum = occupancy * uniform_axis_scale * uniform_axis_scale
    fills_axis_limit = max(width_fraction, height_fraction) >= maximum_axis - axis_tolerance
    axis_constrained = bool(
        expected.get("axisConstrainedOccupancyPolicy")
        == "allow_when_uniform_scale_exceeds_axis_limit"
        and occupancy < minimum
        and axis_limited_maximum < minimum
        and fills_axis_limit
    )
    if occupancy < minimum and not axis_constrained:
        raise PartsManualRenderArtifactError(
            f"technical illustration framing is too small ({occupancy:.1%}; minimum {minimum:.1%})"
        )
    if occupancy > maximum or left == 0 or top == 0 or right == width - 1 or bottom == height - 1:
        touched_edges = [
            name
            for name, touched in (
                ("left", left == 0),
                ("top", top == 0),
                ("right", right == width - 1),
                ("bottom", bottom == height - 1),
            )
            if touched
        ]
        edge_detail = f"; touches {', '.join(touched_edges)} edge" if touched_edges else ""
        raise PartsManualRenderArtifactError(
            "technical illustration appears clipped or overfilled "
            f"({occupancy:.1%}; maximum {maximum:.1%}{edge_detail})"
        )
    return {
        "status": "PASS",
        "backgroundRgb": list(background),
        "foregroundPixelPercent": round(foreground_fraction * 100, 3),
        "minimumForegroundPixelPercent": round(minimum_pixel_percent, 3),
        "foregroundPixelPolicy": foreground_pixel_policy,
        "illustrationStyle": illustration_style,
        "coloredForegroundPercent": round(colored_fraction * 100, 3),
        "foregroundOccupancy": round(occupancy, 4),
        "foregroundOccupancyMetric": "bounding_box_area",
        "axisConstrainedOccupancyAccepted": axis_constrained,
        "axisLimitedMaximumOccupancy": round(axis_limited_maximum, 4),
        "foregroundWidthFraction": round(width_fraction, 4),
        "foregroundHeightFraction": round(height_fraction, 4),
        "foregroundBounds": {
            "left": round(left / width, 4),
            "top": round(top / height, 4),
            "right": round((right + 1) / width, 4),
            "bottom": round((bottom + 1) / height, 4),
        },
    }


def store_render_artifact(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
    page_id: str,
    png_bytes: bytes,
    *,
    balloons: Iterable[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    page = _page_for_render(document, page_id)
    request = page["renderRequest"]
    expected = request.get("image")
    expected = expected if isinstance(expected, Mapping) else {}
    if not isinstance(png_bytes, bytes) or not png_bytes.startswith(_PNG_SIGNATURE):
        raise PartsManualRenderArtifactError("render artifact must be a PNG image")
    try:
        with Image.open(io.BytesIO(png_bytes)) as image:
            image.verify()
        with Image.open(io.BytesIO(png_bytes)) as image:
            width, height = image.size
            quality = _render_quality(image, expected)
    except PartsManualRenderArtifactError:
        raise
    except Exception as exc:
        raise PartsManualRenderArtifactError("render artifact PNG is invalid") from exc
    minimum_width = int(expected.get("minimumWidthPx") or 1)
    minimum_height = int(expected.get("minimumHeightPx") or 1)
    if width < minimum_width or height < minimum_height:
        raise PartsManualRenderArtifactError(
            f"render artifact must be at least {minimum_width} x {minimum_height} pixels"
        )
    balloon_manifest = _validate_balloons(request, balloons)
    expected_by_item = {
        int(row.get("itemNumber") or row.get("item") or 0): row
        for row in request.get("calloutItems") or []
        if isinstance(row, Mapping)
    }
    automatic_rows = [
        row
        for row in balloon_manifest
        if not any(
            key in _leader_override(request, expected_by_item.get(row["itemNumber"], {}))
            for key in ("leaderStyle", "corridorTranslation")
        )
    ]
    server_recomputed_metrics = {
        "balloonCount": len(balloon_manifest),
        "groupAnchorCount": sum(
            1 for row in balloon_manifest if row["anchorScope"] == "manual_group"
        ),
        "branchedCalloutCount": sum(
            1 for row in balloon_manifest if row["calloutType"] == "branched"
        ),
        # Branched callouts the client produced without a user override behind
        # them. _validate_balloons rejects those outright, so a published page
        # always reports zero here; the metric makes that visible in QA evidence.
        "automaticBranchedCalloutCount": sum(
            1
            for row in balloon_manifest
            if row["calloutType"] == "branched"
            and row["repeatedPartStrategySource"] != "user_override"
        ),
        "representativeCountCalloutCount": sum(
            1
            for row in balloon_manifest
            if row["calloutType"] == "representative_with_count"
        ),
        "branchCount": sum(len(row["branches"]) for row in balloon_manifest),
        # Endpoint census. Automatic pages carry only dots; an arrow here means a
        # user explicitly asked for one on that leader.
        "dotEndConditionCount": sum(
            1 for row in balloon_manifest if row["endCondition"] == "dot"
        ),
        "arrowEndConditionCount": sum(
            1 for row in balloon_manifest if row["endCondition"] == "arrow"
        ),
        "straightLeaderCount": sum(
            1 for row in balloon_manifest if row["leaderStyle"] == "straight"
        ),
        "orthogonalLeaderCount": sum(
            1 for row in balloon_manifest if row["leaderStyle"] == "orthogonal"
        ),
        "automaticOrthogonalFallbackCount": sum(
            1 for row in automatic_rows if row["leaderStyle"] == "orthogonal"
        ),
        "maximumAutomaticElbowCount": max(
            (_elbow_count(row) for row in automatic_rows), default=0
        ),
        "balloonCircumferenceAttachmentCount": len(balloon_manifest),
        "minimumVisibleLeaderLength": min(
            (row["visibleLeaderLength"] for row in balloon_manifest),
            default=0.0,
        ),
        "maximumVisibleLeaderLength": max(
            (row["visibleLeaderLength"] for row in balloon_manifest),
            default=0.0,
        ),
        "maximumLeaderDetourRatio": max(
            (row["leaderDetourRatio"] for row in balloon_manifest),
            default=0.0,
        ),
        "totalLeaderLength": round(
            sum(
                row["visibleLeaderLength"]
                + sum(
                    float(branch.get("visibleLeaderLength") or 0.0)
                    for branch in row["branches"]
                )
                for row in balloon_manifest
            ),
            6,
        ),
        "minimumBalloonGap": _minimum_balloon_gap(balloon_manifest),
        "frameClipBalloonCount": _frame_clip_balloon_count(balloon_manifest),
        "softParallelPairCount": _soft_parallel_pair_count(balloon_manifest),
        "maximumElbowCount": _maximum_elbow_count(balloon_manifest),
        "balloonLaneAlignedCount": _balloon_lane_aligned_count(balloon_manifest),
        "repeatedItemsWithoutIndication": _repeated_items_without_indication(
            balloon_manifest
        ),
        "edgeLaneBalloonCount": sum(
            1 for row in balloon_manifest if row["edgeLaneFallback"]
        ),
        "leaderBalloonCollisionCount": sum(
            row["leaderBalloonCollisionCount"] for row in balloon_manifest
        ),
        "nearParallelCongestionCount": sum(
            row["nearParallelCongestionCount"] for row in balloon_manifest
        ),
        # Pairwise leader crossings are independently checked above from the
        # normalized manifest coordinates. A non-zero value never reaches here.
        "leaderCrossingCount": 0,
    }
    client_validated_geometry_evidence = {
        "anchorMethod": "frontmost_camera_raycast",
        "routeValidationMethod": "frontmost_raycast_sampling",
        "visibleAnchorCount": sum(1 for row in balloon_manifest if row["anchorValidated"]),
        "tinyAnchorCount": sum(
            1 for row in balloon_manifest
            if 0 < float(row.get("anchorSalience") or 0.0)
            < PARTS_MANUAL_TINY_ANCHOR_AREA
        ),
        "silhouetteAnchorCount": sum(
            1 for row in balloon_manifest if row.get("anchorOnSilhouette")
        ),
        "normalOrientedAnchorCount": sum(
            1 for row in balloon_manifest if row.get("anchorNormal")
        ),
        "adaptiveSamplingCalloutCount": sum(
            1
            for row in balloon_manifest
            if (row.get("samplingEvidence") or {}).get("adaptive")
        ),
        "anchorSamplingProbeCount": sum(
            int((row.get("samplingEvidence") or {}).get("probeCount") or 0)
            for row in balloon_manifest
        ),
        "maximumAnchorSamplingPassCount": max(
            (
                int((row.get("samplingEvidence") or {}).get("passCount") or 0)
                for row in balloon_manifest
            ),
            default=0,
        ),
        "routeRaycastSampleCount": sum(
            row["routeRaycastSampleCount"] + row["branchRouteRaycastSampleCount"]
            for row in balloon_manifest
        ),
        "reportedLeaderCrossingCount": sum(
            row["leaderCrossingCount"] for row in balloon_manifest
        ),
        "reportedGeometryIntersectionCount": sum(
            row["geometryIntersectionCount"] for row in balloon_manifest
        ),
    }
    quality["calloutQuality"] = {
        "status": "PASS",
        "leaderStyle": str(
            (request.get("calloutContract") or {}).get("leaderStyle")
            or "auto_straight_first"
        ),
        "serverRecomputedMetrics": server_recomputed_metrics,
        "clientValidatedGeometryEvidence": client_validated_geometry_evidence,
        # Flat aliases remain for current PDF/tests while callers migrate to the
        # provenance-specific blocks above. They no longer carry a blanket source label.
        **server_recomputed_metrics,
        "anchorMethod": client_validated_geometry_evidence["anchorMethod"],
        "routeValidationMethod": client_validated_geometry_evidence[
            "routeValidationMethod"
        ],
        "visibleAnchorCount": client_validated_geometry_evidence["visibleAnchorCount"],
        "tinyAnchorCount": client_validated_geometry_evidence["tinyAnchorCount"],
        "silhouetteAnchorCount": client_validated_geometry_evidence[
            "silhouetteAnchorCount"
        ],
        "normalOrientedAnchorCount": client_validated_geometry_evidence[
            "normalOrientedAnchorCount"
        ],
        "routeRaycastSampleCount": client_validated_geometry_evidence[
            "routeRaycastSampleCount"
        ],
        "geometryIntersectionCount": client_validated_geometry_evidence[
            "reportedGeometryIntersectionCount"
        ],
    }

    document_revision = str(document.get("documentRevision") or "")
    image_path, metadata_path = _artifact_paths(
        root,
        assembly_number,
        document_revision,
        page_id,
    )
    digest = hashlib.sha256(png_bytes).hexdigest()
    descriptor: Dict[str, Any] = {
        "status": "ready",
        "renderPipelineVersion": PARTS_MANUAL_RENDER_PIPELINE_VERSION,
        "pageId": page_id,
        "mimeType": "image/png",
        "widthPx": width,
        "heightPx": height,
        "byteLength": len(png_bytes),
        "sha256": digest,
        "quality": quality,
        "balloons": balloon_manifest,
        "documentRevision": document_revision,
        "manualPlanRevision": str(document.get("manualPlanRevision") or ""),
        "sourceRevision": str(document.get("sourceRevision") or ""),
        "capturedAt": _utc_now(),
    }
    _write_atomic(image_path, png_bytes)
    _write_atomic(
        metadata_path,
        (json.dumps(descriptor, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("ascii"),
    )
    return descriptor


def _load_descriptor(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
    page_id: str,
) -> Dict[str, Any] | None:
    document_revision = str(document.get("documentRevision") or "")
    image_path, metadata_path = _artifact_paths(root, assembly_number, document_revision, page_id)
    native_image_path = _native_atomic_path(image_path)
    native_metadata_path = _native_atomic_path(metadata_path)
    if not os.path.isfile(native_image_path) or not os.path.isfile(native_metadata_path):
        return None
    try:
        with open(native_metadata_path, "r", encoding="ascii") as handle:
            descriptor = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    expected = {
        "status": "ready",
        "renderPipelineVersion": PARTS_MANUAL_RENDER_PIPELINE_VERSION,
        "pageId": page_id,
        "documentRevision": document_revision,
        "manualPlanRevision": str(document.get("manualPlanRevision") or ""),
        "sourceRevision": str(document.get("sourceRevision") or ""),
    }
    if not isinstance(descriptor, dict) or any(descriptor.get(key) != value for key, value in expected.items()):
        return None
    if (descriptor.get("quality") or {}).get("status") != "PASS":
        return None
    try:
        if os.stat(native_image_path).st_size != int(descriptor.get("byteLength") or -1):
            return None
    except OSError:
        return None
    descriptor = copy.deepcopy(descriptor)
    descriptor["url"] = (
        f"/api/parts-manual/{assembly_number}/renders/"
        f"{document_revision}/{page_id}"
    )
    return descriptor


def attach_render_artifacts(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
) -> Dict[str, Any]:
    result = copy.deepcopy(dict(document))
    for page in result.get("pages") or []:
        request = page.get("renderRequest") if isinstance(page, dict) else None
        if not isinstance(request, dict):
            continue
        descriptor = _load_descriptor(root, assembly_number, result, str(page.get("pageId") or ""))
        if descriptor is not None:
            image_request = request.get("image")
            image_request = dict(image_request) if isinstance(image_request, Mapping) else {}
            # A ready artifact is the result of the request, not a replacement
            # for its capture contract. Retaining the contract makes reopen and
            # recapture obey the same framing, HLR, and axis-constrained rules as
            # the initial publication pass.
            request["image"] = {**image_request, **descriptor}
    return result


def render_artifact_path(
    root: str | Path,
    assembly_number: str,
    document_revision: str,
    page_id: str,
) -> Path:
    image_path, metadata_path = _artifact_paths(root, assembly_number, document_revision, page_id)
    native_image_path = _native_atomic_path(image_path)
    native_metadata_path = _native_atomic_path(metadata_path)
    if not os.path.isfile(native_image_path) or not os.path.isfile(native_metadata_path):
        raise PartsManualRenderArtifactError("render artifact not found")
    return Path(native_image_path)
