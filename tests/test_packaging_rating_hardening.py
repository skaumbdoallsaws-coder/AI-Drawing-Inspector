"""Rating request/result hardening. MOCK ONLY: every provider response here is a synthetic
httpx.MockTransport reply; nothing in this file is evidence about live EasyPost or carrier behaviour."""
import asyncio
from decimal import Decimal
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_inspector.facility_layout.authorization import local_facility_principal
from ai_inspector.packaging_shipping import api as packaging_api
from ai_inspector.packaging_shipping import quoting as packaging_quoting
from ai_inspector.packaging_shipping.api import create_router
from ai_inspector.packaging_shipping.geometry import assess
from ai_inspector.packaging_shipping.models import QuoteRequest
from ai_inspector.packaging_shipping.rating import EasyPostRating, MESSAGE_HELP, quote_fingerprint
from ai_inspector.packaging_shipping.service import PackagingError, PackagingService
from tests.test_packaging_rating import TEST_KEY, adapter, make_design, quote_request, rate, run_quote, shipment
from tools.run_packaging_pilot import create_app

HEADERS = {"x-inspectorpro-request": "packaging"}


def forbidden(request):
    pytest.fail(f"Unexpected provider request: {request.method} {request.url}")


def request_with(**changes):
    return QuoteRequest.model_validate({**quote_request().model_dump(mode="json"), **changes})


def refused(code, request, design=None):
    with pytest.raises(PackagingError) as caught:
        run_quote(adapter(forbidden), design, request)
    assert caught.value.code == code
    return caught.value


def test_carrier_accounts_and_options_are_sent_only_when_requested():
    bodies = []

    def handle(request):
        bodies.append(json.loads(request.content)["shipment"])
        return httpx.Response(200, json=shipment())

    run_quote(adapter(handle))
    assert set(bodies[-1]) == {"from_address", "to_address", "parcel"}
    chosen = request_with(carrier_accounts=["ca_TEST_A", "ca_TEST_B"],
                          options={"delivery_confirmation": "SIGNATURE", "saturday_delivery": True})
    result = run_quote(adapter(handle), request=chosen)
    assert bodies[-1]["carrier_accounts"] == ["ca_TEST_A", "ca_TEST_B"]
    assert bodies[-1]["options"] == {"delivery_confirmation": "SIGNATURE", "saturday_delivery": True}
    assert result["request"] == {"carrier_accounts": ["ca_TEST_A", "ca_TEST_B"], "services": [],
                                 "options": {"delivery_confirmation": "SIGNATURE", "saturday_delivery": True}}
    with pytest.raises(ValueError):
        request_with(carrier_accounts=["ca_TEST_A", "ca_TEST_A"])
    with pytest.raises(ValueError):
        request_with(carrier_accounts=["not-an-account"])


def test_future_ship_dates_and_unsupported_addresses_are_refused_before_any_shipment():
    assert "does not document" in refused("ship_date_unsupported", request_with(ship_date="2026-12-01")).message
    base = quote_request().model_dump(mode="json")
    for code, change in (("address_territory_unsupported", {"state": "PR", "zip": "00901"}),
                         ("address_military_unsupported", {"state": "AE", "city": "APO", "zip": "09001"}),
                         ("address_po_box_unsupported", {"street1": "PO Box 12"}),
                         ("address_state_unknown", {"state": "ZZ"})):
        refused(code, request_with(destinations=[{**base["destinations"][0], **change}]))
        refused(code, request_with(origin={**base["origin"], **change}))


def test_alaska_and_hawaii_are_rated_with_a_note():
    base = quote_request().model_dump(mode="json")
    request = request_with(destinations=[{**base["destinations"][0], "state": "AK", "zip": "99501"}])
    result = run_quote(adapter(lambda r: httpx.Response(200, json=shipment())), request=request)
    assert [n["code"] for n in result["results"][0]["notes"]] == ["noncontiguous_destination"]
    assert result["results"][0]["destination"]["residential"] is True and result["origin_notes"] == []
    from_hawaii = request_with(origin={**base["origin"], "state": "HI", "zip": "96813"})
    result = run_quote(adapter(lambda r: httpx.Response(200, json=shipment())), request=from_hawaii)
    assert [n["code"] for n in result["origin_notes"]] == ["noncontiguous_destination"]
    assert result["results"][0]["notes"] == []


