"""Deterministic cost comparison against a baseline (P3). MOCK ONLY: synthetic TEST designs and
httpx.MockTransport replies priced by a fixed weight formula. Nothing here is a real provider
response, address or price, and no saving shown here is evidence of a live saving."""
from decimal import ROUND_CEILING, Decimal
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_inspector.packaging_shipping import rating as rating_module
from ai_inspector.packaging_shipping.comparison import REASONS, integrity
from ai_inspector.packaging_shipping.geometry import assess
from ai_inspector.packaging_shipping.models import Design
from ai_inspector.packaging_shipping.rating import OUNCE_KG
from tests.test_packaging_rating import adapter, make_design, quote_request
from tests.test_packaging_rating_hardening import store_app
from tools.run_packaging_pilot import create_app

HEADERS = {"x-inspectorpro-request": "packaging"}
CENT = Decimal("0.01")


def price(weight_oz, service="TEST Ground"):
    """The mock carrier's formula: 4.00 + 2.00 per pound, plus 5.00 for the express service."""
    amount = Decimal("4.00") + Decimal("2.00") * Decimal(str(weight_oz)) / 16
    return (amount + (5 if service == "TEST Express" else 0)).quantize(CENT)


def priced(calls, state=None):
    state = {"mode": "test", "currency": "USD", "express_max_oz": None} if state is None else state

    def handle(request):
        body = json.loads(request.content)["shipment"]
        calls.append(body)
        weight = body["parcel"]["weight"]
        rates = [{"id": "rate_TEST_ground", "rate": str(price(weight)), "currency": state["currency"], "carrier": "TEST Carrier",
                  "service": "TEST Ground", "carrier_account_id": "ca_TEST_A", "mode": state["mode"], "delivery_days": 3}]
        if state["express_max_oz"] is None or weight <= state["express_max_oz"]:
            rates.append({**rates[0], "id": "rate_TEST_express", "rate": str(price(weight, "TEST Express")),
                          "service": "TEST Express", "delivery_days": 1})
        return httpx.Response(200, json={"id": "shp_TEST", "mode": state["mode"], "rates": rates})
    return handle


def expected_shipping(design, destinations=2, service="TEST Ground"):
    """Independent recomputation from the design's gross masses: ounces rounded up at six decimals."""
    ounces = lambda kg: float(Decimal(repr(kg / OUNCE_KG)).quantize(Decimal("1e-9")).quantize(Decimal("1e-6"), rounding=ROUND_CEILING))
    per = sum((price(ounces(p["gross_kg"]), service) for p in assess(design)["packages"]), Decimal(0))
    return per * destinations


def one_box(quantity=2, product=None, allowance=0.05, payload=5, clearance=None, cost=None, inserts=()):
    data = make_design(1).model_dump(mode="json")
    data["name"], data["quantity"] = "TEST one box", quantity
    package = data["packages"][0]
    positions = ([0.02, 0.02, 0.02], [0.02, 0.12, 0.02])
    package["placements"] = [{"id": f"item_{i}", "position_m": positions[i]} for i in range(quantity)]
    package["allowance_kg"] = allowance
    package["carton"]["max_payload_kg"] = payload
    package["carton"]["cost_usd"] = cost
    package["inserts"] = list(inserts)
    if product:
        data["product"] |= product
    if clearance is not None:
        data["constraints"]["clearance_m"] = clearance
    return Design.model_validate(data)


def two_boxes(cost=None, inserts=()):
    data = make_design(2).model_dump(mode="json")
    for package in data["packages"]:
        package["carton"]["cost_usd"] = cost
        package["inserts"] = list(inserts)
    return Design.model_validate(data)


PAD = {"id": "pad_1", "name": "TEST floor pad", "dimensions_m": [0.17, 0.01, 0.12], "position_m": [0, 0, 0],
       "density_kg_m3": 30.0, "material_evidence": "TEST supplier density"}


def test_fixture_designs_are_valid_and_differ_in_price():
    for design in (two_boxes(), one_box(), one_box(inserts=[PAD]), two_boxes(inserts=[PAD])):
        assert assess(design)["rate_ready"], assess(design)["findings"]
    assert expected_shipping(one_box()) < expected_shipping(two_boxes())


