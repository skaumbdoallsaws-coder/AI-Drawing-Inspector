"""Floor-plan import, FP1a: the artifact store, its HTTP routes and the layout underlay record
(docs/facility-floor-plan-import-plan.md, sections 4 and 10)."""
import json
import threading
from copy import deepcopy
from hashlib import sha256
from urllib.parse import quote

import pytest

from ai_inspector.facility_layout import floor_plan_store as store
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.floor_plan_alignment import to_layout
from ai_inspector.facility_layout.floor_plan_worker import FloorPlanParseError
from ai_inspector.facility_layout.floor_plan_references import (KEY, import_id_for, normalize_floor_plan_references,
                                                                normalize_reference)
from tests.floor_plan_dxf_fixtures import factory, hostile, unitless_segment
from tests.test_facility_layout_api import _client, _layout, _principal

BASE = "/api/facility-layouts/site-a/fl-api-cell"
IMPORTS = BASE + "/floor-plan-imports"


def started(tmp_path):
    client, service, shell, policy = _client(tmp_path)
    created = client.post("/api/facility-layouts/site-a", json={"layout": _layout(shell, policy)})
    assert created.status_code < 300, created.text
    return client, service


def upload(client, path, *, name="Factory plan.dxf", role="admin"):
    return client.post(IMPORTS, content=path.read_bytes(), headers={
        "Content-Type": "application/dxf", "X-Floor-Plan-Name": quote(name), "X-Test-Role": role})


def made(tmp_path, name="in"):
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    return folder


def code(response):
    return response.json()["error"]["code"]


def revision(service):
    return service.get_layout(_principal(), "site-a", "fl-api-cell")["revision"]


def saved(service):
    return service.get_layout(_principal(), "site-a", "fl-api-cell")["layout"]


def store_folder(service):
    return store.scope_folder(service.layout_repository.root / store.STORE_FOLDER, _principal(), "site-a")


def reference(imported, **changes):
    record, manifest = imported["import"], imported["manifest"]
    value = {
        "referenceId": "fp-main", "label": "Ground floor", "sourceName": record["sourceName"],
        "importId": record["importId"], "sourceSha256": record["sourceSha256"],
        "geometrySha256": record["geometrySha256"],
        "parserVersion": record["parserVersion"],
        "alignment": {"sourceOrigin": {"u": manifest["origin"][0], "v": manifest["origin"][1]},
                      "metersPerDrawingUnit": manifest["units"]["metersPerUnit"] or 1, "rotationDegrees": 0,
                      "translationMeters": {"x": 0, "z": 0}, "unitSource": "header", "confirmed": True,
                      "controlPoints": []},
        "layers": [{"layerId": layer["layerId"], "visible": True, "role": "reference"}
                   for layer in manifest["layers"]],
        "opacity": 0.35, "showIn3D": False,
    }
    value.update(changes)
    return value


def apply(client, service, *operations):
    return client.put(BASE, json={"baseRevision": revision(service), "operations": list(operations)})


