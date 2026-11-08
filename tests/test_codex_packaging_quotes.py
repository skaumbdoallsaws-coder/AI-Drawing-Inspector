"""Sage quote tools on the shared QuoteDesk (P5 item 5). MOCK ONLY: httpx.MockTransport replies priced by
the comparison tests' fixed formula, with synthetic TEST addresses and designs. "production" below is a mock
reply's mode field, not a live provider; nothing here is a real price or evidence of a live saving."""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import socket
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from pydantic import TypeAdapter
import pytest

from ai_inspector.codex_runtime import packaging_tools as tools
from ai_inspector.codex_runtime.packaging_pilot import INSTRUCTIONS, NO_QUOTES, _evidence, instructions_for
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.packaging_shipping.api import create_router
from ai_inspector.packaging_shipping.geometry import assess, digest
from ai_inspector.packaging_shipping.models import AlternativeSave, Design, ScenarioAuthorization
from ai_inspector.packaging_shipping.quoting import QuoteDesk, ScenarioStore
from ai_inspector.packaging_shipping.service import PackagingError, PackagingService
from tests.test_packaging_comparison import expected_shipping, one_box, priced, two_boxes
from tests.test_packaging_rating import adapter

HEADERS = {"x-inspectorpro-request": "packaging"}
STREET, NAME = "1 Test Street", "TEST ONLY"
ZIPS = ("60601", "75201", "78701")


def address(city="Chicago", state="IL", zip_code="60601", residential=False, street=STREET):
    return {"name": NAME, "street1": street, "city": city, "state": state, "zip": zip_code, "residential": residential}


DESTINATIONS = (address("Dallas", "TX", "75201", True), address("Austin", "TX", "78701"))


def authorization(shipments=4, count=2, **changes):
    return ScenarioAuthorization.model_validate({"origin": address(), "destinations": list(DESTINATIONS[:count]),
                                                 "sage_shipments": shipments, **changes})


