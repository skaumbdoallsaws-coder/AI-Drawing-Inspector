"""Authenticated principal ingress for controlled Facility Layout pilots."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import re
from typing import Mapping

from fastapi import HTTPException, Request

from .authorization import FacilityPrincipal, local_facility_principal


FACILITY_IDENTITY_CONFIG_ENV = "INSPECTORPRO_FACILITY_PILOT_IDENTITIES"
FACILITY_MAKER_CHECKER_ENV = (
    "INSPECTORPRO_FACILITY_REQUIRE_DISTINCT_APPROVER"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})
_MAX_IDENTITIES = 32


class FacilityIdentityConfigurationError(RuntimeError):
    """Raised when pilot identity policy is absent or unsafe."""


def maker_checker_required_from_environment(
    environ: Mapping[str, str] | None = None,
) -> bool:
    source = os.environ if environ is None else environ
    raw = str(source.get(FACILITY_MAKER_CHECKER_ENV, "") or "")
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise FacilityIdentityConfigurationError(
        f"{FACILITY_MAKER_CHECKER_ENV} must be a boolean value."
    )


def _unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={
            "error": {
                "code": "facility_authentication_required",
                "message": "A valid Facility Layout pilot identity is required.",
            }
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


def _parse_bearer(request: Request) -> str:
    value = request.headers.get("Authorization", "").strip()
    scheme, separator, token = value.partition(" ")
    if (
        not separator
        or scheme.lower() != "bearer"
        or token != token.strip()
        or not 32 <= len(token) <= 512
        or any(ord(char) < 33 or ord(char) > 126 for char in token)
    ):
        raise _unauthenticated()
    return token


@dataclass(frozen=True)
class FacilityPrincipalResolver:
    """Resolve either one local principal or a pinned pilot bearer identity."""

    identities: tuple[tuple[str, FacilityPrincipal], ...]
    local_site_id: str
    local_tenant_id: str = "local"

    @property
    def mode(self) -> str:
        return "bearer" if self.identities else "local"

    @property
    def authenticated(self) -> bool:
        return bool(self.identities)

    @classmethod
    def from_environment(
        cls,
        *,
        site_id: str,
        tenant_id: str = "local",
        environ: Mapping[str, str] | None = None,
        require_authenticated: bool = False,
    ) -> "FacilityPrincipalResolver":
        source = os.environ if environ is None else environ
        raw = str(source.get(FACILITY_IDENTITY_CONFIG_ENV, "") or "").strip()
        if not raw:
            if require_authenticated:
                raise FacilityIdentityConfigurationError(
                    f"{FACILITY_IDENTITY_CONFIG_ENV} is required when "
                    "maker-checker policy is enabled."
                )
            return cls((), site_id, tenant_id)

        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FacilityIdentityConfigurationError(
                f"{FACILITY_IDENTITY_CONFIG_ENV} must be valid JSON."
            ) from exc
        if (
            not isinstance(document, dict)
            or set(document) != {"schemaVersion", "principals"}
            or document.get("schemaVersion") != 1
            or not isinstance(document.get("principals"), list)
            or not 1 <= len(document["principals"]) <= _MAX_IDENTITIES
        ):
            raise FacilityIdentityConfigurationError(
                f"{FACILITY_IDENTITY_CONFIG_ENV} must be a closed version 1 "
                f"document with 1-{_MAX_IDENTITIES} principals."
            )

        identities: list[tuple[str, FacilityPrincipal]] = []
        token_hashes: set[str] = set()
        principal_ids: set[str] = set()
        expected_fields = {
            "tokenSha256",
            "principalId",
            "tenantId",
            "allowedSiteIds",
            "roles",
        }
        for index, row in enumerate(document["principals"]):
            if not isinstance(row, dict) or set(row) != expected_fields:
                raise FacilityIdentityConfigurationError(
                    f"Pilot principal {index} has an invalid shape."
                )
            token_hash = str(row.get("tokenSha256") or "")
            if not _SHA256_RE.fullmatch(token_hash):
                raise FacilityIdentityConfigurationError(
                    f"Pilot principal {index} tokenSha256 is invalid."
                )
            try:
                principal = FacilityPrincipal.from_mapping(row)
            except Exception as exc:
                raise FacilityIdentityConfigurationError(
                    f"Pilot principal {index} is invalid."
                ) from exc
            if (
                principal.tenant_id != tenant_id
                or principal.allowed_site_ids != (site_id,)
            ):
                raise FacilityIdentityConfigurationError(
                    "Pilot principals must use the host tenant and exactly "
                    "the host site."
                )
            if (
                token_hash in token_hashes
                or principal.principal_id in principal_ids
            ):
                raise FacilityIdentityConfigurationError(
                    "Pilot token hashes and principal IDs must be unique."
                )
            token_hashes.add(token_hash)
            principal_ids.add(principal.principal_id)
            identities.append((token_hash, principal))

        if require_authenticated:
            makers = {
                principal.principal_id
                for _, principal in identities
                if principal.permits("proposal.create")
            }
            checkers = {
                principal.principal_id
                for _, principal in identities
                if (
                    principal.permits("proposal.approve")
                    and principal.permits("proposal.apply")
                )
            }
            if not any(maker != checker for maker in makers for checker in checkers):
                raise FacilityIdentityConfigurationError(
                    "Maker-checker policy requires distinct configured "
                    "proposal maker and approver principals."
                )
        return cls(tuple(identities), site_id, tenant_id)

    def __call__(self, request: Request) -> FacilityPrincipal:
        if not self.identities:
            return local_facility_principal(site_id=self.local_site_id)
        token_hash = hashlib.sha256(
            _parse_bearer(request).encode("utf-8")
        ).hexdigest()
        for expected, principal in self.identities:
            if hmac.compare_digest(token_hash, expected):
                return principal
        raise _unauthenticated()


__all__ = [
    "FACILITY_IDENTITY_CONFIG_ENV",
    "FACILITY_MAKER_CHECKER_ENV",
    "FacilityIdentityConfigurationError",
    "FacilityPrincipalResolver",
    "maker_checker_required_from_environment",
]