class Pilot:
    def __init__(self, client, baseline_design):
        self.client = client
        doc = client.post("/api/packaging/documents", json=baseline_design.model_dump(mode="json")).json()
        self.url, self.revision = f"/api/packaging/documents/{doc['id']}", doc["revision"]

    def save(self, name, design):
        response = self.client.post(self.url + "/alternatives", json={
            "expected_revision": self.revision, "request_id": "req_" + name.replace(" ", "_"), "name": name,
            "design": design.model_dump(mode="json")})
        assert response.status_code == 200, response.text
        return response.json()["id"]

    def quote(self, ref="current", destinations=2, **changes):
        path = self.url if ref == "current" else f"{self.url}/alternatives/{ref}"
        body = {**quote_request(destinations).model_dump(mode="json"), "expected_revision": self.revision, **changes}
        return self.client.post(path + "/quotes", json=body)

    def compare(self, **params):
        listing = self.client.get(self.url + "/comparison").json()
        scenario = params.pop("scenario_hash", None) or listing["scenarios"][0]["scenario_hash"]
        response = self.client.get(self.url + "/comparison", params={"scenario_hash": scenario, **params})
        assert response.status_code == 200, response.text
        return response.json()["comparison"]


def rows(comparison):
    return {r["name"]: r for r in comparison["rows"]}


def test_comparison_ranks_by_account_rate_and_reports_signed_differences_without_provider_calls(tmp_path):
    calls = []
    with TestClient(create_app(storage=tmp_path / "pilot", rating=adapter(priced(calls))), headers=HEADERS) as client:
        pilot = Pilot(client, two_boxes())
        alt = pilot.save("TEST one box", one_box())
        assert pilot.quote().status_code == 200 and pilot.quote(alt).status_code == 200
        assert len(calls) == 2 * 2 + 1 * 2
        listing = client.get(pilot.url + "/comparison").json()
        assert listing["comparison"] is None and listing["baseline"]["baseline"] == "current"
        scenario, = listing["scenarios"]
        assert scenario["quotes"] == 2 and scenario["modes"] == ["test"] and scenario["current_account"] is True
        assert "street1" not in json.dumps(scenario)
        result = pilot.compare()
        assert len(calls) == 6, "comparing must never contact the provider"
        base, alt_row = rows(result)["Current design (revision 0)"], rows(result)["TEST one box"]
        assert base["baseline"] and base["eligible"] and alt_row["eligible"]
        assert Decimal(base["shipping_total"]) == expected_shipping(two_boxes())
        assert Decimal(alt_row["shipping_total"]) == expected_shipping(one_box())
        assert Decimal(alt_row["shipping_difference"]) == expected_shipping(one_box()) - expected_shipping(two_boxes()) < 0
        assert result["ranking"] == [alt, "current"]
        assert result["service"] == {"carrier": "TEST Carrier", "service": "TEST Ground", "account_id": "ca_TEST_A", "currency": "USD"}
        assert [s["service"] for s in result["services"]] == ["TEST Ground", "TEST Express"]
        assert result["price_basis"] == "amount" and result["savings_claimed"] is False and alt_row["claim"] is None
        assert {"test_mode", "materials_unknown", "parcel_sum"} <= set(result["caveats"])
        assert "test_mode" in alt_row["caveats"] and "parcel_sum" in base["caveats"] and "parcel_sum" not in alt_row["caveats"]
        assert base["total"] is None and base["materials_usd"] is None, "unknown material cost is never zero"
        assert pilot.compare() == result, "the comparison is deterministic"
        express = pilot.compare(carrier="TEST Carrier", service="TEST Express", account_id="ca_TEST_A", currency="USD")
        assert Decimal(rows(express)["TEST one box"]["shipping_total"]) == expected_shipping(one_box(), service="TEST Express")
        incomplete = client.get(pilot.url + "/comparison", params={"scenario_hash": scenario["scenario_hash"], "carrier": "TEST Carrier"})
        assert incomplete.status_code == 422 and incomplete.json()["error"]["code"] == "comparison_service_incomplete"


