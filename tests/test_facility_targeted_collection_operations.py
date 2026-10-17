"""Targeted authoring preserves collections and uses the existing domain checks."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.decals import MAX_DECALS
from ai_inspector.facility_layout.errors import FacilityValidationError
from ai_inspector.facility_layout.operations import (
    FacilityLayoutOperationError,
    apply_facility_layout_operations as apply,
    apply_prevalidated_facility_layout_operations,
    supported_facility_layout_operations,
)
from ai_inspector.facility_layout.plan_settings import default_plan_settings


IMAGE = "/generated/facility-wall-art/" + "a" * 64 + ".png"
KINDS = (
    ("floor_surface", "facilityFloorSurfaces", "surfaces", "surface", "surfaceId"),
    ("interior_wall", "facilityInteriorWalls", "walls", "wall", "wallId"),
    ("decal", "facilityDecals", "artworks", "decal", "artworkId"),
)


def row(kind, number=0):
    if kind == "floor_surface":
        x = 1 + number * 3
        return dict(surfaceId=f"fs-{number}", label=f"Floor {number}",
                    boundary=[dict(x=x, z=1), dict(x=x+2, z=1), dict(x=x+2, z=3), dict(x=x, z=3)],
                    elevation=0, material="rubber", color="#45484b", roughness=.8)
    if kind == "interior_wall":
        return dict(wallId=f"iw-{number}", label=f"Wall {number}",
                    start=dict(x=20+number*2, z=5), end=dict(x=20+number*2, z=25),
                    heightMeters=3, thicknessMeters=.2, baseElevation=0,
                    color="#45484b", openings=[])
    return dict(artworkId=f"decal-{number}", label=f"Decal {number}", imagePath=IMAGE,
                uv=[0, 0, 1, 1], region=[.1, .1, .2, .9], coverage=1,
                target=dict(edge=0, side="interior"))


def artwork(collection, identifier="legacy-a"):
    if collection == "artworks":
        return dict(artworkId=identifier, imagePath=IMAGE, edge=1, startMeters=1,
                    widthMeters=2, bottomMeters=0, heightMeters=2,
                    backingColor="#ababab", borderColor="#45484b")
    return dict(artworkId=identifier, imagePath=IMAGE, uv=[0, 0, 1, 1],
                target=dict(edge=2, side="interior"), region=[.1, .1, .2, .9], coverage=1)


def document():
    path = Path(__file__).parent / "fixtures" / "facility_layout" / "empty_cell.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["extensions"] = {
        "facilityPlan": default_plan_settings(),
        "customEditor": {"version": 3, "enabled": False, "settings": {"view": "plan"}},
    }
    settings = dict(boundarySource="plan", heightMeters=3, thicknessMeters=.2, openings=[],
                    interiorColor="#343638", exteriorFinish={
                        "color": "#282b2d", "jointColor": "#16191b", "panelWidthMeters": 3,
                        "artworks": [artwork("artworks")],
                        "fittedArtworks": [artwork("fittedArtworks", "legacy-b")],
                        "accentStrips": [dict(edge=3, startMeters=1, widthMeters=2, color="#999999")],
                    })
    return apply(value, [dict(op="set_perimeter_walls", wallSettings=settings)])["document"]


def seeded(kind, rows):
    setter, field, collection = {
        "floor_surface": ("set_floor_surfaces", "surfaces", "surfaces"),
        "interior_wall": ("set_interior_walls", "walls", "walls"),
        "decal": ("set_decals", "decals", "artworks"),
    }[kind]
    return apply(document(), [{"op": setter, field: {"version": 1, collection: rows}}])["document"]


@pytest.mark.parametrize("kind,extension,collection,field,identity", KINDS)
def test_upsert_update_delete_preserve_other_rows_and_settings(kind, extension, collection, field, identity):
    before = seeded(kind, [row(kind), row(kind, 1)])
    snapshot = deepcopy(before)
    replacement = dict(row(kind), label="Updated")
    operations = [dict(op="upsert_"+kind, **{field: replacement}),
                  dict(op="upsert_"+kind, **{field: row(kind, 2)})]
    saved_operations = deepcopy(operations)
    result = apply(before, operations)
    after = result["document"]
    entries = after["extensions"][extension][collection]
    assert [entry[identity] for entry in entries] == [row(kind, i)[identity] for i in range(3)]
    assert entries[0]["label"] == "Updated"
    assert entries[1] == before["extensions"][extension][collection][1]
    assert result["createdIds"] == [row(kind, 2)[identity]]
    assert result["affectedIds"] == sorted([row(kind)[identity], row(kind, 2)[identity]])
    untouched = deepcopy(after)
    untouched["extensions"][extension] = before["extensions"][extension]
    assert untouched == before
    assert before == snapshot and operations == saved_operations
    assert apply(before, operations) == result

    repeated = apply(after, operations)
    assert not repeated["changed"] and repeated["createdIds"] == []
    removed = apply(after, [dict(op="delete_"+kind, **{identity: row(kind)[identity]})])
    assert removed["affectedIds"] == [row(kind)[identity]]
    assert removed["createdIds"] == []
    assert removed["document"]["extensions"][extension] == dict(version=1, **{collection: entries[1:]})


@pytest.mark.parametrize("kind,extension,collection,field,identity", KINDS)
def test_create_missing_collection_and_remove_last_row(kind, extension, collection, field, identity):
    before = document()
    operation = dict(op="upsert_"+kind, **{field: row(kind)})
    result = apply(before, [operation])
    assert result["createdIds"] == result["affectedIds"] == [row(kind)[identity]]
    prevalidated = apply_prevalidated_facility_layout_operations(before, [operation], base_revision=layout_revision(before))
    assert prevalidated["document"] == result["document"]
    assert prevalidated["operationResults"] == result["operationResults"]
    after = apply(result["document"], [dict(op="delete_"+kind, **{identity: row(kind)[identity]})])["document"]
    assert after["extensions"][extension] == dict(version=1, **{collection: []})


@pytest.mark.parametrize("kind,extension,collection,field,identity", KINDS)
@pytest.mark.parametrize("exists", [False, True])
def test_missing_delete_fails_atomically(kind, extension, collection, field, identity, exists):
    before = seeded(kind, [row(kind)]) if exists else document()
    snapshot = deepcopy(before)
    with pytest.raises(FacilityLayoutOperationError) as error:
        apply(before, [dict(op="upsert_"+kind, **{field: row(kind, 1)}),
                       dict(op="delete_"+kind, **{identity: "missing"})])
    assert error.value.code == "operation_target_not_found"
    assert error.value.operation_index == 1
    assert before == snapshot


@pytest.mark.parametrize("kind,extension,collection,field,identity", KINDS)
@pytest.mark.parametrize("malformed", ["partial", "unknown_row", "unknown_operation", "missing_id", "bad_id"])
def test_upsert_rejects_malformed_full_rows(kind, extension, collection, field, identity, malformed):
    item = row(kind)
    operation = dict(op="upsert_"+kind, **{field: item})
    if malformed == "partial":
        item.pop("label")
    elif malformed == "unknown_row":
        item["extra"] = True
    elif malformed == "unknown_operation":
        operation["extra"] = True
    elif malformed == "missing_id":
        item.pop(identity)
    else:
        item[identity] = "../bad"
    before = document()
    snapshot = deepcopy(before)
    with pytest.raises(FacilityLayoutOperationError):
        apply(before, [operation])
    assert before == snapshot


def test_floor_upsert_checks_overlap_against_untouched_surfaces():
    before = seeded("floor_surface", [row("floor_surface")])
    overlapping = dict(row("floor_surface"), surfaceId="fs-overlap")
    with pytest.raises(FacilityLayoutOperationError, match="overlap") as error:
        apply(before, [dict(op="upsert_floor_surface", surface=overlapping)])
    assert error.value.code == "invalid_floor_surfaces"


def test_interior_delete_cascades_only_bound_decals_and_reports_ids():
    before = seeded("interior_wall", [row("interior_wall"), row("interior_wall", 1)])
    bound = dict(row("decal"), target=dict(wallId="iw-0", side="left"))
    other = dict(row("decal", 1), target=dict(wallId="iw-1", side="right"))
    before = apply(before, [dict(op="set_decals", decals=dict(version=1, artworks=[bound, other]))])["document"]
    result = apply(before, [dict(op="delete_interior_wall", wallId="iw-0")])
    assert result["affectedIds"] == ["decal-0", "iw-0"]
    assert result["document"]["extensions"]["facilityDecals"]["artworks"] == [other]
    assert result["document"]["extensions"]["facilityInteriorWalls"]["walls"] == before["extensions"]["facilityInteriorWalls"]["walls"][1:]


def test_wall_edit_recompiles_panels_and_keeps_final_decal_validation():
    before = seeded("interior_wall", [row("interior_wall"), row("interior_wall", 1)])
    decal = dict(row("decal"), target=dict(wallId="iw-0", side="left"))
    before = apply(before, [dict(op="upsert_decal", decal=decal)])["document"]
    taller = dict(row("interior_wall"), heightMeters=4)
    after = apply(before, [dict(op="upsert_interior_wall", wall=taller)])["document"]
    assert after["extensions"]["facilityDecals"] == before["extensions"]["facilityDecals"]
    with pytest.raises(FacilityLayoutOperationError, match="fields"):
        apply(before, [dict(op="upsert_interior_wall", wall=before["extensions"]["facilityInteriorWalls"]["walls"][0])])
    conflict = dict(taller, openings=[dict(startMeters=2, endMeters=5)])
    snapshot = deepcopy(before)
    with pytest.raises(FacilityValidationError):
        apply(before, [dict(op="upsert_interior_wall", wall=conflict)])
    assert before == snapshot


@pytest.mark.parametrize("patch", [
    dict(target=dict(wallId="iw-missing", side="left")),
    dict(imagePath="/api/facility-decal-images/site-b/"+"a"*64+".png"),
    dict(artworkId="legacy-a"),
])
def test_decal_upsert_reuses_target_site_and_cross_collection_identity_checks(patch):
    with pytest.raises(FacilityLayoutOperationError) as error:
        apply(document(), [dict(op="upsert_decal", decal=dict(row("decal"), **patch))])
    assert error.value.code == "invalid_decals"


def test_targeted_decal_cannot_exceed_existing_combined_artwork_budget():
    before = seeded("decal", [row("decal", i) for i in range(MAX_DECALS-2)])
    with pytest.raises(FacilityLayoutOperationError, match="budget"):
        apply(before, [dict(op="upsert_decal", decal=row("decal", MAX_DECALS))])


def test_edit_perimeter_merges_finish_without_losing_legacy_composition():
    before = document()
    operation = dict(op="edit_perimeter_walls", patch={
        "interiorColor": "#ABCDEF", "exteriorFinish": {"color": "#AABBCC"},
    })
    result = apply(before, [operation])
    expected = deepcopy(before["extensions"]["facilityPerimeterWalls"]["settings"])
    expected["interiorColor"] = "#abcdef"
    expected["exteriorFinish"]["color"] = "#aabbcc"
    bulk = apply(before, [dict(op="set_perimeter_walls", wallSettings=expected)])
    assert result["document"] == bulk["document"]
    assert result["affectedIds"] == [before["layoutId"]]
    assert apply(before, [operation]) == result
    assert not apply(result["document"], [operation])["changed"]


def test_perimeter_patch_reports_changed_added_and_removed_artwork_ids():
    before = document()
    changed = dict(artwork("artworks"), backingColor="#123456")
    patch = {"exteriorFinish": {"artworks": [changed, artwork("artworks", "added")], "fittedArtworks": []}}
    result = apply(before, [dict(op="edit_perimeter_walls", patch=patch)])
    assert result["createdIds"] == ["added"]
    assert result["affectedIds"] == sorted([before["layoutId"], "legacy-a", "legacy-b", "added"])
    finish = result["document"]["extensions"]["facilityPerimeterWalls"]["settings"]["exteriorFinish"]
    assert finish["accentStrips"] == before["extensions"]["facilityPerimeterWalls"]["settings"]["exteriorFinish"]["accentStrips"]


@pytest.mark.parametrize("collection", ["artworks", "fittedArtworks"])
def test_legacy_artwork_upsert_and_delete_only_touch_selected_row(collection):
    before = document()
    existing_id = "legacy-a" if collection == "artworks" else "legacy-b"
    replacement = dict(artwork(collection, existing_id), imagePath=IMAGE.replace("a"*64, "b"*64))
    operation = dict(op="upsert_wall_artwork", collection=collection, artwork=replacement)
    result = apply(before, [operation])
    expected = deepcopy(before["extensions"]["facilityPerimeterWalls"]["settings"])
    expected["exteriorFinish"][collection] = [replacement]
    assert result["document"] == apply(before, [dict(op="set_perimeter_walls", wallSettings=expected)])["document"]
    assert result["createdIds"] == [] and result["affectedIds"] == [existing_id]
    created = apply(result["document"], [dict(op="upsert_wall_artwork", collection=collection, artwork=artwork(collection, "new-art"))])
    assert created["createdIds"] == created["affectedIds"] == ["new-art"]
    deleted = apply(created["document"], [dict(op="delete_wall_artwork", collection=collection, artworkId="new-art")])
    assert deleted["document"] == result["document"]
    assert deleted["createdIds"] == [] and deleted["affectedIds"] == ["new-art"]
    assert apply(before, [operation]) == result
    assert not apply(result["document"], [operation])["changed"]


@pytest.mark.parametrize("operation", [
    dict(op="delete_wall_artwork", collection="artworks", artworkId="legacy-b"),
    dict(op="delete_wall_artwork", collection="fittedArtworks", artworkId="legacy-a"),
    dict(op="delete_decal", artworkId="legacy-a"),
])
def test_deletes_do_not_cross_artwork_collections(operation):
    with pytest.raises(FacilityLayoutOperationError) as error:
        apply(document(), [operation])
    assert error.value.code == "operation_target_not_found"


@pytest.mark.parametrize("collection", ["artworks", "fittedArtworks"])
def test_legacy_upsert_cannot_duplicate_a_decal_identity(collection):
    before = apply(document(), [dict(op="upsert_decal", decal=row("decal"))])["document"]
    snapshot = deepcopy(before)
    with pytest.raises(FacilityValidationError):
        apply(before, [dict(op="upsert_wall_artwork", collection=collection, artwork=artwork(collection, "decal-0"))])
    assert before == snapshot


@pytest.mark.parametrize("operation", [
    dict(op="delete_decal", decalId="decal-0"),
    dict(op="delete_floor_surface", surfaceId="fs-0", extra=True),
    dict(op="delete_interior_wall", wallId=[]),
    dict(op="edit_perimeter_walls", patch={"panels": []}),
    dict(op="edit_perimeter_walls", patch={"exteriorFinish": None}),
    dict(op="edit_perimeter_walls", patch={"exteriorFinish": {"unknown": True}}),
    dict(op="upsert_wall_artwork", collection="wallFaces", artwork=artwork("artworks")),
    dict(op="upsert_wall_artwork", collection="fittedArtworks", artwork=artwork("fittedArtworks", "legacy-a")),
    dict(op="upsert_wall_artwork", collection="artworks", artwork={"artworkId": "legacy-a"}),
    dict(op="delete_wall_artwork", collection="artworks", artworkId="legacy-a", extra=True),
])
def test_malformed_targeted_operations_fail_closed(operation):
    before = document()
    snapshot = deepcopy(before)
    with pytest.raises(FacilityLayoutOperationError):
        apply(before, [operation])
    assert before == snapshot


def test_perimeter_patch_runs_final_decal_opening_checks_atomically():
    before = apply(document(), [dict(op="upsert_decal", decal=row("decal"))])["document"]
    snapshot = deepcopy(before)
    with pytest.raises(FacilityValidationError):
        apply(before, [dict(op="edit_perimeter_walls", patch={"openings": [dict(edge=0, startMeters=5, endMeters=7)]})])
    assert before == snapshot


def test_perimeter_patch_can_switch_back_from_polygon_to_plan():
    before = document()
    polygon = [dict(x=0, z=0), dict(x=40, z=0), dict(x=40, z=30), dict(x=0, z=30)]
    changed = apply(before, [dict(op="edit_perimeter_walls", patch={"boundarySource": "polygon", "boundary": polygon})])["document"]
    restored = apply(changed, [dict(op="edit_perimeter_walls", patch={"boundarySource": "plan"})])["document"]
    assert restored == before


def test_perimeter_and_finish_must_exist_before_targeted_edits():
    before = document()
    before["extensions"].pop("facilityPerimeterWalls")
    with pytest.raises(FacilityLayoutOperationError) as error:
        apply(before, [dict(op="edit_perimeter_walls", patch={"interiorColor": "#555555"})])
    assert error.value.code == "operation_target_not_found"
    before = document()
    settings = deepcopy(before["extensions"]["facilityPerimeterWalls"]["settings"])
    settings.pop("exteriorFinish")
    before = apply(before, [dict(op="set_perimeter_walls", wallSettings=settings)])["document"]
    operation = dict(op="upsert_wall_artwork", collection="artworks", artwork=artwork("artworks"))
    with pytest.raises(FacilityLayoutOperationError) as error:
        apply(before, [operation])
    assert error.value.code == "operation_target_not_found"
    initialized = apply(before, [dict(op="edit_perimeter_walls", patch={"exteriorFinish": {"color": "#555555"}}), operation])
    assert initialized["createdIds"] == ["legacy-a"]


def test_all_targeted_operations_are_registered():
    expected = {f"{verb}_{kind}" for verb in ("upsert", "delete") for kind, *_ in KINDS}
    expected.update(("edit_perimeter_walls", "upsert_wall_artwork", "delete_wall_artwork"))
    assert expected <= set(supported_facility_layout_operations())
