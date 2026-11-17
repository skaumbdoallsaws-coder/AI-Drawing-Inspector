"""One entry contract for private catalog binding and immutable import installation.

Legacy entries retain their existing rules. Attribution is optional and only
validated when present, so older definitions keep the same revision and shape.
"""
from __future__ import annotations

from collections.abc import Collection
from copy import deepcopy
import math
from pathlib import Path
from typing import Any
import unicodedata
from urllib.parse import urlsplit

ATTRIBUTION_FIELDS = frozenset({"title", "author", "authorUrl", "sourceUrl", "license", "licenseUrl",
                                "licenseClass", "changes", "statedBy"})
LICENSE_CLASSES = frozenset({"cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nd", "cc-by-nc-sa",
                             "cc-by-nc-nd", "other", "unknown"})


def validate_attribution(value: Any) -> dict[str, str]:
    """Validate supplied credit without filling, correcting or inventing facts."""
    if not isinstance(value, dict) or set(value) - ATTRIBUTION_FIELDS:
        raise ValueError("Private asset attribution fields are invalid")
    for key, text in value.items():
        maximum = 600 if key == "changes" else 300
        if (not isinstance(text, str) or len(text) > maximum
                or any(unicodedata.category(c).startswith("C") for c in text)):
            raise ValueError(f"Private asset attribution {key} is invalid")
        if key in {"authorUrl", "sourceUrl", "licenseUrl"} and text:
            try:
                url = urlsplit(text)
                valid = (url.scheme == "https" and bool(url.hostname) and bool(url.netloc)
                         and url.username is None and url.password is None
                         and not any(c.isspace() for c in text) and "\\" not in text)
                url.port  # Force validation of malformed/out-of-range ports too.
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(f"Private asset attribution {key} must be an https URL")
        if key == "licenseClass" and text not in LICENSE_CLASSES:
            raise ValueError("Private asset attribution licenseClass is invalid")
        if key == "statedBy" and text not in {"file", "user"}:
            raise ValueError("Private asset attribution statedBy is invalid")
    return deepcopy(value)


def project_private_asset(raw: Any, **kwargs) -> dict[str, Any]:
    """Add optional builder metadata without changing the legacy entry rules."""
    spec = private_asset_spec(raw, **kwargs)
    if "buildProvenance" in raw:
        from ..industrial_assets.model_builder.identity import validate_provenance
        spec["build_provenance"] = validate_provenance(raw["buildProvenance"])
    return spec


