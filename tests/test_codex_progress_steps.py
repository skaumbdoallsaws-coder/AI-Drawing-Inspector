"""Plain-language steps in the chat pane while Sage works. All inference is stubbed."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from ai_inspector.codex_runtime.policy import LIVE_FLAG, PilotSettings
from ai_inspector.codex_runtime.progress import LayoutNames, TurnProgress, describe
from ai_inspector.facility_layout.host import LOCAL_ASSET_CATALOG, LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost

LAYOUT = {
    "zones": [{"zoneId": "zn-office", "label": "Offices"},
              {"zoneId": "zn-receiving", "label": "Receiving (2 truck doors, west wall)"}],
    "placements": [{"placementId": "pl-desk", "assetId": "asset-desk"},
                   {"placementId": "pl-chair", "assetId": "asset-chair", "metadata": {"instanceLabel": "Visitor chair"}}],
}
CATALOG = [{"assetId": "asset-desk", "displayName": "1400 mm Wood Desk"},
           {"assetId": "asset-chair", "displayName": "Office Chair"}]
NAMES = LayoutNames(LAYOUT, CATALOG)


def running(name, arguments, edit_mode=None):
    return describe(name, arguments, NAMES, edit_mode)["running"]


def test_steps_name_zones_items_and_changes_in_plain_words():
    assert describe("inspect_facility_context", {}, NAMES) == {
        "running": "Reading the layout overview", "done": "Read the layout overview",
        "failed": "Couldn't read the layout overview"}
    assert running("analyze_facility_spatial", {"analysis": "protected_intrusions", "scopeIds": ["zn-office"]}) \
        == "Checking walkways for blockages in Offices"
    assert running("analyze_facility_spatial", {"analysis": "clearances", "query": "Offices"}) \
        == 'Checking clearances for "Offices"'
    assert running("analyze_facility_spatial", {"analysis": "route_widths", "sourceZoneIds": ["zn-receiving"],
                                                "targetZoneIds": ["zn-office"]}) \
        == "Measuring aisle widths between Receiving and Offices"
    assert running("analyze_facility_fit", {"assetId": "asset-desk", "zoneId": "zn-office"}) \
        == "Checking where 1400 mm Wood Desk fits in Offices"
    assert running("inspect_facility_asset", {"assetId": "asset-desk"}) == "Looking up 1400 mm Wood Desk"
    assert running("inspect_facility_components", {"placementId": "pl-chair"}) == "Reading the parts of Visitor chair"
    # An item about to be placed: its catalog name.
    assert running("inspect_facility_components", {"assetId": "asset-desk"}) == "Reading the parts of 1400 mm Wood Desk"
    assert running("inspect_facility_authoring", {"view": "placements", "query": "desk"}) \
        == 'Reading placed equipment matching "desk"'
    assert running("inspect_facility_authoring", {"view": "placements", "offset": 25, "pageSize": 25}) \
        == "Reading placed equipment, items 26-50"
    assert running("inspect_facility_semantics", {"view": "zones", "ids": ["zn-office", "zn-receiving"]}) \
        == "Reading zone details: Offices and Receiving"
    assert running("inspect_facility_region", {"regionKind": "zone", "regionId": "zn-office"}) \
        == "Reading the Offices zone"
    assert running("search_industrial_assets", {"query": "pallet truck"}) \
        == 'Searching the library for "pallet truck"'
    place = {"op": "place_asset"}
    assert running("preview_facility_operations", {"operations": [place, place]}, "preview") \
        == "Staging 2 new items for your review"
    assert running("preview_facility_operations", {"operations": [place, {"op": "move_placement"}]}, "direct") \
        == "Staging 1 new item and 1 move"
    mixed = [place, {"op": "move_placement"}, {"op": "set_ground"}]
    assert running("preview_facility_operations", {"operations": mixed}, "preview") \
        == "Staging 3 changes for your review"


def test_steps_never_show_internal_ids_or_break_on_odd_arguments():
    labels = [running("analyze_facility_spatial", {"analysis": "clearances", "scopeIds": ["zn-unknown"]}),
              running("inspect_facility_asset", {"assetId": "asset-unknown"}),
              running("inspect_facility_entities", {"entityKind": "zone", "ids": ["zn-1", "zn-2", "zn-3"]})]
    assert labels == ["Checking clearances for 1 selected", "Looking up a library item", "Reading 3 zones"]
    assert running("unknown_tool", {}) == "Running a layout check"
    assert running("preview_facility_operations", {"operations": "not a list"}) == "Staging changes"
    assert describe("analyze_facility_fit", None)["running"] == "Checking where an item fits"
    long_label = LayoutNames({"zones": [{"zoneId": "z", "label": "x" * 80}]}).zone("z")
    assert len(long_label) == 40 and long_label.endswith("...")


def collector():
    steps = []

    async def sink(step):
        steps.append((step["kind"], step["state"], step["label"]))
    return steps, sink


def test_remarks_between_tool_calls_leave_the_answer_and_precede_their_step():
    steps, sink = collector()
    streamed = []

    async def text_sink(delta):
        streamed.append(delta)

    async def exercise():
        progress = TurnProgress(sink, text_sink=text_sink, names=lambda: NAMES, edit_mode="preview")
        # The tool reaches the gateway before the runtime reports its start.
        await progress.text("The first preview left out the racks. ")
        await progress.text("I'm re-staging the batch.")
        call = asyncio.create_task(progress.tool_started("preview_facility_operations",
                                                         {"operations": [{"op": "place_asset"}]}))
        await asyncio.sleep(0.05)
        assert steps == []
        await progress.status("codex_inspecting")
        started = await call
        await progress.tool_finished(started, {"ok": False, "error": {"code": "codex_result_too_large"}})
        await progress.text("I staged the revised batch.")
        return await progress.finish("The first preview left out the racks. I'm re-staging the batch."
                                     "I staged the revised batch.")

    assert asyncio.run(exercise()) == "I staged the revised batch."
    assert steps == [
        ("remark", "done", "The first preview left out the racks. I'm re-staging the batch."),
        ("tool", "running", "Staging 1 new item for your review"),
        ("tool", "failed", "Couldn't stage 1 new item for your review (result too large to read)"),
    ]
    assert "".join(streamed).endswith("I staged the revised batch.")


@pytest.mark.parametrize("code, reason", [
    ("spatial_validation_failed", " (spatial checks failed)"),
    ("facility_agent_revision_invalid", " (malformed request)"),
    ("facility_something_new", ""),
])
def test_failed_steps_name_the_reason_when_it_helps(code, reason):
    steps, sink = collector()

    async def exercise():
        progress = TurnProgress(sink)
        progress.RUNTIME_WAIT_SECONDS = 0
        started = await progress.tool_started("preview_facility_operations", {"operations": [{"op": "place_asset"}]})
        await progress.tool_finished(started, {"ok": False, "error": {"code": code, "message": "details"}})

    asyncio.run(exercise())
    assert steps[-1] == ("tool", "failed", "Couldn't stage 1 new item" + reason)


def test_a_coverage_check_tells_the_view_what_to_show_and_other_steps_do_not():
    """docs/facility-lighting-plan.md, "Sage shows the overlay": the done step of check_lighting_coverage carries
    the area Sage checked and the layout revision it read; the chat page hands it to the facility view."""
    sent = []

    async def sink(step):
        sent.append(step)
    identity = {"siteId": "site-local", "layoutId": "fl-a", "revision": "r" * 64}
    area = {"zoneId": "zn-yard-all", "darkBelowLux": 5}

    async def exercise():
        progress = TurnProgress(sink)
        progress.RUNTIME_WAIT_SECONDS = 0
        started = await progress.tool_started("check_lighting_coverage", area)
        await progress.tool_finished(started, {"ok": True, "data": {"identity": identity, "estimatedLux": {}}})
        started = await progress.tool_started("check_lighting_coverage", {"lot": True})
        await progress.tool_finished(started, {"ok": False, "error": {"code": "lighting_coverage_unavailable"}})
        started = await progress.tool_started("inspect_facility_context", {})
        await progress.tool_finished(started, {"ok": True, "data": {"identity": identity}})

    asyncio.run(exercise())
    done = [step for step in sent if step["state"] != "running"]
    assert done[0]["show"] == {"lightingCoverage": dict(identity, area=area)}
    assert done[0]["show"]["lightingCoverage"]["area"] is not area, "a copy"
    assert [step["state"] for step in done] == ["done", "failed", "done"]
    assert "show" not in done[1] and "show" not in done[2]
    page = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_bytes().decode("utf-8")
    assert "workingState.step(event.step);\n                                    _trainFacilityShowFromStep(event.step);" \
        in page.replace("\r\n", "\n")
    assert "workspace.showSageLightCoverage(coverage)" in page


def test_answers_without_remarks_are_unchanged_and_a_silent_runtime_costs_little():
    steps, sink = collector()

    async def exercise():
        progress = TurnProgress(sink)
        began = time.monotonic()
        started = await progress.tool_started("inspect_facility_context", {})
        waited = time.monotonic() - began
        await progress.tool_finished(started, {"ok": True})
        await progress.text("Two zones.")
        return waited, await progress.finish("Two zones, exactly as returned.")

    waited, answer = asyncio.run(exercise())
    assert waited < 1 and answer == "Two zones, exactly as returned."
    assert steps == [("tool", "running", "Reading the layout overview"), ("tool", "done", "Read the layout overview")]


@pytest.fixture
def host(tmp_path):
    value = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    value.ensure_bootstrap()
    yield value
    value.close()


def reference(host):
    current = host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    return {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": current["revision"]}


def test_edit_gateway_names_real_calls_from_the_saved_layout_and_catalog(host):
    bench = next(item for item in LOCAL_ASSET_CATALOG if item["assetId"] == "asset-workbench")
    steps, sink = collector()
    gateway = FacilityEditGateway(host.agent_runtime, host.principal(), reference(host), turn_id="steps-test")
    gateway.progress = TurnProgress(sink, names=gateway.layout_names, edit_mode="preview")
    operation = {"op": "place_asset", "placement": {
        "assetId": "asset-workbench", "assetDefinitionRevision": bench["assetDefinitionRevision"],
        "positionMode": "manual", "snapRelationship": None, "metadata": {},
        "transform": {"position": {"x": 6, "y": 0, "z": 6}, "scale": 1,
                      "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}}}}

    async def exercise():
        assert (await gateway.call("inspect_facility_asset", {"assetId": "asset-workbench"}))["ok"]
        assert (await gateway.call("preview_facility_operations", {"operations": [operation]}))["ok"]
        assert not (await gateway.call("open_any_file", {}))["ok"]

    asyncio.run(exercise())
    assert steps == [
        ("tool", "running", "Looking up Assembly Workbench"), ("tool", "done", "Looked up Assembly Workbench"),
        ("tool", "running", "Staging 1 new item for your review"),
        ("tool", "done", "Staged 1 new item for your review"),
        ("tool", "running", "Running a layout check"), ("tool", "failed", "Couldn't run a layout check (not allowed)"),
    ]


def test_pilot_streams_steps_and_keeps_remarks_out_of_the_answer(host, tmp_path, monkeypatch):
    from ai_inspector.codex_runtime import pilot
    monkeypatch.setenv(LIVE_FLAG, "1")
    monkeypatch.setenv("INSPECTORPRO_CODEX_API_KEY", "synthetic-never-sent")
    monkeypatch.delenv("INSPECTORPRO_CODEX_EDIT_PREVIEWS", raising=False)
    state, steps, statuses, streamed = {}, [], [], []

    @asynccontextmanager
    async def bridge(reader):
        state["gateway"] = reader
        yield "http://127.0.0.1:9/mcp", "test-capability"

    class Transport:
        def __init__(self, *_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def inspect(self, **kwargs):
            kwargs["on_thread"]("thread-test")
            await kwargs["text_sink"]("I'll read the overview first.")
            await kwargs["status_sink"]("codex_inspecting")
            assert (await state["gateway"].call("inspect_facility_context", {}))["ok"]
            await kwargs["text_sink"]("The layout has no zones yet.")
            return "I'll read the overview first.The layout has no zones yet."

    async def step_sink(step):
        steps.append((step["kind"], step["state"], step["label"]))

    async def status_sink(phase):
        statuses.append(phase)

    async def text_sink(delta):
        streamed.append(delta)

    monkeypatch.setattr(pilot, "serve_gateway", bridge)
    request = SimpleNamespace(agent_session_id="session", session_id=None, client_turn_id="turn",
                              conversation_id="conversation", message="Inspect the layout")
    result = asyncio.run(pilot.inspect_facility(
        request, host, None, {"facility_layout_ref": reference(host)},
        settings=PilotSettings(Path("unused"), tmp_path / "pilot", "test-model"), transport_factory=Transport,
        text_sink=text_sink, status_sink=status_sink, step_sink=step_sink))
    assert result["response"] == "The layout has no zones yet."
    assert steps == [("remark", "done", "I'll read the overview first."),
                     ("tool", "running", "Reading the layout overview"), ("tool", "done", "Read the layout overview")]
    assert streamed == ["I'll read the overview first.", "The layout has no zones yet."]
    assert statuses[0] == "codex_connecting" and statuses.count("codex_inspecting") == 2