def test_an_upload_is_authorized_read_stored_and_reused(tmp_path):
    client, service = started(tmp_path)
    drawing = factory(made(tmp_path), unit="millimeters")
    before = revision(service)
    assert upload(client, drawing, role="viewer").status_code == 403
    response = upload(client, drawing)
    assert response.status_code == 200, response.text
    first = response.json()
    record, manifest = first["import"], first["manifest"]
    assert first["reused"] is False
    assert record["sourceName"] == "Factory plan.dxf"
    assert record["bytes"] == drawing.stat().st_size
    assert record["importId"] == import_id_for(record["sourceSha256"], record["parserVersion"])
    assert record["parserVersion"].startswith("ezdxf-1.4.5+a")
    assert manifest["units"]["name"] == "millimeters" and "entities" not in manifest
    again = upload(client, drawing, name="copy.dxf").json()
    assert again["reused"] is True and again["import"] == record  # the first name stays

    status = client.get(IMPORTS + "/" + record["importId"], headers={"X-Test-Role": "viewer"})
    assert status.status_code == 200 and status.json() == {"import": record, "manifest": manifest}
    geometry = client.get(IMPORTS + "/" + record["importId"] + "/geometry", headers={"X-Test-Role": "viewer"})
    assert geometry.status_code == 200
    assert geometry.headers["x-content-type-options"] == "nosniff"
    assert geometry.headers["cache-control"] == "private, no-cache"
    body = geometry.json()
    assert body["source"]["sha256"] == record["sourceSha256"] and len(body["entities"]) > 10
    assert {key: value for key, value in body.items() if key != "entities"} == manifest

    assert client.get(IMPORTS + "/" + record["importId"] + "/source",
                      headers={"X-Test-Role": "viewer"}).status_code == 403
    original = client.get(IMPORTS + "/" + record["importId"] + "/source")
    assert original.status_code == 200 and original.content == drawing.read_bytes()
    assert original.headers["content-disposition"].startswith("attachment;")
    assert original.headers["content-type"] == "application/octet-stream"
    assert original.headers["x-content-type-options"] == "nosniff"

    other_site = "/api/facility-layouts/site-b/fl-api-cell/floor-plan-imports/" + record["importId"]
    assert client.get(other_site).status_code in (403, 404)
    for missing in ("fpi-" + "0" * 32, "not-an-import", "..%2F..%2Fsecrets"):
        assert client.get(IMPORTS + "/" + missing).status_code == 404
        assert client.get(IMPORTS + "/" + missing + "/geometry").status_code == 404
    assert client.get("/api/facility-layouts/site-a/no-such-layout/floor-plan-imports/"
                      + record["importId"]).status_code == 404

    folder = store_folder(service)
    assert [path.name for path in (folder / "sources").iterdir()] == [record["sourceSha256"] + ".dxf"]
    assert sorted(path.name for path in (folder / "geometry").iterdir()) == [
        record["geometrySha256"] + ".json", record["geometrySha256"] + ".manifest.json"]
    assert not list((folder / "uploads").iterdir()) and not list((folder / "jobs").iterdir())
    assert revision(service) == before  # importing changes no layout


def test_refused_uploads_leave_nothing_behind(tmp_path):
    client, service = started(tmp_path)
    files = hostile(made(tmp_path))
    for kind, expected in (("dwg", "dwg_file"), ("zip", "not_dxf"), ("truncated", "truncated"),
                           ("binary", "binary_dxf")):
        response = upload(client, files[kind])
        assert response.status_code == 422, (kind, response.text)
        assert code(response) == expected
    empty = client.post(IMPORTS, content=b"", headers={"Content-Type": "application/dxf"})
    assert empty.status_code == 422 and code(empty) == "floor_plan_empty"
    oversized = b"0\nSECTION\n" + b" " * store.MAX_UPLOAD_BYTES
    declared = client.post(IMPORTS, content=oversized, headers={"Content-Type": "application/dxf"})
    assert declared.status_code == 413 and code(declared) == "floor_plan_too_large"

    def chunks():
        for start in range(0, len(oversized), 1024 * 1024):
            yield oversized[start:start + 1024 * 1024]
    streamed = client.post(IMPORTS, content=chunks(), headers={"Content-Type": "application/dxf"})
    assert streamed.status_code == 413 and code(streamed) == "floor_plan_too_large"
    folder = store_folder(service)
    for kind in ("sources", "geometry", "imports", "uploads", "jobs"):
        assert not (folder / kind).exists() or not list((folder / kind).iterdir()), kind


