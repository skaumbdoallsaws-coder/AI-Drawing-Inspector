"""Revision-bound visual forward axes for prototype activity actors."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Mapping

from .errors import FacilityValidationError


FACILITY_ACTIVITY_VISUAL_ALIGNMENT_SCHEMA_VERSION = (
    "facility-activity-visual-alignments-v1"
)
FACILITY_ACTIVITY_VISUAL_ALIGNMENT_AUTHORITY = (
    "curated_revision_bound_visual_review"
)
FACILITY_ACTIVITY_VISUAL_FORWARD_AXES = {"+X", "-X", "+Z", "-Z"}
_CATALOG_PATH = (
    Path(__file__).resolve().parent
    / "catalogs"
    / "activity-visual-alignments-v1.json"
)


def _non_empty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FacilityValidationError(
            "facility_activity_visual_alignment_catalog_invalid",
            f"{field} must be a non-empty string.",
        )
    return value.strip()


@lru_cache(maxsize=1)
def _alignment_catalog() -> dict[tuple[str, str], dict[str, str]]:
    try:
        source = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FacilityValidationError(
            "facility_activity_visual_alignment_catalog_invalid",
            "The activity visual-alignment catalog is unavailable.",
        ) from exc
    if not isinstance(source, Mapping) or set(source) != {
        "schemaVersion",
        "entries",
    }:
        raise FacilityValidationError(
            "facility_activity_visual_alignment_catalog_invalid",
            "The activity visual-alignment catalog has an invalid root contract.",
        )
    if source["schemaVersion"] != (
        FACILITY_ACTIVITY_VISUAL_ALIGNMENT_SCHEMA_VERSION
    ):
        raise FacilityValidationError(
            "facility_activity_visual_alignment_catalog_invalid",
            "The activity visual-alignment catalog schema is unsupported.",
        )
    entries = source["entries"]
    if not isinstance(entries, list):
        raise FacilityValidationError(
            "facility_activity_visual_alignment_catalog_invalid",
            "The activity visual-alignment entries must be an array.",
        )
    result: dict[tuple[str, str], dict[str, str]] = {}
    for index, item in enumerate(entries):
        if not isinstance(item, Mapping) or set(item) != {
            "assetId",
            "assetDefinitionRevision",
            "forwardAxis",
            "authority",
            "evidenceArtifact",
        }:
            raise FacilityValidationError(
                "facility_activity_visual_alignment_catalog_invalid",
                f"Activity visual-alignment entry {index} is invalid.",
            )
        alignment = {
            "forwardAxis": _non_empty_text(
                item["forwardAxis"],
                f"entries[{index}].forwardAxis",
            ),
            "authority": _non_empty_text(
                item["authority"],
                f"entries[{index}].authority",
            ),
            "evidenceArtifact": _non_empty_text(
                item["evidenceArtifact"],
                f"entries[{index}].evidenceArtifact",
            ),
        }
        if alignment["forwardAxis"] not in (
            FACILITY_ACTIVITY_VISUAL_FORWARD_AXES
        ) or alignment["authority"] != (
            FACILITY_ACTIVITY_VISUAL_ALIGNMENT_AUTHORITY
        ):
            raise FacilityValidationError(
                "facility_activity_visual_alignment_catalog_invalid",
                f"Activity visual-alignment entry {index} is unsupported.",
            )
        key = (
            _non_empty_text(item["assetId"], f"entries[{index}].assetId"),
            _non_empty_text(
                item["assetDefinitionRevision"],
                f"entries[{index}].assetDefinitionRevision",
            ),
        )
        if key in result:
            raise FacilityValidationError(
                "facility_activity_visual_alignment_catalog_invalid",
                "Activity visual-alignment identities must be unique.",
            )
        result[key] = alignment
    return result


def activity_visual_alignment(
    asset_definition_ref: Mapping[str, Any],
) -> dict[str, str]:
    """Return the curated forward axis for one exact visual revision."""

    key = (
        _non_empty_text(asset_definition_ref.get("assetId"), "assetId"),
        _non_empty_text(
            asset_definition_ref.get("assetDefinitionRevision"),
            "assetDefinitionRevision",
        ),
    )
    alignment = _alignment_catalog().get(key)
    if alignment is None:
        raise FacilityValidationError(
            "facility_activity_visual_alignment_unavailable",
            "The exact actor visual has no reviewed forward-axis alignment.",
            details={
                "assetId": key[0],
                "assetDefinitionRevision": key[1],
            },
        )
    return deepcopy(alignment)


__all__ = [
    "FACILITY_ACTIVITY_VISUAL_ALIGNMENT_AUTHORITY",
    "FACILITY_ACTIVITY_VISUAL_ALIGNMENT_SCHEMA_VERSION",
    "FACILITY_ACTIVITY_VISUAL_FORWARD_AXES",
    "activity_visual_alignment",
]
