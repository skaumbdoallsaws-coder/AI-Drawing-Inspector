"""Install step for kitchen_models.py (imported by it): copy the built GLBs into the real repo (or ROOT) and append
the catalog entries under the app's catalog lock, keeping the file's own JSON layout. Assets already in the catalog
are left alone (a placed asset's revision must never change)."""
import json
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\might\OneDrive\Desktop\InspectorPro\AI-Drawing-Inspector")


def install(K, backup, root=ROOT):
    sys.path.insert(0, str(ROOT))
    from ai_inspector.industrial_assets.authored_library import CatalogLock, replace_file
    catalog_path = root / "generated/industrial_assets/local_library/catalog.json"
    with CatalogLock(catalog_path):
        catalog_bytes = catalog_path.read_bytes()
        catalog = json.loads(catalog_bytes)
        known = {a["assetId"] for a in catalog["assets"]}
        todo = [a for a in K.ASSETS if a not in known]
        assert todo, "nothing new to install"
        models = K.built(only=todo)
        entries, credits = [], []
        for asset_id in todo:
            stem, name, _b, category, tags, description, key, change, *_x = K.ASSETS[asset_id]
            artifact = f"{K.FOLDER}/{stem}.glb"
            assert not (root / artifact).exists(), asset_id
            info = models[asset_id]
            text = description + " " + (K.credit(key) + " " if key else "") + change
            if key:
                src = {"author": K.DOWNLOADS[key][1], "generator": K.GEN, "kind": "third-party-model",
                       "license": "CC-BY-4.0", "title": K.DOWNLOADS[key][0], "triangles": info["triangles"],
                       "url": K.DOWNLOADS[key][3]}
            else:
                src = {"evidenceStatus": "authored", "generator": K.GEN, "kind": "authored-primitive",
                       "triangles": info["triangles"]}
            entry = {"artifact": artifact, "assetId": asset_id, "category": category, "description": text,
                     "dimensions": info["dims"], "displayName": name, "source": src,
                     "sourceToCanonical": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                     "tags": list(tags) + ["gym", "kitchenette", "authored"] + (["cc-by"] if key else [])}
            if info["surfaces"]:
                entry["supportSurfaces"] = info["surfaces"]
            if info["footprint"]:
                entry["footprintPolygons"] = [[{"x": x, "z": z} for x, z in poly] for poly in info["footprint"]]
            entries.append(entry)
            if key:
                credits.append(f"{name}: {K.credit(key)} {change}")
        total = len(catalog["assets"]) + len(entries)
        expected = json.loads(catalog_bytes)
        expected["assets"] += entries
        expected["summary"]["total"] = total
        new_text = None
        for style in ({"separators": (",", ":"), "sort_keys": True}, {"indent": 2, "sort_keys": True},
                      {"indent": 2}, {"separators": (",", ":")}):
            for ending in (b"", b"\n", b"\r\n"):
                if json.dumps(catalog, **style).encode("ascii") + ending == catalog_bytes:
                    new_text = json.dumps(expected, **style).encode("ascii") + ending
                    break
            if new_text:
                break
        assert new_text, "catalog layout not recognised; not writing"
        assert json.loads(new_text) == expected
        backup.mkdir(parents=True, exist_ok=False)
        (backup / "catalog.json").write_bytes(catalog_bytes)
        folder = root / K.FOLDER
        credits_file = folder / "CREDITS.txt"
        folder.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            with open(root / entry["artifact"], "xb") as handle:
                handle.write(models[entry["assetId"]]["payload"])
        if credits:
            if not credits_file.exists():
                credits_file.write_text("Private Gym kitchenette models adapted from these CC BY 4.0 models (the "
                                        "rest are our own):\n" + "\n".join(credits) + "\n", encoding="utf-8")
            else:
                (backup / "CREDITS.txt").write_bytes(credits_file.read_bytes())
                with open(credits_file, "a", encoding="utf-8") as handle:
                    handle.write("\n".join(credits) + "\n")
        replace_file(catalog_path, new_text, unchanged=catalog_bytes)
        print("installed", [e["assetId"] for e in entries], "; catalog total", total, "; backup", backup)


