"""Launcher-only fixture and restart contracts; production routes remain unchanged."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.documentation_editor_smoke_server import install_source_fixture


def fixture_server():
    baseline = {"sourceRevision": "a" * 64, "occurrences": [
        {"occurrenceId": "o1", "definitionId": "d1", "description": "Original", "partNumber": "A"},
        {"occurrenceId": "o2", "definitionId": "d2", "description": "Other", "partNumber": "B"},
    ]}
    server = SimpleNamespace(app=FastAPI(), _parts_manual_catalog_for_assembly=lambda _: ({}, baseline))
    return server, baseline


def test_source_fixture_route_persists_and_reapplies_after_restart(tmp_path):
    server, baseline = fixture_server()
    original = deepcopy(baseline)
    install_source_fixture(server, tmp_path)
    body = {"assemblyNumber": "MMLE-50D", "definitionId": "d1",
            "description": "Changed", "partNumber": "ZZZ"}
    with TestClient(server.app) as client:
        response = client.post("/__p1c/source-fixture", json=body)
        assert response.status_code == 200, response.text
        first = response.json()
        repeat = client.post("/__p1c/source-fixture", json=body)
        assert repeat.json() == first
    stored = json.loads((tmp_path / "source-fixture.json").read_bytes())
    assert len(stored["sourceRevision"]) == 64 and int(stored["sourceRevision"], 16) >= 0
    assert stored["sourceRevision"] != baseline["sourceRevision"]
    _, current = server._parts_manual_catalog_for_assembly("MMLE-50D")
    assert current["sourceRevision"] == stored["sourceRevision"]
    assert [r["occurrenceId"] for r in current["occurrences"]] == ["o2", "o1"]
    assert current["occurrences"][1]["description"] == "Changed"
    assert current["occurrences"][1]["partNumber"] == "ZZZ"
    assert baseline == original
    # Other assemblies and the source's objects are never patched in place.
    assert server._parts_manual_catalog_for_assembly("OTHER")[1] == baseline
    restarted, _ = fixture_server()
    install_source_fixture(restarted, tmp_path)
    assert restarted._parts_manual_catalog_for_assembly("MMLE-50D")[1] == current
    assert not (tmp_path / "source-fixture.tmp").exists()


def test_source_fixture_route_refuses_unknown_definition_without_a_write(tmp_path):
    server, baseline = fixture_server()
    install_source_fixture(server, tmp_path)
    with TestClient(server.app) as client:
        response = client.post("/__p1c/source-fixture", json={
            "assemblyNumber": "MMLE-50D", "definitionId": "missing", "description": "Changed", "partNumber": "ZZZ"})
        assert response.status_code == 422
        assert not (tmp_path / "source-fixture.json").exists()
        response = client.post("/__p1c/source-fixture", json={"assemblyNumber": "MMLE-50D"})
        assert response.status_code == 422
    assert server._parts_manual_catalog_for_assembly("MMLE-50D")[1] == baseline


def test_restart_relaunches_on_a_new_port_preserving_scratch_and_isolation(tmp_path, monkeypatch):
    import tests.smoke_documentation_editor as smoke

    instance = smoke.IsolatedDocumentationServer(tmp_path / "report")
    instance.output.mkdir()
    instance.scratch = tmp_path / "scratch"
    instance.code, instance.stores = instance.scratch / "c", instance.scratch / "d"
    instance.code.mkdir(parents=True)
    instance.stores.mkdir()
    sentinel = instance.stores / "keep.json"
    sentinel.write_text('{"keep": true}\n', encoding="ascii")
    calls = []

    class Process:
        def __init__(self):
            self.stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout):
            return 0

    def popen(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return Process()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return json.dumps({"snapshot": str(instance.code), "dotenvDisabled": True, "outboundBlocked": True,
                "roots": {name: str(instance.stores / short) for name, short in smoke.ROOT_NAMES.items()}}).encode("ascii")

    monkeypatch.setattr(smoke.subprocess, "Popen", popen)
    monkeypatch.setattr(smoke, "build_opener", lambda *_: SimpleNamespace(open=lambda *a, **k: Response()))
    instance._launch()
    old_process, old_url = instance.process, instance.url
    instance.restart()
    try:
        assert old_process.stopped
        assert instance.url != old_url
        assert sentinel.read_text("ascii") == '{"keep": true}\n'
        assert instance.isolation["snapshot"] == str(instance.code)
        assert len(calls) == 2
        assert all(Path(args[1]) == instance.code / "smoke_server.py" for args, _ in calls)
        assert all(kwargs["cwd"] == instance.code and kwargs["stderr"] == smoke.subprocess.STDOUT
                   for _, kwargs in calls)
        assert all(kwargs["creationflags"] == getattr(smoke.subprocess, "CREATE_NO_WINDOW", 0)
                   for _, kwargs in calls)
    finally:
        instance.stop()
    assert sentinel.exists()
