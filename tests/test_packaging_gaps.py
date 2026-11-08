"""Implementation gaps recorded 2026-11-07: weight provenance on quotes, added product mass, weighed packed
cartons, an explicit key mode, contents handling and movement/restraint checks.

Offline only: synthetic TEST records, httpx.MockTransport and a Fernet codec in place of DPAPI.
"""
import asyncio
import copy
import json
import socket

from cryptography.fernet import Fernet
import httpx
from pydantic import ValidationError
import pytest

from ai_inspector.packaging_shipping.credentials import ENVIRONMENT_KEY, MODE_ENVIRONMENT, EasyPostCredentialStore
from ai_inspector.packaging_shipping.geometry import assess, digest
from ai_inspector.packaging_shipping.models import Design, QuoteRequest
from ai_inspector.packaging_shipping.quoting import QuoteDesk
from ai_inspector.packaging_shipping.rating import EasyPostRating
from ai_inspector.packaging_shipping.report import check_rows
from ai_inspector.packaging_shipping.service import PackagingError, PackagingService

TEST_KEY = "EZTK_TEST_ONLY_NOT_A_CREDENTIAL"
SCOPE = "tenant-test-scope"
RATE = {"id": "rate_TEST", "rate": "3.25", "currency": "USD", "carrier": "TEST Carrier", "service": "TEST Ground",
        "carrier_account_id": "ca_TEST_A", "delivery_days": 3}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv(ENVIRONMENT_KEY, raising=False)
    monkeypatch.delenv(MODE_ENVIRONMENT, raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("Gap tests must not open network connections")
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def codec():
    cipher = Fernet(Fernet.generate_key())
    return (lambda raw, entropy: cipher.encrypt(entropy + b"\x00" + raw),
            lambda raw, entropy: cipher.decrypt(raw)[len(entropy) + 1:])


def pad(pid, position, dimensions):
    return {"id": pid, "name": f"TEST {pid}", "position_m": [float(v) for v in position],
            "dimensions_m": [float(v) for v in dimensions], "density_kg_m3": 30.0, "material_evidence": "TEST density"}


def lining(x=0.14):
    """Pads on all six sides of a 0.14 x 0.12 x 0.08 m space (x can widen it), 20 mm thick."""
    return [pad("floor", (0, 0, 0), (x, 0.02, 0.08)), pad("top", (0, 0.10, 0), (x, 0.02, 0.08)),
            pad("x-min", (0, 0.02, 0), (0.02, 0.08, 0.08)), pad("x-max", (x - 0.02, 0.02, 0), (0.02, 0.08, 0.08)),
            pad("z-min", (0.02, 0.02, 0), (x - 0.04, 0.08, 0.02)), pad("z-max", (0.02, 0.02, 0.06), (x - 0.04, 0.08, 0.02))]


def base():
    """One 100 x 80 x 40 mm TEST product held by a 20 mm lining on every side: zero predicted clearance, ready to rate."""
    return {
        "name": "TEST gaps", "quantity": 1,
        "product": {"name": "TEST product", "dimensions_m": [0.1, 0.08, 0.04], "mass_kg": 0.5,
                    "mass_basis": "user_measured", "mass_evidence": "TEST scale"},
        "constraints": {"contents": "ordinary_nonhazardous", "clearance_m": 0.0, "gap_m": 0.0},
        "packages": [{"id": "box", "carton": {"name": "TEST carton", "inner_m": [0.14, 0.12, 0.08], "outer_m": [0.15, 0.13, 0.09],
                                               "tare_kg": 0.1, "tare_evidence": "TEST scale", "max_payload_kg": 5.0},
                      "placements": [{"id": "item", "position_m": [0.02, 0.02, 0.02]}],
                      "inserts": lining(), "allowance_kg": 0.01, "allowance_evidence": "TEST tape"}],
    }


def two_products(divider=False):
    """Two TEST products side by side along X, 10 mm apart, in a lining; optionally a 10 mm divider between them."""
    d = base()
    d["quantity"] = 2
    box = d["packages"][0]
    box["carton"].update(inner_m=[0.25, 0.12, 0.08], outer_m=[0.26, 0.13, 0.09])
    box["placements"] = [{"id": "item_a", "position_m": [0.02, 0.02, 0.02]}, {"id": "item_b", "position_m": [0.13, 0.02, 0.02]}]
    box["inserts"] = lining(0.25) + ([pad("divider", (0.12, 0.02, 0.02), (0.01, 0.08, 0.04))] if divider else [])
    return d


def run(design_dict):
    return assess(Design.model_validate(design_dict))


def codes(assessment):
    return {f["code"] for f in assessment["findings"]}


def finding(assessment, code):
    found = [f for f in assessment["findings"] if f["code"] == code]
    assert len(found) == 1, (code, assessment["findings"])
    return found[0]


def row_status(design_dict, assessment, label_start):
    return next(state for check, state, _ in check_rows(Design.model_validate(design_dict).model_dump(mode="json"), assessment)
                if check.startswith(label_start))


# Hash stability: designs that never use the new fields keep their hash, and with it their saved quotes.

def test_unused_new_fields_are_left_out_of_the_saved_design():
    design = Design.model_validate(base())
    dumped = design.model_dump(mode="json")
    assert "additional_mass" not in dumped["product"]
    assert not {"measured_gross_kg", "measured_gross_evidence"} & set(dumped["packages"][0])
    assert not {"contents_basis", "contents_evidence", "restraint"} & set(dumped["constraints"])
    assert digest(design) == digest(Design.model_validate(dumped))


# Added product mass.

def test_known_added_mass_counts_and_unknown_items_stay_listed():
    d = base()
    d["product"]["additional_mass"] = [{"id": "magnets", "name": "Magnets", "basis": "unknown"},
                                       {"id": "adhesive", "name": "Adhesive", "mass_kg": 0.004, "basis": "estimate",
                                        "evidence": "TEST bead length x density"}]
    a = run(d)
    assert a["packages"][0]["product_kg"] == pytest.approx(0.504)
    unknown = finding(a, "added_mass_unknown")
    assert unknown["severity"] == "warning" and unknown["entity_ids"] == ["magnets"] and "Magnets" in unknown["message"]
    assert finding(a, "added_mass_estimated")["entity_ids"] == ["adhesive"]
    assert a["rate_ready"]


@pytest.mark.parametrize("item", [
    {"id": "m", "name": "Magnets", "mass_kg": 0.01},                                   # a mass needs a basis
    {"id": "m", "name": "Magnets", "basis": "estimate", "evidence": "TEST"},           # a basis needs a mass
    {"id": "m", "name": "Magnets", "mass_kg": 0.01, "basis": "user_measured"},         # a mass needs evidence
])
def test_added_mass_needs_its_basis_and_evidence(item):
    d = base()
    d["product"]["additional_mass"] = [item]
    with pytest.raises(ValidationError):
        Design.model_validate(d)


def test_added_mass_ids_are_unique():
    d = base()
    d["product"]["additional_mass"] = [{"id": "m", "name": "A"}, {"id": "m", "name": "B"}]
    with pytest.raises(ValidationError):
        Design.model_validate(d)


# Weighed packed cartons.

def test_a_weighed_carton_is_the_rated_weight_and_the_estimate_stays_beside_it():
    d = base()
    d["product"].update(mass_basis="estimate", mass_evidence="TEST CAD estimate")
    d["product"]["additional_mass"] = [{"id": "magnets", "name": "Magnets"}]
    d["packages"][0].update(measured_gross_kg=0.7, measured_gross_evidence="TEST bench scale, 2026-11-07")
    a = run(d)
    box = a["packages"][0]
    assert box["gross_kg"] == 0.7 and a["total_gross_kg"] == 0.7 and box["gross_basis"] == "measured"
    assert box["estimated_gross_kg"] == pytest.approx(0.5 + 0.03072 + 0.1 + 0.01)
    # The weighed value no longer depends on the estimates, so they no longer condition the price.
    assert not {"estimated_mass", "added_mass_unknown"} & codes(a)


def test_an_unweighed_carton_reports_an_estimated_gross():
    box = run(base())["packages"][0]
    assert box["gross_basis"] == "estimated" and box["gross_kg"] == box["estimated_gross_kg"]


@pytest.mark.parametrize("fields", [{"measured_gross_kg": 0.7}, {"measured_gross_evidence": "TEST scale"}])
def test_a_weighed_mass_and_its_record_go_together(fields):
    d = base()
    d["packages"][0].update(fields)
    with pytest.raises(ValidationError):
        Design.model_validate(d)


# Contents handling.

@pytest.mark.parametrize("contents", ["magnetized_material", "special_handling"])
def test_special_contents_are_unsupported_not_merely_unconfirmed(contents):
    d = base()
    d["constraints"]["contents"] = contents
    a = run(d)
    unsupported = finding(a, "contents_unsupported")
    assert unsupported["severity"] == "error" and not a["rate_ready"] and "contents_unconfirmed" not in codes(a)
    if contents == "magnetized_material":
        assert "USPS ruling" in unsupported["message"]


def test_test_assumption_contents_rate_but_say_they_are_not_clearance():
    d = base()
    d["constraints"].update(contents_basis="test_assumption", contents_evidence="TEST synthetic connection-test parcel")
    a = run(d)
    assert a["rate_ready"] and "not clearance" in finding(a, "contents_test_assumption")["message"]


@pytest.mark.parametrize("fields", [
    {"contents_basis": "product_declaration"},                                        # a basis needs evidence
    {"contents_evidence": "TEST"},                                                    # evidence needs a basis
    {"contents": "unconfirmed", "contents_basis": "test_assumption", "contents_evidence": "TEST"},
])
def test_contents_basis_needs_evidence_and_a_classification(fields):
    d = base()
    d["constraints"].update(fields)
    with pytest.raises(ValidationError):
        Design.model_validate(d)


# Movement and restraint.

def test_a_fully_lined_product_has_zero_predicted_clearance():
    d = base()
    a = run(d)
    row = a["restraint"][0]
    assert row["verified"] and row["max_travel_m"] == 0
    assert all(found["travel_m"] == 0 and found["stops"] == ["insert"] for found in row["directions"].values())
    assert not {"restraint_movement", "products_can_touch", "restraint_insufficient"} & codes(a)
    # No requirement recorded: never PASSED, only review.
    assert row_status(d, a, "Movement and restraint") == "needs_review"


def test_a_gap_is_reported_with_its_size_direction_and_what_stops_it():
    d = base()
    x_max = next(i for i in d["packages"][0]["inserts"] if i["id"] == "x-max")
    x_max["position_m"][0], x_max["dimensions_m"][0] = 0.125, 0.015  # 5 mm open at +x
    a = run(d)
    moved = finding(a, "restraint_movement")
    assert moved["severity"] == "warning" and "5.0 mm, +x" in moved["message"] and a["rate_ready"]
    plus_x = a["restraint"][0]["directions"]["+x"]
    assert plus_x["travel_m"] == pytest.approx(0.005) and plus_x["stops"] == ["insert"] and plus_x["stop_ids"] == ["x-max"]


def test_a_recorded_requirement_fails_or_passes_the_movement():
    d = base()
    x_max = next(i for i in d["packages"][0]["inserts"] if i["id"] == "x-max")
    x_max["position_m"][0], x_max["dimensions_m"][0] = 0.125, 0.015
    d["constraints"]["restraint"] = {"max_travel_m": 0.002, "evidence": "TEST requirement"}
    a = run(d)
    assert finding(a, "restraint_insufficient")["severity"] == "error" and not a["rate_ready"]
    assert row_status(d, a, "Movement and restraint") == "failed"
    d["constraints"]["restraint"]["max_travel_m"] = 0.006
    a = run(d)
    assert not {"restraint_insufficient", "restraint_movement"} & codes(a) and a["rate_ready"]
    assert row_status(d, a, "Movement and restraint") == "passed"


def test_products_that_can_reach_each_other_are_flagged():
    a = run(two_products())
    touch = finding(a, "products_can_touch")
    assert touch["severity"] == "warning" and set(touch["entity_ids"]) == {"item_a", "item_b"}
    by_id = {r["item_id"]: r for r in a["restraint"]}
    assert by_id["item_a"]["directions"]["+x"]["stops"] == ["product"]
    assert by_id["item_a"]["directions"]["+x"]["travel_m"] == pytest.approx(0.01)
    d = two_products()
    d["constraints"]["restraint"] = {"max_travel_m": 0.02, "evidence": "TEST requirement"}
    a = run(d)
    assert finding(a, "products_can_touch")["severity"] == "error" and not a["rate_ready"]
    d["constraints"]["restraint"]["separate_products"] = False
    assert finding(run(d), "products_can_touch")["severity"] == "warning"


def test_a_divider_between_products_restrains_and_separates_them():
    a = run(two_products(divider=True))
    assert not {"products_can_touch", "restraint_movement"} & codes(a)
    assert all(r["max_travel_m"] == 0 and not r["reaches_products"] for r in a["restraint"])


def test_a_product_in_a_pocket_moves_by_the_pocket_clearance():
    d = base()
    block = pad("block", (0, 0, 0), (0.14, 0.10, 0.08))
    block["pockets"] = [{"id": "p", "dimensions_m": [0.104, 0.08, 0.044], "position_m": [0.018, 0.02, 0.018]}]
    d["packages"][0]["inserts"] = [block, pad("top", (0, 0.10, 0), (0.14, 0.02, 0.08))]
    a = run(d)
    assert "insert_overlap" not in codes(a)
    directions = a["restraint"][0]["directions"]
    for name in ("-x", "+x", "-z", "+z"):
        assert directions[name]["travel_m"] == pytest.approx(0.002) and directions[name]["stops"] == ["insert"], name
    assert directions["-y"]["travel_m"] == 0 and directions["+y"]["travel_m"] == 0


def test_a_neighbour_touching_the_side_does_not_stop_the_face():
    d = base()
    inserts = {i["id"]: i for i in d["packages"][0]["inserts"]}
    inserts["z-max"]["position_m"][2], inserts["z-max"]["dimensions_m"][2] = 0.065, 0.015  # 5 mm open at +z
    inserts["x-max"]["position_m"][0] = 0.12 - 1e-9  # float-level overlap with the product's +x side
    a = run(d)
    assert "insert_overlap" not in codes(a)
    plus_z = a["restraint"][0]["directions"]["+z"]
    assert plus_z["travel_m"] == pytest.approx(0.005) and plus_z["stop_ids"] == ["z-max"]


def test_faces_past_the_work_budget_stay_unchecked(monkeypatch):
    from ai_inspector.packaging_shipping import geometry
    monkeypatch.setattr(geometry, "TOTAL_WORK_LIMIT", 0)
    d = base()
    a = run(d)
    row = a["restraint"][0]
    assert not row["verified"] and row["max_travel_m"] is None and set(row["directions"].values()) == {None}
    assert finding(a, "restraint_not_verified")["severity"] == "warning"
    assert row_status(d, a, "Movement and restraint") == "needs_review"


# What a saved quote records, and the key mode.

def handler(calls, mode="test"):
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"id": f"shp_TEST_{len(calls)}", "mode": mode, "rates": [RATE]})
    return respond