def test_account_list_and_retail_rates_stay_separate_and_totals_never_mix_bases():
    full = rate("3.10", list_rate="4.00", list_currency="USD", retail_rate="5.25", retail_currency="USD",
                billing_type="easypost", delivery_date="2026-11-10T18:00:00Z", delivery_date_guaranteed=False)
    no_retail = rate("3.40", list_rate="4.10", list_currency="USD")
    replies = iter((shipment([full]), shipment([no_retail])))
    result = run_quote(adapter(lambda r: httpx.Response(200, json=next(replies))), make_design(2))
    first = result["results"][0]["parcels"][0]["rates"][0]
    assert (first["amount"], first["list_amount"], first["retail_amount"]) == ("3.10", "4.00", "5.25")
    assert first["billing_type"] == "easypost" and first["delivery_date_guaranteed"] is False
    total, = result["results"][0]["totals"]
    assert Decimal(total["amount"]) == Decimal("6.50") and Decimal(total["list_amount"]) == Decimal("8.10")
    assert total["retail_amount"] is None, "a basis missing from any parcel is not summed"
    assert set(result["price_bases"]) == {"amount", "list_amount", "retail_amount"}
    # A list rate without its own currency is not assumed to share the account-rate currency.
    unlabelled = run_quote(adapter(lambda r: httpx.Response(200, json=shipment([rate(list_rate="9.00")]))))
    assert unlabelled["results"][0]["parcels"][0]["rates"][0]["list_amount"] is None
    euro = run_quote(adapter(lambda r: httpx.Response(200, json=shipment([rate(list_rate="9.00", list_currency="EUR")]))))
    assert euro["results"][0]["totals"][0]["list_amount"] is None


@pytest.mark.parametrize("value", ["NaN", "-1", "not-money"])
def test_malformed_list_or_retail_amounts_reject_the_response(value):
    raw = shipment([rate(list_rate=value, list_currency="USD")])
    with pytest.raises(PackagingError) as caught:
        run_quote(adapter(lambda r: httpx.Response(200, json=raw)))
    assert caught.value.code == "carrier_unavailable"


def test_carrier_messages_become_categories_without_carrier_text():
    private = "TEST 1 Private Street, Chicago 60601 address could not be verified"
    messages = [{"carrier": "TEST Carrier", "carrier_account_id": "ca_TEST_A", "type": "rate_error", "message": private},
                {"carrier": "UPS", "message": "TEST weight exceeds maximum"},
                {"carrier": "<script>", "carrier_account_id": "not an id", "message": None},
                "TEST malformed entry"] + [{"message": "TEST service not available"}] * 30
    result = run_quote(adapter(lambda r: httpx.Response(200, json={**shipment([]), "messages": messages})))
    parcel = result["results"][0]["parcels"][0]
    assert parcel["carrier_error_count"] == 34 and len(parcel["carrier_messages"]) == 20
    first, second, third, fourth = parcel["carrier_messages"][:4]
    assert first == {"carrier": "TEST Carrier", "carrier_account_id": "ca_TEST_A", "type": "rate_error",
                     "category": "address", "help": MESSAGE_HELP["address"]}
    assert second["category"] == "package" and third == {"carrier": None, "carrier_account_id": None, "type": "other",
                                                          "category": "other", "help": MESSAGE_HELP["other"]}
    assert fourth["category"] == "other" and parcel["carrier_messages"][4]["category"] == "service"
    text = json.dumps(result)
    assert "Private Street" not in text and "60601 address" not in text and "<script>" not in text