def test_alignment_is_calculated_from_points_or_a_distance_and_not_saved(tmp_path):
    client, service = started(tmp_path)
    imported = upload(client, factory(made(tmp_path), unit="millimeters")).json()
    url = IMPORTS + "/" + imported["import"]["importId"] + "/alignment"
    before = revision(service)
    # A quarter turn: drawing +u runs along layout +z, the drawing's origin corner sits at (5, 5).
    controls = [{"source": {"u": u, "v": v}, "target": {"x": x, "z": z}}
                for (u, v), (x, z) in (((0, 0), (5, 5)), ((30000, 0), (5, 35)), ((30000, 20000), (-15, 35)))]
    fitted = client.post(url, json={"controlPoints": controls}, headers={"X-Test-Role": "viewer"})
    assert fitted.status_code == 200, fitted.text
    result = fitted.json()
    assert result["scale"] == "declared"
    assert result["alignment"]["metersPerDrawingUnit"] == 0.001
    assert result["alignment"]["rotationDegrees"] == pytest.approx(90)
    assert result["rmsMeters"] == pytest.approx(0, abs=1e-6)
    alignment = dict(result["alignment"], unitSource="header", confirmed=True, controlPoints=[])
    for control in controls:
        x, z = to_layout(alignment, control["source"]["u"], control["source"]["v"])
        assert (x, z) == pytest.approx((control["target"]["x"], control["target"]["z"]), abs=1e-6)

    held = client.post(url, json={"controlPoints": controls[:2], "metersPerDrawingUnit": 0.002}).json()
    assert held["scale"] == "held" and held["alignment"]["metersPerDrawingUnit"] == 0.002
    assert held["scaleRatio"] == pytest.approx(0.5) and held["maxResidualMeters"] > 1
    free = client.post(url, json={"controlPoints": controls[:2], "scale": "fit"}).json()
    assert free["alignment"]["metersPerDrawingUnit"] == pytest.approx(0.001)
    assert free["scaleRatio"] == pytest.approx(1)
    distance = client.post(url, json={"distance": {"a": {"u": 0, "v": 0}, "b": {"u": 30000, "v": 0},
                                                   "meters": 30}}).json()
    assert distance["metersPerDrawingUnit"] == pytest.approx(0.001) and distance["scaleRatio"] == pytest.approx(1)
    for body in ({}, {"controlPoints": controls[:1]}, {"controlPoints": controls, "distance": {}},
                 {"controlPoints": controls, "scale": "fit", "metersPerDrawingUnit": 0.001},
                 {"controlPoints": controls, "metersPerDrawingUnit": 0},
                 {"controlPoints": controls, "metersPerDrawingUnit": "0.001"},
                 {"distance": {"a": {"u": 0, "v": 0}, "b": {"u": 1, "v": 0}, "meters": 3}, "scale": "fit"},
                 {"controlPoints": controls, "scale": "guess"}, {"controlPoints": "nope"},
                 {"distance": {"a": {"u": 0, "v": 0}, "b": {"u": 0, "v": 0}, "meters": 3}},
                 {"controlPoints": [{"source": {"u": 0, "v": 0}, "target": {"x": 0, "z": 0}, "extra": 1}] * 2}):
        refused = client.post(url, json=body)
        assert refused.status_code == 422 and code(refused) == "invalid_floor_plan_alignment", body

    unitless = upload(client, unitless_segment(made(tmp_path, "unitless"))).json()
    unitless_url = IMPORTS + "/" + unitless["import"]["importId"] + "/alignment"
    refused = client.post(unitless_url, json={"controlPoints": controls[:2], "scale": "declared"})
    assert refused.status_code == 422 and code(refused) == "floor_plan_units_unresolved"
    assert client.post(unitless_url, json={"controlPoints": controls[:2]}).json()["scale"] == "fit"
    assert revision(service) == before


