"""Isolated SQLite documents with optimistic revisions and atomic Undo/Redo."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4
from pydantic import TypeAdapter, ValidationError

from .geometry import assess, digest
from .models import Design, Product, MassCalculation, Identity

SCHEMA_VERSION = 2
CREATE_ID = TypeAdapter(Identity)


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
            if version not in (0, 1, SCHEMA_VERSION):
                raise PackagingError("schema_unsupported", "This packaging store was created by an unsupported version.", 409)
            if version == 1:
                backup = self.root / ("packaging-before-v2-" + uuid4().hex + ".sqlite3")
                with sqlite3.connect(backup) as target:
                    db.backup(target)
            db.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    scope TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL,
                    design TEXT NOT NULL, past TEXT NOT NULL, future TEXT NOT NULL,
                    updated TEXT NOT NULL, PRIMARY KEY(scope,id));
                CREATE TABLE IF NOT EXISTS receipts (
                    scope TEXT NOT NULL, document_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, result TEXT NOT NULL,
                    PRIMARY KEY(scope,document_id,request_id));
                CREATE TABLE IF NOT EXISTS create_receipts (
                    scope TEXT NOT NULL, request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, result TEXT NOT NULL,
                    PRIMARY KEY(scope,request_id));
                CREATE TABLE IF NOT EXISTS sources (
                    scope TEXT NOT NULL, id TEXT NOT NULL, metadata TEXT NOT NULL,
                    glb BLOB NOT NULL, PRIMARY KEY(scope,id));
                CREATE TABLE IF NOT EXISTS quotes (
                    scope TEXT NOT NULL, document_id TEXT NOT NULL, id TEXT NOT NULL,
                    revision INTEGER NOT NULL, result TEXT NOT NULL,
                    PRIMARY KEY(scope,document_id,id));
                CREATE TABLE IF NOT EXISTS images (
                    scope TEXT NOT NULL, id TEXT NOT NULL, metadata TEXT NOT NULL,
                    png BLOB NOT NULL, PRIMARY KEY(scope,id));
                CREATE TABLE IF NOT EXISTS quote_attempts (
                    scope TEXT NOT NULL, document_id TEXT NOT NULL, id TEXT NOT NULL,
                    revision INTEGER NOT NULL, fingerprint TEXT NOT NULL, started TEXT NOT NULL,
                    finished TEXT, outcome TEXT NOT NULL, requests_sent INTEGER NOT NULL,
                    responses_received INTEGER NOT NULL, shipments_created INTEGER NOT NULL,
                    error_code TEXT, quote_id TEXT, PRIMARY KEY(scope,document_id,id));
                CREATE TABLE IF NOT EXISTS alternatives (
                    scope TEXT NOT NULL, document_id TEXT NOT NULL, id TEXT NOT NULL,
                    name TEXT NOT NULL, revision INTEGER NOT NULL, design TEXT NOT NULL,
                    created TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    PRIMARY KEY(scope,document_id,id), UNIQUE(scope,document_id,request_id));
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
        for package in design.packages:
            for graphic in package.graphics:
                if graphic.image_id and not db.execute("SELECT 1 FROM images WHERE scope=? AND id=?", (scope, graphic.image_id)).fetchone():
                    raise PackagingError("image_not_found", "Artwork is unavailable in this workspace.", 404)
        p = design.product
        if not p or not p.source_id:
            if p and p.mass_calculation:
                raise PackagingError("cad_evidence_required", "A density calculation requires imported closed-solid CAD volume.")
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
            raise PackagingError("cad_mass_unavailable", "Imported geometry does not provide verified material mass. Enter measured mass or a documented estimate.")
        if p.mass_calculation:
            volume = self._solid_volume(meta)
            if abs(volume - p.mass_calculation.volume_m3) > max(1e-12, volume * 1e-8):
                raise PackagingError("source_changed", "Mass calculation must use the imported closed-solid volume.")

    @staticmethod
    def _solid_volume(metadata):
        if (metadata.get("format") != "step" or metadata.get("physical_evidence", {}).get("volume_basis") != "closed_solid_brep"
                or not isinstance(metadata.get("volume_m3"), (int, float)) or metadata["volume_m3"] <= 0):
            raise PackagingError("cad_volume_unavailable", "This source has no verified closed-solid CAD volume.")
        return metadata["volume_m3"]

    def estimate_mass(self, scope, source_id, command):
        metadata = self.source_metadata(scope, source_id)
        if command.source_revision != metadata["source_revision"]:
            raise PackagingError("source_changed", "The imported source revision does not match.")
        calculation = MassCalculation(volume_m3=self._solid_volume(metadata), material=command.material, exclusions=command.exclusions)
        try:
            return Product(name=metadata["name"], dimensions_m=metadata["dimensions_m"], source_id=source_id,
                           source_revision=metadata["source_revision"], mass_basis="estimate",
                           mass_kg=calculation.volume_m3 * command.material.density_kg_m3,
                           mass_evidence=("Closed-solid STEP volume times " + command.material.name + " density. " + command.material.evidence)[:500],
                           mass_calculation=calculation).model_dump(mode="json")
        except ValidationError:
            raise PackagingError("mass_out_of_range", "The calculated product mass exceeds the supported packaging range. Review source units and material density.", 422) from None

    def create(self, scope, design=None, *, request_id=None):
        design = design or Design()
        if request_id is not None:
            try:
                CREATE_ID.validate_python(request_id)
            except ValidationError:
                raise PackagingError("request_id_invalid", "Use a bounded alphanumeric creation request ID.", 422) from None
        fingerprint = digest(design.model_dump(mode="json"))
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if request_id is not None:
                prior = db.execute("SELECT fingerprint,result FROM create_receipts WHERE scope=? AND request_id=?",
                                   (scope, request_id)).fetchone()
                if prior:
                    if prior[0] != fingerprint:
                        raise PackagingError("request_id_reused", "This request ID was already used for different content.")
                    return json.loads(prior[1])
            self._check_sources(db, scope, design)
            doc_id = "pkg_" + uuid4().hex
            db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?)", (scope, doc_id, 0, design.model_dump_json(), "[]", "[]", now()))
            result = self._result(self._row(db, scope, doc_id))
            if request_id is not None:
                db.execute("INSERT INTO create_receipts VALUES(?,?,?,?)", (scope, request_id, fingerprint, encode(result)))
            return result

    def validate_design(self, scope, design):
        with self.db() as db:
            self._check_sources(db, scope, design)
        return assess(design)

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
            return json.loads(db.execute("SELECT metadata FROM sources WHERE scope=? AND id=?", (scope, source_id)).fetchone()[0])

    def sources(self, scope):
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT metadata FROM sources WHERE scope=? ORDER BY rowid DESC LIMIT 200", (scope,))]

    def source(self, scope, source_id):
        with self.db() as db:
            row = db.execute("SELECT metadata,glb FROM sources WHERE scope=? AND id=?", (scope, source_id)).fetchone()
            if not row:
                raise PackagingError("source_not_found", "Product source not found.", 404)
            return json.loads(row[0]), bytes(row[1])

    def source_metadata(self, scope, source_id):
        with self.db() as db:
            row = db.execute("SELECT metadata FROM sources WHERE scope=? AND id=?", (scope, source_id)).fetchone()
            if row is None:
                raise PackagingError("source_not_found", "Product source not found.", 404)
            return json.loads(row[0])

    def store_image(self, scope, payload):
        from ai_inspector.facility_layout.decal_images import normalize_image
        try:
            png, metadata = normalize_image(payload)
        except ValueError as exc:
            raise PackagingError("image_invalid", str(exc), 422) from exc
        image_id = "img_" + sha256(png).hexdigest()[:32]
        metadata = {**metadata, "id": image_id}
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO images VALUES(?,?,?,?)", (scope, image_id, encode(metadata), png))
        return metadata

    def image(self, scope, image_id):
        with self.db() as db:
            row = db.execute("SELECT metadata,png FROM images WHERE scope=? AND id=?", (scope, image_id)).fetchone()
            if row is None:
                raise PackagingError("image_not_found", "Artwork is unavailable in this workspace.", 404)
            return json.loads(row[0]), bytes(row[1])

    def save_alternative(self, scope, doc_id, command):
        fingerprint = digest(command)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM alternatives WHERE scope=? AND document_id=? AND request_id=?", (scope, doc_id, command.request_id)).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise PackagingError("request_id_reused", "This request ID was already used for different content.")
                return self._alternative(prior)
            row = self._row(db, scope, doc_id)
            if row["revision"] != command.expected_revision:
                raise PackagingError("revision_conflict", "The document changed. Refresh before saving an alternative.")
            if db.execute("SELECT COUNT(*) FROM alternatives WHERE scope=? AND document_id=?", (scope, doc_id)).fetchone()[0] >= 20:
                raise PackagingError("alternative_limit", "A document supports at most 20 saved alternatives.", 422)
            design = command.design or Design.model_validate_json(row["design"])
            self._check_sources(db, scope, design)
            alt_id = "alt_" + uuid4().hex
            db.execute("INSERT INTO alternatives VALUES(?,?,?,?,?,?,?,?,?)", (scope, doc_id, alt_id, command.name, row["revision"], design.model_dump_json(), now(), command.request_id, fingerprint))
            return self._alternative(db.execute("SELECT * FROM alternatives WHERE scope=? AND document_id=? AND id=?", (scope, doc_id, alt_id)).fetchone())

    @staticmethod
    def _alternative(row):
        design = Design.model_validate_json(row["design"])
        validation = assess(design)
        costs = [p["materials_cost_usd"] for p in validation["packages"]]
        return {"id": row["id"], "name": row["name"], "base_revision": row["revision"], "created_at": row["created"],
                "design": design.model_dump(mode="json"), "assessment": validation,
                "comparison": {"carton_count": len(design.packages), "total_gross_kg": validation["total_gross_kg"],
                    "outer_volume_m3": sum(p.carton.outer_m[0] * p.carton.outer_m[1] * p.carton.outer_m[2] for p in design.packages),
                    "materials_cost_usd": round(sum(costs), 2) if costs and all(c is not None for c in costs) else None,
                    "shipping_cost_usd": None}}

    def alternatives(self, scope, doc_id):
        with self.db() as db:
            self._row(db, scope, doc_id)
            return [self._alternative(r) for r in db.execute("SELECT * FROM alternatives WHERE scope=? AND document_id=? ORDER BY rowid", (scope, doc_id))]

    def save_quotes(self, scope, doc_id, revision, result):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, scope, doc_id)
            if row["revision"] != revision:
                raise PackagingError("revision_conflict", "The package changed while rates were requested. Refresh and quote again.")
            quote_id = "quote_" + uuid4().hex
            db.execute("INSERT INTO quotes VALUES(?,?,?,?,?)", (scope, doc_id, quote_id, revision, encode(result)))
        return {**result, "id": quote_id, "revision": revision}

    def quote_history(self, scope, doc_id, *, account_ref=None, account_known=False):
        """Recent quotes. A quote is stale when the revision, the design hash it priced or, when the
        caller knows the configured account, the account changed. Quotes saved without a field fall
        back to the revision check."""
        with self.db() as db:
            row = self._row(db, scope, doc_id)
            current, design_hash = row["revision"], digest(Design.model_validate_json(row["design"]))
            history = []
            for r in db.execute("SELECT * FROM quotes WHERE scope=? AND document_id=? ORDER BY rowid DESC LIMIT 10", (scope, doc_id)):
                result = json.loads(r["result"])
                reason = None
                if r["revision"] != current:
                    reason = "revision_changed"
                elif "design_hash" in result and result["design_hash"] != design_hash:
                    reason = "design_changed"
                elif account_known and "account_ref" in result and result["account_ref"] != account_ref:
                    reason = "account_changed" if account_ref else "account_removed"
                history.append({**result, "id": r["id"], "revision": r["revision"], "stale": reason is not None,
                                **({"stale_reason": reason} if reason else {})})
            return history

    def find_quote(self, scope, doc_id, revision, fingerprint):
        """The latest saved quote with this exact fingerprint at this revision, or None."""
        with self.db() as db:
            self._row(db, scope, doc_id)
            for r in db.execute("SELECT * FROM quotes WHERE scope=? AND document_id=? AND revision=? ORDER BY rowid DESC LIMIT 50",
                                (scope, doc_id, revision)):
                result = json.loads(r["result"])
                if result.get("fingerprint") == fingerprint:
                    return {**result, "id": r["id"], "revision": r["revision"]}
        return None

    def begin_quote_attempt(self, scope, doc_id, revision, fingerprint):
        """Record a provider attempt before any request, so interrupted attempts stay visible."""
        attempt_id = "attempt_" + uuid4().hex
        with self.db() as db:
            self._row(db, scope, doc_id)
            db.execute("INSERT INTO quote_attempts VALUES(?,?,?,?,?,?,NULL,'running',0,0,0,NULL,NULL)",
                       (scope, doc_id, attempt_id, revision, fingerprint, now()))
        return attempt_id

    def finish_quote_attempt(self, scope, doc_id, attempt_id, outcome, counts, *, error_code=None, quote_id=None):
        with self.db() as db:
            db.execute("UPDATE quote_attempts SET finished=?, outcome=?, requests_sent=?, responses_received=?, "
                       "shipments_created=?, error_code=?, quote_id=? WHERE scope=? AND document_id=? AND id=?",
                       (now(), outcome, int(counts.get("requests_sent", 0)), int(counts.get("responses_received", 0)),
                        int(counts.get("shipments_created", 0)), error_code, quote_id, scope, doc_id, attempt_id))

    def quote_attempts(self, scope, doc_id, limit=20):
        """Provider attempts for this document, newest first; unfinished ones are reported as interrupted."""
        with self.db() as db:
            self._row(db, scope, doc_id)
            rows = db.execute("SELECT * FROM quote_attempts WHERE scope=? AND document_id=? ORDER BY rowid DESC LIMIT ?",
                              (scope, doc_id, limit)).fetchall()
            total = db.execute("SELECT COALESCE(SUM(shipments_created),0), COUNT(*), COALESCE(SUM(requests_sent - responses_received),0) "
                               "FROM quote_attempts WHERE scope=? AND document_id=?",
                               (scope, doc_id)).fetchone()
        def outcome(r):
            if r["outcome"] != "running":
                return r["outcome"]
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(r["started"])).total_seconds()
            # The provider budget is 65 s; anything older never finished (crash or forced exit).
            return "running" if age < 120 else "interrupted"

        attempts = [{"id": r["id"], "revision": r["revision"], "fingerprint": r["fingerprint"], "started": r["started"],
                     "finished": r["finished"], "outcome": outcome(r),
                     "requests_sent": r["requests_sent"], "responses_received": r["responses_received"],
                     "shipments_created": r["shipments_created"], "error_code": r["error_code"], "quote_id": r["quote_id"],
                     # Sent without a response (timeout, dropped connection): the provider may still have created shipments.
                     "unconfirmed_requests": r["requests_sent"] - r["responses_received"]}
                    for r in rows]
        return {"attempts": attempts, "total_shipments_created": total[0], "attempt_count": total[1],
                "total_unconfirmed_requests": total[2]}
