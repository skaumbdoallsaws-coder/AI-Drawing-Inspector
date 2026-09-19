"""Published Sage knowledge and browser construction acceptance must agree."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator

from ai_inspector.facility_layout.knowledge_foundation import canonical_facility_command_registry
from ai_inspector.facility_layout.tool_knowledge import query_command_prerequisites


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "static/contracts/facility-construction-commands-v1.json").read_text())


def examples():
    return {
        "linear-pattern": {"seedIds": ["bench"], "count": 4, "direction": "vertical", "spacing": 5, "sourceUnit": "m"},
        "create-cell-group": {"selectionIds": ["bench"], "label": "Cell"},
        "surface-stack": {"supportId": "bench", "childIds": ["tool"], "surfaceId": "worktop", "itemGap": 0.05, "inset": 0.05},
        "cell-layout": {"selectionIds": ["bench", "tool"], "strategyId": "line", "targetBounds": {"width": 15, "depth": 8},
                        "sourceUnit": "m", "gap": 0.5, "rows": 1, "orientation": "preserve", "angleDegrees": 0, "invertU": False},
    }


def test_registry_and_sage_prerequisites_publish_shared_schemas():
    commands = {record["commandId"]: record for record in canonical_facility_command_registry()}
    for command_id, schema in CONTRACT["commands"].items():
        Draft202012Validator.check_schema(schema)
        published = commands[command_id]["inputSchema"]
        assert {k: v for k, v in published.items() if k != "$schema"} == schema
        assert query_command_prerequisites(command_id)["inputSchema"] == published
        assert set(commands[command_id]["inputContract"]["fields"]) == set(schema["properties"])
        for key, value in commands[command_id]["defaults"].items():
            Draft202012Validator(schema["properties"][key]).validate(value)


def test_json_schema_and_adapter_agree_on_valid_invalid_and_boundary_inputs():
    requests = []
    for command_id, example in examples().items():
        def add(args):
            requests.append({"commandId": command_id, "arguments": args})
        add(example)
        add({**example, "unrecognized": 3})
        schema = CONTRACT["commands"][command_id]
        for key in schema["required"]:
            missing = deepcopy(example)
            missing.pop(key)
            add(missing)
        for key in example:
            for wrong in [None, [], {}, "", "   ", ["   "], True]:
                add({**example, key: wrong})
    for count in [1, 2, 49, 50, 51, 2.5]:
        requests.append({"commandId": "linear-pattern", "arguments": {**examples()["linear-pattern"], "count": count}})
    for spacing in [-1, 0, 0.001, 5]:
        requests.append({"commandId": "linear-pattern", "arguments": {**examples()["linear-pattern"], "spacing": spacing}})
    expected = [Draft202012Validator(CONTRACT["commands"][r["commandId"]]).is_valid(r["arguments"]) for r in requests]
    result = subprocess.run(["node", "tests/test_facility_layout_command_adapter.js", "--validate"], cwd=ROOT,
                            input=json.dumps(requests), text=True, capture_output=True, check=True, timeout=30)
    actual = json.loads(result.stdout)
    assert len(actual) == len(expected)
    for request, accepted, valid in zip(requests, actual, expected):
        assert accepted == valid, request


def test_construction_session_against_real_python_operation_kernel():
    result = subprocess.run(["node", "tests/test_facility_layout_construction_kernel.js"], cwd=ROOT,
                            env={**os.environ, "CONSTRUCTION_TEST_PYTHON": sys.executable},
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["placements"] == 9
    assert evidence["cells"] == 3
    assert evidence["remappedAttachments"] == 2
    assert evidence["undoRestoredOriginal"]
    assert evidence["undoRestoredOriginalRevision"]
    assert evidence["reorderedRetryMatched"]
    assert evidence["staleRevisionRejected"]
    assert len(evidence["draftRevisions"]) == 6
    assert len(set(evidence["draftRevisions"])) == 6
    assert evidence["saves"] == 0