def quote_request(destinations=1):
    address = {"name": "TEST ONLY", "street1": "1 Test Street", "city": "Chicago", "state": "IL", "zip": "60601",
               "residential": False}
    return QuoteRequest.model_validate({"expected_revision": 0, "origin": address,
                                        "destinations": [{**address, "zip": f"6060{i + 2}"} for i in range(destinations)]})


def price(desk, service, doc, destinations=1, resolved=None):
    current = service.get(SCOPE, doc)
    return asyncio.run(desk.price(SCOPE, doc, 0, Design.model_validate(current["design"]), current["assessment"],
                                  quote_request(destinations), resolved,
                                  lambda fingerprint: service.find_quote(SCOPE, doc, 0, fingerprint),
                                  lambda result: service.save_quotes(SCOPE, doc, 0, result)))


def saved_doc(tmp_path, design_dict):
    service = PackagingService(tmp_path / "service")
    return service, service.create(SCOPE, Design.model_validate(design_dict))["id"]


def test_a_quote_records_its_weight_basis_contents_and_key_mode(tmp_path):
    d = base()
    d["product"]["additional_mass"] = [{"id": "magnets", "name": "Magnets"}]
    service, doc = saved_doc(tmp_path, d)
    calls = []
    desk = QuoteDesk(service, rating=EasyPostRating(key=TEST_KEY, transport=httpx.MockTransport(handler(calls)), declared_mode="test"))
    saved = price(desk, service, doc)
    basis = saved["weight_basis"]
    assert basis["status"] == "estimated" and basis["unknown_items"] == ["Magnets"] and "Magnets" in basis["summary"]
    assert [p["part"] for p in basis["packages"][0]["components"]] == ["product", "added_mass", "inserts", "carton", "allowance"]
    assert saved["contents"]["transmitted_to_carrier"] is False and saved["contents"]["carrier_acceptance"] == "not_verified"
    assert saved["account_mode"] == {"declared": "test", "observed": "test"}
    # Nothing about the contents is sent: the shipment carries addresses and the parcel only.
    assert set(json.loads(calls[0].content)["shipment"]) == {"from_address", "to_address", "parcel"}
    history = service.quote_history(SCOPE, doc)
    assert history[0]["weight_basis"]["status"] == "estimated"


