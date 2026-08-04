"""Tamper-evident evidence ledger for the Facility Layout self-use soak."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Any, Mapping

from ai_inspector.transactions import (
    JsonReceiptStore,
    TransactionError,
    canonical_json_bytes,
)


SOAK_SCHEMA_VERSION = "facility-layout-real-soak-events-v2"
SOAK_DURATION_SECONDS = 14 * 24 * 60 * 60
SOAK_REQUIREMENTS = {
    "elapsedDays": 14,
    "layouts": 10,
    "editingSessions": 50,
    "agentPreviews": 20,
    "approvedReceiptBackedApplies": 10,
    "byteIdenticalDismissals": 5,
    "rejectedStaleOrUnauthorizedAttempts": 5,
    "reopenCyclesPerLayout": 5,
}
SOAK_EVENT_KINDS = frozenset(
    {
        "editing_session",
        "agent_preview",
        "approved_apply",
        "byte_identical_dismissal",
        "rejected_attempt",
        "layout_reopen",
        "workflow_exercised",
    }
)
SOAK_WORKFLOWS = frozenset(
    {"warehouse", "manufacturing_cell", "rollback"}
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_REVISION = re.compile(r"^[0-9a-f]{64}$")


class SoakEvidenceError(ValueError):
    """Raised when a self-use observation cannot be credited."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _current_utc() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now() -> str:
    return _current_utc().isoformat().replace("+00:00", "Z")


