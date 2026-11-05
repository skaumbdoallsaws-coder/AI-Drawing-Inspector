"""Isolated packaging contract tests; no application data or carrier access."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
from threading import Barrier

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
import trimesh

from ai_inspector.facility_layout import authorization
from ai_inspector.packaging_shipping.geometry import assess, oriented
from ai_inspector.packaging_shipping.models import (
    Address, Carton, Constraints, Design, Edit, Insert, Package, PackingRequest,
    Placement, Product, QuoteRequest, RevisionCommand,
)
from ai_inspector.packaging_shipping.packing import propose
from ai_inspector.packaging_shipping.rating import EasyPostRating
from ai_inspector.packaging_shipping.service import PackagingError, PackagingService
from ai_inspector.packaging_shipping.sources import MAX_BYTES, import_glb, import_glb_isolated
from tools.run_packaging_pilot import create_app


def design_data():
    return {
        "name": "TEST packaging",
        "product": {"name": "TEST product", "dimensions_m": [0.1, 0.06, 0.04],
                    "mass_kg": 2, "mass_basis": "user_measured", "mass_evidence": "TEST scale"},
        "quantity": 1,
        "constraints": {"clearance_m": 0.02, "gap_m": 0.01,
                        "allowed_orientations": [0], "contents": "ordinary_nonhazardous"},
        "packages": [{
            "id": "box_1",
            "carton": {"name": "TEST carton", "inner_m": [0.3, 0.2, 0.15],
                       "outer_m": [0.32, 0.22, 0.17], "tare_kg": 0.2,
                       "tare_evidence": "TEST scale", "cost_usd": 1.5, "max_payload_kg": 10},
            "placements": [{"id": "item_1", "position_m": [0.02, 0.02, 0.02]}],
            "inserts": [{"id": "pad_1", "name": "TEST pad", "dimensions_m": [0.1, 0.1, 0.01],
                         "position_m": [0.02, 0.02, 0], "density_kg_m3": 100,
                         "material_evidence": "TEST material density", "cost_usd": 0.25}],
            "allowance_kg": 0.05, "allowance_evidence": "TEST tape",
        }],
    }


def address_data():
    return {"name": "TEST ONLY", "street1": "1 Test Street", "city": "Chicago",
            "state": "IL", "zip": "60601", "residential": False}


def codes(result):
    return {finding["code"] for finding in result["findings"]}


def expect_error(code, operation, status=None):
    with pytest.raises(PackagingError) as caught:
        operation()
    assert caught.value.code == code
    if status is not None:
        assert caught.value.status == status


def json_glb(document):
    chunk = json.dumps(document).encode("utf-8")
    chunk += b" " * (-len(chunk) % 4)
    return struct.pack("<4sIIII", b"glTF", 2, 20 + len(chunk), len(chunk), 0x4E4F534A) + chunk


@pytest.fixture
def design():
    return Design.model_validate(design_data())


@pytest.fixture
def service(tmp_path):
    return PackagingService(tmp_path / "isolated-service")


@pytest.fixture
def box_glb():
    mesh = trimesh.creation.box(extents=[0.1, 0.06, 0.04])
    mesh.apply_translation([0.3, -0.4, 0.5])
    return mesh.export(file_type="glb")


def test_all_request_and_document_models_are_closed(design):
    box = design.packages[0]
    address = Address.model_validate(address_data())
    examples = [design, design.product, design.constraints, box, box.carton,
                box.placements[0], box.inserts[0], address,
                Edit(expected_revision=0, request_id="edit", design=design),
                RevisionCommand(expected_revision=0, request_id="undo"),
                PackingRequest(expected_revision=0, cartons=[box.carton]),
                QuoteRequest(expected_revision=0, origin=address, destinations=[address])]
    for model in examples:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            type(model).model_validate({**model.model_dump(), "injected_scope": "other-tenant"})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), True, False, "0.1"])
def test_all_physical_and_cost_fields_reject_nonfinite_and_coerced_numbers(design, bad):
    box = design.packages[0]
    fields = [(design.product, ("dimensions_m", "mass_kg")),
              (box.carton, ("inner_m", "outer_m", "tare_kg", "cost_usd", "max_payload_kg")),
              (box.placements[0], ("position_m",)),
              (box.inserts[0], ("dimensions_m", "position_m", "density_kg_m3", "cost_usd")),
              (box, ("allowance_kg",)), (design.constraints, ("clearance_m", "gap_m"))]
    for model, names in fields:
        for name in names:
            data = model.model_dump()
            data[name] = [bad, 0.1, 0.1] if isinstance(data[name], tuple) else bad
            with pytest.raises(ValidationError) as caught:
                type(model).model_validate(data)
            if isinstance(bad, (bool, str)):
                assert any(error["type"] == "float_type" for error in caught.value.errors())


def test_residential_requires_a_real_boolean_in_python_and_json():
    for value in (0, 1, "true", "false", None):
        data = {**address_data(), "residential": value}
        with pytest.raises(ValidationError):
            Address.model_validate(data)
        with pytest.raises(ValidationError):
            Address.model_validate_json(json.dumps(data))
    for value in (True, False):
        assert Address.model_validate({**address_data(), "residential": value}).residential is value


def test_bounded_dimensions_strict_counts_and_assignment(design):
    for dimensions in ([0, 0.1, 0.1], [-1, 0.1, 0.1], [5.001, 0.1, 0.1], [0.1, 0.1]):
        with pytest.raises(ValidationError):
            Product(name="TEST", dimensions_m=dimensions)
    for quantity in (0, 49, True, "2", 2.0):
        with pytest.raises(ValidationError):
            Design(quantity=quantity)
    for orientation in (-1, 6, True, "1", 1.0):
        with pytest.raises(ValidationError):
            Placement(id="item", position_m=(0, 0, 0), orientation=orientation)
    for orientations in ([], [6], [0] * 7):
        with pytest.raises(ValidationError):
            Constraints(allowed_orientations=orientations)
    with pytest.raises(ValidationError):
        design.quantity = 49
    with pytest.raises(ValidationError):
        Edit(expected_revision=True, request_id="edit", design=design)


def test_physical_scalar_limits_and_request_collection_bounds(design):
    box = design.packages[0]
    fields = [(box.carton, "tare_kg", 100), (box.carton, "cost_usd", 10000),
              (box.carton, "max_payload_kg", 1000), (box, "allowance_kg", 20),
              (box.inserts[0], "density_kg_m3", 25000), (box.inserts[0], "cost_usd", 10000),
              (design.constraints, "gap_m", 0.2), (design.constraints, "clearance_m", 0.2)]
    for model, field, maximum in fields:
        for value in (-0.001, maximum + 0.001):
            with pytest.raises(ValidationError):
                type(model).model_validate({**model.model_dump(), field: value})
    for position in ((-0.001, 0, 0), (10001, 0, 0)):
        with pytest.raises(ValidationError):
            Placement(id="item", position_m=position)
    for count in (0, 7):
        with pytest.raises(ValidationError):
            PackingRequest(expected_revision=0, cartons=[box.carton] * count)
        with pytest.raises(ValidationError):
            PackingRequest(expected_revision=0, cartons=[box.carton], max_packages=count)
    address = Address.model_validate(address_data())
    for count in (0, 4):
        with pytest.raises(ValidationError):
            QuoteRequest(expected_revision=0, origin=address, destinations=[address] * count)
    for request_id in ("", "../another-document", "x" * 81):
        with pytest.raises(ValidationError):
            RevisionCommand(expected_revision=0, request_id=request_id)


@pytest.mark.parametrize("mass,basis,evidence", [
    (1, "unknown", "scale"), (None, "user_measured", "scale"),
    (1, "estimate", "  "), (0, "user_measured", "scale"),
    (-1, "user_measured", "scale"), (1001, "cad", "CAD record"),
])
def test_product_mass_requires_bounded_value_and_provenance(mass, basis, evidence):
    with pytest.raises(ValidationError):
        Product(name="TEST", dimensions_m=(0.1, 0.1, 0.1), mass_kg=mass,
                mass_basis=basis, mass_evidence=evidence)


def test_carton_external_dimensions_and_zero_mass_provenance(design):
    box = design.packages[0]
    for axis in range(3):
        data = box.carton.model_dump()
        data["outer_m"] = list(data["outer_m"])
        data["outer_m"][axis] = data["inner_m"][axis]
        with pytest.raises(ValidationError):
            Carton.model_validate(data)
    for model, mass_field, evidence_field in (
        (box.carton, "tare_kg", "tare_evidence"), (box, "allowance_kg", "allowance_evidence")
    ):
        data = {**model.model_dump(), mass_field: 0, evidence_field: " \t"}
        with pytest.raises(ValidationError):
            type(model).model_validate(data)
        data[evidence_field] = "TEST zero confirmed"
        assert getattr(type(model).model_validate(data), mass_field) == 0


def test_insert_material_evidence_cannot_be_whitespace(design):
    data = {**design.packages[0].inserts[0].model_dump(), "material_evidence": " \t\n"}
    with pytest.raises(ValidationError):
        Insert.model_validate(data)


def test_component_and_package_ids_are_unique(design):
    original = design.model_dump()
    duplicate_package = deepcopy(original)
    duplicate_package["packages"].append(deepcopy(original["packages"][0]))
    duplicate_instance = deepcopy(duplicate_package)
    duplicate_instance["packages"][1]["id"] = "box_2"
    duplicate_component = deepcopy(original)
    duplicate_component["packages"][0]["inserts"][0]["id"] = "item_1"
    for data in (duplicate_package, duplicate_instance, duplicate_component):
        with pytest.raises(ValidationError, match="unique"):
            Design.model_validate(data)


def test_six_orientation_orders_match_py3dbp():
    from py3dbp import Item
    expected = [(1, 2, 3), (2, 1, 3), (2, 3, 1), (3, 2, 1), (3, 1, 2), (1, 3, 2)]
    item = Item("TEST", 1, 2, 3, 1)
    for rotation, dimensions in enumerate(expected):
        item.rotation_type = rotation
        assert oriented((1, 2, 3), rotation) == dimensions
        assert tuple(item.get_dimension()) == dimensions


def test_mass_budget_separates_contents_tare_and_external_dimensions(design):
    result = assess(design)
    assert result["rate_ready"] is True
    assert result["status"] == "needs_review"
    assert result["validation_level"] == "conservative_bounding_envelopes"
    assert codes(result) == {"protection_not_evaluated"}
    mass = result["packages"][0]
    assert mass["product_kg"] == 2
    assert mass["insert_kg"] == pytest.approx(0.01)
    assert mass["gross_kg"] == pytest.approx(2.26)
    assert result["total_gross_kg"] == pytest.approx(2.26)
    assert mass["outer_m"] == [0.32, 0.22, 0.17]
    assert mass["materials_cost_usd"] == 1.75
    design.packages[0].carton.max_payload_kg = 2.06
    assert "payload_exceeded" not in codes(assess(design))
    design.packages[0].carton.max_payload_kg = 2.059
    assert "payload_exceeded" in codes(assess(design))
    design.packages[0].carton.cost_usd = None
    assert assess(design)["packages"][0]["materials_cost_usd"] is None


def test_unknown_inputs_never_become_zero_or_rate_ready():
    cases = []
    for part, field, code in (
        ("product", "mass_kg", "mass_unknown"), ("carton", "tare_kg", "carton_mass_unknown"),
        ("package", "allowance_kg", "allowance_unknown")
    ):
        data = design_data()
        target = data["product"] if part == "product" else data["packages"][0]
        if part == "carton":
            target = target["carton"]
        target[field] = None
        if part == "product":
            target["mass_basis"] = "unknown"
        cases.append((data, code))
    for data, code in cases:
        result = assess(Design.model_validate(data))
        assert not result["rate_ready"]
        assert code in codes(result)
        assert result["packages"][0]["gross_kg"] is None
        assert result["total_gross_kg"] is None
    assert {"product_required", "packages_required", "quantity_mismatch", "contents_unconfirmed"} <= codes(assess(Design()))


def test_estimates_and_load_limit_are_explicit_warnings(design):
    design.product.mass_basis = "estimate"
    design.packages[0].carton.max_payload_kg = None
    result = assess(design)
    assert result["rate_ready"]
    assert {"estimated_mass", "load_limit_unknown"} <= codes(result)
    assert all(f["severity"] == "warning" for f in result["findings"])
    design.constraints.contents = "special_handling"
    assert not assess(design)["rate_ready"]


@pytest.mark.parametrize("separation,gap,invalid", [
    (0.01, 0.01, False), (0.009995, 0.01, True), (0, 0, False), (-0.000005, 0, True),
])
def test_conservative_product_envelope_separation(design, separation, gap, invalid):
    design.quantity = 2
    design.constraints.gap_m = gap
    design.packages[0].placements.append(Placement(id="item_2", position_m=(0.12 + separation, 0.02, 0.02)))
    result = assess(design)
    assert ("envelope_overlap" in codes(result)) is invalid
    assert result["rate_ready"] is (not invalid)


def test_inner_carton_clearance_orientation_and_insert_intersection(design):
    item = design.packages[0].placements[0]
    item.position_m = (0.02 - 0.000005, 0.02, 0.02)
    assert "outside_usable_carton" in codes(assess(design))
    item.position_m = (0.19, 0.02, 0.02)
    assert item.position_m[0] + 0.1 < design.packages[0].carton.outer_m[0]
    assert "outside_usable_carton" in codes(assess(design))
    item.position_m = (0.02, 0.02, 0.02)
    item.orientation = 1
    assert "orientation_forbidden" in codes(assess(design))
    item.orientation = 0
    pad = design.packages[0].inserts[0]
    pad.position_m = (0.02, 0.02, 0.01)
    assert "insert_overlap" not in codes(assess(design))
    pad.position_m = (0.02, 0.02, 0.010005)
    assert "insert_overlap" in codes(assess(design))
    pad.position_m = (0.201, 0.02, 0)
    assert "insert_outside_carton" in codes(assess(design))


def test_quantities_count_instances_not_packages(design):
    design.quantity = 2
    assert "quantity_mismatch" in codes(assess(design))
    second = design.packages[0].model_copy(deep=True)
    second.id = "box_2"
    second.placements[0].id = "item_2"
    design.packages.append(second)
    assert assess(design)["placed_quantity"] == 2
    assert assess(design)["total_gross_kg"] == pytest.approx(4.52)
    assert "quantity_mismatch" not in codes(assess(design))
    design.quantity = 1
    assert "quantity_mismatch" in codes(assess(design))
    second.placements.clear()
    assert "empty_package" in codes(assess(design))


def test_py3dbp_respects_orientation_quantity_capacity_and_candidate_readiness():
    product = Product(name="TEST", dimensions_m=(0.12, 0.06, 0.04), mass_kg=2,
                      mass_basis="user_measured", mass_evidence="TEST scale")
    carton = Carton(name="TEST", inner_m=(0.1, 0.16, 0.08), outer_m=(0.11, 0.17, 0.09),
                    tare_kg=0.1, tare_evidence="TEST scale", max_payload_kg=5)
    design = Design(product=product, quantity=2,
                    constraints=Constraints(clearance_m=0.01, gap_m=0, contents="ordinary_nonhazardous"))
    assert propose(design, [carton], max_packages=2)["candidates"] == []
    design.constraints.allowed_orientations = [1]
    assert propose(design, [carton], max_packages=1)["candidates"] == []
    before = design.model_dump()
    result = propose(design, [carton], max_packages=2)
    assert result["algorithm"] == "py3dbp-1.1.2"
    assert not result["truncated"]
    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    packed = Design.model_validate(candidate["design"])
    assert candidate["package_count"] == 2
    assert all(p.orientation == 1 for box in packed.packages for p in box.placements)
    assert candidate["assessment"] == assess(packed)
    assert codes(candidate["assessment"]) == {"allowance_unknown", "protection_not_evaluated"}
    assert not candidate["assessment"]["rate_ready"]
    assert candidate["shipping_volume_m3"] == pytest.approx(2 * 0.11 * 0.17 * 0.09)
    assert design.model_dump() == before
    assert propose(design, [carton], max_packages=2)["candidates"][0]["candidate_id"] == candidate["candidate_id"]
    carton.max_payload_kg = 1.9
    assert propose(design, [carton], max_packages=2)["candidates"] == []
    expect_error("product_required", lambda: propose(Design(), [carton]), 400)


def test_py3dbp_unknown_mass_and_deadline_are_not_certification(design, monkeypatch):
    from ai_inspector.packaging_shipping import packing
    data = design.model_dump()
    data["product"].update(mass_kg=None, mass_basis="unknown", mass_evidence="")
    unknown = Design.model_validate(data)
    candidates = propose(unknown, [unknown.packages[0].carton])["candidates"]
    assert candidates
    assert all(not c["assessment"]["rate_ready"] and "mass_unknown" in codes(c["assessment"]) for c in candidates)
    ticks = iter((0, 11, 11))
    monkeypatch.setattr(packing.time, "monotonic", lambda: next(ticks))
    result = propose(design, [design.packages[0].carton], deadline_seconds=10)
    assert result["truncated"] and result["candidates"] == []


def test_future_store_version_is_refused_without_modifying_the_database(tmp_path):
    root = tmp_path / "future-store"
    root.mkdir()
    database = root / "packaging.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE future_data (id INTEGER PRIMARY KEY, evidence TEXT)")
        db.execute("INSERT INTO future_data VALUES (1, 'TEST future data must survive')")
        db.execute("PRAGMA user_version=2")
    before = database.read_bytes()

    expect_error("schema_unsupported", lambda: PackagingService(root), 409)

    assert database.read_bytes() == before
    with sqlite3.connect(database) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("future_data",)]
        assert db.execute("SELECT evidence FROM future_data WHERE id=1").fetchone()[0] == "TEST future data must survive"
    independent = PackagingService(tmp_path / "current-store")
    assert independent.create("TEST scope")["schema_version"] == 1
    assert database.read_bytes() == before


@pytest.mark.parametrize("stored_version", [0, 1])
def test_supported_store_versions_preserve_records_and_document_metadata(service, design, box_glb, stored_version):
    original = service.create("scope", design)
    command = Edit(expected_revision=0, request_id="version_edit", design=Design(name="TEST edited design"))
    edited = service.change("scope", original["id"], command)
    metadata, normalized = import_glb(box_glb, "TEST versioned source", 1.0)
    source = service.store_source("scope", metadata, normalized)
    service.save_quotes("scope", original["id"], 1, {"provider": "TEST", "results": []})
    before = service.get("scope", original["id"])
    quote_history = service.quote_history("scope", original["id"])
    with service.db() as db:
        db.execute(f"PRAGMA user_version={stored_version}")

    reopened = PackagingService(service.root)
    assert reopened.get("scope", original["id"]) == before
    assert reopened.source("scope", source["id"]) == (source, normalized)
    assert reopened.quote_history("scope", original["id"]) == quote_history
    replayed = reopened.change("scope", original["id"], command)
    assert replayed == edited
    undone = reopened.change("scope", original["id"], RevisionCommand(expected_revision=1, request_id="version_undo"), "undo")
    redone = reopened.change("scope", original["id"], RevisionCommand(expected_revision=2, request_id="version_redo"), "redo")
    assert undone["design"] == original["design"]
    assert redone["design"] == edited["design"]
    for result in (original, edited, before, replayed, undone, redone):
        assert type(result["schema_version"]) is int and result["schema_version"] == 1
        assert result["units"] == {"length": "m", "mass": "kg", "up": "Y"}
    with reopened.db() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_report_text_preserves_density_evidence_accounts_and_quote_revision(service, design):
    import pdfplumber
    from ai_inspector.packaging_shipping.report import render_report

    design.packages[0].inserts[0].density_kg_m3 = 37.5
    design.packages[0].inserts[0].material_evidence = "TEST density cert & lot <A-17>"
    document = service.create("scope", design)
    quote = {
        "provider": "TEST EasyPost", "quoted_at": "2026-11-05T12:00:00+00:00",
        "notice": "TEST estimate only. No postage was purchased.",
        "results": [{"destination": {"city": "Chicago", "state": "IL", "zip": "60601"},
                     "totals": [{"carrier": "TEST Carrier", "service": "TEST Ground", "mode": "test",
                                 "account_id": account, "amount": amount, "currency": "USD",
                                 "basis": "TEST separate parcel estimates"}
                                for account, amount in (("ca_TEST_A", "7.10"), ("ca_TEST_B", "9.20"))]}],
    }
    service.save_quotes("scope", document["id"], 0, quote)

    def report_text(current):
        payload = render_report(current, service.quote_history("scope", current["id"]))
        assert payload.startswith(b"%PDF-")
        with pdfplumber.open(BytesIO(payload)) as reader:
            assert len(reader.pages) >= 1
            assert reader.metadata["Title"] == "InspectorPro Packaging Review"
            return " ".join("\n".join(page.extract_text() or "" for page in reader.pages).split())

    text = report_text(document)
    for expected in ("37.5 kg/m3", "Density source: TEST density cert & lot <A-17>",
                     "Account ca_TEST_A: 7.10 USD", "Account ca_TEST_B: 9.20 USD",
                     "TEST | TEST Carrier TEST Ground", "No postage was purchased."):
        assert expected in text
    assert "No quotes are saved for this revision" not in text

    updated = service.change("scope", document["id"], Edit(expected_revision=0, request_id="report_edit", design=design))
    stale_text = report_text(updated)
    assert "No quotes are saved for this revision. No shipping price has been inferred." in stale_text
    assert "Density source: TEST density cert & lot <A-17>" in stale_text
    assert "ca_TEST_A" not in stale_text and "ca_TEST_B" not in stale_text
    assert "7.10 USD" not in stale_text and "9.20 USD" not in stale_text


def test_sqlite_revision_idempotency_and_reuse(service, design):
    document = service.create("tenant-a", design)
    doc_id = document["id"]
    command = Edit(expected_revision=0, request_id="edit_1", design=Design(name="Second"))
    first = service.change("tenant-a", doc_id, command)
    assert first["revision"] == 1
    assert service.change("tenant-a", doc_id, command) == first
    expect_error("revision_conflict", lambda: service.get("tenant-a", doc_id, 0))
    stale = Edit(expected_revision=0, request_id="stale", design=Design(name="Stale"))
    expect_error("revision_conflict", lambda: service.change("tenant-a", doc_id, stale))
    for reused in (
        Edit(expected_revision=0, request_id="edit_1", design=Design(name="Changed body")),
        Edit(expected_revision=1, request_id="edit_1", design=command.design),
    ):
        expect_error("request_id_reused", lambda: service.change("tenant-a", doc_id, reused))
    expect_error("request_id_reused", lambda: service.change("tenant-a", doc_id, RevisionCommand(expected_revision=1, request_id="edit_1"), "undo"))
    service.change("tenant-a", doc_id, Edit(expected_revision=1, request_id="edit_2", design=Design(name="Third")))
    assert service.change("tenant-a", doc_id, command) == first
    assert PackagingService(service.root).get("tenant-a", doc_id)["revision"] == 2


def test_undo_redo_are_revisions_and_new_edit_discards_redo(service, design):
    original = service.create("scope", design)
    doc_id = original["id"]
    expect_error("nothing_to_undo", lambda: service.change("scope", doc_id, RevisionCommand(expected_revision=0, request_id="empty"), "undo"))
    service.change("scope", doc_id, Edit(expected_revision=0, request_id="edit", design=Design(name="Replacement")))
    undo = RevisionCommand(expected_revision=1, request_id="undo")
    restored = service.change("scope", doc_id, undo, "undo")
    assert restored["design"] == original["design"]
    assert restored["revision"] == 2 and restored["can_redo"] and not restored["can_undo"]
    assert service.change("scope", doc_id, undo, "undo") == restored
    redone = service.change("scope", doc_id, RevisionCommand(expected_revision=2, request_id="redo"), "redo")
    assert redone["revision"] == 3 and redone["design"]["name"] == "Replacement"
    assert redone["can_undo"] and not redone["can_redo"]
    service.change("scope", doc_id, RevisionCommand(expected_revision=3, request_id="undo_2"), "undo")
    branched = service.change("scope", doc_id, Edit(expected_revision=4, request_id="branch", design=Design(name="Branch")))
    assert branched["revision"] == 5 and not branched["can_redo"]
    expect_error("nothing_to_redo", lambda: service.change("scope", doc_id, RevisionCommand(expected_revision=5, request_id="no_redo"), "redo"))


@pytest.mark.parametrize("action", ["edit", "undo", "redo"])
def test_receipt_failure_rolls_back_document_history_and_revision(service, action):
    doc_id = service.create("scope", Design(name="Original"))["id"]
    service.change("scope", doc_id, Edit(expected_revision=0, request_id="setup", design=Design(name="Changed")))
    if action == "redo":
        service.change("scope", doc_id, RevisionCommand(expected_revision=1, request_id="setup_undo"), "undo")
    before = service.get("scope", doc_id)
    args = {"expected_revision": before["revision"], "request_id": "atomic"}
    command = Edit(**args, design=Design(name="Final")) if action == "edit" else RevisionCommand(**args)
    with service.db() as db:
        db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON receipts BEGIN SELECT RAISE(ABORT, 'TEST injected receipt failure'); END")
        history_before = tuple(db.execute("SELECT design,past,future FROM documents WHERE id=?", (doc_id,)).fetchone())
    with pytest.raises(sqlite3.IntegrityError, match="TEST injected"):
        service.change("scope", doc_id, command, action)
    assert service.get("scope", doc_id) == before
    with service.db() as db:
        assert tuple(db.execute("SELECT design,past,future FROM documents WHERE id=?", (doc_id,)).fetchone()) == history_before
        assert db.execute("SELECT COUNT(*) FROM receipts WHERE request_id='atomic'").fetchone()[0] == 0
        db.execute("DROP TRIGGER fail_receipt")
    assert service.change("scope", doc_id, command, action)["revision"] == before["revision"] + 1


def test_concurrent_writers_have_exactly_one_revision_winner(service):
    doc_id = service.create("scope")["id"]
    barrier = Barrier(2)

    def write(index):
        barrier.wait(timeout=5)
        try:
            return service.change("scope", doc_id, Edit(expected_revision=0, request_id=f"writer_{index}", design=Design(name=f"Writer {index}")))["revision"]
        except PackagingError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(write, [1, 2]))
    assert outcomes.count(1) == 1
    assert outcomes.count("revision_conflict") == 1
    assert service.get("scope", doc_id)["revision"] == 1


def test_sources_documents_and_quotes_are_scoped_and_revision_bound(service, design, box_glb):
    metadata, normalized = import_glb(box_glb, "TEST source", 1)
    source = service.store_source("a", metadata, normalized)
    assert service.source("a", source["id"]) == (source, normalized)
    expect_error("source_not_found", lambda: service.source("b", source["id"]), 404)
    product_data = {**design.product.model_dump(), "source_id": source["id"],
                    "source_revision": source["source_revision"], "dimensions_m": source["dimensions_m"]}
    design.product = Product.model_validate(product_data)
    document = service.create("a", design)
    doc_id = document["id"]
    assert service.list("b") == []
    expect_error("document_not_found", lambda: service.get("b", doc_id), 404)
    expect_error("source_not_found", lambda: service.create("b", design))
    expect_error("document_not_found", lambda: service.quote_history("b", doc_id), 404)
    expect_error("document_not_found", lambda: service.save_quotes("b", doc_id, 0, {"results": []}), 404)
    quote = service.save_quotes("a", doc_id, 0, {"provider": "TEST", "results": []})
    assert service.quote_history("a", doc_id)[0] == {**quote, "stale": False}
    service.change("a", doc_id, Edit(expected_revision=0, request_id="edit", design=Design(name="New revision")))
    expect_error("document_not_found", lambda: service.change("b", doc_id, Edit(expected_revision=0, request_id="edit", design=Design(name="New revision"))), 404)
    assert service.quote_history("a", doc_id)[0]["stale"] is True
    expect_error("revision_conflict", lambda: service.save_quotes("a", doc_id, 0, {"results": []}))
    assert len(service.quote_history("a", doc_id)) == 1
    for change, code in (({"dimensions_m": [0.01, 0.01, 0.01]}, "source_changed"),
                         ({"source_revision": "wrong"}, "source_changed"),
                         ({"mass_basis": "cad"}, "cad_mass_unavailable")):
        design.product = Product.model_validate({**product_data, **change})
        expect_error(code, lambda: service.change("a", doc_id, Edit(expected_revision=1, request_id="rejected", design=design)))
        assert service.get("a", doc_id)["revision"] == 1
    design.product = Product.model_validate({**product_data, "source_id": None, "mass_basis": "cad"})
    expect_error("cad_evidence_required", lambda: service.create("a", design))


@pytest.mark.parametrize("unit", [1.0, 0.001, 0.0254])
def test_real_trimesh_glb_is_scaled_centered_and_mass_unknown(unit):
    dimensions = np.array([0.12, 0.06, 0.04])
    mesh = trimesh.creation.box(extents=dimensions / unit)
    mesh.apply_translation(np.array([0.3, -0.4, 0.5]) / unit)
    payload = mesh.export(file_type="glb")
    metadata, normalized = import_glb(payload, "TEST source", unit)
    assert metadata["dimensions_m"] == pytest.approx(dimensions, abs=1e-7)
    assert metadata["meters_per_source_unit"] == unit
    assert metadata["mass_basis"] == "unknown" and metadata["mass_kg"] is None
    assert len(metadata["source_revision"]) == 64
    assert metadata == import_glb(payload, "TEST source", unit)[0]
    scene = trimesh.load_scene(BytesIO(normalized), file_type="glb", process=False)
    assert scene.bounds.mean(axis=0) == pytest.approx([0, 0, 0], abs=1e-7)
    assert scene.extents == pytest.approx(dimensions, abs=1e-7)


@pytest.mark.parametrize("section", ["buffers", "images"])
def test_glb_external_file_http_and_data_uris_rejected_before_loading(section, monkeypatch):
    calls = []
    monkeypatch.setattr(trimesh, "load_scene", lambda *a, **k: calls.append((a, k)))
    for uri in ("https://example.invalid/TEST.bin", "file:///TEST/private.bin", "data:application/octet-stream;base64,AAAA"):
        payload = json_glb({"asset": {"version": "2.0"}, section: [{"uri": uri}]})
        expect_error("source_invalid", lambda: import_glb(payload, "TEST", 1), 400)
    assert calls == []


def test_glb_oversize_invalid_headers_unsupported_features_and_units(box_glb, monkeypatch):
    expect_error("source_too_large", lambda: import_glb(b"x" * (MAX_BYTES + 1), "TEST", 1), 413)
    expect_error("source_too_large", lambda: import_glb(b"short", "TEST", 1), 413)
    for unit in (0, -1, 0.01, float("nan"), float("inf")):
        expect_error("units_required", lambda: import_glb(box_glb, "TEST", unit), 400)
    for payload in (b"x" * 24, b"BAD!" + box_glb[4:], box_glb[:-1],
                    box_glb[:4] + struct.pack("<I", 1) + box_glb[8:],
                    struct.pack("<4sIIII", b"glTF", 2, 24, 4, 0x4E4F534A) + b"oops"):
        expect_error("source_invalid", lambda: import_glb(payload, "TEST", 1), 400)
    calls = []
    monkeypatch.setattr(trimesh, "load_scene", lambda *a, **k: calls.append((a, k)))
    for forbidden in ({"nodes": [{}] * 2001}, {"accessors": [{"count": 3000001}]},
                      {"extensionsRequired": ["KHR_draco_mesh_compression"]},
                      {"animations": [{}]}, {"skins": [{}]}):
        payload = json_glb({"asset": {"version": "2.0"}, **forbidden})
        expect_error("source_invalid", lambda: import_glb(payload, "TEST", 1), 400)
    assert calls == []


@pytest.mark.parametrize("dimensions", [(5.01, 0.1, 0.1), (0, 0.1, 0.1)])
def test_real_glb_dimension_limits(dimensions):
    payload = trimesh.creation.box(extents=dimensions).export(file_type="glb")
    expect_error("source_invalid", lambda: import_glb(payload, "TEST", 1), 400)


def test_real_isolated_glb_worker_matches_pure_import_and_cleans_job(tmp_path, box_glb):
    expected, _ = import_glb(box_glb, "TEST worker", 1.0)
    metadata, normalized = asyncio.run(import_glb_isolated(box_glb, "TEST worker", 1.0, tmp_path))
    assert metadata == expected
    scene = trimesh.load_scene(BytesIO(normalized), file_type="glb", process=False)
    assert scene.extents == pytest.approx(expected["dimensions_m"], abs=1e-7)
    assert list((tmp_path / "import-jobs").iterdir()) == []


@pytest.mark.parametrize("termination", ["timeout", "cancel"])
def test_isolated_worker_is_killed_reaped_and_cleaned_on_termination(tmp_path, monkeypatch, termination):
    from ai_inspector.packaging_shipping import sources
    launched = []
    budgets = []
    original_wait_for = asyncio.wait_for
    monkeypatch.setenv("INSPECTORPRO_PACKAGING_EASYPOST_KEY", "TEST_ONLY_SECRET")
    monkeypatch.setenv("OPENAI_API_KEY", "TEST_ONLY_SECRET")

    class Worker:
        returncode = None
        killed = False
        waits = 0

        def __init__(self):
            self.entered = asyncio.Event()
            self.blocked = asyncio.Event()

        async def wait(self):
            self.waits += 1
            self.entered.set()
            if self.returncode is None:
                await self.blocked.wait()
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9

    async def scenario():
        worker = Worker()

        async def launch(*args, **kwargs):
            launched.append((args, kwargs))
            assert Path(args[-2]).is_relative_to(tmp_path)
            assert (Path(args[-2]) / "input.glb").read_bytes() == b"TEST worker input"
            assert "INSPECTORPRO_PACKAGING_EASYPOST_KEY" not in kwargs["env"]
            assert "OPENAI_API_KEY" not in kwargs["env"]
            assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
            if os.name == "nt":
                assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
            return worker

        async def immediate_timeout(awaitable, timeout):
            budgets.append(timeout)
            pending = asyncio.create_task(awaitable)
            await original_wait_for(worker.entered.wait(), timeout=2)
            return await original_wait_for(pending, timeout=0)

        monkeypatch.setattr(sources.asyncio, "create_subprocess_exec", launch)
        if termination == "timeout":
            monkeypatch.setattr(sources.asyncio, "wait_for", immediate_timeout)
            with pytest.raises(PackagingError) as caught:
                await import_glb_isolated(b"TEST worker input", "TEST", 1.0, tmp_path)
            assert (caught.value.code, caught.value.status) == ("source_timeout", 422)
            assert budgets == [25]
        else:
            pending = asyncio.create_task(import_glb_isolated(b"TEST worker input", "TEST", 1.0, tmp_path))
            try:
                await original_wait_for(worker.entered.wait(), timeout=2)
            finally:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
        assert worker.killed and worker.waits == 2

    asyncio.run(scenario())
    assert len(launched) == 1
    assert list((tmp_path / "import-jobs").iterdir()) == []


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    principal = {"value": authorization.FacilityPrincipal("tester", "tenant-a", ("test-site",), ("editor",))}
    monkeypatch.setattr(authorization, "local_facility_principal", lambda **kwargs: principal["value"])
    requests = []

    def carrier(request):
        assert request.method == "POST" and request.url == "https://api.easypost.com/v2/shipments"
        requests.append(request)
        return httpx.Response(200, json={"id": "shp_TEST", "mode": "test", "rates": []})

    rating = EasyPostRating(key="EZTK_TEST_ONLY_NOT_A_CREDENTIAL", transport=httpx.MockTransport(carrier))
    app = create_app(storage=tmp_path / "pilot-only", rating=rating)
    with TestClient(app, base_url="http://127.0.0.1:8179", headers={"x-inspectorpro-request": "packaging"}) as client:
        yield client, principal, requests


def test_pilot_routes_are_isolated_and_reject_unknown_request_fields(pilot):
    client, _, requests = pilot
    status = client.get("/api/packaging/status")
    assert status.status_code == 200 and status.headers["cache-control"] == "no-store"
    assert status.json()["rating"]["purchases_enabled"] is False
    api_paths = {route.path for route in client.app.routes if route.path.startswith("/api/")}
    assert api_paths and all(path.startswith("/api/packaging/") for path in api_paths)
    assert not any("buy" in path or "purchase" in path or "label" in path for path in api_paths)
    assert client.get("/api/facility-layout/layouts").status_code == 404
    for body in ({"tenant_id": "tenant-b"}, {"product": {"name": "TEST", "dimensions_m": [1, 1, 1], "scale": 0.1}}):
        assert client.post("/api/packaging/documents", json=body).status_code == 422
    assert requests == []


@pytest.mark.parametrize("headers", [
    {"host": "attacker.invalid"}, {"origin": "https://attacker.invalid"},
    {"origin": "null"}, {"x-inspectorpro-request": "wrong"},
])
def test_pilot_host_origin_and_custom_header_guards(pilot, headers):
    client, _, requests = pilot
    assert client.post("/api/packaging/documents", json={}, headers=headers).status_code == 403
    assert client.get("/api/packaging/documents").json() == {"documents": []}
    assert requests == []


def test_pilot_missing_header_same_origin_and_roles(pilot):
    client, principal, _ = pilot
    del client.headers["x-inspectorpro-request"]
    assert client.get("/api/packaging/status").status_code == 200
    assert client.post("/api/packaging/documents", json={}).status_code == 403
    client.headers["x-inspectorpro-request"] = "packaging"
    assert client.post("/api/packaging/documents", json={}, headers={"origin": "http://127.0.0.1:8179"}).status_code == 200
    principal["value"] = authorization.FacilityPrincipal("viewer", "tenant-a", ("test-site",), ("viewer",))
    assert client.get("/api/packaging/documents").status_code == 200
    assert client.post("/api/packaging/documents", json={}).status_code == 403
    assert client.post("/api/packaging/sources", content=b"TEST").status_code == 403
    principal["value"] = authorization.FacilityPrincipal("curator", "tenant-a", ("test-site",), ("catalog_curator",))
    assert client.get("/api/packaging/documents").status_code == 403


def test_pilot_document_source_quote_scope_and_stale_quotes(pilot, box_glb):
    client, principal, requests = pilot
    uploaded = client.post("/api/packaging/sources?meters_per_unit=1&name=TEST", content=box_glb)
    assert uploaded.status_code == 200
    source_id = uploaded.json()["id"]
    source_url = f"/api/packaging/sources/{source_id}.glb"
    assert client.get(source_url).headers["content-type"] == "model/gltf-binary"
    document = client.post("/api/packaging/documents", json=design_data()).json()
    assert document["schema_version"] == 1
    assert document["units"] == {"length": "m", "mass": "kg", "up": "Y"}
    url = f"/api/packaging/documents/{document['id']}"
    quote_body = {"expected_revision": 0, "origin": address_data(), "destinations": [address_data()]}
    quoted = client.post(url + "/quotes", json=quote_body)
    assert quoted.status_code == 200 and len(requests) == 1
    assert client.get(url + "/quotes").json()["quotes"][0]["stale"] is False
    edit = {"expected_revision": 0, "request_id": "edit", "design": design_data()}
    assert client.put(url, json=edit).json()["revision"] == 1
    assert client.post(url + "/quotes", json=quote_body).status_code == 409
    assert len(requests) == 1
    assert client.get(url + "/quotes").json()["quotes"][0]["stale"] is True
    assert client.get(url + "/report.pdf?revision=0").status_code == 409
    for tenant, sites in (("tenant-b", ("test-site",)), ("tenant-a", ("other-site",))):
        principal["value"] = authorization.FacilityPrincipal("other", tenant, sites, ("editor",))
        assert client.get("/api/packaging/documents?tenant_id=tenant-a").json() == {"documents": []}
        for path in (url, source_url, url + "/quotes"):
            assert client.get(path).status_code == 404
        assert client.post(url + "/quotes", json=quote_body).status_code == 404
    assert len(requests) == 1


def test_pilot_isolated_import_preserves_unsupported_units_error(pilot, box_glb):
    client, _, requests = pilot
    response = client.post("/api/packaging/sources?meters_per_unit=0.01", content=box_glb)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "units_required"
    assert requests == []