def private_asset_spec(raw: Any, *, index: int = 0, seen: set[str] | None = None,
                       reserved: Collection[str] = ()) -> dict[str, Any]:
    """Validate one entry using the binder's original rules and return its spec."""
    if seen is None:
        seen = set()
    if not isinstance(raw, dict):
        raise ValueError(f"Private asset manifest entry {index} is invalid")
    asset_id = str(raw.get("assetId", "")).strip()
    if (
        not asset_id.startswith("asset-")
        or asset_id in seen
        or asset_id in reserved
    ):
        raise ValueError(
            f"Private asset manifest assetId is invalid: {asset_id!r}"
        )
    seen.add(asset_id)
    display_name = str(raw.get("displayName", "")).strip()
    category = str(raw.get("category", "")).strip()
    description = str(raw.get("description", "")).strip()
    if not display_name or not category or not description:
        raise ValueError(
            f"Private asset manifest metadata is incomplete: {asset_id}"
        )
    dimensions = raw.get("dimensions")
    if not isinstance(dimensions, dict):
        raise ValueError(
            f"Private asset manifest dimensions are missing: {asset_id}"
        )
    measured = []
    for field in ("width", "depth", "height"):
        value = dimensions.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(
                f"Private asset manifest {field} is invalid: {asset_id}"
            )
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError(
                f"Private asset manifest {field} is invalid: {asset_id}"
            )
        measured.append(number)

    artifact = Path(str(raw.get("artifact", "")))
    if (
        artifact.is_absolute()
        or ".." in artifact.parts
        or artifact.suffix.lower() != ".glb"
    ):
        raise ValueError(
            f"Private asset manifest artifact is invalid: {asset_id}"
        )
    matrix = raw.get("sourceToCanonical")
    if (
        not isinstance(matrix, list)
        or len(matrix) != 16
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in matrix
        )
    ):
        raise ValueError(
            f"Private asset manifest transform is invalid: {asset_id}"
        )
    tags = raw.get("tags", [])
    if not isinstance(tags, list) or any(
        not isinstance(value, str) or not value.strip()
        for value in tags
    ):
        raise ValueError(
            f"Private asset manifest tags are invalid: {asset_id}"
        )
    footprint_polygons = None
    if "footprintPolygons" in raw:
        from .spatial import _convex_hull, _polygon, _polygon_is_convex, polygon_area

        polygons = raw["footprintPolygons"]
        if not isinstance(polygons, list) or not 1 <= len(polygons) <= 64:
            raise ValueError(f"Private asset footprint polygons are invalid: {asset_id}")
        footprint_polygons = []
        for polygon in polygons:
            if (
                not isinstance(polygon, list) or not 3 <= len(polygon) <= 32
                or any(not isinstance(p, dict) or set(p) != {"x", "z"} for p in polygon)
            ):
                raise ValueError(f"Private asset footprint polygon is invalid: {asset_id}")
            points = _polygon(polygon, "private asset footprint")
            if (
                len(set(points)) != len(points)
                or not _polygon_is_convex(points)
                or abs(abs(polygon_area(points)) - abs(polygon_area(_convex_hull(points)))) > 1e-8
                or any(abs(x) > measured[0] / 2 + 1e-8 or abs(z) > measured[1] / 2 + 1e-8 for x, z in points)
            ):
                raise ValueError(f"Private asset footprint must be convex and inside its bounds: {asset_id}")
            footprint_polygons.append([{"x": x, "z": z} for x, z in points])
    raw_surfaces = raw.get("supportSurfaces", [])
    if not isinstance(raw_surfaces, list):
        raise ValueError(
            f"Private asset support surfaces are invalid: {asset_id}"
        )
    support_surfaces: list[dict[str, Any]] = []
    surface_ids: set[str] = set()
    for surface_index, raw_surface in enumerate(raw_surfaces):
        if not isinstance(raw_surface, dict):
            raise ValueError(
                f"Private asset support surface is invalid: {asset_id}"
            )
        fields = {
            "surfaceId",
            "label",
            "localFrame",
            "bounds",
            "allowedSides",
            "evidenceStatus",
        }
        if set(raw_surface) != fields:
            raise ValueError(
                f"Private asset support surface fields are invalid: {asset_id}"
            )
        surface_id = str(raw_surface.get("surfaceId", "") or "").strip()
        label = str(raw_surface.get("label", "") or "").strip()
        if not surface_id or surface_id in surface_ids or not label:
            raise ValueError(
                f"Private asset support surface identity is invalid: {asset_id}"
            )
        surface_ids.add(surface_id)
        frame = raw_surface.get("localFrame")
        bounds = raw_surface.get("bounds")
        if not isinstance(frame, dict) or set(frame) != {
            "origin", "xAxis", "zAxis", "normal"
        }:
            raise ValueError(
                f"Private asset support surface frame is invalid: {asset_id}"
            )
        normalized_frame: dict[str, dict[str, float]] = {}
        for vector_name in ("origin", "xAxis", "zAxis", "normal"):
            vector = frame.get(vector_name)
            if not isinstance(vector, dict) or set(vector) != {"x", "y", "z"}:
                raise ValueError(
                    f"Private asset support surface vector is invalid: {asset_id}"
                )
            normalized_vector = {}
            for axis in ("x", "y", "z"):
                value = vector.get(axis)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(
                        f"Private asset support surface vector is invalid: {asset_id}"
                    )
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError(
                        f"Private asset support surface vector is invalid: {asset_id}"
                    )
                normalized_vector[axis] = number
            normalized_frame[vector_name] = normalized_vector
        bound_fields = {"minimumX", "maximumX", "minimumZ", "maximumZ"}
        if not isinstance(bounds, dict) or set(bounds) != bound_fields:
            raise ValueError(
                f"Private asset support surface bounds are invalid: {asset_id}"
            )
        normalized_bounds = {}
        for field in sorted(bound_fields):
            value = bounds.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"Private asset support surface bounds are invalid: {asset_id}"
                )
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(
                    f"Private asset support surface bounds are invalid: {asset_id}"
                )
            normalized_bounds[field] = number
        if (
            normalized_bounds["minimumX"] >= normalized_bounds["maximumX"]
            or normalized_bounds["minimumZ"] >= normalized_bounds["maximumZ"]
        ):
            raise ValueError(
                f"Private asset support surface bounds are empty: {asset_id}"
            )
        allowed_sides = raw_surface.get("allowedSides")
        if (
            not isinstance(allowed_sides, list)
            or not allowed_sides
            or len(allowed_sides) != len(set(allowed_sides))
            or any(side not in {"above", "below"} for side in allowed_sides)
        ):
            raise ValueError(
                f"Private asset support surface sides are invalid: {asset_id}"
            )
        evidence_status = str(
            raw_surface.get("evidenceStatus", "") or ""
        ).strip()
        if evidence_status not in {
            "authored", "derived", "inferred", "unverified", "unknown"
        }:
            raise ValueError(
                f"Private asset support surface evidence is invalid: {asset_id}"
            )
        support_surfaces.append({
            "surfaceId": surface_id,
            "label": label,
            "localFrame": normalized_frame,
            "bounds": normalized_bounds,
            "allowedSides": list(allowed_sides),
            "evidenceStatus": evidence_status,
        })
    spec = {
        "asset_id": asset_id,
        "display_name": display_name,
        "category": category,
        "width": measured[0],
        "depth": measured[1],
        "height": measured[2],
        "description": description,
        "artifact": artifact.as_posix(),
        "source_to_canonical": tuple(float(value) for value in matrix),
        "tags": tuple(value.strip() for value in tags),
        "support_surfaces": tuple(support_surfaces),
        "footprint_polygons": footprint_polygons,
    }
    if "attribution" in raw:
        spec["attribution"] = validate_attribution(raw["attribution"])
    return spec