def test_the_underlay_is_saved_only_for_a_stored_drawing(tmp_path):
    client, service = started(tmp_path)
    imported = upload(client, factory(made(tmp_path), unit="millimeters")).json()
    value = reference(imported, opacity=0.333, layers=list(reversed(reference(imported)["layers"])))
    response = apply(client, service, {"op": "upsert_floor_plan_reference", "reference": value})
    assert response.status_code == 200, response.text
    stored = saved(service)["extensions"][KEY]
    assert stored == normalize_floor_plan_references({"version": 1, "references": [value]})
    assert stored["references"][0]["opacity"] == 0.33
    assert [layer["layerId"] for layer in stored["references"][0]["layers"]] == [
        layer["layerId"] for layer in imported["manifest"]["layers"]]

    invented = reference(imported, geometrySha256="e" * 64)
    parser = imported["import"]["parserVersion"]
    unknown_source = reference(imported, sourceSha256="d" * 64, importId=import_id_for("d" * 64, parser))
    response = apply(client, service, {"op": "upsert_floor_plan_reference", "reference": unknown_source})
    assert response.status_code == 422 and code(response) == "floor_plan_artifact_missing"
    response = apply(client, service, {"op": "upsert_floor_plan_reference", "reference": invented})
    assert response.status_code == 422 and code(response) == "floor_plan_artifact_missing"
    second = reference(imported, referenceId="fp-second")
    response = apply(client, service, {"op": "upsert_floor_plan_reference", "reference": second})
    assert response.status_code == 422 and code(response) == "floor_plan_reference_limit"
    hidden = reference(imported, opacity=0.8)
    hidden["layers"][0]["visible"] = False
    response = apply(client, service, {"op": "upsert_floor_plan_reference", "reference": hidden})
    assert response.status_code == 200, response.text
    assert saved(service)["extensions"][KEY]["references"][0]["layers"][0]["visible"] is False

    document = deepcopy(saved(service))
    document["extensions"][KEY]["references"][0]["opacity"] = 0.333
    whole = client.put(BASE, json={"baseRevision": revision(service), "layout": document})
    assert whole.status_code == 422 and code(whole) == "invalid_floor_plan_references"
    document["extensions"][KEY]["references"][0].update(opacity=0.5, geometrySha256="e" * 64)
    whole = client.put(BASE, json={"baseRevision": revision(service), "layout": document})
    assert whole.status_code == 422 and code(whole) == "floor_plan_artifact_missing"

    response = apply(client, service, {"op": "delete_floor_plan_reference", "referenceId": "fp-main"})
    assert response.status_code == 200, response.text
    assert KEY not in saved(service)["extensions"]
    response = apply(client, service, {"op": "delete_floor_plan_reference", "referenceId": "fp-main"})
    assert response.status_code == 422 and code(response) == "floor_plan_reference_missing"


def test_a_drawing_stored_for_one_site_or_tenant_is_not_found_from_another(tmp_path):
    client, service = started(tmp_path)
    imported = upload(client, factory(made(tmp_path))).json()
    root = service.layout_repository.root / store.STORE_FOLDER
    document = {"extensions": {KEY: {"version": 1, "references": [reference(imported)]}}}
    store.require_reference_artifacts(root, _principal(), "site-a", None, document)
    elsewhere = FacilityPrincipal(principal_id="principal-admin", tenant_id="tenant-b",
                                  allowed_site_ids=("site-a",), roles=("admin",))
    for principal, site in ((elsewhere, "site-a"), (_principal(), "site-b")):
        with pytest.raises(FacilityLayoutError) as error:
            store.require_reference_artifacts(root, principal, site, None, document)
        assert error.value.code == "floor_plan_artifact_missing"
    # A reference the change leaves as it was is not checked again: a lost drawing never blocks other edits.
    store.require_reference_artifacts(root, elsewhere, "site-a", document, document)


def test_the_reference_record_is_closed_and_normalized_once():
    digest = "a" * 64
    value = {"referenceId": "fp-main", "label": "  Ground\tfloor ", "sourceSha256": digest,
             "importId": import_id_for(digest, "ezdxf-1.4.5+a1"),
             "geometrySha256": "b" * 64, "parserVersion": "ezdxf-1.4.5+a1",
             "alignment": {"sourceOrigin": {"u": 1000.0000004, "v": 0}, "metersPerDrawingUnit": 0.001,
                           "rotationDegrees": 270, "translationMeters": {"x": 1, "z": 2},
                           "unitSource": "header", "confirmed": False, "controlPoints": []},
             "layers": [{"layerId": "L10", "visible": True, "role": "column"},
                        {"layerId": "L2", "visible": False, "role": "wall_faces"}],
             "opacity": 0.355, "showIn3D": False}
    normalized = normalize_reference(value)
    assert normalize_reference(deepcopy(normalized)) == normalized
    assert normalized["label"] == "Ground floor"
    assert [layer["layerId"] for layer in normalized["layers"]] == ["L2", "L10"]
    assert normalized["alignment"]["rotationDegrees"] == -90
    assert normalized["alignment"]["sourceOrigin"] == {"u": 1000.0, "v": 0.0}
    for change in ({"showIn3D": True}, {"extra": 1}, {"opacity": 0}, {"opacity": True}, {"opacity": float("nan")},
                   {"referenceId": "main"}, {"referenceId": "fp-Main"}, {"sourceSha256": "A" * 64},
                   {"parserVersion": "../x"}, {"label": " "}, {"label": "x" * 121},
                   {"importId": "fpi-" + "0" * 32}, {"parserVersion": "ezdxf-1.4.6+a1"},
                   {"layers": [{"layerId": "L1", "visible": True, "role": "safety_exit"}]},
                   {"layers": [{"layerId": "layer-1", "visible": True, "role": "reference"}]},
                   {"layers": [{"layerId": "L1", "visible": 1, "role": "reference"}]},
                   {"layers": [{"layerId": "L1", "visible": True, "role": "reference"}] * 2}):
        with pytest.raises(ValueError):
            normalize_reference({**value, **change})
    missing = dict(value)
    del missing["alignment"]
    with pytest.raises(ValueError):
        normalize_reference(missing)
    with pytest.raises(ValueError):
        normalize_floor_plan_references({"version": 1, "references": []})
    with pytest.raises(ValueError):
        normalize_floor_plan_references({"version": 2, "references": [value]})


