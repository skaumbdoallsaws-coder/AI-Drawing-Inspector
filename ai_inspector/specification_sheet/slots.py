"""Specification-sheet slots (docs/specification-sheet-slots-plan.md).

Every text on the page is a slot: a value and where it came from. The page's defaults come from the reviewed
profile and its evidence, the machine type's approved template, the library record and the CAD; values the user or
Sage gives are stored here and win over the defaults on every rebuild. A slot with no value is open.
"""
from __future__ import annotations

import copy
import json
import os
import re
import threading
from functools import wraps
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from ai_inspector.documentation.commands import (
    DocumentEditError, transaction_defaults, validate_transaction_metadata, document_id,
    request_hash, prior_receipt, check_preconditions, make_receipt, retain_receipt,
)

from ai_inspector.documentation.changes import (
    record as change_record, slot_paths, inverse as inverse_change, restore as restore_change,
    find_change, inspect_change, history_choices, validate_record, MAX_CHANGES,
)

SLOT_SCHEMA_VERSION = 3
# Storage metadata does not change the generated sheet's layout/source plan.
SLOT_LAYOUT_VERSION = 1
_SLOT_LOCK = threading.RLock()
TEMPLATE_SCHEMA_VERSION = 1
FEATURE_COUNT = 3
MAX_ROWS = 14
MAX_VALUE = 600
MAX_LABEL = 80
UNITS = ("imperial", "metric")

# Where a value came from. The first group are the page's defaults, the second are stored values.
DEFAULT_SOURCES = ("layout", "profile", "evidence", "library", "template", "cad")
STORED_SOURCES = ("research", "chat", "workspace", "sage_draft", "returned_pdf")
PROTECTED_SOURCES = frozenset({"cad", "evidence"})
UNREVIEWED_SOURCES = frozenset({"research", "sage_draft"})
SOURCE_LABELS = {
    "layout": "page wording",
    "profile": "reviewed profile",
    "evidence": "approved evidence",
    "library": "library record",
    "template": "type template",
    "cad": "CAD",
    "research": "public source, unreviewed",
    "chat": "you, in chat",
    "workspace": "you, in the viewport",
    "sage_draft": "Sage draft, unreviewed",
    "returned_pdf": "returned fillable PDF",
}

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,47}$")
PROSE_SLOTS = (
    "kicker", "title", "tagline", "caption", "specifications.heading", "features.heading",
    *(f"feature.{index}.{part}" for index in range(1, FEATURE_COUNT + 1) for part in ("title", "text")),
)
_ROW_SLOT_RE = re.compile(r"^spec\.([a-z0-9][a-z0-9_]{0,47})\.(label|value)$")
_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,180}$")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")

# Rows the CAD can fill, with the app's own labels for sheets that have no template.
CAD_ROWS = {
    "overall_dimensions": {"label": "Overall dimensions (W x D x H)", "hint": "from the CAD model's extents"},
    "weight": {"label": "Weight", "hint": "from the CAD when every part has a material"},
}



def _slot_identities(state):
    """Slot keys already are persistent IDs. Retain deleted row keys for recovery."""
    active = {"slot:" + key for key in PROSE_SLOTS}
    active.update("slot:" + key for key in state.get("values", {}))
    for row in state.get("rows") or []:
        active.update("slot:spec." + row["key"] + "." + field for field in ("label", "value"))
    identities = state.setdefault("identities", {})
    for item in state.get("journal", []):
        for change in item.get("changes", []):
            address = change["path"]
            if address[0] in {"values", "fieldMeta"} and len(address) == 2:
                key = address[1] if address[0] == "fieldMeta" else "slot:" + address[1]
                identities.setdefault(key, {"id": key})
            if address == ["rows"]:
                for side in ("before", "after"):
                    for row in change[side].get("value") or []:
                        for field in ("label", "value"):
                            key = "slot:spec." + row["key"] + "." + field
                            identities.setdefault(key, {"id": key})
    for key in active:
        identities.setdefault(key, {"id": key})
    for key, value in identities.items():
        value["state"] = "active" if key in active else "tombstone"


class SpecificationSlotError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def row_key(label: Any, taken: Iterable[str] = ()) -> str:
    """A stable key for a row from its label: 'Rated Capacity' is rated_capacity."""
    key = re.sub(r"[^a-z0-9]+", "_", str(label or "").casefold()).strip("_")[:40] or "row"
    if not key[0].isalnum():
        key = "row_" + key
    taken = set(taken)
    candidate, number = key, 2
    while candidate in taken:
        candidate, number = f"{key}_{number}", number + 1
    return candidate


