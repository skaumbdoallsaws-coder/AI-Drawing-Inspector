import asyncio
from copy import deepcopy
from io import BytesIO
import os

import pytest
from jsonschema import Draft202012Validator
from PIL import Image

from ai_inspector.codex_runtime.authoring_artifacts import render_lettering, tool_specs as artifact_specs
from ai_inspector.codex_runtime.authoring_reads import read_authoring, tool_specs
from ai_inspector.codex_runtime.facility_tools import FacilityReadGateway, argument_errors
from ai_inspector.codex_runtime.policy import PilotError
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID, LOCAL_LAYOUT_ID


@pytest.fixture
def setup(tmp_path):
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    host.ensure_bootstrap()
    saved = host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    ref = dict(siteId=LOCAL_SITE_ID, layoutId=LOCAL_LAYOUT_ID, revision=saved["revision"])
    yield host, ref, saved
    host.close()


def test_authoring_schemas_are_closed_and_bounded():
    for spec in [*tool_specs(), *artifact_specs()]:
        Draft202012Validator.check_schema(spec["input_schema"])
        assert spec["input_schema"]["additionalProperties"] is False
    schema = tool_specs()[0]["input_schema"]
    for args in ({"view": "placements", "pageSize": 100}, {"view": "anything"},
                 {"view": "zones", "path": "C:/secret"}):
        assert list(Draft202012Validator(schema).iter_errors(args))


def test_inspection_uses_exact_saved_records_and_pagination(setup):
    host, ref, saved = setup
    before = deepcopy(saved)
    data = read_authoring(host.agent_runtime, host.principal(), ref, "inspect_facility_authoring",
                          {"view": "placements", "pageSize": 1})
    rows = sorted(saved["layout"]["placements"], key=lambda row: row["placementId"])
    assert data["records"] == rows[:1]
    assert data["total"] == len(rows)
    assert data["nextOffset"] == (1 if len(rows) > 1 else None)
    if rows:
        filtered = read_authoring(host.agent_runtime, host.principal(), ref, "inspect_facility_authoring",
                                 {"view": "placements", "ids": [rows[0]["placementId"]]})
        assert filtered["records"] == rows[:1]
    assert host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID) == before


def test_floor_markings_read_top_level_not_an_invented_extension(setup, monkeypatch):
    host, ref, saved = setup
    record = {"markingId": "fm-test", "label": "Test"}
    saved["layout"]["floorMarkings"] = [record]
    monkeypatch.setattr(host.service, "get_layout", lambda *args: deepcopy(saved))
    result = read_authoring(host.agent_runtime, host.principal(), ref, "inspect_facility_authoring", {"view": "floor_markings"})
    assert result["records"] == [record]


def test_perimeter_read_omits_generated_panels_preserves_art(setup, monkeypatch):
    host, ref, saved = setup
    settings = {"interiorColor": "#17191c", "exteriorFinish": {"fittedArtworks": [{"artworkId": "wolf", "label": "APEX"}]}}
    saved["layout"].setdefault("extensions", {})["facilityPerimeterWalls"] = dict(version=1, settings=settings, panels=[1]*1000)
    monkeypatch.setattr(host.service, "get_layout", lambda *args: deepcopy(saved))
    result = read_authoring(host.agent_runtime, host.principal(), ref, "inspect_facility_authoring", {"view": "perimeter_walls"})
    assert result["configuration"] == dict(version=1, settings=settings)
    art = read_authoring(host.agent_runtime, host.principal(), ref, "inspect_facility_authoring", {"view": "wall_artworks"})
    assert art["records"][0]["artworkId"] == "wolf"


def test_authoring_reads_reject_stale_binding(setup):
    host, ref, _ = setup
    with pytest.raises(PilotError, match="changed"):
        read_authoring(host.agent_runtime, host.principal(), dict(ref, revision="0"*64),
                       "inspect_facility_authoring", {"view": "zones"})


def test_asset_inspection_returns_exact_geometry_without_private_paths(setup):
    host, ref, _ = setup
    entry = list(host.agent_runtime.asset_catalog_provider(host.principal(), LOCAL_SITE_ID))[0]
    result = read_authoring(host.agent_runtime, host.principal(), ref, "inspect_facility_asset", {"assetId": entry["assetId"]})
    assert result["assetDefinitionRevision"] == entry["assetDefinitionRevision"]
    assert result["definition"]["geometry"] == entry["definition"]["geometry"]
    assert "overview" not in result["definition"]


