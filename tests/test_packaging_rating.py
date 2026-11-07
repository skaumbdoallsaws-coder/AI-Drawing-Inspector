"""Quote-only EasyPost tests: synthetic TEST records and MockTransport only."""
import asyncio
from decimal import Decimal
import json
from types import SimpleNamespace

import httpx
import pytest

from ai_inspector.packaging_shipping.geometry import assess
from ai_inspector.packaging_shipping.models import Design, QuoteRequest
from ai_inspector.packaging_shipping.rating import EasyPostRating, parcel_inches, parcel_ounces
from ai_inspector.packaging_shipping.service import PackagingError, PackagingService
from tools.run_packaging_pilot import create_app


TEST_KEY = "EZTK_TEST_ONLY_NOT_A_CREDENTIAL"


def make_design(count=1):
    return Design.model_validate({
        "name": "TEST rate request", "quantity": count,
        "product": {"name": "TEST product", "dimensions_m": [0.1, 0.08, 0.04],
                    "mass_kg": 0.5, "mass_basis": "user_measured", "mass_evidence": "TEST scale"},
        "constraints": {"contents": "ordinary_nonhazardous"},
        "packages": [{"id": f"box_{i}", "carton": {
            "name": "TEST carton", "inner_m": [0.17, 0.23, 0.12],
            "outer_m": [0.2032, 0.254, 0.1524], "tare_kg": 0.1,
            "tare_evidence": "TEST scale", "max_payload_kg": 5},
            "placements": [{"id": f"item_{i}", "position_m": [0.02, 0.02, 0.02]}],
            "allowance_kg": 0.05, "allowance_evidence": "TEST tape"} for i in range(count)],
    })


def quote_request(destinations=1):
    address = {"name": "TEST ONLY", "street1": "1 Test Street", "city": "Chicago",
               "state": "IL", "zip": "60601", "residential": False}
    return QuoteRequest.model_validate({"expected_revision": 0, "origin": address,
                                        "destinations": [{**address, "zip": f"6060{i + 2}", "residential": True}
                                                         for i in range(destinations)]})


def rate(amount="3.25", *, account="ca_TEST_A", currency="USD", rate_id="rate_TEST", **changes):
    return {"id": rate_id, "rate": amount, "currency": currency, "carrier": "TEST Carrier",
            "service": "TEST Ground", "carrier_account_id": account,
            "mode": "test", "delivery_days": 3, **changes}


def shipment(rates=None):
    return {"id": "shp_TEST", "mode": "test", "rates": [rate()] if rates is None else rates}


def adapter(handler, key=TEST_KEY):
    return EasyPostRating(key=key, transport=httpx.MockTransport(handler))


def run_quote(provider, design=None, request=None):
    design = design if design is not None else make_design()
    return asyncio.run(provider.quote(design, assess(design), request or quote_request()))


def assert_packaging_error(provider, code, *, design=None, request=None, status=502):
    with pytest.raises(PackagingError) as caught:
        run_quote(provider, design, request)
    assert caught.value.code == code
    assert caught.value.status == status
    assert TEST_KEY not in caught.value.message
    return caught.value


def test_parcels_are_sent_at_provider_precision_never_smaller_or_lighter():
    # EasyPost takes inches to one decimal. Binary noise in an exact size never adds a tenth.
    assert [parcel_inches(x * 0.0254) for x in (10, 8.375, 6.375, 4.625, 12.01)] == [10.0, 8.4, 6.4, 4.7, 12.1]
    assert parcel_inches(0.2) == 7.9 and parcel_ounces(0.65) == 22.928076 and parcel_ounces(16 * 0.028349523125) == 16.0
    sent = []

    def handle(request):
        sent.append(json.loads(request.content)["shipment"]["parcel"])
        return httpx.Response(200, json=shipment())

    value = make_design().model_dump(mode="json")  # A ULINE S-4080 carton: 8 x 6 x 4 in inside.
    value["packages"][0]["carton"].update(inner_m=[8 * 0.0254, 6 * 0.0254, 4 * 0.0254],
                                          outer_m=[8.375 * 0.0254, 6.375 * 0.0254, 4.625 * 0.0254])
    result = run_quote(adapter(handle), Design.model_validate(value))
    assert sent == [{"length": 8.4, "width": 6.4, "height": 4.7, "weight": 22.928076}]
    assert result["results"][0]["parcels"][0]["parcel_sent"] == {
        "length_in": 8.4, "width_in": 6.4, "height_in": 4.7, "weight_oz": 22.928076}


