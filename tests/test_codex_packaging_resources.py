"""Additional Sage tools remain read-only, admitted and source-bound."""
from copy import deepcopy
from dataclasses import replace

from ai_inspector.packaging_shipping.models import AlternativeSave
from tests.test_codex_packaging_tools import env, gateway, invoke, snapshot, assert_error


def test_catalog_and_report_are_read_only_and_revision_bound(env):
    gw = gateway(env)
    before = snapshot(env)
    result = invoke(gw, "packaging_resources", {"expected_revision": 0, "resource": "catalog"})
    assert result["ok"], result
    assert len(result["data"]["materials"]) == 7
    assert result["data"]["cartons"][0]["cost_usd"] is None
    first, offset = result["data"]["cartons"], result["data"]["next_offset"]
    rest = invoke(gw, "packaging_resources", {"expected_revision": 0, "resource": "catalog", "offset": offset})
    assert rest["ok"], rest
    skus = [c["sku"] for c in first + rest["data"]["cartons"]]
    assert (len(first), offset, rest["data"]["next_offset"]) == (6, 6, None)
    assert skus == ["S-4080", "S-4103", "S-4120", "S-4187", "S-4235", "S-4415", "S-4196", "S-15039", "S-4219"]
    report = invoke(gw, "packaging_resources", {"expected_revision": 0, "resource": "report"})
    assert report["ok"], report
    assert report["data"]["report_url"].endswith("report.pdf?revision=0")
    assert snapshot(env) == before


def test_sources_paginated_and_density_estimate_not_saved(env):
    service, scope, context, _ = env
    metadata = {"name": "TEST STEP", "format": "step", "source_revision": "a"*64,
                "dimensions_m": [.1, .1, .1], "volume_m3": .0005,
                "physical_evidence": {"volume_basis": "closed_solid_brep"}}
    source = service.store_source(scope, metadata, b"TEST")
    service.store_source("other-scope", {**metadata, "source_revision": "b"*64}, b"PRIVATE")
    gw = gateway(env)
    before = snapshot(env)
    listed = invoke(gw, "packaging_resources", {"expected_revision": 0, "resource": "sources"})
    assert listed["ok"], listed
    assert [s["id"] for s in listed["data"]["sources"]] == [source["id"]]
    mass = invoke(gw, "estimate_packaging_mass", {"expected_revision": 0, "source_id": source["id"],
        "source_revision": "a"*64, "material": {"name": "PMMA", "density_kg_m3": 1190., "evidence": "TEST source"},
        "exclusions": "Adhesive excluded"})
    assert mass["ok"], mass
    assert mass["data"]["product"]["mass_kg"] == .595
    assert mass["data"]["saved"] is False
    assert snapshot(env) == before
    denied = invoke(gw, "estimate_packaging_mass", {"expected_revision": 0, "source_id": "src_"+"b"*32,
        "source_revision": "b"*64, "material": {"name": "PMMA", "density_kg_m3": 1190., "evidence": "TEST"}})
    assert_error(denied, "source_not_found")


def test_saved_alternative_read_does_not_apply_and_revocation_blocks_resources(env):
    service, scope, context, _ = env
    doc_id = context[0].document_id
    service.save_alternative(scope, doc_id, AlternativeSave(expected_revision=0, request_id="save", name="TEST alternative"))
    gw = gateway(env)
    before = snapshot(env)
    alternatives = invoke(gw, "packaging_resources", {"expected_revision": 0, "resource": "alternatives"})
    assert alternatives["ok"], alternatives
    assert len(alternatives["data"]["alternatives"]) == 1
    assert snapshot(env) == before
    context[0] = replace(context[0], selection_id="changed")
    assert_error(invoke(gw, "packaging_resources", {"expected_revision": 0, "resource": "catalog"}), "codex_packaging_context_changed")
