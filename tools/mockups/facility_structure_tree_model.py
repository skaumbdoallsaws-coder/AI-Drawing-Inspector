"""Derive the real structure tree from the reference layout, for the mockup."""
import json
import pathlib
from collections import Counter, defaultdict

from shapely.geometry import Polygon, Point

ROOT = pathlib.Path(r"C:\Users\might\OneDrive\Desktop\InspectorPro\AI-Drawing-Inspector")
LAYOUT = ROOT / ".runtime/facility-layout/layouts/local/site-local/layouts/fl-reference-manual-20260812.json"
CATALOG = ROOT / "generated/industrial_assets/local_library"

layout = json.loads(LAYOUT.read_text(encoding="utf-8"))

zones = {}
for z in layout["zones"]:
    poly = Polygon([(p["x"], p["z"]) for p in z["boundary"]])
    zones[z["zoneId"]] = {"id": z["zoneId"], "label": z["label"],
                          "poly": poly, "area": poly.area,
                          "kind": z.get("zoneType"), "children": [], "assets": []}

# parent = smallest zone that strictly contains this one
for zid, z in zones.items():
    parents = [o for oid, o in zones.items()
               if oid != zid and o["poly"].covers(z["poly"]) and o["area"] > z["area"]]
    z["parent"] = min(parents, key=lambda o: o["area"])["id"] if parents else None
for zid, z in zones.items():
    if z["parent"]:
        zones[z["parent"]]["children"].append(zid)

# placement -> smallest containing zone
unzoned = []
for p in layout["placements"]:
    pt = Point(p["transform"]["position"]["x"], p["transform"]["position"]["z"])
    hits = [z for z in zones.values() if z["poly"].covers(pt)]
    (min(hits, key=lambda z: z["area"])["assets"] if hits else unzoned).append(p["assetId"])


def display_name(asset_id):
    entry = CATALOG / asset_id.replace("asset-", "", 1) / "catalog-entry.json"
    if entry.is_file():
        try:
            name = json.loads(entry.read_text(encoding="utf-8")).get("displayName")
            if name:
                return name
        except Exception:
            pass
    words = asset_id.replace("asset-", "", 1).replace("_", "-").split("-")
    return " ".join(w.capitalize() for w in words if not w.isdigit())[:34]


def node(zid):
    z = zones[zid]
    groups = [{"name": display_name(a), "count": n}
              for a, n in Counter(z["assets"]).most_common()]
    total = len(z["assets"]) + sum(descendant_total(c) for c in z["children"])
    return {"label": z["label"], "kind": z["kind"], "total": total,
            "groups": groups,
            "children": [node(c) for c in sorted(
                z["children"], key=lambda c: zones[c]["label"])]}


def descendant_total(zid):
    z = zones[zid]
    return len(z["assets"]) + sum(descendant_total(c) for c in z["children"])


roots = [node(zid) for zid in sorted(
    [zid for zid, z in zones.items() if z["parent"] is None],
    key=lambda zid: zones[zid]["label"])]

model = {"roots": roots,
         "unzoned": [{"name": display_name(a), "count": n}
                     for a, n in Counter(unzoned).most_common()],
         "zoneCount": len(zones), "placementCount": len(layout["placements"])}

out = pathlib.Path(__file__).resolve().parent / "tree_model.json"
out.write_text(json.dumps(model, indent=1), encoding="utf-8")
print("zones=%d placements=%d roots=%d unzoned=%d"
      % (model["zoneCount"], model["placementCount"], len(roots), len(model["unzoned"])))
for r in roots:
    print("  %-38s %4d assets, %d child zones" % (r["label"], r["total"], len(r["children"])))
