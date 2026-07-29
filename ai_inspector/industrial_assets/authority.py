"""Trusted-source and evidence authority for industrial assets.

The model in this module is intentionally deterministic. It validates evidence
that already exists; it never promotes inferred information or selects a
preferred authoritative source when current sources disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence


EVIDENCE_STATUSES = frozenset({"authored", "derived", "inferred", "unknown"})
TRUSTED_SOURCE_STATUSES = frozenset({"active", "suspended", "revoked"})
TRUSTED_SOURCE_TYPES = frozenset(
    {
        "cad",
        "drawing",
        "procedure",
        "policy",
        "manufacturer_specification",
        "site_record",
        "user_statement",
    }
)
AUTHORITY_ROLES = frozenset({"authority_curator", "admin"})

_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{64}$")


class IndustrialAssetAuthorityError(ValueError):
    """A structurally invalid authority record."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_stable_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _STABLE_ID_RE.fullmatch(value):
        raise IndustrialAssetAuthorityError(
            "invalid_stable_id",
            f"{field_name} must be a stable ID.",
        )
    return value


def validate_revision(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _REVISION_RE.fullmatch(value):
        raise IndustrialAssetAuthorityError(
            "invalid_revision",
            f"{field_name} must be a lowercase SHA-256 revision.",
        )
    return value


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        payload = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise IndustrialAssetAuthorityError(
            "invalid_json_value",
            f"Authority data must be canonical JSON: {exc}",
        ) from exc
    return (payload + "\n").encode("ascii")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _parse_timestamp(value: Any, field_name: str, *, nullable: bool) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value or len(value) > 64:
        raise IndustrialAssetAuthorityError(
            "invalid_timestamp",
            f"{field_name} must be an ISO-8601 timestamp.",
        )
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise IndustrialAssetAuthorityError(
            "invalid_timestamp",
            f"{field_name} must be an ISO-8601 timestamp.",
        ) from exc
    if parsed.tzinfo is None:
        raise IndustrialAssetAuthorityError(
            "invalid_timestamp",
            f"{field_name} must include a timezone.",
        )
    return parsed.astimezone(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise IndustrialAssetAuthorityError(
            "invalid_evaluation_time",
            "as_of must be a timezone-aware datetime.",
        )
    return value.astimezone(timezone.utc)


def _unique_ids(values: Any, field_name: str, *, limit: int) -> tuple[str, ...]:
    if not isinstance(values, list) or len(values) > limit:
        raise IndustrialAssetAuthorityError(
            "invalid_id_list",
            f"{field_name} must be a bounded list.",
        )
    result = tuple(validate_stable_id(item, field_name) for item in values)
    if len(result) != len(set(result)):
        raise IndustrialAssetAuthorityError(
            "duplicate_id",
            f"{field_name} must not contain duplicates.",
        )
    return tuple(sorted(result))


def _claim_is_permitted(claim_key: str, scopes: Sequence[str]) -> bool:
    return any(
        claim_key == scope or claim_key.startswith(scope + ".")
        for scope in scopes
    )


@dataclass(frozen=True)
class TrustedSource:
    trusted_source_id: str
    owner_tenant_id: str
    source_type: str
    issuer: str
    status: str
    permitted_claim_scopes: tuple[str, ...]
    allowed_site_ids: tuple[str, ...]
    maximum_age_days: int | None
    current_revision: str | None
    allowed_roles: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TrustedSource":
        if not isinstance(value, Mapping):
            raise IndustrialAssetAuthorityError(
                "invalid_trusted_source",
                "Trusted source must be an object.",
            )
        source_type = value.get("sourceType")
        status = value.get("status")
        if source_type not in TRUSTED_SOURCE_TYPES:
            raise IndustrialAssetAuthorityError(
                "invalid_trusted_source_type",
                "Trusted source type is unsupported.",
            )
        if status not in TRUSTED_SOURCE_STATUSES:
            raise IndustrialAssetAuthorityError(
                "invalid_trusted_source_status",
                "Trusted source status is unsupported.",
            )
        issuer = value.get("issuer")
        if not isinstance(issuer, str) or not issuer.strip() or len(issuer) > 120:
            raise IndustrialAssetAuthorityError(
                "invalid_trusted_source_issuer",
                "Trusted source issuer must be a non-empty label.",
            )
        freshness = value.get("freshnessPolicy")
        if not isinstance(freshness, Mapping):
            raise IndustrialAssetAuthorityError(
                "invalid_freshness_policy",
                "freshnessPolicy must be an object.",
            )
        maximum_age = freshness.get("maximumAgeDays")
        if maximum_age is not None and (
            isinstance(maximum_age, bool)
            or not isinstance(maximum_age, int)
            or maximum_age < 0
            or maximum_age > 36500
        ):
            raise IndustrialAssetAuthorityError(
                "invalid_freshness_policy",
                "maximumAgeDays must be an integer between 0 and 36500.",
            )
        current_revision = value.get("currentRevision")
        if current_revision is not None:
            current_revision = validate_revision(
                current_revision,
                "currentRevision",
            )
        access_policy = value.get("accessPolicy", {})
        if not isinstance(access_policy, Mapping):
            raise IndustrialAssetAuthorityError(
                "invalid_source_access_policy",
                "accessPolicy must be an object.",
            )
        allowed_roles_raw = access_policy.get("allowedRoles", [])
        allowed_roles = _unique_ids(
            allowed_roles_raw,
            "accessPolicy.allowedRoles",
            limit=64,
        )
        return cls(
            trusted_source_id=validate_stable_id(
                value.get("trustedSourceId"),
                "trustedSourceId",
            ),
            owner_tenant_id=validate_stable_id(
                value.get("ownerTenantId"),
                "ownerTenantId",
            ),
            source_type=source_type,
            issuer=issuer.strip(),
            status=status,
            permitted_claim_scopes=_unique_ids(
                value.get("permittedClaimScopes"),
                "permittedClaimScopes",
                limit=256,
            ),
            allowed_site_ids=_unique_ids(
                value.get("allowedSiteIds"),
                "allowedSiteIds",
                limit=1000,
            ),
            maximum_age_days=maximum_age,
            current_revision=current_revision,
            allowed_roles=allowed_roles,
        )


@dataclass(frozen=True)
class TrustedSourceRegistry:
    tenant_id: str
    sources: tuple[TrustedSource, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TrustedSourceRegistry":
        if not isinstance(value, Mapping):
            raise IndustrialAssetAuthorityError(
                "invalid_trusted_source_registry",
                "Trusted source registry must be an object.",
            )
        if (
            value.get("schemaVersion") != 1
            or value.get("documentKind") != "trusted_source_registry"
        ):
            raise IndustrialAssetAuthorityError(
                "invalid_trusted_source_registry",
                "Unsupported trusted source registry.",
            )
        tenant_id = validate_stable_id(value.get("tenantId"), "tenantId")
        raw_sources = value.get("sources")
        if not isinstance(raw_sources, list) or len(raw_sources) > 10000:
            raise IndustrialAssetAuthorityError(
                "invalid_trusted_source_registry",
                "sources must be a bounded list.",
            )
        sources = tuple(TrustedSource.from_mapping(item) for item in raw_sources)
        source_ids = [item.trusted_source_id for item in sources]
        if len(source_ids) != len(set(source_ids)):
            raise IndustrialAssetAuthorityError(
                "duplicate_trusted_source",
                "Trusted source IDs must be unique.",
            )
        if any(item.owner_tenant_id != tenant_id for item in sources):
            raise IndustrialAssetAuthorityError(
                "trusted_source_tenant_mismatch",
                "Every trusted source must belong to the registry tenant.",
            )
        return cls(
            tenant_id=tenant_id,
            sources=tuple(
                sorted(sources, key=lambda item: item.trusted_source_id)
            ),
        )

    def by_id(self) -> dict[str, TrustedSource]:
        return {item.trusted_source_id: item for item in self.sources}


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    tenant_id: str
    subject_ref: Mapping[str, Any]
    claim_key: str
    value_fingerprint: str
    status: str
    trusted_source_id: str
    source_revision: str
    source_locator: str | None
    derivation_method_id: str | None
    derivation_method_version: str | None
    input_evidence_ids: tuple[str, ...]
    asserted_by: str
    asserted_at: datetime
    valid_from: datetime | None
    valid_until: datetime | None
    revoked_at: datetime | None
    revocation_reason: str | None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvidenceRecord":
        if not isinstance(value, Mapping):
            raise IndustrialAssetAuthorityError(
                "invalid_evidence_record",
                "Evidence record must be an object.",
            )
        if (
            value.get("schemaVersion") != 1
            or value.get("documentKind") != "evidence_record"
        ):
            raise IndustrialAssetAuthorityError(
                "invalid_evidence_record",
                "Unsupported evidence record.",
            )
        status = value.get("status")
        if status not in EVIDENCE_STATUSES:
            raise IndustrialAssetAuthorityError(
                "invalid_evidence_status",
                "Evidence status is unsupported.",
            )
        subject_ref = value.get("subjectRef")
        if not isinstance(subject_ref, Mapping) or len(subject_ref) > 16:
            raise IndustrialAssetAuthorityError(
                "invalid_evidence_subject",
                "subjectRef must be a bounded object.",
            )
        _canonical_json_bytes(subject_ref)
        source_ref = value.get("sourceRef")
        if not isinstance(source_ref, Mapping):
            raise IndustrialAssetAuthorityError(
                "invalid_evidence_source",
                "sourceRef must be an object.",
            )
        locator = source_ref.get("locator")
        if not isinstance(locator, str) or len(locator) > 512:
            raise IndustrialAssetAuthorityError(
                "invalid_evidence_locator",
                "sourceRef.locator is invalid.",
            )
        derivation = value.get("derivation")
        method_id: str | None = None
        method_version: str | None = None
        input_ids: tuple[str, ...] = ()
        if derivation is not None:
            if not isinstance(derivation, Mapping):
                raise IndustrialAssetAuthorityError(
                    "invalid_evidence_derivation",
                    "derivation must be an object.",
                )
            method_id = validate_stable_id(
                derivation.get("methodId"),
                "derivation.methodId",
            )
            method_version = validate_stable_id(
                derivation.get("methodVersion"),
                "derivation.methodVersion",
            )
            input_ids = _unique_ids(
                derivation.get("inputEvidenceIds"),
                "derivation.inputEvidenceIds",
                limit=64,
            )
        if status == "derived" and derivation is None:
            raise IndustrialAssetAuthorityError(
                "derived_evidence_missing_derivation",
                "Derived evidence requires a pinned derivation.",
            )
        if status != "derived" and derivation is not None:
            raise IndustrialAssetAuthorityError(
                "unexpected_evidence_derivation",
                "Only derived evidence may carry a derivation.",
            )
        revoked_at = _parse_timestamp(
            value.get("revokedAt"),
            "revokedAt",
            nullable=True,
        )
        reason = value.get("revocationReason")
        if reason is not None and (
            not isinstance(reason, str) or len(reason) > 2000
        ):
            raise IndustrialAssetAuthorityError(
                "invalid_revocation_reason",
                "revocationReason is invalid.",
            )
        if revoked_at is not None and not reason:
            raise IndustrialAssetAuthorityError(
                "revocation_reason_required",
                "Revoked evidence requires a reason.",
            )
        asserted_at = _parse_timestamp(
            value.get("assertedAt"),
            "assertedAt",
            nullable=False,
        )
        assert asserted_at is not None
        valid_from = _parse_timestamp(
            value.get("validFrom"),
            "validFrom",
            nullable=True,
        )
        valid_until = _parse_timestamp(
            value.get("validUntil"),
            "validUntil",
            nullable=True,
        )
        if (
            valid_from is not None
            and valid_until is not None
            and valid_until < valid_from
        ):
            raise IndustrialAssetAuthorityError(
                "invalid_evidence_interval",
                "validUntil precedes validFrom.",
            )
        return cls(
            evidence_id=validate_stable_id(
                value.get("evidenceId"),
                "evidenceId",
            ),
            tenant_id=validate_stable_id(value.get("tenantId"), "tenantId"),
            subject_ref=dict(subject_ref),
            claim_key=validate_stable_id(
                value.get("claimKey"),
                "claimKey",
            ),
            value_fingerprint=validate_revision(
                value.get("valueFingerprint"),
                "valueFingerprint",
            ),
            status=status,
            trusted_source_id=validate_stable_id(
                source_ref.get("trustedSourceId"),
                "sourceRef.trustedSourceId",
            ),
            source_revision=validate_revision(
                source_ref.get("sourceRevision"),
                "sourceRef.sourceRevision",
            ),
            source_locator=locator,
            derivation_method_id=method_id,
            derivation_method_version=method_version,
            input_evidence_ids=input_ids,
            asserted_by=validate_stable_id(
                value.get("assertedBy"),
                "assertedBy",
            ),
            asserted_at=asserted_at,
            valid_from=valid_from,
            valid_until=valid_until,
            revoked_at=revoked_at,
            revocation_reason=reason,
        )

    @property
    def subject_fingerprint(self) -> str:
        return _canonical_hash(self.subject_ref)

    def to_dict(self) -> dict[str, Any]:
        def timestamp(value: datetime | None) -> str | None:
            if value is None:
                return None
            return (
                value.astimezone(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )

        result: dict[str, Any] = {
            "schemaVersion": 1,
            "documentKind": "evidence_record",
            "evidenceId": self.evidence_id,
            "tenantId": self.tenant_id,
            "subjectRef": dict(self.subject_ref),
            "claimKey": self.claim_key,
            "valueFingerprint": self.value_fingerprint,
            "status": self.status,
            "sourceRef": {
                "trustedSourceId": self.trusted_source_id,
                "sourceRevision": self.source_revision,
                "locator": self.source_locator,
            },
            "assertedBy": self.asserted_by,
            "assertedAt": timestamp(self.asserted_at),
            "validFrom": timestamp(self.valid_from),
            "validUntil": timestamp(self.valid_until),
            "revokedAt": timestamp(self.revoked_at),
            "revocationReason": self.revocation_reason,
        }
        if self.status == "derived":
            result["derivation"] = {
                "methodId": self.derivation_method_id,
                "methodVersion": self.derivation_method_version,
                "inputEvidenceIds": list(self.input_evidence_ids),
            }
        return result


@dataclass(frozen=True)
class AuthorityFinding:
    code: str
    severity: str
    evidence_ids: tuple[str, ...]
    claim_key: str | None
    message: str

    @property
    def finding_id(self) -> str:
        return "iaa-" + _canonical_hash(
            {
                "claimKey": self.claim_key,
                "code": self.code,
                "evidenceIds": list(self.evidence_ids),
            }
        )[:24]

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "findingId": self.finding_id,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "evidenceIds": list(self.evidence_ids),
        }
        if self.claim_key is not None:
            result["claimKey"] = self.claim_key
        return result


@dataclass(frozen=True)
class EvidenceState:
    evidence_id: str
    claim_key: str
    value_fingerprint: str
    status: str
    current: bool
    authoritative: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidenceId": self.evidence_id,
            "claimKey": self.claim_key,
            "valueFingerprint": self.value_fingerprint,
            "status": self.status,
            "current": self.current,
            "authoritative": self.authoritative,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class EvidenceValidationResult:
    states: tuple[EvidenceState, ...]
    findings: tuple[AuthorityFinding, ...]

    def state_by_id(self) -> dict[str, EvidenceState]:
        return {item.evidence_id: item for item in self.states}

    def is_authoritative(self, evidence_id: str) -> bool:
        state = self.state_by_id().get(evidence_id)
        return bool(state is not None and state.authoritative)

    def claim_is_authoritative(self, claim_key: str) -> bool:
        return any(
            item.claim_key == claim_key and item.authoritative
            for item in self.states
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "states": [item.to_dict() for item in self.states],
            "findings": [item.to_dict() for item in self.findings],
        }


def _approved_method(
    record: EvidenceRecord,
    approved_derivations: Mapping[str, Iterable[tuple[str, str]]],
) -> bool:
    for scope, methods in approved_derivations.items():
        if record.claim_key == scope or record.claim_key.startswith(scope + "."):
            return (
                record.derivation_method_id,
                record.derivation_method_version,
            ) in set(methods)
    return False


def validate_evidence_records(
    registry: TrustedSourceRegistry | Mapping[str, Any],
    records: Sequence[EvidenceRecord | Mapping[str, Any]],
    *,
    tenant_id: str,
    site_id: str,
    as_of: datetime,
    asserted_actor_roles: Mapping[str, Iterable[str]] | None = None,
    approved_derivations: Mapping[
        str,
        Iterable[tuple[str, str]],
    ] | None = None,
    principal_roles: Iterable[str] = (),
) -> EvidenceValidationResult:
    """Validate current evidence without selecting winners or changing status."""

    trusted = (
        registry
        if isinstance(registry, TrustedSourceRegistry)
        else TrustedSourceRegistry.from_mapping(registry)
    )
    tenant_id = validate_stable_id(tenant_id, "tenantId")
    site_id = validate_stable_id(site_id, "siteId")
    if trusted.tenant_id != tenant_id:
        raise IndustrialAssetAuthorityError(
            "authority_registry_tenant_mismatch",
            "Trusted source registry belongs to another tenant.",
        )
    now = _as_utc(as_of)
    parsed = tuple(
        item if isinstance(item, EvidenceRecord) else EvidenceRecord.from_mapping(item)
        for item in records
    )
    by_id = {item.evidence_id: item for item in parsed}
    if len(by_id) != len(parsed):
        raise IndustrialAssetAuthorityError(
            "duplicate_evidence_id",
            "Evidence IDs must be unique.",
        )
    actors = {
        key: frozenset(value)
        for key, value in (asserted_actor_roles or {}).items()
    }
    methods = approved_derivations or {}
    reader_roles = frozenset(principal_roles)
    sources = trusted.by_id()
    base_blockers: dict[str, set[str]] = {}

    for record in parsed:
        blockers: set[str] = set()
        source = sources.get(record.trusted_source_id)
        if record.tenant_id != tenant_id:
            blockers.add("evidence_tenant_mismatch")
        if source is None:
            blockers.add("trusted_source_missing")
        else:
            if source.owner_tenant_id != tenant_id:
                blockers.add("trusted_source_tenant_mismatch")
            if source.status != "active":
                blockers.add(
                    "trusted_source_revoked"
                    if source.status == "revoked"
                    else "trusted_source_suspended"
                )
            if (
                source.allowed_site_ids
                and site_id not in source.allowed_site_ids
            ):
                blockers.add("trusted_source_site_not_allowed")
            if not _claim_is_permitted(
                record.claim_key,
                source.permitted_claim_scopes,
            ):
                blockers.add("claim_scope_not_permitted")
            if (
                source.current_revision is not None
                and record.source_revision != source.current_revision
            ):
                blockers.add("trusted_source_revision_stale")
            if source.allowed_roles and not (
                source.allowed_roles & reader_roles
            ):
                blockers.add("trusted_source_access_denied")
            if (
                source.maximum_age_days is not None
                and now
                > record.asserted_at
                + timedelta(days=source.maximum_age_days)
            ):
                blockers.add("evidence_freshness_expired")
        if record.asserted_at > now:
            blockers.add("evidence_asserted_in_future")
        if record.valid_from is not None and record.valid_from > now:
            blockers.add("evidence_not_yet_valid")
        if record.valid_until is not None and now > record.valid_until:
            blockers.add("evidence_expired")
        if record.revoked_at is not None and record.revoked_at <= now:
            blockers.add("evidence_revoked")
        if record.status == "authored" and not (
            actors.get(record.asserted_by, frozenset()) & AUTHORITY_ROLES
        ):
            blockers.add("authored_evidence_actor_not_authorized")
        if record.status == "derived" and not _approved_method(record, methods):
            blockers.add("derivation_method_not_approved")
        base_blockers[record.evidence_id] = blockers

    resolved: dict[str, EvidenceState] = {}
    visiting: set[str] = set()

    def resolve(record: EvidenceRecord) -> EvidenceState:
        known = resolved.get(record.evidence_id)
        if known is not None:
            return known
        blockers = set(base_blockers[record.evidence_id])
        if record.evidence_id in visiting:
            blockers.add("evidence_derivation_cycle")
        elif record.status == "derived":
            visiting.add(record.evidence_id)
            for input_id in record.input_evidence_ids:
                input_record = by_id.get(input_id)
                if input_record is None:
                    blockers.add("derived_input_missing")
                    continue
                state = resolve(input_record)
                if not state.current:
                    blockers.add("derived_input_stale")
                if not state.authoritative:
                    blockers.add("derived_input_not_authoritative")
            visiting.discard(record.evidence_id)
        current = not blockers
        state = EvidenceState(
            evidence_id=record.evidence_id,
            claim_key=record.claim_key,
            value_fingerprint=record.value_fingerprint,
            status=record.status,
            current=current,
            authoritative=(
                current and record.status in {"authored", "derived"}
            ),
            blockers=tuple(sorted(blockers)),
        )
        resolved[record.evidence_id] = state
        return state

    for record in parsed:
        resolve(record)

    findings: list[AuthorityFinding] = []
    for state in resolved.values():
        for code in state.blockers:
            findings.append(
                AuthorityFinding(
                    code=code,
                    severity="error",
                    evidence_ids=(state.evidence_id,),
                    claim_key=state.claim_key,
                    message=(
                        f"Evidence {state.evidence_id} cannot satisfy an "
                        f"authoritative claim: {code}."
                    ),
                )
            )

    conflict_groups: dict[tuple[str, str], list[EvidenceRecord]] = {}
    for record in parsed:
        state = resolved[record.evidence_id]
        if state.authoritative:
            conflict_groups.setdefault(
                (record.subject_fingerprint, record.claim_key),
                [],
            ).append(record)
    for (_, claim_key), candidates in conflict_groups.items():
        fingerprints = {item.value_fingerprint for item in candidates}
        if len(fingerprints) <= 1:
            continue
        evidence_ids = tuple(sorted(item.evidence_id for item in candidates))
        findings.append(
            AuthorityFinding(
                code="evidence_conflict",
                severity="error",
                evidence_ids=evidence_ids,
                claim_key=claim_key,
                message=(
                    "Current authoritative evidence disagrees; no source was "
                    "selected silently."
                ),
            )
        )
        for evidence_id in evidence_ids:
            state = resolved[evidence_id]
            resolved[evidence_id] = replace(
                state,
                authoritative=False,
                blockers=tuple(
                    sorted(set(state.blockers) | {"evidence_conflict"})
                ),
            )

    unique_findings = {item.finding_id: item for item in findings}
    return EvidenceValidationResult(
        states=tuple(
            sorted(resolved.values(), key=lambda item: item.evidence_id)
        ),
        findings=tuple(
            sorted(
                unique_findings.values(),
                key=lambda item: (
                    item.severity,
                    item.code,
                    item.evidence_ids,
                    item.finding_id,
                ),
            )
        ),
    )