def test_account_and_service_filters_exclude_other_rates_and_count_them():
    rates = [rate("3", account="ca_TEST_A"), rate("2", account="ca_TEST_B"),
             rate("5", account="ca_TEST_A", service="TEST Express")]
    raw = shipment(rates)
    accounts = run_quote(adapter(lambda r: httpx.Response(200, json=raw)), request=request_with(carrier_accounts=["ca_TEST_A"]))
    parcel = accounts["results"][0]["parcels"][0]
    assert {r["account_id"] for r in parcel["rates"]} == {"ca_TEST_A"} and parcel["excluded_rate_count"] == 1
    services = run_quote(adapter(lambda r: httpx.Response(200, json=raw)),
                         request=request_with(services=[{"carrier": "TEST Carrier", "service": "TEST Express"}]))
    parcel = services["results"][0]["parcels"][0]
    assert [r["service"] for r in parcel["rates"]] == ["TEST Express"] and parcel["excluded_rate_count"] == 2


def test_mixed_test_and_production_responses_are_rejected():
    replies = iter((shipment(), {**shipment(), "mode": "production", "rates": [rate(mode="production")]}))
    with pytest.raises(PackagingError) as caught:
        run_quote(adapter(lambda r: httpx.Response(200, json=next(replies)), mode=None), make_design(2))
    assert caught.value.code == "carrier_unavailable"


@pytest.mark.parametrize("failure,expected", [
    ("none", {"requests_sent": 2, "responses_received": 2, "shipments_created": 2}),
    ("http", {"requests_sent": 2, "responses_received": 2, "shipments_created": 1}),
    ("transport", {"requests_sent": 2, "responses_received": 1, "shipments_created": 1}),
])
def test_attempt_counts_report_provider_writes_even_when_the_quote_fails(failure, expected):
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 2 and failure == "http":
            return httpx.Response(422, json={"error": {"message": "TEST"}})
        if len(calls) == 2 and failure == "transport":
            raise httpx.ConnectError("TEST", request=request)
        return httpx.Response(200, json=shipment())

    design, counts = make_design(2), {}
    provider = adapter(handle)
    if failure == "none":
        result = asyncio.run(provider.quote(design, assess(design), quote_request(), counts))
        assert result["provider_shipments_created"] == 2
    else:
        with pytest.raises(PackagingError):
            asyncio.run(provider.quote(design, assess(design), quote_request(), counts))
    assert counts == expected


def test_fingerprint_covers_design_scenario_and_account_but_not_revision_or_refresh():
    design = make_design()
    assessment = assess(design)
    provider = adapter(forbidden)
    base = provider.fingerprint(assessment, quote_request())
    assert base == provider.fingerprint(assessment, request_with(expected_revision=7, refresh=True))
    other_design = make_design(2)
    changes = [request_with(destinations=[{**quote_request().destinations[0].model_dump(mode="json"), "residential": False}]),
               request_with(carrier_accounts=["ca_TEST_A"]),
               request_with(services=[{"carrier": "TEST Carrier", "service": "TEST Ground"}]),
               request_with(options={"delivery_confirmation": "SIGNATURE"})]
    prints = {base, provider.fingerprint(assess(other_design), quote_request()),
              EasyPostRating(key="EZTK_OTHER_TEST_KEY").fingerprint(assessment, quote_request())}
    prints |= {provider.fingerprint(assessment, change) for change in changes}
    assert len(prints) == 3 + len(changes)
    assert quote_fingerprint("a" * 64, "b" * 64, None) != quote_fingerprint("a" * 64, "b" * 64, "c" * 32)
    assert TEST_KEY not in json.dumps(provider.status()) and len(provider.status()["account_ref"]) == 32


