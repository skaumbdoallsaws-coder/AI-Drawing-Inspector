"""Fast contracts for the P5a-only harness. No browser, compiler or real store."""
import ast
from pathlib import Path

import pytest

from tests.documentation_editor_scale_smoke import statistics
from tests.documentation_editor_scale_support import counts
from tools.documentation_benchmark_support import NUMBER, profile

ROOT = Path(__file__).resolve().parents[1]


def test_benchmark_assembly_argument_is_additive():
    assert profile(2) == profile(2, NUMBER)
    a, b = profile(2, "SCALE-P50"), profile(2, "SCALE-P100")
    assert a["identity"]["assemblyNumber"] == "SCALE-P50"
    assert b["identity"]["assemblyNumber"] == "SCALE-P100"
    a["identity"]["assemblyNumber"] = b["identity"]["assemblyNumber"]
    assert a == b
    tree = ast.parse((ROOT / "tools/documentation_benchmark_support.py").read_text("utf-8"))
    for name in ("prepare", "capture", "attached", "profile"):
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        assert function.args.args[-1].arg == "assembly_number"
        assert isinstance(function.args.defaults[-1], ast.Name) and function.args.defaults[-1].id == "NUMBER"


def test_fixture_counts_are_actual_not_requested(tmp_path):
    scene = tmp_path / "scene.json"
    scene.write_bytes(b'{}\n')
    value = counts({"pages": [{"bom": [{}, {}], "documentationObjects": {"a": {}, "b": {}},
        "layoutBlocks": [{}, {}, {}], "renderRequest": {"figure": "x"}}, {}], "sections": [1]}, scene)
    assert value == {"pages": 2, "blocks": 3, "objects": 2, "figures": 1, "bomRows": 2, "groups": 1, "sceneBytes": 3}


def test_browser_statistics_use_nearest_rank_and_do_not_change_samples():
    samples = [100, 1, 4, 3, 2]
    assert statistics(samples) == {"samples": samples, "median": 3, "p95": 100}
    assert samples == [100, 1, 4, 3, 2]
    assert statistics([1, 2, 3, 4])["median"] == 2.5
    assert statistics(list(range(1, 51)))["p95"] == 48
    for values in ([], [float("nan")], [-1]):
        with pytest.raises(ValueError):
            statistics(values)


def test_scale_loader_is_opt_in_and_product_has_no_fixture_path():
    launcher = (ROOT / "tests/documentation_editor_smoke_server.py").read_text("utf-8")
    assert 'os.environ.get("INSPECTORPRO_DOC_SMOKE_PHASE") == "P5a"' in launcher
    assert "install_scale_fixtures" not in (ROOT / "server.py").read_text("utf-8-sig")
    assert "__p5a" not in (ROOT / "static/index.html").read_text("utf-8")


def test_new_phase_has_no_fixed_sleeps_or_unscaled_playwright_timeouts():
    source = (ROOT / "tests/documentation_editor_scale_smoke.py").read_text("utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            assert not (isinstance(node.func, ast.Attribute) and node.func.attr in {"sleep", "wait_for_timeout", "insert_text"})
            for keyword in node.keywords:
                if keyword.arg == "timeout":
                    assert isinstance(keyword.value, (ast.Call, ast.Name))


def test_p5a_accepts_only_one_proved_page_setup_refusal():
    from tests.test_documentation_editor_smoke import empty_report, failure, console_resource
    from tests.smoke_documentation_editor import classify_failures
    report = empty_report()
    item = failure("/api/operations-manual/MMLE-50D/documentation-scene/commands", 409, "POST")
    report.update(phase="P5a", httpFailures=[item], consoleErrors=[console_resource(item)],
        expectedHttpFailures=[{**item, "error": "layout_overflow", "checked": True}])
    assert classify_failures(report)
    report["httpFailures"].append(dict(item))
    assert not classify_failures(report)
    report["httpFailures"].pop()
    report["expectedHttpFailures"][0]["checked"] = False
    assert not classify_failures(report)
