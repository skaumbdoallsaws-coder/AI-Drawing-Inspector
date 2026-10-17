"""Bounded semantic cell composition for the generation admission path."""
from collections import Counter
from collections.abc import Mapping
import math

from .errors import FacilityValidationError
from .g1_planner import G1_ZONE_TYPES
from .semantic_model import CELL_FEASIBILITY_STRATEGIES
from .cell_composition import G5_CELL_OBJECTIVES
from .cell_replication import G6_MAXIMUM_TARGET_AREAS


MAX_GENERATION_PLACEMENTS = 900
COMPOSITION_FIELDS = {
    "area_partition": ("areaGroups", "areaGroupId", {
        "parentDepartmentId", "labels", "zoneTypes", "proportions", "arrangement", "orientation", "rows", "evidenceRefs"}),
    "cell_layout": ("cellRecipes", "recipe_id", {
        "target_area", "member_batches", "candidate_strategies", "selected_strategy_or_objective",
        "authored_spacing", "process_order", "interfaces", "evidence_refs"}),
    "module_repetition": ("moduleFamilies", "family_id", {
        "source_recipe_or_cell", "target_areas", "allowed_transform_mode", "preserve_source",
        "conformance_requirements", "composable_with", "evidence_refs"}),
}


def _fail(message):
    raise FacilityValidationError("generation_composition_invalid", message)


def composition_parameter_schemas():
    def obj(fields):
        return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}
    def arr(items, maximum=32, minimum=0):
        return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}
    ident = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$"}
    text = {"type": "string", "minLength": 1, "maxLength": 240}
    refs = {**arr(ident), "uniqueItems": True}
    empty = arr(obj({}), 0)
    return {
        "area_partition": obj({"parentDepartmentId": ident, "labels": arr(text, 32, 1),
            "zoneTypes": arr({"enum": sorted(G1_ZONE_TYPES)}, 32, 1),
            "proportions": arr({"type": "number", "exclusiveMinimum": 0, "maximum": 1}, 32, 1),
            "arrangement": {"enum": ["rows", "columns"]}, "orientation": {"enum": ["horizontal", "vertical"]},
            "rows": empty, "evidenceRefs": refs}),
        "cell_layout": obj({"target_area": text, "member_batches": {**arr(ident, 24, 1), "uniqueItems": True},
            "candidate_strategies": {**arr({"enum": sorted(CELL_FEASIBILITY_STRATEGIES)}, 10, 1), "uniqueItems": True},
            "selected_strategy_or_objective": {"enum": sorted(set(CELL_FEASIBILITY_STRATEGIES) | G5_CELL_OBJECTIVES)},
            "authored_spacing": {"anyOf": [obj({"value": {"type": "number", "minimum": 0, "maximum": 20},
                "unit": {"const": "m"}, "evidence_ref": ident}), {"type": "null"}]},
            "process_order": empty, "interfaces": empty, "evidence_refs": refs}),
        "module_repetition": obj({"source_recipe_or_cell": ident,
            "target_areas": {**arr(text, G6_MAXIMUM_TARGET_AREAS, 1), "uniqueItems": True},
            "allowed_transform_mode": {"const": "translate_exact"}, "preserve_source": {"const": True},
            "conformance_requirements": {"const": ["exact_relative_geometry"]},
            "composable_with": empty, "evidence_refs": refs}),
    }


