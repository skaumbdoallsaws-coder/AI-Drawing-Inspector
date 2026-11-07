"""Opt-in check of the real straight rack/pusher (user-approved CAD), read-only: one pair, four pairs (the sales set)
and six pairs.

Offline and local: a throwaway store in the system temp directory, the worktree's own packaging code, the isolated
STEP worker and no provider, carrier or Sage request. The CAD files are only read (hashed before and after) and never
copied. Evidence (numbers, report PDFs) goes to --output inside the worktree's .runtime folder, which is never staged.
The protection used here (1 in Ethafoam 220 on every face) is a labelled test assumption, not a requirement.

Independent checks:
  1. BRep (OCP, in the STEP worker) volume and bounds of the assembly.
  2. The tessellated GLB the worker produced, measured with trimesh (mesh volume per solid, scene extents).
  3. The five separately exported part STEP files, imported one by one: their summed BRep volume, and each part's
     volume matched to one assembly solid.
  4. The overall numbers printed on the Straight Pusher drawing (PDF text), next to the pusher part's box, and the
     rack-part sheets of the drawing package next to the rack parts' boxes.
  5. The STEP product structure (which product contains which), to confirm the file is one rack/pusher pair.

    python tests/verify_packaging_real_rack.py --step-python <packaging STEP python> --output .runtime/<new folder>
"""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import numpy as np  # noqa: E402
import pdfplumber  # noqa: E402
import trimesh  # noqa: E402

from ai_inspector.facility_layout.authorization import FacilityPrincipal  # noqa: E402
from ai_inspector.packaging_shipping.api import create_router  # noqa: E402
from ai_inspector.packaging_shipping.service import PackagingService  # noqa: E402
from ai_inspector.packaging_shipping.sources import GlbRuntime  # noqa: E402
from ai_inspector.packaging_shipping.step_import import StepRuntime, import_step  # noqa: E402

CAD = Path(r"C:\Users\might\OneDrive\Desktop\Black Acrylic Glued (Step)")
ASSEMBLY = CAD / "full assembly Concept 1- Straight pusher.step"
PARTS = ["Front Rail.step", "Rack Base Rail.step", "Straight Pusher.step", "Tile Backrest.step", "Tile Support Panel.step"]
DRAWING = CAD / "Straight Pusher.pdf"
# Sheets 4-7 of this package draw the four rack parts by the same names. Only those sheets are read, and only to compare
# with the straight concept's own part files; the scallop pusher itself is not used.
RACK_SHEETS = CAD / "black acrylic glued with scallop pusher - drawing.PDF"
RACK_TITLES = {"Tile Support Panel.step": ("TILE", "SUPPORT", "PANEL"), "Front Rail.step": ("FRONT", "RAIL"),
               "Tile Backrest.step": ("TILE", "BACKREST"), "Rack Base Rail.step": ("RACK", "BASE", "RAIL")}
HEADERS = {"X-InspectorPro-Request": "packaging"}


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def mm(values):
    return [round(v * 1000, 3) for v in values]


def step_args(text):
    out, depth, current, quoted = [], 0, "", False
    for ch in text:
        if quoted:
            current += ch
            quoted = ch != "'"
            continue
        if ch == "'":
            quoted = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(current.strip())
            current = ""
        else:
            current += ch
    return out + [current.strip()]


def assembly_tree(path):
    """Which product contains which, from the STEP product structure (text only; nothing is executed)."""
    text = path.read_text(encoding="latin-1")
    entities = {int(m.group(1)): (m.group(2), step_args(m.group(3)))
                for m in re.finditer(r"#(\d+)\s*=\s*([A-Z_0-9]+)\s*\((.*?)\)\s*;", text, re.S)}

    def ref(value):
        return int(value.lstrip("#"))

    def product_of(definition):
        formation = entities[ref(entities[definition][1][2])]
        return entities[ref(formation[1][2])][1][1].strip("'")

    edges = [(product_of(ref(a[3])), product_of(ref(a[4]))) for kind, a in entities.values()
             if kind == "NEXT_ASSEMBLY_USAGE_OCCURRENCE"]
    children = {}
    for parent, child in edges:
        children.setdefault(parent, []).append(child)
    return {"occurrences": len(edges), "children": {k: sorted(v) for k, v in children.items()},
            "solid_breps": len(re.findall(r"=\s*MANIFOLD_SOLID_BREP\s*\(", text)),
            "mass_or_material_entities": len(re.findall(r"=\s*[A-Z_]*(MASS|DENSITY|MATERIAL)[A-Z_]*\s*\(", text))}


def drawing_numbers(words):
    return sorted({float(w) for w in words if re.fullmatch(r"\d+\.\d+", w)}, reverse=True)


def compare_box(box_mm, numbers):
    """Each box side against the drawing's two-place values (half a unit of the last place, plus float noise)."""
    return [{"cad_mm": side, "drawing_mm": next((n for n in numbers if abs(n - side) <= 0.0051), None)} for side in box_mm]


