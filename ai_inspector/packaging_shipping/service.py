"""Isolated SQLite documents with optimistic revisions and atomic Undo/Redo."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .geometry import assess, digest
from .models import Design

SCHEMA_VERSION = 1


class PackagingError(Exception):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


class PackagingService:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "packaging.sqlite3"
        with self.db() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise PackagingError("schema_unsupported", "This packaging store was created by an unsupported version.", 409)
            db.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    scope TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL,
                    design TEXT NOT NULL, past TEXT NOT NULL, future TEXT NOT NULL,
                    updated TEXT NOT NULL, PRIMARY KEY(scope,id));
                CREATE TABLE IF NOT EXISTS receipts (
                    scope TEXT NOT NULL, document_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, result TEXT NOT NULL,
                    PRIMARY KEY(scope,document_id,request_id));
                CREATE TABLE IF NOT EXISTS sources (
                    scope TEXT NOT NULL, id TEXT NOT NULL, metadata TEXT NOT NULL,
                    glb BLOB NOT NULL, PRIMARY KEY(scope,id));
                CREATE TABLE IF NOT EXISTS quotes (
                    scope TEXT NOT NULL, document_id TEXT NOT NULL, id TEXT NOT NULL,
                    revision INTEGER NOT NULL, result TEXT NOT NULL,
                    PRIMARY KEY(scope,document_id,id));
            """)
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _row(self, db, scope, doc_id):
        row = db.execute("SELECT * FROM documents WHERE scope=? AND id=?", (scope, doc_id)).fetchone()
        if row is None:
            raise PackagingError("document_not_found", "Packaging document not found.", 404)
        return row

    def _result(self, row):
        design = Design.model_validate_json(row["design"])
        return {"id": row["id"], "schema_version": SCHEMA_VERSION, "units": {"length": "m", "mass": "kg", "up": "Y"},
                "revision": row["revision"], "design": design.model_dump(mode="json"),
                "updated_at": row["updated"], "can_undo": bool(json.loads(row["past"])),
                "can_redo": bool(json.loads(row["future"])), "assessment": assess(design)}

    def _check_sources(self, db, scope, design):
        p = design.product
        if not p or not p.source_id:
            if p and p.mass_basis == "cad":
                raise PackagingError("cad_evidence_required", "CAD mass requires an authorized extraction record; use measured or estimate for manual inputs.")
            return
        row = db.execute("SELECT metadata FROM sources WHERE scope=? AND id=?", (scope, p.source_id)).fetchone()
        if not row:
            raise PackagingError("source_not_found", "Product source is unavailable in this workspace.")
        meta = json.loads(row[0])
        if p.source_revision != meta["source_revision"] or any(abs(a - b) > 1e-8 for a, b in zip(p.dimensions_m, meta["dimensions_m"])):
            raise PackagingError("source_changed", "Imported product dimensions and revision cannot be changed to make it fit.")
        if p.mass_basis == "cad":
            raise PackagingError("cad_mass_unavailable", "A GLB does not provide verified CAD mass. Enter measured mass or a documented estimate.")

    def create(self, scope, design=None):
        design = design or Design()
        with self.db() as db:
            self._check_sources(db, scope, design)
            doc_id = "pkg_" + uuid4().hex
            db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?)", (scope, doc_id, 0, design.model_dump_json(), "[]", "[]", now()))
            return self._result(self._row(db, scope, doc_id))

    def list(self, scope):
        with self.db() as db:
            return [{"id": r["id"], "revision": r["revision"], "name": json.loads(r["design"])["name"], "updated_at": r["updated"]}
                    for r in db.execute("SELECT * FROM documents WHERE scope=? ORDER BY updated DESC LIMIT 200", (scope,))]

    def get(self, scope, doc_id, revision=None):
        with self.db() as db:
            row = self._row(db, scope, doc_id)
            if revision is not None and revision != row["revision"]:
                raise PackagingError("revision_conflict", "The document changed. Refresh before applying this operation.")
            return self._result(row)

    def change(self, scope, doc_id, command, action="edit"):
        if action not in {"edit", "undo", "redo"}:
            raise PackagingError("invalid_operation", "Unsupported packaging operation.", 400)
        fingerprint = digest({"action": action, "command": command.model_dump(mode="json")})
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT fingerprint,result FROM receipts WHERE scope=? AND document_id=? AND request_id=?",
                               (scope, doc_id, command.request_id)).fetchone()
            if prior:
                if prior[0] != fingerprint:
                    raise PackagingError("request_id_reused", "This request ID was already used for different content.")
                return json.loads(prior[1])
            row = self._row(db, scope, doc_id)
            if row["revision"] != command.expected_revision:
                raise PackagingError("revision_conflict", "The document changed. Refresh before applying this operation.")
            current, past, future = json.loads(row["design"]), json.loads(row["past"]), json.loads(row["future"])
            if action == "edit":
                design = command.design
                past, future = (past + [current])[-30:], []
            elif action == "undo":
                if not past:
                    raise PackagingError("nothing_to_undo", "No earlier edit is available.")
                design = Design.model_validate(past.pop())
                future = (future + [current])[-30:]
            else:
                if not future:
                    raise PackagingError("nothing_to_redo", "No edit is available to redo.")
                design = Design.model_validate(future.pop())
                past = (past + [current])[-30:]
            self._check_sources(db, scope, design)
            db.execute("UPDATE documents SET revision=?,design=?,past=?,future=?,updated=? WHERE scope=? AND id=?",
                       (row["revision"] + 1, design.model_dump_json(), encode(past), encode(future), now(), scope, doc_id))
            result = self._result(self._row(db, scope, doc_id))
            result["receipt"] = {"request_id": command.request_id, "action": action, "before_revision": row["revision"], "after_revision": result["revision"]}
            db.execute("INSERT INTO receipts VALUES(?,?,?,?,?)", (scope, doc_id, command.request_id, fingerprint, encode(result)))
            return result

    def store_source(self, scope, metadata, glb):
        source_id = "src_" + metadata["source_revision"][:32]
        metadata = deepcopy(metadata)
        metadata["id"] = source_id
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO sources VALUES(?,?,?,?)", (scope, source_id, encode(metadata), glb))
        return metadata

    def source(self, scope, source_id):
        with self.db() as db:
            row = db.execute("SELECT metadata,glb FROM sources WHERE scope=? AND id=?", (scope, source_id)).fetchone()
            if not row:
                raise PackagingError("source_not_found", "Product source not found.", 404)
            return json.loads(row[0]), bytes(row[1])

    def save_quotes(self, scope, doc_id, revision, result):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, scope, doc_id)
            if row["revision"] != revision:
                raise PackagingError("revision_conflict", "The package changed while rates were requested. Refresh and quote again.")
            quote_id = "quote_" + uuid4().hex
            db.execute("INSERT INTO quotes VALUES(?,?,?,?,?)", (scope, doc_id, quote_id, revision, encode(result)))
        return {**result, "id": quote_id, "revision": revision}

    def quote_history(self, scope, doc_id):
        with self.db() as db:
            current = self._row(db, scope, doc_id)["revision"]
            return [{**json.loads(r["result"]), "id": r["id"], "revision": r["revision"], "stale": r["revision"] != current}
                    for r in db.execute("SELECT * FROM quotes WHERE scope=? AND document_id=? ORDER BY rowid DESC LIMIT 10", (scope, doc_id))]
