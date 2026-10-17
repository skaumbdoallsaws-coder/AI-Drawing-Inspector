"""One-layout semantic authoring tests; not manufacturing qualification."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from tools import build_independent_factory_layer3 as layer3


def test_home_anchor_uses_exact_revision_without_persisting_coordinates():
    p = {"placementId": "pl-person", "assetDefinitionRevision": "a" * 64}
    home = layer3.anchor(p, "home")
    assert home["derivedPositionRef"] == {"sourceKind": "placement_transform", "sourceId": "pl-person", "sourceRevision": "a" * 64}
    assert home["localPosition"] is None
    assert home["reviewStatus"] == "pending"


@pytest.mark.parametrize("side", ["north", "south", "east", "west"])
def test_access_side_is_an_explicit_constraint(side):
    a = layer3.anchor({"placementId": "pl-table", "assetDefinitionRevision": "b" * 64}, side)
    assert a["derivedPositionRef"]["sourceKind"] == "placement_access"
    assert a["approachDirections"] == [side]
    assert a["positionAuthority"] == "derived"
    assert a["localPosition"] is None


@pytest.mark.parametrize("doc", [{"layoutId": "manual"}, {"layoutId": layer3.LAYOUT_ID, "extensions": {"facilityNavigation": {"existing": True}}}])
def test_wrong_sheet_or_existing_navigation_refused(doc):
    with pytest.raises(ValueError, match="unchanged Factory"):
        layer3.build_candidate(doc)


def test_real_kernel_keeps_geometry_and_marks_semantics_pending(monkeypatch):
    root = Path(__file__).parent / "fixtures/facility_layout/two_asset_cell.json"
    doc = json.loads(root.read_text())
    doc["layoutId"] = layer3.LAYOUT_ID
    doc.setdefault("extensions", {}).pop("facilityNavigation", None)
    actor, target = doc["placements"][:2]
    actor.setdefault("metadata", {})["instanceLabel"] = "A01 operator"
    before = deepcopy(doc)
    monkeypatch.setattr(layer3, "recipes", lambda _: [{"actor": actor, "target": target, "group": "assembly", "purpose": "test", "stops": [(target, "south")]}])
    candidate, ops, manifest = layer3.build_candidate(doc)
    assert doc == before
    for field in ("placements", "zones", "routes", "floorMarkings", "processBindings"):
        assert candidate.get(field) == doc.get(field)
    assert ops[0]["authoringSource"] == "sage_semantic"
    nav = candidate["extensions"]["facilityNavigation"]
    assert not nav["manualPathConstraints"] and not nav["handoffPrograms"]
    assert all(a["localPosition"] is None for a in nav["anchors"])
    assert nav["movementPrograms"][0]["reviewStatus"] == "pending"
    assert nav["movementPrograms"][0]["loopMode"] == "task_cycle"
    assert manifest[0]["workstationId"] == target["placementId"]
    assert candidate["extensions"]["facilityProcessPresentation"]["productionEligible"] is False


@pytest.mark.parametrize("report", [
    {"status": "failed", "accepted": 40, "programs": 40},
    {"status": "validated", "accepted": 39, "programs": 40},
    {"status": "validated", "accepted": 1, "programs": 1},
])
def test_publication_refuses_incomplete_evidence_before_opening_live_store(tmp_path, monkeypatch, report):
    (tmp_path / "report.json").write_text(json.dumps(report))
    monkeypatch.setattr(layer3, "LocalFacilityLayoutHost", lambda *_args, **_kwargs: pytest.fail("Must not open live store"))
    with pytest.raises(ValueError, match="complete validated"):
        layer3.publish_validated(tmp_path)


@pytest.fixture
def publication_case(tmp_path, monkeypatch):
    store, output = tmp_path / "live", tmp_path / "evidence"
    directory = store / "layouts/local/site-local/layouts"
    directory.mkdir(parents=True)
    output.mkdir()
    doc = json.loads((Path(__file__).parent / "fixtures/facility_layout/two_asset_cell.json").read_text())
    doc["layoutId"] = layer3.LAYOUT_ID
    doc.setdefault("extensions", {}).pop("facilityNavigation", None)
    actor, target = doc["placements"][:2]
    actor.setdefault("metadata", {})["instanceLabel"] = "A01 operator"
    monkeypatch.setattr(layer3, "recipes", lambda _: [{"actor": actor, "target": target,
        "group": "assembly", "purpose": "test", "stops": [(target, "south")]}])
    candidate, _, manifest = layer3.build_candidate(doc)
    original = json.dumps(doc).encode()
    live_file = directory / (layer3.LAYOUT_ID + ".json")
    live_file.write_bytes(original)
    (directory / (layer3.MANUAL_ID + ".json")).write_bytes(b"unchanged manual")
    monkeypatch.setattr(layer3, "STORE", store)
    monkeypatch.setattr(layer3, "SOURCE_HASH", hashlib.sha256(original).hexdigest())
    monkeypatch.setattr(layer3, "LocalFacilityLayoutHost", lambda *_args, **_kwargs: pytest.fail("Must not open live store"))
    (output / "report.json").write_text(json.dumps({"status": "validated", "accepted": 40, "programs": 40}))
    candidate_file = output / "validation-store/layouts/local/site-local/layouts" / live_file.name
    candidate_file.parent.mkdir(parents=True)
    candidate_file.write_text(json.dumps(candidate))
    row = manifest[0]
    journey_file = output / (row["movementProgramId"] + ".json")
    journey = {"outcome": "accepted", "generationLayoutRevision": layer3.layout_revision(candidate),
               "movementProgramId": row["movementProgramId"], "actorPlacementId": row["actorPlacementId"]}
    journey_file.write_text(json.dumps(journey))
    return output, live_file, candidate_file, journey_file, doc, candidate


def test_publication_rejects_changed_live_bytes(publication_case):
    output, live_file, *_ = publication_case
    live_file.write_bytes(live_file.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="changed; refusing stale"):
        layer3.publish_validated(output)


def test_publication_rejects_modified_candidate(publication_case):
    output, _, candidate_file, _, _, candidate = publication_case
    candidate["placements"][0]["transform"]["position"]["x"] += 1
    candidate_file.write_text(json.dumps(candidate))
    with pytest.raises(ValueError, match="differs from the authored intent: placements"):
        layer3.publish_validated(output)


@pytest.mark.parametrize("field,value", [
    ("outcome", "refused"), ("generationLayoutRevision", "old"),
    ("movementProgramId", "other-program"), ("actorPlacementId", "other-actor"),
])
def test_publication_rejects_wrong_journey(publication_case, field, value):
    output, _, _, journey_file, *_ = publication_case
    journey = json.loads(journey_file.read_text())
    journey[field] = value
    journey_file.write_text(json.dumps(journey))
    with pytest.raises(ValueError, match="Missing or stale accepted journey"):
        layer3.publish_validated(output)


def test_publication_saves_once_with_expected_revision(publication_case, monkeypatch):
    output, _, _, _, before, candidate = publication_case
    calls = []

    class Host:
        service = None

        def __init__(self, *_args, **_kwargs):
            self.service = self

        def principal(self):
            return "principal"

        def save_layout(self, principal, site, layout_id, document, revision):
            calls.append((principal, site, layout_id, document, revision))
            return {"layout": document, "revision": layer3.layout_revision(document)}

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(layer3, "LocalFacilityLayoutHost", Host)
    layer3.publish_validated(output)
    assert calls == [("principal", layer3.SITE, layer3.LAYOUT_ID, candidate, layer3.layout_revision(before)), "closed"]
    receipt = json.loads((output / "publication.json").read_text())
    assert receipt["saveCalls"] == 1
    assert receipt["manualUnchanged"] is True
