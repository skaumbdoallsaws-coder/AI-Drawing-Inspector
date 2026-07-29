"""Principal-derived authorization for Facility Layout resources.

Tenant and site scope always come from the authenticated principal. Request
paths may narrow that scope, but they cannot broaden it. Cross-scope requests
use the same not-found response as absent objects to avoid disclosing resource
existence.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from .errors import (
    FacilityAuthorizationError,
    FacilityNotFoundError,
    FacilityValidationError,
)


_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

ROLE_ACTIONS: Mapping[str, frozenset[str]] = {
    "viewer": frozenset(
        {
            "catalog.read",
            "layout.read",
            "authority.read",
            "proposal.read",
            "receipt.read",
        }
    ),
    "editor": frozenset(
        {
            "catalog.read",
            "layout.read",
            "layout.create",
            "layout.edit",
            "layout.archive",
            "authority.read",
            "proposal.create",
            "proposal.dismiss",
            "proposal.read",
            "receipt.read",
        }
    ),
    "approver": frozenset(
        {
            "catalog.read",
            "layout.read",
            "authority.read",
            "proposal.read",
            "proposal.approve",
            "proposal.apply",
            "receipt.read",
        }
    ),
    "catalog_curator": frozenset(
        {
            "catalog.read",
            "catalog.intake",
            "catalog.review",
            "catalog.publish",
            "catalog.deprecate",
            "catalog.quarantine",
            "authority.read",
        }
    ),
    "authority_curator": frozenset(
        {
            "catalog.read",
            "authority.read",
            "authority.create",
            "authority.edit",
            "authority.review",
            "authority.publish",
            "authority.deprecate",
            "authority.archive",
        }
    ),
    "admin": frozenset({"*"}),
}

# Product-facing aliases preserve the frozen contract rather than creating a
# second permission vocabulary.
ROLE_ALIASES: Mapping[str, tuple[str, ...]] = {
    "layout_admin": ("editor", "approver"),
    "facility_authority_admin": ("authority_curator",),
}

KNOWN_ROLES = frozenset(ROLE_ACTIONS) | frozenset(ROLE_ALIASES)


class FacilityPrincipalValidationError(FacilityValidationError):
    pass


class FacilityRoleNotAuthorizedError(FacilityAuthorizationError):
    pass


def validate_stable_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _STABLE_ID_RE.fullmatch(value):
        raise FacilityPrincipalValidationError(
            "invalid_principal",
            f"{field_name} must be a stable ID.",
        )
    return value


def _normalize_unique_ids(
    values: Iterable[Any],
    field_name: str,
    *,
    allowed: frozenset[str] | None = None,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise FacilityPrincipalValidationError(
            "invalid_principal",
            f"{field_name} must be a collection.",
        )
    normalized = tuple(
        sorted(validate_stable_id(item, field_name) for item in values)
    )
    if not normalized or len(normalized) != len(set(normalized)):
        raise FacilityPrincipalValidationError(
            "invalid_principal",
            f"{field_name} must be non-empty and unique.",
        )
    if allowed is not None:
        unsupported = sorted(set(normalized) - allowed)
        if unsupported:
            raise FacilityPrincipalValidationError(
                "invalid_principal",
                f"{field_name} contains unsupported roles.",
            )
    return normalized


@dataclass(frozen=True)
class FacilityPrincipal:
    """Authenticated principal and its server-issued Facility Layout scope."""

    principal_id: str
    tenant_id: str
    allowed_site_ids: tuple[str, ...]
    roles: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "principal_id",
            validate_stable_id(self.principal_id, "principalId"),
        )
        object.__setattr__(
            self,
            "tenant_id",
            validate_stable_id(self.tenant_id, "tenantId"),
        )
        object.__setattr__(
            self,
            "allowed_site_ids",
            _normalize_unique_ids(self.allowed_site_ids, "allowedSiteIds"),
        )
        object.__setattr__(
            self,
            "roles",
            _normalize_unique_ids(
                self.roles,
                "roles",
                allowed=KNOWN_ROLES,
            ),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FacilityPrincipal":
        if not isinstance(value, Mapping):
            raise FacilityPrincipalValidationError(
                "invalid_principal",
                "Principal must be an object.",
            )
        site_ids = value.get("allowedSiteIds")
        compatibility_site_ids = value.get("siteIds")
        if site_ids is None:
            site_ids = compatibility_site_ids
        elif compatibility_site_ids is not None and site_ids != compatibility_site_ids:
            raise FacilityPrincipalValidationError(
                "invalid_principal",
                "Principal site scope is ambiguous.",
            )
        if not isinstance(site_ids, (list, tuple)):
            raise FacilityPrincipalValidationError(
                "invalid_principal",
                "Principal allowedSiteIds must be a list.",
            )
        roles = value.get("roles")
        if not isinstance(roles, (list, tuple)):
            raise FacilityPrincipalValidationError(
                "invalid_principal",
                "Principal roles must be a list.",
            )
        return cls(
            principal_id=value.get("principalId"),
            tenant_id=value.get("tenantId"),
            allowed_site_ids=tuple(site_ids),
            roles=tuple(roles),
        )

    @property
    def site_ids(self) -> tuple[str, ...]:
        """Compatibility alias for the frozen contract's `siteIds` spelling."""

        return self.allowed_site_ids

    @property
    def action_set(self) -> frozenset[str]:
        actions: set[str] = set()
        expanded_roles: list[str] = []
        for role in self.roles:
            expanded_roles.extend(ROLE_ALIASES.get(role, (role,)))
        for role in expanded_roles:
            actions.update(ROLE_ACTIONS[role])
        return frozenset(actions)

    def permits(self, action: str) -> bool:
        actions = self.action_set
        return "*" in actions or action in actions


@dataclass(frozen=True)
class AuthorizationDecision:
    authorized: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorized": self.authorized,
            "reason": self.reason,
        }


def authorize_facility_action(
    principal: FacilityPrincipal,
    *,
    tenant_id: Any,
    site_id: Any,
    action: Any,
) -> AuthorizationDecision:
    """Evaluate scope before role so cross-scope objects remain hidden."""

    if (
        not isinstance(tenant_id, str)
        or not _STABLE_ID_RE.fullmatch(tenant_id)
        or not isinstance(site_id, str)
        or not _STABLE_ID_RE.fullmatch(site_id)
        or tenant_id != principal.tenant_id
        or site_id not in principal.allowed_site_ids
    ):
        return AuthorizationDecision(False, "not_found")
    if not isinstance(action, str) or not principal.permits(action):
        return AuthorizationDecision(False, "role_not_authorized")
    return AuthorizationDecision(True, "authorized")


def require_facility_action(
    principal: FacilityPrincipal,
    *,
    tenant_id: Any,
    site_id: Any,
    action: Any,
) -> None:
    decision = authorize_facility_action(
        principal,
        tenant_id=tenant_id,
        site_id=site_id,
        action=action,
    )
    if decision.authorized:
        return
    if decision.reason == "not_found":
        raise FacilityNotFoundError(
            "not_found",
            "Facility resource was not found.",
        )
    raise FacilityRoleNotAuthorizedError(
        "role_not_authorized",
        "Principal is not authorized for this Facility Layout action.",
    )


def local_facility_principal(
    *,
    site_id: str,
    roles: Iterable[str] = ("admin",),
) -> FacilityPrincipal:
    """Create the explicit local-mode principal without bypassing checks."""

    return FacilityPrincipal(
        principal_id="local-user",
        tenant_id="local",
        allowed_site_ids=(site_id,),
        roles=tuple(roles),
    )
