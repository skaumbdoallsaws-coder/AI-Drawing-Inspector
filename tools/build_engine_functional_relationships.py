"""Build the reviewed functional relationship graph for assembly 100001.

The script expands reviewed interface patterns against the current assembly
instance names. It intentionally does not copy dimensions, tolerances, or FAI
measurements into the functional graph.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY_PATH = ROOT / "400S_Sorted_Library" / "assemblies" / "100001_assembly.json"
CATALOG_PATH = (
    ROOT
    / "ai_inspector"
    / "product_intelligence"
    / "catalogs"
    / "100001.json"
)
PROFILE_PATHS = {
    part_number: ROOT / "400S_Sorted_Library" / f"{part_number}_inspection_profile.json"
    for part_number in ("100002", "100003", "100004", "100005", "100006", "100007", "100008", "100009")
}
MOTION_PATH = ROOT / "generated" / "engine_motion" / "motion" / "engine4cyl_crank_cycle_summary.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _instance_id(source_name: str) -> str:
    value = source_name.strip().lower().replace("/", ".")
    value = re.sub(r"[^a-z0-9.:-]+", "-", value).strip("-.")
    return f"instance:{value}"


def _feature(
    feature_ref: str,
    label: str,
    semantic_tags: list[str],
    aliases: list[str],
    source_ref: str,
) -> dict[str, Any]:
    return {
        "feature_ref": feature_ref,
        "label": label,
        "semantic_tags": semantic_tags,
        "aliases": aliases,
        "source_refs": [source_ref],
    }


def _component_types() -> list[dict[str, Any]]:
    return [
        {
            "part_number": "100002",
            "name": "Lower Engine Block",
            "description": "Fixed crankcase structure that supports the crankshaft and provides the lower moving-clearance envelope.",
            "mobility": "fixed",
            "functional_roles": ["crankshaft support", "rotation-axis locator", "clearance enclosure", "lower structural base"],
            "functional_features": [
                _feature(
                    "lower-block.main-bearing-bores",
                    "Main bearing bores in the end walls",
                    ["internal_diameter", "bearing_surface", "axis_location"],
                    ["main bearing bore", "end wall bore", "crankshaft support bore"],
                    "profile:100002",
                ),
                _feature(
                    "lower-block.end-bearing-faces",
                    "End bearing and locating faces",
                    ["planar_face", "axial_location", "bearing_face"],
                    ["bearing boss face", "end face", "spot face"],
                    "profile:100002",
                ),
                _feature(
                    "lower-block.crankcase-clearance-envelope",
                    "Inner crankcase clearance envelope",
                    ["clearance_surface", "enclosure", "internal_surface"],
                    ["crankcase inner wall", "semicylindrical crankcase wall", "counterweight clearance"],
                    "profile:100002",
                ),
                _feature(
                    "lower-block.open-deck-interface",
                    "Open deck and upper wall rim",
                    ["structural_interface", "datum_transfer", "passage"],
                    ["open deck", "upper wall rim", "upper block interface"],
                    "profile:100002",
                ),
            ],
        },
        {
            "part_number": "100003",
            "name": "Crankshaft",
            "description": "Rotating member that converts the four connecting-rod forces into shaft torque.",
            "mobility": "rotating",
            "functional_roles": ["rotating driver", "motion converter", "torque output", "counterbalanced shaft"],
            "functional_features": [
                _feature(
                    "crankshaft.main-journals",
                    "Main journal bearing surfaces",
                    ["external_diameter", "journal", "rotation_axis"],
                    ["main journal", "bearing journal", "crankshaft support journal"],
                    "profile:100003",
                ),
                _feature(
                    "crankshaft.crank-pin-journals",
                    "Offset crank-pin journals",
                    ["external_diameter", "journal", "eccentric_driver"],
                    ["crank pin", "rod journal", "big end journal"],
                    "profile:100003",
                ),
                _feature(
                    "crankshaft.counterweight-envelope",
                    "Counterweight moving envelope",
                    ["dynamic_envelope", "clearance_member", "rotating_mass"],
                    ["counterweight", "crank web", "rotating clearance envelope"],
                    "profile:100003",
                ),
                _feature(
                    "crankshaft.output-flange",
                    "Output flange",
                    ["torque_interface", "external_connection", "rotating_face"],
                    ["output flange", "flange bolt circle", "driven coupling"],
                    "profile:100003",
                ),
                _feature(
                    "crankshaft.nose-drive-interface",
                    "Nose drive interface",
                    ["torque_input", "rotation_axis", "external_connection"],
                    ["nose stub", "drive interface", "motor interface"],
                    "profile:100003",
                ),
            ],
        },
        {
            "part_number": "100004",
            "name": "Connecting Rod",
            "description": "Oscillating load path between one crank pin and one piston pin.",
            "mobility": "oscillating",
            "functional_roles": ["reciprocating load path", "motion link", "big-end bearing half", "small-end bearing"],
            "functional_features": [
                _feature(
                    "connecting-rod.small-end-bore",
                    "Small-end piston-pin bore",
                    ["internal_diameter", "oscillating_bearing", "pin_joint"],
                    ["small end bore", "piston pin bore", "wrist pin bore"],
                    "profile:100004",
                ),
                _feature(
                    "connecting-rod.small-end-side-faces",
                    "Small-end side faces and boss",
                    ["axial_guidance", "side_clearance", "oscillating_member"],
                    ["small end boss", "rod side face", "small end side face"],
                    "profile:100004",
                ),
                _feature(
                    "connecting-rod.big-end-half-bore",
                    "Big-end upper half bearing surface",
                    ["internal_diameter", "bearing_half", "split_bore"],
                    ["big end half bore", "split saddle", "crank pin bore"],
                    "profile:100004",
                ),
                _feature(
                    "connecting-rod.cap-split-faces",
                    "Big-end cap split faces",
                    ["clamp_interface", "joint_face", "bore_integrity"],
                    ["cap split face", "rod split face", "big end joint face"],
                    "profile:100004",
                ),
                _feature(
                    "connecting-rod.fastener-bores",
                    "Cap fastener bores and seats",
                    ["fastener_interface", "clamp_load_path", "alignment"],
                    ["cap bolt hole", "fastener bore", "bolt seat"],
                    "profile:100004",
                ),
            ],
        },
        {
            "part_number": "100005",
            "name": "Connecting Rod Cap",
            "description": "Removable lower bearing half that closes a connecting-rod big end around a crank pin.",
            "mobility": "carried",
            "functional_roles": ["big-end bearing half", "removable retainer", "clamped joint member"],
            "functional_features": [
                _feature(
                    "rod-cap.big-end-half-bore",
                    "Big-end lower half bearing surface",
                    ["internal_diameter", "bearing_half", "split_bore"],
                    ["cap half bore", "crank pin saddle", "big end lower bore"],
                    "profile:100005",
                ),
                _feature(
                    "rod-cap.split-face",
                    "Cap split face",
                    ["clamp_interface", "joint_face", "bore_integrity"],
                    ["split face", "cap joint face", "rod mating face"],
                    "profile:100005",
                ),
                _feature(
                    "rod-cap.fastener-bores",
                    "Cap fastener bore stack",
                    ["fastener_interface", "clamp_load_path", "alignment"],
                    ["bolt bore", "fastener bore", "cap screw passage"],
                    "profile:100005",
                ),
            ],
        },
        {
            "part_number": "100006",
            "name": "Piston",
            "description": "Reciprocating member guided by a cylinder bore and connected to a rod through a floating pin.",
            "mobility": "reciprocating",
            "functional_roles": ["reciprocating load receiver", "cylinder guided member", "ring carrier", "pin-joint support"],
            "functional_features": [
                _feature(
                    "piston.skirt-running-surface",
                    "Piston body and skirt outside running surface",
                    ["external_diameter", "sliding_surface", "radial_guidance", "piston_body"],
                    ["main outside diameter", "outer diameter", "outside diameter", "piston body diameter", "piston od", "skirt outside surface"],
                    "profile:100006",
                ),
                _feature(
                    "piston.pin-bores",
                    "Pin bores through the piston bosses",
                    ["internal_diameter", "bearing_surface", "pin_joint", "load_transfer"],
                    ["pin bore", "wrist pin hole", "wrist-pin hole", "piston pin bore", "pin hole"],
                    "profile:100006",
                ),
                _feature(
                    "piston.boss-counterbores",
                    "Boss faces and small-end guidance pockets",
                    ["axial_guidance", "side_clearance", "counterbore", "pin_boss"],
                    ["boss face counterbore", "wrist pin boss", "pin boss", "boss depth"],
                    "profile:100006",
                ),
                _feature(
                    "piston.ring-grooves",
                    "Piston ring grooves",
                    ["groove", "ring_retention", "sealing_support"],
                    ["ring groove", "ring grooves", "groove width", "groove depth", "ring land"],
                    "profile:100006",
                ),
                _feature(
                    "piston.crown",
                    "Piston crown and dome",
                    ["load_surface", "combustion_boundary", "overall_height"],
                    ["crown dome", "piston crown", "dome rise", "top face"],
                    "profile:100006",
                ),
                _feature(
                    "piston.skirt-reliefs",
                    "Skirt arched reliefs and lower moving envelope",
                    ["dynamic_envelope", "clearance_member", "skirt_relief"],
                    ["skirt relief", "arched relief", "lower side relief", "skirt cutout"],
                    "profile:100006",
                ),
            ],
        },
        {
            "part_number": "100007",
            "name": "Piston Pin",
            "description": "Floating journal that transfers load between a piston and connecting rod while permitting rod oscillation.",
            "mobility": "carried",
            "functional_roles": ["journal", "load-transfer pin", "oscillation axis"],
            "functional_features": [
                _feature(
                    "piston-pin.outer-bearing-surface",
                    "Outer bearing surface",
                    ["external_diameter", "journal", "pin_joint", "load_transfer"],
                    ["pin outer diameter", "bearing surface", "piston pin diameter", "wrist pin"],
                    "profile:100007",
                ),
                _feature(
                    "piston-pin.end-faces",
                    "Pin end faces",
                    ["axial_boundary", "retention_interface"],
                    ["pin end", "end face", "pin chamfer"],
                    "profile:100007",
                ),
            ],
        },
        {
            "part_number": "100008",
            "name": "Socket Head Cap Screw",
            "description": "Fastener that clamps a connecting-rod cap to its rod body.",
            "mobility": "carried",
            "functional_roles": ["clamp fastener", "joint preload source", "cap retainer"],
            "functional_features": [
                _feature(
                    "cap-screw.thread-interface",
                    "Threaded engagement",
                    ["thread", "clamp_interface", "retention"],
                    ["thread", "threaded end", "fastener engagement"],
                    "profile:100008",
                ),
                _feature(
                    "cap-screw.head-bearing-face",
                    "Head bearing face",
                    ["bearing_face", "clamp_load_path", "fastener_head"],
                    ["head face", "bearing face", "socket head"],
                    "profile:100008",
                ),
                _feature(
                    "cap-screw.shank",
                    "Fastener shank",
                    ["alignment", "shear_path", "fastener_body"],
                    ["shank", "plain shank", "bolt body"],
                    "profile:100008",
                ),
            ],
        },
        {
            "part_number": "100009",
            "name": "Piston Ring",
            "description": "Split resilient ring retained by a piston groove and sliding against the cylinder bore to support sealing.",
            "mobility": "carried",
            "functional_roles": ["sliding seal element", "groove-retained element", "bore contact element"],
            "functional_features": [
                _feature(
                    "piston-ring.outer-bore-contact",
                    "Outer bore-contact surface",
                    ["external_diameter", "sliding_contact", "sealing_surface"],
                    ["ring outer diameter", "bore contact", "outer sealing face"],
                    "profile:100009",
                ),
                _feature(
                    "piston-ring.inner-groove-seat",
                    "Inner groove-seat surface",
                    ["internal_diameter", "groove_seat", "retention"],
                    ["ring inner diameter", "groove seat", "inner ring face"],
                    "profile:100009",
                ),
                _feature(
                    "piston-ring.side-faces",
                    "Ring side faces",
                    ["axial_guidance", "side_clearance", "groove_contact"],
                    ["ring side face", "ring thickness", "groove side contact"],
                    "profile:100009",
                ),
                _feature(
                    "piston-ring.end-gap",
                    "Ring end gap",
                    ["installation_compliance", "thermal_accommodation", "split"],
                    ["end gap", "ring split", "ring opening"],
                    "profile:100009",
                ),
            ],
        },
    ]


def _external_entities() -> list[dict[str, Any]]:
    return [
        {
            "entity_id": "external:upper-cylinder-block",
            "name": "Upper cylinder block and cylinder-bore system",
            "presence": "absent_from_extract",
            "functional_roles": ["piston guide", "ring sealing surface", "upper engine structure"],
            "functional_features": [
                _feature(
                    "upper-block.cylinder-bores",
                    "Cylinder bores that guide the pistons",
                    ["internal_diameter", "sliding_surface", "radial_guidance", "sealing_surface"],
                    ["cylinder bore", "upper block bore", "piston travel path"],
                    "profile:100002",
                ),
                _feature(
                    "upper-block.lower-mating-face",
                    "Lower mating face at the crankcase deck",
                    ["structural_interface", "datum_transfer", "joint_face"],
                    ["upper block lower face", "deck mating face", "cylinder block mount"],
                    "profile:100002",
                ),
            ],
            "evidence_refs": ["profile:100002", "profile:100006", "profile:100009"],
        },
        {
            "entity_id": "external:driven-system",
            "name": "External driven system",
            "presence": "absent_from_extract",
            "functional_roles": ["receive crankshaft torque", "provide external rotational load"],
            "functional_features": [
                _feature(
                    "driven-system.input-coupling",
                    "Input coupling to the crankshaft output flange",
                    ["torque_interface", "external_connection", "rotating_member"],
                    ["driven coupling", "output connection", "flange mate"],
                    "profile:100003",
                )
            ],
            "evidence_refs": ["profile:100003"],
        },
    ]


def _evidence(
    source_ref: str, locator: str, classification: str, claim: str
) -> dict[str, str]:
    return {
        "source_ref": source_ref,
        "locator": locator,
        "classification": classification,
        "claim": claim,
    }


def _participant(
    participant_id: str,
    part_number: str | None,
    feature_refs: list[str],
    role: str,
) -> dict[str, Any]:
    return {
        "participant_id": participant_id,
        "part_number": part_number,
        "feature_refs": feature_refs,
        "role": role,
    }


def _interface(
    interface_id: str,
    pattern_id: str,
    name: str,
    interface_type: str,
    participants: list[dict[str, Any]],
    functions: list[str],
    motion_type: str,
    allowed: list[str],
    constrained: list[str],
    transfer_modes: list[str],
    requirements: list[str],
    evidence: list[dict[str, str]],
    confidence: float,
    review_status: str,
) -> dict[str, Any]:
    return {
        "interface_id": interface_id,
        "pattern_id": pattern_id,
        "name": name,
        "interface_type": interface_type,
        "participants": participants,
        "functions": functions,
        "relative_motion": {
            "type": motion_type,
            "allowed": allowed,
            "constrained": constrained,
        },
        "transfer_modes": transfer_modes,
        "qualitative_requirements": requirements,
        "evidence": evidence,
        "confidence": confidence,
        "review_status": review_status,
    }


def build_graph() -> dict[str, Any]:
    assembly = json.loads(ASSEMBLY_PATH.read_text(encoding="utf-8-sig"))
    cache = assembly.get("partDataCache") or {}
    key_to_part = {}
    for key, value in cache.items():
        identity = (value or {}).get("identity") or {}
        custom = identity.get("customProperties") or {}
        part_number = str(custom.get("PartNo") or identity.get("partNumber") or "").strip()
        if part_number:
            key_to_part[str(key).lower()] = part_number

    source_to_id = {
        str(component["name"]): _instance_id(str(component["name"]))
        for component in assembly.get("components") or []
    }
    cylinder_by_top_level = {
        "piston pin-1": "one",
        "connecting rod-1": "one",
        "connecting rod cap-1": "one",
        "Socket Head Cap Screw-1": "one",
        "Socket Head Cap Screw-2": "one",
        "Piston Assembly-1": "one",
        "piston pin-2": "two",
        "connecting rod-2": "two",
        "connecting rod cap-2": "two",
        "Socket Head Cap Screw-3": "two",
        "Socket Head Cap Screw-4": "two",
        "Piston Assembly-2": "two",
        "piston pin-4": "four",
        "connecting rod-4": "four",
        "connecting rod cap-4": "four",
        "Socket Head Cap Screw-7": "four",
        "Socket Head Cap Screw-8": "four",
        "Piston Assembly-4": "four",
        "piston pin-5": "five",
        "connecting rod-5": "five",
        "connecting rod cap-5": "five",
        "Socket Head Cap Screw-9": "five",
        "Socket Head Cap Screw-10": "five",
        "Piston Assembly-5": "five",
    }
    instances = []
    for component in assembly.get("components") or []:
        source_name = str(component.get("name") or "")
        kind = "physical" if component.get("type") == "Part" else "organizational"
        key = str(component.get("partDataKey") or component.get("referencedFileName") or "").lower()
        part_number = key_to_part.get(key) if kind == "physical" else None
        parent_name = component.get("parentName")
        occurrence = cylinder_by_top_level.get(source_name)
        if occurrence is None and parent_name in cylinder_by_top_level:
            occurrence = cylinder_by_top_level[parent_name]
        if occurrence is None:
            occurrence = "assembly"
        instances.append(
            {
                "instance_id": source_to_id[source_name],
                "source_component_name": source_name,
                "part_number": part_number,
                "parent_instance_id": source_to_id.get(str(parent_name)) if parent_name else None,
                "kind": kind,
                "occurrence_key": occurrence,
            }
        )

    source_evidence = [
        {
            "source_id": "assembly:100001",
            "type": "assembly_extract",
            "path": "400S_Sorted_Library/assemblies/100001_assembly.json",
            "sha256": _sha256(ASSEMBLY_PATH),
            "authority": "cad_constraint",
        }
    ]
    for part_number, path in PROFILE_PATHS.items():
        source_evidence.append(
            {
                "source_id": f"profile:{part_number}",
                "type": "part_profile",
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": _sha256(path),
                "authority": "curated_profile",
            }
        )
    source_evidence.append(
        {
            "source_id": "motion:engine4cyl-crank-cycle",
            "type": "motion_summary",
            "path": MOTION_PATH.relative_to(ROOT).as_posix(),
            "sha256": _sha256(MOTION_PATH),
            "authority": "validated_motion",
        }
    )

    cid = lambda name: source_to_id[name]
    interfaces: list[dict[str, Any]] = []
    interfaces.append(
        _interface(
            "interface:block-crank-main-support",
            "block-crank-main-support",
            "Crankshaft main-journal support in the lower block",
            "revolute_support",
            [
                _participant(cid("Lower block-1"), "100002", ["lower-block.main-bearing-bores", "lower-block.end-bearing-faces"], "support"),
                _participant(cid("crankshaft-1"), "100003", ["crankshaft.main-journals"], "journal"),
            ],
            ["support the crankshaft on a stable axis", "allow crankshaft rotation", "locate the crankshaft axially"],
            "revolute",
            ["rotation about the shared journal axis"],
            ["radial translation", "axis misalignment", "uncontrolled axial translation"],
            ["radial bearing load", "structural reaction", "axial location"],
            ["coaxial alignment", "controlled running clearance", "free rotation", "stable axial location"],
            [
                _evidence("assembly:100001", "mates:Concentric42,Coincident31", "cad_mate", "The lower block and crankshaft share a constrained journal axis and locating face."),
                _evidence("profile:100002", "features:Main bearing bores, end walls", "part_profile", "The lower block end bores are the crankshaft supports."),
                _evidence("profile:100003", "features:Main journals", "part_profile", "The crankshaft main journals are the supported rotating surfaces."),
            ],
            0.99,
            "verified",
        )
    )
    interfaces.append(
        _interface(
            "interface:block-crank-clearance-envelope",
            "block-crank-clearance-envelope",
            "Crank counterweight clearance inside the lower crankcase",
            "dynamic_clearance_envelope",
            [
                _participant(cid("Lower block-1"), "100002", ["lower-block.crankcase-clearance-envelope"], "clearance_boundary"),
                _participant(cid("crankshaft-1"), "100003", ["crankshaft.counterweight-envelope"], "clearance_member"),
            ],
            ["contain the rotating crank train", "prevent contact between counterweights and the crankcase"],
            "non_contact_dynamic",
            ["counterweight rotation within the crankcase envelope"],
            ["contact between the rotating envelope and crankcase wall"],
            ["clearance preservation"],
            ["positive dynamic clearance", "stable crankshaft axis", "crankcase shape integrity"],
            [
                _evidence("profile:100002", "features:Semicylindrical crankcase wall", "part_profile", "The lower block provides the crankcase clearance envelope."),
                _evidence("profile:100003", "features:Counterweight webs", "part_profile", "The counterweights define the principal rotating envelope."),
                _evidence("motion:engine4cyl-crank-cycle", "motion:reciprocating-crank-train", "motion_package", "The validated package rotates the crankshaft through the stationary lower block."),
            ],
            0.95,
            "verified",
        )
    )
    interfaces.append(
        _interface(
            "interface:block-upper-structure",
            "block-upper-structure",
            "Lower crankcase deck to omitted upper cylinder structure",
            "structural_mount",
            [
                _participant(cid("Lower block-1"), "100002", ["lower-block.open-deck-interface"], "support"),
                _participant("external:upper-cylinder-block", None, ["upper-block.lower-mating-face"], "guided_member"),
            ],
            ["support and align the omitted upper cylinder structure", "provide a continuous passage for the piston and rod system"],
            "fixed",
            ["no relative motion in normal service"],
            ["relative translation", "relative rotation", "datum misalignment"],
            ["structural load", "datum transfer"],
            ["stable mounting", "datum continuity", "alignment with the crank axis"],
            [
                _evidence("profile:100002", "features:Open deck / upper wall rim", "part_profile", "The open deck is the expected transfer surface to an upper engine structure."),
                _evidence("profile:100006", "assembly_role", "engineering_inference", "The piston reciprocates above the open lower crankcase and requires an omitted guiding cylinder structure in a complete engine."),
            ],
            0.72,
            "needs_confirmation",
        )
    )
    interfaces.append(
        _interface(
            "interface:crank-output",
            "crank-output",
            "Crankshaft output flange to external driven system",
            "torque_output",
            [
                _participant(cid("crankshaft-1"), "100003", ["crankshaft.output-flange"], "rotating_member"),
                _participant("external:driven-system", None, ["driven-system.input-coupling"], "driven_interface"),
            ],
            ["deliver shaft rotation and torque to a downstream system"],
            "external_unknown",
            ["co-rotation when a coupling is installed"],
            ["uncoupled relative translation under an installed joint"],
            ["torque", "rotation"],
            ["concentric coupling", "secure torque transfer", "axial retention"],
            [
                _evidence("profile:100003", "features:Output flange with bolt circle", "part_profile", "The crankshaft profile identifies the flange as the output end."),
            ],
            0.88,
            "reviewed_inference",
        )
    )

    cylinders = [
        {
            "key": "one",
            "rod": "connecting rod-1",
            "cap": "connecting rod cap-1",
            "screws": ["Socket Head Cap Screw-1", "Socket Head Cap Screw-2"],
            "pin": "piston pin-1",
            "piston": "Piston Assembly-1/piston-1",
            "rings": ["Piston Assembly-1/piston ring-1", "Piston Assembly-1/piston ring-2", "Piston Assembly-1/piston ring-4"],
            "mates": {"big": "Concentric7,Concentric81", "cap": "Concentric9,Concentric10,Coincident14,Concentric11,Coincident15", "rod_pin": "Concentric12", "piston_pin": "Concentric13,Tangent1"},
        },
        {
            "key": "two",
            "rod": "connecting rod-2",
            "cap": "connecting rod cap-2",
            "screws": ["Socket Head Cap Screw-3", "Socket Head Cap Screw-4"],
            "pin": "piston pin-2",
            "piston": "Piston Assembly-2/piston-1",
            "rings": ["Piston Assembly-2/piston ring-1", "Piston Assembly-2/piston ring-2", "Piston Assembly-2/piston ring-4"],
            "mates": {"big": "Concentric19,Concentric20", "cap": "Concentric14,Concentric15,Coincident17,Concentric16,Coincident18", "rod_pin": "Concentric17", "piston_pin": "Concentric18,Tangent2"},
        },
        {
            "key": "four",
            "rod": "connecting rod-4",
            "cap": "connecting rod cap-4",
            "screws": ["Socket Head Cap Screw-7", "Socket Head Cap Screw-8"],
            "pin": "piston pin-4",
            "piston": "Piston Assembly-4/piston-1",
            "rings": ["Piston Assembly-4/piston ring-1", "Piston Assembly-4/piston ring-2", "Piston Assembly-4/piston ring-4"],
            "mates": {"big": "Concentric33,Concentric34", "cap": "Concentric28,Concentric29,Coincident23,Concentric30,Coincident24", "rod_pin": "Concentric31", "piston_pin": "Concentric32,Tangent8"},
        },
        {
            "key": "five",
            "rod": "connecting rod-5",
            "cap": "connecting rod cap-5",
            "screws": ["Socket Head Cap Screw-9", "Socket Head Cap Screw-10"],
            "pin": "piston pin-5",
            "piston": "Piston Assembly-5/piston-1",
            "rings": ["Piston Assembly-5/piston ring-1", "Piston Assembly-5/piston ring-2", "Piston Assembly-5/piston ring-4"],
            "mates": {"big": "Concentric40,Concentric41", "cap": "Concentric35,Concentric36,Coincident26,Concentric37,Coincident27", "rod_pin": "Concentric38", "piston_pin": "Concentric39,Tangent10"},
        },
    ]

    for cylinder in cylinders:
        key = cylinder["key"]
        rod = cid(cylinder["rod"])
        cap = cid(cylinder["cap"])
        pin = cid(cylinder["pin"])
        piston = cid(cylinder["piston"])
        screws = [cid(name) for name in cylinder["screws"]]
        rings = [cid(name) for name in cylinder["rings"]]
        interfaces.append(
            _interface(
                f"interface:{key}:crank-big-end",
                "crank-rod-big-end",
                "Connecting-rod split big end on a crank-pin journal",
                "split_journal_bearing",
                [
                    _participant(cid("crankshaft-1"), "100003", ["crankshaft.crank-pin-journals"], "journal"),
                    _participant(rod, "100004", ["connecting-rod.big-end-half-bore"], "bearing_half"),
                    _participant(cap, "100005", ["rod-cap.big-end-half-bore"], "bearing_half"),
                ],
                ["carry one connecting rod on an offset crank journal", "convert reciprocating rod force into crankshaft torque", "allow relative journal rotation"],
                "revolute",
                ["rotation about the crank-pin axis"],
                ["radial separation", "axis misalignment", "uncontrolled axial displacement"],
                ["reciprocating force", "radial bearing load", "torque"],
                ["complete split bore", "coaxial bearing halves", "controlled running clearance", "free journal rotation"],
                [
                    _evidence("assembly:100001", f"mates:{cylinder['mates']['big']}", "cad_mate", "The rod and cap bearing surfaces share the crank-pin journal axis."),
                    _evidence("profile:100004", "features:Big end half bore", "part_profile", "The rod supplies the upper bearing half and load path."),
                    _evidence("profile:100005", "features:Half bore", "part_profile", "The cap supplies the removable lower bearing half."),
                    _evidence("motion:engine4cyl-crank-cycle", "joint-closure:crank-pin", "motion_package", "The validated motion preserves the rod-to-crank journal closure through the cycle."),
                ],
                0.99,
                "verified",
            )
        )
        interfaces.append(
            _interface(
                f"interface:{key}:rod-cap-clamp",
                "rod-cap-clamp",
                "Bolted connecting-rod cap joint",
                "bolted_clamp",
                [
                    _participant(rod, "100004", ["connecting-rod.cap-split-faces", "connecting-rod.fastener-bores"], "clamp_body"),
                    _participant(cap, "100005", ["rod-cap.split-face", "rod-cap.fastener-bores"], "clamp_body"),
                    _participant(screws[0], "100008", ["cap-screw.thread-interface", "cap-screw.head-bearing-face", "cap-screw.shank"], "fastener"),
                    _participant(screws[1], "100008", ["cap-screw.thread-interface", "cap-screw.head-bearing-face", "cap-screw.shank"], "fastener"),
                ],
                ["retain the cap on the rod", "maintain the assembled big-end bore", "carry clamp load across the split joint"],
                "fixed",
                ["no relative motion after fastening"],
                ["split-face opening", "cap translation", "fastener loosening"],
                ["clamp preload", "bearing reaction", "joint retention"],
                ["full split-face seating", "fastener engagement", "stable clamp preload", "assembled bore integrity"],
                [
                    _evidence("assembly:100001", f"mates:{cylinder['mates']['cap']}", "cad_mate", "The cap and both fasteners are aligned and seated to the rod."),
                    _evidence("profile:100008", "assembly_role", "part_profile", "The two cap screws clamp each rod-cap pair."),
                ],
                0.98,
                "verified",
            )
        )
        interfaces.append(
            _interface(
                f"interface:{key}:piston-pin-bearing",
                "piston-pin-bearing",
                "Piston boss bores supporting the floating pin",
                "floating_pin_bearing",
                [
                    _participant(piston, "100006", ["piston.pin-bores"], "support"),
                    _participant(pin, "100007", ["piston-pin.outer-bearing-surface", "piston-pin.end-faces"], "journal"),
                ],
                ["support the piston pin in the piston bosses", "transfer piston load into the pin", "permit the intended pin float or rotation"],
                "limited_axial_float",
                ["pin rotation relative to the piston", "limited axial pin float"],
                ["radial separation", "axis misalignment", "uncontrolled axial escape"],
                ["piston load", "radial bearing load", "pin support"],
                ["coaxial boss bores", "controlled bearing clearance", "free intended motion", "positive axial retention strategy"],
                [
                    _evidence("assembly:100001", f"mates:{cylinder['mates']['piston_pin']}", "cad_mate", "The piston boss bore and pin share an axis and end relationship."),
                    _evidence("profile:100006", "features:Pin bores through bosses", "part_profile", "The piston bores are the pin load-transfer supports."),
                    _evidence("profile:100007", "features:Outer diameter", "part_profile", "The pin outer surface is the supported journal."),
                    _evidence("motion:engine4cyl-crank-cycle", "joint-closure:piston-pin", "motion_package", "The validated motion preserves pin-to-piston joint closure."),
                ],
                0.99,
                "verified",
            )
        )
        interfaces.append(
            _interface(
                f"interface:{key}:rod-pin-bearing",
                "rod-pin-bearing",
                "Connecting-rod small end oscillating on the piston pin",
                "oscillating_pin_bearing",
                [
                    _participant(pin, "100007", ["piston-pin.outer-bearing-surface"], "journal"),
                    _participant(rod, "100004", ["connecting-rod.small-end-bore"], "oscillating_member"),
                ],
                ["transfer load between the pin and rod", "allow the rod to oscillate as the piston reciprocates"],
                "oscillating_revolute",
                ["rod oscillation about the pin axis"],
                ["radial separation", "axis misalignment", "uncontrolled side translation"],
                ["reciprocating force", "radial bearing load", "oscillating motion"],
                ["coaxial pin and bore", "controlled running clearance", "free rod oscillation", "adequate bearing support"],
                [
                    _evidence("assembly:100001", f"mates:{cylinder['mates']['rod_pin']}", "cad_mate", "The rod small-end bore and piston pin share an axis."),
                    _evidence("profile:100004", "features:Small end pin bore", "part_profile", "The small end is the oscillating pin bearing."),
                    _evidence("motion:engine4cyl-crank-cycle", "joint-closure:rod-pin", "motion_package", "The validated motion preserves rod-to-pin joint closure."),
                ],
                0.99,
                "verified",
            )
        )
        interfaces.append(
            _interface(
                f"interface:{key}:rod-side-guidance",
                "rod-side-guidance",
                "Connecting-rod small-end side guidance between piston bosses",
                "axial_guidance_clearance",
                [
                    _participant(piston, "100006", ["piston.boss-counterbores"], "guide"),
                    _participant(rod, "100004", ["connecting-rod.small-end-side-faces"], "guided_member"),
                ],
                ["keep the rod small end centered between the piston bosses", "provide side clearance for rod oscillation"],
                "limited_axial_float",
                ["rod oscillation with limited side float"],
                ["large axial displacement", "side-face interference"],
                ["side reaction", "axial guidance"],
                ["controlled side clearance", "parallel guidance faces", "free rod oscillation"],
                [
                    _evidence("profile:100006", "features:Boss face counterbores", "part_profile", "The piston boss faces form the rod side-guidance region."),
                    _evidence("profile:100004", "features:Small end pin bore", "engineering_inference", "The rod small-end boss is located between the opposed piston bosses."),
                ],
                0.78,
                "reviewed_inference",
            )
        )
        interfaces.append(
            _interface(
                f"interface:{key}:piston-cylinder-guide",
                "piston-cylinder-guide",
                "Piston running surface guided by an omitted cylinder bore",
                "prismatic_guidance_clearance",
                [
                    _participant(piston, "100006", ["piston.skirt-running-surface"], "guided_member"),
                    _participant("external:upper-cylinder-block", None, ["upper-block.cylinder-bores"], "guide"),
                ],
                ["guide the piston along its reciprocating axis", "control piston side motion", "keep the piston aligned with the crank-slider mechanism"],
                "prismatic",
                ["axial piston translation"],
                ["radial displacement", "piston tilt beyond running allowance", "rotation about a transverse axis"],
                ["piston side load", "radial guidance", "reciprocating motion"],
                ["controlled radial clearance", "free axial translation", "compatible running surfaces", "alignment with the crank-slider axis"],
                [
                    _evidence("profile:100006", "assembly_role", "part_profile", "The piston is the reciprocating guided member and its outside surface is the running interface."),
                    _evidence("profile:100002", "features:Open deck / upper wall rim", "engineering_inference", "The extracted lower crankcase is open and does not include the required upper cylinder-bore guide."),
                    _evidence("motion:engine4cyl-crank-cycle", "motion:reciprocating-components", "motion_package", "The validated package translates the pistons on fixed cylinder axes."),
                ],
                0.86,
                "reviewed_inference",
            )
        )
        interfaces.append(
            _interface(
                f"interface:{key}:ring-retention",
                "piston-ring-retention",
                "Piston ring pack retained in the piston grooves",
                "ring_retention",
                [
                    _participant(piston, "100006", ["piston.ring-grooves"], "retainer"),
                    *[
                        _participant(ring, "100009", ["piston-ring.inner-groove-seat", "piston-ring.side-faces", "piston-ring.end-gap"], "retained_member")
                        for ring in rings
                    ],
                ],
                ["retain the ring pack on the piston", "locate each ring axially", "permit the ring compliance needed for installation and service"],
                "sliding_contact",
                ["limited ring movement within each groove", "ring expansion at the split"],
                ["ring escape", "excessive axial motion", "groove binding"],
                ["ring retention", "axial guidance"],
                ["groove seating", "controlled side clearance", "end-gap accommodation", "free ring compliance"],
                [
                    _evidence("profile:100006", "features:Ring grooves", "part_profile", "The piston grooves retain the ring pack."),
                    _evidence("profile:100009", "assembly_role", "part_profile", "Each split ring seats in a piston groove and remains compliant."),
                    _evidence("assembly:100001", f"hierarchy:Piston Assembly-{key}", "assembly_hierarchy", "Three ring instances are carried by each piston subassembly."),
                ],
                0.94,
                "verified",
            )
        )
        interfaces.append(
            _interface(
                f"interface:{key}:ring-cylinder-seal",
                "ring-cylinder-seal",
                "Piston ring pack sliding against an omitted cylinder bore",
                "sliding_seal",
                [
                    *[
                        _participant(ring, "100009", ["piston-ring.outer-bore-contact", "piston-ring.end-gap"], "sealing_member")
                        for ring in rings
                    ],
                    _participant("external:upper-cylinder-block", None, ["upper-block.cylinder-bores"], "sealing_surface"),
                ],
                ["maintain sliding contact with the cylinder bore", "support sealing while the piston reciprocates"],
                "sliding_contact",
                ["axial sliding along the cylinder bore", "ring compliance against the bore"],
                ["loss of bore contact", "ring seizure", "uncontrolled ring escape"],
                ["sealing contact", "friction reaction", "heat transfer"],
                ["continuous bore contact", "compatible sliding surfaces", "controlled ring loading", "end-gap accommodation"],
                [
                    _evidence("profile:100009", "assembly_role", "part_profile", "The ring outer surface is the expected bore-sealing contact."),
                    _evidence("profile:100006", "features:Ring grooves", "part_profile", "The piston carries the rings through the reciprocating stroke."),
                    _evidence("profile:100002", "features:Open deck / upper wall rim", "engineering_inference", "The required cylinder sealing surface belongs to an upper structure omitted from this extract."),
                ],
                0.82,
                "reviewed_inference",
            )
        )
        interfaces.append(
            _interface(
                f"interface:{key}:skirt-crank-clearance",
                "piston-skirt-crank-clearance",
                "Piston skirt relief clearance to the rotating crank train",
                "dynamic_clearance_envelope",
                [
                    _participant(piston, "100006", ["piston.skirt-reliefs"], "clearance_member"),
                    _participant(cid("crankshaft-1"), "100003", ["crankshaft.counterweight-envelope"], "clearance_boundary"),
                ],
                ["prevent contact between the piston skirt and rotating crank webs near the lower stroke region"],
                "non_contact_dynamic",
                ["piston translation past the rotating crank envelope"],
                ["skirt-to-crank contact"],
                ["clearance preservation"],
                ["positive dynamic clearance", "correct piston guidance", "correct crankshaft axis"],
                [
                    _evidence("profile:100006", "features:Skirt with arched reliefs", "part_profile", "The skirt reliefs provide clearance to the crank webs."),
                    _evidence("profile:100003", "features:Counterweight webs", "part_profile", "The crank webs define the nearby rotating envelope."),
                    _evidence("motion:engine4cyl-crank-cycle", "motion:full-cycle", "motion_package", "The validated cycle exercises the relative skirt and crank motion."),
                ],
                0.95,
                "verified",
            )
        )

    physical_count = sum(1 for item in instances if item["kind"] == "physical")
    organizational_count = sum(1 for item in instances if item["kind"] == "organizational")
    covered = {
        participant["participant_id"]
        for interface in interfaces
        for participant in interface["participants"]
        if participant["participant_id"].startswith("instance:")
    }
    physical_ids = {item["instance_id"] for item in instances if item["kind"] == "physical"}
    graph = {
        "schema_version": "1.0",
        "graph_id": "functional-graph:100001",
        "version": "1.0.0",
        "assembly": {
            "part_number": "100001",
            "name": "Four Cylinder Engine Assembly",
            "configuration": "Engine_Motion_Study",
        },
        "source_evidence": source_evidence,
        "component_types": _component_types(),
        "component_instances": instances,
        "external_entities": _external_entities(),
        "interfaces": interfaces,
        "coverage": {
            "physical_instance_count": physical_count,
            "covered_instance_count": len(physical_ids & covered),
            "uncovered_instance_ids": sorted(physical_ids - covered),
            "organizational_instance_count": organizational_count,
            "external_entity_count": len(_external_entities()),
        },
    }
    return graph


def main() -> None:
    graph = build_graph()
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(
        json.dumps(graph, indent=2, ensure_ascii=True) + "\n",
        encoding="ascii",
    )
    print(
        json.dumps(
            {
                "path": CATALOG_PATH.relative_to(ROOT).as_posix(),
                "instances": len(graph["component_instances"]),
                "physical": graph["coverage"]["physical_instance_count"],
                "interfaces": len(graph["interfaces"]),
                "covered": graph["coverage"]["covered_instance_count"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
