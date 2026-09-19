from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "tests" / "fixtures" / "memory" / "pilot-replay-matrix-v1.json"


def _test_functions(path: Path) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def test_pilot_replay_matrix_is_closed_and_references_real_tests() -> None:
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    scenarios = matrix["scenarios"]

    assert matrix["schemaVersion"] == "sage-memory-pilot-replay-matrix-1.0"
    assert matrix["scenarioCount"] == 12
    assert len(scenarios) == 12
    assert [scenario["id"] for scenario in scenarios] == list(range(1, 13))
    assert len({scenario["title"] for scenario in scenarios}) == 12

    parsed_files: dict[Path, set[str]] = {}
    for scenario in scenarios:
        assert scenario["title"].strip()
        assert len(scenario["invariants"]) >= 2
        assert all(item.strip() for item in scenario["invariants"])
        assert scenario["testNodes"]
        assert any("test_memory_" in node for node in scenario["testNodes"])

        for test_node in scenario["testNodes"]:
            relative_path, separator, function_name = test_node.partition("::")
            assert separator == "::"
            assert function_name.startswith("test_")
            path = ROOT / relative_path
            assert path.is_file(), test_node
            if path not in parsed_files:
                parsed_files[path] = _test_functions(path)
            assert function_name in parsed_files[path], test_node
