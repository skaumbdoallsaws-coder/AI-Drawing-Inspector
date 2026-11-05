"""Offline MCP acceptance: real bridge, gateway, SQLite, and packing solver.

Requires requirements-codex-pilot.txt's MCP/jsonschema dependencies. Missing
dependencies fail collection rather than silently skipping this acceptance gate.
No AppServer, provider, application server, or shipping carrier is started.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
import json
import platform
import socket
import subprocess
import sys
import threading

import httpx
from jsonschema import Draft202012Validator
import pytest

from ai_inspector.codex_runtime.mcp_bridge import make_application, serve_gateway
from ai_inspector.codex_runtime.packaging_tools import (
    PackagingContext, PackagingGateway, create_packaging_gateway, packaging_scope,
)
from ai_inspector.packaging_shipping.models import Design, Edit
from ai_inspector.packaging_shipping.service import PackagingService
from ai_inspector.facility_layout.authorization import FacilityPrincipal


PROTOCOL = "2025-11-25"
ASGI_HOST = "127.0.0.1:7654"
READ_TOOLS = {"inspect_packaging", "validate_packaging", "propose_packaging"}
WRITE_TOOLS = {"edit_packaging", "undo_packaging", "redo_packaging"}


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    """Fail closed on outbound HTTP/DNS/socket attempts and process launches."""
    for flag in ("INSPECTORPRO_CODEX_READONLY_PILOT", "INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE"):
        monkeypatch.setenv(flag, "0")
    if sys.platform == "win32":
        # Uvicorn needs the OS family, not platform's optional `cmd /c ver` probe.
        monkeypatch.setattr(platform, "system", lambda: "Windows")

    def loopback(address):
        assert address in {"127.0.0.1", "::1"}, "Only literal loopback addresses are allowed"

    resolve = socket.getaddrinfo
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    send_async = httpx.AsyncClient.send
    send_sync = httpx.Client.send

    def local_resolve(host, *args, **kwargs):
        loopback(host)
        return resolve(host, *args, **kwargs)

    def local_connect(sock, address):
        loopback(address[0])
        return connect(sock, address)

    def local_connect_ex(sock, address):
        loopback(address[0])
        return connect_ex(sock, address)

    def local_request(request):
        loopback(request.url.host)
        assert request.url.scheme == "http", "Tests use local HTTP only"

    async def local_send_async(client, request, *args, **kwargs):
        local_request(request)
        return await send_async(client, request, *args, **kwargs)

    def local_send_sync(client, request, *args, **kwargs):
        local_request(request)
        return send_sync(client, request, *args, **kwargs)

    def no_process(*args, **kwargs):
        pytest.fail("MCP acceptance must not launch providers or subprocesses")

    monkeypatch.setattr(socket, "getaddrinfo", local_resolve)
    monkeypatch.setattr(socket.socket, "connect", local_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", local_connect_ex)
    monkeypatch.setattr(httpx.AsyncClient, "send", local_send_async)
    monkeypatch.setattr(httpx.Client, "send", local_send_sync)
    monkeypatch.setattr(subprocess, "Popen", no_process)


def design():
    return Design.model_validate({
        "name": "Offline MCP shipment", "quantity": 1,
        "product": {"name": "Measured component", "dimensions_m": [0.1, 0.2, 0.15],
                    "mass_kg": 2, "mass_basis": "user_measured", "mass_evidence": "Test scale"},
        "constraints": {"allowed_orientations": list(range(6)), "contents": "ordinary_nonhazardous"},
        "packages": [{"id": "box_1", "carton": {
            "name": "Test carton", "inner_m": [0.5, 0.5, 0.5], "outer_m": [0.52, 0.52, 0.52],
            "tare_kg": 0.3, "tare_evidence": "Test scale", "max_payload_kg": 20},
            "placements": [{"id": "item_1", "position_m": [0.02, 0.02, 0.02], "orientation": 0}],
            "inserts": [{"id": "pad_1", "name": "End pad", "dimensions_m": [0.01, 0.5, 0.5],
                         "position_m": [0, 0, 0], "density_kg_m3": 30,
                         "material_evidence": "Test supplier data"}],
            "allowance_kg": 0, "allowance_evidence": "No additional packing"}],
    })


@dataclass
class Host:
    service: PackagingService
    scope: str
    context: PackagingContext
    lease: threading.RLock

    def current_context(self):
        with self.lease:
            return self.context

    def refresh(self, **changes):
        with self.lease:
            self.context = replace(self.context, **changes)

    def gateway(self):
        return create_packaging_gateway(self.service, current_context=self.current_context,
            turn_id="offline-mcp-turn", mutation_guard=lambda: self.lease, max_calls=12)

    def saved(self, doc_id=None):
        return self.service.get(self.scope, doc_id or self.context.document_id)

    def rows(self):
        with self.service.db() as db:
            return {table: [tuple(row) for row in db.execute("SELECT * FROM " + table)]
                    for table in ("documents", "receipts", "sources", "quotes")}


@pytest.fixture
def host(tmp_path, monkeypatch):
    service = PackagingService(tmp_path / "mcp-packaging")
    principal = FacilityPrincipal("mcp-engineer", "mcp-tenant", ("site-b", "site-a"), ("editor",))
    scope = packaging_scope(principal)
    saved = service.create(scope, design())

    def no_quotes(*args, **kwargs):
        pytest.fail("MCP packaging tools must not persist carrier quotes")

    monkeypatch.setattr(service, "save_quotes", no_quotes)
    return Host(service, scope, PackagingContext(principal, "session-1", "conversation-1",
        "selection-1", saved["id"], 0, "packaging_shipping", False, False,
        direct_edit_authorized=True), threading.RLock())


@pytest.fixture(params=["asgi", "loopback"])
def transport(request):
    return request.param


def headers(token):
    return {"Authorization": "Bearer " + token,
            "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": PROTOCOL}


class MCPWire:
    """JSON-RPC on real MCP HTTP, with no gateway.call shortcut or canned result."""

    def __init__(self, client, url):
        self.client, self.url = client, url
        self.sequence = 0
        self.tools = {}

    async def request(self, method, params):
        self.sequence += 1
        return await self.client.post(self.url, json={"jsonrpc": "2.0", "id": self.sequence,
                                                     "method": method, "params": params})

    async def rpc(self, method, params):
        response = await self.request(method, params)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert body["jsonrpc"] == "2.0" and body["id"] == self.sequence
        assert "error" not in body, body
        return body["result"]

    async def initialize(self, gateway):
        result = await self.rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
            "clientInfo": {"name": "offline-packaging-acceptance", "version": "1"}})
        assert result["protocolVersion"] == PROTOCOL
        assert result["instructions"] == gateway.server_instructions
        assert "packaging" in result["instructions"] and "tools" in result["capabilities"]
        notified = await self.client.post(self.url, json={"jsonrpc": "2.0",
            "method": "notifications/initialized", "params": {}})
        assert notified.status_code == 202, notified.text

    async def discover(self, expected):
        listing = await self.rpc("tools/list", {})
        self.tools = {tool["name"]: tool for tool in listing["tools"]}
        assert len(self.tools) == len(listing["tools"]) and set(self.tools) == expected
        for name, tool in self.tools.items():
            assert tool["inputSchema"]["type"] == tool["outputSchema"]["type"] == "object"
            Draft202012Validator.check_schema(tool["inputSchema"])
            Draft202012Validator.check_schema(tool["outputSchema"])
            assert tool["annotations"]["readOnlyHint"] is (name in READ_TOOLS)
            assert tool["annotations"]["openWorldHint"] is False
        return self.tools

    async def call(self, name, arguments, *, error=None, schema_name=None):
        result = await self.rpc("tools/call", {"name": name, "arguments": arguments})
        assert result["isError"] is (error is not None), result
        structured = result["structuredContent"]
        assert structured["ok"] is (error is None), structured
        assert [item["type"] for item in result["content"]] == ["text"]
        assert json.loads(result["content"][0]["text"]) == structured
        schema = self.tools[schema_name or name]["outputSchema"]
        Draft202012Validator(schema).validate(structured)
        if error:
            assert structured["error"]["code"] == error, structured
        return structured


@asynccontextmanager
async def connection(gateway, transport):
    if transport == "loopback":
        async with serve_gateway(gateway) as (url, token):
            assert httpx.URL(url).host == "127.0.0.1" and httpx.URL(url).port > 0
            async with httpx.AsyncClient(headers=headers(token), trust_env=False, timeout=10) as client:
                wire = MCPWire(client, url)
                await wire.initialize(gateway)
                yield wire
        assert gateway.closed
        # Rebind without SO_REUSEADDR: prove the listener released its port,
        # independent of Windows' delay in reporting a refused connection.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", httpx.URL(url).port))
    else:
        app, manager = make_application(gateway, "offline-test-capability", ASGI_HOST)
        try:
            async with manager.run():
                asgi = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
                async with httpx.AsyncClient(transport=asgi, headers=headers("offline-test-capability"),
                                            trust_env=False, timeout=10) as client:
                    wire = MCPWire(client, "http://" + ASGI_HOST + "/mcp")
                    await wire.initialize(gateway)
                    yield wire
        finally:
            gateway.closed = True


def test_discover_inspect_propose_edit_validate_undo_and_redo(host, transport):
    gateway = host.gateway()
    assert isinstance(gateway, PackagingGateway)
    initial = host.saved()

    async def exercise():
        async with asyncio.timeout(30):
            async with connection(gateway, transport) as wire:
                await wire.discover(READ_TOOLS | WRITE_TOOLS)
                before = host.rows()
                inspected = await wire.call("inspect_packaging", {"expected_revision": 0})
                assert inspected["data"]["document"] == {"document_id": initial["id"], "revision": 0}
                assert inspected["data"]["assessment"]["rate_ready"] is True
                assert inspected["data"]["packages"][0]["inserts"][0]["id"] == "pad_1"
                proposed = await wire.call("propose_packaging", {"expected_revision": 0,
                    "cartons": [initial["design"]["packages"][0]["carton"]], "max_packages": 1, "limit": 1})
                assert proposed["data"]["saved"] is False
                assert proposed["data"]["replaces_existing_packages"] is True
                candidate, = proposed["data"]["candidates"]
                assert candidate["design"]["packages"][0]["placements"][0]["orientation"] in range(6)
                assert host.rows() == before, "Read/propose must not persist anything"

                command = {"expected_revision": 0, "request_id": "mcp-edit-1", "design": candidate["design"]}
                command["design"]["name"] = "Candidate saved through MCP"
                edited = await wire.call("edit_packaging", command)
                assert edited["data"]["receipt"] == {"request_id": "mcp-edit-1", "action": "edit",
                    "before_revision": 0, "after_revision": 1, "outcome": "committed"}
                assert edited["data"]["can_undo"] is True
                saved = host.saved()
                assert saved["revision"] == 1 and saved["design"] == command["design"]
                host.refresh(revision=1)
                replay = await wire.call("edit_packaging", command)
                assert replay["data"]["replayed"] is True and host.saved() == saved
                assessed = await wire.call("validate_packaging", {"expected_revision": 1})
                assert assessed["data"]["saved"] is True
                assert assessed["data"]["assessment"]["design_hash"] == saved["assessment"]["design_hash"]
                assert assessed["data"]["assessment"]["status"] == "failed"  # candidate lacks allowance evidence

                undone = await wire.call("undo_packaging", {"expected_revision": 1, "request_id": "mcp-undo-1"})
                assert undone["data"]["receipt"]["outcome"] == "committed"
                assert undone["data"]["receipt"]["after_revision"] == 2
                assert host.saved()["design"] == initial["design"]
                host.refresh(revision=2)
                redone = await wire.call("redo_packaging", {"expected_revision": 2, "request_id": "mcp-redo-1"})
                assert redone["data"]["receipt"]["after_revision"] == 3
                assert host.saved()["design"] == saved["design"]
                with host.service.db() as db:
                    rows = db.execute("SELECT result FROM receipts ORDER BY rowid").fetchall()
                    assert [json.loads(row[0])["receipt"]["action"] for row in rows] == ["edit", "undo", "redo"]
                    assert db.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 0
                assert len(gateway.receipts) == 7 and all(r["ok"] for r in gateway.receipts)
                assert str(host.service.root) not in json.dumps(inspected)

    asyncio.run(exercise())


@pytest.mark.parametrize("change,code", [
    ("selection", "codex_packaging_context_changed"),
    ("document", "codex_packaging_context_changed"),
    ("principal", "codex_packaging_context_changed"),
    ("dirty", "codex_saved_document_required"),
    ("revision", "revision_conflict"),
])
def test_stale_context_rejected_over_transport_without_mutation(host, transport, change, code):
    gateway = host.gateway()

    async def exercise():
        async with asyncio.timeout(30):
            async with connection(gateway, transport) as wire:
                await wire.discover(READ_TOOLS | WRITE_TOOLS)
                await wire.call("inspect_packaging", {"expected_revision": 0})
                if change == "selection":
                    host.refresh(selection_id="away-and-back-selection")
                elif change == "document":
                    other = host.service.create(host.scope, design())
                    host.refresh(document_id=other["id"], selection_id="other-document")
                elif change == "principal":
                    host.refresh(principal=replace(host.context.principal, roles=("viewer",)))
                elif change == "dirty":
                    host.refresh(dirty=True)
                else:
                    human = design().model_copy(update={"name": "Human revision"})
                    host.service.change(host.scope, host.context.document_id,
                        Edit(expected_revision=0, request_id="human-edit", design=human))
                before = host.rows()
                rejected = await wire.call("edit_packaging", {"expected_revision": 0,
                    "request_id": "must-not-commit", "design": design().model_dump(mode="json")}, error=code)
                assert rejected["mutation"]["outcome"] == "not_started"
                assert host.rows() == before and gateway.closed
                assert gateway.receipts[-1]["errorCode"] == code
                # Once the stale call closes the turn, the bridge revokes its capability.
                assert (await wire.request("tools/list", {})).status_code == 403
                assert (await wire.request("tools/call", {"name": "inspect_packaging",
                    "arguments": {"expected_revision": 0}})).status_code == 403

    asyncio.run(exercise())


def test_readonly_discovery_and_unadvertised_write_denial(host, transport):
    host.refresh(direct_edit_authorized=False)
    gateway = host.gateway()
    before = host.rows()

    async def exercise():
        async with asyncio.timeout(30):
            async with connection(gateway, transport) as wire:
                await wire.discover(READ_TOOLS)
                await wire.call("inspect_packaging", {"expected_revision": 0})
                await wire.call("edit_packaging", {"expected_revision": 0, "request_id": "denied",
                    "design": design().model_dump(mode="json")}, error="codex_tool_denied",
                    schema_name="inspect_packaging")
                assert host.rows() == before

    asyncio.run(exercise())


def test_invalid_arguments_and_stale_expected_revision_are_structured(host, transport):
    gateway = host.gateway()
    before = host.rows()

    async def exercise():
        async with asyncio.timeout(30):
            async with connection(gateway, transport) as wire:
                await wire.discover(READ_TOOLS | WRITE_TOOLS)
                command = {"expected_revision": 0, "request_id": "bad-input", "design": design().model_dump(mode="json")}
                for bad in ({**command, "scope": "foreign"}, {**command, "expected_revision": 0.0}):
                    await wire.call("edit_packaging", bad, error="codex_tool_arguments_invalid")
                bad = deepcopy(command)
                bad["design"]["product"]["source_path"] = "C:/private/not-a-source.glb"
                rejected = await wire.call("edit_packaging", bad, error="codex_tool_arguments_invalid")
                assert "private" not in json.dumps(rejected)
                await wire.call("validate_packaging", {"expected_revision": 1}, error="revision_conflict")
                await wire.call("inspect_packaging", {"expected_revision": 0})
                assert host.rows() == before

    asyncio.run(exercise())


@pytest.mark.parametrize("boundary", ["missing_token", "wrong_token", "origin", "host", "client", "path", "closed"])
def test_make_application_rejects_untrusted_transport_before_gateway(host, boundary):
    gateway = host.gateway()
    app, manager = make_application(gateway, "offline-test-capability", ASGI_HOST)
    before = host.rows()

    async def exercise():
        async with asyncio.timeout(15):
            async with manager.run():
                peer = "203.0.113.8" if boundary == "client" else "127.0.0.1"
                asgi = httpx.ASGITransport(app=app, client=(peer, 1234))
                request_headers = headers("offline-test-capability")
                if boundary == "missing_token":
                    request_headers.pop("Authorization")
                elif boundary == "wrong_token":
                    request_headers["Authorization"] = "Bearer wrong-capability"
                elif boundary == "origin":
                    request_headers["Origin"] = "http://127.0.0.1:7654"
                elif boundary == "host":
                    request_headers["Host"] = "untrusted.invalid"
                elif boundary == "closed":
                    gateway.closed = True
                path = "/not-mcp" if boundary == "path" else "/mcp"
                async with httpx.AsyncClient(transport=asgi, trust_env=False) as client:
                    response = await client.post("http://" + ASGI_HOST + path, headers=request_headers,
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                            "name": "edit_packaging", "arguments": {"expected_revision": 0,
                                "request_id": "untrusted", "design": design().model_dump(mode="json")}}})
                    assert response.status_code == 403 and response.text == "Forbidden"
                assert gateway.calls == 0 and gateway.receipts == [] and host.rows() == before

    asyncio.run(exercise())
