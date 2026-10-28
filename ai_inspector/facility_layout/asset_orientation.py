"""Reviewed front sides for library assets, and orientation intent for edits.

Library assets carry no facing data, so an agent placing a chair or a lathe
had to guess which raw quaternion pointed it the right way, and rounded
quaternions were rejected for not having unit length. This module registers
the functional sides of commonly used library models and turns an
orientation intent, {"facing": "north"} or {"yawDegrees": 90}, into the exact
canonical quaternion a placement stores.

Sides use the layout compass: north is +z (up on the plan) and east is +x.
A model's sides are named as it stands unrotated. Headings turn a model the
way a compass heading turns, so a 90 degree yaw turns its north side east.
"""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping, Sequence

from .errors import FacilityValidationError

COMPASS_HEADINGS = {"north": 0, "east": 90, "south": 180, "west": 270}
ORIENTATION_INTENT_KEYS = frozenset({"facing", "yawDegrees"})


def _sides(front: str, **roles: str) -> dict[str, Any]:
    sides = {"front": front, **roles}
    return {
        "functionalSides": {
            role: {"side": side, "evidenceStatus": "inferred"}
            for role, side in sorted(sides.items())
        },
        "evidenceStatus": "inferred",
    }


# Each model was viewed unrotated from all four sides in 3D on 2026-10-17.
# An entry applies only to the exact revision that was viewed: a changed model
# must be reviewed again rather than inherit a front that may no longer hold.
# Entries are written in the model file's own axes (east = the file's +x,
# north = its +z), as those views and the probe scripts report them. The
# catalog converts them into the layout's model space (model_axes.py), where the
# file's east side is the unrotated model's west side. Register new entries in
# the file's axes as well.
REGISTERED_ASSET_SEMANTICS: dict[str, tuple[str, dict[str, Any]]] = {
    # Seating: the seat faces the front.
    "asset-chair-black": (
        "f85ec0da2be4b235b0c3874f412e04533f18365bb1307cc1dfcf521b8dfa90e2",
        _sides("north")),
    "asset-breakroom-conference-chair": (
        "3b6bdf70adb28b2009286ad40e00cd5ee7b54ce1215db401a619f9558b56755e",
        _sides("north")),
    # Desks: the user sits on the open side; the modesty panel is the rear.
    "asset-desk-1400-clear-wood": (
        "fbb27348035143bcfc084ebecedd1a83a1fbe884e437ddea3556ec7d406057b9",
        _sides("east", operator="east", rear="west")),
    "asset-import-bzkhmca1or28": (
        "41bc7a95f479524f7497693d4ce0f99c520f993c24fcd3e3f711dae0d4959801",
        _sides("east", operator="east", rear="west")),
    # Corner cubicle (reviewed 2026-10-18): an L of panels and worktop along the
    # south and west sides, open to the north and east. Its footprint leaves the
    # north-east quarter free (x and z above -0.2 m), and its monitor, keyboard and
    # mouse surfaces sit diagonally in the south-west corner. So the seat faces that
    # corner (heading 225); at x = z = 0.25 m an office chair turned 45 degrees is as
    # close to the worktop as its footprint allows (2026-10-20).
    # The two other cubicle models share the look but block their whole square.
    "asset-import-cubicle-corner-workstation": (
        "fb73cc329447cf13c40251ab781dd8e5f512c6143dc0cbb56ddb26b98618b372",
        {**_sides("north", operator="north", rear="south"),
         "workstationSeat": {"localPosition": {"x": 0.25, "z": 0.25}, "facingDegrees": 225,
                             "evidenceStatus": "derived"}}),
    # Kitchen: appliance doors face the front; small appliances belong on a
    # worktop such as the kitchen assembly, not on the floor.
    "asset-breakroom-refrigerator": (
        "701ca8a3a4ea89aad4bf91033eedbb75daea1def90bf285931463352c4383c0a",
        _sides("north")),
    "asset-breakroom-microwave": (
        "a3a900619e12c73b16e3dc403cf7cb39e5500be12e17decf01cb9b00d3c0ac0a",
        {**_sides("north"), "operationalRoles": ["countertop_appliance"]}),
    "asset-breakroom-coffee-pot": (
        "fdd00bea988d1232023a8bbf734caaa7eff19fa976fdccf829987f47b4d73a3f",
        {**_sides("north"), "operationalRoles": ["countertop_appliance"]}),
    "asset-kitchen-assembly-appliance-worktop": (
        "9b0f2f8c9a15b1e1e76964584dec40de2c185673f864f163d57de7f79ba8929f",
        _sides("east", operator="east")),
    # Machine tools: the front carries the doors, controls or carriage.
    "asset-cnc-mill": (
        "2c33d6899de6e048418bb848df6d36d96f2ac067cfb0b7aa5b0798efd5f90186",
        _sides("south", operator="south", loading="south")),
    "asset-cnc-lathe": (
        "4d3344f6d513b0dda3c90eb88f9dd4b3a4e448b15955bb501b5f084a99698d59",
        _sides("north", operator="north", loading="north")),
    "asset-haas-st30-lathe": (
        "2e7123e38487539fd30733a69e25e760298d0c686624f2cf410219bcf38cdf67",
        _sides("north", operator="north", loading="north")),
    "asset-import-haas-vf4": (
        "27ba982c5568281185abcc5c7648fe2c0603d82b9f51e3fff97fea03845f715b",
        _sides("north", operator="north", loading="north")),
    "asset-import-haas-ec": (
        "d37138927d16d512682489f648862b4d818e9de5a68d59b77b937637392be0e7",
        _sides("north", operator="north", loading="north")),
    "asset-lathe-mori-cl200a": (
        "653b5e17604d33f3e1b085b83172f70df2bc1b91f4bb4e7284d577014369ecea",
        _sides("north", operator="north", loading="north")),
    "asset-lathe-hardinge-hlv": (
        "50d0f6b2dc1a1f25ca78cf3acd750176549958ab1951f6f25a9ca48d04abad74",
        _sides("north", operator="north")),
    "asset-lathe-acer-1760g": (
        "5d6429fc49b8a4261775d316c96d53593dc23342f4b7d6753066483633875673",
        _sides("north", operator="north")),
    "asset-okamoto-surface-grinder": (
        "07df89a343dd9037bfc8ad6fa2130277bec72bf0f0b1f128f8a8a60491c76769",
        _sides("north", operator="north")),
    "asset-sinker-edm": (
        "eda9499ded04a86fe5c27c228fe5bfb553b892723035d65d6f016e9fe7952795",
        _sides("east", operator="east")),
    "asset-vertical-band-saw": (
        "7f110adcd8591f9bfd83a016ad9a94b275a6a977c1736b81a06a9d11d1a17a66",
        _sides("east", operator="east")),
    # Horizontal band saw (read from its CAD parts 2026-10-21): the blade and its
    # cutting slot run along the long (x) axis, so bar stock crosses the bed along z.
    # The cut sits near the bed's +z edge, so bars come in from the south and cut
    # pieces leave north. The operator loads and clamps at the infeed side. To put the
    # saw in line with stock racks, face its front (the infeed) toward the racks.
    "asset-kalamazoo-h9aw-horizontal-band-saw": (
        "8241a381234e3ec2f576c40c00e64581e6037aee3f374201ece6cdb427f70bfe",
        _sides("south", operator="south", material_input="south", material_output="north")),
    "asset-industrial-oven": (
        "54abfa67a6a545f6ffacee883188bcf38c467517bb3034f5246cfcdb52f8cb32",
        _sides("north", loading="north")),
    "asset-fanuc-14tes2-robot": (
        "54e4b03b62a68dd6915cec106db9952b92e78f206317585875d3ed75bcbc8391",
        _sides("north", loading="north")),
    # Storage: pallet racks load from both long sides; shelves and cabinets
    # open to the front.
    "asset-pallet-rack": (
        "ea93c630b24819f70b621cd1b877f622bed5aa6c4a096539abaf8f79998bbd38",
        _sides("east", loading="east", rear="west")),
    "asset-tooling-shelves": (
        "6d43c296a14b462dc1be39191a039800ce8cf9be30cd68bc4b2bd0c05eb7facd",
        _sides("north", rear="south")),
    "asset-roll-away-cabinet": (
        "b28070689c4b6fe84a761b08faca3ae0885e25cdf9240c51d1925ab6ad4f696e",
        _sides("north")),
    "asset-user-library-drawers-4-6in-x-42in-w": (
        "8bfdc6594d993ed7c51982b4313952ee45fb7d86d1ffb77d401368283caa01a7",
        _sides("north")),
    "asset-assembled-laboratory-workstation": (
        "549cd1336b231cbf558f536ab838eb906dfd34044b6f3fc18e53d7c769931286",
        _sides("north", operator="north")),
    # Trucks: the front is the fork end.
    "asset-forklift": (
        "da1345e51b1a32c38ad8388799154ba77dc59e99890a855caac3648548f5be5f",
        _sides("north")),
    "asset-pallet-truck-simple": (
        "608a917bb1ae460de6e7c7074ae5c80ff9255086a163b7b24a06a6f91fcaf897",
        _sides("east", rear="west")),
    # Conveyors: the front is the discharge end, so facing names the flow
    # direction. This module rises toward its discharge end; chained end to
    # end it climbs in a sawtooth rather than forming a level line.
    "asset-user-library-na-300x2100": (
        "fe3074052374a8e2a06f15ce78513207ed43339f4c4a02c00516aa74f7276c1e",
        {**_sides("east", material_input="west", material_output="east"),
         "semanticType": "inclined_conveyor"}),
    "asset-user-library-na-450x1200": (
        "d873bec31e97d66fd04de8d7164ce82d346edb889355c4f1d3abb459be6f7fa5",
        {**_sides("east", material_input="west", material_output="east"),
         "semanticType": "level_belt_conveyor"}),
}


