"""Sage's 3D shots, SV2 and SV3 (docs/sage-basic-shapes-plan.md, Part B), as far as the server goes: the app window's
answer to a capture request (sage_shots.py and its endpoint), the contact sheet Sage looks at, show_facility_views
waiting for the shots through its running step, the done step that does not glide twice, the shots block the chat
shows (folded when retaken), and its normalization. The window's own capture (SV1) is in the node workspace suite.
"""
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import shutil
import stat
import threading
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageFile
import pytest
from starlette.requests import Request as StarletteRequest

from ai_inspector.chat_content import normalize_chat_content_blocks
from ai_inspector.codex_runtime import progress
from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from ai_inspector.codex_runtime.progress import TurnProgress
from ai_inspector.facility_layout import sage_shots, sage_views as sv
from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost


def jpeg(width=640, height=360, colour=(90, 120, 160)):
    out = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(out, "JPEG", quality=80)
    return out.getvalue()


def zone(zone_id, label, x0, z0, x1, z1):
    return {"zoneId": zone_id, "label": label, "zoneType": "workcell", "floorElevation": 0.0, "anchors": [],
            "evidence": [], "boundary": [{"x": x0, "z": z0}, {"x": x1, "z": z0}, {"x": x1, "z": z1}, {"x": x0, "z": z1}]}


@pytest.fixture
def host(tmp_path):
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    host.ensure_bootstrap()
    principal = host.principal()
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    host.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"], [
        {"op": "add_zone", "zone": zone("zn-a06", "Assembly Cell A06", 14, 8, 38, 26)},
        {"op": "add_zone", "zone": zone("zn-yard", "Yard", 120, 8, 140, 26)}])
    try:
        yield host
    finally:
        host.close()


def gateway_for(host, turn, *, window=True):
    principal = host.principal()
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    gateway = FacilityEditGateway(host.agent_runtime, principal, {
        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}, turn_id=turn)
    gateway.edit_mode, gateway.app_window = "direct", window
    return gateway, saved


def window(host, answer=None, *, size=(640, 360)):
    """A step sink that plays the app window: on a running step that asks for shots it answers, as the page's POST
    does, with one JPEG per view (or ANSWER(capture) -> (report, images)); every step is kept."""
    steps = []

    async def sink(step):
        steps.append(json.loads(json.dumps(step)))
        capture = step.get("capture")
        if step.get("state") != "running" or not capture:
            return
        if answer is not None:
            got = answer(capture)
            if got is None:
                return  # a window that never answers
            report, images = got
        else:
            report = {"complete": True, "reason": None,
                      "shots": [{"index": index} for index in range(len(capture["views"]))]}
            images = [jpeg(*size) for _ in capture["views"]]
        host.sage_shots.answer(capture["requestId"], host.principal(), capture["siteId"], capture["layoutId"],
                               report, images)
    return steps, sink


def with_steps(gateway, sink):
    gateway.progress = TurnProgress(sink, names=gateway.layout_names, edit_mode="direct")
    return gateway


# ---------------------------------------------------------------- the round trip

def test_show_facility_views_takes_the_shots_in_the_app_window_and_gives_sage_one_contact_sheet(host):
    steps, sink = window(host)
    gateway, saved = gateway_for(host, "shots-turn")
    with_steps(gateway, sink)
    result = asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]}))
    assert result["ok"], result
    data = result["data"]
    assert data["pictures"].startswith("Attached: one contact sheet of 1 3D shot,") and "Look at it" in data["pictures"]
    assert data["shots"]["count"] == 1 and data["shots"]["views"] == 1
    assert data["liveView"]["captured"] is True and data["liveView"]["moves"] is True

    # The running step asked the window, with what captureSageViews needs and where to post the shots.
    asked = [step for step in steps if step.get("capture")]
    assert len(asked) == 1 and asked[0]["state"] == "running"
    assert asked[0]["label"] == "Taking 3D shots of Assembly Cell A06"
    capture = asked[0]["capture"]
    assert {key: capture[key] for key in ("siteId", "layoutId", "revision")} == {
        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}
    assert capture["views"][0]["camera"] == data["views"][0]["camera"]
    assert capture["url"] == f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/sage-shots/{capture['requestId']}"
    # The window moved its view itself: the done step does not glide again.
    done = steps[-1]
    assert done["state"] == "done" and done["label"] == "Took 1 3D shot of Assembly Cell A06" and "show" not in done
    assert progress.view_show(sv.TOOL, {"targetIds": ["zn-a06"]}, data) is None

    # Sage gets one JPEG beside the JSON; the chat a row of the saved shots.
    image = gateway.take_image()
    sheet = Image.open(io.BytesIO(base64.b64decode(image["data"])))
    assert image["mimeType"] == "image/jpeg" and sheet.format == "JPEG" and sheet.width == 640
    assert sheet.height == 360 + sage_shots.SHEET_LABEL
    block, ids = gateway.shot_sets[0]
    assert "zn-a06" in ids and block["type"] == "shots" and block["folded"] is False
    shot, = block["shots"]
    assert shot["url"] == capture["url"] + "/0.jpg" and shot["label"] == "Assembly Cell A06"
    assert shot["camera"] == data["views"][0]["camera"] and (shot["width"], shot["height"]) == (640, 360)
    assert normalize_chat_content_blocks([block]) == [block]
    assert (host.root / "sage-shots" / capture["requestId"] / "0.jpg").read_bytes()[:3] == b"\xff\xd8\xff"
    assert not staged(host, capture["requestId"]).exists(), "kept: moved out of .pending (final round 6)"
    assert host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID) == saved   # it only reads


def test_a_window_that_takes_no_shots_says_why_and_sage_is_told_it_has_not_seen_the_areas(host):
    steps, sink = window(host, lambda capture: ({"complete": False, "reason": "revision_differs", "shots": []}, []))
    gateway, _ = gateway_for(host, "refused-turn")
    with_steps(gateway, sink)
    data = asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]}))["data"]
    assert data["pictures"].startswith("None: the app window shows unsaved edits, a review or another revision")
    assert "never describe how they look" in data["pictures"] and "shots" not in data
    assert data["liveView"]["moves"] is False and data["liveView"]["say"].startswith("The shots stopped: the app")
    assert gateway.take_image() is None and gateway.shot_sets == []
    assert "show" not in steps[-1] and steps[-1]["label"] == "Found a view of Assembly Cell A06"


def test_a_window_that_never_answers_ends_the_wait_and_the_request(host, monkeypatch):
    monkeypatch.setattr(sage_shots, "WAIT_SECONDS", 0.2)
    steps, sink = window(host, lambda capture: None)
    gateway, _ = gateway_for(host, "silent-turn")
    with_steps(gateway, sink)
    data = asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]}))["data"]
    assert data["pictures"] == ("None: the app window did not send them in time. You have not seen these areas: "
                                "never describe how they look.")
    request_id = next(step for step in steps if step.get("capture"))["capture"]["requestId"]
    with pytest.raises(sage_shots.ShotsRefused):   # too late: the request is closed
        host.sage_shots.answer(request_id, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                               {"complete": True, "shots": [{"index": 0}]}, [jpeg()])


def test_without_a_window_or_steps_the_views_come_back_without_pictures(host):
    closed, _ = gateway_for(host, "no-window", window=False)
    with_steps(closed, window(host)[1])
    data = asyncio.run(closed.call(sv.TOOL, {"targetIds": ["zn-a06"]}))["data"]
    assert data["pictures"].startswith("None: no app window has this layout open") and "Tell the user" in data["pictures"]
    plain, _ = gateway_for(host, "no-steps")   # a turn without the chat's steps cannot ask the window
    data = asyncio.run(plain.call(sv.TOOL, {"targetIds": ["zn-a06"]}))["data"]
    assert data["pictures"].startswith("None: this chat cannot take 3D shots.")
    assert progress.view_show(sv.TOOL, {}, data)["cameraView"]["label"] == "Assembly Cell A06"  # it still glides


def test_a_set_retaken_later_in_the_turn_is_folded_and_another_area_stays_open(host):
    _, sink = window(host)
    gateway, _ = gateway_for(host, "fold-turn")
    with_steps(gateway, sink)

    async def turn():   # one turn: one event loop, as the pilot runs it
        return [await gateway.call(sv.TOOL, {"targetIds": ids}) for ids in (["zn-a06"], ["zn-yard"], ["zn-a06"])]

    assert all(result["ok"] for result in asyncio.run(turn()))
    assert [(block["shots"][0]["label"], block["folded"]) for block, _ in gateway.shot_sets] == [
        ("Assembly Cell A06", True), ("Yard", False), ("Assembly Cell A06", False)]


def test_the_contact_sheet_is_one_picture_at_most_1280_wide_numbered_in_two_columns():
    one = Image.open(io.BytesIO(sage_shots.contact_sheet([jpeg(1045, 532)], ["1  Dock"])))
    assert (one.width, one.height) == (1045, 532 + sage_shots.SHEET_LABEL)   # never scaled up
    three = Image.open(io.BytesIO(sage_shots.contact_sheet([jpeg(1280, 720)] * 3, ["1  A", "2  B", "3  C"])))
    assert three.width == 1280 + sage_shots.SHEET_GAP and three.height == 2 * (360 + sage_shots.SHEET_LABEL) + \
        sage_shots.SHEET_GAP


