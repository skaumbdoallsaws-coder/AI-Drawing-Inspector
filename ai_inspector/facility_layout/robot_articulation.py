"""Revision-bound robot articulation profiles for Facility Layout playback.

Animating a placed robot requires kinematic evidence: a joint chain with
parents, axes, and pivots. That evidence must come from glTF animation
channels shipped with the asset, or from an explicitly authored profile bound
to an exact asset-definition revision.

A node hierarchy does not qualify. Parented nodes prove the exporter kept
assembly structure; they carry no axes, pivots, or limits.

It is never inferred at runtime from node names or mesh bounding boxes. A
robot whose kinematics are guessed is a robot that reports a reach it does
not have, so this module fails closed instead.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Mapping, Sequence

from .errors import FacilityValidationError

ROBOT_ARTICULATION_SCHEMA_VERSION = "facility-robot-articulation-v1"

#: Emitted when a placement cannot be animated because no kinematic evidence
#: exists. Callers must surface this rather than moving the robot rigidly.
ARTICULATION_UNAVAILABLE = "facility_robot_articulation_unavailable"

#: The joint roles a prototype pick-and-place cycle needs. A profile missing
#: any required role is incomplete and refused.
REQUIRED_JOINT_ROLES = ("base", "shoulder", "elbow", "wrist")
OPTIONAL_JOINT_ROLES = ("gripper",)
JOINT_ROLES = REQUIRED_JOINT_ROLES + OPTIONAL_JOINT_ROLES

_GLB_MAGIC = b"glTF"
_CHUNK_JSON = 0x4E4F534A


class FacilityRobotArticulationError(FacilityValidationError):
    """Raised when robot articulation evidence is absent or unusable."""


def _fail(code: str, message: str, **details: Any) -> None:
    raise FacilityRobotArticulationError(code, message, details=details or None)


def read_gltf_document(glb_path: Path) -> dict[str, Any]:
    """Return the JSON chunk of a binary glTF file without a 3D dependency."""

    data = Path(glb_path).read_bytes()
    if len(data) < 12 or data[:4] != _GLB_MAGIC:
        _fail(
            "facility_robot_asset_unreadable",
            "Robot asset is not a binary glTF file.",
            path=str(glb_path),
        )
    offset = 12
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        if chunk_type == _CHUNK_JSON:
            raw = data[offset + 8 : offset + 8 + chunk_length]
            return json.loads(raw.decode("utf-8"))
        offset += 8 + chunk_length
    _fail(
        "facility_robot_asset_unreadable",
        "Robot asset contains no glTF JSON chunk.",
        path=str(glb_path),
    )
    raise AssertionError("unreachable")


def summarize_asset_articulation(document: Mapping[str, Any]) -> dict[str, Any]:
    """Report the kinematic evidence a glTF document actually carries."""

    nodes = list(document.get("nodes") or [])
    animations = list(document.get("animations") or [])
    skins = list(document.get("skins") or [])
    parented = sum(1 for node in nodes if node.get("children"))
    channels = sum(len(item.get("channels") or []) for item in animations)
    posed = sum(
        1
        for node in nodes
        if any(key in node for key in ("matrix", "translation", "rotation", "scale"))
    )
    return {
        "nodeCount": len(nodes),
        "animationCount": len(animations),
        "animationNames": [str(item.get("name") or "") for item in animations],
        "skinCount": len(skins),
        "parentedNodeCount": parented,
        "transformedNodeCount": posed,
        "animationChannelCount": channels,
        "hasChannels": channels > 0,
        "hasHierarchy": parented > 0,
        # Hierarchy deliberately excluded: structure is not kinematics.
        "articulationEvidence": channels > 0,
    }


def _joint(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("facility_robot_profile_invalid", "Joint entries must be objects.")
    role = str(value.get("role") or "")
    if role not in JOINT_ROLES:
        _fail(
            "facility_robot_profile_invalid",
            "Joint role is unsupported.",
            role=role,
            index=index,
        )
    node_name = str(value.get("nodeName") or "")
    if not node_name:
        _fail(
            "facility_robot_profile_invalid",
            "Joint requires the exact asset node name it drives.",
            role=role,
        )
    axis = value.get("axis")
    if not (isinstance(axis, Sequence) and not isinstance(axis, str) and len(axis) == 3):
        _fail(
            "facility_robot_profile_invalid",
            "Joint requires a three-component rotation axis.",
            role=role,
        )
    axis_values = [float(component) for component in axis]
    if sum(component * component for component in axis_values) <= 0.0:
        _fail(
            "facility_robot_profile_invalid",
            "Joint rotation axis must be non-zero.",
            role=role,
        )
    pivot = value.get("pivot")
    if not (isinstance(pivot, Sequence) and not isinstance(pivot, str) and len(pivot) == 3):
        _fail(
            "facility_robot_profile_invalid",
            "Joint requires a three-component pivot in asset space.",
            role=role,
        )
    limits = value.get("limitsDegrees")
    if not (
        isinstance(limits, Sequence)
        and not isinstance(limits, str)
        and len(limits) == 2
        and float(limits[0]) < float(limits[1])
    ):
        _fail(
            "facility_robot_profile_invalid",
            "Joint requires ascending [minimum, maximum] limits in degrees.",
            role=role,
        )
    return {
        "role": role,
        "nodeName": node_name,
        "parentRole": (str(value["parentRole"]) if value.get("parentRole") else None),
        "axis": axis_values,
        "pivot": [float(component) for component in pivot],
        "limitsDegrees": [float(limits[0]), float(limits[1])],
        "limitsAuthority": str(value.get("limitsAuthority") or "prototype"),
    }


def normalize_articulation_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an authored profile and bind it to an exact asset revision."""

    if not isinstance(profile, Mapping):
        _fail("facility_robot_profile_invalid", "Profile must be an object.")
    if profile.get("schemaVersion") != ROBOT_ARTICULATION_SCHEMA_VERSION:
        _fail(
            "facility_robot_profile_invalid",
            "Profile schemaVersion is unsupported.",
            expected=ROBOT_ARTICULATION_SCHEMA_VERSION,
        )
    asset_id = str(profile.get("assetId") or "")
    revision = str(profile.get("assetDefinitionRevision") or "")
    if not asset_id or len(revision) != 64:
        _fail(
            "facility_robot_profile_invalid",
            "Profile must name an assetId and a 64-character asset revision.",
        )
    raw_joints = profile.get("joints")
    if not isinstance(raw_joints, Sequence) or isinstance(raw_joints, str) or not raw_joints:
        _fail("facility_robot_profile_invalid", "Profile requires a joint list.")
    joints = [_joint(item, index) for index, item in enumerate(raw_joints)]
    roles = [item["role"] for item in joints]
    if len(set(roles)) != len(roles):
        _fail("facility_robot_profile_invalid", "Joint roles must be unique.")
    missing = [role for role in REQUIRED_JOINT_ROLES if role not in roles]
    if missing:
        _fail(
            "facility_robot_profile_incomplete",
            "Profile is missing required joint roles.",
            missingRoles=missing,
        )
    by_role = {item["role"]: item for item in joints}
    for item in joints:
        parent = item["parentRole"]
        if parent is None:
            continue
        if parent not in by_role:
            _fail(
                "facility_robot_profile_invalid",
                "Joint parent role is not present in the profile.",
                role=item["role"],
                parentRole=parent,
            )
        seen = {item["role"]}
        cursor = parent
        while cursor is not None:
            if cursor in seen:
                _fail(
                    "facility_robot_profile_invalid",
                    "Joint parent chain contains a cycle.",
                    role=item["role"],
                )
            seen.add(cursor)
            cursor = by_role[cursor]["parentRole"]
    normalized = {
        "schemaVersion": ROBOT_ARTICULATION_SCHEMA_VERSION,
        "assetId": asset_id,
        "assetDefinitionRevision": revision,
        "joints": sorted(joints, key=lambda item: JOINT_ROLES.index(item["role"])),
        "evidenceStatus": str(profile.get("evidenceStatus") or "authored"),
        "qualification": (
            "Prototype robot articulation. Joint limits and travel are "
            "illustrative values bound to an exact asset revision. They do not "
            "establish reach capacity, payload, cycle time, collision safety, "
            "throughput, machine synchronization, or production readiness."
        ),
    }
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    normalized["profileRevision"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return normalized


def resolve_articulation(
    *,
    asset_id: str,
    asset_definition_revision: str,
    gltf_document: Mapping[str, Any],
    authored_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve how a placed robot may be animated, or refuse.

    Articulation requires one of exactly two things:

    1. glTF animation channels shipped with the asset; or
    2. an authored profile, bound to this exact asset revision, carrying
       parent/child relationships, pivots, axes, and limits.

    A node hierarchy alone does not qualify. Parented nodes prove only that the
    exporter kept assembly structure; they carry no joint axes, pivots, or
    limits, so posing through them is still invented kinematics.

    With neither, this refuses with ``facility_robot_articulation_unavailable``.
    Rigidly moving the whole robot is never an acceptable fallback.
    """

    summary = summarize_asset_articulation(gltf_document)

    if summary["hasChannels"]:
        return {
            "mode": "asset_animation_clips",
            "assetId": asset_id,
            "assetDefinitionRevision": asset_definition_revision,
            "clipNames": summary["animationNames"],
            "assetSummary": summary,
        }

    if authored_profile is not None:
        normalized = normalize_articulation_profile(authored_profile)
        if normalized["assetId"] != asset_id:
            _fail(
                "facility_robot_profile_mismatch",
                "Authored profile targets a different asset.",
                expected=asset_id,
                received=normalized["assetId"],
            )
        if normalized["assetDefinitionRevision"] != asset_definition_revision:
            _fail(
                "facility_robot_profile_mismatch",
                "Authored profile is bound to a different asset revision.",
                expected=asset_definition_revision,
                received=normalized["assetDefinitionRevision"],
            )
        names = {str(node.get("name") or "") for node in gltf_document.get("nodes") or []}
        unknown = sorted(
            joint["nodeName"] for joint in normalized["joints"] if joint["nodeName"] not in names
        )
        if unknown:
            _fail(
                "facility_robot_profile_mismatch",
                "Authored profile references nodes absent from the asset.",
                unknownNodes=unknown,
            )
        return {
            "mode": "authored_profile",
            "assetId": asset_id,
            "assetDefinitionRevision": asset_definition_revision,
            "profile": normalized,
            "assetSummary": summary,
        }

    # A node hierarchy is not articulation. Parented nodes say only that the
    # exporter preserved assembly structure; they carry no joint axes, pivots,
    # or limits, so posing through them would still be invented kinematics.
    _fail(
        ARTICULATION_UNAVAILABLE,
        (
            "The robot asset carries no articulation evidence: no animation "
            "clips, no skins, no node hierarchy, and no authored profile bound "
            "to this asset revision. Animating it would require inventing a "
            "joint chain, so playback is refused."
        ),
        assetId=asset_id,
        assetDefinitionRevision=asset_definition_revision,
        nodeCount=summary["nodeCount"],
        animationCount=summary["animationCount"],
        skinCount=summary["skinCount"],
        parentedNodeCount=summary["parentedNodeCount"],
        remedy=(
            "Supply an authored articulation profile for this asset revision, "
            "or re-export the asset with its assembly hierarchy preserved."
        ),
    )
    raise AssertionError("unreachable")