def test_a_weighed_carton_quote_is_measured(tmp_path):
    d = base()
    d["packages"][0].update(measured_gross_kg=0.7, measured_gross_evidence="TEST bench scale")
    service, doc = saved_doc(tmp_path, d)
    calls = []
    desk = QuoteDesk(service, rating=EasyPostRating(key=TEST_KEY, transport=httpx.MockTransport(handler(calls)), declared_mode="test"))
    saved = price(desk, service, doc)
    assert saved["weight_basis"]["status"] == "measured"
    assert json.loads(calls[0].content)["shipment"]["parcel"]["weight"] == pytest.approx(0.7 / 0.028349523125, abs=1e-5)


def test_no_request_without_a_recorded_key_mode(tmp_path):
    service, doc = saved_doc(tmp_path, base())
    calls = []
    desk = QuoteDesk(service, rating=EasyPostRating(key=TEST_KEY, transport=httpx.MockTransport(handler(calls))))
    with pytest.raises(PackagingError) as error:
        price(desk, service, doc)
    assert error.value.code == "account_mode_unconfirmed" and calls == []


def test_a_contradicting_response_stops_after_one_shipment(tmp_path):
    service, doc = saved_doc(tmp_path, base())
    calls = []
    desk = QuoteDesk(service, rating=EasyPostRating(key=TEST_KEY, transport=httpx.MockTransport(handler(calls, "test")),
                                                    declared_mode="production"))
    with pytest.raises(PackagingError) as error:
        price(desk, service, doc, destinations=3)
    assert error.value.code == "account_mode_mismatch" and len(calls) == 1
    assert service.quote_history(SCOPE, doc) == []
    attempt = service.quote_attempts(SCOPE, doc)["attempts"][0]
    assert attempt["shipments_created"] == 1 and attempt["error_code"] == "account_mode_mismatch"