# ---------------------------------------------------------------- the window's answer, over HTTP

def test_the_window_posts_its_shots_once_to_its_request_and_the_chat_reads_them_back(host):
    store = host.sage_shots
    app = FastAPI()
    app.include_router(sage_shots.create_sage_shots_router(shots=store, principal_resolver=host.resolve_principal))
    client = TestClient(app)
    principal = host.principal()
    identity = {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": "rev-x"}
    views = [{"label": "A", "from": "south", "roofHidden": False, "camera": {}},
             {"label": "B", "from": "east", "roofHidden": True, "camera": {}}]
    base = f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/sage-shots"

    def post(url, report, images):
        return client.post(url, data={"report": json.dumps(report)},
                           files=[("shot", (f"shot-{i}.jpg", data, "image/jpeg")) for i, data in enumerate(images)])

    async def scenario():
        found = {}
        request_id, answer = store.open(principal, identity, views)
        url = f"{base}/{request_id}"
        found["other"] = (await asyncio.to_thread(post, f"/api/facility-layouts/{LOCAL_SITE_ID}/fl-other/sage-shots/"
                                                  f"{request_id}", {"shots": []}, [])).status_code
        found["ok"] = (await asyncio.to_thread(post, url, {"complete": False, "reason": "interrupted",
                                                           "shots": [{"index": 0}]}, [jpeg()])).json()
        found["answer"] = await asyncio.wait_for(answer, 5)
        found["again"] = (await asyncio.to_thread(post, url, {"shots": []}, [])).status_code
        # The chat reads only a kept set: the tool keeps it (one rename out of .pending) before showing it.
        found["unkept"] = (await asyncio.to_thread(client.get, f"{url}/0.jpg")).status_code
        found["kept"] = await store.keep(request_id, 5)
        store.close(request_id)
        bad_id, bad = store.open(principal, identity, views)
        found["bad"] = (await asyncio.to_thread(post, f"{base}/{bad_id}", {"shots": [{"index": 0}]},
                                                [b"\xff\xd8\xffnot a jpeg"])).status_code
        found["bad_answer"] = await asyncio.wait_for(bad, 5)
        big_id, big = store.open(principal, identity, views)
        found["big"] = (await asyncio.to_thread(post, f"{base}/{big_id}", {"shots": [{"index": 1}]},
                                                [jpeg(1300, 700)])).status_code
        await asyncio.wait_for(big, 5)
        order_id, order = store.open(principal, identity, views)
        found["order"] = (await asyncio.to_thread(post, f"{base}/{order_id}", {"shots": [{"index": 1}, {"index": 0}]},
                                                  [jpeg(), jpeg()])).status_code
        await asyncio.wait_for(order, 5)
        found["request_id"] = request_id
        return found

    found = asyncio.run(scenario())
    assert found["other"] == 404                       # another layout's URL cannot answer it
    assert found["ok"] == {"accepted": 1, "complete": False}
    assert found["answer"] == {"complete": False, "reason": "interrupted",
                               "shots": [{"index": 0, "width": 640, "height": 360}]}
    assert found["again"] == 404                       # answered once
    assert found["unkept"] == 404 and found["kept"] == "kept"
    assert found["bad"] == 422 and found["bad_answer"]["reason"] == "invalid"
    assert found["big"] == 422 and found["order"] == 422
    assert client.post(f"{base}/{'0' * 32}", data={"report": "{}"}).status_code == 404   # never asked

    shot = client.get(f"{base}/{found['request_id']}/0.jpg")
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/jpeg"
    assert shot.content[:3] == b"\xff\xd8\xff" and "immutable" in shot.headers["cache-control"]
    assert client.get(f"{base}/{found['request_id']}/1.jpg").status_code == 404   # no shot of view 2
    assert client.get(f"/api/facility-layouts/{LOCAL_SITE_ID}/fl-other/sage-shots/{found['request_id']}/0.jpg"
                      ).status_code == 404
    assert client.get(f"{base}/not-an-id/0.jpg").status_code == 404


# ---------------------------------------------------------------- round 2 (Codex on 7279e45)

def http_client(host):
    app = FastAPI()
    app.include_router(sage_shots.create_sage_shots_router(shots=host.sage_shots,
                                                           principal_resolver=host.resolve_principal))
    return TestClient(app)


IDENTITY = {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": "rev-x"}
VIEWS = [{"label": "A", "from": "south", "roofHidden": False, "camera": {}}]
BASE = f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/sage-shots"


def staged(host, request_id):
    """Where a set waits until the tool keeps it (final round 6)."""
    return host.root / "sage-shots" / sage_shots.PENDING / request_id


def nowhere(host, request_id):
    """Neither waiting in .pending nor kept."""
    return not staged(host, request_id).exists() and not (host.root / "sage-shots" / request_id).exists()


def huge_jpeg(width, height):
    """A small JPEG whose header says WIDTH x HEIGHT (its frame header patched): what a highly compressed big
    picture looks like before it is decoded."""
    data = bytearray(jpeg(16, 16))
    at = data.index(b"\xff\xc0")
    data[at + 5:at + 9] = height.to_bytes(2, "big") + width.to_bytes(2, "big")
    return bytes(data)


def test_round2_the_endpoint_reads_no_form_for_a_request_nobody_waits_for_and_at_most_2_mb_a_view(host, monkeypatch):
    """Finding 1: the request is checked before the form is read, and the body is cut off past one 2 MB JPEG per
    view (a form's file parts have no size limit of their own)."""
    parsed = []
    form = StarletteRequest.form

    def spy(self, *args, **kwargs):
        parsed.append(self.url.path)
        return form(self, *args, **kwargs)
    monkeypatch.setattr(StarletteRequest, "form", spy)
    client = http_client(host)
    big = b"\xff\xd8\xff" + b"0" * 3_000_000
    files = [("shot", ("shot-0.jpg", big, "image/jpeg"))]
    report = {"report": json.dumps({"complete": True, "shots": [{"index": 0}]})}
    assert client.post(f"{BASE}/{'0' * 32}", data=report, files=files).status_code == 404
    assert parsed == [], "nothing is read for a request nobody waits for"

    async def scenario():
        request_id, answer = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)
        status = (await asyncio.to_thread(client.post, f"{BASE}/{request_id}", data=report, files=files)).status_code
        got = await asyncio.wait_for(answer, 5)
        host.sage_shots.close(request_id)
        return status, got
    status, got = asyncio.run(scenario())
    assert status == 413 and parsed == [], "past one 2 MB JPEG for its one view, the form is never parsed"
    assert got == {"complete": False, "reason": "invalid", "shots": []}, "the tool stops waiting at once"

    # A body sent without its length (chunked) is cut off as it streams in.
    async def chunked():
        request_id, answer = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)
        body = (b"0" * 65536 for _ in range(64))
        status = (await asyncio.to_thread(client.post, f"{BASE}/{request_id}", content=body, headers={
            "content-type": "multipart/form-data; boundary=x"})).status_code
        got = await asyncio.wait_for(answer, 5)
        host.sage_shots.close(request_id)
        return status, got["reason"]
    assert asyncio.run(chunked()) == (413, "invalid") and parsed == []


def test_round2_a_shot_is_checked_for_size_before_it_is_decoded(host, monkeypatch):
    """Finding 2: a small JPEG that says it is 8000 x 8000 is refused from its header; a decompression bomb is a
    refused shot, not an error."""
    decoded = []
    load = ImageFile.ImageFile.load

    def spy(self):
        decoded.append(self.size)
        if self.size[0] > sage_shots.SHOT_WIDTH or self.size[1] > sage_shots.SHOT_HEIGHT:
            raise RuntimeError(f"decoded a {self.size} picture")
        return load(self)
    monkeypatch.setattr(ImageFile.ImageFile, "load", spy)

    async def scenario(data):
        request_id, answer = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)
        try:
            host.sage_shots.answer(request_id, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                                   {"complete": True, "shots": [{"index": 0}]}, [data])
        except sage_shots.ShotsRefused as exc:
            refused = (exc.status, str(exc))
        else:
            refused = None
        got = await asyncio.wait_for(answer, 5)
        host.sage_shots.close(request_id)
        return refused, got["reason"]
    assert len(huge_jpeg(8000, 8000)) < 2_000_000
    assert asyncio.run(scenario(huge_jpeg(8000, 8000))) == ((422, "Each shot is at most 1280 x 720."), "invalid")
    assert asyncio.run(scenario(huge_jpeg(30000, 30000)))[0][0] == 422
    assert decoded == [], "nothing too big was decoded"
    assert asyncio.run(scenario(jpeg()))[0] is None and decoded == [(640, 360)]


