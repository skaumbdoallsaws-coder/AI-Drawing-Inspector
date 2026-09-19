"""Deterministic, evidence-bounded industrial placement patterns."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from typing import Any, Mapping, Sequence

from .knowledge_foundation import canonical_facility_knowledge_bytes


INDUSTRIAL_PATTERN_VERSION = "facility-industrial-patterns-v1"
INDUSTRIAL_PATTERN_IDS = (
    "assembly_bench_rows",
    "guard_run_closed",
    "guard_run_open",
    "inspection_islands",
    "machine_rows",
    "maintenance_group",
    "packaging_islands",
    "pallet_staging",
    "parking_rows",
    "rack_bank",
    "robot_cell_interior",
    "storage_rows",
)

INDUSTRIAL_PATTERN_REGISTRY = {
    "assembly_bench_rows": {"family": "grid", "bestFor": "assembly benches"},
    "guard_run_closed": {"family": "perimeter", "bestFor": "closed guarded cells"},
    "guard_run_open": {"family": "perimeter", "bestFor": "open-sided guarded cells"},
    "inspection_islands": {"family": "grid", "bestFor": "inspection stations"},
    "machine_rows": {"family": "grid", "bestFor": "machine tools"},
    "maintenance_group": {"family": "grid", "bestFor": "maintenance resources"},
    "packaging_islands": {"family": "grid", "bestFor": "packaging resources"},
    "pallet_staging": {"family": "grid", "bestFor": "pallet staging"},
    "parking_rows": {"family": "grid", "bestFor": "parking and charging"},
    "rack_bank": {"family": "grid", "bestFor": "pallet-rack banks"},
    "robot_cell_interior": {"family": "grid", "bestFor": "guarded-cell resources"},
    "storage_rows": {"family": "grid", "bestFor": "shelving and storage"},
}


class FacilityIndustrialPatternError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = deepcopy(dict(details or {}))


def select_industrial_pattern(asset: Mapping[str, Any]) -> str:
    """Select a geometric pattern from exact catalog semantics, never from identity."""

    definition = asset.get("definition")
    definition = definition if isinstance(definition, Mapping) else {}
    category = str(asset.get("category") or definition.get("category") or "").casefold()
    display_name = str(asset.get("displayName") or definition.get("displayName") or "").casefold()
    tags = " ".join(
        str(item).casefold()
        for item in [*(asset.get("tags") or []), *(definition.get("tags") or [])]
    )
    semantic = " ".join((category, display_name, tags))
    if "guard" in semantic and ("panel" in semantic or "fence" in semantic):
        return "guard_run_closed"
    if "rack" in semantic or "shelving" in semantic or "shelves" in semantic:
        return "rack_bank"
    if "pallet" in semantic and "truck" not in semantic:
        return "pallet_staging"
    if "machine" in category or any(
        token in semantic
        for token in ("cnc", "lathe", "mill", "grinder", "edm", "band saw")
    ):
        return "machine_rows"
    if "workbench" in semantic or "workstation" in semantic:
        return "assembly_bench_rows"
    if "inspection" in semantic or "laboratory" in semantic:
        return "inspection_islands"
    if "packaging" in semantic or "folding worktable" in semantic:
        return "packaging_islands"
    if any(token in semantic for token in ("forklift", "pallet truck", "lift table")):
        return "parking_rows"
    if any(token in semantic for token in ("crane", "cabinet", "tooling", "cart")):
        return "maintenance_group"
    if "robot" in semantic or "operator" in semantic:
        return "robot_cell_interior"
    return "storage_rows"


def _revision(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{_revision(value)[:24]}"


def _rectangle(zone: Mapping[str, Any]) -> tuple[float, float, float, float]:
    points = [
        (float(item["x"]), float(item["z"]))
        for item in zone.get("boundary", [])
        if isinstance(item, Mapping) and "x" in item and "z" in item
    ]
    if len(points) != 4:
        raise FacilityIndustrialPatternError(
            "industrial_pattern_zone_unsupported",
            "Initial industrial patterns require one rectangular target area.",
        )
    xs = sorted({round(item[0], 9) for item in points})
    zs = sorted({round(item[1], 9) for item in points})
    if len(xs) != 2 or len(zs) != 2:
        raise FacilityIndustrialPatternError(
            "industrial_pattern_zone_unsupported",
            "Initial industrial patterns require one axis-aligned target area.",
        )
    return xs[0], zs[0], xs[1], zs[1]


def _footprint(asset: Mapping[str, Any]) -> tuple[float, float]:
    definition = asset.get("definition")
    definition = definition if isinstance(definition, Mapping) else asset
    geometry = definition.get("geometry") if isinstance(definition, Mapping) else None
    geometry = geometry if isinstance(geometry, Mapping) else {}
    aabb = geometry.get("aabb")
    aabb = aabb if isinstance(aabb, Mapping) else {}
    minimum = aabb.get("minimum")
    maximum = aabb.get("maximum")
    if not isinstance(minimum, Mapping) or not isinstance(maximum, Mapping):
        raise FacilityIndustrialPatternError(
            "industrial_pattern_asset_geometry_unavailable",
            "The exact catalog asset has no bounded footprint.",
        )
    width = float(maximum.get("x") or 0.0) - float(minimum.get("x") or 0.0)
    depth = float(maximum.get("z") or 0.0) - float(minimum.get("z") or 0.0)
    if width <= 0 or depth <= 0:
        raise FacilityIndustrialPatternError(
            "industrial_pattern_asset_geometry_unavailable",
            "The exact catalog asset footprint is invalid.",
        )
    return width, depth


def _orientation(
    width: float, depth: float, semantic_orientation: str
) -> tuple[float, float, int]:
    if semantic_orientation == "long_side_east_west":
        return (max(width, depth), min(width, depth), 0 if width >= depth else 90)
    if semantic_orientation == "long_side_north_south":
        return (min(width, depth), max(width, depth), 0 if depth >= width else 90)
    if semantic_orientation in {"catalog_default", "reviewed_reference_transform"}:
        return width, depth, 0
    raise FacilityIndustrialPatternError(
        "industrial_pattern_orientation_invalid",
        "The industrial pattern orientation is unsupported.",
        details={"semanticOrientation": semantic_orientation},
    )


def _quaternion(degrees: int) -> dict[str, float]:
    angle = math.radians(degrees) / 2.0
    return {
        "x": 0.0,
        "y": round(math.sin(angle), 12),
        "z": 0.0,
        "w": round(math.cos(angle), 12),
    }


def _grid_shape(
    quantity: int,
    available_width: float,
    available_depth: float,
    item_width: float,
    item_depth: float,
    gap: float,
    pattern_id: str,
) -> tuple[int, int]:
    candidates = []
    for columns in range(1, quantity + 1):
        rows = math.ceil(quantity / columns)
        envelope_width = columns * item_width + max(0, columns - 1) * gap
        envelope_depth = rows * item_depth + max(0, rows - 1) * gap
        if envelope_width <= available_width + 1.0e-9 and envelope_depth <= available_depth + 1.0e-9:
            if pattern_id in {"machine_rows", "rack_bank", "storage_rows", "parking_rows"}:
                row_penalty = rows
            else:
                row_penalty = abs(columns - rows)
            candidates.append(
                (
                    row_penalty,
                    envelope_width * envelope_depth,
                    rows,
                    columns,
                )
            )
    if not candidates:
        raise FacilityIndustrialPatternError(
            "industrial_pattern_unplaceable",
            "The requested pattern and quantity do not fit the target area.",
            details={"quantity": quantity, "patternId": pattern_id},
        )
    _penalty, _area, rows, columns = min(candidates)
    return rows, columns


def _placement(
    *,
    batch_id: str,
    occurrence: int,
    asset: Mapping[str, Any],
    x: float,
    y: float,
    z: float,
    rotation_degrees: int,
    target_zone_id: str,
    target_area: str,
    pattern_id: str,
    spacing_meters: float,
    spacing_authority: str,
) -> dict[str, Any]:
    asset_id = str(asset.get("assetId") or "")
    revision = str(asset.get("assetDefinitionRevision") or "")
    placement_id = _stable_id(
        "pl-rq-pattern",
        {
            "batchId": batch_id,
            "occurrence": occurrence,
            "assetId": asset_id,
            "assetDefinitionRevision": revision,
            "targetZoneId": target_zone_id,
        },
    )
    return {
        "placementId": placement_id,
        "assetId": asset_id,
        "assetDefinitionRevision": revision,
        "transform": {
            "position": {"x": round(x, 9), "y": round(y, 9), "z": round(z, 9)},
            "quaternion": _quaternion(rotation_degrees),
            "scale": 1.0,
        },
        "positionMode": "auto",
        "snapRelationship": None,
        "zoneIds": [target_zone_id],
        "metadata": {
            "generatedBy": "facility_industrial_patterns_rq3",
            "patternVersion": INDUSTRIAL_PATTERN_VERSION,
            "patternId": pattern_id,
            "batchId": batch_id,
            "occurrenceIndex": occurrence,
            "targetZoneId": target_zone_id,
            "targetArea": target_area,
            "spacingMeters": spacing_meters,
            "spacingAuthority": spacing_authority,
        },
    }


def _compile_grid(
    zone: Mapping[str, Any],
    asset: Mapping[str, Any],
    *,
    batch_id: str,
    quantity: int,
    pattern_id: str,
    semantic_orientation: str,
    spacing_meters: float,
    spacing_authority: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    low_x, low_z, high_x, high_z = _rectangle(zone)
    raw_width, raw_depth = _footprint(asset)
    width, depth, rotation = _orientation(raw_width, raw_depth, semantic_orientation)
    rows, columns = _grid_shape(
        quantity,
        high_x - low_x,
        high_z - low_z,
        width,
        depth,
        spacing_meters,
        pattern_id,
    )
    used_width = columns * width + max(0, columns - 1) * spacing_meters
    used_depth = rows * depth + max(0, rows - 1) * spacing_meters
    start_x = low_x + ((high_x - low_x) - used_width) / 2.0 + width / 2.0
    start_z = low_z + ((high_z - low_z) - used_depth) / 2.0 + depth / 2.0
    values = []
    for index in range(quantity):
        row = index // columns
        column = index % columns
        values.append(
            _placement(
                batch_id=batch_id,
                occurrence=index + 1,
                asset=asset,
                x=start_x + column * (width + spacing_meters),
                y=float(zone.get("floorElevation") or 0.0),
                z=start_z + row * (depth + spacing_meters),
                rotation_degrees=rotation,
                target_zone_id=str(zone.get("zoneId") or ""),
                target_area=str(zone.get("label") or ""),
                pattern_id=pattern_id,
                spacing_meters=spacing_meters,
                spacing_authority=spacing_authority,
            )
        )
    return values, {
        "rows": rows,
        "columns": columns,
        "envelopeWidthMeters": round(used_width, 9),
        "envelopeDepthMeters": round(used_depth, 9),
    }


def _guard_dimensions(
    quantity: int,
    available_width: float,
    available_depth: float,
    panel_length: float,
    *,
    open_side: bool,
) -> tuple[int, int]:
    candidates = []
    for columns in range(2, quantity + 1):
        for rows in range(2, quantity + 1):
            count = (
                columns + 2 * (rows - 1)
                if open_side
                else 2 * columns + 2 * (rows - 2)
            )
            if count != quantity:
                continue
            width = columns * panel_length
            depth = rows * panel_length
            if width <= available_width + 1.0e-9 and depth <= available_depth + 1.0e-9:
                candidates.append((width * depth, abs(width - depth), rows, columns))
    if not candidates:
        raise FacilityIndustrialPatternError(
            "industrial_guard_run_unplaceable",
            "The exact guard-panel quantity cannot form the requested enclosure in this area.",
            details={"quantity": quantity, "openSide": open_side},
        )
    _area, _aspect, rows, columns = min(candidates)
    return rows, columns


def _compile_guard_run(
    zone: Mapping[str, Any],
    asset: Mapping[str, Any],
    *,
    batch_id: str,
    quantity: int,
    pattern_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    low_x, low_z, high_x, high_z = _rectangle(zone)
    width, depth = _footprint(asset)
    panel_length = max(width, depth)
    panel_thickness = min(width, depth)
    open_side = pattern_id == "guard_run_open"
    rows, columns = _guard_dimensions(
        quantity,
        high_x - low_x,
        high_z - low_z,
        panel_length,
        open_side=open_side,
    )
    used_width = columns * panel_length
    used_depth = rows * panel_length
    left = low_x + ((high_x - low_x) - used_width) / 2.0
    bottom = low_z + ((high_z - low_z) - used_depth) / 2.0
    values: list[tuple[float, float, int]] = []
    for column in range(columns):
        x = left + (column + 0.5) * panel_length
        values.append((x, bottom + panel_thickness / 2.0, 90))
        if not open_side:
            values.append((x, bottom + used_depth - panel_thickness / 2.0, 90))
    for row in range(1, rows - (0 if open_side else 1)):
        z = bottom + (row + 0.5) * panel_length
        values.append((left + panel_thickness / 2.0, z, 0))
        values.append((left + used_width - panel_thickness / 2.0, z, 0))
    if len(values) != quantity:
        raise FacilityIndustrialPatternError(
            "industrial_guard_run_count_mismatch",
            "The guard-run solver did not preserve the exact requested quantity.",
        )
    placements = [
        _placement(
            batch_id=batch_id,
            occurrence=index,
            asset=asset,
            x=x,
            y=float(zone.get("floorElevation") or 0.0),
            z=z,
            rotation_degrees=rotation,
            target_zone_id=str(zone.get("zoneId") or ""),
            target_area=str(zone.get("label") or ""),
            pattern_id=pattern_id,
            spacing_meters=0.0,
            spacing_authority="panel_abutment_geometry",
        )
        for index, (x, z, rotation) in enumerate(values, start=1)
    ]
    return placements, {
        "rows": rows,
        "columns": columns,
        "envelopeWidthMeters": round(used_width, 9),
        "envelopeDepthMeters": round(used_depth, 9),
        "contactPolicy": "panel_abutment",
        "openSide": open_side,
    }


def compile_industrial_pattern(
    zone: Mapping[str, Any],
    asset: Mapping[str, Any],
    *,
    batch_id: str,
    quantity: int,
    pattern_id: str,
    semantic_orientation: str = "catalog_default",
    authored_spacing_meters: float | None = None,
    spacing_evidence_ref: str | None = None,
) -> dict[str, Any]:
    """Compile one exact-quantity pattern; never return a partial batch."""

    if pattern_id not in INDUSTRIAL_PATTERN_REGISTRY:
        raise FacilityIndustrialPatternError(
            "industrial_pattern_unknown", "The requested industrial pattern is not registered."
        )
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 900:
        raise FacilityIndustrialPatternError(
            "industrial_pattern_quantity_invalid", "Pattern quantity must be from 1 through 900."
        )
    if authored_spacing_meters is None:
        spacing = 0.0
        spacing_authority = "geometric_packing_only"
    else:
        if (
            isinstance(authored_spacing_meters, bool)
            or not isinstance(authored_spacing_meters, (int, float))
            or float(authored_spacing_meters) < 0
            or not spacing_evidence_ref
        ):
            raise FacilityIndustrialPatternError(
                "industrial_pattern_spacing_authority_invalid",
                "Authored spacing requires a non-negative value and evidence reference.",
            )
        spacing = float(authored_spacing_meters)
        spacing_authority = "user_or_policy_authored"
    if INDUSTRIAL_PATTERN_REGISTRY[pattern_id]["family"] == "perimeter":
        placements, metrics = _compile_guard_run(
            zone,
            asset,
            batch_id=batch_id,
            quantity=quantity,
            pattern_id=pattern_id,
        )
    else:
        placements, metrics = _compile_grid(
            zone,
            asset,
            batch_id=batch_id,
            quantity=quantity,
            pattern_id=pattern_id,
            semantic_orientation=semantic_orientation,
            spacing_meters=spacing,
            spacing_authority=spacing_authority,
        )
    if len(placements) != quantity:
        raise FacilityIndustrialPatternError(
            "industrial_pattern_partial_result",
            "Industrial patterns cannot silently reduce the requested quantity.",
        )
    return {
        "schemaVersion": INDUSTRIAL_PATTERN_VERSION,
        "batchId": batch_id,
        "patternId": pattern_id,
        "targetZoneId": str(zone.get("zoneId") or ""),
        "assetId": str(asset.get("assetId") or ""),
        "assetDefinitionRevision": str(asset.get("assetDefinitionRevision") or ""),
        "requestedQuantity": quantity,
        "placedQuantity": len(placements),
        "spacingMeters": spacing,
        "spacingAuthority": spacing_authority,
        "spacingEvidenceRef": spacing_evidence_ref,
        "operations": [
            {"op": "place_asset", "placement": placement}
            for placement in placements
        ],
        "metrics": metrics,
        "claimBoundary": (
            "This pattern establishes deterministic physical arrangement only; it does "
            "not establish safety, throughput, capacity, access, or regulatory compliance."
        ),
    }


__all__ = [
    "INDUSTRIAL_PATTERN_IDS",
    "INDUSTRIAL_PATTERN_REGISTRY",
    "INDUSTRIAL_PATTERN_VERSION",
    "FacilityIndustrialPatternError",
    "compile_industrial_pattern",
    "select_industrial_pattern",
]
