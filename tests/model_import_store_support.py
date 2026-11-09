"""Protocol-shaped fake worker outputs for store tests, never a substitute for reader/renderer tests."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import struct
import time
from types import SimpleNamespace
import zlib

from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.facility_layout.errors import FacilityNotFoundError
from ai_inspector.facility_layout.model_import_store import ModelImportStore, ModelImportScope
from ai_inspector.industrial_assets.model_import.credit import attribution, changes_text, credits_text
from ai_inspector.industrial_assets.model_import.identity import asset_identity
from ai_inspector.industrial_assets.model_import.recipe import normalize_recipe
from ai_inspector.industrial_assets.model_import.validation import json_bytes
from ai_inspector.industrial_assets.model_import.prepare_protocol import PUBLIC_FIELDS


def principal(user="u", tenant="tenant", role="editor", sites=("a", "b")):
    return FacilityPrincipal(user, tenant, sites, (role,))


def scope(user="u", tenant="tenant", role="editor", site="a", layout="layout"):
    return ModelImportScope(principal(user, tenant, role), site, layout)


def layout_reader(person, site, layout):
    if layout != "layout":
        raise FacilityNotFoundError("not_found", "Missing layout.")
    return {}


def png():
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    raw = (b"\0" + b"\xe0\xe0\xe0" * 768) * 768
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 768, 768, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG = png()
# Header-only worker stand-in: the actual encoder/pixel contracts live in test_model_import_preview.
FRAME = b"\x00\x00\x00\x9d\x01\x2a" + struct.pack("<HH", 256, 256)
WEBP = b"RIFF" + struct.pack("<I", 12 + len(FRAME)) + b"WEBPVP8 " + struct.pack("<I", len(FRAME)) + FRAME
LICENSE = {"class": "cc0", "title": "Fixture", "author": "Tester", "authorUrl": "", "sourceUrl": "",
           "license": "CC0", "licenseUrl": "", "excerpt": "Fixture only", "conflicts": []}
MATERIAL = {"name": "paint", "baseColor": [1, 1, 1, 1], "textureSize": None, "alphaMode": "OPAQUE",
            "alphaCutoff": .5, "emissive": [0, 0, 0], "doubleSided": False,
            "roughness": .8, "metalness": 0, "unlit": False}
BOUNDS = {"minimum": [-.5, 0, -.5], "maximum": [.5, 1, .5]}
SIZE = {"width": 1, "height": 1, "depth": 1}


def manifest(directory, filename, version, names):
    files = {n: {"bytes": (directory / n).stat().st_size, "sha256": sha256((directory / n).read_bytes()).hexdigest()}
             for n in names}
    (directory / filename).write_bytes(json_bytes({"schemaVersion": version, "files": files}))


def inspect_worker(job, dependency_root, *, cancel_event, count=1):
    source = (job / "source.bin").read_bytes()
    request = json.loads((job / "request.json").read_bytes())
    parts = [{**deepcopy(MATERIAL), "key": f"p{i}", "node": "node", "mesh": "mesh", "material": "paint",
              "triangles": 1, "bounds": deepcopy(BOUNDS)} for i in range(count)]
    summary = {"schemaVersion": 1, "name": request["name"], "format": "glb", "state": "ready", "refusal": None,
               "sourceBytes": len(source), "sourceSha256": sha256(source).hexdigest(), "triangles": count,
               "rawBounds": BOUNDS, "rawSize": SIZE,
               "unitGuesses": [{"unit": u, "metersPerUnit": f, "sizeMeters": {k: f for k in SIZE}}
                               for u, f in (("m", 1), ("cm", .01), ("mm", .001), ("in", .0254))],
               "upAxisHint": {"declared": "+Y", "generator": "", "bounds": BOUNDS, "suggested": "unknown", "note": ""},
               "licence": LICENSE, "partsTotal": count, "partsOffset": 0, "parts": parts[:64],
               "nextPartsOffset": 64 if count > 64 else None, "materials": [MATERIAL], "materialsTotal": 1,
               "flatTopHints": [], "warnings": []}
    for name, data in (("summary.json", json_bytes(summary)), ("inspection.json", json_bytes(
            {"parts": parts, "licence": LICENSE})), ("preview.png", PNG), ("cache.json", b"{}"), ("parts.npz", b"stub")):
        (job / name).write_bytes(data)
    manifest(job, "result.json", 3, ("summary.json", "inspection.json", "preview.png", "cache.json", "parts.npz"))
    return summary


def prepare_worker(source, recipe, destination, cancel, *, dependency_root, count=1, part_name="paint"):
    recipe = normalize_recipe(recipe)
    destination.mkdir()
    payload = b"Fake worker model; real GLB validation is tested separately."
    changes = changes_text(recipe)
    parts = [{"key": f"p{i}", "name": part_name, "triangles": 1} for i in range(count)]
    draft = {"schemaVersion": 1, "engineVersion": "model-import-1", "recipe": recipe,
             "sourceSha256": sha256(source.read_bytes()).hexdigest(), "outputSha256": sha256(payload).hexdigest(),
             "dimensions": SIZE, "triangles": count, "partsTotal": count,
             "parts": parts[:64], "nextPartsOffset": None,
             "materialsTotal": 1, "materials": [MATERIAL], "surfaces": [],
             "footprint": [[{"x": -.5, "z": -.5}, {"x": .5, "z": -.5}, {"x": .5, "z": .5}, {"x": -.5, "z": .5}]],
             "warnings": [], "attribution": attribution(LICENSE, recipe, changes), "changes": changes}
    draft["draftId"] = "md-" + asset_identity(draft)["sha256"][:24]
    while len(json_bytes({k: draft[k] for k in PUBLIC_FIELDS})) > 48 * 1024:
        draft["parts"].pop()
    draft["nextPartsOffset"] = len(draft["parts"]) if len(draft["parts"]) < count else None
    values = {"draft.json": json_bytes(draft), "model.glb": payload, "preview.png": PNG, "thumbnail.webp": WEBP,
              "parts.jsonl": b"".join(json_bytes(part) + b"\n" for part in parts),
              "CREDITS.txt": credits_text(draft["attribution"]).encode()}
    for name, data in values.items():
        (destination / name).write_bytes(data)
    manifest(destination, "manifest.json", 2, values)
    return {k: draft[k] for k in PUBLIC_FIELDS}


def store(tmp_path, **options):
    return ModelImportStore(tmp_path, layout_reader=layout_reader,
                            runtime=lambda: SimpleNamespace(dependency_root=Path(tmp_path)),
                            inspect_worker=options.pop("inspect_worker", inspect_worker),
                            prepare_worker=options.pop("prepare_worker", prepare_worker), **options)


def wait(store, bound, import_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        record = store.get(bound, import_id)
        if record["state"] not in ("queued", "checking"):
            # A terminal record is written just before lease cleanup.
            from ai_inspector.facility_layout import model_import_files as disk
            with disk.coordinator(store.root):
                active = any(v["importId"] == import_id for v in store._active())
            if not active:
                return record
        time.sleep(.01)
    raise AssertionError("worker did not reach a terminal record")


def upload(store, bound=None, data=b"glTFfixture", name="fixture.glb"):
    bound = bound or scope()
    incoming = store.begin_upload(bound, name, len(data))
    incoming.write(data)
    record = incoming.finish()
    return wait(store, bound, record["id"])


def recipe(import_id, **updates):
    return {"importId": import_id, "name": "Fixture", "category": "decor", **updates}