def test_round2_shots_the_tool_stopped_waiting_for_while_they_were_stored_are_not_kept(host, monkeypatch):
    """Finding 3: the request stays open while its shots are checked and stored, so a tool that times out or is
    cancelled meanwhile gets none: they are deleted, and the window is told."""
    decoding, release = threading.Event(), threading.Event()
    load = ImageFile.ImageFile.load

    def held(self):
        decoding.set()
        release.wait(5)
        return load(self)
    monkeypatch.setattr(ImageFile.ImageFile, "load", held)
    folder = host.root / "sage-shots"

    async def scenario():
        request_id, answer = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)
        posting = asyncio.create_task(asyncio.to_thread(
            host.sage_shots.answer, request_id, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
            {"complete": True, "shots": [{"index": 0}]}, [jpeg()]))
        await asyncio.to_thread(decoding.wait, 5)
        host.sage_shots.close(request_id)   # the tool's wait ended while the shot decoded
        release.set()
        try:
            await posting
        except sage_shots.ShotsRefused as exc:
            refused = (exc.status, exc.code)
        else:
            refused = None
        await asyncio.sleep(0.05)
        return request_id, refused, answer.result() if answer.done() else None
    request_id, refused, answered = asyncio.run(scenario())
    assert refused == (410, "sage_shots_expired")
    assert host.sage_shots.wait_idle(5), "deletes run in the store's files thread"
    assert nowhere(host, request_id), "no orphaned JPEG or set.json"
    assert answered == {"complete": False, "reason": "closed", "shots": []},         "nothing is handed to a tool that stopped waiting: its wait is closed (final round 7)"

    # Stored, then the wait ends without taking them (a timeout at the same moment, a cancel): close deletes them;
    # shots the tool took (keep) stay for the chat.
    monkeypatch.setattr(ImageFile.ImageFile, "load", load)

    async def stored(keep):
        request_id, answer = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)
        host.sage_shots.answer(request_id, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                               {"complete": True, "shots": [{"index": 0}]}, [jpeg()])
        await asyncio.wait_for(answer, 5)
        if keep:
            assert await host.sage_shots.keep(request_id, 5) == "kept"
        host.sage_shots.close(request_id)
        assert host.sage_shots.wait_idle(5)
        return (folder / request_id / "0.jpg").exists(), staged(host, request_id).exists()
    assert asyncio.run(stored(False)) == (False, False) and asyncio.run(stored(True)) == (True, False)


def test_round2_with_no_time_left_in_the_turn_the_window_is_not_asked_and_it_is_told_the_wait(host):
    """Finding 5: the wait is the turn's time left less 15 s for the reply, with no 1 s floor; none left, no ask."""
    steps, sink = window(host)
    gateway, _ = gateway_for(host, "late-turn")
    with_steps(gateway, sink)
    gateway.deadline = time.monotonic() + 15.0
    began = time.monotonic()
    data = asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]}))["data"]
    assert time.monotonic() - began < 0.5
    assert data["pictures"].startswith("None: this turn had no time left to take 3D shots.")
    assert not [step for step in steps if step.get("capture")] and host.sage_shots._pending == {}

    steps, sink = window(host)
    gateway, _ = gateway_for(host, "short-turn")
    with_steps(gateway, sink)
    gateway.deadline = time.monotonic() + 20
    assert asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]}))["ok"]
    capture = next(step for step in steps if step.get("capture"))["capture"]
    assert 4000 < capture["waitMs"] <= 5000, "the window is told how long the tool waits"


def test_round2_the_live_view_is_reported_from_the_capture_however_many_shots_came(host, monkeypatch):
    """Finding 6: only a complete capture ends on the main view with Back; Back after the first shot, a failure or
    no answer at all never tells Sage the view is there."""
    def back_after_one(capture):
        return {"complete": False, "reason": "interrupted", "shots": [{"index": 0}]}, [jpeg()]
    steps, sink = window(host, back_after_one)
    gateway, _ = gateway_for(host, "back-turn")
    with_steps(gateway, sink)
    data = asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06", "zn-yard"]}))["data"]
    assert len(data["views"]) == 2 and data["shots"]["count"] == 1
    live = data["liveView"]
    assert live["moves"] is False and "to" not in live
    assert live["say"] == ("The shots stopped: the user pressed Back, left the 3D view or changed the layout while the "
                           "shots were taken. Say so in one short sentence; do not say where the user's 3D view is.")
    assert progress.view_show(sv.TOOL, {}, data) is None, "and the done step does not glide"

    # Every shot sent, but the window says it did not end complete (Back after the last copy): not on the view.
    def all_but_stopped(capture):
        return ({"complete": False, "reason": "interrupted", "shots": [{"index": 0}, {"index": 1}]},
                [jpeg(), jpeg()])
    steps, sink = window(host, all_but_stopped)
    gateway, _ = gateway_for(host, "late-back-turn")
    with_steps(gateway, sink)
    data = asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06", "zn-yard"]}))["data"]
    assert data["shots"]["count"] == 2 and data["liveView"]["moves"] is False

    monkeypatch.setattr(sage_shots, "WAIT_SECONDS", 0.2)
    steps, sink = window(host, lambda capture: None)
    gateway, _ = gateway_for(host, "silent-turn")
    with_steps(gateway, sink)
    data = asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]}))["data"]
    assert data["liveView"]["moves"] is False and "glides" not in data["liveView"]["say"], "no move on a timeout"
    assert data["liveView"]["say"].startswith("The shots stopped: the app window did not send them in time.")


def test_round2_shot_links_of_the_longest_ids_are_kept_and_malformed_shots_are_dropped_quietly():
    """Finding 7: site and layout ids of 128 characters (each at most 3 when percent-encoded) make links up to 837
    characters (837 at most); malformed shots are dropped, never an error."""
    request_id = "ab" * 16
    plain = sage_shots.shots_url("s" * 128, "l" * 128, request_id) + "/0.jpg"
    encoded = sage_shots.shots_url("s" + ":" * 127, "l" + ":" * 127, request_id) + "/5.jpg"
    assert (len(plain), len(encoded)) == (329, 837)
    for url in (plain, encoded):
        block, = normalize_chat_content_blocks([{"type": "shots", "shots": [{"label": "A", "url": url}]}])
        assert block["shots"][0]["url"] == url
    assert normalize_chat_content_blocks([{"type": "shots", "shots": [{"label": "A", "url": encoded + "x"}]}]) == []
    huge = 10 ** 400
    for shots in (5, True, "abc", {"url": plain}, [None, 5, "x", {"label": "A", "url": 5}]):
        assert normalize_chat_content_blocks([{"type": "shots", "shots": shots}]) == [], shots
    block, = normalize_chat_content_blocks([{"type": "shots", "shots": [{"label": "A", "url": plain, "width": huge,
        "camera": {"position": {"x": huge, "y": 5, "z": 0}, "target": {"x": 0, "y": 0, "z": 0}, "fov": 50}}]}])
    assert block["shots"][0]["camera"] is None and "width" not in block["shots"][0]


# ---------------------------------------------------------------- round 3 (Codex on d6f632a): every exit cleans up

def test_round3_asking_the_window_and_waiting_for_it_share_one_cutoff(host):
    """Finding 2: a step sink that blocks while the capture is asked for cannot eat the 15 s kept for the reply."""
    steps = []

    async def blocked(step):
        steps.append(json.loads(json.dumps(step)))
        if step.get("capture"):
            await asyncio.sleep(3)
    gateway, _ = gateway_for(host, "blocked-turn")
    with_steps(gateway, blocked)
    gateway.deadline = time.monotonic() + 16.0
    began = time.monotonic()
    data = asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]}))["data"]
    assert time.monotonic() - began < 2.0, "the publish counts against the same cutoff as the wait"
    assert data["pictures"].startswith("None: the app window did not send them in time.")
    assert host.sage_shots._pending == {}


def test_round3_shots_are_kept_only_once_sages_picture_and_the_chat_row_are_made(host, monkeypatch):
    """Finding 3: a contact sheet that fails, or a cancel while it is made, leaves no stored shots, no picture and
    no chat row."""
    def broken(images, labels):
        raise OSError("the picture could not be read")
    monkeypatch.setattr(sage_shots, "contact_sheet", broken)
    steps, sink = window(host)
    gateway, _ = gateway_for(host, "sheet-turn")
    with_steps(gateway, sink)
    result = asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]}))
    request_id = next(step for step in steps if step.get("capture"))["capture"]["requestId"]
    assert result["ok"] is False
    assert host.sage_shots.wait_idle(5), "deletes run in the store's files thread"
    assert nowhere(host, request_id), "no orphaned shots"
    assert gateway.take_image() is None and gateway.shot_sets == []

    started = threading.Event()

    def slow(images, labels):
        started.set()
        time.sleep(0.3)
        raise OSError("not reached in time")
    monkeypatch.setattr(sage_shots, "contact_sheet", slow)
    steps, sink = window(host)
    gateway, _ = gateway_for(host, "cancel-turn")
    with_steps(gateway, sink)

    async def scenario():
        task = asyncio.create_task(gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]}))
        await asyncio.to_thread(started.wait, 5)
        task.cancel()   # Stop while the contact sheet is made
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    request_id = next(step for step in steps if step.get("capture"))["capture"]["requestId"]
    assert host.sage_shots.wait_idle(5), "deletes run in the store's files thread"
    assert nowhere(host, request_id)
    assert gateway.take_image() is None and gateway.shot_sets == [] and host.sage_shots._pending == {}


