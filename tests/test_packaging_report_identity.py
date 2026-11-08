"""Report: check status, protection requirements, proposed packing order, packed-assembly labelling, quote identity
and research evidence (P5 item 6). Offline: synthetic TEST designs, quote snapshots and evidence records; no provider,
carrier or web request. Nothing here is a live price or an engineering approval."""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from pathlib import Path
import socket

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pdfplumber
import pytest

from ai_inspector.codex_runtime.packaging_tools import packaging_scope
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.packaging_shipping.api import create_router
from ai_inspector.packaging_shipping.geometry import assess
from ai_inspector.packaging_shipping.models import Design
from ai_inspector.packaging_shipping.quoting import QuoteDesk
from ai_inspector.packaging_shipping.rating import EasyPostRating
from ai_inspector.packaging_shipping.report import check_rows, packing_order, render_report
from ai_inspector.packaging_shipping.service import PackagingService

PAD = {"material": "TEST foam", "density_kg_m3": 30.0, "material_evidence": "TEST supplier density"}


def design_data():
    return {
        "name": "TEST report identity", "quantity": 2,
        "product": {"name": "TEST block", "dimensions_m": [0.1, 0.08, 0.04], "mass_kg": 0.5,
                    "mass_basis": "user_measured", "mass_evidence": "TEST scale"},
        "constraints": {
            "clearance_m": 0.0, "gap_m": 0.0, "contents": "ordinary_nonhazardous",
            "cushion": {"floor_m": 0.02, "top_m": 0.0, "sides_m": 0.0, "evidence": "TEST drop-height guidance",
                        "material": {"name": "TEST PE foam", "density_kg_m3": 30.0, "evidence": "TEST foam datasheet"}},
            "package_allowance": {"allowance_kg": 0.05, "evidence": "TEST tape and labels"},
            "no_contact": [{"id": "nc_face", "name": "TEST optical face", "face": "x_max", "air_gap_m": 0.005,
                            "evidence": "TEST customer drawing"}],
        },
        "packages": [{
            "id": "box_0",
            "carton": {"name": "TEST carton", "inner_m": [0.17, 0.23, 0.12], "outer_m": [0.2032, 0.254, 0.1524],
                       "tare_kg": 0.1, "tare_evidence": "TEST scale", "max_payload_kg": 5},
            # Listed out of order on purpose; the report orders them.
            "placements": [{"id": "item_b", "position_m": [0.035, 0.02, 0.06]}, {"id": "item_a", "position_m": [0.035, 0.02, 0.02]}],
            "inserts": [{"id": "pad_top", "name": "TEST top pad", "dimensions_m": [0.17, 0.02, 0.12], "position_m": [0, 0.10, 0], **PAD},
                        {"id": "pad_floor", "name": "TEST floor pad", "dimensions_m": [0.17, 0.02, 0.12], "position_m": [0, 0, 0], **PAD}],
            "allowance_kg": 0.05, "allowance_evidence": "TEST tape",
        }],
    }


def document_for(data, revision=0):
    design = Design.model_validate(data)
    return {"id": "pkg_report_identity", "revision": revision, "updated_at": "2026-11-06T12:00:00+00:00",
            "design": design.model_dump(mode="json"), "assessment": assess(design)}


def snapshot(qid, fingerprint, marker, amount, *, stale=None, revision=0, scenario="5" * 64, account="acct_TEST_A",
             design_hash="d" * 64):
    return {"id": qid, "revision": revision, "provider": "EasyPost", "adapter": "TEST", "quoted_at": "2026-11-06T10:00:00+00:00",
            "design_hash": design_hash, "scenario_hash": scenario, "account_ref": account, "mode": "test",
            "fingerprint": fingerprint, "notice": f"{marker}; estimates only. No postage was purchased.",
            "fees_notice": "TEST fees notice.",
            "results": [{"destination": {"city": "Dallas", "state": "TX", "zip": "75201", "residential": True},
                         "totals": [{"mode": "test", "carrier": "TEST Carrier", "service": "TEST Ground", "account_id": "ca_TEST_A",
                                     "amount": amount, "currency": "USD",
                                     "basis": "Sum of separate parcel estimates; not a consolidated shipment quote"}]}],
            "stale": stale is not None, **({"stale_reason": stale} if stale else {})}


def record(rid, subject, status, **changes):
    return {"id": rid, "kind": "material_density", "subject": subject, "claim": "Density (ASTM D792): 1.19 g/cm3",
            "claim_basis": "source_quote", "value": 1.19, "unit": "g/cm3", "sku_or_grade": None,
            "effective_date": "2025-01-15", "confidence": "high", "review_status": status,
            "source": {"url": "https://plastics.example.com/ds", "title": "TEST datasheet", "page_age": None,
                       "retrieved_at": "2026-11-06T15:00:00+00:00"}, **changes}