def test_invalid_arguments_report_the_failed_field(setup):
    host, ref, _ = setup
    gateway = FacilityReadGateway(host.agent_runtime, host.principal(), ref, turn_id="authoring-fields")
    result = asyncio.run(gateway.call("inspect_facility_authoring", {"view": "zones", "pageSize": 100}))
    assert result["error"]["code"] == "codex_tool_arguments_invalid"
    assert result["error"]["details"]["findings"][0]["path"] == "/pageSize"


def test_a_page_size_up_to_50_is_read_as_pages_of_25(setup, monkeypatch):
    """inspect_facility_semantics takes pageSize up to 50; the same on this read was refused as malformed (live
    turn "show me the R03 robot", 2026-11-02, the probable cause). Now it is read, a page at most 25 records."""
    host, ref, saved = setup
    saved["layout"]["zones"] = [{"zoneId": f"zn-{index:02d}", "label": f"Bay {index}"} for index in range(30)]
    monkeypatch.setattr(host.service, "get_layout", lambda *args: deepcopy(saved))
    gateway = FacilityReadGateway(host.agent_runtime, host.principal(), ref, turn_id="authoring-page")
    result = asyncio.run(gateway.call("inspect_facility_authoring", {"view": "zones", "query": "bay", "pageSize": 50}))
    assert result["ok"], result
    assert len(result["data"]["records"]) == 25 and result["data"]["total"] == 30
    assert result["data"]["nextOffset"] == 25


def test_a_page_of_large_records_stops_where_they_fit(setup, monkeypatch):
    """43 placements of Robot Cell R01, with provenance, passed the 64 KB limit in one page of 25 and the read
    failed ("result too large to read", live turn "Stack 4 pallets at R01's input", 2026-11-02). Now the page
    stops where they fit and the rest come from nextOffset."""
    host, ref, saved = setup
    provenance = {"provenanceId": "layout-pattern:" + "a" * 40 + ":1", "notes": ["x" * 120] * 20}
    saved["layout"]["placements"] = [{
        "placementId": f"pl-r01-{index:02d}", "assetId": "asset-cnc-mill", "metadata": {
            "instanceLabel": f"R01 item {index}", "layoutProvenance": provenance}} for index in range(43)]
    monkeypatch.setattr(host.service, "get_layout", lambda *args: deepcopy(saved))
    gateway = FacilityReadGateway(host.agent_runtime, host.principal(), ref, turn_id="authoring-bytes")
    seen, offset = [], 0
    while offset is not None:
        arguments = {"view": "placements", "query": "R01", "pageSize": 50, **({"offset": offset} if offset else {})}
        result = asyncio.run(gateway.call("inspect_facility_authoring", arguments))
        assert result["ok"], result
        assert 0 < len(result["data"]["records"]) < 25 and result["data"]["total"] == 43
        seen += [record["placementId"] for record in result["data"]["records"]]
        offset = result["data"]["nextOffset"]
    assert seen == [f"pl-r01-{index:02d}" for index in range(43)]


def test_union_diagnostics_use_requested_operation_only():
    def variant(op, field):
        return {"type": "object", "properties": {"op": {"const": op}, field: {"type": "string"}}, "required": ["op", field]}
    schema = {"type": "object", "properties": {"operations": {"type": "array", "items": {"oneOf": [variant("a", "first"), variant("b", "second")]}}}}
    errors = argument_errors(Draft202012Validator(schema), {"operations": [{"op": "b"}]})
    assert len(errors) == 1 and "second" in errors[0]["message"] and "first" not in errors[0]["message"]


@pytest.mark.skipif(os.name != "nt", reason="Windows desktop font fixture")
def test_lettering_is_transparent_gold_and_bounded():
    settings = dict(text="TRAIN. RECOVER. RISE.", reference="APEX", font="Arial", align="center", color="#C99B39")
    payload, normalized = render_lettering(settings, 3)
    image = Image.open(BytesIO(payload)).convert("RGBA")
    assert image.width <= 3072 and image.height <= 2048
    assert image.getpixel((0, 0))[3] == 0
    assert image.getchannel("A").getbbox() is not None
    assert normalized["color"] == "#c99b39"
    assert any(pixel[:3] == (201, 155, 57) and pixel[3] for pixel in image.getdata())


def test_lettering_never_accepts_a_font_path():
    with pytest.raises(ValueError):
        render_lettering(dict(text="Title", reference="", font="C:/secret", align="center", color="#C99B39"), 2)
