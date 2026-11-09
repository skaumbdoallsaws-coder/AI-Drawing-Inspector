"""MI5 acceptance (docs/sage-model-import-plan.md section 6): the six example recipes on the real downloads.

    python tools/model_import_acceptance.py DOWNLOADS_DIR OUT_DIR [key ...]

DOWNLOADS_DIR holds one folder per download with its model.glb (the 2026-11-08 kitchen downloads: fruit-coll,
board-charc, mug-lister, olive, basil, vases-five). The downloads are untrusted files: they are only read by the
isolated worker, never imported or executed, and they stay outside the repo. For each recipe the script inspects
the source, prepares the draft, checks the result with primitives.verify, compares the size with the 2026-11-08
reference within the stated tolerance, and copies the source and draft previews. OUT_DIR/report.json has it all.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.model_import_runtime import model_import_runtime  # noqa: E402
from ai_inspector.industrial_assets.model_import.errors import ModelImportError  # noqa: E402
from ai_inspector.industrial_assets.model_import.prepare_runner import prepare_draft  # noqa: E402
from ai_inspector.industrial_assets.model_import.runner import run_inspect  # noqa: E402
from ai_inspector.industrial_assets.primitives import verify  # noqa: E402

OFF = {"emissive": "off"}
VASES = ((1, [-0.34, 0, 0]), (4, [0.05, 0, 0]), (3, [0.38, 0, 0]), (5, [-0.22, 0.35, 0]), (2, [0.30, 0.35, 0]))

# key -> (recipe, expected {dimension: (metres, tolerance)}) from the 2026-11-08 assets
RECIPES = {
    "fruit-coll": ({"name": "Fruit bowl", "parts": [{"select": {"all": True}, "material": OFF}]},
                   {"width": (0.52, 0.02)}),
    "board-charc": ({"name": "Serving board", "size": {"scale": 0.85}, "parts": [
        {"select": {"all": True}, "material": OFF},
        {"select": {"material": "Material.002"}, "name": "wine bottle"},
        {"select": {"material": "Material.003"}, "name": "wine bottle"},
        {"select": {"material": "red_wine"}, "name": "wine"},
        {"select": {"material": "glass"}, "name": "glasses"},
        {"select": {"material": "baked_FLAT"}, "name": "board"},
        {"select": {"material": "Material.004"}, "name": "wine label",
         "material": {"color": "#e8dcc4", "roughness": 0.8, "texture": "drop"}}]},
        {"depth": (0.41, 0.01), "height": (0.32, 0.01)}),
    "mug-lister": ({"name": "Mugs", "size": {"dimension": "height", "meters": 0.095},
                    "pivot": {"parts": [{"all": True}]},
                    "parts": [{"select": {"all": True}, "name": "mugs",
                               "material": {"color": "#22272e", "roughness": 0.35, "texture": "drop"}}],
                    "copies": [{"x": -0.02, "z": -0.11, "turnDegrees": 20}, {"x": 0.015, "z": 0, "turnDegrees": -15},
                               {"x": -0.01, "z": 0.11, "turnDegrees": 35}]},
                   {"height": (0.095, 0.001)}),
    "olive": ({"name": "Olive tree in a pot", "pivot": {"parts": [{"material": "olive-tree-bark"}]},
               "size": {"dimension": "height", "meters": 0.965}, "textureMaxPx": 1024, "parts": [
                   {"select": {"material": "olive-leaves"}, "name": "olive leaves",
                    "material": {"alpha": "mask", "alphaCutoff": 0.5, "emissive": "off"}},
                   {"select": {"material": "olive-tree-bark"}, "name": "olive trunk", "material": OFF},
                   {"select": {"all": True}, "move": [0, 0.385, 0]}],
               "add": [{"shape": "frustum", "radiusBottom": 0.18, "radiusTop": 0.25, "height": 0.45, "hollow": 0.012,
                        "position": [0, 0, 0], "name": "terracotta pot", "color": "#b4643e", "roughness": 0.85},
                       {"shape": "cylinder", "radius": 0.234, "height": 0.01, "position": [0, 0.405, 0],
                        "name": "soil", "color": "#3a2a1e", "roughness": 0.95}]},
              {"height": (1.35, 0.03)}),
    "basil": ({"name": "Basil pair", "size": {"dimension": "height", "meters": 0.3}, "textureMaxPx": 1024,
               "parts": [{"select": {"all": True}, "name": "basil", "material": OFF}],
               "copies": [{"x": 0, "z": -0.105}, {"x": 0.01, "z": 0.105, "turnDegrees": 70, "scale": 0.92}]},
              {"height": (0.3, 0.005)}),
    "vases-five": ({"name": "Five vases", "size": {"scale": 0.005}, "textureMaxPx": 512,
                    "parts": [{"select": {"all": True}, "material": OFF}] + [
                        {"select": {"material": f"vase{k}"}, "name": f"vase {k}", "moveTo": xyz} for k, xyz in VASES]},
                   {"width": (0.88, 0.03)}),
}


def run(downloads: Path, out: Path, keys: list[str]) -> dict:
    dependencies = model_import_runtime().dependency_root
    report = {"dependencyRoot": str(dependencies), "results": {}}
    for key in keys:
        recipe, expected = RECIPES[key]
        recipe = {**recipe, "category": "decor", "importId": "mi-" + "0" * 24}
        source = downloads / key / "model.glb"
        job, draft = out / key / "inspect", out / key / "draft"
        shutil.rmtree(out / key, ignore_errors=True)
        job.mkdir(parents=True)
        shutil.copyfile(source, job / "source.bin")
        entry = {"sourceBytes": source.stat().st_size}
        try:
            started = time.monotonic()
            summary = run_inspect(job, dependencies)
            entry["inspectSeconds"] = round(time.monotonic() - started, 2)
            entry["sourceTriangles"] = summary.get("triangles")
            started = time.monotonic()
            result = prepare_draft(source, recipe, draft, threading.Event(), dependency_root=dependencies,
                                   cache_dir=job)
            entry["prepareSeconds"] = round(time.monotonic() - started, 2)
            checked = verify((draft / "model.glb").read_bytes())
            entry.update(dimensions=checked["dimensions"], triangles=checked["triangles"],
                         partsTotal=result.get("partsTotal"), warnings=result.get("warnings", [])[:5])
            entry["sizeChecks"] = {name: {"expected": want, "tolerance": tol, "actual": checked["dimensions"][name],
                                          "ok": abs(checked["dimensions"][name] - want) <= tol}
                                   for name, (want, tol) in expected.items()}
            entry["status"] = "passed" if all(c["ok"] for c in entry["sizeChecks"].values()) else "size-mismatch"
        except ModelImportError as error:
            entry.update(status="refused", error=error.to_dict())
        finally:
            (job / "source.bin").unlink(missing_ok=True)
        report["results"][key] = entry
        print(key, json.dumps({k: entry.get(k) for k in ("status", "dimensions", "inspectSeconds", "prepareSeconds")}),
              flush=True)
    report["passed"] = all(r["status"] == "passed" for r in report["results"].values())
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    downloads, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    keys = sys.argv[3:] or list(RECIPES)
    out.mkdir(parents=True, exist_ok=True)
    return 0 if run(downloads, out, keys)["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