def text_of(payload):
    assert payload.startswith(b"%PDF-")
    with pdfplumber.open(BytesIO(payload)) as reader:
        return " ".join("\n".join(page.extract_text() or "" for page in reader.pages).split())


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A packaging report must not contact a provider")
    monkeypatch.setattr(socket, "create_connection", forbidden)


def test_check_status_separates_geometric_passes_from_review_and_unevaluated_checks():
    document = document_for(design_data())
    rows = {check: status for check, status, _ in check_rows(document["design"], document["assessment"])}
    # Support, movement (no restraint requirement recorded) and packing access need review; transport is not evaluated.
    assert list(rows.values()) == ["passed"] * 6 + ["needs_review", "needs_review", "needs_review", "not_evaluated"]
    overlapping = design_data()
    overlapping["packages"][0]["placements"][0]["position_m"] = [0.035, 0.02, 0.04]
    overlapping["constraints"].pop("cushion")
    overlapping["constraints"]["no_contact"] = []
    overlap = document_for(overlapping)
    statuses = [s for _, s, _ in check_rows(overlap["design"], overlap["assessment"])]
    assert statuses[1] == "failed" and statuses[2] == "not_required" and statuses[3] == "not_required"
    turned = design_data()
    turned["packages"][0]["placements"][1]["orientation"] = 1
    turned = document_for(turned)
    assert check_rows(turned["design"], turned["assessment"])[5][1:] == ("failed", "Allowed orthogonal orientations: 0")
    empty = document_for({})
    assert [s for _, s, _ in check_rows(empty["design"], empty["assessment"])][:2] == ["not_evaluated", "not_evaluated"]


def test_report_shows_protection_rules_packed_labelling_and_a_derived_packing_order():
    document = document_for(design_data())
    assert [item[3]["id"] for item in packing_order(document["design"]["packages"][0])] == ["pad_floor", "item_a", "item_b", "pad_top"]
    text = text_of(render_report(document))
    for expected in (
            "Packed assembly: all dimensions, positions, projections and masses in this report describe the packed carton contents.",
            "rate requests use each packed carton's outer dimensions and gross mass",
            "Check status", "PASSED", "(geometric)", "NEEDS REVIEW", "NOT EVALUATED", "It is not a protective-performance result.",
            "Contents declaration: Ordinary, non-hazardous (declared by the user)",
            "Allowed product orientations (orthogonal index; 0 is the product as modelled): 0",
            "Minimum clearance from product envelopes to carton walls: 0.00 mm | Minimum gap between product envelopes: 0.00 mm",
            "floor 20.00 mm | top 0.00 mm | sides 0.00 mm", "TEST PE foam, 30 kg/m3 (density source: TEST foam datasheet)",
            "Cushion requirement source: TEST drop-height guidance",
            "Package box_0: least insert material found: floor 20.00 mm | top not required | sides not required",
            "Package allowance rule: 0.05 kg per package", "Source: TEST tape and labels",
            "No-contact region nc_face: TEST optical face | Product face x_max (whole face) | Air gap 5.00 mm | Source: TEST customer drawing",
            "region nc_face: 0 of 2 products have material", "Cushioning, drop, vibration and compression performance are not evaluated.",
            "Proposed packing order (derived from saved positions; not verified)",
            "Whether each item can be inserted and removed in this order is not evaluated and needs review."):
        assert expected in text, expected
    steps = ["1. Insert pad_floor (TEST floor pad): bottom face at Y 0.00 mm.", "2. Product item_a: bottom face at Y 20.00 mm.",
             "3. Product item_b: bottom face at Y 20.00 mm.", "4. Insert pad_top (TEST top pad): bottom face at Y 100.00 mm.",
             "5. Close the carton."]
    positions = [text.index(step) for step in steps]
    assert positions == sorted(positions)
    bare = text_of(render_report(document_for({**design_data(), "constraints": {"contents": "unconfirmed"}})))
    for expected in ("No minimum-cushion requirement is recorded.", "No package allowance rule is recorded",
                     "No no-contact regions are recorded.", "Contents declaration: Not confirmed"):
        assert expected in bare