def test_quote_uses_external_inches_gross_ounces_and_test_mode_only():
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://api.easypost.com/v2/shipments"
        body = json.loads(request.content)
        assert set(body) == {"shipment"}
        assert set(body["shipment"]) == {"from_address", "to_address", "parcel"}
        parcel = body["shipment"]["parcel"]
        assert parcel == {"length": 10.0, "width": 8.0, "height": 6.0, "weight": 22.928076}  # 22.9280752... rounded up
        assert body["shipment"]["from_address"]["residential"] is False
        assert body["shipment"]["to_address"]["residential"] is True
        assert "Authorization" in request.headers
        return httpx.Response(200, json=shipment())

    provider = adapter(handle)
    assert provider.status()["purchases_enabled"] is False
    assert TEST_KEY not in json.dumps(provider.status())
    design = make_design()
    result = run_quote(provider, design, quote_request(2))
    assert len(calls) == 2
    assert result["design_hash"] == assess(design)["design_hash"]
    assert len(result["scenario_hash"]) == 64
    for destination in result["results"]:
        assert destination["parcels"][0]["mode"] == "test"
        assert destination["totals"][0]["mode"] == "test"
        assert Decimal(destination["totals"][0]["amount"]) == Decimal("3.25")
        assert "street1" not in destination["destination"]
    assert TEST_KEY not in json.dumps(result)
    assert "No postage was purchased" in result["notice"]


def test_preflight_unknown_mass_missing_key_and_request_budget_never_call_provider():
    def forbidden(request):
        pytest.fail(f"Unexpected network attempt: {request.method} {request.url}")

    assert_packaging_error(adapter(forbidden, key=""), "provider_not_configured", status=503)
    unknown = make_design().model_dump()
    unknown["product"].update(mass_kg=None, mass_basis="unknown", mass_evidence="")
    assert_packaging_error(adapter(forbidden), "package_not_rate_ready", design=Design.model_validate(unknown), status=422)
    assert_packaging_error(adapter(forbidden), "quote_budget_exceeded", design=make_design(5), request=quote_request(3), status=422)


def test_missing_or_empty_rates_do_not_fabricate_totals():
    for response in ({"id": "shp_TEST", "mode": "test"}, shipment([])):
        result = run_quote(adapter(lambda request: httpx.Response(200, json=response)))
        destination = result["results"][0]
        assert destination["parcels"][0]["rates"] == []
        assert destination["totals"] == []
    replies = iter((shipment([rate()]), shipment([])))
    result = run_quote(adapter(lambda request: httpx.Response(200, json=next(replies))), make_design(2))
    assert result["results"][0]["totals"] == []


@pytest.mark.parametrize("mutation", ["missing-shipment-mode", "unknown-shipment-mode", "mismatched-rate-mode"])
def test_unverified_or_mixed_modes_are_rejected(mutation):
    raw = shipment()
    if mutation == "missing-shipment-mode":
        del raw["mode"]
    elif mutation == "unknown-shipment-mode":
        raw["mode"] = "unknown_TEST_mode"
    else:
        raw["rates"][0]["mode"] = "unknown_TEST_mode"
    assert_packaging_error(adapter(lambda request: httpx.Response(200, json=raw)), "carrier_unavailable")


def test_rate_can_inherit_verified_shipment_test_mode():
    raw = shipment()
    del raw["rates"][0]["mode"]
    result = run_quote(adapter(lambda request: httpx.Response(200, json=raw)))
    assert result["results"][0]["parcels"][0]["rates"][0]["mode"] == "test"


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-0.01", "1000000.01", "not-money"])
def test_invalid_rate_amounts_are_sanitized(amount):
    assert_packaging_error(adapter(lambda request: httpx.Response(200, json=shipment([rate(amount)]))), "carrier_unavailable")


@pytest.mark.parametrize("failure", ["http", "transport", "invalid-json", "oversize", "redirect"])
def test_provider_errors_are_sanitized_and_redirects_not_followed(failure):
    sensitive = f"TEST private address, provider diagnostic, secret {TEST_KEY}"
    calls = []

    def handle(request):
        calls.append(request)
        if failure == "http":
            return httpx.Response(422, json={"error": {"message": sensitive}})
        if failure == "transport":
            raise httpx.ConnectError(sensitive, request=request)
        if failure == "invalid-json":
            return httpx.Response(200, content=sensitive)
        if failure == "oversize":
            return httpx.Response(200, content=b"x" * 1000001)
        return httpx.Response(302, headers={"location": "https://example.invalid/TEST"}, content=sensitive)

    code = {"http": "carrier_request_failed", "oversize": "carrier_response_invalid"}.get(failure, "carrier_unavailable")
    error = assert_packaging_error(adapter(handle), code)
    assert sensitive not in error.message
    assert "TEST private" not in error.message
    assert len(calls) == 1


