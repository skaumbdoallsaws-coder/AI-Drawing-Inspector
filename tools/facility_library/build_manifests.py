"""Build the Facility library manifests from curated definitions and measured file hashes."""
import sys, json, hashlib
from pathlib import Path

LIB = Path(sys.argv[1]); S = Path(sys.argv[2])
VERSION = "2026.10.25.2"
tex_report = json.loads((S / "texture_report.json").read_text(encoding="utf-8"))
zip_sha = {}
for line in (S / "acg_zip_sha256.txt").read_text().splitlines():
    digest, path = line.split(" *", 1); zip_sha[path.split("/")[0]] = digest
signs = json.loads((S / "library_build" / "signs_report.json").read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


TILE = {"wood-maple": 1.0, "wood-oak": 1.0, "wood-walnut": 1.0, "metal-brushed": 0.4, "fabric-woven": 0.12,
        "cardboard-kraft": 0.25, "paper-matte": 0.3, "concrete-smooth": 2.0, "marble-white": 1.2, "rubber-speckled": 0.75}
LABEL = {"wood-maple": "Light wood grain", "wood-oak": "Medium oak-like grain", "wood-walnut": "Dark walnut-like grain",
         "metal-brushed": "Brushed metal streaks", "fabric-woven": "Fine woven fabric", "cardboard-kraft": "Corrugated cardboard",
         "paper-matte": "Matte paper fibre", "concrete-smooth": "Smooth poured concrete", "marble-white": "Veined white marble",
         "rubber-speckled": "Speckled rubber matting"}
texture_sets = []
for name, record in tex_report.items():
    src = record["source"]
    texture_sets.append({
        "textureSetId": name, "label": LABEL[name], "tileMeters": TILE[name],
        "grain": "u", "roughnessMean": record["roughnessMean"], "pixels": record["pixels"],
        "maps": {kind: f"textures/{name}/{info['path']}" for kind, info in record["files"].items()},
        "files": {f"textures/{name}/{info['path']}": {"bytes": info["bytes"], "sha256": info["sha256"]}
                  for info in record["files"].values()},
        "source": {"provider": "ambientCG", "assetId": src, "url": f"https://ambientcg.com/view?id={src}",
                   "package": f"{src}_1K-JPG.zip", "packageSha256": zip_sha[src], "license": "CC0-1.0",
                   "licenseUrl": "https://docs.ambientcg.com/license/", "retrieved": "2026-10-19",
                   "modifications": "Resized and re-encoded; tintable sets converted to a neutral detail map."}})


def tex(set_id, **extra):
    value = {"textureSetId": set_id, "sizeMeters": TILE[set_id], "rotationDegrees": 0, "mapping": "box",
             "grain": "length", "strength": 1}
    value.update(extra)
    return value


A = []


def add(appearance_id, label, category, color, roughness, metalness=0.0, texture=None, tags=(), description="", **extra):
    item = {"appearanceId": appearance_id, "label": label, "category": category, "model": "standard",
            "color": color, "roughness": roughness, "metalness": metalness, "opacity": 1, "texture": texture,
            "tags": list(tags), "description": description,
            "thumbnail": f"thumbnails/appearances/{appearance_id}.png"}
    item.update(extra)
    A.append(item)


add("steel-brushed", "Brushed steel", "metals", "#b9bdc0", 0.42, 1.0, tex("metal-brushed", grain="part"), ("steel", "stainless", "brushed", "metal"))
add("steel-polished", "Polished steel", "metals", "#c6c9cb", 0.12, 1.0, None, ("steel", "chrome", "polished", "metal"))
add("aluminum-brushed", "Brushed aluminum", "metals", "#d5d7d9", 0.38, 1.0, tex("metal-brushed", grain="part"), ("aluminum", "aluminium", "brushed", "metal"))
add("aluminum-polished", "Polished aluminum", "metals", "#dcdfe1", 0.1, 1.0, None, ("aluminum", "aluminium", "polished", "metal"))
add("brass-brushed", "Brushed brass", "metals", "#c9a35e", 0.4, 1.0, tex("metal-brushed", grain="part"), ("brass", "brushed", "gold", "metal"))
add("brass-polished", "Polished brass", "metals", "#d8b066", 0.12, 1.0, None, ("brass", "polished", "gold", "metal"))
add("plastic-matte", "Matte plastic", "plastics", "#3f4449", 0.78, 0.0, None, ("plastic", "matte", "abs", "housing"))
add("plastic-glossy", "Glossy plastic", "plastics", "#e9ebed", 0.2, 0.0, None, ("plastic", "glossy", "shiny"),
    model="physical", clearcoat=0.25, clearcoatRoughness=0.2)
add("plastic-translucent", "Translucent plastic", "plastics", "#dbe6ee", 0.3, 0.0, None,
    ("plastic", "translucent", "polycarbonate", "guard"), opacity=0.55)
add("wood-maple", "Maple (visual)", "wood", "#ffffff", 0.55, 0.0, tex("wood-maple", grain="part"), ("maple", "light wood", "hardwood", "furniture"),
    "Visual representation of a light hardwood; not a certified wood species.")
add("wood-oak", "Oak (visual)", "wood", "#ffffff", 0.52, 0.0, tex("wood-oak", grain="part"), ("oak", "wood", "hardwood", "furniture", "rack"),
    "Visual representation of an oak-like grain; not a certified wood species.")
add("wood-walnut", "Walnut (visual)", "wood", "#ffffff", 0.48, 0.0, tex("wood-walnut", grain="part"), ("walnut", "dark wood", "hardwood", "furniture"),
    "Visual representation of a walnut-like grain; not a certified wood species.")
add("rubber-black", "Black rubber", "rubber", "#1d1e1f", 0.92, 0.0, None, ("rubber", "black", "tire", "seal"))
add("rubber-speckled", "Speckled rubber matting", "rubber", "#ffffff", 0.85, 0.0, tex("rubber-speckled"), ("rubber", "mat", "flooring", "gym"))
add("glass-clear", "Clear glass", "glass", "#ffffff", 0.03, 0.0, None, ("glass", "clear", "window", "transparent"),
    model="physical", transmission=1.0, ior=1.5, thickness=0.006)
add("glass-frosted", "Frosted glass", "glass", "#f4f7f8", 0.42, 0.0, None, ("glass", "frosted", "privacy", "satin"),
    model="physical", transmission=1.0, ior=1.5, thickness=0.006)
add("fabric-woven-gray", "Woven fabric, gray", "fabric", "#8e9296", 0.88, 0.0, tex("fabric-woven"), ("fabric", "cloth", "upholstery", "woven"))
add("fabric-woven-navy", "Woven fabric, navy", "fabric", "#33415e", 0.88, 0.0, tex("fabric-woven"), ("fabric", "cloth", "upholstery", "woven", "blue"))
add("cardboard-kraft", "Kraft cardboard", "paper", "#b58f60", 0.82, 0.0, tex("cardboard-kraft"),
    ("cardboard", "carton", "box", "kraft", "packaging"))
add("paper-ivory-matte", "Matte ivory paper", "paper", "#ebe4d4", 0.86, 0.0, tex("paper-matte"), ("paper", "ivory", "matte", "label"))
add("paint-safety-yellow", "Safety yellow paint", "paint", "#f2c200", 0.45, 0.0, None, ("paint", "yellow", "safety", "guard", "rail"),
    model="physical", clearcoat=0.3, clearcoatRoughness=0.35)
add("paint-safety-orange", "Safety orange paint", "paint", "#f06a1f", 0.45, 0.0, None, ("paint", "orange", "safety"),
    model="physical", clearcoat=0.3, clearcoatRoughness=0.35)
add("paint-machine-gray", "Machine gray enamel", "paint", "#cbd0cc", 0.38, 0.0, None, ("paint", "gray", "grey", "machine", "enamel", "RAL 7035"),
    model="physical", clearcoat=0.45, clearcoatRoughness=0.25)
add("paint-powder-blue", "Blue powder coat", "paint", "#1f5aa6", 0.55, 0.0, None, ("paint", "blue", "powder coat", "rack", "shelving"))
add("paint-gloss-red", "Gloss red enamel", "paint", "#b3201f", 0.22, 0.0, None, ("paint", "red", "gloss", "fire", "enamel"),
    model="physical", clearcoat=0.8, clearcoatRoughness=0.1)
add("paint-matte-black", "Matte black powder coat", "paint", "#1e2023", 0.78, 0.0, None, ("paint", "black", "matte", "powder coat"))
add("paint-signal-green", "Signal green paint", "paint", "#2f8f4e", 0.45, 0.0, None, ("paint", "green", "safety", "first aid"),
    model="physical", clearcoat=0.3, clearcoatRoughness=0.35)
add("concrete-smooth", "Smooth concrete", "stone", "#ffffff", 0.82, 0.0, tex("concrete-smooth"), ("concrete", "cement", "floor", "wall"))
add("marble-white", "White marble (visual)", "stone", "#ffffff", 0.14, 0.0, tex("marble-white"), ("marble", "stone", "countertop", "polished"),
    "Visual representation of polished marble; not a stone specification.")

appearances = {
    "schemaVersion": 1, "libraryVersion": VERSION,
    "notes": "Appearances are visual only. They never change mass, density, strength or an assigned engineering material.",
    "categories": [{"categoryId": c, "label": l} for c, l in (
        ("metals", "Metals"), ("plastics", "Plastics"), ("wood", "Wood"), ("rubber", "Rubber"), ("glass", "Glass"),
        ("fabric", "Fabric"), ("paper", "Paper & Cardboard"), ("paint", "Paint & Coatings"), ("stone", "Concrete & Stone"))],
    "textureSets": texture_sets, "appearances": A}

ENV = [("machine-shop", "machine_shop_02", "Machine Shop 02"), ("warehouse", "empty_warehouse_01", "Empty Warehouse 01"),
       ("soft-studio", "studio_small_08", "Studio Small 08")]
environments = []
for env_id, ph_id, name in ENV:
    path = LIB / "environments" / f"{ph_id}_1k.hdr"
    environments.append({
        "environmentId": env_id, "label": name, "file": f"environments/{ph_id}_1k.hdr",
        "bytes": path.stat().st_size, "sha256": sha(path),
        "source": {"provider": "Poly Haven", "assetId": ph_id, "url": f"https://polyhaven.com/a/{ph_id}",
                   "author": "Sergej Majboroda", "license": "CC0-1.0", "licenseUrl": "https://polyhaven.com/license",
                   "resolution": "1k", "retrieved": "2026-10-19", "modifications": "None"}})


def scene(scene_id, label, group, description, environment, intensity, background, ambient, directional, exposure, shadows=False):
    return {"sceneId": scene_id, "label": label, "group": group, "description": description,
            "environment": environment, "environmentIntensity": intensity, "background": background,
            "ambient": ambient, "directional": directional, "exposure": exposure, "shadows": shadows,
            "thumbnail": f"thumbnails/scenes/{scene_id}.png"}


scenes = {
    "schemaVersion": 1, "libraryVersion": VERSION,
    "notes": "A scene changes only the viewport: background, lighting, reflections and shadows. It never changes the layout.",
    "groups": [{"groupId": "basic", "label": "Basic scenes"}, {"groupId": "studio", "label": "Studio scenes"},
               {"groupId": "industrial", "label": "Industrial scenes"}],
    "environments": environments,
    "scenes": [
        scene("classic", "Classic", "basic", "InspectorPro's standard viewport lighting. Only library finishes show reflections.", None, 0, "theme", 1.55, 2.0, 1.22),
        # Environment scenes were tuned on a real layout so plain models keep Classic's
        # brightness and shading: a gentle environment fill, low ambient and a strong
        # key light. Finishes reflect at twice the environment strength (see the adapter).
        scene("neutral-room", "Neutral room", "basic", "Soft, even studio light with neutral reflections.", "room", 0.35, "theme", 0.15, 2.4, 1.0),
        scene("presentation-light", "Presentation, light", "basic", "Light backdrop with soft shadows for screenshots.", "room", 0.38, "#eef0f2", 0.15, 2.4, 1.0, True),
        scene("presentation-dark", "Presentation, dark", "basic", "Dark backdrop with soft shadows for screenshots.", "room", 0.35, "#1c2026", 0.15, 2.6, 1.0, True),
        scene("soft-studio", "Soft studio", "studio", "Photographic studio lighting from a CC0 HDRI.", "soft-studio", 0.45, "theme", 0.2, 2.2, 1.0),
        scene("machine-shop", "Machine shop", "industrial", "Industrial hall lighting and reflections from a CC0 HDRI.", "machine-shop", 0.35, "theme", 0.15, 2.4, 1.0),
        scene("warehouse", "Warehouse", "industrial", "Overhead warehouse lighting from a CC0 HDRI.", "warehouse", 0.45, "theme", 0.15, 2.4, 1.0),
    ]}

GROUP = {"W": "warning", "M": "mandatory", "P": "prohibition", "E": "emergency", "F": "fire"}
NAMES = {"E001": "Emergency exit, left", "E002": "Emergency exit, right", "E003": "First aid", "E004": "Emergency telephone",
         "E007": "Evacuation assembly point", "E011": "Eyewash station", "E012": "Safety shower", "F001": "Fire extinguisher",
         "F002": "Fire hose reel", "F004": "Firefighting equipment", "F005": "Fire alarm call point",
         "M001": "General mandatory action", "M003": "Wear ear protection", "M004": "Wear eye protection",
         "M008": "Wear safety footwear", "M009": "Wear protective gloves", "M014": "Wear head protection",
         "M015": "Wear high-visibility clothing", "P001": "General prohibition", "P002": "No smoking",
         "P003": "No open flame", "P004": "No thoroughfare", "P006": "No forklift trucks", "P010": "Do not touch",
         "W001": "General warning", "W007": "Floor-level obstacle", "W011": "Slippery surface", "W012": "Electricity",
         "W014": "Forklift trucks", "W015": "Overhead load", "W017": "Hot surface", "W019": "Crushing",
         "W024": "Crushing of hands", "W026": "Battery charging",
         # Added 2026-10-25 for machine safety signs (fire hazard, robot cells).
         "W002": "Explosive material", "W016": "Toxic material", "W018": "Automatic start-up",
         "W021": "Flammable material", "W022": "Sharp element", "W023": "Corrosive substance",
         "P015": "No reaching in",
         # Added 2026-10-25: the in-running nip, a pinch point between rollers.
         "W025": "Counter-rotating rollers"}
decals = {
    "schemaVersion": 1, "libraryVersion": VERSION,
    "notes": "Safety signs are visual layout aids. Check site requirements and current ISO 7010 editions before relying on them.",
    "groups": [{"groupId": g, "label": l} for g, l in (
        ("warning", "Warning signs"), ("mandatory", "Mandatory action signs"), ("prohibition", "Prohibition signs"),
        ("emergency", "Emergency and first aid"), ("fire", "Fire equipment"))],
    "decals": [{"decalId": f"iso7010-{s['code'].lower()}", "label": NAMES[s["code"]], "code": f"ISO 7010 {s['code']}",
                "group": GROUP[s["code"][0]], "file": f"decals/{s['file']}", "aspect": s["aspect"],
                "widthMeters": 0.3, "bytes": s["bytes"], "sha256": s["sha256"],
                "source": {"provider": "Wikimedia Commons", "url": s["sourceUrl"], "fileUrl": s["fileUrl"],
                           "license": "CC0 1.0" if s.get("license") == "CC0 1.0" else "Public domain",
                           "originalSha256": s["originalSha256"],
                           "retrieved": s.get("retrieved", "2026-10-19"),
                           "modifications": "Added an explicit viewBox." if s["viewBoxAdded"] else "None"}}
               for s in sorted(signs, key=lambda s: ("WMPEF".index(s["code"][0]), s["code"]))]}

for name, value in (("appearances.json", appearances), ("scenes.json", scenes), ("decals.json", decals)):
    # Bytes with LF only: the manifests are hashed and must match every checkout.
    (LIB / name).write_bytes((json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode("utf-8"))
    print(name, len(json.dumps(value)))
print(len(A), "appearances;", len(scenes["scenes"]), "scenes;", len(decals["decals"]), "decals")
