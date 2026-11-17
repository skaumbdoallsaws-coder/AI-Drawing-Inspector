"""Scoped focus pictures for built drafts; cache files are outside frozen bundles."""
from hashlib import sha256
import os
import uuid

from . import model_import_files as disk
from .errors import FacilityLayoutError
from ..industrial_assets.model_builder import drafts
from ..industrial_assets.model_builder.errors import json_bytes, parse_json
from ..industrial_assets.model_builder.job_io import read_bytes
from ..industrial_assets.model_builder.protocol import RESULT_BYTES, GLB_BYTES
from ..industrial_assets.model_builder.imports import module
from ..industrial_assets.model_builder_runner import appearance_colors, run_focus
from ..industrial_assets.model_builder_bundle import FOLDER

VIEW_RESERVATION = 34 * 1024 * 1024
MAX_VIEWS = 8


def _select(result, focus):
    if type(focus) is not str or not 0 < len(focus) <= 512:
        raise FacilityLayoutError("model_focus_invalid", "Choose a built part key or name.")
    parts = result["parts"]
    selected = [i for i, part in enumerate(parts) if part["key"] == focus]
    if not selected:
        selected = [i for i, part in enumerate(parts) if part["name"] == focus]
    if not selected:
        keys = result.get("partMap", {}).get("entries", {}).get(focus, [])
        selected = [i for i, part in enumerate(parts) if part["key"] in keys]
    if not selected or len(selected) > 64:
        raise FacilityLayoutError("model_focus_invalid", "That part is not in the built model.")
    return [{"index": i, "name": parts[i]["name"]} for i in selected]


def focus_view(store, scope, draft_id, focus, private_asset_root, cancel=None):
    """Read frozen bytes under the store lock, render in a contained worker, cache per draft."""
    from .model_import_store import build_failure, missing
    store._authorize(scope)
    store.reconcile()
    lease = None
    try:
        with disk.coordinator(store.root):
            draft = store._draft(scope, draft_id)
            if draft.get("kind") != "build":
                raise FacilityLayoutError("model_focus_invalid", "Focus is available for built models only.")
            folder = store._folder(scope) / "drafts" / draft_id
            result = parse_json(read_bytes(folder, "result.json", RESULT_BYTES), RESULT_BYTES)
            drafts.result_matches(draft, result)
            selected = _select(result, focus)
            palette = appearance_colors()
            digest = sha256(json_bytes({"model": draft["outputSha256"], "parts": selected,
                                        "palette": palette, "renderer": 1})).hexdigest()[:24]
            view_folder = disk.safe(store._folder(scope) / "views" / draft_id)
            cached = disk.safe(view_folder / (digest + ".png"))
            if cached.is_file():
                picture = read_bytes(view_folder, cached.name, module("limits").PREVIEW_BYTES)
                module("pictures").validate_picture(picture, "preview")
                return picture
            receipt = store._receipt(scope, draft_id)
            if receipt is None:
                source = folder / "model.glb"
            else:
                if receipt["assetId"] != draft["assetId"]:
                    raise missing()
                source = disk.safe(private_asset_root / FOLDER / draft["assetId"] / "model.glb")
            payload = read_bytes(source.parent, source.name, GLB_BYTES)
            if sha256(payload).hexdigest() != draft["outputSha256"]:
                raise FacilityLayoutError("model_store_invalid", "The built model differs from its draft.", status_code=503)
            lease = store._claim(scope, "mbj-"+uuid.uuid4().hex[:24], VIEW_RESERVATION, cancel, kind="build")
        lease.check()
        picture = run_focus(lease.job, store._dependencies(), payload, selected, cancel_event=lease.cancel)
        lease.check()
        with disk.coordinator(store.root):
            store._authorize(scope)
            store._draft(scope, draft_id)
            lease.check()
            disk.mkdir(view_folder)
            if not cached.exists():
                with disk.safe(lease.job / "staged.png").open("xb") as stream:
                    stream.write(picture)
                os.replace(lease.job / "staged.png", cached)
            views = sorted((p for p in view_folder.glob("*.png") if p.is_file()),
                           key=lambda p: (p.stat().st_mtime_ns, p.name))
            for stale in views[:-MAX_VIEWS]:
                disk.remove(stale)
        return picture
    except Exception as error:
        if isinstance(error, FacilityLayoutError):
            raise
        raise build_failure(error) from None
    finally:
        if lease is not None:
            lease.release()
