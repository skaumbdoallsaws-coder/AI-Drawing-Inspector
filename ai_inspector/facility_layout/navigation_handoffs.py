"""NAV6 deterministic topology for actor-to-FIFO handoffs."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import threading
from typing import Any, Mapping, Sequence

from .errors import FacilityNotFoundError, FacilityValidationError
from .navigation_contract import (
    navigation_identity_index,
    navigation_stable_id,
    validate_facility_navigation_extension,
    validate_journey_solution,
)


FACILITY_NAVIGATION_HANDOFF_RESULT_SCHEMA = "facility-navigation-handoff-result-v1"
FACILITY_NAVIGATION_HANDOFF_COMPILER_VERSION = "facility-navigation-handoff-compiler-v1"
FACILITY_NAVIGATION_HANDOFF_STORE_MAXIMUM = 128
FACILITY_NAVIGATION_HANDOFF_MAXIMUM_CANONICAL_BYTES = 65_536
FACILITY_NAVIGATION_HANDOFF_QUALIFICATION = (
    "Derived handoff topology binds two existing actor journeys and one material "
    "transfer edge. Sequence does not imply timing, simultaneous presence, "
    "throughput, staffing sufficiency, or operational safety."
)


class FacilityNavigationHandoffError(FacilityValidationError):
    """A handoff cannot be compiled from the reviewed topology."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError) as error:
        raise FacilityNavigationHandoffError(
            "facility_navigation_handoff_invalid",
            "Handoff topology must be finite canonical JSON.",
        ) from error


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def compile_handoff_topology(
    layout: Mapping[str, Any],
    handoff_program_id: str,
    journeys: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compile one handoff without converting material flow into walking."""

    extension = (
        layout.get("extensions", {}).get("facilityNavigation")
        if isinstance(layout.get("extensions"), Mapping)
        else None
    )
    if not isinstance(extension, Mapping):
        raise FacilityNavigationHandoffError(
            "facility_navigation_handoff_unavailable",
            "The layout has no authored handoff program.",
        )
    extension = validate_facility_navigation_extension(
        extension,
        navigation_identity_index(layout),
    )
    handoff = next(
        (
            item
            for item in extension["handoffPrograms"]
            if item["handoffProgramId"] == handoff_program_id
        ),
        None,
    )
    if handoff is None:
        raise FacilityNavigationHandoffError(
            "facility_navigation_handoff_unavailable",
            "The requested handoff program does not exist.",
        )
    programs = {
        item["movementProgramId"]: item for item in extension["movementPrograms"]
    }
    source_program = programs[handoff["sourceMovementProgramId"]]
    target_program = programs[handoff["targetMovementProgramId"]]
    anchors = {item["navigationAnchorId"]: item for item in extension["anchors"]}
    source_anchor = anchors[handoff["sourceFifoAnchorId"]]
    target_anchor = anchors[handoff["targetFifoAnchorId"]]
    findings = []
    if source_program["actorPlacementId"] == target_program["actorPlacementId"]:
        findings.append({
            "code": "facility_navigation_handoff_distinct_actor_required",
            "severity": "error",
            "sourceRefIds": [handoff_program_id],
        })
    if source_anchor["anchorKind"] != "fifo_output":
        findings.append({
            "code": "facility_navigation_handoff_source_role_invalid",
            "severity": "error",
            "sourceRefIds": [handoff["sourceFifoAnchorId"]],
        })
    if target_anchor["anchorKind"] != "fifo_input":
        findings.append({
            "code": "facility_navigation_handoff_target_role_invalid",
            "severity": "error",
            "sourceRefIds": [handoff["targetFifoAnchorId"]],
        })
    by_program = {}
    for raw in journeys:
        journey = validate_journey_solution(raw)
        program_id = journey["movementProgramId"]
        if program_id in by_program:
            findings.append({
                "code": "facility_navigation_handoff_journey_ambiguous",
                "severity": "error",
                "sourceRefIds": [program_id],
            })
        by_program[program_id] = journey
    source_journey = by_program.get(source_program["movementProgramId"])
    target_journey = by_program.get(target_program["movementProgramId"])
    for role, program, anchor_id, journey in (
        ("source", source_program, handoff["sourceFifoAnchorId"], source_journey),
        ("target", target_program, handoff["targetFifoAnchorId"], target_journey),
    ):
        if journey is None:
            findings.append({
                "code": "facility_navigation_handoff_journey_missing",
                "severity": "error",
                "role": role,
                "sourceRefIds": [program["movementProgramId"]],
            })
        elif journey["outcome"] != "accepted" or anchor_id not in journey["orderedAnchorIds"]:
            findings.append({
                "code": "facility_navigation_handoff_endpoint_unreachable",
                "severity": "error",
                "role": role,
                "sourceRefIds": [journey["journeySolutionId"], anchor_id],
            })
        elif journey["actorPlacementId"] != program["actorPlacementId"]:
            findings.append({
                "code": "facility_navigation_handoff_actor_mismatch",
                "severity": "error",
                "role": role,
                "sourceRefIds": [journey["journeySolutionId"]],
            })
    findings.sort(
        key=lambda item: (
            item["code"],
            item.get("role", ""),
            item.get("sourceRefIds", []),
        )
    )
    complete = not findings
    material_edge = {
        "materialEdgeId": navigation_stable_id(
            "nne",
            {
                "kind": "material-handoff",
                "handoffProgramId": handoff_program_id,
                "source": handoff["sourceFifoAnchorId"],
                "target": handoff["targetFifoAnchorId"],
                "material": handoff["materialIdentityRef"],
            },
        ),
        "sourceFifoAnchorId": handoff["sourceFifoAnchorId"],
        "targetFifoAnchorId": handoff["targetFifoAnchorId"],
        "materialIdentityRef": handoff["materialIdentityRef"],
        "edgeKind": "material_transfer",
        "renderAsActorWalking": False,
    }
    result = {
        "schemaVersion": FACILITY_NAVIGATION_HANDOFF_RESULT_SCHEMA,
        "compilerVersion": FACILITY_NAVIGATION_HANDOFF_COMPILER_VERSION,
        "handoffProgramId": handoff_program_id,
        "outcome": "complete" if complete else "incomplete",
        "sourceParticipant": {
            "movementProgramId": source_program["movementProgramId"],
            "actorPlacementId": source_program["actorPlacementId"],
            "fifoAnchorId": handoff["sourceFifoAnchorId"],
            "journeySolutionId": (
                source_journey["journeySolutionId"] if source_journey else None
            ),
        },
        "targetParticipant": {
            "movementProgramId": target_program["movementProgramId"],
            "actorPlacementId": target_program["actorPlacementId"],
            "fifoAnchorId": handoff["targetFifoAnchorId"],
            "journeySolutionId": (
                target_journey["journeySolutionId"] if target_journey else None
            ),
        },
        "materialEdge": material_edge,
        "sequencePolicy": handoff["sequencePolicy"],
        "timingAuthority": handoff["timingAuthority"],
        "timingKnown": handoff["timingAuthority"] in {
            "user_authored", "controlled_source"
        },
        "topologyComplete": complete,
        "findings": findings,
        "qualification": FACILITY_NAVIGATION_HANDOFF_QUALIFICATION,
    }
    result["resultFingerprint"] = _fingerprint(result)
    result["handoffResultId"] = f"nhr-{result['resultFingerprint'][:24]}"
    size = 0
    for _ in range(4):
        result["canonicalBytes"] = size
        measured = len(_canonical_bytes(result))
        if measured == size:
            break
        size = measured
    result["canonicalBytes"] = len(_canonical_bytes(result))
    size = result["canonicalBytes"]
    if size > FACILITY_NAVIGATION_HANDOFF_MAXIMUM_CANONICAL_BYTES:
        raise FacilityNavigationHandoffError(
            "facility_navigation_handoff_budget_exceeded",
            "The handoff result exceeds its canonical byte ceiling.",
            details={"canonicalBytes": size},
        )
    return json.loads(_canonical_bytes(result).decode("ascii"))


def handoff_topology_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "facility-navigation-handoff-summary-v1",
        "handoffResultId": result["handoffResultId"],
        "handoffProgramId": result["handoffProgramId"],
        "outcome": result["outcome"],
        "topologyComplete": result["topologyComplete"],
        "sourceActorPlacementId": result["sourceParticipant"]["actorPlacementId"],
        "targetActorPlacementId": result["targetParticipant"]["actorPlacementId"],
        "materialIdentityRef": result["materialEdge"]["materialIdentityRef"],
        "timingKnown": result["timingKnown"],
        "findingCodes": sorted({item["code"] for item in result["findings"]}),
        "resultFingerprint": result["resultFingerprint"],
        "qualification": FACILITY_NAVIGATION_HANDOFF_QUALIFICATION,
    }


class FacilityNavigationHandoffStore:
    def __init__(self, maximum_items: int = FACILITY_NAVIGATION_HANDOFF_STORE_MAXIMUM) -> None:
        self.maximum_items = int(maximum_items)
        self._lock = threading.RLock()
        self._values: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def put(self, result: Mapping[str, Any]) -> dict[str, Any]:
        value = deepcopy(dict(result))
        identity = str(value["handoffResultId"])
        with self._lock:
            self._values[identity] = value
            self._values.move_to_end(identity)
            while len(self._values) > self.maximum_items:
                self._values.popitem(last=False)
        return deepcopy(value)

    def get(self, identity: str) -> dict[str, Any]:
        with self._lock:
            value = self._values.get(identity)
            if value is None:
                raise FacilityNotFoundError(
                    "facility_navigation_handoff_result_unavailable",
                    "The requested handoff result is unavailable.",
                )
            self._values.move_to_end(identity)
            return deepcopy(value)


__all__ = [
    "FACILITY_NAVIGATION_HANDOFF_COMPILER_VERSION",
    "FACILITY_NAVIGATION_HANDOFF_QUALIFICATION",
    "FACILITY_NAVIGATION_HANDOFF_RESULT_SCHEMA",
    "FacilityNavigationHandoffError",
    "FacilityNavigationHandoffStore",
    "compile_handoff_topology",
    "handoff_topology_summary",
]