def attach_registered_semantics(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a catalog record carrying reviewed sides for its exact revision.

    Semantics sit beside the definition, never inside it, so the definition
    and its revision are unchanged.
    """
    result = deepcopy(dict(record))
    entry = REGISTERED_ASSET_SEMANTICS.get(str(result.get("assetId") or ""))
    if (
        entry is not None
        and result.get("assetDefinitionRevision") == entry[0]
        and not isinstance(result.get("facilitySemantics"), Mapping)
    ):
        result["facilitySemantics"] = deepcopy(entry[1])
    return result


def yaw_quaternion(degrees: float) -> dict[str, float]:
    """Return the canonical unit quaternion for a turn about the vertical axis."""
    half = math.radians(float(degrees) % 360) / 2
    y, w = math.sin(half), math.cos(half)
    if math.isclose(abs(y), math.sqrt(0.5), abs_tol=1e-12):
        y = math.copysign(math.sqrt(0.5), y)
        w = math.copysign(math.sqrt(0.5), w)
    y = 0.0 if abs(y) < 1e-15 else y
    w = 0.0 if abs(w) < 1e-15 else w
    # The layout requires the first nonzero of w, x, y, z to be positive.
    if w < 0 or (w == 0 and y < 0):
        y, w = -y, -w
    return {"x": 0.0, "y": y + 0.0, "z": 0.0, "w": w + 0.0}


def _front_side(records: Mapping[str, Mapping[str, Any]], asset_id: Any, revision: Any) -> str | None:
    record = records.get(str(asset_id or ""))
    if record is None or record.get("assetDefinitionRevision") != revision:
        return None
    semantics = record.get("facilitySemantics")
    sides = semantics.get("functionalSides") if isinstance(semantics, Mapping) else None
    front = sides.get("front") if isinstance(sides, Mapping) else None
    side = front.get("side") if isinstance(front, Mapping) else front
    return side if side in COMPASS_HEADINGS else None


def _intent_quaternion(intent: Any, records, asset_id: Any, revision: Any, index: int) -> dict[str, float]:
    if (
        not isinstance(intent, Mapping)
        or len(ORIENTATION_INTENT_KEYS.intersection(intent)) != 1
        or set(intent) - ORIENTATION_INTENT_KEYS
    ):
        raise FacilityValidationError(
            "orientation_intent_invalid",
            "Give orientation as exactly one of facing (north, east, south or west) or yawDegrees.",
            details={"operationIndex": index},
        )
    if "yawDegrees" in intent:
        degrees = intent["yawDegrees"]
        if isinstance(degrees, bool) or not isinstance(degrees, (int, float)) or not math.isfinite(degrees):
            raise FacilityValidationError(
                "orientation_intent_invalid",
                "yawDegrees must be a finite number of degrees.",
                details={"operationIndex": index},
            )
        return yaw_quaternion(degrees)
    facing = intent["facing"]
    if facing not in COMPASS_HEADINGS:
        raise FacilityValidationError(
            "orientation_intent_invalid",
            "facing must be north, east, south or west.",
            details={"operationIndex": index},
        )
    front = _front_side(records, asset_id, revision)
    if front is None:
        raise FacilityValidationError(
            "asset_front_side_unknown",
            "This asset revision has no reviewed front side, so facing cannot be resolved. "
            "Use yawDegrees and say that its orientation is unverified.",
            details={"operationIndex": index, "assetId": str(asset_id or "")},
        )
    return yaw_quaternion(COMPASS_HEADINGS[facing] - COMPASS_HEADINGS[front])


def resolve_orientation_intents(
    operations: Any,
    *,
    catalog: Sequence[Mapping[str, Any]],
    layout: Mapping[str, Any],
) -> Any:
    """Replace each operation's orientation intent with an exact quaternion.

    Operations without an intent pass through unchanged, so the operation
    kernel still validates every batch it receives.
    """
    if not isinstance(operations, list) or not any(
        isinstance(item, Mapping) and "orientation" in item for item in operations
    ):
        return operations
    records = {
        str(item.get("assetId")): item
        for item in catalog
        if isinstance(item, Mapping) and item.get("assetId")
    }
    saved = {
        item.get("placementId"): item
        for item in layout.get("placements", [])
        if isinstance(item, Mapping)
    }
    resolved = []
    for index, raw in enumerate(operations):
        if not isinstance(raw, Mapping) or "orientation" not in raw:
            resolved.append(raw)
            continue
        operation = deepcopy(dict(raw))
        intent = operation.pop("orientation")
        if operation.get("op") == "place_asset" and isinstance(operation.get("placement"), Mapping):
            placement = operation["placement"]
            transform = placement.setdefault("transform", {})
            if not isinstance(transform, dict) or "quaternion" in transform:
                raise FacilityValidationError(
                    "orientation_intent_conflict",
                    "Give either orientation or transform.quaternion, not both.",
                    details={"operationIndex": index},
                )
            transform["quaternion"] = _intent_quaternion(
                intent, records, placement.get("assetId"), placement.get("assetDefinitionRevision"), index)
        elif operation.get("op") == "rotate_placement":
            if "quaternion" in operation:
                raise FacilityValidationError(
                    "orientation_intent_conflict",
                    "Give either orientation or quaternion, not both.",
                    details={"operationIndex": index},
                )
            current = saved.get(operation.get("placementId"))
            if current is None:
                raise FacilityValidationError(
                    "orientation_placement_not_saved",
                    "Orient a new placement with orientation on place_asset; rotate_placement needs a saved placement.",
                    details={"operationIndex": index},
                )
            operation["quaternion"] = _intent_quaternion(
                intent, records, current.get("assetId"), current.get("assetDefinitionRevision"), index)
        else:
            raise FacilityValidationError(
                "orientation_intent_unsupported",
                "orientation is accepted only on place_asset and rotate_placement.",
                details={"operationIndex": index},
            )
        resolved.append(operation)
    return resolved