def test_discovery_with_a_test_key_sends_nothing():
    calls = []
    provider = EasyPostRating(key=TEST_KEY, transport=httpx.MockTransport(handler(calls)), declared_mode="test")
    with pytest.raises(PackagingError) as error:
        asyncio.run(provider.carrier_accounts())
    assert error.value.code == "carrier_discovery_refused" and calls == []


def store_at(tmp_path, codec):
    return EasyPostCredentialStore(tmp_path / "carrier-credentials", "tenant-test/profile-test/user-test", enabled=True,
                                   protect=codec[0], unprotect=codec[1])


def test_the_store_keeps_the_recorded_and_observed_modes(tmp_path, codec):
    store = store_at(tmp_path, codec)
    first = store.replace(TEST_KEY, account_alias="TEST account")
    assert first["declared_mode"] is None and first["mode_mismatch"] is False
    assert store.declare_mode("test")["declared_mode"] == "test"
    contradicted = store.observe_mode(first["account_ref"], "production")
    assert contradicted["observed_mode"] == "production" and contradicted["mode_mismatch"] is True
    restarted = store_at(tmp_path, codec)
    credential = restarted.resolve()
    assert (credential.declared_mode, credential.observed_mode) == ("test", "production")
    # Recording the mode again keeps what EasyPost reported, so the contradiction still stands.
    assert restarted.declare_mode("test")["mode_mismatch"] is True
    # A new key starts with only what its save records.
    replaced = store.replace(TEST_KEY + "B", account_alias="TEST account", mode="production")
    assert (replaced["declared_mode"], replaced["observed_mode"]) == ("production", None)
    assert store.observe_mode(first["account_ref"], "test")["observed_mode"] is None  # an old key's response is ignored
    assert store.remove()["declared_mode"] is None
    with pytest.raises(PackagingError) as error:
        store.declare_mode("live")
    assert error.value.code == "carrier_mode_invalid"