def test_round3_every_way_out_of_the_endpoint_answers_the_request_once(host, monkeypatch):
    """Finding 4: a shot sent as text, or any error in the endpoint, ends the tool's wait at once (invalid) and the
    request cannot be answered again."""
    client = http_client(host)
    report = {"report": json.dumps({"complete": True, "shots": [{"index": 0}]})}

    async def scenario():
        request_id, answer = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)
        url = f"{BASE}/{request_id}"
        status = (await asyncio.to_thread(client.post, url, data=dict(report, shot="not-a-file"))).status_code
        got = await asyncio.wait_for(answer, 2)
        again = (await asyncio.to_thread(client.post, url, data=report,
                                         files=[("shot", ("shot-0.jpg", jpeg(), "image/jpeg"))])).status_code
        host.sage_shots.close(request_id)
        return status, got["reason"], again
    assert asyncio.run(scenario()) == (422, "invalid", 404)

    def boom(*args, **kwargs):
        raise RuntimeError("an error in the endpoint")

    async def failing():
        request_id, answer = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)
        monkeypatch.setattr(host.sage_shots, "answer", boom)
        with pytest.raises(RuntimeError):
            await asyncio.to_thread(client.post, f"{BASE}/{request_id}", data=report,
                                    files=[("shot", ("shot-0.jpg", jpeg(), "image/jpeg"))])
        got = await asyncio.wait_for(answer, 2)
        host.sage_shots.close(request_id)
        return got["reason"]
    assert asyncio.run(failing()) == "invalid"


# ---------------------------------------------------------------- final round (Codex on 8f1b252..c93bc2f)

def test_final_an_error_while_the_shots_are_stored_answers_the_wait_and_leaves_no_partial_files(host, monkeypatch):
    """Finding 1: a write that fails part way (a full disk writing set.json) resolves the tool's wait as failed and
    removes what it wrote; the request cannot be answered again."""
    def half_write(request_id, pending, shots):
        folder = host.sage_shots.pending_root / request_id
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "0.jpg").write_bytes(shots[0]["data"])
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(host.sage_shots, "_write", half_write)

    async def scenario():
        request_id, answer = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)
        with pytest.raises(OSError):
            host.sage_shots.answer(request_id, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                                   {"complete": True, "shots": [{"index": 0}]}, [jpeg()])
        got = await asyncio.wait_for(answer, 2)
        with pytest.raises(sage_shots.ShotsRefused):
            host.sage_shots.answer(request_id, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                                   {"complete": True, "shots": [{"index": 0}]}, [jpeg()])
        host.sage_shots.close(request_id)
        return request_id, got
    request_id, got = asyncio.run(scenario())
    assert got == {"complete": False, "reason": "failed", "shots": []}
    assert host.sage_shots.wait_idle(5), "deletes run in the store's files thread"
    assert nowhere(host, request_id), "no partial files"


def test_final_reading_the_shots_and_making_the_contact_sheet_count_against_the_cutoff(host, monkeypatch):
    """Finding 2: shots that come just before the cutoff, with a slow contact sheet, are not kept or shown: the tool
    answers at the cutoff without pictures and deletes them."""
    real = sage_shots.contact_sheet

    def slow(images, labels):
        time.sleep(2.5)
        return real(images, labels)
    monkeypatch.setattr(sage_shots, "contact_sheet", slow)
    steps, sink = window(host)
    gateway, _ = gateway_for(host, "slow-sheet-turn")
    with_steps(gateway, sink)
    gateway.deadline = time.monotonic() + 16.0

    async def turn():
        began = time.monotonic()
        result = await gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]})
        return result, time.monotonic() - began
    result, seconds = asyncio.run(turn())
    assert seconds < 2.0, "it answers at the cutoff, not when the contact sheet is done"
    data = result["data"]
    assert data["pictures"].startswith("None: the shots came too late to look at in this turn.")
    assert "shots" not in data and gateway.take_image() is None and gateway.shot_sets == []
    request_id = next(step for step in steps if step.get("capture"))["capture"]["requestId"]
    assert host.sage_shots.wait_idle(5), "deletes run in the store's files thread"
    assert nowhere(host, request_id)


# ---------------------------------------------------------------- final round 2 (Codex on c93bc2f..a82c4c6)

def test_final2_shots_still_being_read_at_the_cutoff_are_deleted_once_the_read_is_done(host, monkeypatch):
    """The read the tool stopped waiting for still holds a shot open, and Windows cannot delete an open file: the
    shots go as soon as that read is done, and the tool still answers at its cutoff."""
    shots_root = (host.root / "sage-shots").resolve()
    real = Path.read_bytes
    reading = threading.Event()

    def slow_read(self):
        if self.suffix == ".jpg" and shots_root in self.resolve().parents:
            with open(self, "rb") as handle:
                reading.set()
                time.sleep(2.5)
                return handle.read()
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", slow_read)
    steps, sink = window(host)
    gateway, _ = gateway_for(host, "held-read-turn")
    with_steps(gateway, sink)
    gateway.deadline = time.monotonic() + 16.0

    async def turn():
        began = time.monotonic()
        result = await gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]})
        return result, time.monotonic() - began
    result, seconds = asyncio.run(turn())   # returns once the read has finished too
    assert seconds < 2.0, "the tool answers at its cutoff"
    assert result["data"]["pictures"].startswith("None: the shots came too late to look at in this turn.")
    assert reading.is_set()
    request_id = next(step for step in steps if step.get("capture"))["capture"]["requestId"]
    assert host.sage_shots.wait_idle(5), "deletes run in the store's files thread"
    assert nowhere(host, request_id), "deleted once the read was done"
    assert host.sage_shots._reading == {} and host.sage_shots._abandoned == set()


def test_final2_shots_another_program_holds_open_are_deleted_by_the_next_request_and_kept_shots_never(host):
    """A delete that fails (a viewer or a virus scan holds a shot open) leaves the set in .pending; a later request
    deletes it once it is old enough. Kept shots have left .pending and stay, however old."""
    shot = {"complete": True, "shots": [{"index": 0}]}

    async def scenario():
        kept_id, kept_answer = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)
        host.sage_shots.answer(kept_id, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID, shot, [jpeg()])
        await asyncio.wait_for(kept_answer, 5)
        assert await host.sage_shots.keep(kept_id, 5) == "kept"
        host.sage_shots.close(kept_id)
        request_id, _ = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)
        host.sage_shots.answer(request_id, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID, shot, [jpeg()])
        folder = staged(host, request_id)
        with open(folder / "0.jpg", "rb"):
            host.sage_shots.close(request_id)   # Sage stopped waiting; the shot cannot be deleted yet
            assert host.sage_shots.wait_idle(5)
            left = folder.exists()
        old = time.time() - 2 * sage_shots.SWEEP_AFTER_SECONDS
        for path in (host.root / "sage-shots" / kept_id, folder):
            os.utime(path, (old, old))
        later, _ = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)
        host.sage_shots.close(later)
        return kept_id, folder, left
    kept_id, folder, left = asyncio.run(scenario())
    assert left, "the open file kept the folder (Windows), in .pending"
    for _ in range(100):   # the sweep runs in the files thread (final rounds 3 and 4)
        if not folder.exists():
            break
        time.sleep(0.05)
    assert not folder.exists(), "the next request deleted it"
    assert (host.root / "sage-shots" / kept_id / "0.jpg").is_file(), "kept shots stay"


# ---------------------------------------------------------------- final round 3 (Codex on 3ce0b30)

def test_final3_the_sweep_never_runs_on_the_event_loop_and_one_runs_at_a_time(host, monkeypatch):
    """Finding 1: opening a request starts the backstop sweep in its own thread and does not wait for it (the tool's
    cutoff is running); requests opened while it runs start no second one."""
    lock = threading.Lock()
    running, most, threads = [0], [0], []

    def slow_sweep():
        with lock:
            running[0] += 1
            most[0] = max(most[0], running[0])
            threads.append(threading.get_ident())
        time.sleep(0.5)
        with lock:
            running[0] -= 1
    monkeypatch.setattr(host.sage_shots, "_sweep", slow_sweep)

    async def scenario():
        began = time.monotonic()
        ids = [host.sage_shots.open(host.principal(), IDENTITY, VIEWS)[0] for _ in range(3)]
        took = time.monotonic() - began
        for request_id in ids:
            host.sage_shots.close(request_id)
        return threading.get_ident(), took
    loop_thread, took = asyncio.run(scenario())
    assert took < 0.2, "open() does not wait for the sweep"
    for _ in range(100):
        if threads and not running[0]:
            break
        time.sleep(0.05)
    assert threads and loop_thread not in threads, "the sweep runs off the event loop"
    assert most[0] == 1 and len(threads) == 1, "one sweep at a time"
    assert host.sage_shots._sweeping is False