def _parse_utc(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SoakEvidenceError(f"{field} must be a UTC ISO timestamp.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise SoakEvidenceError(
            f"{field} must be a UTC ISO timestamp."
        ) from error
    if parsed.tzinfo is None:
        raise SoakEvidenceError(f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _identifier(value: Any, field: str) -> str:
    cleaned = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(cleaned):
        raise SoakEvidenceError(f"{field} is invalid.")
    return cleaned


def _revision(value: Any, field: str) -> str:
    cleaned = str(value or "").strip().lower()
    if not _REVISION.fullmatch(cleaned):
        raise SoakEvidenceError(
            f"{field} must be a 64-character lowercase SHA-256 revision."
        )
    return cleaned


def _git_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def facility_build_identity(root: Path) -> dict[str, Any]:
    """Hash the source surface that can affect Facility Layout writes."""

    root = root.resolve()
    candidates = sorted(
        {
            *(
                root / "ai_inspector" / "facility_layout"
            ).rglob("*.py"),
            *(
                root / "ai_inspector" / "transactions"
            ).rglob("*.py"),
            *(root / "static").rglob("facility_layout*.js"),
            *(root / "static").rglob("facility_layout*.css"),
            root / "static" / "index.html",
            root / "server.py",
            root / "tools" / "record_facility_layout_soak.py",
        },
        key=lambda path: path.as_posix(),
    )
    records = []
    for path in candidates:
        if not path.is_file():
            continue
        relative = str(path.relative_to(root)).replace("\\", "/")
        records.append(
            {
                "path": relative,
                "byteLength": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    if not records:
        raise SoakEvidenceError("No Facility Layout source files were found.")
    aggregate = _sha256_bytes(_canonical_bytes(records))
    return {
        "algorithm": "sha256-canonical-source-list-v1",
        "gitCommit": _git_commit(root),
        "aggregateSha256": aggregate,
        "files": records,
    }


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value,
        indent=2,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
    ) + "\n"
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="ascii",
        newline="\n",
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if temporary.exists():
            temporary.unlink()


def load_soak_events(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SoakEvidenceError("The soak event ledger is unreadable.") from error
    if not isinstance(value, dict):
        raise SoakEvidenceError("The soak event ledger must be an object.")
    if value.get("schemaVersion") != SOAK_SCHEMA_VERSION:
        raise SoakEvidenceError("The soak event ledger schema is unsupported.")
    if not isinstance(value.get("campaign"), dict):
        raise SoakEvidenceError("The soak event ledger has no campaign.")
    if not isinstance(value.get("events"), list):
        raise SoakEvidenceError("The soak event ledger events must be an array.")
    if not _verify_chain(value):
        raise SoakEvidenceError("The soak event ledger hash chain is invalid.")
    return value


def start_soak_campaign(
    path: Path,
    *,
    build_identity: Mapping[str, Any],
) -> dict[str, Any]:
    if path.exists():
        raise SoakEvidenceError(
            "A soak campaign already exists; archive it before starting another."
        )
    started = _utc_now()
    _parse_utc(started, "startedAtUtc")
    identity = deepcopy(dict(build_identity))
    aggregate = _revision(
        identity.get("aggregateSha256"),
        "buildIdentity.aggregateSha256",
    )
    campaign_id = "fls-" + _sha256_bytes(
        _canonical_bytes(
            {
                "startedAtUtc": started,
                "buildAggregateSha256": aggregate,
            }
        )
    )[:24]
    campaign = {
        "campaignId": campaign_id,
        "startedAtUtc": started,
        "buildIdentity": identity,
        "requirements": deepcopy(SOAK_REQUIREMENTS),
    }
    campaign_genesis = _sha256_bytes(
        _canonical_bytes(
            {
                "schemaVersion": SOAK_SCHEMA_VERSION,
                "campaign": campaign,
            }
        )
    )
    ledger = {
        "schemaVersion": SOAK_SCHEMA_VERSION,
        "campaign": campaign,
        "campaignGenesisSha256": campaign_genesis,
        "events": [],
        "chainHeadSha256": campaign_genesis,
    }
    _write_json_atomic(path, ledger)
    return ledger


def _validate_event_evidence(
    kind: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    value = deepcopy(dict(evidence))
    if kind == "editing_session":
        value["layoutId"] = _identifier(value.get("layoutId"), "layoutId")
        value["sessionId"] = _identifier(value.get("sessionId"), "sessionId")
        value["layoutRevision"] = _revision(
            value.get("layoutRevision"),
            "layoutRevision",
        )
    elif kind == "agent_preview":
        value["layoutId"] = _identifier(value.get("layoutId"), "layoutId")
        value["proposalId"] = _identifier(
            value.get("proposalId"),
            "proposalId",
        )
        value["baseRevision"] = _revision(
            value.get("baseRevision"),
            "baseRevision",
        )
        if value.get("displayedForReview") is not True:
            raise SoakEvidenceError(
                "An agent preview counts only after it was displayed for review."
            )
    elif kind == "approved_apply":
        value["layoutId"] = _identifier(value.get("layoutId"), "layoutId")
        value["proposalId"] = _identifier(
            value.get("proposalId"),
            "proposalId",
        )
        value["receiptId"] = _identifier(
            value.get("receiptId"),
            "receiptId",
        )
        value["receiptSha256"] = _revision(
            value.get("receiptSha256"),
            "receiptSha256",
        )
        value["resultingRevision"] = _revision(
            value.get("resultingRevision"),
            "resultingRevision",
        )
        if value.get("durablyRetrieved") is not True:
            raise SoakEvidenceError(
                "An approved apply requires a durably retrieved receipt."
            )
    elif kind == "byte_identical_dismissal":
        value["layoutId"] = _identifier(value.get("layoutId"), "layoutId")
        value["proposalId"] = _identifier(
            value.get("proposalId"),
            "proposalId",
        )
        value["beforeSha256"] = _revision(
            value.get("beforeSha256"),
            "beforeSha256",
        )
        value["afterSha256"] = _revision(
            value.get("afterSha256"),
            "afterSha256",
        )
        if value["beforeSha256"] != value["afterSha256"]:
            raise SoakEvidenceError(
                "A dismissed preview changed the canonical layout bytes."
            )
    elif kind == "rejected_attempt":
        value["layoutId"] = _identifier(value.get("layoutId"), "layoutId")
        value["errorCode"] = _identifier(
            value.get("errorCode"),
            "errorCode",
        )
        status = int(value.get("statusCode") or 0)
        if status not in {401, 403, 409}:
            raise SoakEvidenceError(
                "A credited rejected attempt must be a 401, 403, or 409."
            )
        value["statusCode"] = status
    elif kind == "layout_reopen":
        value["layoutId"] = _identifier(value.get("layoutId"), "layoutId")
        value["layoutRevision"] = _revision(
            value.get("layoutRevision"),
            "layoutRevision",
        )
        value["canonicalLayoutSha256"] = _revision(
            value.get("canonicalLayoutSha256"),
            "canonicalLayoutSha256",
        )
        if value.get("savedRevisionRetrieved") is not True:
            raise SoakEvidenceError(
                "A reopen counts only after the saved revision was retrieved."
            )
    elif kind == "workflow_exercised":
        workflow = str(value.get("workflow") or "").strip()
        if workflow not in SOAK_WORKFLOWS:
            raise SoakEvidenceError("The soak workflow is unsupported.")
        value = {"workflow": workflow}
    else:
        raise SoakEvidenceError("The soak event kind is unsupported.")
    return value


def append_soak_event(
    path: Path,
    *,
    kind: str,
    evidence: Mapping[str, Any],
    build_identity: Mapping[str, Any],
) -> dict[str, Any]:
    if kind not in SOAK_EVENT_KINDS:
        raise SoakEvidenceError("The soak event kind is unsupported.")
    ledger = load_soak_events(path)
    occurred = _utc_now()
    occurred_at = _parse_utc(occurred, "occurredAtUtc")
    started_at = _parse_utc(
        ledger["campaign"]["startedAtUtc"],
        "campaign.startedAtUtc",
    )
    now = _current_utc()
    if occurred_at < started_at:
        raise SoakEvidenceError("A soak event cannot predate the campaign.")
    if occurred_at > now.replace(microsecond=now.microsecond) and (
        occurred_at - now
    ).total_seconds() > 5:
        raise SoakEvidenceError("A soak event cannot be recorded in the future.")
    existing_events = ledger.get("events")
    if isinstance(existing_events, list) and existing_events:
        previous_occurred = _parse_utc(
            str(existing_events[-1].get("occurredAtUtc") or ""),
            "previousEvent.occurredAtUtc",
        )
        if occurred_at < previous_occurred:
            raise SoakEvidenceError(
                "A soak event cannot predate the previous event."
            )

    expected_build = ledger["campaign"]["buildIdentity"]
    current_build = deepcopy(dict(build_identity))
    if (
        current_build.get("aggregateSha256")
        != expected_build.get("aggregateSha256")
    ):
        raise SoakEvidenceError(
            "The write-capable Facility Layout build changed during the soak."
        )
    normalized = _validate_event_evidence(kind, evidence)
    previous_hash = str(ledger.get("chainHeadSha256") or "0" * 64)
    event_body = {
        "kind": kind,
        "occurredAtUtc": occurred,
        "buildAggregateSha256": expected_build["aggregateSha256"],
        "evidence": normalized,
        "previousEventSha256": previous_hash,
    }
    event_hash = _sha256_bytes(_canonical_bytes(event_body))
    event = {
        "eventId": "fle-" + event_hash[:24],
        **event_body,
        "eventSha256": event_hash,
    }
    ledger["events"].append(event)
    ledger["chainHeadSha256"] = event_hash
    _write_json_atomic(path, ledger)
    return event


def _verify_chain(ledger: Mapping[str, Any]) -> bool:
    campaign = ledger.get("campaign")
    if not isinstance(campaign, Mapping):
        return False
    expected_genesis = _sha256_bytes(
        _canonical_bytes(
            {
                "schemaVersion": ledger.get("schemaVersion"),
                "campaign": dict(campaign),
            }
        )
    )
    if ledger.get("campaignGenesisSha256") != expected_genesis:
        return False
    previous_hash = expected_genesis
    seen_ids: set[str] = set()
    for raw in ledger.get("events", []):
        if not isinstance(raw, Mapping):
            return False
        event = dict(raw)
        event_id = str(event.pop("eventId", ""))
        event_hash = str(event.pop("eventSha256", ""))
        if event_id in seen_ids or event.get("previousEventSha256") != previous_hash:
            return False
        if _sha256_bytes(_canonical_bytes(event)) != event_hash:
            return False
        if event_id != "fle-" + event_hash[:24]:
            return False
        seen_ids.add(event_id)
        previous_hash = event_hash
    return str(ledger.get("chainHeadSha256")) == previous_hash


def summarize_soak_events(
    ledger: Mapping[str, Any],
    *,
    evaluated_at_utc: str | None = None,
) -> dict[str, Any]:
    evaluated = evaluated_at_utc or _utc_now()
    evaluated_at = _parse_utc(evaluated, "evaluatedAtUtc")
    campaign = ledger.get("campaign")
    if not isinstance(campaign, Mapping):
        raise SoakEvidenceError("The soak campaign is missing.")
    started = _parse_utc(str(campaign.get("startedAtUtc")), "startedAtUtc")
    elapsed_seconds = max(0.0, (evaluated_at - started).total_seconds())
    elapsed_days = elapsed_seconds / (24 * 60 * 60)
    events = ledger.get("events")
    if not isinstance(events, list):
        raise SoakEvidenceError("The soak events must be an array.")

    layouts: set[str] = set()
    sessions: set[str] = set()
    previews: set[str] = set()
    receipts: set[str] = set()
    dismissals: set[str] = set()
    rejected: set[str] = set()
    reopens: dict[str, int] = {}
    workflows: set[str] = set()
    for event in events:
        if not isinstance(event, Mapping):
            continue
        kind = event.get("kind")
        evidence = event.get("evidence")
        if not isinstance(evidence, Mapping):
            continue
        layout_id = evidence.get("layoutId")
        if isinstance(layout_id, str):
            layouts.add(layout_id)
        if kind == "editing_session":
            sessions.add(str(evidence.get("sessionId")))
        elif kind == "agent_preview":
            previews.add(str(evidence.get("proposalId")))
        elif kind == "approved_apply":
            receipts.add(str(evidence.get("receiptId")))
        elif kind == "byte_identical_dismissal":
            dismissals.add(str(evidence.get("proposalId")))
        elif kind == "rejected_attempt":
            rejected.add(str(event.get("eventId")))
        elif kind == "layout_reopen" and isinstance(layout_id, str):
            reopens[layout_id] = reopens.get(layout_id, 0) + 1
        elif kind == "workflow_exercised":
            workflows.add(str(evidence.get("workflow")))

    minimum_reopens = min(
        (reopens.get(layout_id, 0) for layout_id in layouts),
        default=0,
    )
    observed = {
        "layouts": len(layouts),
        "editingSessions": len(sessions),
        "agentPreviews": len(previews),
        "approvedReceiptBackedApplies": len(receipts),
        "byteIdenticalDismissals": len(dismissals),
        "rejectedStaleOrUnauthorizedAttempts": len(rejected),
        "reopenCyclesPerLayout": minimum_reopens,
        "canonicalReceiptIds": sorted(receipts),
    }
    checks = {
        "elapsedDurationMet": elapsed_seconds >= SOAK_DURATION_SECONDS,
        **{
            key: observed[key] >= threshold
            for key, threshold in SOAK_REQUIREMENTS.items()
            if key != "elapsedDays"
        },
        "canonicalReceiptCountMet": (
            len(receipts)
            >= SOAK_REQUIREMENTS["approvedReceiptBackedApplies"]
        ),
        "requiredWorkflowsExercised": SOAK_WORKFLOWS.issubset(workflows),
        "eventChainValid": _verify_chain(ledger),
    }
    release_gate_met = all(checks.values())
    if not checks["eventChainValid"]:
        status = "evidence_chain_invalid"
    elif not checks["elapsedDurationMet"]:
        status = "elapsed_duration_pending"
    elif not all(
        value
        for key, value in checks.items()
        if key not in {"elapsedDurationMet", "eventChainValid"}
    ):
        status = "activity_requirements_pending"
    else:
        status = "complete"
    return {
        "campaignId": campaign.get("campaignId"),
        "startedAtUtc": campaign.get("startedAtUtc"),
        "lastEvaluatedAtUtc": evaluated,
        "elapsedDays": elapsed_days,
        "elapsedHours": elapsed_seconds / (60 * 60),
        "elapsedSeconds": elapsed_seconds,
        "requirements": deepcopy(SOAK_REQUIREMENTS),
        "observed": observed,
        "workflowsExercised": sorted(workflows),
        "eventCount": len(events),
        "chainHeadSha256": ledger.get("chainHeadSha256"),
        "checks": checks,
        "status": status,
        "releaseGateMet": release_gate_met,
        "note": (
            "Only source-bound, real self-use events in the append-only "
            "evidence chain are credited."
        ),
    }


def verified_apply_evidence(
    receipt_store_root: Path,
    *,
    receipt_id: str,
    layout_id: str,
) -> dict[str, Any]:
    receipt_store_root = Path(receipt_store_root)
    if not receipt_store_root.is_dir():
        raise SoakEvidenceError(
            "The canonical durable receipt store does not exist."
        )
    try:
        receipt_record = JsonReceiptStore(
            receipt_store_root
        ).get_receipt(receipt_id)
    except (OSError, TransactionError) as error:
        raise SoakEvidenceError(
            "The canonical durable receipt could not be retrieved."
        ) from error
    receipt = receipt_record.to_dict()
    if receipt_record.action != "apply-layout-plan":
        raise SoakEvidenceError(
            "The receipt does not represent an approved layout-plan apply."
        )
    if receipt_record.approval_fingerprint is None:
        raise SoakEvidenceError(
            "The durable receipt is not bound to an explicit approval."
        )
    binding = receipt.get("binding")
    target = binding.get("target") if isinstance(binding, Mapping) else None
    target_layout = target.get("resourceId") if isinstance(target, Mapping) else None
    target_domain = target.get("domain") if isinstance(target, Mapping) else None
    if target_domain != "facility-layout" or target_layout != layout_id:
        raise SoakEvidenceError("The receipt targets a different layout.")
    payload = receipt.get("payload")
    operation = (
        payload.get("operationResult")
        if isinstance(payload, Mapping)
        else None
    )
    canonical_diff = (
        operation.get("canonicalDiff")
        if isinstance(operation, Mapping)
        else None
    )
    resulting_revision = (
        canonical_diff.get("afterRevision")
        if isinstance(canonical_diff, Mapping)
        else None
    )
    return {
        "layoutId": _identifier(layout_id, "layoutId"),
        "proposalId": _identifier(receipt.get("proposalId"), "proposalId"),
        "receiptId": _identifier(receipt.get("receiptId"), "receiptId"),
        "receiptSha256": _sha256_bytes(canonical_json_bytes(receipt)),
        "approvalFingerprint": _revision(
            receipt_record.approval_fingerprint,
            "approvalFingerprint",
        ),
        "explicitApprovalBound": True,
        "resultingRevision": _revision(
            resulting_revision,
            "resultingRevision",
        ),
        "durablyRetrieved": True,
        "retrievalMethod": "canonical_transaction_store",
    }


def verified_dismissal_evidence(
    before_path: Path,
    after_path: Path,
    *,
    layout_id: str,
    proposal_id: str,
) -> dict[str, Any]:
    before = _sha256_file(before_path)
    after = _sha256_file(after_path)
    evidence = {
        "layoutId": layout_id,
        "proposalId": proposal_id,
        "beforeSha256": before,
        "afterSha256": after,
    }
    return _validate_event_evidence("byte_identical_dismissal", evidence)


def verified_reopen_evidence(
    layout_path: Path,
    *,
    layout_id: str,
    layout_revision: str,
) -> dict[str, Any]:
    if not layout_path.is_file():
        raise SoakEvidenceError("The reopened canonical layout is missing.")
    return _validate_event_evidence(
        "layout_reopen",
        {
            "layoutId": layout_id,
            "layoutRevision": layout_revision,
            "canonicalLayoutSha256": _sha256_file(layout_path),
            "savedRevisionRetrieved": True,
        },
    )


__all__ = [
    "SOAK_EVENT_KINDS",
    "SOAK_REQUIREMENTS",
    "SOAK_SCHEMA_VERSION",
    "SOAK_WORKFLOWS",
    "SoakEvidenceError",
    "append_soak_event",
    "facility_build_identity",
    "load_soak_events",
    "start_soak_campaign",
    "summarize_soak_events",
    "verified_apply_evidence",
    "verified_dismissal_evidence",
    "verified_reopen_evidence",
]
