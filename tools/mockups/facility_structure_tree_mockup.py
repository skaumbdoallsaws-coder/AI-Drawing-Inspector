"""Mock up the Facility Layout structure tree using the real derived model."""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent
ROOT = Path(r"C:\Users\might\OneDrive\Desktop\InspectorPro\AI-Drawing-Inspector")
ICONS = ROOT / "static/assets/facility-layout-ribbon-icons/svg"
MODEL = json.loads((OUT / "tree_model.json").read_text(encoding="utf-8"))

W, H = 1320, 860


def icon(name, cls="ti"):
    return '<img class="%s" src="%s" alt="">' % (cls, (ICONS / (name + ".svg")).as_uri())


def row(depth, kind, label, meta="", state="", caret="none", sel=False):
    """caret: open | closed | none"""
    car = {"open": "&#9662;", "closed": "&#9656;", "none": ""}[caret]
    ico = {"root": "cell-layout", "zone": "rectangle",
           "leaf": "polygon", "asset": "cube", "unzoned": "map-pin"}[kind]
    return (
        '<div class="row%s%s" style="--d:%d">'
        '<span class="caret">%s</span>%s'
        '<span class="lbl">%s</span>'
        '<span class="meta">%s</span></div>'
        % (" sel" if sel else "", " " + state if state else "", depth,
           car, icon(ico), label, meta))


roots = {r["label"]: r for r in MODEL["roots"]}
rows = [row(0, "root", "Reference Facility",
            "%d zones &middot; %d assets" % (MODEL["zoneCount"], MODEL["placementCount"]),
            caret="open")]

# One root expanded two levels deep to show nesting and grouping.
auto = roots["Automation + Robot cells"]
rows.append(row(1, "zone", "Automation + Robot cells", str(auto["total"]), caret="open"))
for child in auto["children"][:2]:
    rows.append(row(2, "zone", child["label"], str(child["total"]), caret="open"))
    for g in child["groups"][:3]:
        rows.append(row(3, "asset", g["name"],
                        "&times;%d" % g["count"] if g["count"] > 1 else "",
                        sel=(g is child["groups"][0] and child is auto["children"][0])))
for child in auto["children"][2:5]:
    rows.append(row(2, "zone", child["label"], str(child["total"]), caret="closed"))
rows.append('<div class="more" style="--d:2">%d more zones</div>'
            % (len(auto["children"]) - 5))

# A flat root: no child zones, assets directly inside.
recv = roots["Receiving + Raw Material"]
rows.append(row(1, "zone", "Receiving + Raw Material", str(recv["total"]), caret="open"))
for g in recv["groups"][:3]:
    rows.append(row(2, "asset", g["name"],
                    "&times;%d" % g["count"] if g["count"] > 1 else ""))

for label in ("Assembly + Kitting", "Inspection + Packing + Finished goods",
              "Machining Hall", "Material handling + Maintenance"):
    rows.append(row(1, "zone", label, str(roots[label]["total"]), caret="closed"))

# Authoring-time case: assets placed before their zone exists.
rows.append(row(1, "unzoned", "Unzoned", "3", state="warn", caret="open"))
for name, n in (("Workbench W84 D48", 2), ("Pallet Rack", 1)):
    rows.append(row(2, "asset", name, "&times;%d" % n if n > 1 else ""))

TREE = "".join(rows)