def update(K, asset_ids, backup, root=ROOT, ignore_layouts=()):
    """Rebuild ASSET_IDS and replace their GLB and catalog entry (name, description, dimensions, triangles), only
    while no saved layout uses them (a placed asset's revision must never change)."""
    sys.path.insert(0, str(ROOT))
    from ai_inspector.industrial_assets.authored_library import CatalogLock, replace_file
    catalog_path = root / "generated/industrial_assets/local_library/catalog.json"
    layouts = sorted((root / ".runtime/facility-layout/layouts").glob("*/*/layouts/*.json"))
    used = [(path.name, a) for path in layouts for a in asset_ids if path.stem not in ignore_layouts
            and a in path.read_text(encoding="utf-8", errors="replace")]
    assert not used, f"placed in a saved layout, not changing: {used}"
    models = K.built(only=asset_ids)
    with CatalogLock(catalog_path):
        catalog_bytes = catalog_path.read_bytes()
        catalog = json.loads(catalog_bytes)
        expected = json.loads(catalog_bytes)
        credits = []
        for entry in expected["assets"]:
            if entry["assetId"] not in asset_ids:
                continue
            stem, name, _b, _c, tags, description, key, change, *_x = K.ASSETS[entry["assetId"]]
            entry["tags"] = list(tags) + ["gym", "kitchenette", "authored"] + (["cc-by"] if key else [])
            if key:   # now drawn from a CC BY download: its source and a credit line
                entry["source"] = {"author": K.DOWNLOADS[key][1], "generator": K.GEN, "kind": "third-party-model",
                                   "license": "CC-BY-4.0", "title": K.DOWNLOADS[key][0], "url": K.DOWNLOADS[key][3]}
                credits.append(f"{name}: {K.credit(key)} {change}")
            elif "Model from" in change:
                credits.append(f"{name}: {change}")
            info = models[entry["assetId"]]
            assert entry["artifact"] == f"{K.FOLDER}/{stem}.glb"
            entry["displayName"] = name
            entry["description"] = description + " " + (K.credit(key) + " " if key else "") + change
            entry["dimensions"] = info["dims"]
            entry["source"]["triangles"] = info["triangles"]
            if info["surfaces"]:
                entry["supportSurfaces"] = info["surfaces"]
            if info["footprint"]:
                entry["footprintPolygons"] = [[{"x": x, "z": z} for x, z in poly] for poly in info["footprint"]]
        new_text = None
        for style in ({"separators": (",", ":"), "sort_keys": True}, {"indent": 2, "sort_keys": True},
                      {"indent": 2}, {"separators": (",", ":")}):
            for ending in (b"", b"\n", b"\r\n"):
                if json.dumps(catalog, **style).encode("ascii") + ending == catalog_bytes:
                    new_text = json.dumps(expected, **style).encode("ascii") + ending
                    break
            if new_text:
                break
        assert new_text, "catalog layout not recognised; not writing"
        backup.mkdir(parents=True, exist_ok=False)
        (backup / "catalog.json").write_bytes(catalog_bytes)
        for asset_id in asset_ids:
            path = root / f"{K.FOLDER}/{K.ASSETS[asset_id][0]}.glb"
            (backup / path.name).write_bytes(path.read_bytes())
            path.write_bytes(models[asset_id]["payload"])
        if credits:
            credits_file = root / K.FOLDER / "CREDITS.txt"
            (backup / "CREDITS.txt").write_bytes(credits_file.read_bytes())
            with open(credits_file, "a", encoding="utf-8") as handle:
                handle.write(chr(10).join(credits) + chr(10))
        replace_file(catalog_path, new_text, unchanged=catalog_bytes)
        print("updated", asset_ids, "; backup", backup)