@pytest.mark.parametrize("raw", [[], None, "TEST malformed document"])
def test_non_object_provider_json_is_a_sanitized_domain_error(raw):
    assert_packaging_error(adapter(lambda request: httpx.Response(200, content=json.dumps(raw), headers={"content-type": "application/json"})), "carrier_unavailable")


@pytest.mark.parametrize("entry", [None, "TEST invalid rate", [], True])
def test_nonobject_rate_entry_rejects_response_even_after_a_valid_rate(entry):
    raw = shipment([rate(), entry])
    assert_packaging_error(adapter(lambda request: httpx.Response(200, json=raw)), "carrier_unavailable")


def test_rates_container_must_be_a_list():
    for invalid in (None, {"TEST rate": rate()}, "TEST invalid list", True):
        raw = {**shipment(), "rates": invalid}
        assert_packaging_error(adapter(lambda request: httpx.Response(200, json=raw)), "carrier_unavailable")


def test_rate_list_limit_accepts_100_but_never_silently_truncates_101():
    rates = [rate(rate_id=f"rate_TEST_{index}") for index in range(100)]
    result = run_quote(adapter(lambda request: httpx.Response(200, json=shipment(rates))))
    returned = result["results"][0]["parcels"][0]["rates"]
    assert len(returned) == 100
    assert [r["id"] for r in returned] == [r["id"] for r in rates]
    rates.append(rate(rate_id="rate_TEST_over_limit"))
    assert_packaging_error(adapter(lambda request: httpx.Response(200, json=shipment(rates))), "carrier_unavailable")


def test_delivery_days_reject_bool_object_coercions_and_out_of_range_values():
    for days in (True, False, {"days": 3, "TEST_secret": TEST_KEY}, [], "3", 3.0, -1, 366):
        raw = shipment([rate(delivery_days=days)])
        assert_packaging_error(adapter(lambda request: httpx.Response(200, json=raw)), "carrier_unavailable")


def test_delivery_days_accept_missing_null_and_integer_boundaries():
    for days in ("missing", None, 0, 365):
        entry = rate(delivery_days=days)
        if days == "missing":
            del entry["delivery_days"]
        result = run_quote(adapter(lambda request: httpx.Response(200, json=shipment([entry]))))
        returned = result["results"][0]["parcels"][0]["rates"][0]["delivery_days"]
        assert returned == (None if days == "missing" else days)
        assert returned is None or type(returned) is int


@pytest.mark.parametrize("field", ["id", "carrier", "service", "carrier_account_id", "shipment.id"])
def test_provider_identities_reject_malformed_and_overlong_values(field):
    invalid_values = [None, True, {"TEST_secret": TEST_KEY}, [], "TEST_" + "x" * 96]
    if field in {"id", "carrier", "service"}:
        invalid_values.extend(("", " \t\n"))
    for value in invalid_values:
        raw = shipment()
        if field == "shipment.id":
            raw["id"] = value
        else:
            raw["rates"][0][field] = value
        assert_packaging_error(adapter(lambda request: httpx.Response(200, json=raw)), "carrier_unavailable")


def test_required_identities_cannot_be_missing_but_optional_ids_can():
    for field in ("id", "carrier", "service"):
        raw = shipment()
        del raw["rates"][0][field]
        assert_packaging_error(adapter(lambda request: httpx.Response(200, json=raw)), "carrier_unavailable")
    raw = shipment()
    del raw["id"]
    del raw["rates"][0]["carrier_account_id"]
    result = run_quote(adapter(lambda request: httpx.Response(200, json=raw)))
    destination = result["results"][0]
    assert destination["parcels"][0]["provider_id"] == ""
    assert destination["parcels"][0]["rates"][0]["account_id"] == ""
    assert destination["totals"][0]["account_id"] == ""


@pytest.mark.parametrize("field", ["carrier", "service", "carrier_account_id"])
def test_overlong_identity_cannot_collide_with_valid_100_character_prefix(field):
    prefix = "TEST_" + "x" * 95
    first, second = rate("3"), rate("4")
    first[field], second[field] = prefix, prefix + "B"
    assert len(prefix) == 100 and second[field][:100] == first[field]
    replies = iter((shipment([first]), shipment([second])))
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == "POST" and str(request.url) == "https://api.easypost.com/v2/shipments"
        return httpx.Response(200, json=next(replies))

    assert_packaging_error(adapter(handle), "carrier_unavailable", design=make_design(2))
    assert len(calls) == 2


