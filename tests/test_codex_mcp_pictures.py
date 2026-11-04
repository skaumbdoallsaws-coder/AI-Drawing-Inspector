"""SV5 fix (docs/sage-basic-shapes-plan.md, Part B): the pinned Codex (0.162.1) gives the model only the structured
content of a tool result that has it, so the picture beside it never reached Sage. A result with a picture is now its
JSON text and the picture, with no structured content, and the tools that can attach a picture declare no output
schema (MCP asks every tool that declares one for structured content). Every other result and tool is as before.
"""
import asyncio
import base64
import json

import httpx
import pytest

from ai_inspector.codex_runtime import documentation_tools, facility_tools
from ai_inspector.codex_runtime.facility_tools import OUTPUT_SCHEMA
from ai_inspector.codex_runtime.mcp_bridge import make_application

PICTURE = {"mimeType": "image/jpeg", "data": base64.b64encode(b"\xff\xd8\xff a picture").decode("ascii")}
# The tools that can attach a picture: show_facility_views (Sage's 3D shots, facility_tools._take_shots) and
# look_at_site_photo (the outlined site photo, site_tools' _image). The Documentation gateway attaches none.
PICTURE_TOOLS = {"show_facility_views", "look_at_site_photo"}
HEADERS = {"Authorization": "Bearer secret", "Accept": "application/json, text/event-stream",
           "MCP-Protocol-Version": "2025-11-25"}


class Gateway:
    """Answers as the real gateways do: a JSON result per call, in order, and maybe a picture, handed out once."""
    closed = False
    server_instructions = None

    def __init__(self, specs, answers=()):
        self.specs, self.answers, self.image = specs, list(answers), None

    async def call(self, name, arguments):
        result, self.image = self.answers.pop(0)
        return result

    def take_image(self):
        image, self.image = self.image, None
        return image


def spec(name, **extra):
    return {"name": name, "description": "A tool.",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}, **extra}


def posted(gateway, *requests):
    """The JSON-RPC results of REQUESTS ((method, params)) posted to the bridge for GATEWAY, in process."""
    pytest.importorskip("mcp")
    app, manager = make_application(gateway, "secret", "127.0.0.1:7654")

    async def exercise():
        results = []
        async with manager.run():
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:7654") as client:
                for number, (method, params) in enumerate(requests, 1):
                    response = await client.post("/mcp", headers=HEADERS, json={
                        "jsonrpc": "2.0", "id": number, "method": method, "params": params})
                    assert response.status_code == 200, response.text
                    results.append(response.json()["result"])
        return results
    return asyncio.run(exercise())


def called(name):
    return "tools/call", {"name": name, "arguments": {}}


def test_a_result_with_a_picture_is_its_json_text_and_the_picture_without_structured_content():
    result = {"ok": True, "data": {"pictures": "Attached: one contact sheet of 2 3D shots."}}
    got, = posted(Gateway([spec("show_facility_views", pictures=True)], [(result, PICTURE)]),
                  called("show_facility_views"))
    assert got.get("structuredContent") is None, "the pinned Codex would give the model the JSON without the picture"
    text, image = got["content"]
    assert text["type"] == "text" and json.loads(text["text"]) == result, "the JSON text is the whole result"
    assert {key: image.get(key) for key in ("type", "data", "mimeType")} == {"type": "image", **PICTURE}
    assert not got.get("isError")


def test_every_result_without_a_picture_is_as_before():
    """No picture, a failed call (a picture left over is not attached), or a tool that never attaches one: the JSON
    text and the same JSON as structured content."""
    ok = {"ok": True, "data": {"pictures": "None: no app window has this layout open."}}
    failed = {"ok": False, "error": {"code": "codex_tool_failed", "message": "The shots failed."}}
    plain = {"ok": True, "data": {"layout": "Factory 02"}}
    gateway = Gateway([spec("show_facility_views", pictures=True), spec("inspect_facility_context")],
                      [(ok, None), (failed, PICTURE), (plain, None)])
    got = posted(gateway, called("show_facility_views"), called("show_facility_views"),
                 called("inspect_facility_context"))
    for answer, result, error in zip(got, (ok, failed, plain), (False, True, False)):
        assert answer["structuredContent"] == result and [item["type"] for item in answer["content"]] == ["text"]
        assert json.loads(answer["content"][0]["text"]) == result and bool(answer.get("isError")) is error


def test_the_tools_that_can_attach_a_picture_declare_no_output_schema_and_the_others_keep_theirs():
    facility = facility_tools.tool_specs()
    assert {item["name"] for item in facility if item.get("pictures")} == PICTURE_TOOLS
    for specs in (facility, documentation_tools.tool_specs(), documentation_tools.tool_specs(research=True)):
        listed, = posted(Gateway(specs), ("tools/list", {}))
        tools = {tool["name"]: tool for tool in listed["tools"]}
        assert set(tools) == {item["name"] for item in specs}
        for item in specs:
            schema = tools[item["name"]].get("outputSchema")
            if item["name"] in PICTURE_TOOLS:
                assert schema is None, f"{item['name']} declares no output schema"
            else:
                expected = json.loads(json.dumps(item.get("output_schema", OUTPUT_SCHEMA)))
                assert schema == expected, f"{item['name']} keeps its output schema"
