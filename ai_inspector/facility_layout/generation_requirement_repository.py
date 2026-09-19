"""Typed generation-ledger heads over the existing design repository primitives.

This is server-side storage, not an authenticated tool or a write-lease owner.
The future admission adapter must authorize callers and validate their sources.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from .design_brief import design_revision
from .design_repository import (
    FacilityDesignRepository,
    FacilityDesignRepositoryIntegrityError,
    FacilityDesignRepositoryNotFoundError,
    _exists,
    _read_json,
    _timestamp,
    _walk_json_files,
)
from .generation_requirements import (
    GenerationRequirementError,
    MAX_LEDGER_REVISIONS,
    identifier,
    revision,
    validate_generation_amendment,
    validate_generation_ledger,
)


def _error(code: str, message: str) -> GenerationRequirementError:
    return GenerationRequirementError(code, message)


class GenerationRequirementRepository(FacilityDesignRepository):
    """Immutable ledgers, bounded CAS heads and durable, key-order-independent retry."""

    def list_source_context_refs(self, tenant_id, site_id, *, limit=64):
        root = self._scope(tenant_id, site_id) / "artifacts" / "generation-source-context"
        refs = []
        for path in _walk_json_files(root):
            if len(refs) >= limit:
                return {"refs": refs, "truncated": True}
            refs.append({"artifactKind": "generation-source-context", "artifactId": path.parent.name,
                         "artifactRevision": path.stem})
        return {"refs": refs, "truncated": False}

    def _ledger_root(self, tenant_id: str, site_id: str, ledger_id: str) -> Path:
        # Canonical IDs may contain colons or Windows device names. Never use
        # those strings as directory names or NTFS stream selectors.
        key = design_revision({"ledgerId": identifier(ledger_id, "ledgerId")})
        return self._scope(tenant_id, site_id) / "generation-ledgers" / key

    def _ledger_path(self, tenant_id: str, site_id: str, ledger_id: str, ledger_revision: str) -> Path:
        return self._ledger_root(tenant_id, site_id, ledger_id) / "revisions" / f"{revision(ledger_revision, 'ledgerRevision')}.json"

    def _ledger_head_path(self, tenant_id: str, site_id: str, ledger_id: str) -> Path:
        return self._ledger_root(tenant_id, site_id, ledger_id) / "head.json"

    def _read_ledger_head(self, tenant_id: str, site_id: str, ledger_id: str) -> dict[str, Any]:
        head = _read_json(self._ledger_head_path(tenant_id, site_id, ledger_id),
                          missing_code="generation_ledger_not_found")
        fields = {"recordKind", "ledgerId", "ledgerRevision", "commits", "headRevision"}
        if (set(head) != fields or head["recordKind"] != "generation_requirement_head"
                or head["ledgerId"] != ledger_id
                or head["headRevision"] != design_revision({key: value for key, value in head.items() if key != "headRevision"})):
            raise _error("generation_ledger_head_corrupt", "Generation ledger head failed its integrity check.")
        commits = head["commits"]
        if not isinstance(commits, list) or not 1 <= len(commits) <= MAX_LEDGER_REVISIONS:
            raise _error("generation_ledger_head_corrupt", "Generation ledger commit history is invalid.")
        keys, revisions = set(), set()
        for commit in commits:
            if not isinstance(commit, Mapping) or set(commit) != {"requestKey", "requestRevision", "ledgerRevision"}:
                raise _error("generation_ledger_head_corrupt", "Generation ledger retry receipt is invalid.")
            key = identifier(commit["requestKey"], "requestKey")
            digest = revision(commit["ledgerRevision"], "ledgerRevision")
            revision(commit["requestRevision"], "requestRevision")
            if key in keys or digest in revisions:
                raise _error("generation_ledger_head_corrupt", "Generation ledger commit identity is duplicated.")
            keys.add(key)
            revisions.add(digest)
        if head["ledgerRevision"] != commits[-1]["ledgerRevision"]:
            raise _error("generation_ledger_head_corrupt", "Generation ledger head does not match the last commit.")
        return head

    @staticmethod
    def _artifact_references(values: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
        if not isinstance(values, (tuple, list)) or len(values) > 64:
            raise _error("generation_ledger_artifact_refs_invalid", "Ledger artifact references exceed their bounds.")
        refs = []
        seen = set()
        for value in values:
            if not isinstance(value, Mapping) or set(value) != {"artifactKind", "artifactId", "artifactRevision"}:
                raise _error("generation_ledger_artifact_refs_invalid", "Invalid ledger artifact reference.")
            ref = {
                "artifactKind": identifier(value["artifactKind"], "artifactKind"),
                "artifactId": identifier(value["artifactId"], "artifactId"),
                "artifactRevision": revision(value["artifactRevision"], "artifactRevision"),
            }
            # Existing repository pins are indexed by revision, so ambiguity must be refused.
            if ref["artifactRevision"] in seen:
                raise _error("generation_ledger_artifact_refs_invalid", "Duplicate artifact revision in ledger pins.")
            seen.add(ref["artifactRevision"])
            refs.append(ref)
        return sorted(refs, key=lambda ref: (ref["artifactKind"], ref["artifactId"], ref["artifactRevision"]))

    def _read_ledger(self, tenant_id: str, site_id: str, ledger_id: str,
                     ledger_revision: str) -> dict[str, Any]:
        envelope = _read_json(self._ledger_path(tenant_id, site_id, ledger_id, ledger_revision),
                              missing_code="generation_ledger_revision_not_found")
        fields = {"recordKind", "ledger", "artifactRefs", "envelopeRevision"}
        if (set(envelope) != fields or envelope["recordKind"] != "generation_requirement_revision"
                or envelope["envelopeRevision"] != design_revision({key: value for key, value in envelope.items() if key != "envelopeRevision"})):
            raise _error("generation_ledger_record_corrupt", "Ledger envelope failed its integrity check.")
        record = validate_generation_ledger(envelope["ledger"])
        self._artifact_references(envelope["artifactRefs"])
        if (record["tenantId"], record["siteId"], record["ledgerId"], record["ledgerRevision"]) != (
                tenant_id, site_id, ledger_id, ledger_revision):
            raise _error("generation_ledger_scope_mismatch", "Ledger content does not match its namespace/revision.")
        return envelope

    def get_ledger(self, tenant_id: str, site_id: str, ledger_id: str, *,
                   ledger_revision: str | None = None) -> dict[str, Any]:
        head = self._read_ledger_head(tenant_id, site_id, ledger_id)
        requested = revision(ledger_revision, "ledgerRevision") if ledger_revision is not None else head["ledgerRevision"]
        if not any(commit["ledgerRevision"] == requested for commit in head["commits"]):
            raise _error("generation_ledger_revision_uncommitted", "This revision was never committed to the ledger head.")
        envelope = self._read_ledger(tenant_id, site_id, ledger_id, requested)
        return {"ledger": envelope["ledger"], "head": head,
                "artifactRefs": envelope["artifactRefs"], "isCurrent": requested == head["ledgerRevision"]}

    def commit_ledger(self, *, tenant_id: str, site_id: str, ledger: Mapping[str, Any],
                      expected_ledger_revision: str | None, request_key: str,
                      artifact_refs: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
        record = validate_generation_ledger(ledger)
        if (record["tenantId"], record["siteId"]) != (tenant_id, site_id):
            raise _error("generation_ledger_scope_mismatch", "Ledger belongs to another tenant/site.")
        identifier(request_key, "requestKey")
        expected = None if expected_ledger_revision is None else revision(expected_ledger_revision, "expectedLedgerRevision")
        refs = self._artifact_references(artifact_refs)
        signature = design_revision({"ledger": record, "expectedLedgerRevision": expected, "artifactRefs": refs})
        ledger_id = record["ledgerId"]
        with self._write_lock(tenant_id, site_id):
            try:
                head = self._read_ledger_head(tenant_id, site_id, ledger_id)
            except FacilityDesignRepositoryNotFoundError as exc:
                if exc.code != "generation_ledger_not_found":
                    raise
                head = None
            if head is not None:
                prior = next((item for item in head["commits"] if item["requestKey"] == request_key), None)
                if prior is not None:
                    if signature != prior["requestRevision"]:
                        raise _error("generation_ledger_idempotency_conflict", "Retry key was already used for different content.")
                    return self.get_ledger(tenant_id, site_id, ledger_id, ledger_revision=prior["ledgerRevision"])
            current = head["ledgerRevision"] if head is not None else None
            if current != expected or record["parentLedgerRevision"] != current:
                raise _error("generation_ledger_revision_conflict", "Ledger head changed or parent revision is incorrect.")
            if head is not None:
                if len(head["commits"]) >= MAX_LEDGER_REVISIONS:
                    raise _error("generation_ledger_revision_limit", "Generation ledger reached its revision limit.")
                previous = self._read_ledger(tenant_id, site_id, ledger_id, current)
                validate_generation_amendment(previous["ledger"], record)
            elif any(item["disposition"] == "superseded" for item in record["requirements"]):
                raise _error("generation_ledger_initial_history_invalid", "Initial ledger cannot contain superseded history.")
            for ref in refs:
                self.get_artifact(tenant_id, site_id, ref["artifactKind"], ref["artifactId"], ref["artifactRevision"])
            envelope = {"recordKind": "generation_requirement_revision", "ledger": record, "artifactRefs": refs}
            envelope["envelopeRevision"] = design_revision(envelope)
            path = self._ledger_path(tenant_id, site_id, ledger_id, record["ledgerRevision"])
            if _exists(path):
                if self._read_ledger(tenant_id, site_id, ledger_id, record["ledgerRevision"]) != envelope:
                    raise FacilityDesignRepositoryIntegrityError(
                        "generation_ledger_revision_collision", "Immutable ledger revision conflicts with stored bytes.")
            else:
                self._atomic_write(path, envelope)
            # Pins precede the commit point. A pre-commit crash can retain extra data,
            # but cannot publish a ledger whose dependencies have been collected.
            self._replace_owner_pins_locked(tenant_id, site_id, "generation_ledger_revision",
                                            record["ledgerRevision"], refs)
            next_head = {"recordKind": "generation_requirement_head", "ledgerId": ledger_id,
                         "ledgerRevision": record["ledgerRevision"],
                         "commits": deepcopy(head["commits"]) if head is not None else []}
            next_head["commits"].append({"requestKey": request_key, "requestRevision": signature,
                                         "ledgerRevision": record["ledgerRevision"]})
            next_head["headRevision"] = design_revision(next_head)
            self._atomic_write(self._ledger_head_path(tenant_id, site_id, ledger_id), next_head)
            return self.get_ledger(tenant_id, site_id, ledger_id, ledger_revision=record["ledgerRevision"])

    def require_current_ledger(self, tenant_id: str, site_id: str, ledger_id: str,
                               ledger_revision: str) -> dict[str, Any]:
        """Point-in-time preview check, not a reservation or atomic Apply authorization."""
        record = self.get_ledger(tenant_id, site_id, ledger_id, ledger_revision=ledger_revision)
        if not record["isCurrent"]:
            raise _error("generation_ledger_superseded", "A correction superseded this ledger revision.")
        return record

    def publish_current_artifact(self, *, tenant_id: str, site_id: str, ledger_id: str,
                                 ledger_revision: str, artifact_kind: str, artifact_id: str,
                                 artifact: Mapping[str, Any], dependency_refs=()) -> dict[str, Any]:
        """Publish a retry-addressed artifact while serializing against corrections.

        The storage address is a retry index. Consumers must additionally verify
        the logical content revision returned inside the artifact.
        """
        identifier(artifact_kind, "artifactKind")
        identifier(artifact_id, "artifactId")
        address = design_revision({"artifactKind": artifact_kind, "artifactId": artifact_id})
        ref = {"artifactKind": artifact_kind, "artifactId": artifact_id, "artifactRevision": address}
        refs = self._artifact_references([*dependency_refs, ref])
        with self._write_lock(tenant_id, site_id):
            self.require_current_ledger(tenant_id, site_id, ledger_id, ledger_revision)
            path = self._artifact_path(tenant_id, site_id, artifact_kind, artifact_id, address)
            envelope = {"recordKind": "facility_design_artifact", **ref,
                        "artifactHash": design_revision(artifact), "artifact": deepcopy(dict(artifact)),
                        "storedAt": _timestamp(self._now())}
            for dependency in dependency_refs:
                self.get_artifact(tenant_id, site_id, dependency["artifactKind"],
                                  dependency["artifactId"], dependency["artifactRevision"])
            if _exists(path):
                prior = self.get_artifact(tenant_id, site_id, artifact_kind, artifact_id, address)
                if prior["artifact"] != artifact:
                    raise _error("generation_artifact_retry_conflict", "Retry key already identifies different content.")
            else:
                self._atomic_write(path, envelope)
            self._replace_owner_pins_locked(tenant_id, site_id, "generation_preview", address, refs)
            # Publish only after every retention pin is durable. Interrupted
            # publication is recoverable using the same retry identity.
            self._atomic_write(self._scope(tenant_id, site_id) / "generation-publications" / f"{address}.json",
                               {"artifactRef": ref, "artifactHash": design_revision(artifact), "dependencyRefs": refs})
            if artifact_kind == "generation-isolated-preview":
                latest = {"artifactRef": ref, "ledgerRevision": ledger_revision, "contentRevision": artifact["contentRevision"]}
                latest["indexRevision"] = design_revision(latest)
                self._atomic_write(self._ledger_root(tenant_id, site_id, ledger_id) / "latest-preview.json", latest)
            return ref

    def latest_preview_reference(self, tenant_id, site_id, ledger_id):
        path = self._ledger_root(tenant_id, site_id, ledger_id) / "latest-preview.json"
        if not _exists(path):
            return None
        record = _read_json(path, missing_code="generation_preview_index_missing")
        if (set(record) != {"artifactRef", "ledgerRevision", "contentRevision", "indexRevision"}
                or record["indexRevision"] != design_revision({key: value for key, value in record.items() if key != "indexRevision"})
                or record.get("artifactRef", {}).get("artifactKind") != "generation-isolated-preview"):
            raise _error("generation_preview_index_corrupt", "Prior preview index failed integrity validation.")
        self._artifact_references([record["artifactRef"]])
        self.get_ledger(tenant_id, site_id, ledger_id, ledger_revision=record["ledgerRevision"])
        return record

    def require_published_artifact(self, tenant_id, site_id, artifact_kind, artifact_id, artifact):
        address = design_revision({"artifactKind": artifact_kind, "artifactId": artifact_id})
        marker = _read_json(self._scope(tenant_id, site_id) / "generation-publications" / f"{address}.json",
                            missing_code="generation_artifact_unpublished")
        ref = {"artifactKind": artifact_kind, "artifactId": artifact_id, "artifactRevision": address}
        if marker.get("artifactRef") != ref or marker.get("artifactHash") != design_revision(artifact):
            raise _error("generation_artifact_publication_mismatch", "Artifact publication does not match its content.")
        for dependency in marker["dependencyRefs"]:
            self.get_artifact(tenant_id, site_id, dependency["artifactKind"], dependency["artifactId"], dependency["artifactRevision"])
            if not self.artifact_pin_count(tenant_id, site_id, dependency["artifactRevision"]):
                raise _error("generation_artifact_unpublished", "A published artifact is missing retention pins.")