def test_final3_a_partial_set_is_the_same_shots_for_sage_the_chat_and_the_kept_files(host, monkeypatch):
    """Finding 3 (by design, pinned): Back after the first of two shots keeps the partial set. The contact sheet
    Sage is shown, the chat's row and the files kept on disk are exactly the same shots, and the view did not
    move."""
    sheets = []
    real = sage_shots.contact_sheet

    def recorded(images, labels):
        sheet = real(images, labels)
        sheets.append((list(images), list(labels), sheet))
        return sheet
    monkeypatch.setattr(sage_shots, "contact_sheet", recorded)
    first = jpeg(colour=(200, 40, 40))

    def back_after_one(capture):
        return {"complete": False, "reason": "interrupted", "shots": [{"index": 0}]}, [first]
    steps, sink = window(host, back_after_one)
    gateway, _ = gateway_for(host, "partial-turn")
    with_steps(gateway, sink)
    data = asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06", "zn-yard"]}))["data"]
    request_id = next(step for step in steps if step.get("capture"))["capture"]["requestId"]
    views = data["views"]
    assert len(views) == 2 and data["shots"] == {"count": 1, "views": 2, "shownInChat": data["shots"]["shownInChat"]}
    assert data["liveView"]["moves"] is False and "to" not in data["liveView"]

    # What Sage is shown: one tile, the first view's shot, and the picture it gets is that sheet.
    (images, labels, sheet), = sheets
    assert images == [first] and len(labels) == 1 and labels[0].startswith("1  ")
    assert gateway.take_image()["data"] == base64.b64encode(sheet).decode("ascii")
    assert data["pictures"].startswith("Attached: one contact sheet of 1 3D shot,")
    assert data["pictures"].endswith(f"Views without a shot (the user pressed Back, left the 3D view or changed the "
                                     f"layout while the shots were taken): 2 {views[1]['label']}; you have not seen "
                                     f"them.")

    # The chat's row: the same one shot.
    (block, ids), = gateway.shot_sets
    assert [shot["url"].rsplit("/", 1)[1] for shot in block["shots"]] == ["0.jpg"]
    assert block["shots"][0]["label"] == views[0]["label"]

    # The kept files: the same one shot, byte for byte, and its record.
    folder = host.root / "sage-shots" / request_id
    assert sorted(path.name for path in folder.iterdir()) == ["0.jpg", "set.json"]
    assert not staged(host, request_id).exists()
    assert (folder / "0.jpg").read_bytes() == first
    assert [shot["index"] for shot in json.loads((folder / "set.json").read_bytes())["shots"]] == [0]


# ---------------------------------------------------------------- final round 4 (Codex on 5f7122d)

def test_final4_no_shots_are_deleted_on_the_event_loop(host, monkeypatch):
    """Finding 1: a delete (a slow disk, a virus scan) never holds up the tool. close() only drops the request;
    the files go in the store's files thread, also when the shots outlast the contact-sheet cutoff."""
    real_rmtree = sage_shots.shutil.rmtree
    deleted_in = []

    def slow_rmtree(path, *args, **kwargs):
        if "sage-shots" in str(path):
            deleted_in.append(threading.get_ident())
            time.sleep(0.8)
        return real_rmtree(path, *args, **kwargs)
    monkeypatch.setattr(sage_shots.shutil, "rmtree", slow_rmtree)
    shot = {"complete": True, "shots": [{"index": 0}]}

    async def closing():
        request_id, answer = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)
        host.sage_shots.answer(request_id, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID, shot, [jpeg()])
        await asyncio.wait_for(answer, 5)
        began = time.monotonic()
        host.sage_shots.close(request_id)
        return threading.get_ident(), time.monotonic() - began, request_id
    loop_thread, took, request_id = asyncio.run(closing())
    assert took < 0.1, "close() does not wait for the delete"

    real_sheet = sage_shots.contact_sheet

    def slow_sheet(images, labels):
        time.sleep(1.5)
        return real_sheet(images, labels)
    monkeypatch.setattr(sage_shots, "contact_sheet", slow_sheet)
    steps, sink = window(host)
    gateway, _ = gateway_for(host, "slow-delete-turn")
    with_steps(gateway, sink)
    gateway.deadline = time.monotonic() + 16.0   # a 1 s cutoff

    async def turn():
        began = time.monotonic()
        result = await gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]})
        return threading.get_ident(), result, time.monotonic() - began
    turn_thread, result, seconds = asyncio.run(turn())
    assert seconds < 1.4, "the cleanup at the cutoff does not wait for the delete"
    assert result["data"]["pictures"].startswith("None: the shots came too late to look at in this turn.")
    turn_id = next(step for step in steps if step.get("capture"))["capture"]["requestId"]
    assert host.sage_shots.wait_idle(10)
    assert deleted_in and loop_thread not in deleted_in and turn_thread not in deleted_in, "never on the loop"
    assert nowhere(host, request_id)
    assert nowhere(host, turn_id)


# ---------------------------------------------------------------- final round 5 (Codex on 996b2e3)

def test_final5_the_app_stopping_gives_queued_deletes_a_bounded_wait(host, monkeypatch):
    """Finding 1: shutting the host down waits for queued deletes, at most about 2 s."""
    real_rmtree = sage_shots.shutil.rmtree
    slow = []

    def slow_rmtree(path, *args, **kwargs):
        if "sage-shots" in str(path):
            time.sleep(slow[0] if slow else 0.5)
        return real_rmtree(path, *args, **kwargs)
    monkeypatch.setattr(sage_shots.shutil, "rmtree", slow_rmtree)
    shot = {"complete": True, "shots": [{"index": 0}]}

    async def closed():
        request_id, answer = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)
        host.sage_shots.answer(request_id, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID, shot, [jpeg()])
        await asyncio.wait_for(answer, 5)
        host.sage_shots.close(request_id)
        return request_id
    request_id = asyncio.run(closed())
    host.close()
    assert nowhere(host, request_id), "the delete finished before the host closed"

    slow.append(8.0)
    host.sage_shots = sage_shots.SageShots(host.root / "sage-shots")   # the next start's store: a closed one takes none
    request_id = asyncio.run(closed())
    began = time.monotonic()
    host.close()
    assert time.monotonic() - began < 3.0, "but never waits long"


# ---------------------------------------------------------------- final round 6 (Codex on 5bb9252)
# Shots land in .pending. The tool keeps a set with one rename out of it, before Sage or the chat is shown the set, and
# only .pending is ever deleted from: losing a kept set is impossible by construction.

def test_final6_kept_sets_are_never_touched_however_old_even_locked_or_unmarked(host, monkeypatch):
    """Findings 1 and 2: the sweep looks only in .pending, so nothing kept is ever deleted. Not a set kept while no
    mark could be written (5bb9252 swept the shots it had shown), nor one whose set.json is locked while a store
    starts (5bb9252 skipped marking such a set, then swept it), however old."""
    msvcrt = pytest.importorskip("msvcrt")
    root = host.root / "sage-shots"
    real_touch = Path.touch

    def no_marks(self, *args, **kwargs):
        if "sage-shots" in str(self):
            raise PermissionError(13, "Access is denied")
        return real_touch(self, *args, **kwargs)
    monkeypatch.setattr(Path, "touch", no_marks)
    steps, sink = window(host)
    gateway, _ = gateway_for(host, "unmarked-turn")
    with_steps(gateway, sink)
    data = asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]}))["data"]
    assert data["pictures"].startswith("Attached: one contact sheet") and len(gateway.shot_sets) == 1, "shown"
    shown = root / next(step for step in steps if step.get("capture"))["capture"]["requestId"]
    monkeypatch.setattr(Path, "touch", real_touch)
    locked = root / ("ab" * 16)
    locked.mkdir()
    (locked / "0.jpg").write_bytes(jpeg())
    (locked / "set.json").write_bytes(json.dumps({"shots": [{"index": 0, "width": 640, "height": 360}]})
                                      .encode("utf-8"))
    assert host.sage_shots.wait_idle(5)

    def contents():
        return {folder.name: sorted((path.name, path.read_bytes()) for path in folder.iterdir())
                if folder.is_dir() else None for folder in (shown, locked)}
    before = contents()
    old = time.time() - 86400
    for folder in (shown, locked):
        os.utime(folder, (old, old))
    handle = open(locked / "set.json", "rb")
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1 << 16)   # nobody else can read it meanwhile
        stores = [host.sage_shots, sage_shots.SageShots(root)]      # the running app, and the next start

        async def requests():
            for store in stores:
                request_id, _ = store.open(host.principal(), IDENTITY, VIEWS)
                store.close(request_id)
        asyncio.run(requests())
        assert all(store.wait_idle(5) for store in stores)
    finally:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1 << 16)
        handle.close()
    assert contents() == before, "kept sets are never touched"


def test_final6_a_keep_that_fails_shows_nothing_and_the_set_never_leaves_pending(host, monkeypatch):
    """Sage's picture and the chat's row are published only once the set is kept. A rename that keeps failing (a
    virus scan holds a file) publishes nothing, Sage is told, and the set is deleted from .pending."""
    real_rename = os.rename

    def held(source, target, *args, **kwargs):
        if "sage-shots" in str(source):
            raise PermissionError(13, "The process cannot access the file because it is being used")
        return real_rename(source, target, *args, **kwargs)
    monkeypatch.setattr(os, "rename", held)
    steps, sink = window(host)
    gateway, _ = gateway_for(host, "unkept-turn")
    with_steps(gateway, sink)
    data = asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]}))["data"]
    assert data["pictures"] == ("None: the shots could not be saved. You have not seen these areas: never describe "
                                "how they look.")
    assert "shots" not in data and gateway.take_image() is None and gateway.shot_sets == []
    request_id = next(step for step in steps if step.get("capture"))["capture"]["requestId"]
    assert host.sage_shots.wait_idle(5)
    assert nowhere(host, request_id), "never kept, and deleted from .pending"