def test_a_store_without_the_mode_table_still_opens(tmp_path, codec):
    store = store_at(tmp_path, codec)
    store.replace(TEST_KEY, account_alias="TEST account", mode="test")
    db = store._connect()
    db.execute("DROP TABLE carrier_account_modes")
    db.commit()
    db.close()
    status = store_at(tmp_path, codec).status()
    assert status["configured"] and status["declared_mode"] is None


def test_the_desk_refuses_a_contradicted_key_before_any_request(tmp_path, codec):
    store = store_at(tmp_path, codec)
    ref = store.replace(TEST_KEY, account_alias="TEST account", mode="test")["account_ref"]
    store.observe_mode(ref, "production")
    service, doc = saved_doc(tmp_path, base())
    desk = QuoteDesk(service, credential_factory=lambda resolved: store)
    with pytest.raises(PackagingError) as error:
        price(desk, service, doc)
    assert error.value.code == "account_mode_mismatch"
    assert service.quote_attempts(SCOPE, doc)["attempts"] == []


def test_the_desk_records_the_mode_easypost_reports(tmp_path, codec, monkeypatch):
    store = store_at(tmp_path, codec)
    store.replace(TEST_KEY, account_alias="TEST account", mode="test")
    service, doc = saved_doc(tmp_path, base())
    calls = []
    desk = QuoteDesk(service, credential_factory=lambda resolved: store)
    real = EasyPostRating.__init__

    def mocked(self, *args, **kwargs):
        real(self, *args, **{**kwargs, "transport": httpx.MockTransport(handler(calls))})
    monkeypatch.setattr(EasyPostRating, "__init__", mocked)
    saved = price(desk, service, doc)
    assert saved["account_mode"] == {"declared": "test", "observed": "test"} and len(calls) == 1
    status = store.status()
    assert status["observed_mode"] == "test" and status["mode_mismatch"] is False and status["observed_at"]


