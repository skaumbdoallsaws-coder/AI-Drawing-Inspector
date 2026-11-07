"""Supported US parcel addresses for quote-only rating.

Rules are checked before any provider request, so unsupported addresses never
create provider shipments. Sources (checked 2026-11-06): EasyPost Shipments
docs state that customs information is required to rate international
shipments, "including when the destination is a U.S. territory"; the EasyPost
errors guide lists customs information as required for US military addresses
and US territories. This pilot collects no customs data, so both are refused.
"""
from __future__ import annotations

import re

from .service import PackagingError

STATES = frozenset("""
AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ
NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC""".split())
NONCONTIGUOUS = frozenset({"AK", "HI"})
TERRITORIES = frozenset({"PR", "GU", "VI", "AS", "MP", "UM", "FM", "MH", "PW"})
MILITARY = frozenset({"AA", "AE", "AP"})
# "PO Box", "P.O. Box", "Post Office Box", "POB 12", "Box 12" at the start, "PMB" is allowed
# (a private mailbox at a street address).
PO_BOX = re.compile(r"\b(p\.?\s*o\.?\s*box|post\s+office\s+box|pob\s*\d|p\.?\s*o\.?\s*b\.?\s*\d)|^\s*box\s+\d", re.IGNORECASE)
MILITARY_CITY = re.compile(r"^\s*(apo|fpo|dpo)\s*$", re.IGNORECASE)

RULES = {
    "supported": "The 50 states and the District of Columbia, street addresses only.",
    "noncontiguous": "Alaska and Hawaii are rated, with a note: fewer ground services, longer transit and remote-area surcharges are common.",
    "territories": "US territories (PR, GU, VI, AS, MP and others) are refused: rating needs customs information this pilot does not collect.",
    "military": "APO/FPO/DPO military addresses (AA, AE, AP) are refused: rating needs customs information this pilot does not collect.",
    "po_box": "PO Box addresses are refused: carrier eligibility differs (generally USPS only), and EasyPost rejects mixed street and PO Box data.",
}


def check_address(address, role):
    """Raise for unsupported addresses; return explanatory notes for supported ones."""
    state = address.state
    if state in MILITARY or MILITARY_CITY.match(address.city or ""):
        raise PackagingError("address_military_unsupported", f"The {role} is a military APO/FPO/DPO address. {RULES['military']}", 422)
    if state in TERRITORIES:
        raise PackagingError("address_territory_unsupported", f"The {role} is in a US territory ({state}). {RULES['territories']}", 422)
    if state not in STATES:
        raise PackagingError("address_state_unknown", f"The {role} state code {state} is not a US state or DC.", 422)
    if any(PO_BOX.search(line or "") for line in (address.street1, address.street2)):
        raise PackagingError("address_po_box_unsupported", f"The {role} looks like a PO Box. {RULES['po_box']}", 422)
    notes = []
    if state in NONCONTIGUOUS:
        notes.append({"code": "noncontiguous_destination", "message": RULES["noncontiguous"]})
    return notes