def test_final6_a_keep_slower_than_the_cutoff_shows_nothing_and_the_late_set_is_removed(host, monkeypatch):
    """Finding 3: keeping is waited for within the tool's cutoff, off the event loop. A rename that lands only after
    the cutoff publishes nothing, and the late set is deleted where the rename left it: nothing renames it back
    (final round 9). (5bb9252 wrote its mark on the loop, in the finally, after everything was shown.)"""
    real_rename, real_touch = os.rename, Path.touch
    renames = []

    def slow_rename(source, target, *args, **kwargs):
        if "sage-shots" in str(source):
            renames.append((Path(source).parent.name, Path(target).parent.name))
            time.sleep(1.5)
        return real_rename(source, target, *args, **kwargs)

    def slow_touch(self, *args, **kwargs):
        if "sage-shots" in str(self):
            time.sleep(1.5)
        return real_touch(self, *args, **kwargs)
    monkeypatch.setattr(os, "rename", slow_rename)
    monkeypatch.setattr(Path, "touch", slow_touch)
    steps, sink = window(host)
    gateway, _ = gateway_for(host, "late-keep-turn")
    with_steps(gateway, sink)
    gateway.deadline = time.monotonic() + 16.0   # a 1 s cutoff

    async def turn():
        began = time.monotonic()
        result = await gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]})
        return result, time.monotonic() - began
    result, seconds = asyncio.run(turn())
    assert seconds < 1.4, "the tool answers at its cutoff"
    data = result["data"]
    assert data["pictures"].startswith("None: the shots came too late to look at in this turn.")
    assert "shots" not in data and gateway.take_image() is None and gateway.shot_sets == []
    request_id = next(step for step in steps if step.get("capture"))["capture"]["requestId"]
    assert host.sage_shots.wait_idle(10)
    assert renames == [(sage_shots.PENDING, "sage-shots")], "one rename: nothing moves a late set back (round 9)"
    assert nowhere(host, request_id), "the late set was deleted where the rename left it"


def test_final6_links_where_a_set_could_be_are_never_followed(host, tmp_path, monkeypatch):
    """Finding 4: a junction or a symbolic link named like a set, in .pending or beside the kept sets, is never
    followed, at any age: the folders they point at, outside the store, are untouched. (5bb9252 wrote a mark into the
    folder a junction pointed at.)"""
    _winapi = pytest.importorskip("_winapi")
    monkeypatch.setattr(sage_shots, "SWEEP_AFTER_SECONDS", -60)   # every entry counts as old
    root = tmp_path / "shots-root"   # a store root no store has opened yet
    pending = root / sage_shots.PENDING
    pending.mkdir(parents=True)
    record = json.dumps({"shots": [{"index": 0, "width": 640, "height": 360}]}).encode("utf-8")
    targets = []
    for number, place in enumerate((pending, root, pending, root)):
        target = tmp_path / f"outside-{number}"
        target.mkdir()
        (target / "0.jpg").write_bytes(jpeg())
        (target / "set.json").write_bytes(record)
        link = place / (str(number) * 32)
        if number < 2:
            _winapi.CreateJunction(str(target), str(link))
        else:
            try:
                os.symlink(target, link, target_is_directory=True)
            except OSError:   # symbolic links need Developer Mode or an administrator on Windows
                continue
        targets.append(target)

    def contents():
        return {target.name: sorted((path.name, path.read_bytes()) for path in target.iterdir()) for target in targets}
    before = contents()
    store = sage_shots.SageShots(root)

    async def a_request():
        request_id, _ = store.open(host.principal(), IDENTITY, VIEWS)
        store.close(request_id)
    asyncio.run(a_request())
    assert store.wait_idle(5)
    assert len(targets) >= 2 and contents() == before, "never followed: the folders they point at are untouched"


def test_final6_queued_deletes_lost_when_the_app_stops_are_swept_from_pending_on_the_next_start(host, monkeypatch):
    """The files thread is a daemon: deletes still queued when the app stops (here behind one that hangs) are lost.
    Their sets are still in .pending, so the next start's sweep deletes them once they are old enough. A kept set is
    not in .pending and is never touched."""
    real_rmtree = sage_shots.shutil.rmtree
    stall, release = [], threading.Event()

    def stalling(path, *args, **kwargs):
        if Path(path).name in stall:
            release.wait(20)   # a delete that hangs (a slow disk)
        return real_rmtree(path, *args, **kwargs)
    monkeypatch.setattr(sage_shots.shutil, "rmtree", stalling)
    store, root = host.sage_shots, host.root / "sage-shots"
    shot = {"complete": True, "shots": [{"index": 0}]}

    async def stored():
        request_id, answer = store.open(host.principal(), IDENTITY, VIEWS)
        store.answer(request_id, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID, shot, [jpeg()])
        await asyncio.wait_for(answer, 5)
        return request_id

    async def before_the_app_stops():
        kept_id = await stored()
        assert await store.keep(kept_id, 5) == "kept"
        store.close(kept_id)
        first, second = await stored(), await stored()
        stall.append(first)
        store.close(first)    # its delete hangs in the files thread
        store.close(second)   # queued behind it
        return kept_id, first, second
    try:
        kept_id, first, second = asyncio.run(before_the_app_stops())
        time.sleep(0.3)
        assert staged(host, second).exists(), "still queued when the app stops"
        # The app stops; the queued delete is lost. The next start opens the same store later.
        old = time.time() - 3600
        for path in (root / kept_id, staged(host, second)):
            os.utime(path, (old, old))
        restarted = sage_shots.SageShots(root)

        async def next_request():
            request_id, _ = restarted.open(host.principal(), IDENTITY, VIEWS)
            restarted.close(request_id)
        asyncio.run(next_request())
        assert restarted.wait_idle(5)
        assert not staged(host, second).exists(), "the lost delete is swept from .pending on the next start"
        assert (root / kept_id / "0.jpg").is_file(), "the kept set stays"
        assert staged(host, first).exists(), "a set younger than the limit is left to its own delete"
    finally:
        release.set()


# ---------------------------------------------------------------- final round 7 (Codex on 5bb9252..4c274e3)

def test_final7_closing_the_app_answers_every_open_request_first_and_refuses_a_late_upload(host):
    """Finding 1: host.close() closes every open shots request before its bounded drain. Whatever waits on one is
    answered at once (closed, no shots), and a window that uploads afterwards is refused with 410, over HTTP too, and
    writes nothing. (4c274e3 only drained the file jobs: the waits stayed open and a late upload was accepted.)"""
    client = http_client(host)
    shot = {"complete": True, "shots": [{"index": 0}]}

    async def scenario():
        request_id, answer = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)
        late_id, late = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)
        await asyncio.to_thread(host.close)   # the app stops, from the server's shutdown
        after_id, after = host.sage_shots.open(host.principal(), IDENTITY, VIEWS)   # a request opened after it
        got = [await asyncio.wait_for(answer, 2), await asyncio.wait_for(late, 2), after.result()]
        host.sage_shots.close(after_id)
        response = await asyncio.to_thread(client.post, f"{BASE}/{request_id}", data={"report": json.dumps(shot)},
                                           files=[("shot", ("shot-0.jpg", jpeg(), "image/jpeg"))])
        try:
            host.sage_shots.answer(late_id, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID, shot, [jpeg()])
        except sage_shots.ShotsRefused as exc:
            refused = (exc.status, exc.code)
        else:
            refused = None
        return request_id, late_id, got, (response.status_code, response.json()["error"]["code"]), refused
    request_id, late_id, got, posted, refused = asyncio.run(scenario())
    assert got == [{"complete": False, "reason": "closed", "shots": []}] * 3, "answered at once, with no shots"
    assert posted == (410, "sage_shots_closed") and refused == (410, "sage_shots_closed"), "a late upload is refused"
    assert host.sage_shots.wait_idle(5)
    assert nowhere(host, request_id) and nowhere(host, late_id), "nothing was written"
    assert sage_shots.REASONS["closed"] == "the app was closing", "what Sage is told"