def test_identical_requests_reuse_the_saved_quote_and_refresh_is_explicit(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=shipment())

    app = create_app(storage=tmp_path / "pilot", rating=adapter(handle))
    with TestClient(app, headers=HEADERS) as client:
        doc = client.post("/api/packaging/documents?contents_confirmed=true", json=make_design().model_dump(mode="json")).json()
        url = f"/api/packaging/documents/{doc['id']}"
        body = quote_request().model_dump(mode="json")
        first = client.post(url + "/quotes", json=body).json()
        assert first["reused"] is False and first["provider_shipments_created"] == 1 and len(calls) == 1
        again = client.post(url + "/quotes", json=body).json()
        assert again["reused"] is True and again["id"] == first["id"] and len(calls) == 1
        changed = client.post(url + "/quotes", json={**body, "options": {"saturday_delivery": True}}).json()
        assert changed["reused"] is False and len(calls) == 2
        refreshed = client.post(url + "/quotes", json={**body, "refresh": True}).json()
        assert refreshed["reused"] is False and refreshed["id"] != first["id"] and len(calls) == 3
        attempts = client.get(url + "/quote-attempts").json()
        assert attempts["attempt_count"] == 3 and attempts["total_shipments_created"] == 3
        assert [a["outcome"] for a in attempts["attempts"]] == ["saved", "saved", "saved"]
        assert "$0.02" in attempts["fees_notice"]
        status = client.get("/api/packaging/status").json()
        assert {"quote_reuse", "quote_attempt_audit", "carrier_account_discovery"} <= set(status["capabilities"])
        assert set(status["quote_rules"]) == {"destinations", "ship_date", "fees", "price_bases"}


