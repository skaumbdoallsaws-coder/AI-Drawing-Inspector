"""Reviewed prototype itineraries for the archived reference factory.

The archived manual layout carries no authored navigation anchors or process
bindings, so no movement program can be routed from it alone. This module
builds a *prototype* itinerary that lives entirely outside that immutable
layout and is bound to its exact revision and placement IDs.

Every stop references a placement that already exists. Nothing here creates an
actor, a station, or a process step, and nothing here is production authority:
the stop ordering is a disclosed prototype assumption, marked
``evidenceStatus: "inferred"`` and ``reviewStatus: "pending"`` so it can never
be mistaken for confirmed manufacturing sequence.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .navigation_contract import FACILITY_NAVIGATION_SCHEMA_VERSION

PROTOTYPE_ITINERARY_SCHEMA_VERSION = "facility-prototype-itinerary-v1"
REFERENCE_COMPLETE_ACTIVITY_PRESET = "reference_complete_navigation"
REFERENCE_COMPLETE_ACTIVITY_ACTOR_COUNT = 23
REFERENCE_COMPLETE_ACTIVITY_COMPILER_REVISION = (
    "reference-complete-navigation-v1"
)
REFERENCE_DOWNSTREAM_ACTIVITY_PRESET = "reference_downstream_navigation"
REFERENCE_DOWNSTREAM_ROOT_ZONE_LABEL = (
    "Inspection + Packing + Finished goods"
)

PROTOTYPE_ITINERARY_QUALIFICATION = (
    "Prototype candidate movement only. Stop selection and ordering are "
    "disclosed prototype assumptions bound to an exact layout revision, not "
    "authored process sequence. This establishes no safety, staffing, timing, "
    "throughput, capacity, collision avoidance, ergonomics, regulatory "
    "compliance, or production scheduling claim."
)

#: Existing station assets an operator can plausibly interact with. Membership
#: makes a placement eligible for a prototype stop; it asserts no process role.
_OPERATOR_STOP_TOKENS = (
    "workstation",
    "worktable",
    "workbench",
    "drawers",
)
_PACKAGING_ZONE_PREFIX = "Packaging Station"
_INSPECTION_ZONE_PREFIXES = ("Inspection Station", "Inpection Station")
_PALLET_TOKEN = "pallet-"
_CART_TOKENS = ("mobile-cart", "mobile_cart", "platform-truck")
_INSPECTION_INPUT_TOKENS = ("mobile-folding-worktable",)
_INSPECTION_MACHINE_TOKENS = ("assembled-laboratory-workstation",)
_INSPECTION_OUTPUT_TOKENS = ("drawers", "output-container")


def _stable(prefix: str, seed: Any) -> str:
    payload = json.dumps(seed, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _is_work_surface(asset_id: str) -> bool:
    lowered = asset_id.lower()
    return any(token in lowered for token in _OPERATOR_STOP_TOKENS)


def _placement_anchor(
    placement: Mapping[str, Any],
    *,
    layout_revision: str,
    role: str,
    anchor_kind: str,
    interaction_kind: str,
    approach_directions: list[str],
) -> dict[str, Any]:
    placement_id = str(placement["placementId"])
    return {
        "navigationAnchorId": _stable(
            "na", [role, placement_id, layout_revision]
        ),
        "anchorKind": anchor_kind,
        "ownerRef": {
            "ownerKind": "placement",
            "ownerId": placement_id,
        },
        "interactionKind": interaction_kind,
        "positionAuthority": "inferred",
        "localPosition": None,
        "derivedPositionRef": {
            "sourceKind": "placement_access",
            "sourceId": placement_id,
            "sourceRevision": str(
                placement.get("assetDefinitionRevision") or ""
            ),
        },
        "approachDirections": approach_directions,
        "actorClasses": ["pedestrian"],
        "evidenceStatus": "inferred",
        "evidence": [],
        "reviewStatus": "pending",
    }


def _stop(
    anchor: Mapping[str, Any],
    *,
    layout_revision: str,
    role: str,
    interaction_kind: str,
) -> dict[str, Any]:
    return {
        "stopId": _stable(
            "nst", [role, anchor["navigationAnchorId"], layout_revision]
        ),
        "navigationAnchorId": anchor["navigationAnchorId"],
        "interactionKind": interaction_kind,
        "required": True,
    }


def _one_way_program(
    actor: Mapping[str, Any],
    *,
    layout_revision: str,
    actor_profile_id: str,
    actor_profile_revision: str,
    program_family: str,
    phase: str,
    stops: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "movementProgramId": _stable(
            "nmp",
            [program_family, phase, actor["placementId"], layout_revision],
        ),
        "actorPlacementId": actor["placementId"],
        "actorClass": "pedestrian",
        "actorProfileRef": {
            "profileKind": "pedestrian",
            "profileId": actor_profile_id,
            "profileRevision": actor_profile_revision,
        },
        "orderedStops": stops,
        "loopMode": "one_way",
        "requiredRouteIds": [],
        "requiredAnchorIds": sorted({
            stop["navigationAnchorId"] for stop in stops
        }),
        "forbiddenZoneIds": [],
        "forbiddenRouteIds": [],
        "manualPathConstraintIds": [],
        "handoffProgramIds": [],
        "sourceRevisions": {
            "layout": layout_revision,
            "actor_profile": actor_profile_revision,
        },
        "evidenceStatus": "inferred",
        "evidence": [],
        "reviewStatus": "pending",
    }


def _packaging_cycle(
    actor: Mapping[str, Any],
    inventory: Mapping[str, Any],
    *,
    layout_revision: str,
    actor_profile_id: str,
    actor_profile_revision: str,
) -> dict[str, Any] | None:
    """Build the reviewed pick, work, place, and empty-return cycle."""

    zone_id = str(actor["zoneId"])
    stations = [
        item for item in inventory["stations"]
        if str(item["zoneId"]) == zone_id
    ]
    mobile = [
        item for item in inventory["actors"]
        if (
            str(item["zoneId"]) == zone_id
            and item.get("actorKind") == "mobile_equipment"
            and any(
                token in str(item["assetId"]).lower()
                for token in _CART_TOKENS
            )
        )
    ]
    pallets = sorted(
        (
            item for item in stations
            if _PALLET_TOKEN in str(item["assetId"]).lower()
        ),
        key=lambda item: (
            float(item["position"]["x"]),
            str(item["placementId"]),
        ),
    )
    work_surfaces = sorted(
        (item for item in stations if _is_work_surface(str(item["assetId"]))),
        key=lambda item: str(item["placementId"]),
    )
    if len(pallets) != 2 or len(work_surfaces) != 1 or len(mobile) != 1:
        return None

    input_pallet = pallets[0]
    bypass_pallet = pallets[1]
    work_surface = work_surfaces[0]
    cart = mobile[0]
    input_anchor = _placement_anchor(
        input_pallet,
        layout_revision=layout_revision,
        role="packaging-input",
        anchor_kind="fifo_input",
        interaction_kind="load",
        approach_directions=["south", "north", "west", "east"],
    )
    work_anchor = _placement_anchor(
        work_surface,
        layout_revision=layout_revision,
        role="packaging-work",
        anchor_kind="station_operate",
        interaction_kind="operate",
        approach_directions=["south"],
    )
    right_bypass_anchor = _placement_anchor(
        bypass_pallet,
        layout_revision=layout_revision,
        role="packaging-right-bypass",
        anchor_kind="aisle_access",
        interaction_kind="none",
        approach_directions=["northeast"],
    )
    cart_anchor = _placement_anchor(
        cart,
        layout_revision=layout_revision,
        role="packaging-output-cart",
        anchor_kind="station_unload",
        interaction_kind="unload",
        approach_directions=["south"],
    )
    anchors = [
        input_anchor,
        work_anchor,
        right_bypass_anchor,
        cart_anchor,
    ]
    carry_in = _one_way_program(
        actor,
        layout_revision=layout_revision,
        actor_profile_id=actor_profile_id,
        actor_profile_revision=actor_profile_revision,
        program_family="packaging",
        phase="carry_in",
        stops=[
            _stop(
                input_anchor,
                layout_revision=layout_revision,
                role="packaging-pick",
                interaction_kind="load",
            ),
            _stop(
                work_anchor,
                layout_revision=layout_revision,
                role="packaging-work",
                interaction_kind="operate",
            ),
        ],
    )
    carry_out = _one_way_program(
        actor,
        layout_revision=layout_revision,
        actor_profile_id=actor_profile_id,
        actor_profile_revision=actor_profile_revision,
        program_family="packaging",
        phase="carry_out",
        stops=[
            _stop(
                work_anchor,
                layout_revision=layout_revision,
                role="packaging-work-out",
                interaction_kind="operate",
            ),
            _stop(
                right_bypass_anchor,
                layout_revision=layout_revision,
                role="packaging-right-bypass",
                interaction_kind="none",
            ),
            _stop(
                cart_anchor,
                layout_revision=layout_revision,
                role="packaging-place",
                interaction_kind="unload",
            ),
        ],
    )
    return_empty = _one_way_program(
        actor,
        layout_revision=layout_revision,
        actor_profile_id=actor_profile_id,
        actor_profile_revision=actor_profile_revision,
        program_family="packaging",
        phase="return_empty",
        stops=[
            _stop(
                cart_anchor,
                layout_revision=layout_revision,
                role="packaging-cart-out",
                interaction_kind="unload",
            ),
            _stop(
                input_anchor,
                layout_revision=layout_revision,
                role="packaging-next-pick",
                interaction_kind="load",
            ),
        ],
    )
    programs = [carry_in, carry_out, return_empty]
    phases = ["carry_in", "carry_out", "return_empty"]
    return {
        "anchors": anchors,
        "programs": programs,
        "group": {
            "cycleKind": "packaging",
            "actorPlacementId": actor["placementId"],
            "primaryProgramId": carry_in["movementProgramId"],
            "candidateProgramIds": [
                program["movementProgramId"] for program in programs
            ],
            "snapshotAnchorIds": [
                anchor["navigationAnchorId"] for anchor in anchors
            ],
            "cycleSegments": [
                {
                    "phase": phase,
                    "movementProgramId": program["movementProgramId"],
                }
                for phase, program in zip(phases, programs)
            ],
            "requestedStopPlacementIds": [
                input_pallet["placementId"],
                work_surface["placementId"],
                cart["placementId"],
            ],
            "rightBypassPlacementId": bypass_pallet["placementId"],
        },
    }


def _inspection_cycle(
    actor: Mapping[str, Any],
    inventory: Mapping[str, Any],
    *,
    layout_revision: str,
    actor_profile_id: str,
    actor_profile_revision: str,
) -> dict[str, Any] | None:
    """Build the reviewed pick, inspect, place, and empty-return cycle."""

    zone_id = str(actor["zoneId"])
    stations = [
        item for item in inventory["stations"]
        if str(item["zoneId"]) == zone_id
    ]

    def matching(tokens: tuple[str, ...]) -> list[Mapping[str, Any]]:
        return sorted(
            (
                item for item in stations
                if any(
                    token in str(item["assetId"]).lower()
                    for token in tokens
                )
            ),
            key=lambda item: (
                float(item["position"]["x"]),
                str(item["placementId"]),
            ),
        )

    input_tables = matching(_INSPECTION_INPUT_TOKENS)
    inspection_machines = matching(_INSPECTION_MACHINE_TOKENS)
    output_containers = matching(_INSPECTION_OUTPUT_TOKENS)
    if (
        len(input_tables) != 1
        or len(inspection_machines) != 1
        or len(output_containers) != 1
    ):
        return None

    input_table = input_tables[0]
    inspection_machine = inspection_machines[0]
    output_container = output_containers[0]
    if not (
        float(input_table["position"]["x"])
        < float(inspection_machine["position"]["x"])
        < float(output_container["position"]["x"])
    ):
        return None

    input_anchor = _placement_anchor(
        input_table,
        layout_revision=layout_revision,
        role="inspection-input-table",
        anchor_kind="station_load",
        interaction_kind="load",
        approach_directions=["southwest"],
    )
    inspect_anchor = _placement_anchor(
        inspection_machine,
        layout_revision=layout_revision,
        role="inspection-machine",
        anchor_kind="station_inspect",
        interaction_kind="inspect",
        approach_directions=["south"],
    )
    output_return_anchor = _placement_anchor(
        output_container,
        layout_revision=layout_revision,
        role="inspection-output-return-bypass",
        anchor_kind="aisle_access",
        interaction_kind="none",
        approach_directions=["northeast"],
    )
    input_return_anchor = _placement_anchor(
        input_table,
        layout_revision=layout_revision,
        role="inspection-input-return-bypass",
        anchor_kind="aisle_access",
        interaction_kind="none",
        approach_directions=["northwest"],
    )
    output_anchor = _placement_anchor(
        output_container,
        layout_revision=layout_revision,
        role="inspection-output-container",
        anchor_kind="station_unload",
        interaction_kind="unload",
        approach_directions=["south"],
    )
    anchors = [
        input_anchor,
        inspect_anchor,
        output_anchor,
        output_return_anchor,
        input_return_anchor,
    ]
    inspect_in = _one_way_program(
        actor,
        layout_revision=layout_revision,
        actor_profile_id=actor_profile_id,
        actor_profile_revision=actor_profile_revision,
        program_family="inspection",
        phase="inspection_pick",
        stops=[
            _stop(
                input_anchor,
                layout_revision=layout_revision,
                role="inspection-pick",
                interaction_kind="load",
            ),
            _stop(
                inspect_anchor,
                layout_revision=layout_revision,
                role="inspection-process",
                interaction_kind="inspect",
            ),
        ],
    )
    inspect_out = _one_way_program(
        actor,
        layout_revision=layout_revision,
        actor_profile_id=actor_profile_id,
        actor_profile_revision=actor_profile_revision,
        program_family="inspection",
        phase="inspection_place",
        stops=[
            _stop(
                inspect_anchor,
                layout_revision=layout_revision,
                role="inspection-process-out",
                interaction_kind="inspect",
            ),
            _stop(
                output_anchor,
                layout_revision=layout_revision,
                role="inspection-place",
                interaction_kind="unload",
            ),
        ],
    )
    return_empty = _one_way_program(
        actor,
        layout_revision=layout_revision,
        actor_profile_id=actor_profile_id,
        actor_profile_revision=actor_profile_revision,
        program_family="inspection",
        phase="return_empty",
        stops=[
            _stop(
                output_anchor,
                layout_revision=layout_revision,
                role="inspection-output-return",
                interaction_kind="unload",
            ),
            _stop(
                output_return_anchor,
                layout_revision=layout_revision,
                role="inspection-output-return-bypass",
                interaction_kind="none",
            ),
            _stop(
                input_return_anchor,
                layout_revision=layout_revision,
                role="inspection-input-return-bypass",
                interaction_kind="none",
            ),
            _stop(
                input_anchor,
                layout_revision=layout_revision,
                role="inspection-next-pick",
                interaction_kind="load",
            ),
        ],
    )
    programs = [inspect_in, inspect_out, return_empty]
    phases = ["inspection_pick", "inspection_place", "return_empty"]
    return {
        "anchors": anchors,
        "programs": programs,
        "group": {
            "cycleKind": "inspection",
            "actorPlacementId": actor["placementId"],
            "primaryProgramId": inspect_in["movementProgramId"],
            "candidateProgramIds": [
                program["movementProgramId"] for program in programs
            ],
            "snapshotAnchorIds": [
                anchor["navigationAnchorId"] for anchor in anchors
            ],
            "cycleSegments": [
                {
                    "phase": phase,
                    "movementProgramId": program["movementProgramId"],
                }
                for phase, program in zip(phases, programs)
            ],
            "requestedStopPlacementIds": [
                input_table["placementId"],
                inspection_machine["placementId"],
                output_container["placementId"],
            ],
            "returnBypassPlacementIds": [
                output_container["placementId"],
                input_table["placementId"],
            ],
            "reviewedStopActions": [
                {
                    "stop": "A",
                    "placementId": input_table["placementId"],
                    "actions": ["load"],
                },
                {
                    "stop": "B",
                    "placementId": inspection_machine["placementId"],
                    "actions": ["load", "inspect", "record", "unload"],
                },
                {
                    "stop": "C",
                    "placementId": output_container["placementId"],
                    "actions": ["unload"],
                },
            ],
        },
    }


def build_prototype_itinerary(
    layout: Mapping[str, Any],
    inventory: Mapping[str, Any],
    *,
    layout_revision: str,
    actor_profile_id: str,
    actor_profile_revision: str,
) -> dict[str, Any]:
    """Build anchors and movement programs for the operators in an inventory.

    Generic stations receive candidate programs over their existing work
    surfaces. Reviewed Packaging and Inspection stations receive three linked
    one-way legs over exact existing placements. Every inferred program
    remains bound to the immutable source revision.
    """

    placements = {
        str(item["placementId"]): item
        for item in layout.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    actors = [item for item in inventory["actors"] if item["actorKind"] == "operator"]
    stations = list(inventory["stations"])

    anchors: list[dict[str, Any]] = []
    programs: list[dict[str, Any]] = []
    program_candidates: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []

    for actor in sorted(actors, key=lambda item: item["placementId"]):
        actor_placement = placements.get(str(actor["placementId"]))
        if actor_placement is None:
            raise ValueError(
                "Prototype itinerary actor does not exist in the bound layout: "
                f"{actor['placementId']}"
            )
        actor_revision = str(
            actor_placement.get("assetDefinitionRevision") or ""
        )
        zone_id = actor["zoneId"]
        if str(actor.get("zoneLabel") or "").startswith(
            _PACKAGING_ZONE_PREFIX
        ):
            packaging = _packaging_cycle(
                actor,
                inventory,
                layout_revision=layout_revision,
                actor_profile_id=actor_profile_id,
                actor_profile_revision=actor_profile_revision,
            )
            if packaging is None:
                unsupported.append(
                    {
                        "actorPlacementId": actor["placementId"],
                        "zoneId": zone_id,
                        "code": "packaging_cycle_assets_unavailable",
                        "reason": (
                            "the station must contain exactly two pallets, "
                            "one work surface, and one mobile cart"
                        ),
                    }
                )
                continue
            anchors.extend(packaging["anchors"])
            programs.extend(packaging["programs"])
            program_candidates.append(packaging["group"])
            continue
        if str(actor.get("zoneLabel") or "").startswith(
            _INSPECTION_ZONE_PREFIXES
        ):
            inspection = _inspection_cycle(
                actor,
                inventory,
                layout_revision=layout_revision,
                actor_profile_id=actor_profile_id,
                actor_profile_revision=actor_profile_revision,
            )
            if inspection is None:
                unsupported.append(
                    {
                        "actorPlacementId": actor["placementId"],
                        "zoneId": zone_id,
                        "code": "inspection_cycle_assets_unavailable",
                        "reason": (
                            "the station must contain exactly one left input "
                            "worktable, one laboratory workstation, and one "
                            "right output container"
                        ),
                    }
                )
                continue
            anchors.extend(inspection["anchors"])
            programs.extend(inspection["programs"])
            program_candidates.append(inspection["group"])
            continue
        surfaces = sorted(
            (
                item
                for item in stations
                if item["zoneId"] == zone_id and _is_work_surface(item["assetId"])
            ),
            key=lambda item: item["placementId"],
        )
        if not surfaces:
            unsupported.append(
                {
                    "actorPlacementId": actor["placementId"],
                    "zoneId": zone_id,
                    "code": "needs_authored_stops",
                    "reason": "no existing work surface inside the actor's own zone",
                }
            )
            continue

        home_anchor_id = _stable("na", ["home", actor["placementId"], layout_revision])
        anchors.append(
            {
                "navigationAnchorId": home_anchor_id,
                "anchorKind": "actor_home",
                "ownerRef": {"ownerKind": "placement", "ownerId": actor["placementId"]},
                "interactionKind": "none",
                "positionAuthority": "derived",
                # Derived anchors reference geometry; persisting a generated
                # coordinate here is refused by the contract, correctly.
                "localPosition": None,
                "derivedPositionRef": {
                    "sourceKind": "placement_transform",
                    "sourceId": actor["placementId"],
                    "sourceRevision": actor_revision,
                },
                "approachDirections": [],
                "actorClasses": ["pedestrian"],
                "evidenceStatus": "derived",
                "evidence": [],
                "reviewStatus": "pending",
            }
        )

        stops = [
            {
                "stopId": _stable("nst", ["home-out", actor["placementId"], layout_revision]),
                "navigationAnchorId": home_anchor_id,
                "interactionKind": "none",
                "required": True,
            }
        ]
        for surface in surfaces:
            surface_placement = placements.get(str(surface["placementId"]))
            if surface_placement is None:
                raise ValueError(
                    "Prototype itinerary stop does not exist in the bound layout: "
                    f"{surface['placementId']}"
                )
            surface_revision = str(
                surface_placement.get("assetDefinitionRevision") or ""
            )
            anchor_id = _stable("na", ["work", surface["placementId"], layout_revision])
            anchors.append(
                {
                    "navigationAnchorId": anchor_id,
                    "anchorKind": "station_operate",
                    "ownerRef": {
                        "ownerKind": "placement",
                        "ownerId": surface["placementId"],
                    },
                    "interactionKind": "operate",
                    "positionAuthority": "inferred",
                    "localPosition": None,
                    "derivedPositionRef": {
                        "sourceKind": "placement_access",
                        "sourceId": surface["placementId"],
                        "sourceRevision": surface_revision,
                    },
                    "approachDirections": [],
                    "actorClasses": ["pedestrian"],
                    "evidenceStatus": "inferred",
                    "evidence": [],
                    "reviewStatus": "pending",
                }
            )
            stops.append(
                {
                    "stopId": _stable("nst", ["work", surface["placementId"], layout_revision]),
                    "navigationAnchorId": anchor_id,
                    "interactionKind": "operate",
                    "required": True,
                }
            )

        primary_program = {
                "movementProgramId": _stable(
                    "nmp", ["operator", actor["placementId"], layout_revision]
                ),
                "actorPlacementId": actor["placementId"],
                "actorClass": "pedestrian",
                "actorProfileRef": {
                    "profileKind": "pedestrian",
                    "profileId": actor_profile_id,
                    "profileRevision": actor_profile_revision,
                },
                "orderedStops": stops,
                "loopMode": "closed_loop",
                "requiredRouteIds": [],
                # The contract requires every ordered stop to also be declared
                # a required anchor, so a stop can never be silently skipped.
                "requiredAnchorIds": sorted({stop["navigationAnchorId"] for stop in stops}),
                "forbiddenZoneIds": [],
                "forbiddenRouteIds": [],
                "manualPathConstraintIds": [],
                "handoffProgramIds": [],
                "sourceRevisions": {
                    "layout": layout_revision,
                    "actor_profile": actor_profile_revision,
                },
                "evidenceStatus": "inferred",
                "evidence": [],
                "reviewStatus": "pending",
            }
        programs.append(primary_program)
        candidate_ids = [primary_program["movementProgramId"]]
        if len(stops) > 2:
            work_stops = stops[1:]
            fallback_stop_sets = [
                [
                    stop
                    for candidate_index, stop in enumerate(work_stops)
                    if candidate_index != omitted_index
                ]
                for omitted_index in range(len(work_stops))
            ]
            fallback_stop_sets.extend([[stop] for stop in work_stops])
            seen_stop_sets: set[tuple[str, ...]] = set()
            for fallback_stops in fallback_stop_sets:
                stop_anchor_ids = tuple(
                    stop["navigationAnchorId"] for stop in fallback_stops
                )
                if not stop_anchor_ids or stop_anchor_ids in seen_stop_sets:
                    continue
                seen_stop_sets.add(stop_anchor_ids)
                fallback = dict(primary_program)
                fallback["movementProgramId"] = _stable(
                    "nmp",
                    [
                        "operator-fallback",
                        actor["placementId"],
                        *stop_anchor_ids,
                        layout_revision,
                    ],
                )
                fallback["orderedStops"] = [stops[0], *fallback_stops]
                fallback["requiredAnchorIds"] = sorted({
                    stops[0]["navigationAnchorId"],
                    *stop_anchor_ids,
                })
                programs.append(fallback)
                candidate_ids.append(fallback["movementProgramId"])
        program_candidates.append({
            "actorPlacementId": actor["placementId"],
            "primaryProgramId": primary_program["movementProgramId"],
            "candidateProgramIds": candidate_ids,
            "requestedStopPlacementIds": [
                surface["placementId"] for surface in surfaces
            ],
        })

    extension = {
        "schemaVersion": FACILITY_NAVIGATION_SCHEMA_VERSION,
        "anchors": anchors,
        "movementPrograms": programs,
        "manualPathConstraints": [],
        "handoffPrograms": [],
    }

    payload = json.dumps(extension, sort_keys=True, separators=(",", ":"))
    return {
        "schemaVersion": PROTOTYPE_ITINERARY_SCHEMA_VERSION,
        "prototypeMode": True,
        "productionEligible": False,
        "boundLayoutId": layout.get("layoutId"),
        "boundLayoutRevision": layout_revision,
        "itineraryRevision": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "facilityNavigation": extension,
        "programCandidates": program_candidates,
        "unsupportedActors": unsupported,
        "qualification": PROTOTYPE_ITINERARY_QUALIFICATION,
    }


def assert_itinerary_binding(
    itinerary: Mapping[str, Any],
    layout: Mapping[str, Any],
    layout_revision: str,
) -> None:
    """Refuse a prototype itinerary that has drifted from its layout."""

    if itinerary.get("boundLayoutRevision") != layout_revision:
        raise ValueError(
            "Prototype itinerary is bound to a different layout revision: "
            f"{itinerary.get('boundLayoutRevision')} != {layout_revision}"
        )
    placement_ids = {item["placementId"] for item in layout.get("placements") or []}
    referenced = {
        anchor["ownerRef"]["ownerId"]
        for anchor in itinerary["facilityNavigation"]["anchors"]
    } | {
        program["actorPlacementId"]
        for program in itinerary["facilityNavigation"]["movementPrograms"]
    }
    missing = sorted(referenced - placement_ids)
    if missing:
        raise ValueError(f"Prototype itinerary references absent placements: {missing}")