def test_final7_no_file_of_the_store_is_reached_through_a_link(host, tmp_path, monkeypatch):
    """Finding 2: every file access of the store goes through one containment check: no link, junction or other
    reparse point below the shots root is followed, and each path resolves where it should. 4c274e3 served a request
    id that was a junction to a folder with a matching set.json; and an upload wrote through a .pending junction, the
    contact sheet read through one, and a keep moved one. A real kept set is still served."""
    _winapi = pytest.importorskip("_winapi")
    client = http_client(host)
    principal = host.principal()
    root = host.root / "sage-shots"
    root.mkdir(parents=True, exist_ok=True)
    shot = {"complete": True, "shots": [{"index": 0}]}
    record = json.dumps({"tenantId": principal.tenant_id, "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID,
                         "revision": "rev-x", "views": VIEWS,
                         "shots": [{"index": 0, "width": 640, "height": 360}]}).encode("utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = jpeg(colour=(200, 30, 30))
    (outside / "0.jpg").write_bytes(secret)
    (outside / "set.json").write_bytes(record)

    def untouched():
        return sorted((path.name, path.read_bytes()) for path in outside.iterdir())
    before = untouched()

    # The chat's read: a request id that is a junction to a folder outside with a set.json that matches.
    junction_id = "c" * 32
    _winapi.CreateJunction(str(outside), str(root / junction_id))
    assert client.get(f"{BASE}/{junction_id}/0.jpg").status_code == 404, "a junction is never served"
    # A kept set whose JPEG is a symbolic link to a file outside, where such links can be made.
    linked_id = "d" * 32
    (root / linked_id).mkdir()
    (root / linked_id / "set.json").write_bytes(record)
    linked = root / linked_id / "0.jpg"
    try:
        os.symlink(outside / "0.jpg", linked)
        faked = False
    except OSError:   # symbolic links need Developer Mode or an administrator on Windows: the JPEG says it is one
        linked.write_bytes(secret)
        faked = True
    real_lstat = os.lstat

    def lstat(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if faked and Path(path) == linked:
            return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_file_attributes=0, st_mtime=info.st_mtime)
        return info
    with monkeypatch.context() as patched:
        patched.setattr(os, "lstat", lstat)
        assert client.get(f"{BASE}/{linked_id}/0.jpg").status_code == 404, "a linked JPEG is never served"
    real_id = "e" * 32
    (root / real_id).mkdir()
    (root / real_id / "set.json").write_bytes(record)
    (root / real_id / "0.jpg").write_bytes(jpeg())
    assert client.get(f"{BASE}/{real_id}/0.jpg").status_code == 200, "a real kept set still is"

    # The upload: .pending is a junction to a folder outside. Nothing is written there, and the tool is told.
    target = tmp_path / "pending-target"
    target.mkdir()
    pending = root / sage_shots.PENDING
    _winapi.CreateJunction(str(target), str(pending))

    async def upload():
        request_id, answer = host.sage_shots.open(principal, IDENTITY, VIEWS)
        with pytest.raises(OSError):
            host.sage_shots.answer(request_id, principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, shot, [jpeg()])
        got = await asyncio.wait_for(answer, 2)
        host.sage_shots.close(request_id)
        return got
    assert asyncio.run(upload())["reason"] == "failed"
    assert host.sage_shots.wait_idle(5)
    assert list(target.iterdir()) == [], "nothing written through the junction"
    os.rmdir(pending)   # the junction only

    # The contact sheet and the keep: a stored set swapped for a junction to the folder outside.
    async def swapped():
        request_id, answer = host.sage_shots.open(principal, IDENTITY, VIEWS)
        host.sage_shots.answer(request_id, principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, shot, [jpeg()])
        await asyncio.wait_for(answer, 2)
        folder = staged(host, request_id)
        shutil.rmtree(folder)
        _winapi.CreateJunction(str(outside), str(folder))
        try:
            with pytest.raises(OSError):
                host.sage_shots.images(request_id, [0])
            kept = await host.sage_shots.keep(request_id, 5)
        finally:
            host.sage_shots.close(request_id)
        return request_id, kept
    request_id, kept = asyncio.run(swapped())
    assert host.sage_shots.wait_idle(5)
    assert kept == "failed" and not os.path.lexists(root / request_id), "a junction is never kept"
    assert untouched() == before, "the folder outside is untouched"


# ---------------------------------------------------------------- final round 8 (Codex on 139b1e7)

def test_final8_closing_a_request_before_its_keep_renames_wins_and_after_that_the_keep_stands(host, monkeypatch):
    """A keep belongs to its request, and its rename is its commit point (final round 9). Before it, closing the
    request wins: the tool's close, or the app's shutdown from its first moment. Nothing is renamed, the set is
    deleted from .pending, and keep() says "closed". After it nothing takes the keep back: closed during the rename
    or right after it, the set stays kept and keep() says "kept" (round 8 took it back). 139b1e7 kept a set whose
    keep was queued behind another file job when the app closed."""
    root = host.root / "sage-shots"
    shot = {"complete": True, "shots": [{"index": 0}]}
    case = {"id": None, "during": False, "after": False}
    handed, renames = [], []
    real_settle, real_rename = sage_shots._settle, sage_shots.SageShots._rename

    def settle(loop, future, value):
        if isinstance(value, (bool, str)):   # the files thread's answer to a keep (a request's answer is a dict)
            handed.append((value, os.path.lexists(root / case["id"])))
            if case["after"]:
                store.close(case["id"])   # the request closes before keep() reads that answer
        real_settle(loop, future, value)

    def rename(source, target):
        renames.append(Path(target).parent.name)
        if case["during"] and Path(target).parent.name != sage_shots.PENDING:
            store.close(case["id"])   # the request closes while its set is renamed out of .pending
        return real_rename(source, target)
    monkeypatch.setattr(sage_shots, "_settle", settle)
    monkeypatch.setattr(sage_shots.SageShots, "_rename", staticmethod(rename))

    async def stored():
        request_id, answer = store.open(host.principal(), IDENTITY, VIEWS)
        store.answer(request_id, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID, shot, [jpeg()])
        await asyncio.wait_for(answer, 5)
        case["id"] = request_id
        return request_id

    async def queued(closing):
        """The keep waits in the files thread behind another job while CLOSING(request_id, release) closes its
        request; then the files thread goes on."""
        request_id = await stored()
        busy, release = threading.Event(), threading.Event()
        store._background(lambda: (busy.set(), release.wait(10)))
        assert await asyncio.to_thread(busy.wait, 5)
        keeping = asyncio.ensure_future(store.keep(request_id, 10))
        await asyncio.sleep(0.05)   # its rename is queued behind the busy job
        await asyncio.to_thread(closing, request_id, release)
        release.set()
        return request_id, await asyncio.wait_for(keeping, 10)

    def app_shutdown(request_id, release):   # the exact case: the app closes while the files thread is busy
        store.shutdown(0.1)

    def shutdown_begun(request_id, release):   # the keep comes to its rename once shutdown has begun, but before
        real_close = store.close                # shutdown has closed its request

        def later_close(closing_id):
            release.set()
            assert store.wait_idle(5)
            real_close(closing_id)
        monkeypatch.setattr(store, "close", later_close)
        store.shutdown(0.1)

    def tool_close(request_id, release):   # the tool's own close
        store.close(request_id)

    for closing in (app_shutdown, shutdown_begun, tool_close):
        store = host.sage_shots = sage_shots.SageShots(root)   # a fresh store each time: a closed one takes no shots
        handed.clear(), renames.clear()
        request_id, kept = asyncio.run(queued(closing))
        name = closing.__name__
        assert store.wait_idle(5)
        assert kept == "closed", f"never kept once closed ({name})"
        assert (handed, renames) == ([("closed", False)], []), f"never moved out of .pending ({name})"
        assert nowhere(host, request_id), f"deleted from .pending ({name})"

    async def keep():
        request_id = await stored()
        return request_id, await store.keep(request_id, 10)

    # Closed while its set is renamed, or right after the files thread kept it and before keep() reads that: past
    # the commit point nothing takes the keep back (round 8 moved the set back and said "closed").
    for moment in ("during", "after"):
        handed.clear(), renames.clear()
        case[moment] = True
        request_id, kept = asyncio.run(keep())
        case[moment] = False
        assert store.wait_idle(5)
        assert (kept, handed, renames) == ("kept", [("kept", True)], [root.name]), f"closed {moment} it: kept"
        assert (root / request_id / "0.jpg").is_file() and not staged(host, request_id).exists()

    # A keep asked for once its request is closed, or once the app is closing.
    assert asyncio.run(store.keep(request_id, 5)) == "closed"
    store.shutdown(1)

    async def after_shutdown():
        late_id, answer = store.open(host.principal(), IDENTITY, VIEWS)
        try:
            return (await answer)["reason"], await store.keep(late_id, 5)
        finally:
            store.close(late_id)
    assert asyncio.run(after_shutdown()) == ("closed", "closed")


# ---------------------------------------------------------------- final round 9 (Codex on 69d8496)
# A keep's rename is its commit point. Before it, closing the request or the tool giving up wins and nothing is
# renamed; after it nothing takes the keep back, so what the tool shows is what is kept. Nothing renames a set back.

async def stored_set(host):
    """A request whose one shot the window sent: stored in .pending, to be kept."""
    store = host.sage_shots
    request_id, answer = store.open(host.principal(), IDENTITY, VIEWS)
    store.answer(request_id, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                 {"complete": True, "shots": [{"index": 0}]}, [jpeg()])
    await asyncio.wait_for(answer, 5)
    return request_id


def test_final9_after_a_keeps_rename_the_app_closing_takes_nothing_back(host, monkeypatch):
    """Codex's interleaving: the app closes after the keep's rename and before the tool has its answer. Nothing takes
    the keep back: the set is kept, Sage and the chat are shown it, and the chat's link serves it, with the store
    closed and no request open. (69d8496 took the keep back here, but kept and showed the set on a close a moment
    later: kept and shown could disagree. Now they always agree.)"""
    real_settle = sage_shots._settle
    closing = []

    def settle(loop, future, value):
        if value == "kept" and not closing:   # the files thread's answer to the keep, past its rename
            closing.append(host.sage_shots.shutdown(0))   # the app closes now
        real_settle(loop, future, value)
    monkeypatch.setattr(sage_shots, "_settle", settle)
    steps, sink = window(host)
    gateway, _ = gateway_for(host, "closing-turn")
    with_steps(gateway, sink)
    data = asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]}))["data"]
    request_id = next(step for step in steps if step.get("capture"))["capture"]["requestId"]
    assert host.sage_shots.wait_idle(5) and host.sage_shots.closed and len(closing) == 1, "the app closed meanwhile"
    assert data["pictures"].startswith("Attached: one contact sheet of 1 3D shot"), "Sage is shown the set"
    assert gateway.take_image() is not None and len(gateway.shot_sets) == 1, "and the chat"
    kept = host.root / "sage-shots" / request_id
    assert (kept / "0.jpg").is_file() and (kept / "set.json").is_file() and not staged(host, request_id).exists()
    url = gateway.shot_sets[0][0]["shots"][0]["url"]
    assert http_client(host).get(url).status_code == 200, "the chat's link serves the kept set"