def parse_slot(slot: Any) -> tuple[str, Optional[str], Optional[str]]:
    """('prose', None, None) for a page text, ('row', key, 'label'|'value') for a specification cell."""
    text = str(slot or "")
    if text in PROSE_SLOTS:
        return "prose", None, None
    match = _ROW_SLOT_RE.fullmatch(text)
    if match:
        return "row", match.group(1), match.group(2)
    raise SpecificationSlotError(f"unknown specification-sheet slot: {text[:60]}")


def slot_name(slot: str, labels: Mapping[str, str]) -> str:
    """What the user calls the slot: 'Spindle speed value', 'Feature 2 text'."""
    kind, key, part = parse_slot(slot)
    if kind == "row":
        label = labels.get(key) or key.replace("_", " ")
        return f"{label} {'name' if part == 'label' else 'value'}"
    if slot.startswith("feature."):
        _, index, part = slot.split(".")
        return f"Feature {index} {part}"
    return {"specifications.heading": "Specifications heading", "features.heading": "Features heading"}.get(
        slot, slot.capitalize())


def numbers_in(text: Any) -> List[str]:
    return [value.replace(",", "") for value in _NUMBER_RE.findall(str(text or ""))]


def unsupported_numbers(text: Any, sheet_texts: Iterable[Any]) -> List[str]:
    """Numbers in a draft that no value on the sheet has: a draft may only restate figures already on the page."""
    known = {number for value in sheet_texts for number in numbers_in(value)}
    return sorted({number for number in numbers_in(text) if number not in known})


