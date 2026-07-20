"""Compile a minimal trusted context for selected Sage skills."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


_ALWAYS_FIELDS = {
    "_user_message",
    "part_number",
    "part_name",
    "revision",
    "active_mode",
    "mode_submode",
    "has_drawing_file",
    "has_part_number",
    "inspection_in_progress",
    "inspection_can_run",
    "drawing_type",
    "drawing_workflow_mode",
    "drawing_capabilities",
    "drawing_classification_reasons",
    "fai_request",
}

_CONTEXT_FIELDS = {
    "fai.characteristics": {"fai_characteristics"},
    "drawing.dimensions": {"selected_dimensions", "available_dimensions", "available_views"},
    "part.feature_map": {
        "profile_features",
        "part_description",
        "view_expectations",
        "focused_feature",
        "available_cad_features",
    },
    "assembly.parts": {
        "selected_parts",
        "available_parts",
        "part_properties",
        "part_color_legend",
    },
    "assembly.mates": {"mate_relationships", "nearby_parts"},
    "assembly.functional_relationships": {
        "functional_relationship_summary",
        "functional_relationships",
        "affected_functional_interfaces",
    },
    "motion.groups": {"mode_state", "viewport_context"},
    "viewport.state": {"mode_state", "viewport_context", "selected_parts"},
}


@dataclass(frozen=True)
class CompiledContext:
    context: dict[str, Any]
    accounting: dict[str, Any]
    provenance: tuple[dict[str, Any], ...] = ()


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _compact_number(value: float) -> float:
    return round(float(value), 9)


def _characteristic_id(row: Mapping[str, Any], index: int) -> str:
    value = row.get("char_number")
    return str(value if value not in (None, "") else index + 1)


def _feature_kind(row: Mapping[str, Any]) -> str | None:
    declared = str(row.get("fit_feature_kind") or "").strip().lower()
    if declared in {"internal", "internal_diameter", "bore", "hole"}:
        return "internal_diameter"
    if declared in {"external", "external_diameter", "shaft", "outside_diameter"}:
        return "external_diameter"
    text = str(row.get("description") or "").lower()
    if re.search(r"\b(?:outside|outer|external)\s+diameter\b|\bo\.?d\.?(?:\s|$)", text):
        return "external_diameter"
    if re.search(r"\b(?:inside|inner|internal)\s+diameter\b|\bi\.?d\.?(?:\s|$)", text):
        return "internal_diameter"
    if re.search(r"\b(?:bore|hole)\b", text) and re.search(r"\b(?:diameter|dia\.?|thru)\b", text):
        return "internal_diameter"
    return None


def _fit_effect(feature_kind: str | None, direction: str | None) -> str | None:
    if feature_kind == "external_diameter":
        if direction == "below_lower_limit":
            return "increased_clearance"
        if direction == "above_upper_limit":
            return "reduced_clearance_or_increased_interference"
    if feature_kind == "internal_diameter":
        if direction == "above_upper_limit":
            return "increased_clearance"
        if direction == "below_lower_limit":
            return "reduced_clearance_or_increased_interference"
    return None


def _enrich_fai_rows(rows: list[Any]) -> tuple[list[Any], dict[str, Any], list[dict[str, Any]]]:
    enriched: list[Any] = []
    conflicts: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    seen: dict[str, tuple[Any, ...]] = {}
    units: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            enriched.append(copy.deepcopy(raw))
            warnings.append({"type": "invalid_fai_row", "row_index": index})
            continue
        row = copy.deepcopy(raw)
        char_id = _characteristic_id(row, index)
        nominal = _as_float(row.get("nominal"))
        measured = _as_float(row.get("measured"))
        lower = _as_float(row.get("lower_limit"))
        upper = _as_float(row.get("upper_limit"))
        tol_plus = _as_float(row.get("tol_plus"))
        tol_minus = _as_float(row.get("tol_minus"))
        if nominal is not None and lower is None and tol_minus is not None:
            lower = nominal - abs(tol_minus)
            row["lower_limit"] = _compact_number(lower)
        if nominal is not None and upper is None and tol_plus is not None:
            upper = nominal + abs(tol_plus)
            row["upper_limit"] = _compact_number(upper)
        unit = str(row.get("unit") or row.get("units") or "mm").strip().lower()
        if unit:
            units.add(unit)

        direction = None
        computed_status = None
        out_of_tolerance = None
        if measured is not None and nominal is not None:
            row["deviation_from_nominal"] = _compact_number(measured - nominal)
        if measured is not None and lower is not None and upper is not None:
            if measured < lower:
                direction = "below_lower_limit"
                out_of_tolerance = lower - measured
                computed_status = "FAIL"
            elif measured > upper:
                direction = "above_upper_limit"
                out_of_tolerance = measured - upper
                computed_status = "FAIL"
            else:
                direction = "within_tolerance"
                out_of_tolerance = 0.0
                computed_status = "PASS"
            row["deviation_direction"] = direction
            row["out_of_tolerance_by"] = _compact_number(out_of_tolerance)
            declared_status = str(row.get("status") or "").strip().upper()
            if declared_status in {"PASS", "FAIL"} and declared_status != computed_status:
                conflicts.append({
                    "type": "fai_status_conflict",
                    "characteristic_id": char_id,
                    "declared": declared_status,
                    "computed": computed_status,
                })
            elif declared_status not in {"PASS", "FAIL"}:
                row["computed_status"] = computed_status

        kind = _feature_kind(row)
        effect = _fit_effect(kind, direction)
        if kind:
            row["fit_feature_kind"] = kind
        if effect:
            row["fit_effect_hint"] = effect

        signature = (
            nominal,
            measured,
            lower,
            upper,
            str(row.get("status") or "").strip().upper(),
        )
        if char_id in seen and seen[char_id] != signature:
            conflicts.append({
                "type": "duplicate_characteristic_conflict",
                "characteristic_id": char_id,
            })
        else:
            seen[char_id] = signature

        source = {
            "type": "fai_table",
            "characteristic_id": char_id,
        }
        if measured is not None:
            provenance.append({
                "evidence_id": f"fai.{char_id}.measured",
                "classification": "observed_fact",
                "value": _compact_number(measured),
                "unit": unit,
                "source": source,
            })
        if nominal is not None:
            provenance.append({
                "evidence_id": f"fai.{char_id}.nominal",
                "classification": "product_requirement",
                "value": _compact_number(nominal),
                "unit": unit,
                "source": source,
            })
        if out_of_tolerance is not None:
            provenance.append({
                "evidence_id": f"fai.{char_id}.out_of_tolerance_by",
                "classification": "calculated_fact",
                "value": _compact_number(out_of_tolerance),
                "unit": unit,
                "based_on": [f"fai.{char_id}.measured", f"fai.{char_id}.nominal"],
            })
        if effect:
            provenance.append({
                "evidence_id": f"fai.{char_id}.fit_effect",
                "classification": "engineering_inference",
                "value": effect,
                "based_on": [
                    f"fai.{char_id}.out_of_tolerance_by",
                    f"fai.{char_id}.feature_kind",
                ],
            })
        enriched.append(row)
    if len(units) > 1:
        warnings.append({"type": "mixed_fai_units", "units": sorted(units)})
    status = "error" if conflicts else ("warning" if warnings else "ok")
    diagnostics = {
        "schema_version": 1,
        "status": status,
        "conflicts": conflicts,
        "warnings": warnings,
    }
    return enriched, diagnostics, provenance


def _manifest_context_keys(packages: Iterable[Any]) -> tuple[set[str], set[str]]:
    required: set[str] = set()
    optional: set[str] = set()
    for package in packages:
        manifest = package.manifest
        required.update(str(v) for v in manifest.requires_context)
        optional.update(str(v) for v in manifest.optional_context)
    return required, optional


def _contract_policy(packages: Iterable[Any]) -> dict[str, Any]:
    contracts = [
        package.contract
        for package in packages
        if getattr(package, "contract", None) is not None
    ]
    maximum_tokens = max(
        (contract.maximum_context_tokens for contract in contracts),
        default=6000,
    )
    priorities: list[str] = []
    for contract in contracts:
        for key in contract.context_priorities:
            if key not in priorities:
                priorities.append(key)
    return {
        "maximum_tokens": maximum_tokens,
        "priorities": priorities,
        "forbidden_context": sorted({
            key for contract in contracts for key in contract.forbidden_context
        }),
        "required_evidence": sorted({
            key for contract in contracts for key in contract.required_evidence
        }),
    }


def _context_key_available(compiled: Mapping[str, Any], context_key: str) -> bool:
    fields = _CONTEXT_FIELDS.get(context_key, set())
    return any(compiled.get(field) not in (None, "", [], {}) for field in fields)


def _estimate_tokens(value: Mapping[str, Any]) -> int:
    serialized = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    )
    return math.ceil(len(serialized) / 4)


def _apply_context_budget(
    compiled: dict[str, Any],
    *,
    required: set[str],
    optional: set[str],
    maximum_tokens: int,
    priorities: list[str],
) -> dict[str, Any]:
    removed: list[str] = []
    ranked = list(priorities)
    for key in sorted(optional):
        if key not in ranked:
            ranked.append(key)
    retained_keys = set(required) | set(optional)
    while _estimate_tokens(compiled) > maximum_tokens:
        removable = next(
            (key for key in reversed(ranked) if key in optional and key in retained_keys),
            None,
        )
        if removable is None:
            break
        retained_keys.remove(removable)
        removed.append(removable)
        fields_still_needed = {
            field
            for key in retained_keys
            for field in _CONTEXT_FIELDS.get(key, set())
        }
        for field in _CONTEXT_FIELDS.get(removable, set()):
            if field not in fields_still_needed:
                compiled.pop(field, None)
        if removable == "fai.characteristics" and "fai.characteristics" not in retained_keys:
            compiled.pop("fai_table_summary", None)
    estimated = _estimate_tokens(compiled)
    return {
        "maximum_tokens": maximum_tokens,
        "estimated_tokens": estimated,
        "removed_optional_context": removed,
        "required_evidence_preserved": True,
        "budget_exceeded": estimated > maximum_tokens,
    }


def _fai_status_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "PENDING").upper()
        counts[status] = counts.get(status, 0) + 1
    return {"total": len(rows), "status_counts": counts}


def _filter_direct_mates(ctx: Mapping[str, Any], relationships: Any) -> Any:
    if not isinstance(relationships, list):
        return relationships
    part_name = re.sub(r"[^a-z0-9]+", "", str(ctx.get("part_name") or "").lower())
    if not part_name:
        return relationships[:20]
    direct = []
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        filenames = [
            str(rel.get("component1FileName") or ""),
            str(rel.get("component2FileName") or ""),
        ]
        stems = [re.sub(r"[^a-z0-9]+", "", value.lower().rsplit(".", 1)[0]) for value in filenames]
        if part_name in stems:
            direct.append(rel)
    return direct[:20] if direct else []


def _identity_diagnostics(
    ctx: Mapping[str, Any], compiled: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    conflicts: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    current_part = str(ctx.get("part_number") or "").strip()
    part_rows = compiled.get("available_parts") or compiled.get("part_color_legend") or []
    known_parts = {
        str(row.get("part_number") or row.get("partNumber") or "").strip()
        for row in part_rows
        if isinstance(row, dict)
    }
    known_parts.discard("")
    if current_part and known_parts and current_part not in known_parts:
        conflicts.append({
            "type": "inspected_part_not_in_assembly_context",
            "inspected_part": current_part,
        })

    viewport = compiled.get("viewport_context")
    state = viewport.get("state") if isinstance(viewport, dict) else None
    state = state if isinstance(state, dict) else {}
    for key in ("revision", "configuration"):
        application_value = str(ctx.get(key) or "").strip()
        viewport_value = str(state.get(key) or viewport.get(key) or "").strip() if isinstance(viewport, dict) else ""
        if application_value and viewport_value and application_value != viewport_value:
            conflicts.append({
                "type": f"active_{key}_conflict",
                "application": application_value,
                "viewport": viewport_value,
            })

    relationships = compiled.get("mate_relationships")
    if isinstance(relationships, list):
        seen: set[tuple[str, str, str]] = set()
        duplicate_count = 0
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            endpoints = sorted([
                str(relationship.get("component1") or relationship.get("component1FileName") or ""),
                str(relationship.get("component2") or relationship.get("component2FileName") or ""),
            ])
            signature = (
                endpoints[0],
                endpoints[1],
                str(relationship.get("type") or relationship.get("mateType") or ""),
            )
            if signature in seen:
                duplicate_count += 1
            seen.add(signature)
        if duplicate_count:
            warnings.append({
                "type": "duplicate_mate_relationships",
                "count": duplicate_count,
            })
    return conflicts, warnings


def _prune_mode_and_viewport(
    compiled: dict[str, Any],
    *,
    include_motion: bool,
) -> None:
    mode_state = compiled.get("mode_state")
    if isinstance(mode_state, dict) and not include_motion:
        mode_state.pop("motion", None)
        if not mode_state:
            compiled.pop("mode_state", None)
    viewport = compiled.get("viewport_context")
    if isinstance(viewport, dict):
        allowed = {"state", "execution_receipts", "part_legend"}
        if include_motion:
            allowed.add("motion")
        compiled["viewport_context"] = {
            key: copy.deepcopy(value)
            for key, value in viewport.items()
            if key in allowed
        }


def compile_skill_context(
    ctx: Mapping[str, Any],
    packages: Iterable[Any],
    *,
    mode: str,
) -> CompiledContext:
    """Return only fields declared by the selected skills and base mode."""
    packages = tuple(packages)
    selected_skill_ids = {package.manifest.id for package in packages}
    required, optional = _manifest_context_keys(packages)
    derived_context: set[str] = set()
    if (
        {"trace-assembly-impact", "reason-about-assembly-context"} & selected_skill_ids
        and ctx.get("functional_relationships")
    ):
        # Functional relationships are a reviewed derivative of assembly
        # evidence, not a replacement for the selected skills' declared CAD
        # part/mate providers. Keep it optional until the v1 skill manifests
        # are versioned for a broader catalog rollout.
        optional.add("assembly.functional_relationships")
        derived_context.add("assembly.functional_relationships")
    contract_policy = _contract_policy(packages)
    requested = required | optional
    selected_fields = set(_ALWAYS_FIELDS)
    for context_key in requested:
        selected_fields.update(_CONTEXT_FIELDS.get(context_key, set()))

    compiled = {
        key: copy.deepcopy(value)
        for key, value in ctx.items()
        if key in selected_fields and value not in (None, "", [], {})
    }
    compiled["_compiled_prompt"] = True
    include_motion = bool(
        {"reason-about-motion", "control-cad-viewport"} & selected_skill_ids
        or "motion.groups" in required
    )
    _prune_mode_and_viewport(compiled, include_motion=include_motion)

    if "assembly.mates" in requested and "mate_relationships" in compiled:
        compiled["mate_relationships"] = _filter_direct_mates(
            ctx, compiled["mate_relationships"]
        )
        if not compiled["mate_relationships"]:
            compiled.pop("mate_relationships", None)

    provenance: list[dict[str, Any]] = []
    fai_rows = compiled.get("fai_characteristics")
    if isinstance(fai_rows, list):
        enriched_rows, diagnostics, provenance = _enrich_fai_rows(fai_rows)
        compiled["fai_characteristics"] = enriched_rows
        compiled["fai_table_summary"] = _fai_status_summary(enriched_rows)
        compiled["context_diagnostics"] = diagnostics
        fai_request = compiled.get("fai_request")
        target_ids = {
            str(value)
            for value in (
                fai_request.get("target_characteristic_ids")
                if isinstance(fai_request, dict) else []
            ) or []
        }
        if target_ids or {"trace-assembly-impact", "recommend-fai-disposition"} & selected_skill_ids:
            relevant = []
            for index, row in enumerate(enriched_rows):
                if not isinstance(row, dict):
                    continue
                row_id = _characteristic_id(row, index)
                if target_ids:
                    if row_id in target_ids:
                        relevant.append(row)
                elif str(row.get("status") or row.get("computed_status") or "").upper() in {"FAIL", "WARN"}:
                    relevant.append(row)
            if relevant:
                compiled["fai_characteristics"] = relevant
                relevant_ids = {
                    _characteristic_id(row, index)
                    for index, row in enumerate(relevant)
                }
                provenance = [
                    item for item in provenance
                    if str((item.get("source") or {}).get("characteristic_id") or "")
                    in relevant_ids
                    or any(
                        str(evidence_id).startswith(f"fai.{char_id}.")
                        for char_id in relevant_ids
                        for evidence_id in item.get("based_on", [])
                    )
                ]

        if target_ids and isinstance(compiled.get("affected_functional_interfaces"), list):
            compiled["affected_functional_interfaces"] = [
                item for item in compiled["affected_functional_interfaces"]
                if isinstance(item, dict)
                and str(item.get("characteristic_id") or "") in target_ids
            ]

    if "assembly.functional_relationships" in requested:
        functional_provenance = ctx.get("functional_relationship_provenance")
        if isinstance(functional_provenance, list):
            provenance.extend(
                copy.deepcopy(item)
                for item in functional_provenance
                if isinstance(item, dict)
            )

    missing_required = sorted(
        key for key in required if not _context_key_available(compiled, key)
    )
    diagnostics = compiled.setdefault(
        "context_diagnostics",
        {"schema_version": 1, "status": "ok", "conflicts": [], "warnings": []},
    )
    diagnostics["missing_required_context"] = missing_required
    identity_conflicts, identity_warnings = _identity_diagnostics(ctx, compiled)
    diagnostics["conflicts"].extend(identity_conflicts)
    diagnostics["warnings"].extend(identity_warnings)
    if diagnostics["conflicts"]:
        diagnostics["status"] = "error"
    elif diagnostics["warnings"] and diagnostics.get("status") == "ok":
        diagnostics["status"] = "warning"
    if missing_required and diagnostics.get("status") == "ok":
        diagnostics["status"] = "warning"
    if diagnostics.get("status") == "ok":
        compiled.pop("context_diagnostics", None)

    budget = _apply_context_budget(
        compiled,
        required=required,
        optional=optional,
        maximum_tokens=contract_policy["maximum_tokens"],
        priorities=contract_policy["priorities"],
    )
    if budget["budget_exceeded"]:
        diagnostics["warnings"].append({
            "type": "required_context_exceeds_budget",
            "estimated_tokens": budget["estimated_tokens"],
            "maximum_tokens": budget["maximum_tokens"],
        })
        if diagnostics.get("status") == "ok":
            diagnostics["status"] = "warning"
        compiled["context_diagnostics"] = diagnostics

    serialized = json.dumps(compiled, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    original = json.dumps(dict(ctx), sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    accounting = {
        "schema_version": 2,
        "mode": mode,
        "required_context": sorted(required),
        "optional_context": sorted(optional),
        "derived_context": sorted(derived_context),
        "included_fields": sorted(compiled),
        "original_chars": len(original),
        "compiled_chars": len(serialized),
        "reduction_ratio": round(1.0 - (len(serialized) / max(1, len(original))), 4),
        "context_sha256": hashlib.sha256(serialized.encode("ascii")).hexdigest(),
        "context_status": diagnostics.get("status"),
        "conflict_count": len(diagnostics.get("conflicts") or []),
        "warning_count": len(diagnostics.get("warnings") or []),
        "missing_required_context": missing_required,
        "provenance_count": len(provenance),
        "provenance_sha256": hashlib.sha256(
            json.dumps(
                provenance,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).hexdigest(),
        "contract_policy": contract_policy,
        "budget": budget,
    }
    return CompiledContext(
        context=compiled,
        accounting=accounting,
        provenance=tuple(provenance),
    )
