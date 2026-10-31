"""Atomic revision-aware repository for illustrated parts manual plans."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import tempfile
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .catalog import build_scoped_bom
from .quality import audit_manual_plan, is_publishable_section_name
from .schema import (
    PARTS_MANUAL_SCHEMA_VERSION,
    PartsManualValidationError,
    default_section_visualization,
    require_valid_manual_plan,
)


_ASSEMBLY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
_SECTION_ID_RE = re.compile(r"^section-[0-9a-f]{8,32}$")
_WRITE_LOCK = threading.RLock()


class PartsManualRepositoryError(RuntimeError):
    pass


class PartsManualConflictError(PartsManualRepositoryError):
    def __init__(self, current_revision: str):
        self.current_revision = current_revision
        super().__init__("parts manual revision conflict")


class PartsManualSourceConflictError(PartsManualRepositoryError):
    def __init__(self, plan_source_revision: str, current_source_revision: str):
        self.plan_source_revision = plan_source_revision
        self.current_source_revision = current_source_revision
        super().__init__("parts manual source revision conflict")


class PartsManualNotFoundError(PartsManualRepositoryError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_manual_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def manual_plan_revision(value: Any) -> str:
    return hashlib.sha256(canonical_manual_bytes(value)).hexdigest()


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Optional[Path] = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=".tmp-",
            suffix=path.suffix,
            dir=str(path.parent),
        )
        temp_path = Path(temp_name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(6):
            try:
                os.replace(temp_path, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.03 * (2**attempt))
        temp_path = None
    except OSError as exc:
        raise PartsManualRepositoryError(f"failed to write parts manual: {exc}") from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


class PartsManualRepository:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _plan_path(self, assembly_number: str) -> Path:
        value = str(assembly_number or "").strip()
        if _ASSEMBLY_RE.fullmatch(value) is None:
            raise PartsManualNotFoundError("unknown assembly")
        directory = (self.root / value.lower()).resolve()
        try:
            directory.relative_to(self.root)
        except ValueError as exc:
            raise PartsManualNotFoundError("unknown assembly") from exc
        return directory / "manual-plan.json"

    @staticmethod
    def new_plan(
        assembly_number: str,
        source_revision: str,
        *,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "schemaVersion": PARTS_MANUAL_SCHEMA_VERSION,
            "assemblyNumber": str(assembly_number),
            "sourceRevision": str(source_revision),
            "title": str(title or f"{assembly_number} Illustrated Parts Manual"),
            # An unsaved empty plan must hash identically across GET and the
            # first mutation. Real timestamps are assigned on first save.
            "createdAt": None,
            "updatedAt": None,
            "documentControl": {
                "documentNumber": f"IPM-{str(assembly_number).upper()}-001",
                "revision": "A",
            },
            "excludedOccurrences": [],
            "sections": [],
        }

    @staticmethod
    def _normalize_section_visualizations(plan: Dict[str, Any]) -> None:
        """Backfill visualization defaults without weakening schema validation."""
        for section in plan.get("sections") or []:
            if not isinstance(section, dict):
                continue
            visualization = section.get("visualization")
            if visualization is None:
                section["visualization"] = default_section_visualization()
            elif isinstance(visualization, Mapping):
                normalized = default_section_visualization()
                normalized.update(copy.deepcopy(dict(visualization)))
                section["visualization"] = normalized

    def read(
        self,
        assembly_number: str,
        source_revision: str,
        *,
        known_occurrence_ids: Iterable[str] = (),
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        path = self._plan_path(assembly_number)
        if path.is_file():
            try:
                plan = json.loads(path.read_text("ascii"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise PartsManualRepositoryError(f"could not read parts manual: {exc}") from exc
        else:
            plan = self.new_plan(assembly_number, source_revision, title=title)
        self._normalize_section_visualizations(plan)
        source_current = plan.get("sourceRevision") == source_revision
        require_valid_manual_plan(
            plan,
            known_occurrence_ids=known_occurrence_ids if source_current else None,
        )
        return {
            "plan": copy.deepcopy(plan),
            "revision": manual_plan_revision(plan),
            "persisted": path.is_file(),
            "sourceCurrent": source_current,
        }

    @staticmethod
    def _assert_revision(current: Dict[str, Any], base_revision: str) -> None:
        revision = manual_plan_revision(current)
        if str(base_revision or "") != revision:
            raise PartsManualConflictError(revision)

    @staticmethod
    def _assert_source(current: Dict[str, Any], source_revision: str) -> None:
        plan_source = str(current.get("sourceRevision") or "")
        if plan_source != source_revision:
            raise PartsManualSourceConflictError(plan_source, source_revision)

    @staticmethod
    def _item_assignments(
        catalog: Iterable[Mapping[str, Any]],
        occurrence_ids: Iterable[str],
        existing: Iterable[Mapping[str, Any]] = (),
    ) -> List[Dict[str, Any]]:
        rows = build_scoped_bom(
            catalog,
            occurrence_ids,
            item_assignments=existing,
        )
        return [
            {"definitionId": row["definitionId"], "itemNumber": row["item"]}
            for row in rows
        ]

    def create_section(
        self,
        assembly_number: str,
        source_revision: str,
        *,
        base_revision: str,
        name: str,
        occurrence_ids: Iterable[str],
        catalog: Iterable[Mapping[str, Any]],
        parent_section_id: Optional[str] = None,
        source: str = "manual",
        confidence: Optional[float] = None,
        evidence: Iterable[str] = (),
        visualization: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        catalog_rows = list(catalog)
        known_ids = {str(row.get("occurrenceId")) for row in catalog_rows if row.get("occurrenceId")}
        with _WRITE_LOCK:
            loaded = self.read(
                assembly_number,
                source_revision,
                known_occurrence_ids=known_ids,
            )
            plan = loaded["plan"]
            self._assert_revision(plan, base_revision)
            self._assert_source(plan, source_revision)
            normalized_occurrence_ids = list(dict.fromkeys(str(value) for value in occurrence_ids if value))
            now = _utc_now()
            if not plan.get("createdAt"):
                plan["createdAt"] = now
            section_visualization = default_section_visualization()
            if visualization is not None:
                section_visualization.update(copy.deepcopy(dict(visualization)))
            section = {
                "sectionId": f"section-{secrets.token_hex(6)}",
                "name": str(name or "").strip(),
                "parentSectionId": parent_section_id,
                "occurrenceIds": normalized_occurrence_ids,
                "source": source,
                "confidence": confidence,
                "evidence": [str(value) for value in evidence if str(value).strip()],
                "includeInManual": True,
                "pageOrder": len(plan["sections"]) + 1,
                "itemAssignments": self._item_assignments(catalog_rows, normalized_occurrence_ids),
                "visualization": section_visualization,
                "allowSinglePartPage": False,
                "processOperationIds": [],
                "occurrenceOrder": list(normalized_occurrence_ids),
                "createdAt": now,
                "updatedAt": now,
            }
            plan["sections"].append(section)
            plan["updatedAt"] = now
            require_valid_manual_plan(plan, known_occurrence_ids=known_ids)
            _write_atomic(self._plan_path(assembly_number), canonical_manual_bytes(plan))
            return {
                "plan": copy.deepcopy(plan),
                "section": copy.deepcopy(section),
                "revision": manual_plan_revision(plan),
            }

    def apply_proposed_sections(
        self,
        assembly_number: str,
        source_revision: str,
        *,
        base_revision: str,
        catalog: Iterable[Mapping[str, Any]],
        candidates: Iterable[Mapping[str, Any]],
        candidate_ids: Iterable[str],
    ) -> Dict[str, Any]:
        """Approve trusted planner candidates in one validated, atomic write."""
        catalog_rows = list(catalog)
        known_ids = {
            str(row.get("occurrenceId"))
            for row in catalog_rows
            if row.get("occurrenceId")
        }
        candidate_by_id = {
            str(row.get("candidateId")): copy.deepcopy(dict(row))
            for row in candidates
            if isinstance(row, Mapping) and row.get("candidateId")
        }
        selected_ids = list(dict.fromkeys(str(value) for value in candidate_ids if value))
        if not selected_ids:
            raise PartsManualRepositoryError("select at least one ready manual-group candidate")
        unknown = [value for value in selected_ids if value not in candidate_by_id]
        if unknown:
            raise PartsManualRepositoryError("unknown manual-group proposal candidate")
        blocked = [
            value
            for value in selected_ids
            if candidate_by_id[value].get("status") != "ready"
        ]
        if blocked:
            raise PartsManualRepositoryError(
                "only conflict-free ready candidates can be approved"
            )

        with _WRITE_LOCK:
            loaded = self.read(
                assembly_number,
                source_revision,
                known_occurrence_ids=known_ids,
            )
            plan = loaded["plan"]
            self._assert_revision(plan, base_revision)
            self._assert_source(plan, source_revision)
            selected = {value: candidate_by_id[value] for value in selected_ids}
            ordered: List[Mapping[str, Any]] = []
            remaining = set(selected_ids)
            while remaining:
                progressed = False
                for candidate_id in selected_ids:
                    if candidate_id not in remaining:
                        continue
                    parent_candidate_id = str(
                        selected[candidate_id].get("parentCandidateId") or ""
                    )
                    if parent_candidate_id in remaining:
                        continue
                    ordered.append(selected[candidate_id])
                    remaining.remove(candidate_id)
                    progressed = True
                if not progressed:
                    raise PartsManualRepositoryError(
                        "manual-group proposal hierarchy contains a cycle"
                    )

            now = _utc_now()
            if not plan.get("createdAt"):
                plan["createdAt"] = now
            selected_occurrence_ids = {
                str(value)
                for candidate in selected.values()
                for value in candidate.get("occurrenceIds") or []
            }
            superseded_section_ids = {
                str(value)
                for candidate in selected.values()
                for value in candidate.get("supersedesSectionIds") or []
                if value
            }
            if superseded_section_ids:
                sections_by_id = {
                    str(row.get("sectionId")): row
                    for row in plan.get("sections") or []
                    if isinstance(row, Mapping) and row.get("sectionId")
                }
                for section_id in superseded_section_ids:
                    section = sections_by_id.get(section_id)
                    if section is None:
                        raise PartsManualRepositoryError(
                            "a replacement section no longer exists; refresh the proposal"
                        )
                    section_occurrences = {
                        str(value) for value in section.get("occurrenceIds") or []
                    }
                    if not section_occurrences <= selected_occurrence_ids:
                        raise PartsManualRepositoryError(
                            "select every proposed group required to replace the incomplete draft structure"
                        )
                remaining_parent_ids = {
                    str(row.get("parentSectionId"))
                    for row in plan.get("sections") or []
                    if row.get("parentSectionId")
                    and str(row.get("sectionId")) not in superseded_section_ids
                }
                if superseded_section_ids & remaining_parent_ids:
                    raise PartsManualRepositoryError(
                        "replace or remove child manual sections before superseding their parent"
                    )
                eligible_ids = {
                    str(row.get("occurrenceId"))
                    for row in catalog_rows
                    if row.get("kind") == "part"
                    and not row.get("suppressed")
                    and row.get("occurrenceId")
                }
                remaining_occurrence_ids = {
                    str(value)
                    for row in plan.get("sections") or []
                    if str(row.get("sectionId")) not in superseded_section_ids
                    and row.get("includeInManual", True)
                    for value in row.get("occurrenceIds") or []
                }
                excluded_ids = {
                    str(row.get("occurrenceId"))
                    for row in plan.get("excludedOccurrences") or []
                    if isinstance(row, Mapping) and row.get("occurrenceId")
                }
                unexplained = eligible_ids - selected_occurrence_ids - remaining_occurrence_ids - excluded_ids
                if unexplained:
                    raise PartsManualRepositoryError(
                        "select every proposed functional group so the replacement retains 100% component coverage"
                    )
                plan["sections"] = [
                    row
                    for row in plan.get("sections") or []
                    if str(row.get("sectionId")) not in superseded_section_ids
                ]
            section_id_by_candidate: Dict[str, str] = {}
            approved_sections: List[Dict[str, Any]] = []
            for candidate in ordered:
                candidate_id = str(candidate.get("candidateId") or "")
                occurrence_ids = list(
                    dict.fromkeys(
                        str(value)
                        for value in candidate.get("occurrenceIds") or []
                        if value
                    )
                )
                parent_candidate_id = str(
                    candidate.get("parentCandidateId") or ""
                )
                parent_section_id = (
                    section_id_by_candidate.get(parent_candidate_id)
                    or candidate.get("suggestedParentSectionId")
                    or None
                )
                section_id = f"section-{secrets.token_hex(6)}"
                evidence = []
                for value in candidate.get("evidence") or []:
                    if isinstance(value, Mapping):
                        detail = str(value.get("detail") or "").strip()
                        source_ref = str(value.get("sourceRef") or "").strip()
                        if detail and source_ref:
                            evidence.append(f"{detail} Source: {source_ref}")
                        elif detail or source_ref:
                            evidence.append(detail or source_ref)
                    elif str(value).strip():
                        evidence.append(str(value).strip())
                section = {
                    "sectionId": section_id,
                    "name": str(candidate.get("name") or "").strip(),
                    "parentSectionId": parent_section_id,
                    "occurrenceIds": occurrence_ids,
                    "source": str(candidate.get("source") or "inferred"),
                    "confidence": candidate.get("confidence"),
                    "evidence": evidence,
                    "includeInManual": True,
                    "pageOrder": len(plan["sections"]) + 1,
                    "itemAssignments": self._item_assignments(
                        catalog_rows,
                        occurrence_ids,
                    ),
                    "visualization": default_section_visualization(),
                    "allowSinglePartPage": False,
                    "processOperationIds": list(
                        dict.fromkeys(
                            str(value)
                            for value in candidate.get("processOperationIds") or []
                            if value
                        )
                    ),
                    "occurrenceOrder": [
                        str(value)
                        for value in candidate.get("occurrenceOrder") or occurrence_ids
                        if str(value) in set(occurrence_ids)
                    ],
                    "groupQuality": copy.deepcopy(candidate.get("groupQuality")),
                    "createdAt": now,
                    "updatedAt": now,
                }
                plan["sections"].append(section)
                approved_sections.append(section)
                section_id_by_candidate[candidate_id] = section_id

            plan["updatedAt"] = now
            require_valid_manual_plan(plan, known_occurrence_ids=known_ids)
            _write_atomic(
                self._plan_path(assembly_number),
                canonical_manual_bytes(plan),
            )
            return {
                "plan": copy.deepcopy(plan),
                "sections": copy.deepcopy(approved_sections),
                "approvedCandidateIds": selected_ids,
                "supersededSectionIds": sorted(superseded_section_ids),
                "revision": manual_plan_revision(plan),
            }

    def update_section(
        self,
        assembly_number: str,
        section_id: str,
        source_revision: str,
        *,
        base_revision: str,
        catalog: Iterable[Mapping[str, Any]],
        patch: Mapping[str, Any],
    ) -> Dict[str, Any]:
        if _SECTION_ID_RE.fullmatch(str(section_id or "")) is None:
            raise PartsManualNotFoundError("manual section not found")
        catalog_rows = list(catalog)
        known_ids = {str(row.get("occurrenceId")) for row in catalog_rows if row.get("occurrenceId")}
        with _WRITE_LOCK:
            loaded = self.read(assembly_number, source_revision, known_occurrence_ids=known_ids)
            plan = loaded["plan"]
            self._assert_revision(plan, base_revision)
            self._assert_source(plan, source_revision)
            section = next((row for row in plan["sections"] if row.get("sectionId") == section_id), None)
            if section is None:
                raise PartsManualNotFoundError("manual section not found")
            for key in ("name", "parentSectionId", "source", "confidence", "includeInManual", "pageOrder"):
                if key in patch:
                    section[key] = copy.deepcopy(patch[key])
            if "visualization" in patch:
                candidate = patch["visualization"]
                if isinstance(candidate, Mapping):
                    visualization = default_section_visualization()
                    if isinstance(section.get("visualization"), Mapping):
                        visualization.update(copy.deepcopy(dict(section["visualization"])))
                    visualization.update(copy.deepcopy(dict(candidate)))
                    section["visualization"] = visualization
                else:
                    section["visualization"] = copy.deepcopy(candidate)
            if "evidence" in patch:
                section["evidence"] = [str(value) for value in patch.get("evidence") or [] if str(value).strip()]
            if "occurrenceIds" in patch:
                occurrence_ids = list(dict.fromkeys(str(value) for value in patch.get("occurrenceIds") or [] if value))
                section["occurrenceIds"] = occurrence_ids
                previous_order = [
                    str(value)
                    for value in section.get("occurrenceOrder") or []
                    if str(value) in set(occurrence_ids)
                ]
                section["occurrenceOrder"] = previous_order + [
                    value for value in occurrence_ids if value not in set(previous_order)
                ]
                section["itemAssignments"] = self._item_assignments(
                    catalog_rows,
                    occurrence_ids,
                    section.get("itemAssignments") or [],
                )
            now = _utc_now()
            section["updatedAt"] = now
            plan["updatedAt"] = now
            require_valid_manual_plan(plan, known_occurrence_ids=known_ids)
            _write_atomic(self._plan_path(assembly_number), canonical_manual_bytes(plan))
            return {
                "plan": copy.deepcopy(plan),
                "section": copy.deepcopy(section),
                "revision": manual_plan_revision(plan),
            }

    def move_occurrences(
        self,
        assembly_number: str,
        source_revision: str,
        *,
        base_revision: str,
        catalog: Iterable[Mapping[str, Any]],
        moves: Iterable[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Move part occurrences to another manual section in one validated write.

        Each move is {"occurrenceIds": [...], "toSectionId": id} or, for a new
        section, {"occurrenceIds": [...], "newSectionName": name}. The parts
        leave every section other than the target and its ancestors; an
        ancestor that holds all of the target's parts gets them too. Item
        numbers are kept: a part keeps no number in the section it left and
        takes the first free number in the one it joined. Refused when a
        section would be left empty, or when a plan that passed the publication
        audit would fail it.
        """
        catalog_rows = list(catalog)
        known_ids = {str(row.get("occurrenceId")) for row in catalog_rows if row.get("occurrenceId")}
        part_ids = {
            str(row.get("occurrenceId"))
            for row in catalog_rows
            if row.get("occurrenceId") and row.get("kind") == "part" and not row.get("suppressed")
        }
        requested = [dict(row) for row in moves if isinstance(row, Mapping)]
        if not requested:
            raise PartsManualRepositoryError("name at least one part to move")
        with _WRITE_LOCK:
            loaded = self.read(assembly_number, source_revision, known_occurrence_ids=known_ids)
            plan = loaded["plan"]
            self._assert_revision(plan, base_revision)
            self._assert_source(plan, source_revision)
            audit_before = audit_manual_plan(plan, catalog_rows)
            sections = plan["sections"]
            by_id = {str(row.get("sectionId")): row for row in sections}
            before = {
                section_id: list(row.get("occurrenceIds") or [])
                for section_id, row in by_id.items()
            }
            now = _utc_now()
            created: List[str] = []
            moved: List[Dict[str, Any]] = []
            for move in requested:
                occurrence_ids = list(
                    dict.fromkeys(str(value) for value in move.get("occurrenceIds") or [] if value)
                )
                if not occurrence_ids:
                    raise PartsManualRepositoryError("a move names no parts")
                not_parts = [value for value in occurrence_ids if value not in part_ids]
                if not_parts:
                    raise PartsManualRepositoryError(
                        "not serviceable parts of this assembly: " + ", ".join(not_parts[:5])
                    )
                target_id = str(move.get("toSectionId") or "")
                new_name = re.sub(r"\s+", " ", str(move.get("newSectionName") or "")).strip()
                if bool(target_id) == bool(new_name):
                    raise PartsManualRepositoryError(
                        "move parts either to an existing section or to a new one"
                    )
                if new_name:
                    if not is_publishable_section_name(new_name):
                        raise PartsManualRepositoryError(
                            f"'{new_name}' is not a customer-facing section name"
                        )
                    if any(
                        str(row.get("name") or "").casefold() == new_name.casefold()
                        for row in sections
                    ):
                        raise PartsManualRepositoryError(
                            f"a section named '{new_name}' already exists; move the parts to it"
                        )
                    target_id = f"section-{secrets.token_hex(6)}"
                    section = {
                        "sectionId": target_id,
                        "name": new_name,
                        "parentSectionId": None,
                        "occurrenceIds": [],
                        "source": "manual",
                        "confidence": None,
                        "evidence": [],
                        "includeInManual": True,
                        "pageOrder": len(sections) + 1,
                        "itemAssignments": [],
                        "visualization": default_section_visualization(),
                        "allowSinglePartPage": False,
                        "processOperationIds": [],
                        "occurrenceOrder": [],
                        "createdAt": now,
                        "updatedAt": now,
                    }
                    sections.append(section)
                    by_id[target_id] = section
                    before[target_id] = []
                    created.append(target_id)
                target = by_id.get(target_id)
                if target is None:
                    raise PartsManualNotFoundError("manual section not found")
                ancestors: List[str] = []
                cursor = target.get("parentSectionId")
                while cursor and str(cursor) in by_id and str(cursor) not in ancestors:
                    ancestors.append(str(cursor))
                    cursor = by_id[str(cursor)].get("parentSectionId")
                target_parts = set(target.get("occurrenceIds") or [])
                moving = set(occurrence_ids)
                left: List[str] = []
                for section in sections:
                    section_id = str(section.get("sectionId"))
                    if section_id == target_id or section_id in ancestors:
                        continue
                    current = list(section.get("occurrenceIds") or [])
                    kept = [value for value in current if value not in moving]
                    if len(kept) != len(current):
                        section["occurrenceIds"] = kept
                        left.append(section_id)
                target["occurrenceIds"] = list(target.get("occurrenceIds") or []) + [
                    value for value in occurrence_ids if value not in target_parts
                ]
                for ancestor_id in ancestors:
                    ancestor = by_id[ancestor_id]
                    holds = set(ancestor.get("occurrenceIds") or [])
                    if target_parts and target_parts <= holds:
                        ancestor["occurrenceIds"] = list(ancestor.get("occurrenceIds") or []) + [
                            value for value in occurrence_ids if value not in holds
                        ]
                plan["excludedOccurrences"] = [
                    row
                    for row in plan.get("excludedOccurrences") or []
                    if not (isinstance(row, Mapping) and str(row.get("occurrenceId")) in moving)
                ]
                moved.append(
                    {
                        "occurrenceIds": occurrence_ids,
                        "fromSectionIds": left,
                        "toSectionId": target_id,
                        "alreadyThere": [value for value in occurrence_ids if value in target_parts],
                    }
                )

            changed = [
                section_id
                for section_id, row in by_id.items()
                if list(row.get("occurrenceIds") or []) != before.get(section_id)
            ]
            if not changed:
                raise PartsManualRepositoryError("the parts are already in that section")
            emptied = [by_id[section_id] for section_id in changed if not by_id[section_id]["occurrenceIds"]]
            if emptied:
                names = ", ".join(f"'{row.get('name')}'" for row in emptied)
                raise PartsManualRepositoryError(
                    f"the move would leave {names} with no parts; move other parts into it or delete it"
                )
            for section_id in changed:
                section = by_id[section_id]
                occurrence_ids = list(section["occurrenceIds"])
                previous_order = [
                    str(value)
                    for value in section.get("occurrenceOrder") or []
                    if str(value) in set(occurrence_ids)
                ]
                section["occurrenceOrder"] = previous_order + [
                    value for value in occurrence_ids if value not in set(previous_order)
                ]
                section["itemAssignments"] = self._item_assignments(
                    catalog_rows,
                    occurrence_ids,
                    section.get("itemAssignments") or [],
                )
                section["updatedAt"] = now
            plan["updatedAt"] = now
            require_valid_manual_plan(plan, known_occurrence_ids=known_ids)
            audit_after = audit_manual_plan(plan, catalog_rows)
            if audit_before["status"] == "PASS" and audit_after["status"] != "PASS":
                raise PartsManualValidationError(list(audit_after["findings"]))
            _write_atomic(self._plan_path(assembly_number), canonical_manual_bytes(plan))
            return {
                "plan": copy.deepcopy(plan),
                "revision": manual_plan_revision(plan),
                "previousRevision": str(base_revision),
                "changedSectionIds": changed,
                "createdSectionIds": created,
                "moves": moved,
                "publicationReadiness": audit_after,
            }

    def delete_section(
        self,
        assembly_number: str,
        section_id: str,
        source_revision: str,
        *,
        base_revision: str,
        known_occurrence_ids: Iterable[str],
    ) -> Dict[str, Any]:
        with _WRITE_LOCK:
            loaded = self.read(
                assembly_number,
                source_revision,
                known_occurrence_ids=known_occurrence_ids,
            )
            plan = loaded["plan"]
            self._assert_revision(plan, base_revision)
            self._assert_source(plan, source_revision)
            if not any(row.get("sectionId") == section_id for row in plan["sections"]):
                raise PartsManualNotFoundError("manual section not found")
            if any(row.get("parentSectionId") == section_id for row in plan["sections"]):
                raise PartsManualRepositoryError("delete child manual sections first")
            plan["sections"] = [row for row in plan["sections"] if row.get("sectionId") != section_id]
            plan["updatedAt"] = _utc_now()
            require_valid_manual_plan(plan, known_occurrence_ids=known_occurrence_ids)
            _write_atomic(self._plan_path(assembly_number), canonical_manual_bytes(plan))
            return {"plan": copy.deepcopy(plan), "revision": manual_plan_revision(plan)}