def validate_composition_parameters(kind, value):
    # These closed fields match the existing package/program contracts. Fields
    # the compilers do not execute stay empty instead of implying support.
    from .generation_requirements import identifier
    if not isinstance(value, Mapping) or set(value) != COMPOSITION_FIELDS[kind][2]:
        _fail(f"{kind} fields do not match the supported contract.")

    def texts(field, maximum=32, minimum=0, ids=False):
        values = value[field]
        if (not isinstance(values, list) or not minimum <= len(values) <= maximum
                or any(not isinstance(v, str) or not v.strip() or len(v) > 240 for v in values)
                or len(set(values)) != len(values)):
            _fail(f"{kind}.{field} must be a bounded list of distinct names.")
        if ids:
            for v in values:
                identifier(v, field)
        return values

    evidence_key = "evidenceRefs" if kind == "area_partition" else "evidence_refs"
    texts(evidence_key, ids=True)
    if kind == "area_partition":
        identifier(value["parentDepartmentId"], "parentDepartmentId")
        labels = texts("labels", minimum=1)
        types, proportions = value["zoneTypes"], value["proportions"]
        if (not isinstance(types, list) or len(types) != len(labels)
                or any(not isinstance(t, str) or t not in G1_ZONE_TYPES for t in types)
                or not isinstance(proportions, list) or len(proportions) != len(labels)
                or any(type(n) not in (int, float) or not math.isfinite(n) or not 0 < n <= 1 for n in proportions)
                or abs(sum(proportions) - 1) > 1e-9
                or value["arrangement"] not in ("rows", "columns")
                or value["orientation"] not in ("horizontal", "vertical") or value["rows"] != []):
            _fail("Area partitions need matching labels/types/proportions and supported rows or columns.")
    elif kind == "cell_layout":
        if not isinstance(value["target_area"], str) or not value["target_area"].strip() or len(value["target_area"]) > 240:
            _fail("A cell needs one named area.")
        texts("member_batches", maximum=24, minimum=1, ids=True)
        strategies = texts("candidate_strategies", maximum=10, minimum=1, ids=True)
        selected = value["selected_strategy_or_objective"]
        if (not set(strategies) <= set(CELL_FEASIBILITY_STRATEGIES) or not isinstance(selected, str)
                or selected not in set(strategies) | G5_CELL_OBJECTIVES
                or value["process_order"] != [] or value["interfaces"] != []):
            _fail("Unsupported cell strategy, process order or interface authoring.")
        spacing = value["authored_spacing"]
        if spacing is not None:
            if (not isinstance(spacing, Mapping) or set(spacing) != {"value", "unit", "evidence_ref"}
                    or spacing["unit"] != "m" or type(spacing["value"]) not in (int, float)
                    or not math.isfinite(spacing["value"]) or not 0 <= spacing["value"] <= 20):
                _fail("Cell spacing must be an explicit metre gap with evidence, or null.")
            identifier(spacing["evidence_ref"], "evidence_ref")
    else:
        identifier(value["source_recipe_or_cell"], "source_recipe_or_cell")
        texts("target_areas", maximum=G6_MAXIMUM_TARGET_AREAS, minimum=1)
        if (value["allowed_transform_mode"] != "translate_exact" or value["preserve_source"] is not True
                or value["conformance_requirements"] != ["exact_relative_geometry"] or value["composable_with"] != []):
            _fail("Modules support preserved seeds and exact translated copies only.")