def test_the_report_shows_contents_requirements_movement_and_each_quote_basis():
    from io import BytesIO
    import pdfplumber
    from ai_inspector.packaging_shipping.provenance import contents_record, weight_basis
    from ai_inspector.packaging_shipping.report import render_report
    d = base()
    d["constraints"]["contents"] = "magnetized_material"
    d["product"]["additional_mass"] = [{"id": "magnets", "name": "TEST magnets"}]
    x_max = next(i for i in d["packages"][0]["inserts"] if i["id"] == "x-max")
    x_max["position_m"][0], x_max["dimensions_m"][0] = 0.125, 0.015
    design = Design.model_validate(d)
    assessment = assess(design)
    document = {"id": "pkg_gaps_report", "revision": 0, "updated_at": "2026-11-07T12:00:00+00:00",
                "design": design.model_dump(mode="json"), "assessment": assessment}
    quote = {"id": "quote_TEST", "revision": 0, "provider": "EasyPost", "adapter": "TEST", "quoted_at": "2026-11-07T10:00:00+00:00",
             "design_hash": assessment["design_hash"], "scenario_hash": "5" * 64, "account_ref": "acct_TEST_A", "mode": "test",
             "fingerprint": "6" * 64, "notice": "TEST estimates only.", "fees_notice": "TEST fees notice.",
             "weight_basis": weight_basis(design, assessment), "contents": contents_record(design),
             "account_mode": {"declared": "test", "observed": "test"},
             "results": [{"destination": {"city": "Dallas", "state": "TX", "zip": "75201", "residential": True},
                          "totals": [{"mode": "test", "carrier": "TEST Carrier", "service": "TEST Ground", "account_id": "ca_TEST_A",
                                      "amount": "9.99", "currency": "USD", "basis": "TEST basis"}]}], "stale": False}
    with pdfplumber.open(BytesIO(render_report(document, [quote]))) as reader:
        text = " ".join("\n".join(page.extract_text() or "" for page in reader.pages).split())
    for expected in ("Contents declaration: Magnetized material (not supported for rating)",
                     "A USPS ruling is needed before any eligibility rule is applied.",
                     "No contents or hazardous-materials information is sent to carriers.",
                     "Added mass magnets: TEST magnets | unknown (left out of rated weights)",
                     "Predicted translational clearance (bounding-box model)", "+x 5.0 mm to insert",
                     "Rotation, foam compression and shipping protection remain unverified",
                     "Gross mass basis: estimate (sum of component masses",
                     "Weight basis: Estimate: sum of component masses; excludes 1 item(s) of unknown mass: TEST magnets",
                     "Key mode: recorded test; EasyPost answered test."):
        assert expected in text, expected


