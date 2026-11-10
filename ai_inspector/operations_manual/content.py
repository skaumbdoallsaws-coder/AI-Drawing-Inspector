"""Evidence-bound content for the MMLE-50D operations manual.

The prose in this module is original InspectorPro manual content. It uses the
registered OEM and CAD evidence, while preserving review labels for claims that
are legacy, configuration-sensitive, or awaiting engineering approval.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, Mapping, Sequence


def _block(
    block_id: str,
    block_type: str,
    order: int,
    *,
    claims: Iterable[str] = (),
    **payload: Any,
) -> Dict[str, Any]:
    claims = list(claims)
    return {
        **({"evidenceBindingVersion": 1} if list(claims) or any("claimIds" in row for row in payload.get("rows", payload.get("items", []))) else {}),
        "blockId": block_id,
        "blockType": block_type,
        "readingOrder": order,
        "evidenceClaimIds": list(claims),
        "payload": payload,
    }


def _heading(block_id: str, order: int, text: str, *, level: int = 1) -> Dict[str, Any]:
    return _block(block_id, "heading", order, level=level, text=text)


def _paragraph(
    block_id: str,
    order: int,
    text: str,
    *,
    claims: Iterable[str] = (),
) -> Dict[str, Any]:
    return _block(block_id, "paragraph", order, claims=claims, text=text)


def _note(
    block_id: str,
    order: int,
    signal: str,
    text: str,
    *,
    claims: Iterable[str] = (),
) -> Dict[str, Any]:
    tone = signal.strip().lower()
    return _block(
        block_id,
        "note",
        order,
        claims=claims,
        tone=tone,
        signalWord=signal.strip().upper(),
        text=text,
    )


def _list(
    block_id: str,
    order: int,
    items: Sequence[str | Mapping[str, Any]],
    *,
    style: str = "numbered",
    columns: int = 1,
    claims: Iterable[str] = (),
) -> Dict[str, Any]:
    normalized: list[Dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, Mapping):
            row = copy.deepcopy(dict(item))
        else:
            row = {"text": str(item)}
        row.setdefault("itemNumber", index)
        row.setdefault("text", "")
        normalized.append(row)
    return _block(
        block_id,
        "list",
        order,
        claims=claims,
        style=style,
        columns=max(1, min(2, int(columns))),
        items=normalized,
    )


def _figure_legend(
    block_id: str,
    order: int,
    figure_id: str,
    items: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    return _block(
        block_id,
        "figure_legend",
        order,
        figureId=figure_id,
        style="keyed",
        columns=2,
        items=[copy.deepcopy(dict(item)) for item in items],
    )


def _table(
    block_id: str,
    order: int,
    columns: Sequence[str],
    rows: Sequence[Sequence[str] | Mapping[str, Any]],
    *,
    claims: Iterable[str] = (),
    keep_together: bool = False,
) -> Dict[str, Any]:
    normalized = []
    for row in rows:
        if isinstance(row, Mapping):
            normalized.append(copy.deepcopy(dict(row)))
        else:
            normalized.append({"cells": [str(value) for value in row]})
    return _block(
        block_id,
        "table",
        order,
        claims=claims,
        columns=list(columns),
        columnKeys=list({
            "records-log": ("date", "asset", "work", "finding", "disposition", "person"),
            "troubleshooting-table": ("condition", "checks", "disposition"),
            "sources-open": ("area", "treatment", "requirement"),
        }.get(block_id, ("label", "value"))),
        rows=normalized,
        keepTogether=bool(keep_together),
    )


def _figure(
    block_id: str,
    order: int,
    figure_id: str,
    caption: str,
    *,
    claims: Iterable[str] = ("CLM-CAD-001",),
    height: float = 320,
) -> Dict[str, Any]:
    return _block(
        block_id,
        "cad_figure",
        order,
        claims=claims,
        figureId=figure_id,
        caption=caption,
        height=height,
    )


def _section(section_id: str, title: str, blocks: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return {
        "sectionId": section_id,
        "title": title,
        "blocks": [copy.deepcopy(dict(block)) for block in blocks],
    }


def _source_rows(
    snapshot: Mapping[str, Any],
    claim_ids: Iterable[str],
) -> list[Dict[str, Any]]:
    source_claims: Dict[str, set[str]] = {}
    claims = snapshot.get("claims") if isinstance(snapshot.get("claims"), Mapping) else {}
    for claim_id in claim_ids:
        claim = claims.get(str(claim_id)) if isinstance(claims, Mapping) else None
        if not isinstance(claim, Mapping):
            continue
        for source_id in claim.get("sourceIds") or []:
            source_claims.setdefault(str(source_id), set()).add(str(claim_id))

    authority_order = {
        "OEM_CURRENT": 0,
        "OEM_LEGACY": 1,
        "INDUSTRY_GUIDANCE": 2,
        "CAD_AUTHORED": 3,
        "USER_AUTHORED": 4,
    }
    rows: list[Dict[str, Any]] = []
    sources = snapshot.get("sources") if isinstance(snapshot.get("sources"), Mapping) else {}
    source_ids = sorted(
        source_claims,
        key=lambda source_id: (
            authority_order.get(
                str((sources.get(source_id) or {}).get("authority") or ""), 99
            ),
            str((sources.get(source_id) or {}).get("title") or source_id).casefold(),
            source_id,
        ),
    )
    for source_id in source_ids:
        source = sources.get(source_id) if isinstance(sources, Mapping) else None
        if not isinstance(source, Mapping):
            continue
        authority = str(source.get("authority") or "UNKNOWN")
        role = {
            "OEM_CURRENT": "Current manufacturer source",
            "OEM_LEGACY": "Legacy manufacturer manual - applicability review required",
            "INDUSTRY_GUIDANCE": "Industry guidance",
            "CAD_AUTHORED": "CAD model evidence",
            "USER_AUTHORED": "Reviewed internal source",
        }.get(authority, "Registered evidence")
        blocking_conflicts = [
            row
            for row in snapshot.get("conflicts") or []
            if isinstance(row, Mapping)
            and bool(row.get("releaseBlocking"))
            and source_id in {str(value) for value in row.get("sourceIds") or []}
        ]
        conflict_topics = [
            str(row.get("topic") or "evidence conflict").replace("_", " ")
            for row in blocking_conflicts
        ]
        use = f"{role}; cited by {len(source_claims[source_id])} claims"
        if conflict_topics:
            shown_topics = conflict_topics[:2]
            topic_text = ", ".join(shown_topics)
            if len(conflict_topics) > len(shown_topics):
                topic_text += f", and {len(conflict_topics) - len(shown_topics)} more"
            use += (
                f"; involved in {len(conflict_topics)} blocking conflict"
                f"{'s' if len(conflict_topics) != 1 else ''}: {topic_text}"
            )
        rows.append(
            {
                "cells": [
                    str(source.get("title") or source_id),
                    use,
                ],
                "sourceIds": [source_id],
            }
        )
    return rows


def _cited_item(snapshot, claim_id, item):
    claim = (snapshot.get("claims") or {}).get(claim_id) or {}
    return {**item, "claimIds": [claim_id], "sourceIds": list(claim.get("sourceIds") or []),
            "evidenceBindingVersion": 1}


def _cited_row(snapshot, claim_id, cells):
    # The authored plan names the registered claim beside the row; no text match.
    claim = (snapshot.get("claims") or {}).get(claim_id) or {}
    return {"sourceKey": claim_id, "cells": cells, "claimIds": [claim_id], "sourceIds": list(claim.get("sourceIds") or []),
            "evidenceBindingVersion": 1}


def legacy_plan_projection(value):
    """Keep saved scenes bound to the historical plan while adding evidence keys."""
    if isinstance(value, list):
        return [legacy_plan_projection(row) for row in value]
    if isinstance(value, dict):
        removed = {"evidenceBindingVersion", "sourceKey", "columnKeys"}
        if value.get("evidenceBindingVersion") == 1 and ("cells" in value or "itemNumber" in value):
            removed.update({"claimIds", "sourceIds"})
        return {key: legacy_plan_projection(item) for key, item in value.items() if key not in removed}
    return value


def prototype_sections(
    snapshot: Mapping[str, Any],
    *,
    figure_legends: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    overview_systems: Sequence[Mapping[str, Any]] = (),
) -> list[Dict[str, Any]]:
    """Return the substantial, review-marked MMLE content plan."""

    legends = figure_legends or {}
    safety_claims = [f"CLM-SAFETY-00{index}" for index in range(1, 6)]
    specification_claims = [f"CLM-SPEC-00{index}" for index in range(1, 7)]
    sections = [
        _section("about", "1 About This Manual", [
            _heading("about-title", 1, "1 About This Manual"),
            _paragraph(
                "about-purpose", 2,
                "This manual provides product information, technical illustrations, operating guidance, inspection requirements, and maintenance references for the MMLE-50D Electric Mobile Lift. Read it alongside the machine identification, labels, and current manufacturer information for the applicable configuration.",
                claims=["CLM-IDENTITY-001", "CLM-CAD-001"],
            ),
            _paragraph(
                "about-read", 3,
                "Read the entire manual before operating, inspecting, or maintaining the machine. Keep it available to operators and maintenance personnel, and confirm that the model, configuration, and revision apply to the machine.",
            ),
            _heading("about-audience-title", 4, "1.1 Intended Readers", level=2),
            _list("about-audience", 5, [
                {"sourceKey": "decl-dc512206dcfc40f4", "label": "Operators", "text": "Use this manual to understand control locations, inspection sequences, normal movement, and the conditions that require the machine to be removed from service."},
                {"sourceKey": "decl-9d2d1bed747145b9", "label": "Supervisors and owners", "text": "Review application suitability, training, inspection, recordkeeping, and site-specific controls before authorizing use."},
                {"sourceKey": "decl-6b83b7a0c53a4685", "label": "Qualified maintenance personnel", "text": "Use the system figures for identification and planning only. Do not infer pressure, torque, fluid, or adjustment values from an illustration."},
            ], style="definitions"),
            _note(
                "about-document-status", 6, "notice",
                "Confirm that the model, configuration, labels, and document revision apply to the machine before using this manual.",
            ),
        ]),
        _section("safety", "2 Safety Information", [
            _heading("safety-title", 1, "2 Safety Information"),
            _paragraph(
                "safety-intro", 2,
                "Safety messages identify a hazard, describe the possible consequence, and state the action required to reduce exposure. Read and obey every safety message before operating, inspecting, charging, maintaining, or servicing the lift.",
            ),
            _note("safety-definition-danger", 3, "danger", "Indicates an imminently hazardous situation which, if not avoided, will result in death or serious injury."),
            _note("safety-definition-warning", 4, "warning", "Indicates a potentially hazardous situation which, if not avoided, could result in death or serious injury."),
            _note("safety-definition-caution", 5, "caution", "Indicates a potentially hazardous situation which, if not avoided, may result in minor or moderate injury."),
            _note("safety-definition-notice", 6, "notice", "Identifies information required to protect the equipment, preserve records, or maintain the approved configuration."),
            _heading("safety-general-title", 7, "2.1 General Safety", level=2),
            _note("safety-no-rider", 8, "danger", "Never sit, stand, or ride on the platform. The MMLE-50D is a material lift, not a personnel lift.", claims=["CLM-SAFETY-001"]),
            _note("safety-under", 9, "danger", "Never place any part of the body beneath an unsupported raised platform or inside the scissor mechanism. Lower the platform fully unless an approved mechanical support and energy-control procedure is in force.", claims=["CLM-SAFETY-002", "CLM-SAFETY-FEATURE-004"]),
            _note("safety-load", 10, "warning", "Do not exceed the 1,100 lb rated capacity. Do not lift an unstable, unbalanced, loosely stacked, concentrated, or overhanging load unless that condition has been approved.", claims=["CLM-SAFETY-004", "CLM-SPEC-001"]),
            _note("safety-floor", 11, "warning", "Do not move or operate the lift on a slope, soft surface, damaged floor, abrupt transition, or uneven surface outside approved conditions.", claims=["CLM-SAFETY-003"]),
            _note("safety-trained", 12, "warning", "Only trained and authorized personnel may operate the lift. The operator must remain in control of the machine while it is moving.", claims=["CLM-SAFETY-005"]),
            _heading("safety-residual-title", 13, "2.2 Principal Hazard Zones", level=2),
            _list("safety-hazard-zones", 14, [
                {"sourceKey": "decl-84fb19f6de744711", "label": "Under the platform and inside the scissor stack", "text": "Crushing, shearing, and stored-energy hazards exist. Keep clear, lower the platform fully, and use only an approved support and isolation procedure for maintenance."},
                {"sourceKey": "decl-5802e9ec90d74766", "label": "Caster and wheel path", "text": "Feet can be trapped and bystanders can be struck. Keep the route clear and move only at a controlled walking pace."},
                {"sourceKey": "decl-c30a49da3083437b", "label": "Platform and load", "text": "Material can fall or shift. Center and stabilize the load and stop immediately if its condition changes."},
                {"sourceKey": "decl-c269a8749d634652", "label": "Hydraulic system", "text": "Stored pressure, hot fluid, and unexpected descent can cause injury. Operators perform external inspection only; qualified personnel perform hydraulic work."},
                {"sourceKey": "decl-1c7735738f8e446a", "label": "Battery and charger", "text": "Electrical energy and configuration-specific battery hazards exist. Inspect external condition only and follow approved instructions for the actual charger and battery."},
            ], style="definitions", claims=safety_claims),
            _note("safety-feature-review", 15, "notice", "The manufacturer describes maintenance safety bars, a maintenance isolator, and an emergency relief valve. Confirm the exact devices and approved procedures for the machine configuration. Do not substitute nearby components or invent an engagement sequence.", claims=["CLM-SAFETY-FEATURE-001", "CLM-SAFETY-FEATURE-002", "CLM-SAFETY-FEATURE-004"]),
        ]),
        _section("product-overview", "3 Product Overview", [
            _heading("overview-title", 1, "3 Product Overview"),
            _paragraph(
                "overview-purpose", 2,
                "The MMLE-50D is an electric mobile industrial lift intended to raise, lower, position, and transport material within the limits approved for the specific application. Published examples include order picking, die handling, assembly, and general lifting. These examples do not authorize every load, floor, environment, or duty cycle.",
                claims=["CLM-IDENTITY-001", "CLM-USE-001"],
            ),
            _figure("overview-figure", 3, "OM-FIG-001", "Figure 3-1. Exploded system overview of the MMLE-50D.", height=390),
            _figure_legend("overview-systems", 4, "OM-FIG-001", overview_systems),
        ]),
        _section("specifications", "4 Specifications and Application Limits", [
            _heading("spec-title", 1, "4 Specifications and Application Limits"),
            _paragraph("spec-intro", 2, "Values are shown as published by the manufacturer. Shipping weight is not represented as operating weight. Specifications are presented in the manufacturer's published US customary units."),
            _table("spec-table", 3, ["Characteristic", "Published value"], [
                _cited_row(snapshot, "CLM-SPEC-001", ["Rated capacity", "1,100 lb"]),
                _cited_row(snapshot, "CLM-SPEC-002", ["Vertical travel", "44 in"]),
                _cited_row(snapshot, "CLM-SPEC-003", ["Lowered height", "19.5 in"]),
                _cited_row(snapshot, "CLM-SPEC-004", ["Raised height", "63.5 in"]),
                _cited_row(snapshot, "CLM-SPEC-005", ["Platform", "20.5 x 39.8 in"]),
                _cited_row(snapshot, "CLM-SPEC-006", ["Shipping weight", "436 lb"]),
                _cited_row(snapshot, "CLM-ELECTRICAL-001", ["Battery architecture", "Onboard 12 V battery"]),
                _cited_row(snapshot, "CLM-ELECTRICAL-002", ["Charger architecture", "Internal automatic 110 V charger"]),
                _cited_row(snapshot, "CLM-RUNNING-001", ["Running gear", "Two front rigid and two rear swivel polyurethane casters"]),
            ], claims=specification_claims + ["CLM-ELECTRICAL-001", "CLM-ELECTRICAL-002", "CLM-RUNNING-001"]),
            _heading("spec-application-title", 4, "4.1 Application Approval Checklist", level=2),
            _list("spec-application", 5, [
                {"sourceKey": "decl-630d73da24774a0e", "label": "Load", "text": "Confirm the total mass, center of gravity, stability, and distribution before use."},
                {"sourceKey": "decl-14f23940e4454f35", "label": "Load transfer", "text": "Review edge loading, impact, rolling, and other dynamic loading as part of the application approval."},
                {"sourceKey": "decl-2cb50ff260fd4df4", "label": "Floor and route", "text": "Confirm floor strength, levelness, transitions, debris, clearance, and separation from personnel."},
                {"sourceKey": "decl-1422de6bc56a48e3", "label": "Duty and environment", "text": "Confirm the operating frequency, ambient temperature, moisture exposure, and storage conditions."},
                {"sourceKey": "decl-5b726cdf8aa34cd5", "label": "People and responsibilities", "text": "Document operator training, authorization, inspection ownership, maintenance qualification, and escalation paths."},
            ], style="numbered"),
            _note("spec-limit", 6, "warning", "Rated capacity alone does not approve concentrated, offset, rolling, impact, edge, or overhanging loads. Obtain application-specific approval before using those conditions.", claims=["CLM-SAFETY-004"]),
        ]),
        _section("controls", "5 Controls and Indicators", [
            _heading("controls-title", 1, "5 Controls and Indicators"),
            _paragraph("controls-intro", 2, "The current product description identifies handle-mounted color-coded push buttons and a battery-discharge indicator. The assembly data identifies the battery box, switch, charger, plug, covers, and handle region; confirm the labels and control behavior on the machine before use." , claims=["CLM-CONTROL-001", "CLM-CAD-001"]),
            _figure("controls-figure", 3, "OM-FIG-002", "Figure 5-1. Battery and control assembly, isolated technical view."),
            _figure_legend("controls-legend", 4, "OM-FIG-002", legends.get("OM-FIG-002", [])),
            _heading("controls-functions-title", 5, "5.1 Control Functions", level=2),
            _list("controls-table", 6, [
                _cited_item(snapshot, "CLM-CONTROL-001", {"sourceKey": "decl-869532f7473d4c07", "label": "UP push button", "text": "Commands upward platform motion while held. Verify the label and momentary operation on the actual machine."}),
                _cited_item(snapshot, "CLM-CONTROL-001", {"sourceKey": "decl-035817b5504745d4", "label": "DOWN push button", "text": "Commands downward platform motion while held. Verify direction and release-to-stop behavior before handling a load."}),
                _cited_item(snapshot, "CLM-CONTROL-001", {"sourceKey": "decl-2a08c00b16284e4a", "label": "Battery-discharge indicator", "text": "Displays available battery state. Interpret the indication only according to the current machine label."}),
                _cited_item(snapshot, "CLM-SAFETY-FEATURE-001", {"sourceKey": "decl-3957a9ef9c1842ad", "label": "Main switch or isolation device", "text": "Controls electrical availability. Confirm the maintenance-isolation device and sequence for the machine configuration."}),
                _cited_item(snapshot, "CLM-ELECTRICAL-002", {"sourceKey": "decl-768adc98c0434c8e", "label": "Onboard charger connection", "text": "Connects the internal charger to the facility supply. Confirm the voltage, cord condition, and charger label before connection."}),
            ], style="definitions", claims=["CLM-CONTROL-001", "CLM-ELECTRICAL-001", "CLM-ELECTRICAL-002", "CLM-SAFETY-FEATURE-001"]),
            _note("controls-stop", 7, "warning", "If motion continues after a control is released, motion is reversed, or an indicator behaves unexpectedly, stop using the lift, prevent access, and refer the machine to qualified service personnel."),
        ]),
        _section("receiving", "6 Receiving and Initial Setup", [
            _heading("receiving-title", 1, "6 Receiving and Initial Setup"),
            _paragraph("receiving-intro", 2, "Complete receiving inspection before the machine enters service. Preserve shipping evidence and do not assemble, energize, or operate damaged equipment merely to determine whether it works."),
            _list("receiving-checklist", 3, [
                {"sourceKey": "decl-f7740aa9248141f2", "text": "Compare the model identification with the shipping documents. Record the serial number and configuration effectivity before the machine enters service."},
                {"sourceKey": "decl-086aff4e637744b6", "text": "Inspect the packaging and exposed structure for impact, bending, puncture, moisture, and tip-over evidence."},
                {"sourceKey": "decl-4cdc80ebb0ce4e85", "text": "Inventory loose items, covers, fasteners, charger lead, and supplied documentation. Resolve every shortage before setup."},
                {"sourceKey": "decl-f01706411da94b5f", "text": "Inspect the platform, scissor members, frame, cylinder, hose routing, and guards for deformation, leakage, missing retention, and interference."},
                {"sourceKey": "decl-80efce3f61b745b3", "text": "Inspect the casters and brakes. Wheels must rotate, swivel mechanisms must move freely, and brake hardware must be intact."},
                {"sourceKey": "decl-a328e494ad474699", "text": "Inspect the battery enclosure, controls, cables, and charger for damage, exposed conductors, contamination, and loose mounting."},
                {"sourceKey": "decl-c376800b4dd04399", "text": "Record every discrepancy with photographs, an assigned owner, and a documented disposition."},
            ], style="numbered", claims=["CLM-CAD-001", "CLM-RUNNING-001", "CLM-ELECTRICAL-001"]),
            _note("receiving-damage", 4, "warning", "Do not place a visibly damaged, leaking, incomplete, or incorrectly identified lift into service. Isolate it and obtain disposition from the supplier or responsible product authority."),
        ]),
        _section("pre-use", "7 Pre-Use Inspection", [
            _heading("preuse-title", 1, "7 Pre-Use Inspection"),
            _paragraph("preuse-intro", 2, "Perform and document a pre-use inspection at the start of each shift and after any event that could affect safe condition. Use the following checks with the acceptance criteria approved for the machine configuration.", claims=["CLM-INSPECTION-001"]),
            _list("preuse-checklist", 3, [
                {"sourceKey": "decl-2465dc47827e4e9c", "label": "Identification and inspection status", "text": "Confirm the correct machine and verify that required inspections are current."},
                {"sourceKey": "decl-2bf366b89e434adf", "label": "Platform and load surface", "text": "Confirm the surface is clean and secure, with no bend, crack, or loose component."},
                {"sourceKey": "decl-2a921e2ff3f742e2", "label": "Scissor members and pivots", "text": "Look for deformation, cracks, missing retention, damaged shafts, and abnormal looseness."},
                {"sourceKey": "decl-bb87e3c9d69d4f81", "label": "Hydraulic system", "text": "Inspect the cylinder, hose, fittings, and power pack for leakage, abrasion, damage, and fluid accumulation."},
                {"sourceKey": "decl-9c83ad659ba74ec3", "label": "Casters", "text": "Confirm rigid and swivel casters turn without binding, flat spots, damage, or trapped debris."},
                {"sourceKey": "decl-a5fbc6db02974653", "label": "Parking restraints", "text": "Inspect each installed brake mechanism. Verify the configuration-specific parking-restraint test and acceptance criteria before use; do not assume a one- or two-brake arrangement."},
                {"sourceKey": "decl-9f0f5e6bdcd64596", "label": "Handle and controls", "text": "Confirm controls, labels, and the indicator are secure, legible, responsive, and free from damage."},
                {"sourceKey": "decl-8903b91ca0d94daa", "label": "Battery and charger", "text": "Confirm the enclosure is closed, dry, secured, and free from exposed conductors or damaged connections."},
                {"sourceKey": "decl-7a8074ee5a24461d", "label": "Guards and safety devices", "text": "Confirm all expected devices are present and secure with no bypass or substitution."},
                {"sourceKey": "decl-a96a2027875142de", "label": "Work area and route", "text": "Confirm the floor is level, strong, dry, clear, illuminated, and separated from personnel."},
                {"sourceKey": "decl-37309348900a45f0", "label": "No-load function", "text": "Raise and lower without a load. Motion must be smooth and must stop when the control is released."},
                {"sourceKey": "decl-dbbd5cde13124640", "label": "Vertical creep", "text": "Observe the stationary platform. Any unexpected descent removes the machine from service."},
            ], style="numbered", claims=["CLM-INSPECTION-001", "CLM-ENV-001", "CLM-RUNNING-001"]),
            _note("preuse-fail", 4, "danger", "If any safety-critical inspection item fails, label the machine out of service, prevent operation, and report the condition. Do not defeat a device or improvise a repair to complete the shift."),
        ]),
        _section("operation", "8 Operating Instructions", [
            _heading("operation-title", 1, "8 Operating Instructions"),
            _paragraph("operation-boundary", 2, "Follow these steps together with the machine labels and approved site procedures. Confirm control behavior, load distribution, braking, duty cycle, and abnormal-operation response for the machine configuration."),
            _heading("operation-before", 3, "8.1 Before Raising a Load", level=2),
            _list("operation-before-table", 4, [
                {"sourceKey": "decl-998d4ca9798a47e4", "text": "Complete the pre-use inspection and clear the work area. Do not continue with an unresolved defect or bystander exposure."},
                {"sourceKey": "decl-10f0c8309d8c4474", "text": "Place the lift on the approved level surface with every caster fully supported and clear of slopes or soft transitions."},
                {"sourceKey": "decl-20f485674e964dff", "text": "Prevent unintended movement using the parking method approved for the actual brake configuration."},
                {"sourceKey": "decl-92f3d24636454ab5", "text": "Place the load on the platform without impact. Confirm the load is within capacity, stable, and distributed as approved."},
                {"sourceKey": "decl-6d1c3041c47244a3", "text": "Check the overhead and side clearances for the full expected travel. Keep structures, cables, racks, and people outside the path."},
            ], style="numbered", claims=["CLM-SAFETY-003", "CLM-SAFETY-004", "CLM-INSPECTION-001"]),
            _heading("operation-raise", 5, "8.2 Raise and Position", level=2),
            _list("operation-raise-table", 6, [
                {"sourceKey": "decl-4ca95e7dc4e2429f", "text": "Stand at the controls with a clear view of the load and lift. Keep hands, feet, clothing, and bystanders outside every hazard zone."},
                {"sourceKey": "decl-dbe40ec9b8974e93", "text": "Press and hold the verified UP control. Confirm the platform rises smoothly and stops when the control is released."},
                {"sourceKey": "decl-068420328c554e42", "text": "Stop at the required working height. Confirm the load remains stable and the platform and base show no abnormal movement."},
                {"sourceKey": "decl-7e19026258f342ec", "text": "Monitor the elevated machine for leakage, creep, unusual noise, deflection, or contact with an obstruction."},
            ], style="numbered", claims=["CLM-CONTROL-001", "CLM-SAFETY-005"]),
            _heading("operation-lower", 7, "8.3 Lower the Platform", level=2),
            _list("operation-lower-table", 8, [
                {"sourceKey": "decl-eaa727cad87947c9", "text": "Clear the complete platform and scissor travel zone. No person, tool, cable, or loose material may remain beneath or beside the mechanism."},
                {"sourceKey": "decl-d456a42fa5dd4ef4", "text": "Press and hold the verified DOWN control. Confirm the platform descends smoothly and stops when the control is released."},
                {"sourceKey": "decl-4dea140d973b4a36", "text": "Lower to the required height without abrupt cycling. Confirm the load remains stable and no component contacts an obstruction."},
                {"sourceKey": "decl-beae256f08674521", "text": "When work is complete, lower the platform fully and remove or secure the load so the machine is left stable."},
            ], style="numbered", claims=["CLM-SAFETY-002", "CLM-CONTROL-001"]),
            _note("operation-abnormal", 9, "warning", "Release the control immediately if motion is jerky, reversed, uncontrolled, unusually slow, accompanied by leakage or abnormal noise, or if the load shifts. Lower only when safe, isolate the machine, and request qualified service."),
        ]),
        _section("moving", "9 Moving and Parking", [
            _heading("moving-title", 1, "9 Moving and Parking"),
            _paragraph("moving-intro", 2, "The MMLE-50D uses two rigid front casters and two rear swivel casters. Move the lift manually only with the platform lowered and the load stable. Confirm the brake terminology and parking sequence on the actual machine because available source documents describe different brake arrangements.", claims=["CLM-RUNNING-001", "CLM-OPERATION-001"]),
            _list("moving-steps", 3, [
                {"sourceKey": "decl-9ca7d4ca0acb4593", "text": "Survey the route, destination, clearances, and floor transitions. Do not proceed over a slope, damaged area, debris, liquid, or insufficient clearance."},
                {"sourceKey": "decl-d2e9a9c68c524e64", "text": "Lower the platform and stabilize the load so nothing can fall, roll, snag, or shift."},
                {"sourceKey": "decl-9e65ecfac46f4d63", "text": "Release only the approved parking restraints while keeping the machine under direct operator control."},
                {"sourceKey": "decl-691fe6c09e7c4c1f", "text": "Move from the handle at a controlled walking pace. Stop if steering, caster motion, load stability, or visibility changes."},
                {"sourceKey": "decl-864c48633cca43ec", "text": "Keep feet and bystanders outside the caster path and maintain a clear exclusion zone."},
                {"sourceKey": "decl-33cbebb514e34fce", "text": "At the destination, stop on a level surface, apply the approved parking method, and verify the lift cannot roll."},
            ], style="numbered", claims=["CLM-OPERATION-001", "CLM-SAFETY-003", "CLM-SAFETY-005"]),
            _note("moving-no-raised", 4, "danger", "Do not transport the lift with the platform raised. A raised load increases instability and exposes the scissor mechanism and surrounding personnel."),
            _figure("running-gear-figure", 5, "OM-FIG-006", "Figure 9-1. Running gear and caster assemblies, exploded identification view.", height=390),
            _figure_legend("running-gear-legend", 6, "OM-FIG-006", legends.get("OM-FIG-006", [])),
        ]),
        _section("charging", "10 Battery and Charging", [
            _heading("charging-title", 1, "10 Battery and Charging"),
            _paragraph("charging-current", 2, "The current manufacturer product page describes an onboard 12 V battery and an internal fully automatic 110 V charger. The older service manual describes an external charger and electrolyte service; do not use those legacy steps because they conflict with the current architecture. See Figure 5-1 for the battery and control components.", claims=["CLM-ELECTRICAL-001", "CLM-ELECTRICAL-002", "CLM-CHARGE-LEGACY-001"]),
            _heading("charging-procedure-title", 3, "10.1 Charging Preparation", level=2),
            _list("charging-boundary", 4, [
                {"sourceKey": "decl-175df685b46b430c", "text": "Park the lift in a dry charging area, lower the platform fully, remove the load, and apply the approved parking method."},
                {"sourceKey": "decl-48ee274ddee142ee", "text": "Inspect the charger cord, plug, enclosure, and facility supply. Do not use damaged equipment, an adapter, or an unverified voltage."},
                {"sourceKey": "decl-381ea50cd17f4da9", "text": "Follow the current charger label and indicator sequence for the installed configuration. Do not apply the conflicting legacy external-charger procedure."},
                {"sourceKey": "decl-a48e3bdf55f44287", "text": "After charging, disconnect and stow the lead clear of the wheels and mechanism before moving the lift."},
                {"sourceKey": "decl-56c05d29b5124b09", "text": "Remove the lift from service and request qualified electrical or battery support if there is heat, odor, swelling, leakage, or repeated charge failure. Do not open the enclosure."},
            ], style="numbered", claims=["CLM-ELECTRICAL-001", "CLM-ELECTRICAL-002"]),
            _note("charging-review", 5, "notice", "Use the actual charger label and current manufacturer instructions for connection order, indicators, ventilation, completion criteria, battery chemistry, and fault response. Where no value is listed, obtain the current approved specification before charging or service."),
        ]),
        _section("cleaning-storage", "11 Cleaning and Storage", [
            _heading("cleaning-title", 1, "11 Cleaning and Storage"),
            _paragraph("cleaning-intro", 2, "A clean, dry machine makes defects easier to detect and protects controls, labels, wheels, and moving interfaces. The legacy source describes the lift as non-waterproof and intended for dry environments; current ingress and environmental ratings remain unverified.", claims=["CLM-ENV-001"]),
            _list("cleaning-table", 3, [
                {"sourceKey": "decl-9c52b7bdbb524178", "label": "Remove loose debris", "text": "Lower the platform, isolate the lift from use, and brush or vacuum accessible surfaces while keeping hands outside pinch zones."},
                {"sourceKey": "decl-d3d914c6486d495a", "label": "Wipe external surfaces", "text": "Use a lightly damp non-abrasive cloth on the platform, frame, handle, and covers, then dry the surfaces. Do not flood electrical or hydraulic components."},
                {"sourceKey": "decl-72823064db254e5f", "label": "Clean the casters", "text": "Prevent movement and remove accessible string and debris. Do not place hands beneath an unsupported machine."},
                {"sourceKey": "decl-8797b53366f8462a", "label": "Inspect after cleaning", "text": "Check labels, fasteners, leakage, corrosion, cables, and controls. Do not return a defective machine to service."},
                {"sourceKey": "decl-86ff6d99841a4735", "label": "Store the lift", "text": "Remove the load, lower the platform fully, apply the parking restraint, and use a dry level indoor area clear of travel routes."},
            ], style="definitions"),
            _note("cleaning-pressure", 4, "caution", "Do not use a pressure washer, steam jet, aggressive solvent, or abrasive process unless the manufacturer has approved it for this configuration."),
        ]),
        _section("maintenance", "12 Inspection and Maintenance", [
            _heading("maintenance-title", 1, "12 Inspection and Maintenance"),
            _paragraph("maintenance-boundary", 2, "Operators perform visual inspection and normal cleaning only. Qualified maintenance personnel perform work involving guards, elevated structures, stored energy, electrical enclosures, batteries, hydraulics, adjustment, or component replacement. Site energy-control procedures apply in addition to the machine-specific method.", claims=["CLM-SAFETY-002", "CLM-SAFETY-FEATURE-001"]),
            _note("maintenance-support", 3, "danger", "Never work under or within a raised platform unless the load is removed, hazardous energy is controlled, and the exact approved mechanical support is fully engaged and verified. Confirm the maintenance safety bars and their engagement procedure for the machine configuration." , claims=["CLM-SAFETY-FEATURE-004"]),
            _heading("maintenance-roles-title", 4, "12.1 Responsibilities", level=2),
            _list("maintenance-roles", 5, [
                {"sourceKey": "decl-2c57915bd46c444f", "label": "Operators", "text": "Perform the pre-use visual inspection and routine external cleaning. Report defects and do not remove guards or open enclosures."},
                {"sourceKey": "decl-45284a8885ba401c", "label": "Qualified maintenance personnel", "text": "Perform approved lubrication, hydraulic oil service, electrical work, and structural or caster repair using current specifications and acceptance criteria."},
                {"sourceKey": "decl-82d470788680454a", "label": "Authorized specialists", "text": "Perform relief-valve, pressure, or other safety-critical adjustment only when current settings, instruments, and approval are available."},
            ], style="definitions"),
            _heading("maintenance-candidate-title", 6, "12.2 Maintenance Planning Schedule", level=2),
            _paragraph("maintenance-schedule-scope", 7, "The intervals below originate in legacy manufacturer guidance. Confirm their applicability and obtain the approved lubricant, hydraulic fluid, quantity, procedure, and acceptance criteria for the identified machine before performing the work."),
            _table("maintenance-schedule", 8, ["Interval", "Maintenance activity"], [
                {"sourceKey": "decl-c487dabba3cd499a", "cells": ["Each shift / before use", "Inspect condition, leaks, creep, controls, casters, installed brake mechanisms, hardware, and route."]},
                {"sourceKey": "decl-9fcf6808a82a4d80", "cells": ["Monthly", "Inspect and lubricate applicable roller guides and confirmed grease points."]},
                {"sourceKey": "decl-85559e04e3c04af9", "cells": ["Six months", "Inspect and lubricate approved pivot points and axles."]},
                {"sourceKey": "decl-fcee61cdb96547c4", "cells": ["First 10 accumulated hours", "Perform the approved initial hydraulic-oil service when applicable to the confirmed configuration."]},
                {"sourceKey": "decl-2cc15d8698744227", "cells": ["Every 12 months", "Perform the approved hydraulic-oil service and comprehensive inspection."]},
                {"sourceKey": "decl-24ae3cff3ca74dc9", "cells": ["After damage, overload, uncontrolled motion, or major repair", "Remove the lift from service and complete a documented special inspection before return to service."]},
            ], claims=["CLM-MAINT-001", "CLM-MAINT-002", "CLM-MAINT-003", "CLM-INSPECTION-001"], keep_together=True),
        ]),
        _section("technical-reference", "13 Technical System Reference", [
            _heading("technical-title", 1, "13 Technical System Reference"),
            _paragraph("technical-intro", 2, "The following technical figures identify major assemblies for inspection planning and qualified-service discussion. Use the keys to locate scissor retention and wear points, check shafts and tubes for straightness and secure retention, inspect the cylinder for leakage or damaged exposed surfaces, and inspect the power pack externally for loose mounting, leakage, or damaged connections. Exploded presentation is for visualization only; it does not define disassembly order, torque, pressure, test criteria, or replacement authorization.", claims=["CLM-CAD-001", "CLM-INSPECTION-001"]),
            _figure("lift-mechanism-figure", 3, "OM-FIG-003", "Figure 13-1. Lift mechanism scissor, pivot, and roller components, exploded technical view.", height=330),
            _figure_legend("lift-mechanism-legend", 4, "OM-FIG-003", legends.get("OM-FIG-003", [])),
            _figure("lift-shafts-figure", 5, "OM-FIG-003B", "Figure 13-2. Lift mechanism shafts and shaft tubes, exploded technical view.", height=380),
            _figure_legend("lift-shafts-legend", 6, "OM-FIG-003B", legends.get("OM-FIG-003B", [])),
            _figure("cylinder-figure", 7, "OM-FIG-004", "Figure 13-3. Hydraulic cylinder assembly and mounting components, exploded technical view.", height=380),
            _figure_legend("cylinder-legend", 8, "OM-FIG-004", legends.get("OM-FIG-004", [])),
            _figure("powerpack-figure", 9, "OM-FIG-005", "Figure 13-4. Hydraulic power pack assembly, exploded technical view.", height=365),
            _figure_legend("powerpack-legend", 10, "OM-FIG-005", legends.get("OM-FIG-005", [])),
        ]),
        _section("troubleshooting", "14 Troubleshooting", [
            _heading("troubleshooting-title", 1, "14 Troubleshooting"),
            _paragraph("troubleshooting-boundary", 2, "Troubleshooting begins with condition recognition and safe escalation. Operators may perform only the non-invasive observations below. Removing covers, adjusting valves, opening electrical circuits, adding hydraulic fluid, or repairing components is qualified-service work." , claims=["CLM-TROUBLE-001"]),
            _table("troubleshooting-table", 3, ["Observed condition", "Operator-safe checks", "Required disposition"], [
                {"sourceKey": "decl-3537c8e30e4a4209", "cells": ["No response from controls", "Verify machine is in approved operating state; inspect indicator and visible cord/connection condition", "If not immediately explained by approved instructions, remove from service"]},
                {"sourceKey": "decl-93450c5c6f65490c", "cells": ["Motor runs but platform does not rise", "Release control; verify load is not above rated capacity and no visible obstruction exists", "Qualified hydraulic/electrical diagnosis"]},
                {"sourceKey": "decl-f2a2dc3288304eb5", "cells": ["Platform rises or lowers unevenly / jerks", "Release control; clear people; observe load stability and visible interference", "Lower only if safe; isolate and service"]},
                {"sourceKey": "decl-b5b17240dd0c4d80", "cells": ["Platform creeps downward", "Remove people from hazard zone; lower safely if possible; remove load", "Remove from service; qualified hydraulic inspection"]},
                {"sourceKey": "decl-ce0e1d7578454d27", "cells": ["Hydraulic leakage", "Do not touch or search for a pressurized leak; prevent access", "Qualified repair and cleanup/disposal"]},
                {"sourceKey": "decl-b7f0187b29aa413b", "cells": ["Abnormal noise, vibration, heat, odor, or smoke", "Release controls and move away if necessary", "Isolate supply only if safe; emergency/site response as applicable"]},
                {"sourceKey": "decl-2e7443e614754d08", "cells": ["Caster or brake problem", "Stop movement on a level surface and prevent rolling", "Remove from service until repaired and verified"]},
                {"sourceKey": "decl-9a7f8b278d904320", "cells": ["Charger fault or repeated low-battery indication", "Inspect only external cord, plug, label, and visible indicator", "Use current charger documentation; qualified electrical/battery service"]},
            ], claims=["CLM-TROUBLE-001", "CLM-INSPECTION-001"]),
            _note("troubleshooting-no-adjust", 4, "warning", "Do not adjust the relief valve, bypass a control, bridge a switch, open the battery or charger, or work on a pressurized hydraulic circuit without the approved service procedure."),
        ]),
        _section("records", "15 Inspection and Maintenance Records", [
            _heading("records-title", 1, "15 Inspection and Maintenance Records"),
            _paragraph("records-intro", 2, "Records connect machine condition, findings, corrective action, and return-to-service authorization. Use a unique asset identifier and retain records according to company policy and applicable obligations."),
            _table("records-log", 3, ["Date / time", "Asset / serial", "Inspection or work", "Finding / measurement", "Disposition", "Person"], [
                {"sourceKey": "decl-02cdd1a62dd34557", "cells": ["", "", "", "", "", ""]},
                {"sourceKey": "decl-2082ec2fd6c246c0", "cells": ["", "", "", "", "", ""]},
                {"sourceKey": "decl-076abc34a07045f5", "cells": ["", "", "", "", "", ""]},
                {"sourceKey": "decl-b5852124fb424ab3", "cells": ["", "", "", "", "", ""]},
                {"sourceKey": "decl-17ab2de56edc4a86", "cells": ["", "", "", "", "", ""]},
                {"sourceKey": "decl-48adb5e474b74ab7", "cells": ["", "", "", "", "", ""]},
            ]),
            _table("records-defect", 4, ["Defect-control field", "Required entry"], [
                {"sourceKey": "decl-c2c87e2470f14d35", "cells": ["Problem statement", "Observed condition without diagnosis unless verified"]},
                {"sourceKey": "decl-eef9a99ad9c6460a", "cells": ["Immediate control", "Out-of-service tag, barricade, load removal, or other containment"]},
                {"sourceKey": "decl-9385cb4d963b4e92", "cells": ["Technical evaluation", "Cause, affected components, evidence, and approved repair"]},
                {"sourceKey": "decl-3bd8232af6124413", "cells": ["Verification", "Inspection/test performed and acceptance criteria"]},
                {"sourceKey": "decl-245d70b1a8694ebb", "cells": ["Return to service", "Named authorization, date, configuration, and supporting records"]},
            ], keep_together=True),
        ]),
        _section("service-parts", "16 Service, Parts, and Support", [
            _heading("service-title", 1, "16 Service, Parts, and Support"),
            _paragraph("service-parts", 2, "Use the InspectorPro Illustrated Parts Manual to identify assemblies and components. Confirm the current service part number, revision, compatibility, and quantity before ordering or installing any item." , claims=["CLM-SERVICE-PARTS-001", "CLM-PART-IDENTITY-001"]),
            _table("service-info", 3, ["Information required for support", "Record"], [
                {"sourceKey": "decl-a55f3ca742604a58", "cells": ["Product / model", "MMLE-50D Electric Mobile Lift"]},
                {"sourceKey": "decl-ad18fe4ccea1410f", "cells": ["Serial number", "Not specified"]},
                {"sourceKey": "decl-6f0a960fd15a4483", "cells": ["OEM configuration / effectivity", "Not specified"]},
                {"sourceKey": "decl-45ff61b093e34301", "cells": ["InspectorPro asset revision", "Internal A - not an OEM document revision"]},
                {"sourceKey": "decl-642a7cb845b941dc", "cells": ["Current document number", "OM-MMLE-50D-001"]},
                {"sourceKey": "decl-1ae9d1b09cf44b3f", "cells": ["Manufacturer / authorized service contact", "Not specified - obtain before release"]},
                {"sourceKey": "decl-d1342b24301549e6", "cells": ["Related illustrated parts manual", "MMLE-50D Illustrated Parts Manual"]},
            ], claims=["CLM-REVISION-001", "CLM-PART-IDENTITY-001"]),
            _note("service-substitution", 4, "notice", "Do not select a replacement solely because its name, appearance, or internal reference appears similar. Product authority must approve service identity and effectivity."),
        ]),
        _section("sources", "17 Sources and Document Review Status", [
            _heading("sources-title", 1, "17 Sources and Document Review Status"),
            _paragraph("sources-method", 2, "This manual uses current manufacturer product information, available service literature, industry guidance, and assembly records. When sources differ, information approved for the machine configuration takes precedence."),
            _table("sources-table", 3, ["Claim-contributing source", "Evidence role and limitations"], []),
            _heading("sources-open-title", 4, "17.1 Open Review Items", level=2),
            _table("sources-open", 5, ["Area", "Current treatment", "Release requirement"], [
                {"sourceKey": "decl-45ba8e104f3a4c9e", "cells": ["Configuration/effectivity", "Shown as not specified", "Bind serial/build/revision to current instructions"]},
                {"sourceKey": "decl-d48f30c221db4701", "cells": ["Safety features", "Named but not called out or procedurally described", "Map safety bars, isolator, and relief valve to actual configuration"]},
                {"sourceKey": "decl-d05eeef68d104423", "cells": ["Charging", "Architecture and boundaries only", "Approve current connection, indicators, environment, and completion procedure"]},
                {"sourceKey": "decl-65257b8df2c6451b", "cells": ["Maintenance", "Legacy candidates labeled for review", "Approve intervals, fluids, lubricants, torque, pressure, tools, and criteria"]},
                {"sourceKey": "decl-94307265243f4bb2", "cells": ["Schematics", "Not reproduced", "Supply current approved electrical and hydraulic diagrams"]},
                {"sourceKey": "decl-9f692b79f191491d", "cells": ["Standards/symbols", "Bibliographic awareness only", "Complete licensed clause-level and symbol review"]},
                {"sourceKey": "decl-2802300c75684d3d", "cells": ["Reviewers", "No release signatures", "Engineering, safety, product, technical-publications, legal, and accessibility approvals"]},
            ]),
        ]),
    ]
    cited_claim_ids = {
        str(claim_id)
        for section in sections
        if str(section.get("sectionId") or "") != "sources"
        for block in section.get("blocks") or []
        for claim_id in block.get("evidenceClaimIds") or []
        if str(claim_id).strip()
    }
    for section in sections:
        if str(section.get("sectionId") or "") != "sources":
            continue
        for block in section.get("blocks") or []:
            if str(block.get("blockId") or "") == "sources-table":
                block["payload"]["rows"] = _source_rows(snapshot, cited_claim_ids)
    return sections


FIGURE_SPECS: Dict[str, Dict[str, Any]] = {
    "OM-FIG-001": {
        "scopeKind": "assembly",
        "groupNames": [],
        "pose": "exploded",
        "cameraPreset": "isometric",
        "explodeFactor": 0.58,
    },
    "OM-FIG-002": {
        "scopeKind": "manual_group",
        "groupNames": ["Battery and Control Assembly"],
        "pose": "exploded",
        "cameraPreset": "isometric",
        "explodeFactor": 0.75,
    },
    "OM-FIG-003": {
        "scopeKind": "manual_group",
        "groupNames": ["Lift Mechanism Assembly"],
        "pose": "exploded",
        "cameraPreset": "isometric",
        "explodeFactor": 0.38,
        "descriptionExcludesAny": ["Shaft"],
    },
    "OM-FIG-003B": {
        "scopeKind": "manual_group",
        "groupNames": ["Lift Mechanism Assembly"],
        "pose": "exploded",
        "cameraPreset": "isometric",
        "explodeFactor": 0.38,
        "descriptionIncludesAny": ["Shaft"],
    },
    "OM-FIG-004": {
        "scopeKind": "manual_group",
        "groupNames": ["Hydraulic Cylinder Assembly"],
        "pose": "exploded",
        "cameraPreset": "front",
        "explodeFactor": 0.52,
    },
    "OM-FIG-005": {
        "scopeKind": "manual_group",
        "groupNames": ["Hydraulic Power Pack Assembly"],
        "pose": "exploded",
        "cameraPreset": "isometric",
        "explodeFactor": 0.78,
    },
    "OM-FIG-006": {
        "scopeKind": "manual_group",
        "groupNames": [
            "Right Swivel Caster and Brake Assembly",
            "Left Swivel Caster and Brake Assembly",
            "Rigid Caster Assembly",
            "Caster Support Structure",
        ],
        "pose": "exploded",
        "cameraPreset": "isometric",
        "explodeFactor": 0.28,
        "calloutScope": "manual_group",
    },
}