def test_100_character_identities_are_preserved_and_distinct_accounts_stay_separate():
    prefix = "TEST_" + "x" * 94
    account_a, account_b = prefix + "A", prefix + "B"
    carrier, service, shipment_id = prefix + "C", prefix + "S", prefix + "P"
    rate_a, rate_b = prefix + "1", prefix + "2"

    def response(amount_a, amount_b):
        return {"id": shipment_id, "mode": "test", "rates": [
            rate(amount_a, account=account_a, rate_id=rate_a, carrier=carrier, service=service),
            rate(amount_b, account=account_b, rate_id=rate_b, carrier=carrier, service=service),
        ]}

    replies = iter((response("3", "6"), response("4", "8")))
    result = run_quote(adapter(lambda request: httpx.Response(200, json=next(replies))), make_design(2))
    destination = result["results"][0]
    for parcel in destination["parcels"]:
        assert parcel["provider_id"] == shipment_id
        assert [(r["id"], r["account_id"], r["carrier"], r["service"]) for r in parcel["rates"]] == [
            (rate_a, account_a, carrier, service), (rate_b, account_b, carrier, service),
        ]
    assert {r["account_id"]: Decimal(r["amount"]) for r in destination["totals"]} == {
        account_a: Decimal("7"), account_b: Decimal("14"),
    }
    assert all(r["carrier"] == carrier and r["service"] == service for r in destination["totals"])


def test_carrier_messages_are_counted_without_exposing_private_text():
    raw = {**shipment([]), "messages": [{"message": "TEST private address and diagnostic", "carrier": "TEST"}]}
    result = run_quote(adapter(lambda request: httpx.Response(200, json=raw)))
    assert result["results"][0]["parcels"][0]["carrier_error_count"] == 1
    assert "private address" not in json.dumps(result)


def test_totals_only_intersect_same_service_account_currency_and_use_cheapest_rate():
    responses = iter((
        shipment([rate("9.99", rate_id="rate_TEST_expensive"), rate("3.10"),
                  rate("1.20", account="ca_TEST_A", currency="EUR"),
                  rate("1.00", account="ca_TEST_B"), rate("8", service="TEST Express")]),
        shipment([rate("4.20"), rate("2.30", account="ca_TEST_A", currency="EUR"),
                  rate("0.50", account="ca_TEST_C")]),
    ))
    result = run_quote(adapter(lambda request: httpx.Response(200, json=next(responses))), make_design(2))
    totals = result["results"][0]["totals"]
    assert [(r["currency"], Decimal(r["amount"])) for r in totals] == [("EUR", Decimal("3.50")), ("USD", Decimal("7.30"))]
    assert all(r["mode"] == "test" and r["service"] == "TEST Ground" for r in totals)
    assert all("not a consolidated shipment quote" in r["basis"] for r in totals)


def test_totals_preserve_account_identity_when_two_accounts_offer_same_service():
    responses = iter((shipment([rate("3", account="ca_TEST_A"), rate("6", account="ca_TEST_B")]),
                      shipment([rate("4", account="ca_TEST_A"), rate("8", account="ca_TEST_B")])))
    result = run_quote(adapter(lambda request: httpx.Response(200, json=next(responses))), make_design(2))
    totals = result["results"][0]["totals"]
    assert all("account_id" in total for total in totals), "Totals must identify the account whose rates were summed"
    assert {total["account_id"]: Decimal(total["amount"]) for total in totals} == {"ca_TEST_A": Decimal(7), "ca_TEST_B": Decimal(14)}


@pytest.mark.parametrize("currency", ["USDX", "", None])
def test_invalid_currency_is_rejected_not_truncated_or_coerced(currency):
    responses = iter((shipment([rate("3", currency="USD")]), shipment([rate("4", currency=currency)])))
    assert_packaging_error(adapter(lambda request: httpx.Response(200, json=next(responses))),
                           "carrier_unavailable", design=make_design(2))


