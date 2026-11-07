"""Dedicated packaging permissions over the frozen Facility Layout roles.

Packaging code asks only for these actions. Each is granted when the principal holds it directly
(an administrator's "*" today, or an explicit grant if the role contract ever adds one) or holds
the Facility Layout action packaging checked before these names existed. The migration is exact:
no role gains or loses packaging access. Narrowing an action, for example carrier accounts for
administrators only, is a product decision; change DERIVED_FROM together with
tests/test_packaging_permissions.py.
"""
from __future__ import annotations

from ai_inspector.facility_layout.authorization import FacilityPrincipal

READ = "packaging.read"  # documents, sources, catalog, saved quotes, comparisons and reports
EDIT = "packaging.edit"  # documents, sources, images, baselines and proposals
QUOTE = "packaging.quote"  # sends shipment data to the carrier provider: an external write that may be billed
ACCOUNT = "packaging.account"  # carrier credential changes and carrier-account discovery
DERIVED_FROM = {READ: "layout.read", EDIT: "layout.edit", QUOTE: "layout.edit", ACCOUNT: "layout.edit"}


def permits(principal, action: str) -> bool:
    if action not in DERIVED_FROM:
        raise ValueError(f"Unknown packaging action: {action}")
    return isinstance(principal, FacilityPrincipal) and (principal.permits(action) or principal.permits(DERIVED_FROM[action]))


def granted(principal) -> list[str]:
    return [action for action in DERIVED_FROM if permits(principal, action)]
