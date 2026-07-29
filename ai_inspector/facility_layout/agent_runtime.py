"""Trusted Sage runtime for Facility Layout observation and preview.

The browser supplies only revision-bound identity and ephemeral editor facts.
This adapter reloads every authoritative document, compiles the bounded P9
contexts, serves signed read cursors, and delegates preview creation to the P8
transaction service. It never accepts model-authored geometry or commits a
layout.
"""

from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from .authorization import FacilityPrincipal, require_facility_action
from .digest import build_facility_layout_digest
from .errors import (
    FacilityConflictError,
    FacilityLayoutError,
    FacilityNotFoundError,
)
from .observation import (
    MAXIMUM_READ_IDS,
    MAXIMUM_READ_PAGE_SIZE,
    TrustedFacilityContext,
    TrustedFacilitySource,
    build_facility_layout_observation,
    trusted_facility_source,
)
from .semantic_plan import (
    SemanticFacilityPlanError,
    compile_semantic_facility_plan,
)


FACILITY_LAYOUT_AGENT_RUNTIME_VERSION = 1
FACILITY_LAYOUT_AGENT_MAXIMUM_CALLS_PER_TURN = 8
FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES = 16_384
FACILITY_LAYOUT_AGENT_CURSOR_TTL_SECONDS = 300
FACILITY_LAYOUT_AGENT_TURN_TTL_SECONDS = 600

_READ_TOOLS = frozenset(
    {
        "search_industrial_assets",
        "inspect_facility_entities",
        "inspect_facility_region",
        "inspect_facility_findings",
        "inspect_process_bindings",
    }
)
_ENTITY_COLLECTIONS = {
    "placement": ("placements", "placementId"),
    "zone": ("zones", "zoneId"),
    "route": ("routes", "routeId"),
    "utility_network": ("utilityNetworks", "utilityNetworkId"),
}