def test_rate_lock_rejects_overlap_and_is_released_after_failure():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def handle(request):
            entered.set()
            await release.wait()
            raise httpx.ConnectError("TEST transport failure", request=request)

        provider = adapter(handle)
        design, request = make_design(), quote_request()
        first = asyncio.create_task(provider.quote(design, assess(design), request))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            with pytest.raises(PackagingError) as busy:
                await provider.quote(design, assess(design), request)
            assert (busy.value.code, busy.value.status) == ("quote_in_progress", 429)
        finally:
            release.set()
            with pytest.raises(PackagingError, match="could not be verified"):
                await first
        with pytest.raises(PackagingError) as next_call:
            await provider.quote(design, assess(design), request)
        assert next_call.value.code == "carrier_unavailable"

    asyncio.run(scenario())


def test_quote_changed_during_provider_call_is_not_saved(tmp_path):
    from fastapi.testclient import TestClient
    service = PackagingService(tmp_path / "pilot")
    document_id = None
    calls = []

    def handle(request):
        calls.append(request)
        # Simulate the independent editor committing while the provider is working.
        with service.db() as db:
            db.execute("UPDATE documents SET revision=revision+1 WHERE id=?", (document_id,))
        return httpx.Response(200, json=shipment())

    app = create_app(storage=service.root, rating=adapter(handle))
    with TestClient(app, headers={"x-inspectorpro-request": "packaging"}) as client:
        created = client.post("/api/packaging/documents", json=make_design().model_dump(mode="json"))
        assert created.status_code == 200
        document_id = created.json()["id"]
        url = f"/api/packaging/documents/{document_id}/quotes"
        result = client.post(url, json=quote_request().model_dump(mode="json"))
        assert result.status_code == 409
        assert result.json()["error"]["code"] == "revision_conflict"
        assert client.get(url).json() == {"quotes": []}
    assert len(calls) == 1


def test_partial_carrier_failure_never_saves_partial_quote(tmp_path):
    from fastapi.testclient import TestClient
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=shipment()) if len(calls) == 1 else httpx.Response(500, json={"error": "TEST private diagnostic"})

    app = create_app(storage=tmp_path / "pilot", rating=adapter(handle))
    with TestClient(app, headers={"x-inspectorpro-request": "packaging"}) as client:
        created = client.post("/api/packaging/documents", json=make_design(2).model_dump(mode="json"))
        assert created.status_code == 200
        url = f"/api/packaging/documents/{created.json()['id']}/quotes"
        result = client.post(url, json=quote_request().model_dump(mode="json"))
        assert result.status_code == 502
        assert "private diagnostic" not in result.text and TEST_KEY not in result.text
        assert client.get(url).json() == {"quotes": []}
    assert len(calls) == 2


def test_total_quote_timeout_cancels_provider_releases_lock_and_saves_nothing(tmp_path, monkeypatch):
    from ai_inspector.packaging_shipping import rating
    calls = []
    budgets = []

    async def scenario():
        entered, cancelled, blocked = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def handle(request):
            assert request.method == "POST" and str(request.url) == "https://api.easypost.com/v2/shipments"
            calls.append(request)
            if len(calls) == 1:
                entered.set()
                try:
                    await blocked.wait()
                finally:
                    cancelled.set()
            return httpx.Response(200, json=shipment())

        async def shortened_budget(awaitable, timeout):
            budgets.append(timeout)
            if len(budgets) == 1:
                pending = asyncio.create_task(awaitable)
                await asyncio.wait_for(entered.wait(), timeout=2)
                return await asyncio.wait_for(pending, timeout=0)
            return await asyncio.wait_for(awaitable, timeout=2)

        provider = adapter(handle)
        monkeypatch.setattr(rating, "asyncio", SimpleNamespace(wait_for=shortened_budget, Lock=asyncio.Lock))
        app = create_app(storage=tmp_path / "timeout-pilot", rating=provider)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver",
                                     headers={"x-inspectorpro-request": "packaging"}) as client:
            created = await client.post("/api/packaging/documents", json=make_design().model_dump(mode="json"))
            assert created.status_code == 200
            url = f"/api/packaging/documents/{created.json()['id']}/quotes"
            response = await client.post(url, json=quote_request().model_dump(mode="json"))
            assert response.status_code == 504
            assert response.json()["error"]["code"] == "quote_timeout"
            assert TEST_KEY not in response.text
            assert cancelled.is_set()
            assert (await client.get(url)).json() == {"quotes": []}
            retry = await client.post(url, json=quote_request().model_dump(mode="json"))
            assert retry.status_code == 200
            assert len((await client.get(url)).json()["quotes"]) == 1

    asyncio.run(scenario())
    assert budgets == [65, 65]
    assert len(calls) == 2