def test_a_cheaper_design_cannot_win_by_dropping_inputs_or_using_unmatched_rates(tmp_path):
    calls = []
    with TestClient(create_app(storage=tmp_path / "pilot", rating=adapter(priced(calls))), headers=HEADERS) as client:
        pilot = Pilot(client, two_boxes())
        variants = {
            "TEST honest": (one_box(), []),
            "TEST shrunk product": (one_box(product={"dimensions_m": [0.05, 0.04, 0.02]}), ["product_changed"]),
            "TEST lighter product": (one_box(product={"mass_kg": 0.2}), ["product_changed"]),
            "TEST one item dropped": (one_box(quantity=1), ["quantity_changed"]),
            "TEST no allowance": (one_box(allowance=0.0), ["allowance_reduced"]),
            "TEST no payload limit": (one_box(payload=None), ["payload_unverified"]),
            "TEST tighter clearance": (one_box(clearance=0.015), ["constraints_changed"]),
        }
        ids = {}
        for name, (design, _) in variants.items():
            ids[name] = pilot.save(name, design)
            assert pilot.quote(ids[name]).status_code == 200, name
        overlapping = one_box().model_dump(mode="json")
        overlapping["packages"][0]["placements"][1]["position_m"] = [0.03, 0.03, 0.02]
        broken = pilot.save("TEST overlapping", Design.model_validate(overlapping))
        refused = pilot.quote(broken)
        assert refused.status_code == 422 and refused.json()["error"]["code"] == "package_not_rate_ready"
        # Quotes are addressed by design hash, so this must differ from the honest design to be unquoted.
        pilot.save("TEST not quoted", one_box(cost=2.0))
        other_scenario = pilot.save("TEST quoted elsewhere", one_box(cost=0.0))
        assert pilot.quote(other_scenario, destinations=1).status_code == 200
        assert pilot.quote().status_code == 200
        before = len(calls)
        listing = client.get(pilot.url + "/comparison").json()
        scenario = next(s for s in listing["scenarios"] if len(s["destinations"]) == 2)["scenario_hash"]
        result = pilot.compare(scenario_hash=scenario)
        assert len(calls) == before
        by_name = rows(result)
        for name, (design, expected) in variants.items():
            row = by_name[name]
            assert set(expected) <= set(row["reasons"]), (name, row["reasons"])
            assert row["eligible"] is (not expected), name
            if expected:
                # Every manipulated variant is priced at or below the honest one, yet it is never ranked.
                assert Decimal(row["shipping_total"]) <= Decimal(by_name["TEST honest"]["shipping_total"]), name
                assert ids[name] not in result["ranking"] and row["shipping_difference"] is None and row["claim"] is None
        assert set(by_name["TEST overlapping"]["reasons"]) >= {"validation_failed", "not_quoted"}
        assert by_name["TEST not quoted"]["reasons"] == ["not_quoted"]
        assert "not_quoted" in by_name["TEST quoted elsewhere"]["reasons"]
        assert result["ranking"] == [ids["TEST honest"], "current"]
        assert set(result["reasons"]) <= set(REASONS)


def test_protection_cannot_shrink_without_a_cushion_requirement():
    baseline = {"design": two_boxes(inserts=[PAD]), "assessment": assess(two_boxes(inserts=[PAD]))}
    without = {"design": one_box(), "assessment": assess(one_box())}
    kept = {"design": one_box(inserts=[PAD, {**PAD, "id": "pad_2", "position_m": [0, 0.215, 0]}])}
    kept["assessment"] = assess(kept["design"])
    assert kept["assessment"]["rate_ready"], kept["assessment"]["findings"]
    assert "protection_reduced" in integrity(baseline, without)
    assert "protection_reduced" not in integrity(baseline, kept)
    assert integrity(baseline, baseline) == []


def test_stale_design_and_changed_accounts_never_match(tmp_path, monkeypatch):
    calls = []
    app = store_app(tmp_path, monkeypatch, priced(calls))
    with TestClient(app, headers=HEADERS) as client:
        client.put("/api/packaging/account", json={"api_key": "EZTK_TEST_ONLY_FIRST", "account_alias": "TEST first"})
        pilot = Pilot(client, two_boxes())
        alt = pilot.save("TEST one box", one_box())
        assert pilot.quote().status_code == 200 and pilot.quote(alt).status_code == 200
        result = pilot.compare()
        assert result["ranking"] == [alt, "current"]
        client.put("/api/packaging/account", json={"api_key": "EZTK_TEST_ONLY_SECOND", "account_alias": "TEST second"})
        replaced = pilot.compare(scenario_hash=result["scenario_hash"])
        assert replaced["ranking"] == [] and all("not_quoted" in r["reasons"] for r in replaced["rows"])
        assert replaced["baseline"]["ready"] is False
        listing = client.get(pilot.url + "/comparison").json()
        assert listing["scenarios"][0]["current_account"] is False
        assert "EZTK_TEST_ONLY" not in json.dumps(listing) + json.dumps(replaced)


def test_editing_the_design_unmatches_its_old_quote(tmp_path):
    calls = []
    with TestClient(create_app(storage=tmp_path / "pilot", rating=adapter(priced(calls))), headers=HEADERS) as client:
        pilot = Pilot(client, two_boxes())
        alt = pilot.save("TEST one box", one_box())
        assert pilot.quote().status_code == 200 and pilot.quote(alt).status_code == 200
        scenario = client.get(pilot.url + "/comparison").json()["scenarios"][0]["scenario_hash"]
        doc = client.get(pilot.url).json()
        edited = doc["design"] | {"name": "TEST renamed"}
        saved = client.put(pilot.url, json={"expected_revision": doc["revision"], "request_id": "req_rename", "design": edited})
        assert saved.status_code == 200, saved.text
        result = pilot.compare(scenario_hash=scenario)
        current = next(r for r in result["rows"] if r["ref"] == "current")
        assert "not_quoted" in current["reasons"] and result["baseline"]["ready"] is False
        assert all(r["shipping_difference"] is None for r in result["rows"])


