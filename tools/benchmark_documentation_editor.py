"""Server-only documentation measurements. No real library, browser or performance gate.

Each sample opens a fresh hidden process and an isolated copy of generated stores.
Cold open means scene read plus compilation with cold process caches, not disk-cache
purging or Python startup. Export timing calls builders (never the artifact cache).
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
METRICS = ("coldOpen", "commit", "undo", "reload", "pdf", "docx", "peakRss")
P0 = {"source": "docs/documentation-editor-reports/P0.md", "openSeconds": None,
      "pdfSeconds": None, "docxSeconds": None, "peakRssBytes": None,
      "note": "P0 recorded correctness baselines, not numeric open/export/RSS measurements."}


def peak_rss():
    try:
        import psutil
        info = psutil.Process().memory_info()
        if hasattr(info, "peak_wset"):
            return info.peak_wset, "psutil.memory_info().peak_wset"
    except ImportError:
        pass
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                 "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        counters = Counters(); counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.PeakWorkingSetSize, "GetProcessMemoryInfo.PeakWorkingSetSize"
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024), "resource.getrusage(RUSAGE_SELF).ru_maxrss"


def sample(root):
    import os
    os.environ["INSPECTORPRO_DOCUMENTATION_RICH_TEXT"] = "1"
    from tools.documentation_benchmark_support import NUMBER, KINDS, compile_document, attached
    from ai_inspector.parts_manual.documentation import DocumentationSceneRepository
    inputs = json.loads((root / "input.json").read_text(encoding="utf-8"))
    baseline = json.loads((root / "base.json").read_text(encoding="utf-8"))
    repo = DocumentationSceneRepository(root, KINDS[inputs["kind"]])
    binding = (NUMBER, baseline["sourceRevision"], baseline["manualPlanRevision"])
    measures = dict.fromkeys(METRICS)
    errors = {}
    def timed(name, fn):
        start = time.perf_counter(); result = fn(); measures[name] = time.perf_counter() - start
        return result
    def open_document():
        loaded = repo.read(*binding, identity_document=baseline)
        return loaded, compile_document(root, inputs, loaded["scene"], loaded["revision"])
    loaded, document = timed("coldOpen", open_document)
    original = deepcopy(document)
    scene_path = root / NUMBER.lower() / "documentation-scene.json"
    sizes = {"requestedPages": inputs["requestedPages"], "pages": len(document["pages"]),
        "blocks": sum(len(p.get("layoutBlocks", [])) for p in document["pages"]),
        "objects": sum(len(p.get("documentationObjects", {})) for p in document["pages"]),
        "bomRows": sum(len(p.get("bom", [])) for p in document["pages"]),
        "cadFigures": sum(bool(p.get("renderRequest")) for p in document["pages"]),
        "sceneBytes": scene_path.stat().st_size}
    def commit():
        result = repo.apply_command(*binding, base_revision=loaded["revision"], identity_document=baseline,
            page_targets={document["pages"][0]["pageId"]: {"page_element": ["header_title"]}},
            command={"operation": "update_text", "pageId": document["pages"][0]["pageId"], "targetType": "page_element",
                     "targetId": "header_title", "text": "Timed benchmark text edit"})
        return result, compile_document(root, inputs, result["scene"], result["revision"])
    edited, _ = timed("commit", commit)
    def undo():
        result = repo.move_history(*binding, base_revision=edited["revision"], direction="undo", identity_document=baseline)
        return result, compile_document(root, inputs, result["scene"], result["revision"])
    timed("undo", undo)
    _, document = timed("reload", open_document)
    if inputs["kind"] == "parts":
        from ai_inspector.parts_manual.pdf import build_manual_pdf_bytes
        document = attached(root, document)
        jobs = {"pdf": lambda: build_manual_pdf_bytes(root, NUMBER, document)}
    else:
        from ai_inspector.operations_manual.artifacts import carry_draft_render_artifacts
        from ai_inspector.operations_manual.exports import build_prototype_pdf_bytes, build_prototype_docx_bytes
        carry_draft_render_artifacts(root, NUMBER, attached(root, original), document)
        document = attached(root, document)
        jobs = {"pdf": lambda: build_prototype_pdf_bytes(root, NUMBER, document),
                "docx": lambda: build_prototype_docx_bytes(root, NUMBER, document)}
    lengths = {}
    for name, job in jobs.items():
        try:
            lengths[name] = len(timed(name, job))
        except Exception as error:
            errors[name] = {"type": type(error).__name__, "message": str(error)}
    measures["peakRss"], memory_method = peak_rss()
    return {"status": "error" if errors else "ok", "sizes": sizes, "measurements": measures,
            "errors": errors, "memoryMethod": memory_method,
            "pdfBytes": lengths.get("pdf"), "docxBytes": lengths.get("docx")}


def aggregate(values):
    values = [value for value in values if value is not None]
    return {"median": statistics.median(values), "p95": sorted(values)[max(0, math.ceil(.95*len(values))-1)],
            "samples": values} if values else None


def run(pages, runs):
    from tools.documentation_benchmark_support import prepare
    import os
    os.environ["INSPECTORPRO_DOCUMENTATION_RICH_TEXT"] = "1"
    report = {"schemaVersion": 1, "clock": "time.perf_counter", "p95Method": "nearest rank",
        "units": {"timings": "seconds", "peakRss": "bytes"}, "platform": sys.platform, "python": sys.version,
        "coldOpenDefinition": "Fresh process: scene read plus compile; excludes process startup; OS disk cache is not purged.",
        "p0": P0, "requestedPages": pages, "runs": runs, "results": [],
        "notes": ["Parts require at least six compiled pages; operations require at least four. Requested sizes below the compiler minimum use that minimum.",
                  "Parts retain 20 rows per BOM page. Mandatory front matter/index pages are counted in actual sizes.",
                  "Typing, selection and 20 open/close memory cycles belong to P5a-2."]}
    with tempfile.TemporaryDirectory(prefix="deb-") as directory:
        temp = Path(directory)
        for kind in ("operations", "parts"):
            for count in pages:
                entry = {"documentType": kind, "requestedPages": count, "samples": [], "metrics": {}, "budgets": []}
                report["results"].append(entry)
                fixture = temp / f"{kind[0]}{count}"
                try:
                    prepare(fixture, kind, count)
                    for index in range(runs):
                        target = temp / f"{kind[0]}{count}r{index}"; shutil.copytree(fixture, target)
                        result_file = target / "result.json"
                        # Never flash a child console on Windows. Workers only see their own temporary root.
                        completed = subprocess.run([sys.executable, str(Path(__file__)), "--worker", str(target), "--out", str(result_file)],
                            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
                        if not result_file.exists():
                            raise RuntimeError(completed.stderr.decode(errors="replace") or "Worker produced no result")
                        entry["samples"].append(json.loads(result_file.read_text(encoding="utf-8")))
                    measured = [s for s in entry["samples"] if "measurements" in s]
                    entry["status"] = "ok" if all(s["status"] == "ok" for s in entry["samples"]) else "error"
                    entry["sizes"] = measured[0]["sizes"] if measured else None
                    entry["metrics"] = {key: aggregate([s["measurements"][key] for s in measured]) for key in METRICS}
                    budgets = {"commit": 1.0}
                    if count == 100: budgets.update(coldOpen=5.0, pdf=30.0, **({"docx": 30.0} if kind == "operations" else {}))
                    for key, ceiling in budgets.items():
                        measured = entry["metrics"][key]
                        entry["budgets"].append({"metric": key, "seconds": ceiling,
                            "median": measured["median"] if measured else None,
                            "p95": measured["p95"] if measured else None,
                            "status": "NOT MEASURED" if measured is None else "MISSED" if measured["p95"] > ceiling
                                      else "INCOMPLETE" if len(measured["samples"]) != runs else "MET"})
                except Exception as error:
                    entry.update(status="error", error={"type": type(error).__name__, "message": str(error)})
    return report


def display(report):
    print("Type        requested actual  metric      median        p95       P0")
    for row in report["results"]:
        if row["status"] != "ok": print(row["documentType"], row["requestedPages"], "ERROR", row.get("error", row["samples"]))
        for name, values in row["metrics"].items():
            if values is None: continue
            factor, unit = (1/(1024*1024), "MiB") if name == "peakRss" else (1, "s")
            print(f"{row['documentType']:11} {row['requestedPages']:9} {row['sizes']['pages']:6}  {name:10}  "
                  f"{values['median']*factor:9.3f}{unit} {values['p95']*factor:9.3f}{unit}  not recorded")
        for budget in row["budgets"]:
            print(f"  {budget['status']}: {budget['metric']} p95={budget['p95']} s; budget <= {budget['seconds']} s")
    print(P0["note"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", nargs="+", type=int, default=[1, 50, 100])
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.runs < 1 or any(n < 1 for n in args.pages): parser.error("pages and runs must be positive")
    try:
        report = sample(args.worker) if args.worker else run(args.pages, args.runs)
    except Exception as error:
        report = {"status": "error", "error": {"type": type(error).__name__, "message": str(error)}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    if not args.worker:
        if "results" in report: display(report)
        else: print("ERROR", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