# A mismatch is known only from a response: the request that revealed it was sent and cannot be undone.
# What the guard does is stop that quote there, never retry, and refuse every later request.

def quote_with(desk, service, doc, destinations=1, refresh=False):
    current = service.get(SCOPE, doc)
    body = quote_request(destinations).model_copy(update={"refresh": refresh})
    return asyncio.run(desk.price(SCOPE, doc, 0, Design.model_validate(current["design"]), current["assessment"], body, None,
                                  lambda fingerprint: service.find_quote(SCOPE, doc, 0, fingerprint),
                                  lambda result: service.save_quotes(SCOPE, doc, 0, result)))


def test_after_a_mismatch_the_direct_key_sends_nothing_more(tmp_path):
    service, doc = saved_doc(tmp_path, base())
    calls = []
    provider = EasyPostRating(key=TEST_KEY, transport=httpx.MockTransport(handler(calls, "production")), declared_mode="test")
    desk = QuoteDesk(service, rating=provider)
    with pytest.raises(PackagingError) as first:
        quote_with(desk, service, doc, destinations=3)
    assert first.value.code == "account_mode_mismatch" and len(calls) == 1
    assert "already sent" in first.value.message and "cannot be undone" in first.value.message
    assert provider.status()["mode_mismatch"] is True
    for refresh in (False, True):
        with pytest.raises(PackagingError) as later:
            quote_with(desk, service, doc, destinations=3, refresh=refresh)
        assert later.value.code == "account_mode_mismatch" and "No request was sent" in later.value.message
    with pytest.raises(PackagingError) as listing:
        asyncio.run(desk.carrier_accounts(None))
    assert listing.value.code == "account_mode_mismatch"
    assert len(calls) == 1  # no retry and no continuation
    attempts = service.quote_attempts(SCOPE, doc)["attempts"]
    assert len(attempts) == 1 and attempts[0]["requests_sent"] == 1 and attempts[0]["shipments_created"] == 1
    assert service.quote_history(SCOPE, doc) == []


def production_replies(monkeypatch, calls, mode="production"):
    real = EasyPostRating.__init__

    def mocked(self, *args, **kwargs):
        real(self, *args, **{**kwargs, "transport": httpx.MockTransport(handler(calls, mode))})
    monkeypatch.setattr(EasyPostRating, "__init__", mocked)


