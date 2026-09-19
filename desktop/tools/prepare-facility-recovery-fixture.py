"""Prepare a real, isolated manual-layout recovery fixture; never start an app.

Only explicit referenced layout/authority documents, catalog records, GLBs and
adjacent thumbnails are copied. Credentials, authority markers, transactions,
CAD sources and unrelated live library records are never traversed or copied.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import struct
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("facility_fixture_backend", Path(__file__).with_name("run-rendering-backend.py"))
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)
LAYOUT_ID = "fl-reference-manual-20260812"
MANIFEST_NAME = "facility-recovery-fixture.json"
CATALOG_PATH = "generated/industrial_assets/local_library/catalog.json"
HOST_PATH = "ai_inspector/facility_layout/host.py"
MAX_GLB_BYTES = 256 * 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024


def native(path: Path) -> Path:
    text = str(path.absolute())
    return Path("\\\\?\\" + text) if os.name == "nt" and not text.startswith("\\\\?\\") else path


def safe_path(root: Path, relative: str, *, must_exist: bool = True) -> Path:
    """Decode a relative local asset URL once, rejecting alternate authorities."""
    if not isinstance(relative, str) or not relative or len(relative) > 1800:
        raise ValueError("Fixture reference must be a bounded local relative path")
    parsed = urlsplit(relative)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("External or decorated fixture asset URLs are forbidden")
    decoded = unquote(parsed.path, errors="strict")
    if (decoded.startswith(("/", "\\")) or "\\" in decoded or ":" in decoded
            or "%" in decoded or any(ord(c) < 32 for c in decoded)):
        raise ValueError("Fixture asset path is not canonical and relative")
    if any(part in {"", ".", ".."} for part in decoded.split("/")):
        raise ValueError("Fixture asset path is not canonical")
    parts = PurePosixPath(decoded).parts
    if not parts or any(part in {".", ".."} or part.endswith((".", " ")) for part in parts):
        raise ValueError("Fixture asset path escapes the selected source")
    root = backend.no_links(root)
    path = root.joinpath(*parts)
    for item in (path, *path.parents):
        check = native(item)
        if check.is_symlink() or getattr(check, "is_junction", lambda: False)():
            raise ValueError("Fixture references must not traverse symbolic links or junctions")
        if item == root:
            break
    if must_exist and not native(path).is_file():
        raise ValueError(f"Required fixture file is missing: {decoded}")
    return path


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def read_json(path: Path):
    if native(path).stat().st_size > MAX_JSON_BYTES:
        raise ValueError("Fixture JSON exceeds the bounded size")
    return json.loads(native(path).read_bytes())


def sha256(path: Path) -> str:
    with native(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect_glb(path: Path) -> dict:
    """Validate embedded GLB2 structure and a reachable, nonempty mesh scene.

    This is structural inspection, not a renderer or a visual-quality claim.
    Binary POSITION ranges/counts are validated without loading entire meshes.
    """
    size = native(path).stat().st_size
    if size < 28 or size > MAX_GLB_BYTES:
        raise ValueError("GLB size is outside the supported fixture bounds")
    with native(path).open("rb") as stream:
        magic, version, declared = struct.unpack("<4sII", stream.read(12))
        if magic != b"glTF" or version != 2 or declared != size:
            raise ValueError("GLB header/version/declared size is invalid")
        chunks = []
        document = None
        offset = 12
        while offset < size:
            header = stream.read(8)
            if len(header) != 8:
                raise ValueError("GLB chunk header is truncated")
            length, kind = struct.unpack("<II", header)
            if length % 4 or offset + 8 + length > size:
                raise ValueError("GLB chunk bounds or alignment is invalid")
            if not chunks:
                if kind != 0x4E4F534A or length > MAX_JSON_BYTES:
                    raise ValueError("GLB must begin with a bounded JSON chunk")
                document = json.loads(stream.read(length))
            else:
                if kind != 0x004E4942 or len(chunks) != 1:
                    raise ValueError("Fixture GLBs require one embedded BIN chunk")
                stream.seek(length, 1)
            chunks.append((kind, length))
            offset += 8 + length
    if len(chunks) != 2 or not isinstance(document, dict) or document.get("asset", {}).get("version") != "2.0":
        raise ValueError("GLB must contain glTF2 JSON and binary geometry")
    for key in ("buffers", "images"):
        if any("uri" in item for item in document.get(key, [])):
            raise ValueError("Fixture GLB external/data URI dependencies are forbidden")
    buffers = document.get("buffers", [])
    if len(buffers) != 1 or not isinstance(buffers[0].get("byteLength"), int) or not 0 < buffers[0]["byteLength"] <= chunks[1][1]:
        raise ValueError("GLB embedded buffer length is invalid")
    views = document.get("bufferViews", [])
    for view in views:
        start, length = view.get("byteOffset", 0), view.get("byteLength")
        if (view.get("buffer") != 0 or not isinstance(start, int) or isinstance(start, bool)
                or not isinstance(length, int) or isinstance(length, bool) or start < 0 or length <= 0
                or start + length > buffers[0]["byteLength"]):
            raise ValueError("GLB bufferView is outside the embedded buffer")
    scenes, nodes, meshes, accessors = (document.get(k, []) for k in ("scenes", "nodes", "meshes", "accessors"))
    selected = document.get("scene", 0)
    if not isinstance(selected, int) or isinstance(selected, bool) or not 0 <= selected < len(scenes):
        raise ValueError("GLB default scene is invalid")
    pending = list(scenes[selected].get("nodes", []))
    if not pending:
        raise ValueError("GLB default scene contains no roots")
    visited, mesh_ids = set(), set()
    while pending:
        index = pending.pop()
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(nodes):
            raise ValueError("GLB scene references an invalid node")
        if index in visited:
            continue
        visited.add(index)
        node = nodes[index]
        pending.extend(node.get("children", []))
        if "mesh" in node:
            mesh = node["mesh"]
            if not isinstance(mesh, int) or isinstance(mesh, bool) or not 0 <= mesh < len(meshes):
                raise ValueError("GLB node references an invalid mesh")
            mesh_ids.add(mesh)
    primitives, positions = 0, 0
    for index in mesh_ids:
        for primitive in meshes[index].get("primitives", []):
            position = primitive.get("attributes", {}).get("POSITION")
            if not isinstance(position, int) or isinstance(position, bool) or not 0 <= position < len(accessors):
                raise ValueError("GLB primitive has no valid POSITION accessor")
            accessor = accessors[position]
            count, view_id, start = accessor.get("count"), accessor.get("bufferView"), accessor.get("byteOffset", 0)
            if (accessor.get("type") != "VEC3" or accessor.get("componentType") != 5126
                    or not isinstance(count, int) or isinstance(count, bool) or count < 3
                    or not isinstance(view_id, int) or isinstance(view_id, bool) or not 0 <= view_id < len(views)
                    or not isinstance(start, int) or isinstance(start, bool) or start < 0):
                raise ValueError("GLB POSITION accessor has no supported embedded geometry")
            view = views[view_id]
            stride = view.get("byteStride", 12)
            if not isinstance(stride, int) or stride < 12 or start + (count - 1) * stride + 12 > view["byteLength"]:
                raise ValueError("GLB POSITION accessor exceeds its bufferView")
            for bound in ("min", "max"):
                values = accessor.get(bound)
                if not isinstance(values, list) or len(values) != 3 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in values):
                    raise ValueError("GLB POSITION bounds are missing or nonfinite")
            if any(a > b for a, b in zip(accessor["min"], accessor["max"])) or sum(a < b for a, b in zip(accessor["min"], accessor["max"])) < 2:
                raise ValueError("GLB POSITION bounds are empty or invalid")
            primitives += 1
            positions += count
    if not mesh_ids or not primitives:
        raise ValueError("GLB has no mesh primitives reachable from its default scene")
    return {"schemaVersion": 1, "format": "glTF", "version": 2, "bytes": size,
            "defaultScene": selected, "sceneCount": len(scenes), "nodeCount": len(nodes),
            "reachableNodeCount": len(visited), "reachableMeshCount": len(mesh_ids),
            "primitiveCount": primitives, "positionCount": positions, "embeddedBinaryBytes": chunks[1][1],
            "externalDependencies": [], "inspection": "structural-only; native rendering remains separate"}


def builtin_specs(source: Path) -> tuple:
    tree = ast.parse(native(safe_path(source, HOST_PATH)).read_text(encoding="utf-8"))
    matches = [node.value for node in tree.body if isinstance(node, ast.AnnAssign)
               and isinstance(node.target, ast.Name) and node.target.id == "_PRIVATE_LOCAL_ASSET_SPECS"]
    if len(matches) != 1:
        raise ValueError("Source private asset specs did not resolve uniquely")
    specs = ast.literal_eval(matches[0])  # Data only: do not execute the source application.
    if not isinstance(specs, tuple) or not specs:
        raise ValueError("Source private asset specs are invalid")
    return specs


def prepare(snapshot: Path, source: Path, data_root: Path, *, port: int, profile_id: str,
            layout_id: str = LAYOUT_ID) -> dict:
    expected_source = backend.verify_snapshot(snapshot)
    source, snapshot, data_root = map(backend.no_links, (source, snapshot, data_root))
    if source != expected_source:
        raise ValueError("Source must match the snapshot checkpoint provenance")
    if not backend.within(data_root, snapshot / ".runtime" / "desktop-spike") or data_root == snapshot / ".runtime" / "desktop-spike":
        raise ValueError("Recovery data root must be a new child under snapshot .runtime/desktop-spike")
    if native(data_root).exists():
        raise ValueError("Recovery data root must not already exist; never reuse a live or prior fixture")
    if not re.fullmatch(r"fl-[A-Za-z0-9][A-Za-z0-9._-]{0,120}", layout_id):
        raise ValueError("Invalid layout ID")
    layout_relative = f".runtime/facility-layout/layouts/local/site-local/layouts/{layout_id}.json"
    layout_path = safe_path(source, layout_relative)
    layout_bytes = native(layout_path).read_bytes()
    document = json.loads(layout_bytes)
    revision = hashlib.sha256(layout_bytes).hexdigest()
    if document.get("layoutId") != layout_id or document.get("schemaVersion") != 1 or canonical(document) != layout_bytes:
        raise ValueError("Source layout identity or canonical byte representation is invalid")
    registry_path = safe_path(source, str(PurePosixPath(layout_relative).parent / "registry.json"))
    registry = read_json(registry_path)
    entries = [entry for entry in registry.get("layouts", []) if entry.get("layoutId") == layout_id]
    if len(entries) != 1 or entries[0].get("currentRevision") != revision:
        raise ValueError("Source layout revision does not match its registry")
    placement_counts = Counter(item["assetId"] for item in document["placements"])
    if not placement_counts:
        raise ValueError("Recovery fixture must contain placed equipment")
    catalog_path = safe_path(source, CATALOG_PATH)
    catalog = read_json(catalog_path)
    if catalog.get("schemaVersion") != 1 or not isinstance(catalog.get("assets"), list):
        raise ValueError("Source asset catalog schema is invalid")
    records = {record["assetId"]: record for record in catalog["assets"]}
    if len(records) != len(catalog["assets"]):
        raise ValueError("Source asset catalog contains duplicate IDs")
    builtins = {entry["asset_id"]: entry for entry in builtin_specs(source)}
    if set(records) & set(builtins):
        raise ValueError("Source catalog shadows a built-in private asset")
    source_files = {}
    assets = []
    selected_records = []
    for asset_id in sorted(placement_counts):
        record = records.get(asset_id)
        spec = builtins.get(asset_id)
        if record is None and spec is None:
            raise ValueError(f"Placed asset has no local metadata: {asset_id}")
        relative = (record or spec)["artifact"]
        path = safe_path(source, relative)
        relative = path.relative_to(source).as_posix()
        if not relative.startswith("generated/industrial_assets/") or path.suffix.lower() != ".glb":
            raise ValueError("Fixture GLBs must be under generated/industrial_assets")
        inspected = inspect_glb(path)
        digest = sha256(path)
        source_files[relative] = {"source": path, "sha256": digest, "destination": "asset-project/" + relative}
        revisions = sorted({item["assetDefinitionRevision"] for item in document["placements"] if item["assetId"] == asset_id})
        asset = {"assetId": asset_id, "placementCount": placement_counts[asset_id],
                 "placementDefinitionRevisions": revisions, "sourceRelativePath": relative,
                 "relativePath": "asset-project/" + relative, "route": "/" + quote(relative, safe="/"),
                 "sha256": digest, "bytes": inspected["bytes"], "glbInspection": inspected,
                 "metadataKind": "source-catalog" if record else "source-built-in"}
        thumb_relative = str(PurePosixPath(relative).parent / "thumbnail.webp")
        thumb = safe_path(source, thumb_relative, must_exist=False)
        if native(thumb).is_file():
            source_files[thumb_relative] = {"source": thumb, "sha256": sha256(thumb), "destination": "asset-project/" + thumb_relative}
            asset["thumbnailRoute"] = "/" + quote(thumb_relative, safe="/")
        if record:
            selected_records.append(record)
        assets.append(asset)
    # Copy only the precise authority revisions referenced by this layout.
    authority_registries = []
    for category, kind, ref, id_key, rev_key in (
        ("shells", "facility_shell", document["sourceShellRef"], "shellId", "shellRevision"),
        ("policies", "policy_set", document["policySetRef"], "policySetId", "policySetRevision"),
    ):
        authority_id, authority_rev = ref[id_key], ref[rev_key]
        if not re.fullmatch(r"[A-Za-z0-9._-]+", authority_id) or not re.fullmatch(r"[0-9a-f]{64}", authority_rev):
            raise ValueError("Layout authority reference is invalid")
        base = f".runtime/facility-layout/authorities/{category}/local/site-local/authority/{kind}"
        relative = f"{base}/{authority_id}/revisions/{authority_rev}.json"
        path = safe_path(source, relative)
        payload = native(path).read_bytes()
        if hashlib.sha256(payload).hexdigest() != authority_rev or canonical(json.loads(payload)) != payload:
            raise ValueError("Referenced authority document bytes do not match its revision")
        source_files[relative] = {"source": path, "sha256": authority_rev, "destination": relative.replace(".runtime/facility-layout/", "facility/", 1)}
        authority_registry = read_json(safe_path(source, base + "/registry.json"))
        matches = [entry for entry in authority_registry["entries"] if entry["authorityId"] == authority_id]
        if len(matches) != 1 or authority_rev not in matches[0]["revisionHistory"]:
            raise ValueError("Referenced authority revision is not registered")
        entry = dict(matches[0], currentRevision=authority_rev, publishedRevision=authority_rev,
                     revisionHistory=[authority_rev], status=json.loads(payload)["status"])
        authority_registries.append((base.replace(".runtime/facility-layout/", "facility/", 1) + "/registry.json",
                                    dict(authority_registry, entries=[entry])))
    # Preflight is read-only. The first mutation creates a fresh isolated identity.
    library, identity = backend.prepare_fixture(snapshot, data_root, profile_id, port)
    copied = []
    def write(relative: str, payload: bytes, kind: str):
        destination = safe_path(data_root, relative, must_exist=False)
        native(destination.parent).mkdir(parents=True, exist_ok=True)
        with native(destination).open("xb") as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        copied.append({"relativePath": relative, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload), "kind": kind})
    layout_destination = layout_relative.replace(".runtime/facility-layout/", "facility/", 1)
    write(layout_destination, layout_bytes, "exact-source-layout")
    write(str(PurePosixPath(layout_destination).parent / "registry.json"),
          canonical(dict(registry, layouts=entries, defaultLayoutId=layout_id)), "filtered-layout-registry")
    for relative, item in sorted(source_files.items()):
        destination = safe_path(data_root, item["destination"], must_exist=False)
        native(destination.parent).mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with native(item["source"]).open("rb") as src, native(destination).open("xb") as dst:
            for chunk in iter(lambda: src.read(1024 * 1024), b""):
                dst.write(chunk); digest.update(chunk)
            dst.flush(); os.fsync(dst.fileno())
        if digest.hexdigest() != item["sha256"] or sha256(item["source"]) != item["sha256"] or sha256(destination) != item["sha256"]:
            raise ValueError("Source or copied asset changed during fixture preparation")
        copied.append({"relativePath": item["destination"], "sourceRelativePath": relative,
                       "sha256": item["sha256"], "bytes": native(destination).stat().st_size, "kind": "exact-source-file"})
    write("asset-project/" + CATALOG_PATH, canonical({"schemaVersion": 1, "assets": selected_records,
          "summary": {"total": len(selected_records), "fixtureSubset": True}}), "filtered-source-catalog")
    for path, value in authority_registries:
        write(path, canonical(value), "filtered-authority-registry")
    if sha256(layout_path) != revision or sha256(safe_path(data_root, layout_destination)) != revision:
        raise ValueError("Source manual layout changed during fixture preparation")
    manifest = {
        "schemaVersion": 1, "revision": "facility-recovery-fixture-v1", "status": "prepared",
        "createdAt": datetime.now(timezone.utc).isoformat(), "fixtureRoot": str(data_root),
        "snapshotRoot": str(snapshot), "assetProjectRoot": str(data_root / "asset-project"),
        "facilityRoot": str(data_root / "facility"), "libraryRoot": str(library),
        "source": {"root": str(source), "layoutRelativePath": layout_relative,
                   "layoutSha256Before": revision, "layoutSha256After": sha256(layout_path),
                   "registrySha256": sha256(registry_path), "catalogSha256": sha256(catalog_path),
                   "hostSha256": sha256(safe_path(source, HOST_PATH))},
        "identity": identity,
        "layout": {"layoutId": layout_id, "relativePath": layout_destination, "revision": revision,
                   "bytes": len(layout_bytes), "displayName": document["displayName"],
                   "counts": {key: len(document.get(key, [])) for key in ("placements", "zones", "routes", "floorMarkings")}},
        "assets": assets, "assetCount": len(assets), "totalGlbBytes": sum(asset["bytes"] for asset in assets),
        "files": list(copied),
        "backendRequirements": {"privateAssets": True, "privateAssetRoot": str(data_root / "asset-project"),
            "generatedMount": str(data_root / "asset-project/generated"), "generatedMountPrecedesGeneric": True,
            "layoutSelectionId": layout_id, "catalogRoute": "/api/industrial-assets",
            "layoutRoute": f"/api/facility-layouts/site-local/{layout_id}", "bootstrapRoute": "/api/facility-layout-bootstrap"},
        "verification": {"sourceBytesPreserved": True, "selfContainedGlbsInspected": True,
            "backendRoutesExercised": False, "nativeRenderingExercised": False,
            "limitations": ["GLB inspection is structural; native scene rendering remains separate.",
                            "Fixture registries contain only referenced source documents; live store identity and transaction history were not copied."]},
    }
    write(MANIFEST_NAME, json.dumps(manifest, indent=2, allow_nan=False).encode("utf-8") + b"\n", "fixture-manifest")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=ROOT)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--layout-id", default=LAYOUT_ID)
    args = parser.parse_args()
    result = prepare(args.snapshot_root, args.source_root, args.data_root, port=args.port,
                     profile_id=args.profile_id, layout_id=args.layout_id)
    print(json.dumps({"status": result["status"], "manifest": str(args.data_root / MANIFEST_NAME),
                      "layoutRevision": result["layout"]["revision"], "assetCount": result["assetCount"],
                      "totalGlbBytes": result["totalGlbBytes"]}))


if __name__ == "__main__":
    main()