def _clean(value: Any, limit: int, label: str) -> str:
    lines = str(value or "").replace("\r", "").split("\n")
    text = "\n".join(" ".join(line.split()) for line in lines).strip()
    if len(text) > limit:
        raise SpecificationSlotError(f"{label} is longer than {limit} characters")
    return text


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".tmp-{uuid.uuid4().hex}{path.suffix}")
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _write_bytes(path, (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpecificationSlotError(f"{path.name} is unreadable") from exc
    if not isinstance(payload, dict):
        raise SpecificationSlotError(f"{path.name} must be an object")
    return payload


def clean_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    key = str(row.get("key") or "")
    if not KEY_RE.fullmatch(key):
        raise SpecificationSlotError(f"invalid row key: {key[:60]}")
    label = _clean(row.get("label"), MAX_LABEL, "a row name")
    if not label:
        raise SpecificationSlotError("a row needs a name")
    result = {"key": key, "label": label}
    if row.get("source") in ("workspace", "chat"):
        result["source"] = row["source"]
    if row.get("provisional") is True:
        result["provisional"] = True
    for field, limit in (("unit", 24), ("hint", 160)):
        value = _clean(row.get(field), limit, f"a row {field}")
        if value:
            result[field] = value
    return result


def _slot_mutation(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with _SLOT_LOCK:
            if self._candidate is not None:
                return method(self, *args, **kwargs)
            return self.transaction(lambda store: method(store, *args, **kwargs))
    return wrapped


def _slot_semantics(data):
    if isinstance(data, dict):
        return {k: _slot_semantics(v) for k, v in data.items() if k not in {"at", "updatedAt"}}
    if isinstance(data, list):
        return [_slot_semantics(v) for v in data]
    return data


class SlotStore:
    """One sheet's stored values, row list, machine type and units: <root>/<assembly>/slots.json."""

    transaction_lock = _SLOT_LOCK

    def __init__(self, root: str | Path, assembly_number: str):
        self._candidate = None
        self.last_receipt = None
        self.provenance_defaults = {}
        self.provenance_values = {}
        number = str(assembly_number or "").strip()
        if not _SAFE_RE.fullmatch(number):
            raise SpecificationSlotError("invalid specification-sheet assembly number")
        self.assembly_number = number
        base = Path(root).resolve()
        # Resolve the assembly folder, never slots.json itself: while another writer replaces the file, Windows can
        # resolve it to its \\?\ form, which then fails the containment check (the scene store does the same).
        directory = (base / number.lower()).resolve()
        directory.relative_to(base)
        self.path = directory / "slots.json"

    def read(self) -> Dict[str, Any]:
        if self._candidate is not None:
            return copy.deepcopy(self._candidate)
        payload = _read_json(self.path) or {}
        version = payload.get("schemaVersion", 1)
        if version not in {1, 2, SLOT_SCHEMA_VERSION}:
            raise DocumentEditError("unsupported_document_schema", "This slot store needs a newer editor.")
        values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
        rows = payload.get("rows") if isinstance(payload.get("rows"), list) else None
        result = {
            "schemaVersion": SLOT_SCHEMA_VERSION,
            "assemblyNumber": self.assembly_number,
            "values": {slot: dict(item) for slot, item in values.items() if isinstance(item, dict)},
            "rows": [dict(row) for row in rows if isinstance(row, dict)] if rows is not None else None,
            "type": payload.get("type") if isinstance(payload.get("type"), dict) else None,
            "units": payload.get("units") if payload.get("units") in UNITS else None,
            "updatedAt": payload.get("updatedAt"),
        }
        for key in ("editRevision", "editEpoch", "fieldVersions", "fieldMeta", "receipts", "receiptOrder", "conflicts", "journal", "identities"):
            if key in payload:
                result[key] = copy.deepcopy(payload[key])
        transaction_defaults(result)
        result.setdefault("journal", [])
        if not isinstance(result["journal"], list) or len(result["journal"]) > MAX_CHANGES:
            raise DocumentEditError("unsupported_document_schema", "Invalid slot change history.")
        for item in result["journal"]:
            validate_record(item, {"values", "fieldMeta", "rows", "type", "units"})
        _slot_identities(result)
        validate_transaction_metadata(result)
        return result

    def _save(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if self._candidate is None:
            raise RuntimeError("Slot writes require a transaction")
        self._candidate = copy.deepcopy(data)
        return self.read()

    def transaction(self, change, *, expected_revision=None, request_id=None,
                    expected_hashes=None, current_hashes=None, payload=None, actor="user",
                    _restore_meta=False, _inverse_of=None):
        """Stage every nested row/value/settings change and replace slots once."""
        with _SLOT_LOCK:
            if self._candidate is not None:
                return change(self)
            before = self.read()
            self.last_receipt = None
            payload_hash = None
            if request_id is not None:
                payload_hash = request_hash(request_id, {"payload": payload, "actor": actor})
                prior = prior_receipt(before, request_id, payload_hash)
                if prior is not None:
                    self.last_receipt = prior
                    return {"storedSlots": prior["changedIds"], "retried": True}
                check_preconditions(before, expected_revision, expected_hashes or {}, current_hashes or {})
            self._candidate = copy.deepcopy(before)
            try:
                result = change(self)
                candidate = self._candidate
                changed = ["slot:" + key for key in set(before["values"]) | set(candidate["values"])
                           if _slot_semantics(before["values"].get(key)) != _slot_semantics(candidate["values"].get(key))]
                structural = any(before[key] != candidate[key] for key in ("rows", "type", "units"))
                if structural:
                    changed.append("@sheet")
                changed.extend(key for key in set(before["fieldMeta"]) | set(candidate["fieldMeta"])
                    if before["fieldMeta"].get(key) != candidate["fieldMeta"].get(key) and key not in changed)
                changed.sort()
                if changed and payload_hash is None:
                    request_id = "slot-" + uuid.uuid4().hex
                    expected_revision = before["editRevision"]
                    payload_hash = request_hash(request_id, {"changed": changed, "actor": actor})
                if payload_hash is not None:
                    self.last_receipt = make_receipt(before, request_id=request_id, payload_hash=payload_hash,
                        document=document_id("product_specification_sheet", self.assembly_number),
                        expected_revision=expected_revision, changed=changed, undoable=True)
                if not changed and payload_hash is None:
                    return result
                if changed:
                    from ai_inspector.documentation.provenance import slot_mutation_meta
                    if not _restore_meta:
                        slot_mutation_meta(before, candidate, self.provenance_defaults, effective_values=self.provenance_values, actor=actor,
                            change_id=self.last_receipt["changeId"])
                    for key in changed:
                        meta = candidate["fieldMeta"].get(key)
                        if _restore_meta and not _inverse_of and meta and meta.get("confirmation"):
                            meta.update(changeId=self.last_receipt["changeId"], actor=actor)
                            meta["confirmation"].update(changeId=self.last_receipt["changeId"], at=now())
                    item = change_record(before, candidate, slot_paths(before, candidate),
                        change_id=self.last_receipt["changeId"], actor=actor, created_at=now(),
                        version_keys=changed, inverse_of=_inverse_of)
                    item["binding"] = copy.deepcopy(getattr(self, "binding", {}))
                    candidate["journal"].append(item)
                    if len(candidate["journal"]) > MAX_CHANGES:
                        raise DocumentEditError("document_history_full", "The slot change history is full.")
                    candidate["editRevision"] = before["editRevision"] + 1
                    for key in set(changed) | {"@sheet"}:
                        candidate["fieldVersions"][key] = before["fieldVersions"].get(key, 0) + 1
                    candidate["updatedAt"] = now()
                if self.last_receipt is not None:
                    retain_receipt(candidate, self.last_receipt)
                _slot_identities(candidate)
                validate_transaction_metadata(candidate)
                if len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) > 16 * 1024 * 1024:
                    raise DocumentEditError("document_history_full", "The slot change history exceeds its storage limit.")
                if self.path.is_file():
                    original = self.path.read_bytes()
                    old_version = json.loads(original).get("schemaVersion", 1)
                    if old_version in {1, 2}:
                        backup = self.path.with_name(f"slots.v{old_version}.json")
                        if backup.exists() and backup.read_bytes() != original:
                            raise DocumentEditError("legacy_store_changed", "The slot rollback input changed.")
                        if not backup.exists():
                            # Preserve bytes, not a reserialized JSON copy.
                            _write_bytes(backup, original)
                _write_json(self.path, candidate)
                # Preserve existing return shapes while returning the committed
                # projection for methods that traditionally returned the store.
                if isinstance(result, dict) and "schemaVersion" in result and "values" in result:
                    result = copy.deepcopy(candidate)
                return result
            finally:
                self._candidate = None

    def inspect_change(self, change_id):
        with _SLOT_LOCK:
            return inspect_change(self.read()["journal"], change_id,
                document_id("product_specification_sheet", self.assembly_number))

    def undo_change(self, change_id, *, expected_revision, request_id, actor="sage"):
        with _SLOT_LOCK:
            before = self.read()
            payload = {"changeId": change_id, "expectedRevision": expected_revision}
            prior = prior_receipt(before, request_id, request_hash(request_id, {"payload": payload, "actor": actor}))
            if prior is not None:
                self.last_receipt = prior
                return {"receipt": prior}
            if type(expected_revision) is not int or not 0 <= expected_revision <= before["editRevision"]:
                raise DocumentEditError("stale_revision", "Read the current document revision.")
            chosen = find_change(before["journal"], change_id)
            if chosen.get("binding") and chosen["binding"] != getattr(self, "binding", {}):
                raise DocumentEditError("undo_conflict", "The sheet's source binding changed.", changeId=change_id)
            item = inverse_change(before, chosen, change_id="pending", actor=actor, created_at=now())
            def apply(store):
                candidate = store.read()
                restore_change(candidate, item["changes"])
                return store._save(candidate)
            self.transaction(apply, expected_revision=expected_revision, request_id=request_id,
                expected_hashes={"change": "matched"}, current_hashes={"change": "matched"},
                payload=payload, actor=actor, _restore_meta=True, _inverse_of=change_id)
            return {"receipt": self.last_receipt}

    def confirm_values(self, targets, *, by, expected_revision, request_id, expected_hashes, current_hashes, payload):
        from ai_inspector.documentation.provenance import confirmation_command
        def confirm(store):
            candidate = store.read()
            for target in targets:
                candidate["fieldMeta"].update(confirmation_command(target, by=by)["fieldMeta"])
            return store._save(candidate)
        return self.transaction(confirm, expected_revision=expected_revision, request_id=request_id,
            expected_hashes=expected_hashes, current_hashes=current_hashes, payload=payload,
            actor="user", _restore_meta=True)

    def move_history(self, *, expected_revision, direction):
        with _SLOT_LOCK:
            before = self.read()
            if expected_revision != before["editRevision"]:
                raise DocumentEditError("stale_revision", "Read the current document revision.")
            undo, redo = history_choices(before["journal"])
            choices = undo if direction == "undo" else redo if direction == "redo" else []
            if not choices:
                raise DocumentEditError("change_not_found", "There is no slot change to " + direction + ".")
            return self.undo_change(choices[-1], expected_revision=expected_revision,
                request_id="slot-history-" + uuid.uuid4().hex, actor="user")

    def apply_batch(self, items, source, *, expected_revision, request_id, expected_hashes,
                    current_hashes, payload=None, actor="sage"):
        items = list(items)
        if not 1 <= len(items) <= 12:
            raise DocumentEditError("invalid_document_operation", "Submit 1-12 slot values.")
        if len({item.get("slot") for item in items}) != len(items):
            raise DocumentEditError("invalid_document_operation", "Each slot may occur only once in a batch.")
        if set(expected_hashes) != {"slot:" + str(item.get("slot")) for item in items}:
            raise DocumentEditError("document_read_required", "Every slot requires its observed hash.")
        self.transaction(lambda store: store.set_values(items, source), expected_revision=expected_revision,
                         request_id=request_id, expected_hashes=expected_hashes, current_hashes=current_hashes,
                         payload=payload if payload is not None else {"items": items, "source": source,
                             "expectedRevision": expected_revision, "hashes": expected_hashes}, actor=actor)
        return {"receipt": self.last_receipt, "changed": self.last_receipt["changedIds"]}

    @_slot_mutation
    def set_values(self, items: Iterable[Mapping[str, Any]], source: str) -> Dict[str, Any]:
        """Store values, or clear them (an empty value goes back to the page's default)."""
        if source not in STORED_SOURCES:
            raise SpecificationSlotError(f"values cannot be stored from {source}")
        data = self.read()
        for item in items:
            slot = str(item.get("slot") or "")
            kind, _key, part = parse_slot(slot)
            limit = MAX_LABEL if part == "label" else MAX_VALUE
            value = _clean(item.get("value"), limit, slot_name(slot, {}))
            if not value:
                data["values"].pop(slot, None)
                continue
            entry = {"value": value, "source": source, "at": now()}
            for field in ("quote", "citation"):
                if item.get(field):
                    entry[field] = copy.deepcopy(item[field])
            data["values"][slot] = entry
        return self._save(data)

    @_slot_mutation
    def accept(self, slots: Iterable[str], by: str) -> List[str]:
        data = self.read()
        accepted = []
        for slot in slots:
            entry = data["values"].get(slot)
            if entry and entry.get("source") in UNREVIEWED_SOURCES and not entry.get("accepted"):
                entry["accepted"] = {"at": now(), "by": by}
                accepted.append(slot)
        if accepted:
            self._save(data)
        return accepted

    @_slot_mutation
    def set_rows(self, rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
        cleaned = [clean_row(row) for row in rows]
        keys = [row["key"] for row in cleaned]
        if len(set(keys)) != len(keys):
            raise SpecificationSlotError("two rows have the same key")
        if len(cleaned) > MAX_ROWS:
            raise SpecificationSlotError(f"a one-page sheet holds at most {MAX_ROWS} rows")
        data = self.read()
        data["rows"] = cleaned
        for slot in list(data["values"]):
            kind, key, _part = parse_slot(slot)
            if kind == "row" and key not in keys:
                data["values"].pop(slot)
        return self._save(data)

    @_slot_mutation
    def name_new_row(self, key: str, label: str) -> str:
        """A row added with a placeholder name takes its key from the first real name typed into it; its values
        move with it. Returns the row's key."""
        data = self.read()
        rows = data["rows"] or []
        row = next((item for item in rows if item.get("key") == key), None)
        if row is None or not row.get("provisional"):
            raise SpecificationSlotError(f"row {key[:60]} already has its name")
        label = _clean(label, MAX_LABEL, "a row name")
        if not label:
            raise SpecificationSlotError("a row needs a name")
        new_key = row_key(label, [item["key"] for item in rows if item is not row])
        row.pop("provisional", None)
        row.update({"key": new_key, "label": label})
        data["values"].pop(f"spec.{key}.label", None)
        for part in ("value",):
            entry = data["values"].pop(f"spec.{key}.{part}", None)
            if entry is not None:
                data["values"][f"spec.{new_key}.{part}"] = entry
        self._save(data)
        return new_key

    @_slot_mutation
    def reset_rows(self) -> Dict[str, Any]:
        """Back to the profile's or the template's rows; values for rows that remain are kept."""
        data = self.read()
        data["rows"] = None
        return self._save(data)

    @_slot_mutation
    def set_units(self, units: str) -> Dict[str, Any]:
        if units not in UNITS:
            raise SpecificationSlotError("units must be imperial or metric")
        data = self.read()
        data["units"] = units
        return self._save(data)

    @_slot_mutation
    def set_type(self, key: str, label: str, source: str) -> Dict[str, Any]:
        if not KEY_RE.fullmatch(str(key or "")):
            raise SpecificationSlotError("invalid machine type")
        data = self.read()
        data["type"] = {"key": key, "label": _clean(label, MAX_LABEL, "the type name") or key.replace("_", " "),
                        "source": source, "at": now()}
        return self._save(data)


class TemplateStore:
    """The specification names per machine type, approved once and reused: <root>/_templates/<type>.json."""

    def __init__(self, root: str | Path):
        self.root = (Path(root).resolve() / "_templates")

    def _path(self, key: str) -> Path:
        if not KEY_RE.fullmatch(str(key or "")):
            raise SpecificationSlotError("invalid machine type")
        return self.root / f"{key}.json"

    def get(self, key: Optional[str]) -> Optional[Dict[str, Any]]:
        if not key:
            return None
        return _read_json(self._path(key))

    def list(self) -> List[Dict[str, Any]]:
        if not self.root.is_dir():
            return []
        result = []
        for path in sorted(self.root.glob("*.json")):
            try:
                payload = _read_json(path)
            except SpecificationSlotError:
                continue
            if payload:
                result.append({"type": payload.get("type"), "label": payload.get("label"),
                               "approved": bool(payload.get("approved")),
                               "proposed": bool(payload.get("proposal")),
                               "rows": len(((payload.get("approved") or payload.get("proposal")) or {}).get("rows")
                                           or [])})
        return result

    def propose(self, key: str, label: str, rows: Iterable[Mapping[str, Any]], *, by: str,
                assembly_number: str, units: Optional[str] = None) -> Dict[str, Any]:
        cleaned = [clean_row(row) for row in rows]
        if not cleaned:
            raise SpecificationSlotError("a template needs at least one row")
        if len(cleaned) > MAX_ROWS:
            raise SpecificationSlotError(f"a one-page sheet holds at most {MAX_ROWS} rows")
        if len({row["key"] for row in cleaned}) != len(cleaned):
            raise SpecificationSlotError("two rows have the same key")
        path = self._path(key)
        payload = _read_json(path) or {"schemaVersion": TEMPLATE_SCHEMA_VERSION, "type": key, "approved": None}
        payload["label"] = _clean(label, MAX_LABEL, "the type name") or key.replace("_", " ")
        payload["proposal"] = {"rows": cleaned, "at": now(), "by": by, "forAssembly": assembly_number,
                               **({"units": units} if units in UNITS else {})}
        _write_json(path, payload)
        return payload

    def approve(self, key: str, *, by: str) -> Dict[str, Any]:
        path = self._path(key)
        payload = _read_json(path)
        if not payload or not payload.get("proposal"):
            raise SpecificationSlotError(f"there is no proposed template for {key} to approve")
        proposal = payload.pop("proposal")
        payload["approved"] = {**proposal, "approvedAt": now(), "approvedBy": by}
        payload["proposal"] = None
        _write_json(path, payload)
        return payload


def resolve(defaults: Mapping[str, Mapping[str, Any]], stored: Mapping[str, Mapping[str, Any]],
            order: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """Each slot's value: a stored value wins over the default; typing over the CAD or the evidence is kept and
    flagged. A slot with neither is open."""
    result: Dict[str, Dict[str, Any]] = {}
    for slot in order:
        default = defaults.get(slot) or {}
        entry = stored.get(slot)
        has_default = default.get("value") not in (None, "")
        if entry and entry.get("value") not in (None, ""):
            item = {"value": entry["value"], "source": entry["source"], "at": entry.get("at")}
            for field in ("quote", "citation", "accepted", "legacy"):
                if entry.get(field):
                    item[field] = copy.deepcopy(entry[field])
            if has_default and default.get("source") in PROTECTED_SOURCES and default["value"] != entry["value"]:
                item["overrides"] = {"value": default["value"], "source": default["source"]}
        elif has_default:
            item = {"value": default["value"], "source": default["source"]}
        else:
            item = {"value": None, "source": None}
        item["open"] = item["value"] in (None, "")
        item["unreviewed"] = item.get("source") in UNREVIEWED_SOURCES and not item.get("accepted")
        for field in ("hint", "claimIds"):
            if default.get(field):
                item[field] = copy.deepcopy(default[field])
        if has_default:
            item["default"] = {"value": default["value"], "source": default["source"]}
        result[slot] = item
    return result