def mesh_check(glb):
    scene = trimesh.load(io.BytesIO(glb), file_type="glb", force="scene")
    meshes = scene.dump() if hasattr(scene, "dump") else [scene]
    solids = []
    for mesh in meshes:
        solids.append({"volume_m3": float(abs(mesh.volume)), "watertight": bool(mesh.is_watertight),
                       "extents_mm": sorted(mm(mesh.extents.tolist()), reverse=True)})
    bounds = np.array(scene.bounds)
    return {"solids": solids, "total_volume_m3": sum(s["volume_m3"] for s in solids),
            "extents_mm": mm((bounds[1] - bounds[0]).tolist())}


async def brep(path, runtime):
    result = await import_step(path.read_bytes(), runtime=runtime)
    meta = result.metadata
    return {"dimensions_mm": mm(meta["dimensions_m"]), "volume_m3": meta["volume_m3"], "solid_count": meta["solid_count"],
            "faces": meta["face_count"], "triangles": meta["triangle_count"]}, result.glb_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step-python", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".runtime"):
        parser.error("Output must stay in this worktree's .runtime directory")
    if not all(f.is_file() for f in [ASSEMBLY, DRAWING, RACK_SHEETS] + [CAD / name for name in PARTS]):
        parser.error("The real rack/pusher files are not on this computer; nothing was run")
    output.mkdir(parents=True, exist_ok=False)
    files = [ASSEMBLY, DRAWING, RACK_SHEETS] + [CAD / name for name in PARTS]
    before = {f.name: digest(f) for f in files}
    temporary = Path(tempfile.mkdtemp(prefix="pk-rack-"))
    evidence = {"cad_files_sha256": before}
    try:
        runtime = StepRuntime(Path(args.step_python), temporary / "step-jobs")

        # 1-2. Assembly: BRep in the worker, then the worker's GLB measured independently.
        assembly, glb = asyncio.run(brep(ASSEMBLY, runtime))
        mesh = mesh_check(glb)
        evidence["assembly_brep"] = assembly
        evidence["assembly_mesh"] = mesh
        evidence["mesh_vs_brep"] = {
            "volume_relative_difference": (mesh["total_volume_m3"] - assembly["volume_m3"]) / assembly["volume_m3"],
            "extent_differences_mm": [round(a - b, 3) for a, b in zip(sorted(mesh["extents_mm"], reverse=True),
                                                                        sorted(assembly["dimensions_mm"], reverse=True))]}

        # 3. The separately exported parts.
        parts = {}
        for name in PARTS:
            part, part_glb = asyncio.run(brep(CAD / name, runtime))
            parts[name] = part
        evidence["parts_brep"] = parts
        part_total = sum(p["volume_m3"] for p in parts.values())
        unmatched = list(mesh["solids"])
        matches = {}
        for name, part in parts.items():
            best = min(unmatched, key=lambda s: abs(s["volume_m3"] - part["volume_m3"]))
            unmatched.remove(best)
            matches[name] = {"part_volume_m3": part["volume_m3"], "assembly_solid_volume_m3": best["volume_m3"],
                             "relative_difference": (best["volume_m3"] - part["volume_m3"]) / part["volume_m3"],
                             "part_box_mm": sorted(part["dimensions_mm"], reverse=True), "assembly_solid_box_mm": best["extents_mm"]}
        evidence["parts_vs_assembly"] = {"summed_part_volume_m3": part_total,
                                         "relative_difference_to_assembly": (part_total - assembly["volume_m3"]) / assembly["volume_m3"],
                                         "per_part": matches}

        # 4. Drawing text (numbers only).
        with pdfplumber.open(DRAWING) as pdf:
            words = [w["text"] for w in pdf.pages[0].extract_words()]
        numbers = sorted({float(w) for w in words if w.replace(".", "", 1).isdigit() and "." in w}, reverse=True)
        evidence["pusher_drawing"] = {"numbers_mm": numbers, "title_block_units": "inches" if "INCHES" in words else "millimeters",
                                      "box_vs_drawing": compare_box(sorted(parts["Straight Pusher.step"]["dimensions_mm"], reverse=True), numbers)}
        rack = {}
        with pdfplumber.open(RACK_SHEETS) as pdf:
            sheets = [[w["text"] for w in page.extract_words()] for page in pdf.pages]
        for name, title in RACK_TITLES.items():
            pages = [i for i, sheet in enumerate(sheets) if "ITEM" not in sheet
                     and all(word in {w.upper() for w in sheet} for word in title)]
            if len(pages) != 1:
                rack[name] = {"sheet": None, "note": f"{len(pages)} matching sheets; not compared"}
                continue
            numbers = drawing_numbers(sheets[pages[0]])
            rack[name] = {"sheet": pages[0] + 1, "numbers_mm": numbers,
                          "box_vs_drawing": compare_box(sorted(parts[name]["dimensions_mm"], reverse=True), numbers)}
        evidence["rack_part_sheets"] = rack
        evidence["assembly_tree"] = assembly_tree(ASSEMBLY)

        # Packing: one pair, the four-pair sales set and six pairs, in a throwaway store.
        service = PackagingService(temporary / "store")
        principal = FacilityPrincipal("engineer", "tenant-rack", ("site-rack",), ("editor",))
        app = FastAPI()
        app.include_router(create_router(service, principal_resolver=lambda request: principal, static_root=ROOT / "static",
                                         step_runtime=runtime, source_runtime=GlbRuntime(Path(trimesh.__file__).resolve().parents[1])))
        runs = {}
        with TestClient(app, headers=HEADERS) as client:
            catalog = client.get("/api/packaging/catalog").json()
            imported = client.post("/api/packaging/sources/step", params={"name": "Straight rack and pusher pair"},
                                   content=ASSEMBLY.read_bytes(), headers={"content-type": "application/step"})
            assert imported.status_code == 200, imported.text
            source = imported.json()
            pmma = next(m["material"] for m in catalog["materials"] if m["id"].startswith("pmma"))
            foam = next(m["material"] for m in catalog["materials"] if m["id"] == "ethafoam-220-0924")
            estimate = client.post(f"/api/packaging/sources/{source['id']}/mass-estimate", json={
                "source_revision": source["source_revision"], "material": pmma,
                "exclusions": "Excludes magnets, adhesive, finish and all packaging."})
            assert estimate.status_code == 200, estimate.text
            product = estimate.json()["product"]
            evidence["product"] = {key: product[key] for key in ("name", "dimensions_m", "mass_kg", "mass_basis", "mass_evidence")}
            # At most six per request: the six with the longest inside dimension. The three smallest (8, 10 and 12 in)
            # cannot hold a 508 mm part in any orientation.
            every = [entry["carton"] for entry in catalog["cartons"]]
            cartons = sorted(every, key=lambda c: max(c["inner_m"]), reverse=True)[:6]
            evidence["cartons_offered"] = [c["name"] for c in cartons]
            evidence["cartons_not_offered"] = [c["name"] for c in every if c not in cartons]
            for quantity in (1, 4, 6):
                design = {"name": f"TEST straight rack pairs x{quantity}", "quantity": quantity, "product": product, "packages": [],
                          "constraints": {"clearance_m": 0.02, "gap_m": 0.01, "allowed_orientations": [0, 1, 2, 3, 4, 5],
                                          "contents": "unconfirmed",
                                          "cushion": {"floor_m": 0.0254, "top_m": 0.0254, "sides_m": 0.0254, "material": foam,
                                                      "evidence": "TEST assumption for an offline run: 1 in Ethafoam 220 on every face. "
                                                                  "Not a drop-tested or customer requirement."}}}
                doc = client.post("/api/packaging/documents", json=design).json()
                proposals = client.post(f"/api/packaging/documents/{doc['id']}/arrangements",
                                        json={"expected_revision": doc["revision"], "cartons": cartons, "max_packages": 3})
                assert proposals.status_code == 200, proposals.text
                body = proposals.json()
                run = {"candidates": [{"cartons": [p["carton"]["name"] for p in c["design"]["packages"]],
                                       "package_count": c["package_count"], "shipping_volume_m3": c["shipping_volume_m3"],
                                       "findings": sorted({f["code"] for f in c["assessment"]["findings"]})}
                                      for c in body["candidates"]],
                       "rejected": body["rejected"], "notice": body["notice"]}
                if body["candidates"]:
                    best = body["candidates"][0]
                    saved = client.put(f"/api/packaging/documents/{doc['id']}", json={
                        "expected_revision": doc["revision"], "request_id": f"edit_rack_x{quantity}", "design": best["design"]})
                    assert saved.status_code == 200, saved.text
                    saved = saved.json()
                    assessment = saved["assessment"]
                    run["saved_revision"] = saved["revision"]
                    run["packages"] = [{"carton": p["carton"]["name"], "items": len(p["placements"]), "inserts": len(p["inserts"]),
                                        "carton_tare_kg": p["carton"].get("tare_kg"),
                                        "insert_mass_kg": sum(np.prod(i["dimensions_m"]) * i["density_kg_m3"] for i in p["inserts"])}
                                       for p in saved["design"]["packages"]]
                    run["assessment"] = {"findings": [{"code": f["code"], "severity": f.get("severity"), "message": f.get("message")}
                                                      for f in assessment["findings"]],
                                         "packages": assessment.get("packages"), "total_gross_kg": assessment.get("total_gross_kg")}
                    report = client.get(f"/api/packaging/documents/{doc['id']}/report.pdf?revision={saved['revision']}")
                    run["report"] = {"status": report.status_code, "bytes": len(report.content)}
                    if report.status_code == 200:
                        (output / f"report-pairs-{quantity}.pdf").write_bytes(report.content)
                runs[quantity] = run
        evidence["packing_runs"] = runs
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
        after = {f.name: digest(f) for f in files}
        evidence["cad_files_unchanged"] = after == before
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2, default=float), encoding="utf-8")
    print(json.dumps({"output": str(output), "unchanged": evidence["cad_files_unchanged"]}))


if __name__ == "__main__":
    main()