PAGE = """<!doctype html><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg-main:#252B36;--bg-panel:#1C2029;--bg-elevated:#1a1d22;
 --bg-hover:rgba(255,255,255,.06);--bg-selected:rgba(79,195,247,.16);
 --border-structure:rgba(255,255,255,.08);--border-strong:rgba(255,255,255,.14);
 --text-primary:#E3E6EB;--text-secondary:#9AA3AF;--accent:#4fc3f7}
*{box-sizing:border-box}
body{margin:0;width:%(W)dpx;height:%(H)dpx;background:var(--bg-main);
 font-family:Inter,"Segoe UI",sans-serif;color:var(--text-primary);display:flex}
.rail{width:48px;flex:0 0 48px;background:#141820;border-right:1px solid var(--border-structure);
 display:flex;flex-direction:column;align-items:center;padding-top:8px;gap:4px}
.ric{width:38px;height:38px;border-radius:6px;display:flex;align-items:center;
 justify-content:center;color:#7d8794;position:relative}
.ric.on{background:rgba(255,255,255,.07);color:#E3E6EB;
 box-shadow:inset 2px 0 0 var(--accent)}
.ric svg{width:20px;height:20px}

/* plan viewport stand-in */
.viewport{flex:1;position:relative;background:#eef4fb;
 background-image:linear-gradient(rgba(21,101,192,.07) 1px,transparent 1px),
  linear-gradient(90deg,rgba(21,101,192,.07) 1px,transparent 1px);background-size:26px 26px}
.zoneblk{position:absolute;border:1px solid rgba(21,101,192,.45);border-radius:2px;
 font:600 10px Inter;color:#2b4a66;padding:4px 6px}
.hl{outline:2px solid #4fc3f7;outline-offset:1px;background:rgba(79,195,247,.22)}
.vlabel{position:absolute;left:14px;top:12px;font:600 11px Inter;color:#5b6674}

/* the pane */
.pane{width:290px;flex:0 0 290px;background:var(--bg-panel);
 border-right:1px solid var(--border-structure);display:flex;flex-direction:column}
.phead{height:34px;display:flex;align-items:center;gap:8px;padding:0 10px;
 border-bottom:1px solid var(--border-structure);background:var(--bg-elevated)}
.phead b{font-size:11.5px;font-weight:600;letter-spacing:.2px;flex:1}
.phead .x{color:var(--text-secondary);font-size:13px}
.tabs{display:flex;gap:2px;padding:6px 8px 0;border-bottom:1px solid var(--border-structure)}
.tab{font-size:11px;color:var(--text-secondary);padding:5px 10px;border-radius:4px 4px 0 0}
.tab.on{background:var(--bg-main);color:var(--text-primary);font-weight:600}
.body{flex:1;overflow:hidden;padding:5px 0}

.row{display:flex;align-items:center;gap:6px;height:23px;
 padding-left:calc(6px + var(--d) * 15px);padding-right:9px;font-size:11.5px;
 color:var(--text-primary);white-space:nowrap}
.row:hover{background:var(--bg-hover)}
.row.sel{background:var(--bg-selected);box-shadow:inset 2px 0 0 var(--accent)}
.row.warn .lbl{color:#e0b357}
.caret{width:9px;flex:0 0 9px;color:var(--text-secondary);font-size:9px}
.ti{width:14px;height:14px;flex:0 0 14px;opacity:.92}
.lbl{overflow:hidden;text-overflow:ellipsis}
.meta{margin-left:auto;color:var(--text-secondary);font-size:10px;
 font-variant-numeric:tabular-nums}
.more{padding-left:calc(30px + var(--d) * 15px);height:21px;display:flex;
 align-items:center;font-size:10.5px;color:var(--text-secondary);font-style:italic}
.foot{border-top:1px solid var(--border-structure);padding:7px 10px;
 font-size:10px;color:var(--text-secondary);line-height:1.45}
</style>
<nav class="rail"><div class="ric"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></svg></div><div class="ric"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3Z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/></svg></div><div class="ric on" title="Structure"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 5h5M4 5v14h5M9 5h11M9 12H4M9 12h11M9 19h11"/><rect x="2.5" y="3.5" width="3" height="3" rx="0.6" fill="currentColor" stroke="none"/></svg></div></nav>
<aside class="pane">
  <div class="phead"><b>Facility Layout</b><span class="x">&#9662;</span></div>
  <div class="tabs"><span class="tab on">Structure</span><span class="tab">Properties</span></div>
  <div class="body">%(tree)s</div>
  <div class="foot">Membership is geometric: each asset is listed under the
    smallest zone whose boundary contains it. Moving an asset re-parents its row.</div>
</aside>
<div class="viewport">
  <span class="vlabel">Plan</span>
  <div class="zoneblk" style="left:40px;top:44px;width:250px;height:300px">Automation + Robot cells</div>
  <div class="zoneblk hl" style="left:58px;top:78px;width:96px;height:74px">Cell A01</div>
  <div class="zoneblk" style="left:170px;top:78px;width:96px;height:74px">Cell A02</div>
  <div class="zoneblk" style="left:40px;top:370px;width:250px;height:150px">Receiving + Raw Material</div>
  <div class="zoneblk" style="left:320px;top:44px;width:230px;height:200px">Assembly + Kitting</div>
  <div class="zoneblk" style="left:320px;top:270px;width:230px;height:250px">Inspection + Packing + Finished goods</div>
  <div class="zoneblk" style="left:580px;top:44px;width:180px;height:180px">Machining Hall</div>
  <div class="zoneblk" style="left:580px;top:250px;width:180px;height:140px">Material handling</div>
</div>""" % {"W": W, "H": H, "tree": TREE}


def main() -> None:
    f = OUT / "tree_mockup_rail.html"
    f.write_text(PAGE, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=2)
        pg.goto(f.as_uri())
        pg.wait_for_timeout(1800)
        pg.screenshot(path=str(OUT / "tree_mockup_rail.png"))
        b.close()
    print("wrote tree_mockup_rail.png")


if __name__ == "__main__":
    main()