def test_baseline_choice_is_kept_and_differences_follow_it(tmp_path):
    calls = []
    with TestClient(create_app(storage=tmp_path / "pilot", rating=adapter(priced(calls))), headers=HEADERS) as client:
        pilot = Pilot(client, two_boxes())
        alt = pilot.save("TEST one box", one_box())
        assert pilot.quote().status_code == 200 and pilot.quote(alt).status_code == 200
        chosen = client.put(pilot.url + "/comparison/baseline", json={"baseline": alt})
        assert chosen.status_code == 200 and chosen.json()["baseline"] == alt and chosen.json()["selected_at"]
        result = pilot.compare()
        assert result["baseline"]["ref"] == alt
        current = next(r for r in result["rows"] if r["ref"] == "current")
        assert Decimal(current["shipping_difference"]) == expected_shipping(two_boxes()) - expected_shipping(one_box()) > 0
        assert client.put(pilot.url + "/comparison/baseline", json={"baseline": "alt_" + "0" * 32}).status_code == 404
        assert client.put(pilot.url + "/comparison/baseline", json={"baseline": "anything"}).status_code == 422
        assert client.put(pilot.url + "/comparison/baseline", json={"baseline": "current"}).json()["baseline"] == "current"


def test_production_quotes_name_the_saving_and_mixed_modes_are_refused(tmp_path, monkeypatch):
    calls, state = [], {"mode": "production", "currency": "USD", "express_max_oz": None}
    times = iter(["2026-11-01T09:00:00+00:00", "2026-11-03T09:00:00+00:00", "2026-11-03T10:00:00+00:00"])
    monkeypatch.setattr(rating_module, "now", lambda: next(times))
    with TestClient(create_app(storage=tmp_path / "pilot", rating=adapter(priced(calls, state))), headers=HEADERS) as client:
        pilot = Pilot(client, two_boxes(cost=1.5))
        alt = pilot.save("TEST one box", one_box(cost=1.5))
        mixed = pilot.save("TEST test-mode quote", one_box(cost=1.5, product={"mass_evidence": "TEST scale, rechecked"}))
        assert pilot.quote().status_code == 200 and pilot.quote(alt).status_code == 200
        state["mode"] = "test"
        assert pilot.quote(mixed).status_code == 200
        result = pilot.compare()
        by_name = rows(result)
        base, row = by_name["Current design (revision 0)"], by_name["TEST one box"]
        assert result["savings_claimed"] is True and "test_mode" not in row["caveats"]
        assert Decimal(base["materials_usd"]) == Decimal("3.00") and Decimal(row["materials_usd"]) == Decimal("1.50")
        assert Decimal(row["total"]) == expected_shipping(one_box()) + Decimal("1.50")
        assert Decimal(row["total_difference"]) == Decimal(row["total"]) - Decimal(base["total"])
        claim = row["claim"]
        saving = expected_shipping(two_boxes()) - expected_shipping(one_box())
        assert Decimal(claim["shipping_saving"]) == saving
        assert claim["baseline"] == "Current design (revision 0)" and claim["baseline_quoted_at"] == "2026-11-01T09:00:00+00:00"
        assert claim["quoted_at"] == "2026-11-03T09:00:00+00:00" and claim["account_id"] == "ca_TEST_A"
        assert claim["destinations"] == ["Chicago, IL 60602", "Chicago, IL 60603"] and claim["account_ref"]
        assert f"USD {saving}" in claim["text"] and "Chicago, IL 60602" in claim["text"]
        assert "quote_dates_differ" in row["caveats"]
        assert by_name["TEST test-mode quote"]["reasons"] == ["mode_mismatch"] and by_name["TEST test-mode quote"]["claim"] is None


def test_missing_service_and_foreign_currency_are_explained(tmp_path):
    calls, state = [], {"mode": "test", "currency": "USD", "express_max_oz": 30}
    with TestClient(create_app(storage=tmp_path / "pilot", rating=adapter(priced(calls, state))), headers=HEADERS) as client:
        pilot = Pilot(client, two_boxes(cost=1.5))
        alt = pilot.save("TEST one box", one_box(cost=1.5))
        assert pilot.quote().status_code == 200 and pilot.quote(alt).status_code == 200
        express = pilot.compare(carrier="TEST Carrier", service="TEST Express", account_id="ca_TEST_A", currency="USD")
        assert "service_unavailable" in rows(express)["TEST one box"]["reasons"]
        assert rows(express)["Current design (revision 0)"]["eligible"]
    calls, state = [], {"mode": "test", "currency": "EUR", "express_max_oz": None}
    with TestClient(create_app(storage=tmp_path / "pilot-eur", rating=adapter(priced(calls, state))), headers=HEADERS) as client:
        pilot = Pilot(client, two_boxes(cost=1.5))
        assert pilot.quote().status_code == 200
        base = pilot.compare()["rows"][0]
        assert base["eligible"] and base["total"] is None and "currency_differs" in base["caveats"]