def test_after_a_mismatch_the_saved_key_is_refused_even_if_the_store_write_fails(tmp_path, codec, monkeypatch):
    store = store_at(tmp_path, codec)
    store.replace(TEST_KEY, account_alias="TEST account", mode="test")
    service, doc = saved_doc(tmp_path, base())
    calls = []
    production_replies(monkeypatch, calls)

    def unwritable(*args, **kwargs):
        raise OSError("TEST store write failure")
    monkeypatch.setattr(store, "observe_mode", unwritable)
    desk = QuoteDesk(service, credential_factory=lambda resolved: store)
    with pytest.raises(PackagingError) as first:
        quote_with(desk, service, doc, destinations=2)
    assert first.value.code == "account_mode_mismatch" and len(calls) == 1
    assert store.status()["observed_mode"] is None  # nothing reached the store
    for refresh in (False, True):
        with pytest.raises(PackagingError) as later:
            quote_with(desk, service, doc, destinations=2, refresh=refresh)
        assert later.value.code == "account_mode_mismatch"
    assert len(calls) == 1 and len(service.quote_attempts(SCOPE, doc)["attempts"]) == 1


def test_recording_the_mode_again_does_not_clear_what_easypost_reported(tmp_path, codec, monkeypatch):
    store = store_at(tmp_path, codec)
    store.replace(TEST_KEY, account_alias="TEST account", mode="test")
    service, doc = saved_doc(tmp_path, base())
    calls = []
    production_replies(monkeypatch, calls)
    desk = QuoteDesk(service, credential_factory=lambda resolved: store)
    with pytest.raises(PackagingError):
        quote_with(desk, service, doc)
    assert store.status()["mode_mismatch"] is True and len(calls) == 1
    store.declare_mode("test")
    with pytest.raises(PackagingError) as refused:
        quote_with(desk, service, doc)
    assert refused.value.code == "account_mode_mismatch" and len(calls) == 1
    store.declare_mode("production")  # Mock only: the mode the mock reported, recorded by the user.
    saved = quote_with(desk, service, doc)
    assert saved["account_mode"] == {"declared": "production", "observed": "production"} and len(calls) == 2


# Test assumptions are for synthetic connection-test parcels: never priced on a production key.

def assumed(basis="test_assumption"):
    d = base()
    d["constraints"].update(contents_basis=basis, contents_evidence="TEST synthetic parcel for a connection test")
    return d


@pytest.mark.parametrize("mode", ["production", None])
def test_test_assumption_contents_are_refused_unless_the_key_is_recorded_as_test(tmp_path, mode):
    service, doc = saved_doc(tmp_path, assumed())
    calls = []
    provider = EasyPostRating(key=TEST_KEY, transport=httpx.MockTransport(handler(calls, mode or "test")), declared_mode=mode)
    with pytest.raises(PackagingError) as refused:
        quote_with(QuoteDesk(service, rating=provider), service, doc)
    assert refused.value.code == ("test_assumption_needs_test_key" if mode else "account_mode_unconfirmed") and calls == []
    assert service.quote_attempts(SCOPE, doc)["attempts"] == []
    current = service.get(SCOPE, doc)
    with pytest.raises(PackagingError) as direct:
        provider.preflight(Design.model_validate(current["design"]), current["assessment"], quote_request())
    assert direct.value.code == "test_assumption_needs_test_key"


def test_test_assumption_contents_rate_on_a_test_key_and_declarations_on_any_key(tmp_path):
    service, doc = saved_doc(tmp_path / "assumed", assumed())
    calls = []
    test_key = EasyPostRating(key=TEST_KEY, transport=httpx.MockTransport(handler(calls)), declared_mode="test")
    saved = quote_with(QuoteDesk(service, rating=test_key), service, doc)
    assert saved["contents"]["basis"] == "test_assumption" and saved["mode"] == "test" and len(calls) == 1
    declared_service, declared_doc = saved_doc(tmp_path / "declared", assumed("product_declaration"))
    production = EasyPostRating(key=TEST_KEY, transport=httpx.MockTransport(handler(calls, "production")), declared_mode="production")
    saved = quote_with(QuoteDesk(declared_service, rating=production), declared_service, declared_doc)
    assert saved["contents"]["basis"] == "product_declaration" and len(calls) == 2