def test_final9_a_tool_that_gives_up_on_its_keep_shows_nothing_and_its_set_is_deleted_where_it_is(host, monkeypatch):
    """The tool giving up (a 0.3 s wait here) wins before the rename: nothing is renamed, and close() deletes the set
    from .pending. Once the rename has begun (it renames, or it has kept the set and the tool has not had the answer
    yet), it finishes, and one job then deletes the set where it landed: before close(), with nothing renamed back.
    Nobody was shown it. (69d8496 renamed it back to .pending, and a reverse rename that failed left it kept.)"""
    store, root = host.sage_shots, host.root / "sage-shots"
    real_rename, real_settle = sage_shots.SageShots._rename, sage_shots._settle
    renames, hold = [], {"queued": None, "rename": None, "answer": None}

    def rename(source, target):
        renames.append(Path(target).parent.name)
        if hold["rename"] is not None:
            hold["rename"].wait(10)   # a slow disk: the rename outlasts the tool's wait
        return real_rename(source, target)

    def settle(loop, future, value):
        if value == "kept" and hold["answer"] is not None:
            hold["answer"].wait(10)   # kept, but the answer reaches the tool only after its wait
        real_settle(loop, future, value)
    monkeypatch.setattr(sage_shots.SageShots, "_rename", staticmethod(rename))
    monkeypatch.setattr(sage_shots, "_settle", settle)

    async def given_up(where):
        request_id = await stored_set(host)
        release = threading.Event()
        if where == "queued":
            store._background(lambda: release.wait(10))   # the keep waits behind another file job
        hold[where] = release
        try:
            return request_id, await store.keep(request_id, 0.3)
        finally:
            release.set()
            hold[where] = None

    # Before the rename: never renamed, and the set waits in .pending for close().
    request_id, kept = asyncio.run(given_up("queued"))
    assert kept == "late" and store.wait_idle(5)
    assert renames == [] and staged(host, request_id).exists(), "never renamed"
    store.close(request_id)
    assert store.wait_idle(5) and nowhere(host, request_id), "deleted from .pending by close()"
    # While it renames, and once it has kept the set: deleted where it landed, before close().
    for where in ("rename", "answer"):
        renames.clear()
        request_id, kept = asyncio.run(given_up(where))
        assert kept == "late" and store.wait_idle(5)
        assert renames == [root.name] and nowhere(host, request_id), f"deleted where it landed ({where})"
        store.close(request_id)


def test_final9_a_failed_rename_says_failed_and_deletes_the_set_at_once(host, monkeypatch):
    """Past the commit point the rename's result stands. One that fails (Windows holds a file past the retries) says
    "failed", and the set is deleted from .pending at once, before close(). (69d8496 left it there for close().)"""
    monkeypatch.setattr(sage_shots.SageShots, "_rename", staticmethod(lambda source, target: False))
    store = host.sage_shots

    async def scenario():
        request_id = await stored_set(host)
        return request_id, await store.keep(request_id, 5)
    request_id, kept = asyncio.run(scenario())
    assert kept == "failed" and store.wait_idle(5)
    assert nowhere(host, request_id), "deleted from .pending at once"
    store.close(request_id)


def test_final9_the_keeps_rename_is_the_only_one_and_nothing_renames_a_set_back():
    """One rename moves a set, out of .pending into the kept sets: nothing takes a keep back by renaming it again.
    (69d8496's _move_back could fail its reverse rename and leave a set kept that nobody saw.)"""
    source = Path(sage_shots.__file__).read_bytes().decode("utf-8")
    assert "_move_back" not in source
    assert source.count("self._rename(") == 1 and "self._rename(source, self.root / request_id)" in source


def answered_in_time_then_held(monkeypatch, deadline):
    """Final round 10, Codex's ordering: the files thread answers the keep "kept" within its cutoff, and on the loop
    another ready callback, queued right behind that answer, holds the loop until 0.3 s past DEADLINE (a list, [when],
    on time.monotonic()). So the keep's future resolves in time, and the keep goes on only after its deadline.
    Returns the times the answer resolved the keep's future."""
    real_settle, resolved = sage_shots._settle, []

    def resolve(future, value):
        sage_shots._resolve(future, value)
        resolved.append(time.monotonic())

    def hold():
        time.sleep(max(0.0, deadline[0] - time.monotonic()) + 0.3)

    def settle(loop, future, value):
        if value != "kept":
            return real_settle(loop, future, value)

        def queue():   # both from the loop itself, so nothing runs between the answer and the hold
            loop.call_soon(resolve, future, value)
            loop.call_soon(hold)
        loop.call_soon_threadsafe(queue)
    monkeypatch.setattr(sage_shots, "_settle", settle)
    return resolved


def test_final10_a_keep_that_goes_on_past_its_deadline_is_late_and_its_set_is_deleted(host, monkeypatch):
    """Codex's finding: the rename answers "kept" within the cutoff, but another ready callback holds the loop past
    it before keep() goes on. keep() checks its deadline once its wait is over: "late", so the tool shows nothing,
    and the give-up deletes the set its rename kept, where it landed. (c5cf053 trusted wait_for: "kept" after the
    deadline, and the gateway published.)"""
    store, deadline = host.sage_shots, []
    resolved = answered_in_time_then_held(monkeypatch, deadline)

    async def scenario():
        request_id = await stored_set(host)
        deadline.append(time.monotonic() + 1.0)
        return request_id, await store.keep(request_id, 1.0)
    request_id, kept = asyncio.run(scenario())
    assert resolved and resolved[0] < deadline[0], "the rename answered within the cutoff"
    assert kept == "late", "past its deadline the keep is late, however its wait ended"
    assert store.wait_idle(5) and nowhere(host, request_id), "the set its rename kept is deleted where it landed"
    store.close(request_id)


def test_final10_the_tool_shows_nothing_when_its_keep_goes_on_past_the_cutoff(host, monkeypatch):
    """The gateway variant, with a 1 s cutoff: the keep's rename answers in time, and the loop is held past the
    cutoff before the tool goes on. Nothing is shown: no picture for Sage, no row in the chat, and pictures says the
    shots came too late. The set is deleted. (c5cf053 published the sheet and the chat block after the cutoff.)"""
    steps, sink = window(host)
    gateway, _ = gateway_for(host, "held-loop-turn")
    with_steps(gateway, sink)
    gateway.deadline = time.monotonic() + 16.0   # a 1 s cutoff: the turn keeps 15 s for the reply
    cutoff = [gateway.deadline - 15.0]
    resolved = answered_in_time_then_held(monkeypatch, cutoff)
    data = asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]}))["data"]
    request_id = next(step for step in steps if step.get("capture"))["capture"]["requestId"]
    assert resolved and resolved[0] < cutoff[0], "the rename answered within the cutoff"
    assert data["pictures"].startswith("None: the shots came too late to look at in this turn.")
    assert "shots" not in data and gateway.take_image() is None and gateway.shot_sets == [], "nothing is shown"
    assert host.sage_shots.wait_idle(5) and nowhere(host, request_id), "and the set its rename kept is deleted"


# ---------------------------------------------------------------- the chat block

def test_a_shots_block_links_only_to_saved_shots_and_keeps_each_views_camera():
    url = f"/api/facility-layouts/site-local/fl-a/sage-shots/{'ab' * 16}/0.jpg"
    camera = {"position": {"x": 20, "y": 5, "z": 10}, "target": {"x": 20, "y": 0.7, "z": 18}, "fov": 50}
    block, = normalize_chat_content_blocks([{"type": "shots", "siteId": "site-local", "layoutId": "fl-a",
        "revision": "r-1", "folded": True, "shots": [
            {"label": "Dock Door S1", "url": url, "from": "east", "roofHidden": True, "camera": camera,
             "width": 1045, "height": 532},
            {"label": "Below", "url": url, "camera": dict(camera, position={"x": 0, "y": 0, "z": 0})},
            {"label": "Elsewhere", "url": "https://example.com/a.jpg"},
            {"label": "", "url": url}]}])
    assert block == {"type": "shots", "siteId": "site-local", "layoutId": "fl-a", "revision": "r-1", "folded": True,
                     "shots": [{"label": "Dock Door S1", "url": url, "from": "east", "roofHidden": True,
                                "camera": {"position": {"x": 20.0, "y": 5.0, "z": 10.0},
                                           "target": {"x": 20.0, "y": 0.7, "z": 18.0}, "fov": 50.0},
                                "width": 1045, "height": 532},
                               {"label": "Below", "url": url, "from": "", "roofHidden": False, "camera": None}]}
    for bad in ("/api/facility-layouts/site-local/fl-a/sage-shots/xyz/0.jpg", url.replace("0.jpg", "6.jpg"),
                url.replace("/api/", "/static/"), url + "?x=1"):
        assert normalize_chat_content_blocks([{"type": "shots", "shots": [{"label": "A", "url": bad}]}]) == []