def test_parsing_is_one_job_per_person_with_a_bounded_queue(monkeypatch):
    monkeypatch.setattr(store, "QUEUE_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(store, "MAX_WAITING_PARSES", 1)
    people = [FacilityPrincipal(principal_id=f"person-{n}", tenant_id="tenant-a", allowed_site_ids=("site-a",),
                                roles=("admin",)) for n in range(4)]
    release, holding = threading.Event(), []

    def hold(principal, ready):
        with store._parse_slot(principal):
            ready.set()
            release.wait(5)

    threads = []
    for principal in people[:store.MAX_PARALLEL_PARSES]:
        ready = threading.Event()
        thread = threading.Thread(target=hold, args=(principal, ready))
        thread.start()
        assert ready.wait(5)
        threads.append(thread)
    try:
        with pytest.raises(FacilityLayoutError) as busy:
            store.check_not_busy(people[0])
        assert busy.value.code == "floor_plan_import_busy" and busy.value.status_code == 429
        with pytest.raises(FacilityLayoutError) as busy:
            with store._parse_slot(people[0]):
                pass
        assert busy.value.code == "floor_plan_import_busy"
        # Both slots are taken: one more person waits and gives up after QUEUE_WAIT_SECONDS; with that one
        # waiting, the queue is full for anyone else.
        outcome = {}

        def wait_for_slot():
            try:
                with store._parse_slot(people[2]):
                    outcome["ran"] = True
            except FacilityLayoutError as error:
                outcome["error"] = error.code
        waiter = threading.Thread(target=wait_for_slot)
        waiter.start()
        for _ in range(100):
            with store._GATE.lock:
                if store._GATE.waiting:
                    break
            threading.Event().wait(0.01)
        with pytest.raises(FacilityLayoutError) as full:
            with store._parse_slot(people[3]):
                pass
        assert full.value.code == "floor_plan_import_queue_full" and full.value.status_code == 503
        waiter.join(5)
        assert outcome == {"error": "floor_plan_import_queue_full"}
    finally:
        release.set()
        for thread in threads:
            thread.join(5)
    assert not store._GATE.active and not store._GATE.waiting
    with store._parse_slot(people[0]):
        pass


DRAWING = b"0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n"
DIGEST = sha256(DRAWING).hexdigest()


def person(n):
    return FacilityPrincipal(principal_id=f"person-{n}", tenant_id="tenant-a", allowed_site_ids=("site-a",),
                             roles=("admin",))


def sent(tmp_path, name):
    """An upload as the route leaves it for import_drawing: the received bytes in a file of their own."""
    path = made(tmp_path, "upload-" + name) / "upload.part"
    path.write_bytes(DRAWING)
    return path


def reader(calls, *, entered=None, release=None, fail=None):
    """A stand-in for the worker: writes a geometry and a manifest into the job folder (or fails)."""
    def parse(source, job, *, source_sha256):
        calls.append(source_sha256)
        if entered is not None:
            entered.set()
        if release is not None:
            assert release.wait(5)
        if fail is not None:
            raise fail
        (job / "geometry.json").write_text(json.dumps({"source": {"sha256": source_sha256}, "entities": []}))
        (job / "manifest.json").write_text(json.dumps({"source": {"sha256": source_sha256}}))
        return {"geometryPath": str(job / "geometry.json"), "manifestPath": str(job / "manifest.json"),
                "seconds": 0.01, "peakMemoryBytes": 1}
    return parse


def kept(folder):
    return {kind: sorted(path.name for path in (folder / kind).iterdir()) if (folder / kind).is_dir() else []
            for kind in ("sources", "geometry", "imports", "jobs")}


def test_the_same_drawing_sent_by_two_people_at_once_is_read_once(tmp_path):
    root = tmp_path / "store"
    key = (str(store.scope_folder(root, person(0), "site-a")), DIGEST)
    calls, entered, release, results = [], threading.Event(), threading.Event(), {}
    parse = reader(calls, entered=entered, release=release)

    def send(n):
        results[n] = store.import_drawing(root, person(n), "site-a", sent(tmp_path, str(n)), DIGEST,
                                          len(DRAWING), f"plan-{n}.dxf", parse=parse)

    threads = [threading.Thread(target=send, args=(0,))]
    threads[0].start()
    try:
        assert entered.wait(5)
        threads.append(threading.Thread(target=send, args=(1,)))
        threads[1].start()
        for _ in range(500):  # the second person's request waits on the first's read of the same file
            with store._SOURCES.lock:
                if store._SOURCES.held.get(key, [None, 0])[1] == 2:
                    break
            threading.Event().wait(0.01)
        else:
            pytest.fail("the second import did not wait for the first")
        assert len(calls) == 1
    finally:
        release.set()
        for thread in threads:
            thread.join(5)
    assert len(calls) == 1
    assert results[0]["reused"] is False and results[1]["reused"] is True
    assert results[1]["import"] == results[0]["import"]  # the first record is kept, with its name
    assert results[0]["import"]["sourceName"] == "plan-0.dxf"
    assert not store._SOURCES.held and not store._GATE.active


def test_a_failed_import_removes_only_what_it_stored(tmp_path, monkeypatch):
    root = tmp_path / "store"
    folder = store.scope_folder(root, person(0), "site-a")
    nothing = {"sources": [], "geometry": [], "imports": [], "jobs": []}
    calls = []

    def send(name, parse):
        return store.import_drawing(root, person(0), "site-a", sent(tmp_path, name), DIGEST, len(DRAWING),
                                    "plan.dxf", parse=parse)

    # The reader cannot be run: the source it was handed goes again, and so does the upload.
    with pytest.raises(OSError):
        send("a", reader(calls, fail=OSError("no worker")))
    assert kept(folder) == nothing and not (tmp_path / "upload-a" / "upload.part").exists()

    # Writing the record fails after the source and the geometry were stored: all of it goes.
    write = store._write_atomic

    def failing(target, data):
        if target.parent.name == "imports":
            raise OSError("disk full")
        return write(target, data)
    monkeypatch.setattr(store, "_write_atomic", failing)
    with pytest.raises(OSError):
        send("b", reader(calls))
    monkeypatch.setattr(store, "_write_atomic", write)
    assert kept(folder) == nothing

    # A source stored before (read by an earlier reader version, say) stays when a new attempt fails.
    source = store.source_path(folder, DIGEST)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(DRAWING)
    with pytest.raises(FacilityLayoutError) as refused:
        send("c", reader(calls, fail=FloorPlanParseError("truncated", "The file ends early.")))
    assert refused.value.code == "truncated"
    assert kept(folder) == dict(nothing, sources=[DIGEST + ".dxf"])

    # A stored import whose source was lost since gets it back from the same bytes, without reading them again.
    first = send("d", reader(calls))
    assert first["reused"] is False
    read = len(calls)
    source.unlink()
    again = send("e", reader(calls))
    assert again["reused"] is True and again["import"] == first["import"] and len(calls) == read
    assert source.read_bytes() == DRAWING
    assert not store._SOURCES.held and not store._GATE.active