def private(value):
    """True when a street, name or ZIP code would reach the model."""
    text = json.dumps(value)
    return STREET in text or NAME in text or any(z in text for z in ZIPS)


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def env(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Quote tests must not open network connections")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    calls, state = [], {"mode": "test", "currency": "USD", "express_max_oz": None}
    service, clock = PackagingService(tmp_path / "packaging"), Clock()
    desk = QuoteDesk(service, rating=adapter(priced(calls, state)), clock=clock)
    principal = FacilityPrincipal("engineer", "tenant-a", ("site-a",), ("editor",))
    scope = tools.packaging_scope(principal)
    saved = service.create(scope, two_boxes())
    return SimpleNamespace(service=service, desk=desk, calls=calls, state=state, clock=clock, principal=principal,
                           scope=scope, doc=saved["id"], hash=saved["assessment"]["design_hash"])


def gateway(env, principal=None, **kwargs):
    context = tools.PackagingContext(principal or env.principal, "session-1", "conversation-1", "selection-1",
                                     env.doc, 0, "packaging_shipping", False, False)
    return tools.create_packaging_gateway(env.service, current_context=lambda: context, turn_id="turn-1",
                                          quotes=env.desk, **({"max_calls": 16} | kwargs))


def invoke(gw, name, args):
    result = asyncio.run(gw.call(name, args))
    TypeAdapter(tools._TOOLS[name][1] | tools.Failure).validate_python(result)
    return result


def assert_error(result, code):
    assert result["ok"] is False and result["error"]["code"] == code, result


def scenario(env, owner="engineer", **changes):
    return env.desk.scenarios.create(env.scope, env.doc, owner, authorization(**changes))["id"]


def test_scenario_store_holds_addresses_and_shows_city_level_labels():
    store = ScenarioStore(Clock())
    public = store.create("scope", "doc", "me", authorization())
    assert public["origin"] == "Chicago, IL" and public["destinations"] == ["Dallas, TX (residential)", "Austin, TX"]
    assert public["sage_shipments"] == public["shipments_remaining"] == 4 and public["expires_in_s"] == 3600
    assert not private(public)
    assert store.list("scope", "doc", "me") == [public]
    assert store.list("scope", "doc", "someone-else") == [] and store.list("scope", "other-doc", "me") == []
    request = store.get("scope", "doc", "me", public["id"]).request(3, refresh=True)
    assert request.origin.street1 == STREET and request.expected_revision == 3 and request.refresh is True
    assert digest(request.scenario()) == public["scenario_hash"]
    for other in (("scope", "doc", "someone-else"), ("scope", "other-doc", "me"), ("other-scope", "doc", "me")):
        with pytest.raises(PackagingError) as caught:
            store.get(*other, public["id"])
        assert caught.value.code == "scenario_not_found"


def test_scenario_budget_expiry_revocation_and_refusals():
    clock = Clock()
    store = ScenarioStore(clock)
    sid = store.create("s", "d", "me", authorization(shipments=3))["id"]
    store.reserve("s", "d", "me", sid, 2)
    with pytest.raises(PackagingError) as caught:
        store.reserve("s", "d", "me", sid, 2)
    assert caught.value.code == "scenario_budget_exhausted"
    with pytest.raises(PackagingError) as caught:
        store.reserve("s", "d", "intruder", sid, 1)
    assert caught.value.code == "scenario_not_found" and store.remaining("s", "d", "me", sid) == 1
    clock.now += 3601
    assert store.list("s", "d", "me") == [] and store.remaining("s", "d", "me", sid) == 0
    sid = store.create("s", "d", "me", authorization())["id"]
    with pytest.raises(PackagingError):
        store.revoke("s", "d", "intruder", sid)
    assert store.revoke("s", "d", "me", sid) == {"revoked": sid} and store.list("s", "d", "me") == []
    for _ in range(8):
        store.create("s", "d", "me", authorization())
    with pytest.raises(PackagingError) as caught:
        store.create("s", "d", "me", authorization())
    assert caught.value.code == "scenario_limit"
    for changes, code in (({"origin": address(street="PO Box 12")}, "address_po_box_unsupported"),
                          ({"destinations": [address("APO", "AE", "09001")]}, "address_military_unsupported"),
                          ({"ship_date": date(2026, 11, 20)}, "ship_date_unsupported")):
        with pytest.raises(PackagingError) as caught:
            ScenarioStore(Clock()).create("s", "d", "me", authorization(**changes))
        assert caught.value.code == code
    with pytest.raises(ValueError):
        authorization(shipments=13)


def test_router_takes_one_desk_bound_to_its_service(tmp_path):
    service = PackagingService(tmp_path / "store")
    desk = QuoteDesk(service, rating=adapter(lambda request: pytest.fail("no provider call")))
    for kwargs in ({"rating": desk.provider}, {"credential_factory": lambda p: None}):
        with pytest.raises(ValueError):
            create_router(service, principal_resolver=lambda r: None, static_root=Path("static"), quotes=desk, **kwargs)
    with pytest.raises(ValueError):
        create_router(PackagingService(tmp_path / "other"), principal_resolver=lambda r: None, static_root=Path("static"), quotes=desk)


def app_for(env, current):
    app = FastAPI()
    app.include_router(create_router(env.service, principal_resolver=lambda r: current["principal"],
                                     static_root=Path("static"), quotes=env.desk))
    return app


def test_scenario_routes_hold_addresses_for_the_caller_only(env):
    current = {"principal": env.principal}
    body = json.loads(authorization().model_dump_json())
    path = f"/api/packaging/documents/{env.doc}/scenarios"
    with TestClient(app_for(env, current)) as client:
        created = client.post(path, json=body, headers=HEADERS)
        assert created.status_code == 200 and not private(created.json())
        sid = created.json()["id"]
        assert client.get(path).json()["scenarios"] == [created.json()]
        current["principal"] = FacilityPrincipal("someone-else", "tenant-a", ("site-a",), ("editor",))
        assert client.get(path).json()["scenarios"] == []
        assert client.delete(f"{path}/{sid}", headers=HEADERS).status_code == 404
        current["principal"] = env.principal
        assert client.delete(f"{path}/{sid}", headers=HEADERS).json() == {"revoked": sid}
        refused = client.post(path, json={**body, "origin": {**body["origin"], "street1": "PO Box 7"}}, headers=HEADERS)
        assert refused.status_code == 422 and refused.json()["error"]["code"] == "address_po_box_unsupported"
        assert client.get("/api/packaging/status").json()["capabilities"].count("sage_quote_scenarios") == 1
    assert env.calls == [] and env.desk.scenarios.list(env.scope, env.doc, "engineer") == []


def test_quote_tools_follow_the_desk_and_the_quote_permission(env):
    context = tools.PackagingContext(env.principal, "session-1", "conversation-1", "selection-1", env.doc, 0,
                                     "packaging_shipping", False, False)
    plain = tools.create_packaging_gateway(env.service, current_context=lambda: context, turn_id="turn-1")
    assert not {s["name"] for s in plain.specs} & tools._QUOTING
    assert "provider tools" in plain.server_instructions and instructions_for(plain) == INSTRUCTIONS
    gw = gateway(env)
    specs = {s["name"]: s for s in gw.specs}
    assert tools._QUOTING <= set(specs) and specs["quote_packaging"]["read_only"] is False
    assert specs["compare_packaging"]["read_only"] and specs["packaging_quote_scenarios"]["read_only"]
    assert "provider tools" not in gw.server_instructions and "scenario IDs" in gw.server_instructions
    assert NO_QUOTES not in instructions_for(gw) and "quote_packaging prices the saved design" in instructions_for(gw)
    viewer = gateway(env, FacilityPrincipal("viewer-1", "tenant-a", ("site-a",), ("viewer",)))
    names = {s["name"] for s in viewer.specs}
    assert "quote_packaging" not in names and {"packaging_quote_scenarios", "compare_packaging"} <= names
    sid = scenario(env, owner="viewer-1")
    assert_error(invoke(viewer, "quote_packaging", {"expected_revision": 0, "scenario_id": sid,
                                                     "expected_design_hash": env.hash}), "codex_tool_denied")
    assert env.calls == []
    with pytest.raises(Exception):
        tools.create_packaging_gateway(env.service, current_context=lambda: context, turn_id="turn-1",
                                       quotes=QuoteDesk(PackagingService(env.service.root.parent / "other")))


def test_sage_quotes_an_authorized_scenario_without_seeing_addresses(env):
    gw = gateway(env)
    args = {"expected_revision": 0, "scenario_id": "scn_" + "0" * 24, "expected_design_hash": env.hash}
    assert_error(invoke(gw, "quote_packaging", args), "scenario_not_found")
    sid = scenario(env, shipments=5)
    args["scenario_id"] = sid
    listed = invoke(gw, "packaging_quote_scenarios", {"expected_revision": 0})
    assert [s["id"] for s in listed["data"]["authorized"]] == [sid] and listed["data"]["can_quote"]
    assert listed["data"]["quoted"] == []
    assert_error(invoke(gw, "quote_packaging", {**args, "expected_design_hash": "0" * 64}), "quote_design_changed")
    assert env.calls == []

    quoted = invoke(gw, "quote_packaging", args)
    data = quoted["data"]
    assert quoted["ok"] and data["reused"] is False and data["provider_shipments_created"] == 4 == len(env.calls)
    assert data["shipments_remaining"] == 1 and data["mode"] == "test" and data["design_ref"] == "current"
    assert [d["destination"] for d in data["destinations"]] == ["Dallas, TX (residential)", "Austin, TX"]
    for destination in data["destinations"]:
        ground = destination["totals"][0]
        assert ground["service"] == "TEST Ground" and Decimal(ground["amount"]) == expected_shipping(two_boxes(), destinations=1)
    # The host sends the real addresses to the provider; nothing Sage receives carries them.
    assert {c["to_address"]["street1"] for c in env.calls} == {c["from_address"]["street1"] for c in env.calls} == {STREET}
    assert not private(quoted) and not private(listed)
    history = env.service.quote_history(env.scope, env.doc)
    assert [q["id"] for q in history] == [data["quote_id"]] and history[0]["design_hash"] == env.hash
    assert [a["outcome"] for a in env.service.quote_attempts(env.scope, env.doc)["attempts"]] == ["saved"]
    assert gw.receipts[-1]["external"] == {"kind": "carrier_quote", "scenario_id": sid, "design_ref": "current",
        "design_hash": env.hash, "scenario_hash": data["scenario_hash"], "shipments_reserved": 4,
        "provider_shipments_created": 4, "outcome": "saved", "quote_id": data["quote_id"], "mode": "test"}

    again = invoke(gw, "quote_packaging", args)["data"]
    assert again["reused"] and again["quote_id"] == data["quote_id"] and again["provider_shipments_created"] == 0
    assert len(env.calls) == 4 and again["shipments_remaining"] == 1 and gw.receipts[-1]["external"]["outcome"] == "reused"
    assert_error(invoke(gw, "quote_packaging", {**args, "refresh": True}), "scenario_budget_exhausted")
    assert len(env.calls) == 4 and len(env.service.quote_attempts(env.scope, env.doc)["attempts"]) == 1
    listed = invoke(gw, "packaging_quote_scenarios", {"expected_revision": 0})["data"]
    assert [q["scenario_hash"] for q in listed["quoted"]] == [data["scenario_hash"]] and not private(listed)
    evidence = _evidence(gw, settings=SimpleNamespace(auth_mode="test"), effort="low")
    assert [row["outcome"] for row in evidence["externalRequests"]] == ["saved", "reused", "not_started"]


def test_a_failed_provider_request_keeps_its_reservation_and_audit(env):
    def failing(request):
        env.calls.append(json.loads(request.content)["shipment"])
        return httpx.Response(500, json={"error": {"code": "TEST"}})
    env.desk.provider = adapter(failing)
    gw = gateway(env)
    sid = scenario(env, shipments=6)
    result = invoke(gw, "quote_packaging", {"expected_revision": 0, "scenario_id": sid, "expected_design_hash": env.hash})
    assert result["ok"] is False and result["error"]["code"] in {"carrier_unavailable", "carrier_request_failed"}
    assert gw.receipts[-1]["external"]["outcome"] == "failed" and gw.receipts[-1]["external"]["shipments_reserved"] == 4
    assert env.desk.scenarios.remaining(env.scope, env.doc, "engineer", sid) == 2
    assert env.service.quote_history(env.scope, env.doc) == []
    assert [a["outcome"] for a in env.service.quote_attempts(env.scope, env.doc)["attempts"]] == ["failed"]
    assert not gw.closed


def test_sage_quotes_alternatives_and_compares_saved_quotes(env):
    env.state["mode"] = "production"  # A mock reply field only; this is still MockTransport.
    env.desk.provider.declared_mode = "production"  # The TEST key recorded to match the mock replies.
    gw = gateway(env)
    alt = env.service.save_alternative(env.scope, env.doc, AlternativeSave(expected_revision=0, request_id="alt-1",
                                                                           name="TEST one box", design=one_box()))
    sid = scenario(env, shipments=12)
    invoke(gw, "quote_packaging", {"expected_revision": 0, "scenario_id": sid, "expected_design_hash": env.hash})
    assert_error(invoke(gw, "quote_packaging", {"expected_revision": 0, "scenario_id": sid, "alternative_id": alt["id"],
                                                "expected_design_hash": env.hash}), "quote_design_changed")
    other = invoke(gw, "quote_packaging", {"expected_revision": 0, "scenario_id": sid, "alternative_id": alt["id"],
                                           "expected_design_hash": assess(one_box())["design_hash"]})["data"]
    assert other["design_ref"] == alt["id"] and other["provider_shipments_created"] == 2 and len(env.calls) == 6
    compared = invoke(gw, "compare_packaging", {"expected_revision": 0, "scenario_id": sid})
    data = compared["data"]
    rows = {r["ref"]: r for r in data["rows"]}
    assert rows["current"]["baseline"] and rows[alt["id"]]["eligible"] and data["ranking"][0] == alt["id"]
    assert Decimal(rows[alt["id"]]["shipping_difference"]) == expected_shipping(one_box()) - expected_shipping(two_boxes()) < 0
    assert data["savings_claimed"] and "Dallas, TX (residential); Austin, TX" in rows[alt["id"]]["claim"]
    assert not private(compared)
    by_hash = invoke(gw, "compare_packaging", {"expected_revision": 0, "scenario_hash": data["scenario_hash"]})["data"]
    assert by_hash["rows"] == data["rows"]
    express = invoke(gw, "compare_packaging", {"expected_revision": 0, "scenario_id": sid, "service": {
        "carrier": "TEST Carrier", "service": "TEST Express", "account_id": "ca_TEST_A", "currency": "USD"}})["data"]
    assert express["service"]["service"] == "TEST Express"
    assert_error(invoke(gw, "compare_packaging", {"expected_revision": 0}), "codex_tool_arguments_invalid")
    assert len(env.calls) == 6  # Comparing made no provider request.


def test_quote_binding_follows_revision_owner_revocation_and_expiry(env):
    gw = gateway(env)
    sid = scenario(env)
    args = {"expected_revision": 0, "scenario_id": sid, "expected_design_hash": env.hash}
    assert_error(invoke(gw, "quote_packaging", {**args, "expected_revision": 1}), "revision_conflict")
    assert_error(invoke(gw, "quote_packaging", {**args, "scenario_id": scenario(env, owner="someone-else")}), "scenario_not_found")
    env.desk.scenarios.revoke(env.scope, env.doc, "engineer", sid)
    assert_error(invoke(gw, "quote_packaging", args), "scenario_not_found")
    later = scenario(env)
    env.clock.now += 3601
    assert_error(invoke(gw, "quote_packaging", {**args, "scenario_id": later}), "scenario_not_found")
    assert_error(invoke(gw, "compare_packaging", {"expected_revision": 0, "scenario_id": later}), "scenario_not_found")
    assert env.calls == []


def test_manual_and_sage_quotes_share_one_lock(env):
    class Held:
        def locked(self):
            return True
    env.desk.lock = Held()
    gw = gateway(env)
    sid = scenario(env)
    assert_error(invoke(gw, "quote_packaging", {"expected_revision": 0, "scenario_id": sid,
                                                "expected_design_hash": env.hash}), "quote_in_progress")
    body = {"expected_revision": 0, "origin": address(), "destinations": [DESTINATIONS[0]]}
    with TestClient(app_for(env, {"principal": env.principal})) as client:
        response = client.post(f"/api/packaging/documents/{env.doc}/quotes", json=body, headers=HEADERS)
    assert response.status_code == 429 and response.json()["error"]["code"] == "quote_in_progress"
    assert env.calls == [] and env.desk.scenarios.remaining(env.scope, env.doc, "engineer", sid) == 4


def test_after_a_mode_mismatch_sage_is_refused_and_nothing_more_is_sent(env):
    env.state["mode"] = "production"  # A mock reply field only; the TEST key stays recorded as test.
    gw = gateway(env)
    sid = scenario(env, shipments=8)
    args = {"expected_revision": 0, "scenario_id": sid, "expected_design_hash": env.hash}
    assert_error(invoke(gw, "quote_packaging", args), "account_mode_mismatch")
    assert len(env.calls) == 1  # the request that revealed the mismatch was sent; nothing after it
    for again in (args, {**args, "refresh": True}):
        assert_error(invoke(gw, "quote_packaging", again), "account_mode_mismatch")
    assert len(env.calls) == 1 and env.desk.scenarios.remaining(env.scope, env.doc, "engineer", sid) == 4
    assert [a["outcome"] for a in env.service.quote_attempts(env.scope, env.doc)["attempts"]] == ["failed"]
    assert env.service.quote_history(env.scope, env.doc) == []


def test_sage_cannot_quote_test_assumption_contents_on_a_production_key(env):
    data = two_boxes().model_dump(mode="json")
    data["constraints"].update(contents_basis="test_assumption", contents_evidence="TEST synthetic connection-test parcel")
    saved = env.service.create(env.scope, Design.model_validate(data))
    env.doc, env.hash = saved["id"], saved["assessment"]["design_hash"]
    env.state["mode"] = "production"
    env.desk.provider.declared_mode = "production"  # Mock only.
    sid = scenario(env, shipments=4)
    result = invoke(gateway(env), "quote_packaging", {"expected_revision": 0, "scenario_id": sid, "expected_design_hash": env.hash})
    assert_error(result, "test_assumption_needs_test_key")
    assert env.calls == [] and env.service.quote_attempts(env.scope, env.doc)["attempts"] == []