def composition_inventory(package):
    """Qualify recipe scope and compute total inventory before geometry expansion."""
    if package.get("floorCommunication"):
        _fail("Floor communication is not yet admitted by the generation chat.")
    resources = package["equipmentRequirements"]
    batches = {r["requirementId"]: r for r in resources}
    totals = {key: r["quantity"] for key, r in batches.items()}
    departments = {d["departmentId"]: d["label"] for d in package["departments"]}
    parents = {label.casefold(): key for key, label in departments.items()}
    evidence = {e["evidenceId"]: e for e in package["evidenceRegister"]}
    groups, recipes, families = (package[k] for k in ("areaGroups", "cellRecipes", "moduleFamilies"))
    if len(groups) > 8 or len(recipes) > 8 or len(families) > 8:
        _fail("At most eight partitions, seed recipes and module families are supported.")
    for kind, (collection, id_key, fields) in COMPOSITION_FIELDS.items():
        ids = []
        for entry in package[collection]:
            if not isinstance(entry, Mapping) or set(entry) != fields | {id_key}:
                _fail(f"{collection} contains unsupported fields.")
            from .generation_requirements import identifier
            identifier(entry[id_key], id_key)
            ids.append(entry[id_key])
            validate_composition_parameters(kind, {k: entry[k] for k in fields})
            refs = entry["evidenceRefs" if kind == "area_partition" else "evidence_refs"]
            if not set(refs) <= evidence.keys():
                _fail("Composition references unknown evidence.")
        if len(ids) != len(set(ids)):
            _fail("Composition IDs must be unique within their collection.")
    divided = set()
    for group in groups:
        parent = group["parentDepartmentId"]
        if parent not in departments or parent in divided:
            _fail("Each partition needs a distinct existing department.")
        divided.add(parent)
        for label in group["labels"]:
            key = label.casefold()
            if key in parents:
                _fail("Department and cell area labels must be globally unambiguous.")
            parents[key] = parent
    if sum(len(g["labels"]) for g in groups) > 64:
        _fail("The child-area budget is 64.")
    for resource in resources:
        area = resource["targetArea"].casefold()
        if area not in parents or area in {departments[d].casefold() for d in divided}:
            _fail("Resources must target a known leaf area, not a subdivided parent.")
    occupied = {r["targetArea"].casefold() for r in resources}
    recipe_by_id, recipe_areas = {}, set()
    for recipe in recipes:
        area = recipe["target_area"].casefold()
        members = {key for key, r in batches.items() if r["targetArea"].casefold() == area}
        if not members or members != set(recipe["member_batches"]) or area in recipe_areas:
            _fail("A seed recipe must name every resource batch in its own distinct leaf area.")
        spacing = recipe["authored_spacing"]
        if spacing and (spacing["evidence_ref"] not in evidence or evidence[spacing["evidence_ref"]]["sourceType"]
                        in {"public_research_result", "local_equipment_document"}):
            _fail("A document read is not an applicable cell-spacing fact.")
        recipe_areas.add(area)
        recipe_by_id[recipe["recipe_id"]] = recipe
    targets, used_seeds = set(), set()
    for family in families:
        source = family["source_recipe_or_cell"]
        if source not in recipe_by_id or source in used_seeds:
            _fail("Each module family needs one distinct qualified seed recipe.")
        used_seeds.add(source)
        recipe = recipe_by_id[source]
        source_area = recipe["target_area"].casefold()
        for label in family["target_areas"]:
            area = label.casefold()
            if (area not in parents or area in occupied or area in targets
                    or area in {d.casefold() for d in departments.values()}
                    or parents[area] != parents[source_area]):
                _fail("Copies need distinct empty sibling child areas in the seed department.")
            targets.add(area)
        for key in recipe["member_batches"]:
            totals[key] += batches[key]["quantity"] * len(family["target_areas"])
    if sum(totals.values()) > MAX_GENERATION_PLACEMENTS:
        raise FacilityValidationError("generation_admission_budget_exceeded", "Expanded inventory exceeds 900 placements.")
    return {"resourceTotals": totals, "placements": sum(totals.values()), "cellCount": len(recipes) + len(targets)}


def require_composition_coverage(ledger, package, inventory):
    active = {(r["predicate"]["kind"], r["predicate"]["subjectId"]) for r in ledger["requirements"]
              if r["disposition"] == "represented"}
    required = {(kind, entry[id_key]) for kind, (collection, id_key, _) in COMPOSITION_FIELDS.items()
                for entry in package[collection]}
    if package["moduleFamilies"]:
        required.update(("resource_total", key) for key in inventory["resourceTotals"])
    missing = sorted(required - active)
    if missing:
        raise FacilityValidationError("generation_composition_requirements_incomplete",
            "Cell structure and expanded quantities need explicit requirement dispositions.",
            details={"missingPredicates": [{"kind": k, "subjectId": s} for k, s in missing]})


def validate_composed_inventory(candidate, inventory):
    actual = Counter(p.get("metadata", {}).get("batchId") for p in candidate.get("placements", []))
    if dict(actual) != inventory["resourceTotals"]:
        _fail("Compiled resource inventory differs from the admitted seed and copy counts.")
