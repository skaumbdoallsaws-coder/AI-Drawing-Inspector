"""US address coverage rules for quote-only rating (synthetic TEST addresses only)."""
import pytest

from ai_inspector.packaging_shipping.destinations import (
    MILITARY, NONCONTIGUOUS, RULES, STATES, TERRITORIES, check_address)
from ai_inspector.packaging_shipping.models import Address
from ai_inspector.packaging_shipping.service import PackagingError


def address(**changes):
    return Address.model_validate({"name": "TEST ONLY", "street1": "1 Test Street", "city": "Testville",
                                   "state": "MN", "zip": "55401", "residential": False, **changes})


def refused(code, **changes):
    with pytest.raises(PackagingError) as caught:
        check_address(address(**changes), "destination 1")
    assert caught.value.code == code and caught.value.status == 422
    assert "destination 1" in caught.value.message
    return caught.value.message


def test_supported_set_is_fifty_states_and_dc():
    assert len(STATES) == 51 and "DC" in STATES
    assert not STATES & (TERRITORIES | MILITARY)
    for state in sorted(STATES - NONCONTIGUOUS):
        assert check_address(address(state=state), "origin") == []


@pytest.mark.parametrize("state", sorted(NONCONTIGUOUS))
def test_alaska_and_hawaii_are_rated_with_an_explanation(state):
    notes = check_address(address(state=state), "destination 1")
    assert notes == [{"code": "noncontiguous_destination", "message": RULES["noncontiguous"]}]


@pytest.mark.parametrize("state", ["PR", "GU", "VI", "AS", "MP"])
def test_territories_are_refused_because_rating_needs_customs_data(state):
    assert "customs information" in refused("address_territory_unsupported", state=state)


@pytest.mark.parametrize("changes", [{"state": "AA"}, {"state": "AE"}, {"state": "AP"},
                                     {"city": "APO", "state": "NY"}, {"city": " fpo ", "state": "CA"}])
def test_military_addresses_are_refused(changes):
    assert "customs information" in refused("address_military_unsupported", **changes)


def test_unknown_state_codes_are_refused():
    refused("address_state_unknown", state="ZZ")


@pytest.mark.parametrize("street", ["PO Box 12", "P.O. Box 12", "p. o. box 12", "Post Office Box 9",
                                    "POB 44", "P.O.B. 7", "Box 15"])
def test_po_boxes_are_refused_in_either_street_line(street):
    refused("address_po_box_unsupported", street1=street)
    refused("address_po_box_unsupported", street2=street)


@pytest.mark.parametrize("street", ["1 Pond Boxwood Road", "100 Spoke Box Way", "PMB 12, 1 Test Street",
                                    "12 Box Elder Drive", "Suite 200"])
def test_street_addresses_resembling_boxes_are_not_misclassified(street):
    assert check_address(address(street1="1 Test Street", street2=street), "destination 1") == []
