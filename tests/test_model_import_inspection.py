"""Stable source primitive keys survive omission, metadata validation and paging."""
from copy import deepcopy
import json
import threading
import time

import pytest

from ai_inspector.facility_layout.model_import_store import ModelImportStore
from ai_inspector.industrial_assets.model_import.errors import ModelImportError
from ai_inspector.industrial_assets.model_import.inspection import validate_inspection, inspection_page
from tests.model_import_store_support import inspect_worker, layout_reader, scope, recipe, wait


def metadata(tmp_path, keys):
    (tmp_path / "source.bin").write_bytes(b"glTFfixture")
    (tmp_path / "request.json").write_bytes(b'{"name":"mixed.glb","storeMetadata":true}')
    summary = inspect_worker(tmp_path, tmp_path, cancel_event=threading.Event(), count=len(keys))
    value = json.loads((tmp_path / "inspection.json").read_bytes())
    for part, key in zip(value["parts"], keys):
        part["key"] = key
    summary["parts"] = deepcopy(value["parts"][:64])
    return summary, value


@pytest.mark.parametrize("keys", [["p0"], ["p1"], ["p1", "p3"], ["p9", "p10"], ["p4095"]])
def test_inspection_accepts_unique_increasing_source_keys_with_gaps(tmp_path, keys):
    summary, value = metadata(tmp_path, keys)
    assert validate_inspection(value, summary) == value
    pages = [inspection_page(summary, value, offset, 1) for offset in range(len(keys))]
    assert [p["parts"][0]["key"] for p in pages] == keys
    assert [p["partsOffset"] for p in pages] == list(range(len(keys)))
    assert pages[-1]["nextPartsOffset"] is None
    assert inspection_page(summary, value, len(keys), 1)["parts"] == []
    assert [p["key"] for p in summary["parts"]] == keys


@pytest.mark.parametrize("keys", [["p1", "p1"], ["p3", "p1"], ["p10", "p9"],
                                ["p01"], ["p4096"], ["p-1"], ["x1"]])
def test_inspection_rejects_duplicate_reversed_noncanonical_and_out_of_budget_keys(tmp_path, keys):
    summary, value = metadata(tmp_path, keys)
    with pytest.raises(ModelImportError) as caught:
        validate_inspection(value, summary)
    assert caught.value.code == "model_worker_failed"


def test_inspection_requires_summary_page_to_match_retained_source_identity(tmp_path):
    summary, value = metadata(tmp_path, ["p1", "p3"])
    summary["parts"][0]["key"] = "p0"
    with pytest.raises(ModelImportError) as caught:
        validate_inspection(value, summary)
    assert caught.value.code == "model_worker_failed"


def test_real_store_worker_omits_points_preserves_keys_and_selects_the_paged_part(tmp_path):
    from tests.model_import_test_support import Fixture

    fixture = Fixture()
    primitives = [fixture.triangle(mode=0),
                  fixture.triangle([[0, 0, 0], [1, 0, 0], [0, 1, 1]]),
                  fixture.triangle(mode=0),
                  fixture.triangle([[2, 0, 0], [3, 0, 0], [2, 1, 1]])]
    fixture.document["meshes"] = [{"name": "mixed primitives", "primitives": primitives}]
    fixture.document["nodes"] = [{"name": "mixed node", "mesh": 0}]
    fixture.document["scenes"] = [{"nodes": [0]}]
    instance = ModelImportStore(tmp_path, layout_reader=layout_reader)
    bound = scope()
    try:
        incoming = instance.begin_upload(bound, "mixed.glb")
        incoming.write(fixture.bytes())
        import_id = incoming.finish()["id"]
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            record = instance.get(bound, import_id)
            if record["state"] not in {"queued", "checking"}:
                break
            time.sleep(.02)
        assert record["state"] == "ready", record
        wait(instance, bound, import_id)
        assert record["summary"]["partsTotal"] == record["summary"]["triangles"] == 2
        assert [p["key"] for p in record["summary"]["parts"]] == ["p1", "p3"]
        assert "Point and line primitives were omitted." in record["warnings"]
        first, second = instance.inspect(bound, import_id, 0, 1), instance.inspect(bound, import_id, 1, 1)
        assert first["parts"][0]["key"] == "p1" and first["nextPartsOffset"] == 1
        assert second["parts"][0]["key"] == "p3" and second["nextPartsOffset"] is None
        assert instance.preview(bound, import_id).startswith(b"\x89PNG")
        # Source keys, not retained offsets, select geometry in the real prepare worker.
        draft = instance.prepare(bound, recipe(import_id, parts=[
            {"select": {"part": first["parts"][0]["key"]}, "drop": True},
            {"select": {"part": second["parts"][0]["key"]}, "name": "retained p3"}]))
        assert draft["partsTotal"] == draft["triangles"] == 1
        assert draft["parts"][0]["name"] == "retained p3"
    finally:
        instance.close()
