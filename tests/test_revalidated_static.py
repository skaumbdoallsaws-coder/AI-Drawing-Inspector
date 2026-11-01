"""Model files under /generated/ are rewritten in place, keeping their URLs (tools/factory02_light_models.py, a
re-export). The browser must ask again each time and get the new bytes once they change: the desktop app showed a
rewritten stack-light.glb from its cache (2026-11-01). No server import: the mount's class on a small app."""
from __future__ import annotations

import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from ai_inspector.revalidated_static import RevalidatedStaticFiles

URL = "/generated/industrial_assets/factory02_lights/stack-light.glb"


def test_a_model_file_is_asked_for_again_and_a_rewrite_comes_new(tmp_path):
    folder = tmp_path / "generated" / "industrial_assets" / "factory02_lights"
    folder.mkdir(parents=True)
    model = folder / "stack-light.glb"
    model.write_bytes(b"glTF amber only")
    (folder / "thumbnail.png").write_bytes(b"png")
    client = TestClient(Starlette(routes=[Mount("/generated", RevalidatedStaticFiles(directory=tmp_path / "generated"))]))

    first = client.get(URL)
    assert first.status_code == 200 and first.content == b"glTF amber only"
    assert first.headers["cache-control"] == "no-cache" and first.headers["etag"].startswith('"')
    again = client.get(URL, headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and again.content == b""
    assert again.headers["etag"] == first.headers["etag"] and again.headers["cache-control"] == "no-cache"
    assert client.head(URL).headers["etag"] == first.headers["etag"]

    # Rewritten (the green lamp added), even with an older modification time, as a copy that keeps the source's
    # time makes it: the browser's If-None-Match and If-Modified-Since no longer hold, so the new bytes come.
    old = model.stat()
    model.write_bytes(b"glTF amber + light-stack-green")
    os.utime(model, ns=(old.st_atime_ns, old.st_mtime_ns - 5 * 10**9))
    changed = client.get(URL, headers={"If-None-Match": first.headers["etag"],
                                       "If-Modified-Since": first.headers["last-modified"]})
    assert changed.status_code == 200 and changed.content == b"glTF amber + light-stack-green"
    assert changed.headers["etag"] != first.headers["etag"] and changed.headers["cache-control"] == "no-cache"
    # The same size, a new time: new too.
    model.write_bytes(b"glTF amber + light-stack-GREEN")
    os.utime(model, ns=(old.st_atime_ns, old.st_mtime_ns + 5 * 10**9))
    assert client.get(URL, headers={"If-None-Match": changed.headers["etag"]}).content.endswith(b"GREEN")

    # Other files keep Starlette's default; a missing model is a 404.
    picture = client.get("/generated/industrial_assets/factory02_lights/thumbnail.png")
    assert picture.status_code == 200 and "cache-control" not in picture.headers
    assert client.get("/generated/industrial_assets/factory02_lights/none.glb").status_code == 404


def test_the_server_serves_generated_with_it():
    source = (Path(__file__).resolve().parents[1] / "server.py").read_bytes().decode("utf-8")
    assert 'app.mount("/generated", RevalidatedStaticFiles(directory="generated"), name="generated")' in source
    assert 'app.mount("/generated", StaticFiles(' not in source