def test_refused_and_failed_requests_are_audited_without_saving_quotes(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(500, json={"error": "TEST private diagnostic"})

    app = create_app(storage=tmp_path / "pilot", rating=adapter(handle))
    with TestClient(app, headers=HEADERS) as client:
        doc = client.post("/api/packaging/documents?contents_confirmed=true", json=make_design().model_dump(mode="json")).json()
        url = f"/api/packaging/documents/{doc['id']}"
        body = quote_request().model_dump(mode="json")
        po_box = {**body, "destinations": [{**body["destinations"][0], "street1": "PO Box 9"}]}
        assert client.post(url + "/quotes", json=po_box).json()["error"]["code"] == "address_po_box_unsupported"
        assert calls == [] and client.get(url + "/quote-attempts").json()["attempt_count"] == 0
        failed = client.post(url + "/quotes", json=body)
        assert failed.status_code == 502 and "private diagnostic" not in failed.text
        attempt, = client.get(url + "/quote-attempts").json()["attempts"]
        assert (attempt["outcome"], attempt["error_code"], attempt["requests_sent"], attempt["shipments_created"]) == (
            "failed", "carrier_request_failed", 1, 0)
        assert client.get(url + "/quotes").json() == {"quotes": []}


def test_requests_without_a_response_are_reported_as_unconfirmed(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 2:
            raise httpx.ReadTimeout("TEST", request=request)
        return httpx.Response(200, json=shipment())

    app = create_app(storage=tmp_path / "pilot", rating=adapter(handle))
    with TestClient(app, headers=HEADERS) as client:
        doc = client.post("/api/packaging/documents?contents_confirmed=true", json=make_design(2).model_dump(mode="json")).json()
        url = f"/api/packaging/documents/{doc['id']}"
        failed = client.post(url + "/quotes", json=quote_request().model_dump(mode="json"))
        assert failed.status_code == 502 and failed.json()["error"]["code"] == "carrier_unavailable"
        audit = client.get(url + "/quote-attempts").json()
        attempt, = audit["attempts"]
        assert (attempt["requests_sent"], attempt["responses_received"], attempt["shipments_created"],
                attempt["unconfirmed_requests"]) == (2, 1, 1, 1)
        assert audit["total_unconfirmed_requests"] == 1 and audit["total_shipments_created"] == 1
        assert client.get(url + "/quotes").json() == {"quotes": []}


def test_interrupted_attempts_stay_visible(tmp_path):
    service = PackagingService(tmp_path / "store")
    doc = service.create("scope", make_design())
    attempt_id = service.begin_quote_attempt("scope", doc["id"], 0, "f" * 64)
    assert service.quote_attempts("scope", doc["id"])["attempts"][0]["outcome"] == "running"
    with service.db() as db:
        db.execute("UPDATE quote_attempts SET started=? WHERE id=?", ("2026-01-01T00:00:00+00:00", attempt_id))
    assert service.quote_attempts("scope", doc["id"])["attempts"][0]["outcome"] == "interrupted"


class MockedRating(EasyPostRating):
    transport = None

    def __init__(self, key=None, *, transport=None, account_ref=None, declared_mode=None):
        super().__init__(key, transport=self.transport, account_ref=account_ref, declared_mode=declared_mode)


def store_app(tmp_path, monkeypatch, handle):
    from cryptography.fernet import Fernet
    from ai_inspector.packaging_shipping.credentials import EasyPostCredentialStore
    monkeypatch.delenv("INSPECTORPRO_PACKAGING_EASYPOST_KEY", raising=False)
    MockedRating.transport = httpx.MockTransport(handle)
    monkeypatch.setattr(packaging_quoting, "EasyPostRating", MockedRating)
    cipher = Fernet(Fernet.generate_key())
    store = EasyPostCredentialStore(tmp_path / "account", "test-owner", enabled=True,
        protect=lambda raw, entropy: cipher.encrypt(raw), unprotect=lambda raw, entropy: cipher.decrypt(raw))
    service = PackagingService(tmp_path / "service")
    app = FastAPI()
    app.include_router(create_router(service, principal_resolver=lambda r: local_facility_principal(site_id="test"),
        static_root=Path("static"), credential_factory=lambda p: store))
    return app


def test_replacing_or_removing_the_account_makes_saved_quotes_stale(tmp_path, monkeypatch):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=shipment())

    app = store_app(tmp_path, monkeypatch, handle)
    with TestClient(app, headers=HEADERS) as client:
        client.put("/api/packaging/account", json={"api_key": "EZTK_TEST_ONLY_FIRST", "account_alias": "TEST first", "mode": "test"})
        first_ref = client.get("/api/packaging/account").json()["account_ref"]
        doc = client.post("/api/packaging/documents?contents_confirmed=true", json=make_design().model_dump(mode="json")).json()
        url = f"/api/packaging/documents/{doc['id']}"
        body = quote_request().model_dump(mode="json")
        quoted = client.post(url + "/quotes", json=body).json()
        assert quoted["account_ref"] == first_ref and quoted["reused"] is False
        assert client.get(url + "/quotes").json()["quotes"][0]["stale"] is False
        client.put("/api/packaging/account", json={"api_key": "EZTK_TEST_ONLY_SECOND", "account_alias": "TEST second", "mode": "test"})
        history = client.get(url + "/quotes").json()["quotes"][0]
        assert history["stale"] is True and history["stale_reason"] == "account_changed"
        assert client.post(url + "/quotes", json=body).json()["reused"] is False and len(calls) == 2
        client.delete("/api/packaging/account")
        reasons = {q["stale_reason"] for q in client.get(url + "/quotes").json()["quotes"]}
        assert reasons == {"account_removed"}
        assert "EZTK_TEST_ONLY" not in json.dumps(client.get(url + "/quotes").json())


def test_carrier_account_discovery_returns_only_allowlisted_fields(tmp_path, monkeypatch):
    raw = [{"id": "ca_TEST_A", "object": "CarrierAccount", "type": "UpsAccount", "readable": "UPS",
            "description": "TEST warehouse account", "reference": "TEST-REF", "billing_type": "carrier",
            "credentials": {"account_number": "TEST-SECRET-NUMBER", "password": "TEST-SECRET-PASSWORD"},
            "test_credentials": {"key": "TEST-SECRET-TEST"},
            "fields": {"credentials": {"client_secret": {"visibility": "masked", "value": "********"}}},
            "logo": "https://example.invalid/logo.png", "clone": True},
           {"id": "ca_TEST_B", "type": "USPSAccount", "readable": "USPS", "description": "EZAK hidden key text",
            "reference": None, "billing_type": "EasyPost Wallet"},
           {"id": "not-an-id", "type": "Bad"}, "TEST malformed"]
    seen = []

    def handle(request):
        seen.append((request.method, str(request.url)))
        return httpx.Response(200, json=raw)

    app = store_app(tmp_path, monkeypatch, handle)
    with TestClient(app, headers=HEADERS) as client:
        client.put("/api/packaging/account", json={"api_key": "EZAK_TEST_ONLY_PRODUCTION", "account_alias": "TEST prod", "mode": "production"})
        assert client.get("/api/packaging/account/carrier-accounts").status_code == 405
        listed = client.post("/api/packaging/account/carrier-accounts")
        assert listed.status_code == 200
        data = listed.json()
        assert seen == [("GET", "https://api.easypost.com/v2/carrier_accounts")]
        assert data["carrier_accounts"] == [
            {"id": "ca_TEST_A", "type": "UpsAccount", "readable": "UPS", "description": "TEST warehouse account",
             "reference": "TEST-REF", "billing_type": "carrier"},
            {"id": "ca_TEST_B", "type": "USPSAccount", "readable": "USPS", "description": None,
             "reference": None, "billing_type": None}]
        assert data["skipped_count"] == 2
        assert "SECRET" not in listed.text and "logo" not in listed.text and "EZAK" not in listed.text
        denied = client.post("/api/packaging/account/carrier-accounts", headers={"x-inspectorpro-request": "other"})
        assert denied.status_code == 403


@pytest.mark.parametrize("status,provider_code,code", [
    (403, None, "carrier_discovery_refused"), (401, "MODE.UNAUTHORIZED", "carrier_discovery_refused"),
    (401, None, "carrier_credentials_invalid"), (500, "INTERNAL_SERVER_ERROR", "carrier_request_failed")])
def test_carrier_account_discovery_errors_are_explained(status, provider_code, code):
    body = {"error": {"code": provider_code, "message": "TEST private diagnostic"}}
    provider = adapter(lambda request: httpx.Response(status, json=body), mode="production")
    with pytest.raises(PackagingError) as caught:
        asyncio.run(provider.carrier_accounts())
    assert caught.value.code == code and "TEST" not in caught.value.message
    oversize = adapter(lambda request: httpx.Response(200, content=b"[" + b" " * 1000001 + b"]"), mode="production")
    with pytest.raises(PackagingError) as large:
        asyncio.run(oversize.carrier_accounts())
    assert large.value.code == "carrier_response_invalid"
    with pytest.raises(PackagingError) as missing:
        asyncio.run(adapter(forbidden, key="").carrier_accounts())
    assert missing.value.code == "provider_not_configured"


@pytest.mark.parametrize("provider_code,shown,help_text", [
    ("PARCEL.PARAMETERS.INVALID", True, "dimensions and weight"),
    ("SHIPMENT.RATES.UNAVAILABLE", True, "No carrier offered a rate"),
    ("PAYMENT_REQUIRED", True, "nothing was purchased"),
    ("SOMETHING.NEW", True, "Verify addresses"),
    ("<script>alert(1)</script>", False, "Verify addresses"),
    (None, False, "Verify addresses"),
])
def test_quote_rejections_show_only_the_provider_error_code(provider_code, shown, help_text):
    body = {"error": {"code": provider_code, "message": "TEST 1 Private Street diagnostic"}}
    with pytest.raises(PackagingError) as caught:
        run_quote(adapter(lambda request: httpx.Response(422, json=body)))
    message = caught.value.message
    assert caught.value.code == "carrier_request_failed" and help_text in message
    assert (provider_code in message) is shown if provider_code else "HTTP 422)" in message
    assert "Private Street" not in message and "<script>" not in message
