"""P4a: authored objects, workspace bindings and geometry. Temporary stores only."""
from copy import deepcopy
import json
import math

def object_vectors():
    """Deterministic Python oracle; regenerate with --generate-vectors."""
    from ai_inspector.documentation import objects as geometry
    result = {"placement": [], "box": []}
    for i in range(180):
        size = [40 + (i * 37) % 1000, 30 + (i * 53) % 800]
        pixels = [1 + (i * 131) % 2200, 1 + (i * 79) % 1800]
        value = {"contentMode": ("contain", "cover", "contain")[i % 3]}
        if i % 3 == 2:
            value["crop"] = {"x": (i % 5) / 10, "y": (i % 4) / 10, "width": .5, "height": .6}
        source, draw = geometry.placement(value, size, pixels)
        result["placement"].append({"value": value, "size": size, "pixels": pixels,
                                    "expected": [source, list(draw)]})
        frame = {"x": (i % 19) / 10 - .5, "y": (i % 13) / 10 - .2,
                 "width": .01 + (i % 31) / 30, "height": .01 + (i % 23) / 22,
                 "rotation": (0, 90, 180, 270, 30, -45, 123)[i % 7]}
        page_size = [960,540] if i % 2 else [612,792]
        result["box"].append({"frame": frame, "size": page_size, "expected": geometry.box(frame, page_size)})
    return result


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if sys.argv[1:] != ["--generate-vectors"]:
        raise SystemExit("Use --generate-vectors; tests are run by pytest.")
    vector_path = Path(__file__).parent / "fixtures" / "documentation_object_vectors.json"
    vector_path.write_text(json.dumps(object_vectors(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print("Wrote 180 placement and 180 box vectors.")
    raise SystemExit(0)


import pytest

from ai_inspector.documentation import objects
from ai_inspector.documentation.commands import DocumentEditError, canonical_bytes, operation_store
from ai_inspector.parts_manual.documentation import (
    _document_object, _upgrade_documentation_scene, replay_documentation_commands,
    validate_documentation_scene, DocumentationSceneError,
)
from tests.test_documentation_rich_text import scene, KIND, NUMBER, PAGE, OBJECT
from tests.test_documentation_refresh import mmle_client


def value(key="document-object-a", kind="shape", **fields):
    item = {"objectId": key, "name": key, "type": kind, "source": "user",
            "frame": {"x": .1, "y": .1, "width": .2, "height": .1, "rotation": 0}}
    if kind == "shape":
        item["shapeType"] = "rectangle"
    elif kind == "image":
        item.update(asset={"assetId": "a" * 64, "mimeType": "image/png", "filename": "proof.png",
            "url": "/api/parts-manual/PROOF/documentation-assets/" + "a" * 64}, contentMode="contain")
    else:
        item["content"] = "A"
    return _document_object({**item, **fields})


def refused(code, fn):
    with pytest.raises(DocumentEditError) as caught:
        fn()
    assert caught.value.code == code
    return caught.value


def page(*items):
    return {"documentObjects": {v["objectId"]: deepcopy(v) for v in items},
            "objectOrder": [v["objectId"] for v in items]}


def operation(p, kind, **fields):
    default_id = {} if kind in {"set_object_order", "arrange_objects"} else {"objectId": p["objectOrder"][0]}
    return objects.apply_operation(p, {"operation": kind, "pageId": PAGE,
        **default_id, **fields}, (960, 540))


def test_schema_six_read_is_pure_and_backup_is_exact(scene):
    scene.add("document-object-b")
    loaded = scene.load()["scene"]
    before = deepcopy(loaded["pages"][PAGE]["documentObjects"])
    loaded["schemaVersion"] = 6
    for p in loaded["pages"].values():
        p.pop("objectOrder", None)
    for command in loaded["commands"]:
        if "change" in command:
            command["change"]["changes"] = [c for c in command["change"]["changes"] if c["path"][-1] != "objectOrder"]
    raw = (json.dumps(loaded, indent=2) + "\n").encode()
    scene.path.write_bytes(raw)
    read = scene.load()
    assert read["scene"]["schemaVersion"] == 7
    assert read["scene"]["pages"][PAGE]["documentObjects"] == before
    assert read["scene"]["pages"][PAGE]["objectOrder"] == list(before)
    assert scene.path.read_bytes() == raw
    frame = {**before[OBJECT]["frame"], "x": .2}
    scene.command({"operation": "set_object_frame", "frame": frame})
    assert (scene.path.parent / "documentation-scene.v6.json").read_bytes() == raw
    future = deepcopy(loaded)
    future["schemaVersion"] = 8
    with pytest.raises(DocumentationSceneError):
        _upgrade_documentation_scene(future)


def history(scene, direction):
    loaded = scene.load()
    return scene.repo.move_history(NUMBER, scene.base["sourceRevision"], scene.base["manualPlanRevision"],
        base_revision=loaded["revision"], direction=direction, identity_document=scene.base)


def reset(scene):
    # The shared fixture offers no figure target; the routes offer one on pages with a figure.
    loaded = scene.load()
    names = list(loaded["scene"]["pages"].get(PAGE, {}).get("documentObjects", {}))
    return scene.repo.apply_command(NUMBER, scene.base["sourceRevision"], scene.base["manualPlanRevision"],
        base_revision=loaded["revision"], identity_document=scene.base,
        page_targets={PAGE: {"document_object": names, "page_element": ["generated-note"], "figure": [PAGE]}},
        command={"operation": "reset_page", "pageId": PAGE, "targetType": "figure", "targetId": PAGE})


def test_order_add_remove_reorder_reset_and_undo(scene):
    b, c = "document-object-b", "document-object-c"
    scene.add(b); scene.add(c)
    original = deepcopy(scene.load()["scene"]["pages"][PAGE])
    scene.command({"operation": "remove_object", "targetId": b})
    assert scene.load()["scene"]["pages"][PAGE]["objectOrder"] == [OBJECT, c]
    history(scene, "undo")
    assert scene.load()["scene"]["pages"][PAGE] == original
    history(scene, "redo")
    assert scene.load()["scene"]["pages"][PAGE]["objectOrder"] == [OBJECT, c]
    history(scene, "undo")
    scene.command({"operation": "set_object_order", "targetType": "figure", "targetId": PAGE, "order": [c, b, OBJECT]})
    assert scene.load()["scene"]["pages"][PAGE]["objectOrder"] == [c, b, OBJECT]
    history(scene, "undo")
    assert scene.load()["scene"]["pages"][PAGE] == original
    history(scene, "redo")
    reset(scene)
    assert PAGE not in scene.load()["scene"]["pages"]
    history(scene, "undo")
    assert scene.load()["scene"]["pages"][PAGE]["objectOrder"] == [c, b, OBJECT]


def test_legacy_restore_appends_missing_ids_and_empty_order_drops(scene):
    b = "document-object-b"
    scene.add(b)
    scene.command({"operation": "remove_object", "targetId": OBJECT})
    commands = deepcopy(scene.load()["scene"]["commands"])
    # A record predating schema 7 restores only the deleted dictionary member.
    old = value(OBJECT, "text")
    commands.append({"operation": "restore_change", "change": {"changes": [{
        "path": ["pages", PAGE, "documentObjects", OBJECT],
        "before": {"present": False}, "after": {"present": True, "value": old}}]}})
    restored = replay_documentation_commands(commands)
    assert restored[PAGE]["objectOrder"] == [b, OBJECT]
    p = {"documentObjects": {}, "objectOrder": ["gone"]}
    assert objects.normalize_order(p) == [] and "objectOrder" not in p


@pytest.mark.parametrize("key,low,high", [("x", -1, 2), ("y", -1, 2), ("width", .01, 2),
                                          ("height", .01, 2), ("rotation", -180, 180)])
def test_frame_bounds(key, low, high):
    frame = value()["frame"]
    for n in (low, high):
        assert objects.frame_value({**frame, key: n})[key] == n
    for n in (low-.000001, high+.000001, True, None, float("nan"), float("inf")):
        refused("invalid_object_frame", lambda: objects.frame_value({**frame, key: n}))


@pytest.mark.parametrize("crop", [
    {"x": -.000001, "y": 0, "width": 1, "height": 1},
    {"x": 1, "y": 0, "width": .01, "height": 1},
    {"x": 0, "y": 1, "width": 1, "height": .01},
    {"x": 0, "y": 0, "width": .009999, "height": 1},
    {"x": 0, "y": 0, "width": 1.000001, "height": 1},
    {"x": .5, "y": 0, "width": .500001, "height": 1},
    {"x": 0, "y": .5, "width": 1, "height": .500001},
    {"x": False, "y": 0, "width": 1, "height": 1},
    {"x": 0, "y": "0", "width": 1, "height": 1},
    {"x": 0, "y": 0, "width": 1, "height": float("inf")},
    {}, {"x": 0, "y": 0, "width": 1, "height": 1, "extra": 2},
])
def test_crop_bounds_and_types(crop):
    refused("invalid_image_crop", lambda: objects.crop_value(crop))


def test_crop_canonical_and_cover_conversion(scene):
    assert objects.crop_value({"x": 0, "y": 0, "width": 1, "height": 1}) is None
    assert objects.crop_value({"x": .333333333, "y": .99, "width": .5, "height": .01}) == {
        "x": .333333, "y": .99, "width": .5, "height": .01}
    assert objects.crop_value({"x": .5, "y": 0, "width": .5000000005, "height": 1})["width"] == .5
    image = value("document-object-image", "image", contentMode="cover")
    scene.command({"operation": "add_object", "targetId": image["objectId"], "documentObject": image})
    before = deepcopy(scene.load()["scene"]["pages"][PAGE])
    scene.command({"operation": "set_image_crop", "targetId": image["objectId"],
                   "crop": {"x": .5, "y": 0, "width": .5, "height": .5}})
    changed = scene.load()["scene"]["pages"][PAGE]["documentObjects"][image["objectId"]]
    assert changed["contentMode"] == "contain" and changed["crop"]["x"] == .5
    history(scene, "undo")
    assert scene.load()["scene"]["pages"][PAGE] == before
    for crop in ({"x": 0, "y": 0, "width": 1, "height": 1}, {"x": .5, "y": 0, "width": .5, "height": 1}):
        result, command, _ = operation(page(image), "set_image_crop", crop=crop)
        assert result["documentObjects"][image["objectId"]]["contentMode"] == "contain"
        assert command["contentMode"] == "contain"


def test_aspect_lock_release_lone_dimension_and_legacy_resize(scene):
    p = page(value(aspectLock=True))
    refused("aspect_locked", lambda: operation(p, "set_object_frame", width=.3, height=.1))
    result, _, _ = operation(p, "set_object_frame", width=.3)
    assert result["documentObjects"][p["objectOrder"][0]]["frame"]["height"] == .15
    result, _, _ = operation(p, "set_object_frame", height=.2)
    assert result["documentObjects"][p["objectOrder"][0]]["frame"]["width"] == .4
    result, _, _ = operation(p, "set_object_frame", width=.3, aspectLock=False)
    assert "aspectLock" not in result["documentObjects"][p["objectOrder"][0]]
    objects.check_aspect(p["documentObjects"][p["objectOrder"][0]], {**value()["frame"], "width": .2002})
    refused("aspect_locked", lambda: objects.check_aspect(p["documentObjects"][p["objectOrder"][0]], {**value()["frame"], "width": .200201}))
    original = scene.load()["scene"]["pages"][PAGE]["documentObjects"][OBJECT]["frame"]
    scene.command({"operation": "set_object_frame", "frame": original, "aspectLock": True})
    refused("aspect_locked", lambda: scene.command({"operation": "resize", "sizeDelta": [.1, 0, 0]}))
    scene.command({"operation": "set_object_frame", "frame": original, "aspectLock": False})
    assert "aspectLock" not in scene.load()["scene"]["pages"][PAGE]["documentObjects"][OBJECT]


def test_angle_policy_live_and_old_replay(scene):
    image = value("document-object-image", "image")
    scene.command({"operation": "add_object", "targetId": image["objectId"], "documentObject": image})
    refused("unsupported_object_operation", lambda: scene.command({"operation": "rotate",
        "targetId": image["objectId"], "rotation": [0, 0, 15]}))
    for angle in (0, 90, -90, 180, -180):
        objects.image_angle(image, {**image["frame"], "rotation": angle})
    old = deepcopy(scene.load()["scene"]["commands"])
    old.append({"operation": "rotate", "pageId": PAGE, "targetType": "document_object",
                "targetId": image["objectId"], "rotation": [0, 0, 37]})
    restored = replay_documentation_commands(old)
    assert restored[PAGE]["documentObjects"][image["objectId"]]["frame"]["rotation"] == 37


@pytest.mark.parametrize("arrangement,expected", [
    ("align_left", [(.1, .1), (.1, .4), (.1, .8)]),
    ("align_center", [(.475, .1), (.525, .4), (.55, .8)]),
    ("align_right", [(.85, .1), (.95, .4), (1., .8)]),
    ("align_top", [(.1, .1), (.5, .1), (1., .1)]),
    ("align_middle", [(.1, .45), (.5, .4), (1., .45)]),
    ("align_bottom", [(.1, .8), (.5, .7), (1., .8)]),
    ("distribute_horizontal", [(.1, .1), (.6, .4), (1., .8)]),
    ("distribute_vertical", [(.1, .1), (.5, .4), (1., .8)]),
])
def test_arrangement_vectors(arrangement, expected):
    rows = [value("document-object-a"), value("document-object-b", frame={"x": .5, "y": .4, "width": .1, "height": .2, "rotation": 0}),
            value("document-object-c", frame={"x": 1., "y": .8, "width": .05, "height": .1, "rotation": 0})]
    if arrangement == "distribute_vertical":
        rows[1]["frame"]["y"] = .3  # The equal-gap result is .4.
    for size in ((960, 540), (612, 792)):
        result = objects.arrangement_frames(rows, arrangement, size)
        for row, xy in zip(result, expected):
            assert (row["frame"]["x"], row["frame"]["y"]) == pytest.approx(xy, abs=1e-6)


@pytest.mark.parametrize("size,left,top,right_x,bottom_y", [
    ((960, 540), .171875, -.027778, .471875, .372222),
    ((612, 792), .135294, .072727, .435294, .472727),
])
def test_rotated_page_fraction_vectors(size, left, top, right_x, bottom_y):
    a = value(frame={"x": .1, "y": .1, "width": .2, "height": .1, "rotation": 90})
    b = value("document-object-b", frame={"x": .5, "y": .4, "width": .1, "height": .2, "rotation": 0})
    for arrangement, oid, axis, expected in (
        ("align_left", b["objectId"], "x", left), ("align_top", b["objectId"], "y", top),
        ("align_right", a["objectId"], "x", right_x), ("align_bottom", a["objectId"], "y", bottom_y)):
        result = {r["targetId"]: r["frame"] for r in objects.arrangement_frames([a, b], arrangement, size)}
        assert result[oid][axis] == pytest.approx(expected, abs=1e-6)


def test_distribution_negative_gaps_and_id_tie():
    rows = [value("document-object-c"), value("document-object-b"), value("document-object-a")]
    rows[0]["frame"]["x"] = .2
    rows[1]["frame"]["x"] = .15
    rows[2]["frame"]["x"] = .1
    rows[1]["frame"]["width"] = .3
    result = objects.arrangement_frames(rows, "distribute_horizontal", (960, 540))
    assert [r["targetId"] for r in result] == [r["objectId"] for r in reversed(rows)]
    assert [r["frame"]["x"] for r in result] == pytest.approx([.1, .125, .25])


@pytest.mark.parametrize("size,mode,crop,source,drawn", [
    ((100, 100), "contain", None, (0, 0, 1, 1), (0, 25, 100, 50)),
    ((100, 100), "cover", None, (.25, 0, .5, 1), (0, 0, 100, 100)),
    ((400, 100), "contain", None, (0, 0, 1, 1), (100, 0, 200, 100)),
    ((400, 100), "cover", None, (0, .25, 1, .5), (0, 0, 400, 100)),
    ((100, 200), "cover", {"x": .5, "y": 0, "width": .5, "height": .5}, (.5, 0, .5, .5), (0, 75, 100, 50)),
])
def test_placement(size, mode, crop, source, drawn):
    result, rect = objects.placement({"contentMode": mode, "crop": crop}, size, (200, 100))
    assert tuple(result[k] for k in ("x", "y", "width", "height")) == pytest.approx(source)
    assert rect == pytest.approx(drawn)


def test_refusals_do_not_mutate_and_lock_all_operations():
    a, b = value(), value("document-object-b")
    p = page(a, b)
    before = deepcopy(p)
    cases = [
        ("object_not_found", "set_object_frame", {"objectId": "missing", "x": .2}),
        ("unsupported_object_operation", "set_image_crop", {"crop": None}),
        ("invalid_object_order", "set_object_order", {"order": [a["objectId"]]}),
        ("invalid_object_order", "set_object_order", {"order": [a["objectId"], a["objectId"]]}),
        ("invalid_object_order", "set_object_order", {"order": p["objectOrder"]}),
        ("invalid_object_frame", "set_object_frame", {"x": .1}),
        ("invalid_object_frame", "arrange_objects", {"objectIds": p["objectOrder"], "arrangement": "distribute_vertical"}),
    ]
    for code, kind, fields in cases:
        refused(code, lambda: operation(p, kind, **fields))
        assert p == before
    p["documentObjects"][a["objectId"]]["locked"] = True
    for kind, fields in [("set_object_frame", {"x": .2}), ("set_image_crop", {"crop": None}),
                         ("set_object_order", {"order": list(reversed(p["objectOrder"]))}),
                         ("arrange_objects", {"objectIds": p["objectOrder"], "arrangement": "align_left"})]:
        refused("object_locked", lambda: operation(p, kind, **fields))


def test_batches_preimage_chained_results_limits_and_one_undo(scene):
    state, document, _ = scene.snapshot()
    obj = state["scene"]["pages"][PAGE]["documentObjects"][OBJECT]
    hashed = objects.object_hash(obj)
    ops = [{"operation": "set_object_frame", "pageId": PAGE, "objectId": OBJECT, "expectedObjectHash": hashed, "x": x}
           for x in (.2, .3)]
    commands, expected, current, results = objects.prepare_batch(state["scene"], document, ops, state["revision"])
    assert results[0]["objects"][0]["frame"]["x"] == .2
    assert results[0]["objects"][0]["objectHash"] != results[1]["objects"][0]["objectHash"]
    before = canonical_bytes(scene.load()["scene"]["pages"])
    arguments = dict(base_revision=state["sceneRevision"], expected_revision=state["revision"], request_id="objects",
        commands=commands, page_targets={PAGE: {"document_object": [OBJECT]}}, expected_hashes=expected,
        current_hashes=current, hashes_revision=state["sceneRevision"], object_results=results, identity_document=scene.base)
    result = scene.repo.apply_batch(NUMBER, scene.base["sourceRevision"], scene.base["manualPlanRevision"], **arguments)
    assert result["receipt"]["operationResults"] == results
    assert result["receipt"]["revision"] == result["receipt"]["beforeRevision"] + 1
    assert scene.repo.apply_batch(NUMBER, scene.base["sourceRevision"], scene.base["manualPlanRevision"], **arguments)["receipt"] == result["receipt"]
    history(scene, "undo")
    assert canonical_bytes(scene.load()["scene"]["pages"]) == before
    refused("invalid_document_operation", lambda: operation_store(ops * 7))
    refused("invalid_document_operation", lambda: operation_store([ops[0], {"operation": "replace_text", "targetId": OBJECT, "text": ""}]))
    refused("invalid_document_operation", lambda: operation_store([ops[0], {**ops[0], "pageId": "another"}]))
    refused("content_hash_mismatch", lambda: objects.prepare_batch(state["scene"], document,
        [{**ops[0], "expectedObjectHash": "0"*64}], state["revision"]))


def test_sage_objects_read_batch_retry_and_refusal(mmle_client, monkeypatch):
    import server
    from tests.test_codex_documentation_tools import gateway, call
    host = server._DocumentationAgentHost()
    reader = gateway(host, "MMLE-50D", timeout=3600)
    snapshot = host.document_snapshot("MMLE-50D", KIND)
    state = snapshot["state"]
    page_id = snapshot["document"]["pages"][0]["pageId"]
    added = mmle_client.post("/api/operations-manual/MMLE-50D/documentation-scene/commands", json={
        "baseRevision": state["sceneRevision"], "sourceRevision": state["sourceRevision"],
        "manualPlanRevision": state["manualPlanRevision"], "operation": "add_object", "pageId": page_id,
        "targetType": "document_object", "targetId": OBJECT, "documentObject": value(OBJECT)})
    assert added.status_code == 200, added.text
    read = call(reader, "read_document_objects", {"documentType": KIND, "pageIds": [page_id]})
    assert read["ok"], read
    data = read["data"]
    row = next(v for v in data["pages"][0]["objects"] if v["objectId"] == OBJECT)
    assert set(row) == {"objectId", "type", "name", "locked", "frame", "box", "aspectLock", "objectHash", "shapeType"}
    args = {"documentId": data["documentId"], "expectedRevision": data["revision"], "requestId": "object-tool",
        "operations": [{"operation": "set_object_frame", "pageId": page_id, "objectId": OBJECT,
            "expectedObjectHash": row["objectHash"], "x": .2}, {"operation": "set_object_frame", "pageId": page_id,
            "objectId": OBJECT, "expectedObjectHash": row["objectHash"], "y": .3}]}
    result = call(reader, "apply_document_edits", args)
    assert result["ok"], result
    assert call(reader, "apply_document_edits", args) == result
    receipt = result["data"]["receipt"]
    last = receipt["operationResults"][-1]["objects"][0]
    chained = call(reader, "apply_document_edits", {**args, "requestId": "object-chain", "expectedRevision": receipt["revision"],
        "operations": [{**args["operations"][0], "expectedObjectHash": last["objectHash"], "x": .4}]})
    assert chained["ok"], chained
    bad = call(reader, "apply_document_edits", {**args, "requestId": "stale-object"})
    assert bad["error"]["code"] == "content_hash_mismatch"


@pytest.mark.parametrize("size,center,middle,dx,dy", [
    ((960,540), (.285938,.335938), (.236111,.186111), .464062, .413889),
    ((612,792), (.267647,.317647), (.286364,.236364), .482353, .363636),
])
def test_rotated_centres_and_distribution(size, center, middle, dx, dy):
    a = value(frame={"x":.1,"y":.1,"width":.2,"height":.1,"rotation":90})
    b = value("document-object-b", frame={"x":.5,"y":.4,"width":.1,"height":.2,"rotation":0})
    c = value("document-object-c", frame={"x":.8,"y":.7,"width":.1,"height":.1,"rotation":0})
    for kind, axis, expected in (("align_center","x",center),("align_middle","y",middle)):
        result = objects.arrangement_frames([a,b],kind,size)
        # The exact answers end in 5 at the seventh decimal: either rounding is correct.
        assert [r["frame"][axis] for r in result] == pytest.approx(expected,abs=1.5e-6)
    for kind, axis, expected in (("distribute_horizontal","x",dx),("distribute_vertical","y",dy)):
        result = objects.arrangement_frames([a,b,c],kind,size)
        assert result[1]["frame"][axis] == pytest.approx(expected,abs=1e-6)


def test_order_read_uses_canonical_order_and_image_identity_only(tmp_path):
    from tests.test_documentation_export_matrix import install_picture
    image = value("document-object-image", "image", asset=install_picture(tmp_path))
    text = value("document-object-text", "text")
    descriptor = {"pageId":PAGE,"documentationObjects":{text["objectId"]:text,image["objectId"]:image},
                  "documentationObjectOrder":[image["objectId"],text["objectId"]]}
    state = {"documentId":"proof","revision":99,"sourceRevision":"s","manualPlanRevision":"p",
             "sceneRevision":"r","scene":{"editRevision":7}}
    snapshot = {"state":state,"document":{"documentType":KIND,"pages":[descriptor]},"targets":{}}
    result = objects.read_objects(snapshot,[PAGE],tmp_path,"PROOF")
    assert result["revision"] == 7  # Specification slot revision must never bind an object mutation.
    rows = result["pages"][0]["objects"]
    assert [r["objectId"] for r in rows] == descriptor["documentationObjectOrder"]
    assert rows[0]["pixelSize"] == [200,100]
    assert rows[0]["assetId"] == image["asset"]["assetId"]
    assert not any(token in canonical_bytes(result) for token in (b"/api/",b"documentation-assets",b'"content":',b"filename",b"url"))
    assert result["pages"][0]["orderHash"] == objects.order_hash(descriptor)
    refused("invalid_document_operation",lambda:objects.read_objects(snapshot,[],tmp_path,"PROOF"))
    refused("invalid_document_operation",lambda:objects.read_objects(snapshot,[str(i) for i in range(9)],tmp_path,"PROOF"))


def test_noop_crop_and_order_stale_are_refused(scene):
    image = value(kind="image")
    refused("invalid_image_crop",lambda:operation(page(image),"set_image_crop",crop=None))
    state,document,_ = scene.snapshot()
    request = {"operation":"set_object_order","pageId":PAGE,"expectedOrderHash":"0"*64,"order":[OBJECT]}
    refused("content_hash_mismatch",lambda:objects.prepare_batch(state["scene"],document,[request],state["revision"]))
    good = {**request,"expectedOrderHash":objects.order_hash(state["scene"]["pages"][PAGE])}
    refused("invalid_object_order",lambda:objects.prepare_batch(state["scene"],document,[good],state["revision"]))


def test_object_operations_version_keys_and_locked_log_replay(scene):
    scene.add("document-object-b")
    before = scene.load()["scene"]
    scene.command({"operation":"set_object_order","targetType":"figure","targetId":PAGE,
                   "order":["document-object-b",OBJECT]})
    after = scene.load()["scene"]
    changed = {k for k in after["fieldVersions"] if after["fieldVersions"][k] != before["fieldVersions"].get(k)}
    assert changed == {"@page:"+PAGE}
    f = after["pages"][PAGE]["documentObjects"][OBJECT]["frame"]
    scene.command({"operation":"set_object_frame","frame":{**f,"x":.2}})
    last = scene.load()["scene"]["commands"][-1]
    assert last["change"]["versionKeys"] == [PAGE+"/document_object/"+OBJECT]
    old = deepcopy(scene.load()["scene"]["commands"])
    for command in old:
        if command.get("operation") == "add_object" and command["targetId"] == OBJECT:
            command["documentObject"]["locked"] = True
    # Live policy is deliberately not applied while replaying a saved log.
    assert replay_documentation_commands(old)[PAGE]["documentObjects"][OBJECT]["frame"]["x"] == .2


def test_frame_patch_preserves_unmentioned_bytes_and_arrangement_dimensions():
    a = value(frame={"x":.123456789,"y":.223456789,"width":.323456789,"height":.123456789,"rotation":12.3456789})
    p = page(a)
    changed, _, _ = operation(p,"set_object_frame",x=.3)
    f = changed["documentObjects"][a["objectId"]]["frame"]
    assert {k:v for k,v in f.items() if k != "x"} == {k:v for k,v in a["frame"].items() if k != "x"}
    b = value("document-object-b",frame={"x":.6,"y":.4,"width":.123456789,"height":.2,"rotation":0})
    result = objects.arrangement_frames([a,b],"align_left",(960,540))
    for row in result:
        original = next(v for v in (a,b) if v["objectId"] == row["targetId"])
        assert {k:v for k,v in row["frame"].items() if k != "x"} == {k:v for k,v in original["frame"].items() if k != "x"}


def test_invalid_order_in_stored_scene(scene):
    loaded = scene.load()["scene"]
    for order in ([], [OBJECT, OBJECT], ["missing"], [False]):
        invalid = deepcopy(loaded)
        invalid["pages"][PAGE]["objectOrder"] = order
        refused("invalid_object_order", lambda: validate_documentation_scene(invalid))


def test_add_and_reset_redo_restore_order_exactly(scene):
    initial = deepcopy(scene.load()["scene"]["pages"])
    scene.add("document-object-second")
    added = deepcopy(scene.load()["scene"]["pages"])
    history(scene, "undo")
    assert scene.load()["scene"]["pages"] == initial
    history(scene, "redo")
    assert scene.load()["scene"]["pages"] == added
    reset(scene)
    assert PAGE not in scene.load()["scene"]["pages"]
    history(scene, "undo")
    assert scene.load()["scene"]["pages"] == added
    history(scene, "redo")
    assert PAGE not in scene.load()["scene"]["pages"]


@pytest.mark.parametrize("key", ["x", "y", "width", "height"])
def test_each_crop_axis_bounds(key):
    accepted = {"x":0, "y":0, "width":.01, "height":.01}
    low, high = (0, .99) if key in {"x","y"} else (.01, 1)
    for number in (low, high):
        result = objects.crop_value({**accepted, key:number})
        assert result[key] == number
    for number in ((-.000001, 1) if key in {"x","y"} else (.009999, 1.000001)):
        refused("invalid_image_crop", lambda: objects.crop_value({**accepted, key:number}))


def test_arrangement_count_and_equal_edge_id_order():
    rows = [value("document-object-%02d" % n, frame={"x":n/100,"y":.1,"width":.1,"height":.1,"rotation":0})
            for n in range(65)]
    assert len(objects.arrangement_frames(rows[:64],"align_left",(960,540))) == 64
    for chosen in (rows[:1],rows):
        refused("invalid_object_frame",lambda:objects.arrangement_frames(chosen,"align_left",(960,540)))
    # At a tied left edge the ID, rather than input order, decides the middle object.
    tied = [value("document-object-c"),value("document-object-b"),value("document-object-a")]
    tied[0]["frame"]["x"] = .6
    result = objects.arrangement_frames(tied,"distribute_horizontal",(960,540))
    assert [r["targetId"] for r in result] == ["document-object-a","document-object-b","document-object-c"]
    assert [r["frame"]["x"] for r in result] == pytest.approx([.1,.35,.6])


def test_later_object_refusal_leaves_the_store_and_preimage_untouched(scene):
    state, document, _ = scene.snapshot()
    before = scene.path.read_bytes()
    source = deepcopy(state["scene"])
    op = {"operation":"set_object_frame","pageId":PAGE,"objectId":OBJECT,
          "expectedObjectHash":objects.object_hash(source["pages"][PAGE]["documentObjects"][OBJECT]),"x":.3}
    refused("unsupported_object_operation",lambda:objects.prepare_batch(source,document,
        [op,{"operation":"set_image_crop","pageId":PAGE,"objectId":OBJECT,
             "expectedObjectHash":op["expectedObjectHash"],"crop":None}],state["revision"]))
    assert source == state["scene"]
    assert scene.path.read_bytes() == before


# P4a-2 workspace controls.
def test_object_vectors_are_current():
    from pathlib import Path
    stored = json.loads((Path(__file__).parent / "fixtures/documentation_object_vectors.json").read_text(encoding="utf-8"))
    assert stored == object_vectors()


@pytest.mark.parametrize("lock", [True, False])
@pytest.mark.parametrize("patch,height", [({"width":.3},.1),({"width":.3,"height":.4},.4)])
def test_explicit_aspect_lock_takes_new_proportions_without_carrying(lock,patch,height):
    original = value(aspectLock=True)
    result, command, _ = operation(page(original),"set_object_frame",**patch,aspectLock=lock)
    changed = result["documentObjects"][original["objectId"]]
    assert changed["frame"]["width"] == .3 and changed["frame"]["height"] == height
    assert bool(changed.get("aspectLock")) is lock
    assert command["aspectLock"] is lock
    live = objects.live_command({"pages":{PAGE:page(original)}},command)
    assert live["frame"] == changed["frame"] and live["aspectLock"] is lock


def test_lock_only_toggle_live_and_replay(scene):
    before = deepcopy(scene.load()["scene"]["pages"][PAGE]["documentObjects"][OBJECT]["frame"])
    scene.command({"operation":"set_object_frame","aspectLock":True})
    locked = deepcopy(scene.load()["scene"]["pages"][PAGE]["documentObjects"][OBJECT])
    assert locked["frame"] == before and locked["aspectLock"]
    refused("invalid_object_frame",lambda:scene.command({"operation":"set_object_frame","aspectLock":True}))
    scene.command({"operation":"set_object_frame","aspectLock":False})
    assert "aspectLock" not in scene.load()["scene"]["pages"][PAGE]["documentObjects"][OBJECT]
    history(scene,"undo")
    assert scene.load()["scene"]["pages"][PAGE]["documentObjects"][OBJECT] == locked
    # Replay does not reapply today's lock policy to previously saved complete frames.
    commands = deepcopy(scene.load()["scene"]["commands"][:scene.load()["scene"]["historyCursor"]])
    commands.append({"operation":"set_object_frame","pageId":PAGE,"targetType":"document_object",
                     "targetId":OBJECT,"frame":{**before,"width":.17}})
    assert replay_documentation_commands(commands)[PAGE]["documentObjects"][OBJECT]["frame"]["width"] == .17


@pytest.mark.parametrize("kind,base", [
    ("illustrated_parts_manual","parts-manual"),
    ("operations_and_maintenance_manual","operations-manual"),
    ("work_instructions","work-instructions"),
    ("product_specification_sheet","specification-sheet"),
])
def test_workspace_objects_binding_route_receipt_and_undo(mmle_client,monkeypatch,kind,base):
    import server
    monkeypatch.setenv("INSPECTORPRO_DOCUMENTATION_RICH_TEXT","off")
    host = server._DocumentationAgentHost()
    url = "/api/"+base+"/MMLE-50D/documentation-scene"
    first = mmle_client.get(url).json()
    page_id = first["document"]["pages"][0]["pageId"]
    ids = ["document-object-p4a2-a","document-object-p4a2-b"]
    for key in ids:
        current = mmle_client.get(url).json()
        response = mmle_client.post(url+"/commands",json={"baseRevision":current["revision"],
            "sourceRevision":current["scene"]["sourceRevision"],"manualPlanRevision":current["scene"]["manualPlanRevision"],
            "operation":"add_object","pageId":page_id,"targetType":"document_object","targetId":key,"documentObject":value(key)})
        assert response.status_code == 200,response.text
        # Supervisor: a command's answer carries the binding the next read gives (no second read by the page).
        assert response.json()["objectBinding"] == mmle_client.get(url).json()["objectBinding"]
        assert key in response.json()["objectBinding"]["pages"][page_id]["objects"]
    for step in ("undo","redo"):
        current = mmle_client.get(url).json()
        moved = mmle_client.post(url+"/"+step,json={"baseRevision":current["revision"],
            "sourceRevision":current["scene"]["sourceRevision"],"manualPlanRevision":current["scene"]["manualPlanRevision"]})
        assert moved.status_code == 200,moved.text
        assert moved.json()["objectBinding"] == mmle_client.get(url).json()["objectBinding"]
    before = mmle_client.get(url).json()
    binding = before["objectBinding"]
    expected_pages = {p["pageId"] for p in before["document"]["pages"] if p.get("documentationObjects")}
    assert set(binding["pages"]) == expected_pages
    for page in expected_pages:
        read = host.read_document_objects("MMLE-50D",kind,[page])
        assert {k:binding[k] for k in binding if k!="pages"} == {k:read[k] for k in binding if k!="pages"}
        row = read["pages"][0]
        assert binding["pages"][page] == {"orderHash":row["orderHash"],
            "objects":{item["objectId"]:item["objectHash"] for item in row["objects"]}}
    reread = mmle_client.get(url).json()
    assert reread["document"]["documentRevision"] == before["document"]["documentRevision"]
    assert reread["scene"] == before["scene"]
    op = {"operation":"set_object_frame","pageId":page_id,"objectId":ids[0],
          "expectedObjectHash":binding["pages"][page_id]["objects"][ids[0]],"x":.3}
    old_order = before["scene"]["pages"][page_id]["objectOrder"]
    new_order = [key for key in old_order if key!=ids[0]]+[ids[0]]
    args = {k:binding[k] for k in ("documentId","sourceRevision","manualPlanRevision","sceneRevision")}
    args.update(expectedRevision=binding["revision"],requestId="workspace-objects",operations=[op,{
        "operation":"set_object_order","pageId":page_id,"order":new_order,
        "expectedOrderHash":binding["pages"][page_id]["orderHash"]}])
    route = "/api/documentation/"+kind+"/MMLE-50D/objects"
    response = mmle_client.post(route,json=args)
    assert response.status_code == 200,response.text
    receipt = response.json()["receipt"]
    assert len(receipt["operationResults"]) == 2
    current = mmle_client.get(url).json()
    entry = current["scene"]["commands"][-1]
    assert entry["actor"] == entry["change"]["actor"] == "user"
    assert all(c["actor"]=="user" for c in entry["commands"])
    assert mmle_client.post(route,json=args).json()["receipt"] == receipt
    assert mmle_client.get(url).json()["scene"] == current["scene"]
    bad = mmle_client.post(route,json={**args,"requestId":"stale-objects","operations":[op]})
    assert bad.json()["error"] == "content_hash_mismatch"
    host.undo_document_change("MMLE-50D",kind,{"documentId":receipt["documentId"],"changeId":receipt["changeId"],
        "expectedRevision":receipt["revision"],"requestId":"undo-workspace-objects"})
    assert mmle_client.get(url).json()["scene"]["pages"][page_id] == before["scene"]["pages"][page_id]


def test_workspace_objects_exact_body_and_only_object_operations(mmle_client,monkeypatch):
    import server
    called = []
    monkeypatch.setattr(server._DocumentationAgentHost,"apply_document_edits",lambda *a,**kw:called.append((a,kw)))
    valid = {"documentId":"document","expectedRevision":0,"requestId":"request","sourceRevision":"source",
             "manualPlanRevision":"plan","sceneRevision":"scene","operations":[
                 {"operation":"set_object_frame","pageId":PAGE,"objectId":OBJECT,"expectedObjectHash":"hash","x":.2}]}
    bad = [{k:v for k,v in valid.items() if k!=missing} for missing in valid]
    bad += [{**valid,"extra":True},{**valid,"operations":[]},{**valid,"operations":valid["operations"]*13},
            {**valid,"operations":None},{**valid,"operations":["bad"]},
            {**valid,"operations":[valid["operations"][0],{**valid["operations"][0],"pageId":"elsewhere"}]}]
    for kind in ("replace_text","set_slot_value","replace_range","create_table","modify_table","add_object","remove_object"):
        bad.append({**valid,"operations":[{**valid["operations"][0],"operation":kind}]})
    for body in bad:
        response = mmle_client.post("/api/documentation/"+KIND+"/MMLE-50D/objects",json=body)
        assert response.status_code != 200 and response.json()["error"]=="invalid_document_operation",response.text
    assert not called


def test_object_binding_early_read_needs_no_snapshot_or_picture(monkeypatch):
    import server
    from ai_inspector.documentation.commands import document_id
    document = {"documentType":"illustrated_parts_manual","sourceRevision":"source","manualPlanRevision":"plan",
        "documentRevision":"untouched","pages":[{"pageId":PAGE,"documentationObjects":{OBJECT:value(OBJECT,"image")}},
                                             {"pageId":"empty"}]}
    loaded = {"revision":"opaque","scene":{"assemblyNumber":"PROOF","editRevision":12}}
    monkeypatch.setattr(server,"_documentation_snapshot_payload",lambda *a,**kw:pytest.fail("snapshot"))
    monkeypatch.setattr(objects,"picture_info",lambda *a,**kw:pytest.fail("picture read"))
    before = deepcopy(document)
    result = server._documentation_editor_read(document,loaded,{})
    assert result["objectBinding"]["documentId"] == document_id("illustrated_parts_manual","PROOF")
    assert result["objectBinding"]["revision"] == 12
    assert set(result["objectBinding"]["pages"]) == {PAGE}
    assert document == before
