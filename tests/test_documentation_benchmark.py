"""Small server-only CLI contract; no timing assertions or real stores."""
import json
from pathlib import Path
import subprocess
import sys


def test_one_page_one_run_benchmark_json_shape(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "b.json"
    result = subprocess.run([sys.executable, str(root / "tools/benchmark_documentation_editor.py"),
        "--pages", "1", "--runs", "1", "--out", str(output)], cwd=root,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=90, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schemaVersion"] == 1 and report["requestedPages"] == [1] and report["runs"] == 1
    assert report["p0"]["openSeconds"] is None
    assert [row["documentType"] for row in report["results"]] == ["operations", "parts"]
    for row in report["results"]:
        assert row["status"] == "ok", row
        assert set(row["sizes"]) == {"requestedPages", "pages", "blocks", "objects", "bomRows", "cadFigures", "sceneBytes"}
        assert set(row["metrics"]) == {"coldOpen", "commit", "undo", "reload", "pdf", "docx", "peakRss"}
        assert len(row["samples"]) == 1 and row["samples"][0]["memoryMethod"]
        for key, value in row["metrics"].items():
            if key == "docx" and row["documentType"] == "parts": assert value is None
            else: assert set(value) == {"median", "p95", "samples"} and len(value["samples"]) == 1
