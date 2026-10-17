"""Checks declared process precedence and departmental circulation, not station IO."""
from .errors import FacilityValidationError


FLOW_SCOPE = "declared_process_and_department_circulation_not_station_transfers"


def process_edges(steps):
    return {(prior, step["processStepId"]) for step in steps
            for prior in step["predecessorProcessStepIds"]}


def _edge_details(edges, name):
    return {name: [list(edge) for edge in sorted(edges)[:16]], "edgeCount": len(edges), "truncated": len(edges) > 16}


def require_process_coverage(ledger, context, *, allow_unresolved=False):
    edges = process_edges(context["processSteps"])
    covered = set()
    for item in ledger["requirements"]:
        predicate = item.get("predicate") or {}
        if item["disposition"] != "represented" or predicate.get("kind") != "process_sequence":
            continue
        steps = predicate["parameters"]["processStepIds"]
        pairs = set(zip(steps, steps[1:]))
        if predicate["subjectId"] != ledger["layoutId"] or not pairs <= edges:
            raise FacilityValidationError("generation_process_sequence_unbound",
                "Process sequence must name adjacent dependencies in the bound process context and target this layout.",
                details={"requirementId": item["requirementId"], **_edge_details(edges, "availableEdges")})
        covered.update(pairs)
    if allow_unresolved and any(item["disposition"] in {"needs_clarification", "unsupported"} for item in ledger["requirements"]):
        return
    if edges - covered:
        raise FacilityValidationError("generation_process_sequence_uncovered",
            "Record process_sequence predicates for every declared dependency. Department presence alone does not preserve process order.",
            details={**_edge_details(edges - covered, "missingEdges"), "subjectId": ledger["layoutId"]})


def check_process_sequence(package, step_ids):
    """One declared material itinerary must serve each interdepartment dependency.

    Do not join unrelated routes just because their area labels coincide: that
    would assert a physical junction which has not been established here.
    """
    steps = {item["processStepId"]: item for item in package.get("processSteps", [])}
    departments = {item["departmentId"]: item for item in package.get("departments", [])}
    labels = {}
    for key, department in departments.items():
        labels.setdefault(department["label"].casefold(), []).append(key)
    resource_areas = {label: list(ids) for label, ids in labels.items()}
    for group in package.get("areaGroups", []):
        for label in group["labels"]:
            resource_areas.setdefault(label.casefold(), []).append(group["parentDepartmentId"])
    transfers = []
    for before, after in zip(step_ids, step_ids[1:]):
        check = {"fromStepId": before, "toStepId": after, "passed": False, "routeIds": []}
        source, target = steps.get(before), steps.get(after)
        if source is None or target is None or before not in target["predecessorProcessStepIds"]:
            check["code"] = "generation_process_precedence_missing"
        elif any(step["departmentId"] not in departments or step["processStepId"] not in
                 departments[step["departmentId"]].get("processStepRefs", []) for step in (source, target)):
            check["code"] = "generation_process_department_binding_missing"
        elif any(resource_areas.get(resource.get("targetArea", "").casefold(), []) != [step["departmentId"]]
                 for step in (source, target) for resource in package.get("equipmentRequirements", [])
                 if step["processStepId"] in resource.get("processStepRefs", [])):
            check["code"] = "generation_process_resource_binding_mismatch"
        elif source["departmentId"] == target["departmentId"]:
            check.update(passed=True, code=None, limitation="intradepartment_transfer_not_evaluated")
        else:
            for route in package.get("routes", []):
                if (route.get("routeKind") not in {"material", "forklift"}
                        or route.get("direction") not in {"one_way", "two_way"}
                        or not {before, after} <= set(route.get("processStepRefs", []))):
                    continue
                names = [route["sourceArea"], *route.get("viaAreas", []), route["targetArea"]]
                resolved = [labels.get(name.casefold(), []) for name in names]
                if any(len(matches) != 1 for matches in resolved):
                    continue
                itinerary = [matches[0] for matches in resolved]
                if source["departmentId"] not in itinerary or target["departmentId"] not in itinerary:
                    continue
                if route["direction"] == "two_way" or any(
                        left < right for left, dept in enumerate(itinerary) if dept == source["departmentId"]
                        for right, other in enumerate(itinerary) if other == target["departmentId"]):
                    check["routeIds"].append(route["routeId"])
                    break
            check.update(passed=bool(check["routeIds"]), code=None if check["routeIds"] else "generation_process_material_route_missing")
        transfers.append(check)
    return {"scope": FLOW_SCOPE, "passed": bool(transfers) and all(item["passed"] for item in transfers), "transfers": transfers}
