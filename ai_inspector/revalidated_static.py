"""Static files that a tool can rewrite in place, keeping their URLs.

Model files under /generated/ keep their URL when they are rewritten (tools/factory02_light_models.py, a re-export),
and the catalog revision that names them does not change with their bytes. Starlette's StaticFiles sends them with no
Cache-Control, so the browser may reuse its copy without asking (heuristic caching): the desktop app showed a
rewritten stack-light.glb from its cache, unlit, even after a restart (2026-11-01).

So model files (.glb, .gltf) go out with Cache-Control: no-cache and an ETag of the file's modification time and size,
and a request whose If-None-Match names that ETag gets 304 with no body, as server.py's _assembly_model_file does.
The browser then asks again each time and gets the new bytes as soon as the file changes. Other files keep
Starlette's default.
"""
from __future__ import annotations

import os

from starlette.datastructures import Headers
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles

MODEL_SUFFIXES = (".glb", ".gltf")


def model_etag(stat_result: os.stat_result) -> str:
    """The file's modification time (ns) and size, as _assembly_model_file makes it."""
    return f'"{stat_result.st_mtime_ns:x}-{stat_result.st_size:x}"'


class RevalidatedStaticFiles(StaticFiles):
    """StaticFiles whose model files the browser revalidates each time (no-cache, ETag, 304 while unchanged)."""

    def file_response(self, full_path, stat_result, scope, status_code=200):
        if status_code != 200 or not os.fspath(full_path).lower().endswith(MODEL_SUFFIXES):
            return super().file_response(full_path, stat_result, scope, status_code)
        etag = model_etag(stat_result)
        headers = {"Cache-Control": "no-cache", "ETag": etag}
        asked = Headers(scope=scope).get("if-none-match") or ""
        if etag in [item.strip() for item in asked.split(",")]:
            return Response(status_code=304, headers=headers)
        return FileResponse(full_path, stat_result=stat_result, headers=headers)