class FacilityLayoutAgentRuntimeError(ValueError):
    """Fail-closed P9 runtime error with a stable public code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.details = deepcopy(dict(details or {}))


@dataclass(frozen=True)
class FacilityAgentContextBundle:
    state: TrustedFacilityContext
    evidence: TrustedFacilityContext
    digest: dict[str, Any]
    shell_document: dict[str, Any]
    policy_document: dict[str, Any]


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_payload_invalid",
            "Facility Layout agent payload must be finite JSON.",
        ) from exc


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _clean_text(value: Any, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _stable_id(value: Any, label: str) -> str:
    text = _clean_text(value, 128)
    if (
        not text
        or not text[0].isalnum()
        or any(
            not (character.isalnum() or character in "._:@+-")
            for character in text
        )
    ):
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_id_invalid",
            f"{label} must be a stable ID.",
        )
    return text


def _revision(value: Any, label: str) -> str:
    text = str(value or "")
    if (
        len(text) != 64
        or any(character not in "0123456789abcdef" for character in text)
    ):
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_revision_invalid",
            f"{label} must be a lowercase SHA-256 revision.",
        )
    return text


def _bounded_page_size(value: Any) -> int:
    if value is None:
        return min(25, MAXIMUM_READ_PAGE_SIZE)
    if isinstance(value, bool):
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_page_size_invalid",
            "pageSize must be an integer.",
        )
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_page_size_invalid",
            "pageSize must be an integer.",
        ) from exc
    if result < 1 or result > MAXIMUM_READ_PAGE_SIZE:
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_page_size_invalid",
            f"pageSize must be between 1 and {MAXIMUM_READ_PAGE_SIZE}.",
        )
    return result


def _bounded_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_ids_invalid",
            "ids must be an array.",
        )
    if len(value) > MAXIMUM_READ_IDS:
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_ids_exceeded",
            f"At most {MAXIMUM_READ_IDS} IDs may be inspected.",
        )
    return sorted({_stable_id(item, "id") for item in value})


def _extract_created_ids(operations: Sequence[Mapping[str, Any]]) -> list[str]:
    identifiers: set[str] = set()
    for operation in operations:
        if not isinstance(operation, Mapping):
            continue
        for key, value in operation.items():
            if (
                isinstance(key, str)
                and key.endswith("Id")
                and isinstance(value, str)
                and value
            ):
                identifiers.add(value)
    return sorted(identifiers)


class FacilityLayoutAgentRuntime:
    """Revision-bound Facility Layout context, reads, and preview gateway."""

    def __init__(
        self,
        *,
        service: Any,
        shell_repository: Any,
        policy_repository: Any,
        vehicle_repository: Any,
        asset_catalog_provider: Callable[
            [FacilityPrincipal, str], Sequence[Mapping[str, Any]]
        ],
        process_catalog_provider: Callable[
            [FacilityPrincipal, str, Mapping[str, Any]],
            Sequence[Mapping[str, Any]],
        ]
        | None = None,
        evidence_provider: Callable[
            [
                FacilityPrincipal,
                str,
                Mapping[str, Any],
                Mapping[str, Any],
                Mapping[str, Any],
                Sequence[Mapping[str, Any]],
            ],
            Mapping[str, Any],
        ]
        | None = None,
        capabilities_provider: Callable[
            [FacilityPrincipal, str], Mapping[str, Any]
        ]
        | None = None,
        cursor_secret: bytes | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.service = service
        self.shell_repository = shell_repository
        self.policy_repository = policy_repository
        self.vehicle_repository = vehicle_repository
        self.asset_catalog_provider = asset_catalog_provider
        self.process_catalog_provider = process_catalog_provider
        self.evidence_provider = evidence_provider
        self.capabilities_provider = capabilities_provider
        self.cursor_secret = cursor_secret or secrets.token_bytes(32)
        if len(self.cursor_secret) < 32:
            raise ValueError("cursor_secret must contain at least 32 bytes")
        self.clock = clock or time.time
        self._turn_lock = threading.RLock()
        self._turn_calls: dict[tuple[str, str, str, str], tuple[float, int]] = {}

    @staticmethod
    def _asset_source_document(
        values: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        assets = []
        for raw in values:
            if not isinstance(raw, Mapping):
                continue
            definition = raw.get("definition")
            if not isinstance(definition, Mapping):
                definition = raw.get("document")
            if not isinstance(definition, Mapping):
                definition = raw
            revision = (
                raw.get("assetDefinitionRevision")
                or raw.get("revision")
                or _fingerprint(definition)
            )
            assets.append(
                {
                    "revision": _revision(
                        revision,
                        "assetDefinitionRevision",
                    ),
                    "document": deepcopy(dict(definition)),
                }
            )
        assets.sort(
            key=lambda item: (
                str(item["document"].get("assetId") or ""),
                item["revision"],
            )
        )
        return {"assets": assets}

    def _published_vehicles(
        self,
        principal: FacilityPrincipal,
        site_id: str,
    ) -> list[dict[str, Any]]:
        vehicles = []
        for summary in self.vehicle_repository.list_documents(
            principal,
            site_id=site_id,
        ):
            if not isinstance(summary, Mapping):
                continue
            vehicle_id = summary.get("vehicleProfileId")
            revision = summary.get("publishedRevision")
            if not vehicle_id or not revision:
                continue
            try:
                envelope = self.vehicle_repository.get_published(
                    principal,
                    site_id=site_id,
                    authority_id=str(vehicle_id),
                    revision=str(revision),
                )
            except FacilityNotFoundError:
                continue
            vehicles.append(
                {
                    "revision": envelope.revision,
                    "document": deepcopy(dict(envelope.document)),
                }
            )
        return vehicles

    @staticmethod
    def _default_evidence(
        _principal: FacilityPrincipal,
        _site_id: str,
        layout: Mapping[str, Any],
        shell: Mapping[str, Any],
        policy: Mapping[str, Any],
        assets: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        unresolved = []
        for source_kind, document in (
            ("layout", layout),
            ("facility_shell", shell),
            ("facility_policy", policy),
        ):
            for index, raw in enumerate(document.get("unresolvedItems", [])):
                if not isinstance(raw, Mapping):
                    continue
                unresolved.append(
                    {
                        "findingId": str(
                            raw.get("findingId")
                            or f"{source_kind}-unresolved-{index + 1}"
                        ),
                        "code": str(
                            raw.get("code") or "authority_review_required"
                        ),
                        "message": _clean_text(raw.get("message"), 600),
                        "subjectRefs": [source_kind],
                    }
                )
        records = []
        for source in (layout, shell, policy, *assets):
            for raw in source.get("evidenceRecords", []):
                if isinstance(raw, Mapping):
                    records.append(deepcopy(dict(raw)))
        return {
            "records": records,
            "unresolvedFacts": unresolved,
        }

    def _proposal_document(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        proposal_id: str | None,
    ) -> Mapping[str, Any] | None:
        if not proposal_id:
            return None
        try:
            preview = self.service.get_layout_proposal_preview(
                principal,
                site_id,
                layout_id,
                _stable_id(proposal_id, "proposalId"),
            )
        except (FacilityNotFoundError, FacilityConflictError):
            return None
        alternative = (
            preview.get("alternative")
            if isinstance(preview.get("alternative"), Mapping)
            else {}
        )
        binding = (
            preview.get("transactionBinding")
            if isinstance(preview.get("transactionBinding"), Mapping)
            else {}
        )
        operations = [
            item
            for item in alternative.get("operations", [])
            if isinstance(item, Mapping)
        ]
        return {
            "proposalId": preview.get("proposalId"),
            "layoutId": layout_id,
            "baseRevision": binding.get("baseRevision"),
            "status": "preview",
            "selectedAlternativeId": alternative.get("alternativeId"),
            "entityIds": _extract_created_ids(operations),
            "counts": {
                "operations": len(operations),
                "routeProposals": len(
                    alternative.get("routeProposals", [])
                    if isinstance(
                        alternative.get("routeProposals"),
                        list,
                    )
                    else []
                ),
            },
            "pendingApproval": True,
        }

    def _receipt_documents(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        receipt_ids: Sequence[Any] | None,
    ) -> list[dict[str, Any]]:
        result = []
        for raw_id in list(receipt_ids or [])[-6:]:
            try:
                receipt_id = _stable_id(raw_id, "receiptId")
                receipt = self.service.get_layout_receipt(
                    principal,
                    site_id,
                    layout_id,
                    receipt_id,
                )
            except (FacilityNotFoundError, FacilityLayoutAgentRuntimeError):
                continue
            result.append(deepcopy(dict(receipt)))
        return result

    def resolve_context(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        layout_id: str,
        expected_revision: str | None = None,
        live_facts: Mapping[str, Any] | None = None,
        proposal_id: str | None = None,
        receipt_ids: Sequence[Any] | None = None,
    ) -> FacilityAgentContextBundle:
        site_id = _stable_id(site_id, "siteId")
        layout_id = _stable_id(layout_id, "layoutId")
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        layout_receipt = self.service.get_layout(
            principal,
            site_id,
            layout_id,
        )
        layout = deepcopy(dict(layout_receipt["layout"]))
        current_revision = _revision(
            layout_receipt["revision"],
            "layout revision",
        )
        if expected_revision is not None:
            requested_revision = _revision(
                expected_revision,
                "expected revision",
            )
            if requested_revision != current_revision:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_layout_revision_conflict",
                    "The Facility Layout changed before Sage observed it.",
                    status_code=409,
                    details={"currentRevision": current_revision},
                )
        shell_ref = layout.get("sourceShellRef")
        policy_ref = layout.get("policySetRef")
        if not isinstance(shell_ref, Mapping) or not isinstance(
            policy_ref,
            Mapping,
        ):
            raise FacilityLayoutAgentRuntimeError(
                "facility_layout_authority_missing",
                "Facility Layout shell or policy authority is missing.",
                status_code=409,
            )
        shell = self.shell_repository.get_published(
            principal,
            site_id=site_id,
            authority_id=str(shell_ref.get("shellId") or ""),
            revision=str(shell_ref.get("shellRevision") or ""),
        )
        policy = self.policy_repository.get_published(
            principal,
            site_id=site_id,
            authority_id=str(policy_ref.get("policySetId") or ""),
            revision=str(policy_ref.get("policySetRevision") or ""),
        )
        raw_assets = list(self.asset_catalog_provider(principal, site_id))
        asset_source_document = self._asset_source_document(raw_assets)
        process_maps = (
            list(self.process_catalog_provider(principal, site_id, layout))
            if self.process_catalog_provider is not None
            else []
        )
        evidence_document = (
            self.evidence_provider(
                principal,
                site_id,
                layout,
                shell.document,
                policy.document,
                [
                    item["document"]
                    for item in asset_source_document["assets"]
                ],
            )
            if self.evidence_provider is not None
            else self._default_evidence(
                principal,
                site_id,
                layout,
                shell.document,
                policy.document,
                [
                    item["document"]
                    for item in asset_source_document["assets"]
                ],
            )
        )
        capabilities = (
            dict(self.capabilities_provider(principal, site_id))
            if self.capabilities_provider is not None
            else {
                "read": True,
                "semanticPlanning": True,
                "semanticPreview": (
                    "*" in principal.action_set
                    or "proposal.create" in principal.action_set
                ),
                "approval": (
                    "*" in principal.action_set
                    or "proposal.approve" in principal.action_set
                ),
                "apply": (
                    "*" in principal.action_set
                    or "proposal.apply" in principal.action_set
                ),
            }
        )
        proposal_document = self._proposal_document(
            principal,
            site_id,
            layout_id,
            proposal_id,
        )
        receipts = self._receipt_documents(
            principal,
            site_id,
            layout_id,
            receipt_ids,
        )
        sources: dict[str, TrustedFacilitySource | None] = {
            "layout": trusted_facility_source(
                "facility_layout",
                layout,
                revision=current_revision,
                provider="facility-layout-repository",
            ),
            "assets": trusted_facility_source(
                "industrial_asset_catalog",
                asset_source_document,
                provider="industrial-asset-catalog",
            ),
            "shell": trusted_facility_source(
                "facility_shell",
                shell.document,
                revision=shell.revision,
                provider="facility-shell-repository",
            ),
            "policy": trusted_facility_source(
                "facility_policy",
                policy.document,
                revision=policy.revision,
                provider="facility-policy-repository",
            ),
            "evidence": trusted_facility_source(
                "facility_evidence",
                evidence_document,
                provider="facility-evidence-resolver",
            ),
            "vehicles": trusted_facility_source(
                "vehicle_profiles",
                {"vehicles": self._published_vehicles(principal, site_id)},
                provider="vehicle-profile-repository",
            ),
            "process": trusted_facility_source(
                "process_maps",
                {"processMaps": process_maps},
                provider="process-map-repository",
            ),
            "diagnostics": trusted_facility_source(
                "facility_diagnostics",
                {
                    "findings": deepcopy(
                        layout_receipt.get("findings", [])
                    ),
                    "metrics": {},
                },
                provider="facility-layout-validator",
            ),
            "capabilities": trusted_facility_source(
                "facility_capabilities",
                capabilities,
                provider="facility-layout-authorization",
            ),
            "proposal": (
                trusted_facility_source(
                    "facility_proposal",
                    proposal_document,
                    provider="facility-layout-transaction-runtime",
                )
                if proposal_document is not None
                else None
            ),
            "receipts": (
                trusted_facility_source(
                    "facility_receipts",
                    {"receipts": receipts},
                    provider="facility-layout-receipt-store",
                )
                if receipts
                else None
            ),
        }
        observation = build_facility_layout_observation(
            sources["layout"],
            sources["assets"],
            shell_source=sources["shell"],
            policy_source=sources["policy"],
            evidence_source=sources["evidence"],
            vehicle_source=sources["vehicles"],
            process_source=sources["process"],
            diagnostics_source=sources["diagnostics"],
            capabilities_source=sources["capabilities"],
            proposal_source=sources["proposal"],
            receipts_source=sources["receipts"],
            live_facts=live_facts,
        )
        digest = build_facility_layout_digest(
            observation["state"],
            observation["evidence"],
        )
        return FacilityAgentContextBundle(
            state=observation["state"],
            evidence=observation["evidence"],
            digest=digest,
            shell_document=deepcopy(dict(shell.document)),
            policy_document=deepcopy(dict(policy.document)),
        )

    def _principal_binding(
        self,
        principal: FacilityPrincipal,
    ) -> dict[str, Any]:
        return {
            "tenantId": principal.tenant_id,
            "principalId": principal.principal_id,
            "roles": list(principal.roles),
        }

    def _encode_cursor(self, payload: Mapping[str, Any]) -> str:
        raw = _canonical_bytes(payload)
        signature = hmac.new(
            self.cursor_secret,
            raw,
            hashlib.sha256,
        ).digest()
        encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        encoded_signature = (
            base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
        )
        return f"flc1.{encoded}.{encoded_signature}"

    def _decode_cursor(
        self,
        cursor: str,
        *,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        revision: str,
        tool_name: str,
        filter_hash: str,
    ) -> int:
        try:
            prefix, encoded, encoded_signature = str(cursor).split(".", 2)
            if prefix != "flc1":
                raise ValueError
            raw = base64.urlsafe_b64decode(
                encoded + "=" * (-len(encoded) % 4)
            )
            signature = base64.urlsafe_b64decode(
                encoded_signature + "=" * (-len(encoded_signature) % 4)
            )
            expected = hmac.new(
                self.cursor_secret,
                raw,
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            payload = json.loads(raw.decode("ascii"))
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise FacilityLayoutAgentRuntimeError(
                "facility_agent_cursor_invalid",
                "The Facility Layout read cursor is invalid.",
            ) from exc
        expected_binding = {
            **self._principal_binding(principal),
            "siteId": site_id,
            "layoutId": layout_id,
            "revision": revision,
            "tool": tool_name,
            "filterHash": filter_hash,
        }
        if any(
            payload.get(key) != value
            for key, value in expected_binding.items()
        ):
            raise FacilityLayoutAgentRuntimeError(
                "facility_agent_cursor_scope_mismatch",
                "The Facility Layout read cursor belongs to another scope.",
                status_code=404,
            )
        if float(payload.get("expiresAt") or 0) < self.clock():
            raise FacilityLayoutAgentRuntimeError(
                "facility_agent_cursor_expired",
                "The Facility Layout read cursor expired.",
                status_code=409,
            )
        offset = payload.get("offset")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise FacilityLayoutAgentRuntimeError(
                "facility_agent_cursor_invalid",
                "The Facility Layout read cursor is invalid.",
            )
        return offset

    def _next_cursor(
        self,
        *,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        revision: str,
        tool_name: str,
        filter_hash: str,
        offset: int,
    ) -> str:
        return self._encode_cursor(
            {
                **self._principal_binding(principal),
                "siteId": site_id,
                "layoutId": layout_id,
                "revision": revision,
                "tool": tool_name,
                "filterHash": filter_hash,
                "offset": offset,
                "expiresAt": round(
                    self.clock()
                    + FACILITY_LAYOUT_AGENT_CURSOR_TTL_SECONDS,
                    3,
                ),
            }
        )

    def _consume_turn_call(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        turn_id: str,
    ) -> None:
        turn_id = _stable_id(turn_id, "turnId")
        now = self.clock()
        key = (
            principal.tenant_id,
            principal.principal_id,
            site_id,
            f"{layout_id}:{turn_id}",
        )
        with self._turn_lock:
            stale = [
                item
                for item, (updated, _) in self._turn_calls.items()
                if now - updated > FACILITY_LAYOUT_AGENT_TURN_TTL_SECONDS
            ]
            for item in stale:
                self._turn_calls.pop(item, None)
            _, count = self._turn_calls.get(key, (now, 0))
            if count >= FACILITY_LAYOUT_AGENT_MAXIMUM_CALLS_PER_TURN:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_turn_budget_exceeded",
                    "The Facility Layout observation budget is exhausted.",
                    status_code=429,
                )
            self._turn_calls[key] = (now, count + 1)

    def _page(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        offset: int,
        page_size: int,
        envelope: Mapping[str, Any],
        cursor_factory: Callable[[int], str],
    ) -> dict[str, Any]:
        end = min(len(records), offset + page_size)
        page = [deepcopy(dict(item)) for item in records[offset:end]]
        result = {
            **deepcopy(dict(envelope)),
            "records": page,
            "returnedCount": len(page),
            "totalCount": len(records),
            "nextCursor": cursor_factory(end) if end < len(records) else None,
        }
        while (
            len(_canonical_bytes(result))
            > FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES
            and result["records"]
        ):
            result["records"].pop()
            result["returnedCount"] = len(result["records"])
            next_offset = offset + len(result["records"])
            result["nextCursor"] = cursor_factory(next_offset)
        if len(_canonical_bytes(result)) > FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES:
            raise FacilityLayoutAgentRuntimeError(
                "facility_agent_response_budget_exceeded",
                "The Facility Layout read response exceeded its bound.",
            )
        return result

    def execute_read_tool(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        layout_id: str,
        expected_revision: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        turn_id: str,
        live_facts: Mapping[str, Any] | None = None,
        proposal_id: str | None = None,
        receipt_ids: Sequence[Any] | None = None,
    ) -> dict[str, Any]:
        if tool_name not in _READ_TOOLS:
            raise FacilityLayoutAgentRuntimeError(
                "facility_agent_tool_unknown",
                "The Facility Layout observation tool is unavailable.",
                status_code=404,
            )
        if not isinstance(arguments, Mapping):
            raise FacilityLayoutAgentRuntimeError(
                "facility_agent_arguments_invalid",
                "Facility Layout tool arguments must be an object.",
            )
        site_id = _stable_id(site_id, "siteId")
        layout_id = _stable_id(layout_id, "layoutId")
        expected_revision = _revision(
            expected_revision,
            "expectedRevision",
        )
        self._consume_turn_call(
            principal,
            site_id,
            layout_id,
            turn_id,
        )
        bundle = self.resolve_context(
            principal,
            site_id=site_id,
            layout_id=layout_id,
            expected_revision=expected_revision,
            live_facts=live_facts,
            proposal_id=proposal_id,
            receipt_ids=receipt_ids,
        )
        state = bundle.state
        revision = str(state["identity"]["revision"])
        args = deepcopy(dict(arguments))
        cursor = args.pop("cursor", None)
        filter_hash = _fingerprint(args)
        offset = (
            self._decode_cursor(
                str(cursor),
                principal=principal,
                site_id=site_id,
                layout_id=layout_id,
                revision=revision,
                tool_name=tool_name,
                filter_hash=filter_hash,
            )
            if cursor
            else 0
        )
        page_size = _bounded_page_size(args.get("pageSize"))
        base_envelope = {
            "ok": True,
            "runtimeVersion": FACILITY_LAYOUT_AGENT_RUNTIME_VERSION,
            "tool": tool_name,
            "siteId": site_id,
            "layoutId": layout_id,
            "revision": revision,
            "authoritative": True,
        }

        def next_cursor(next_offset: int) -> str:
            return self._next_cursor(
                principal=principal,
                site_id=site_id,
                layout_id=layout_id,
                revision=revision,
                tool_name=tool_name,
                filter_hash=filter_hash,
                offset=next_offset,
            )

        if tool_name == "search_industrial_assets":
            query = _clean_text(args.get("query"), 120).lower()
            category = _clean_text(args.get("category"), 80).lower()
            capability = _clean_text(
                args.get("capabilityId"),
                128,
            ).lower()
            records = [
                item
                for item in state.get("assets", [])
                if isinstance(item, Mapping)
                and (
                    not query
                    or query
                    in " ".join(
                        (
                            str(item.get("assetId") or ""),
                            str(item.get("displayName") or ""),
                            str(item.get("category") or ""),
                            " ".join(item.get("capabilityIds", [])),
                        )
                    ).lower()
                )
                and (
                    not category
                    or str(item.get("category") or "").lower() == category
                )
                and (
                    not capability
                    or capability
                    in {
                        str(value).lower()
                        for value in item.get("capabilityIds", [])
                    }
                )
            ]
            return self._page(
                records,
                offset=offset,
                page_size=page_size,
                envelope=base_envelope,
                cursor_factory=next_cursor,
            )

        if tool_name == "inspect_facility_entities":
            kind = str(args.get("entityKind") or "")
            if kind not in _ENTITY_COLLECTIONS:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_entity_kind_invalid",
                    "entityKind is unsupported.",
                )
            ids = _bounded_ids(args.get("ids"))
            collection, id_field = _ENTITY_COLLECTIONS[kind]
            index = {
                str(item.get(id_field)): item
                for item in state.get(collection, [])
                if isinstance(item, Mapping) and item.get(id_field)
            }
            return {
                **base_envelope,
                "entityKind": kind,
                "records": [
                    deepcopy(dict(index[item]))
                    for item in ids
                    if item in index
                ],
                "unresolvedIds": [
                    item for item in ids if item not in index
                ],
            }

        if tool_name == "inspect_facility_region":
            kind = str(args.get("regionKind") or "")
            region_id = _stable_id(args.get("regionId"), "regionId")
            records = []
            if kind == "zone":
                records = [
                    deepcopy(dict(item))
                    for item in state.get("zones", [])
                    if isinstance(item, Mapping)
                    and item.get("zoneId") == region_id
                ]
            elif kind == "shell_feature":
                records = [
                    deepcopy(dict(item))
                    for item in bundle.shell_document.get("features", [])
                    if isinstance(item, Mapping)
                    and item.get("featureId") == region_id
                ]
            else:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_region_kind_invalid",
                    "regionKind is unsupported.",
                )
            return {
                **base_envelope,
                "regionKind": kind,
                "records": records,
                "unresolvedIds": [] if records else [region_id],
            }

        if tool_name == "inspect_facility_findings":
            ids = (
                set(_bounded_ids(args.get("ids")))
                if "ids" in args
                else set()
            )
            code = _clean_text(args.get("code"), 128)
            records = [
                item
                for item in state.get("diagnostics", {}).get("findings", [])
                if isinstance(item, Mapping)
                and (
                    not ids
                    or str(item.get("findingId") or "") in ids
                )
                and (not code or str(item.get("code") or "") == code)
            ]
            return self._page(
                records,
                offset=offset,
                page_size=page_size,
                envelope=base_envelope,
                cursor_factory=next_cursor,
            )

        ids = (
            set(_bounded_ids(args.get("ids")))
            if "ids" in args
            else set()
        )
        process_map_id = _clean_text(args.get("processMapId"), 128)
        records = [
            item
            for item in state.get("processBindings", [])
            if isinstance(item, Mapping)
            and (
                not ids
                or str(item.get("processBindingId") or "") in ids
            )
            and (
                not process_map_id
                or str(item.get("processMapId") or "") == process_map_id
            )
        ]
        return self._page(
            records,
            offset=offset,
            page_size=page_size,
            envelope=base_envelope,
            cursor_factory=next_cursor,
        )

    def build_preview(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        layout_id: str,
        expected_revision: str,
        semantic_plan: Mapping[str, Any],
        live_facts: Mapping[str, Any] | None = None,
        proposal_id: str | None = None,
        receipt_ids: Sequence[Any] | None = None,
    ) -> dict[str, Any]:
        bundle = self.resolve_context(
            principal,
            site_id=site_id,
            layout_id=layout_id,
            expected_revision=expected_revision,
            live_facts=live_facts,
            proposal_id=proposal_id,
            receipt_ids=receipt_ids,
        )
        if not bundle.state.get("savedStateCurrent"):
            raise FacilityLayoutAgentRuntimeError(
                "facility_layout_saved_state_required",
                "Save or discard editor changes before building a proposal.",
                status_code=409,
            )
        try:
            compiled = compile_semantic_facility_plan(
                semantic_plan,
                state=bundle.state,
                evidence=bundle.evidence,
            )
            proposals = self.service.create_layout_proposals(
                principal,
                str(bundle.state["identity"]["siteId"]),
                str(bundle.state["identity"]["layoutId"]),
                str(bundle.state["identity"]["revision"]),
                compiled["plannerRequest"],
            )
        except SemanticFacilityPlanError as error:
            raise FacilityLayoutAgentRuntimeError(
                error.code,
                str(error),
                details={"findings": deepcopy(error.findings)},
            ) from error
        except FacilityLayoutError as error:
            raise FacilityLayoutAgentRuntimeError(
                error.code,
                str(error),
                status_code=error.status_code,
                details=error.details,
            ) from error
        return {
            "ok": True,
            "runtimeVersion": FACILITY_LAYOUT_AGENT_RUNTIME_VERSION,
            "previewOnly": True,
            "saved": False,
            "identity": deepcopy(bundle.state["identity"]),
            "semanticPlan": {
                "planId": compiled["plan"]["planId"],
                "planHash": compiled["planHash"],
                "bindingHash": compiled["bindingHash"],
                "summary": deepcopy(compiled["semanticSummary"]),
                "assumptions": deepcopy(compiled["assumptions"]),
                "unresolvedItems": deepcopy(compiled["unresolvedItems"]),
                "findings": deepcopy(compiled["findings"]),
            },
            "plannerRequest": deepcopy(compiled["plannerRequest"]),
            "proposal": proposals,
            "selectedProposalId": proposals.get("selectedProposalId"),
            "canonicalReceipt": None,
            "message": (
                "Facility Layout ghost preview created. It is not saved and "
                "requires explicit approval before atomic apply."
            ),
        }


__all__ = [
    "FACILITY_LAYOUT_AGENT_CURSOR_TTL_SECONDS",
    "FACILITY_LAYOUT_AGENT_MAXIMUM_CALLS_PER_TURN",
    "FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES",
    "FACILITY_LAYOUT_AGENT_RUNTIME_VERSION",
    "FacilityAgentContextBundle",
    "FacilityLayoutAgentRuntime",
    "FacilityLayoutAgentRuntimeError",
]