def test_every_current_quote_identity_is_printed_and_stale_amounts_are_withheld():
    document = document_for(design_data())
    quotes = [snapshot("quote_new", "1" * 64, "NEWEST_F1", "11.11"),
              snapshot("quote_old", "1" * 64, "OLDER_F1", "22.22"),
              snapshot("quote_other", "2" * 64, "SECOND_SCENARIO", "33.33", scenario="6" * 64),
              snapshot("quote_stale", "3" * 64, "ACCOUNT_STALE", "44.44", stale="account_changed", account="acct_TEST_OLD"),
              snapshot("quote_prev", "4" * 64, "PREVIOUS_REVISION", "55.55", revision=-1)]
    before = deepcopy(quotes)
    text = text_of(render_report(document, quotes))
    assert quotes == before
    for expected in ("NEWEST_F1", "11.11", "SECOND_SCENARIO", "33.33", "Quote quote_new | Mode: test", "Design hash: " + "d" * 64,
                     "Scenario hash: " + "5" * 64, "Scenario hash: " + "6" * 64, "Account reference: acct_TEST_A",
                     "Fingerprint: " + "1" * 64, "Destination: Dallas, TX 75201 (residential)",
                     "It is not a consolidated or all-in price", "TEST fees notice.", "ACCOUNT_STALE",
                     "Account reference: acct_TEST_OLD", "STALE (carrier account changed): amounts are not shown.",
                     "1 older quote(s) at this revision with the same identity"):
        assert expected in text, expected
    for excluded in ("OLDER_F1", "22.22", "44.44", "PREVIOUS_REVISION", "55.55"):
        assert excluded not in text, excluded


def test_report_lists_accepted_and_unreviewed_evidence_but_not_rejected_records():
    evidence = [record("ev_1", "Cast acrylic sheet", "accepted"),
                record("ev_2", "RSC carton 12 x 10 x 8 in", "unreviewed", kind="carton_sku", claim_basis="provider_summary",
                       claim="lists a 12 x 10 x 8 in carton rated 32 ECT as SKU S-4127", value=12.0, unit="in",
                       sku_or_grade="S-4127", effective_date=None, confidence="medium"),
                record("ev_3", "REJECTED_SUBJECT", "rejected")]
    text = text_of(render_report(document_for(design_data()), (), evidence))
    for expected in ("Public-source evidence", "Material density: Cast acrylic sheet | ACCEPTED by the user | Sage confidence: high",
                     "Claim (quoted from the page): Density (ASTM D792): 1.19 g/cm3", "Value: 1.19 g/cm3 | Effective: 2025-01-15",
                     "Source: TEST datasheet | https://plastics.example.com/ds | retrieved 2026-11-06T15:00:00+00:00",
                     "Carton SKU: RSC carton 12 x 10 x 8 in | UNREVIEWED | Sage confidence: medium",
                     "Claim (provider summary of the page, not a quotation)", "Value: 12 in | SKU/grade: S-4127",
                     "1 rejected record(s) are not shown.", "It does not edit the design, pass validation or certify packaging."):
        assert expected in text, expected
    assert "REJECTED_SUBJECT" not in text
    assert "No research evidence is recorded for this document." in text_of(render_report(document_for(design_data())))


def test_report_route_marks_quotes_stale_by_the_current_account_and_includes_evidence(tmp_path):
    service = PackagingService(tmp_path / "packaging")
    principal = FacilityPrincipal("engineer", "tenant-a", ("site-a",), ("editor",))
    scope = packaging_scope(principal)
    saved = service.create(scope, Design.model_validate(design_data()))
    desk = QuoteDesk(service, rating=EasyPostRating(key="EZTK_TEST_REPORT_ONLY"))
    current, design_hash = desk.provider.account_ref, saved["assessment"]["design_hash"]
    service.save_quotes(scope, saved["id"], 0, snapshot(None, "7" * 64, "OTHER_ACCOUNT", "66.66", account="acct_TEST_OLD",
                                                        design_hash=design_hash))
    service.save_quotes(scope, saved["id"], 0, snapshot(None, "8" * 64, "THIS_ACCOUNT", "77.77", account=current,
                                                        design_hash=design_hash))
    service.add_evidence(scope, saved["id"], [{key: value for key, value in record("unused", "Cast acrylic sheet", "unreviewed").items()
                                               if key not in {"id", "review_status"}}])
    app = FastAPI()
    app.include_router(create_router(service, principal_resolver=lambda r: principal, static_root=Path("static"), quotes=desk))
    with TestClient(app) as client:
        response = client.get(f"/api/packaging/documents/{saved['id']}/report.pdf", params={"revision": 0})
    assert response.status_code == 200
    text = text_of(response.content)
    assert "THIS_ACCOUNT" in text and "77.77" in text and "Account reference: " + current in text
    assert "OTHER_ACCOUNT" in text and "STALE (carrier account changed): amounts are not shown." in text and "66.66" not in text
    assert "Material density: Cast acrylic sheet | UNREVIEWED" in text
