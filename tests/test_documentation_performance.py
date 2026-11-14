"""P5a-3: exact old/new answers, ownership and request-bounded reuse (no timing gates)."""
from contextlib import contextmanager
from copy import deepcopy
import ast
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import uuid
from unittest.mock import patch

import pytest

from ai_inspector.documentation import identity, refresh
from ai_inspector.documentation.commands import canonical_bytes
from ai_inspector.documentation.request_work import work_scope, mark_identified
from ai_inspector.parts_manual import documentation as scenes
from tests.test_documentation_refresh import mmle_client, MMLE_ROUTES
from tests.test_documentation_page_setup import _real
from tests.test_documentation_rich_text import RichScene, NUMBER, PAGE, OBJECT

ROOT = Path(__file__).resolve().parents[1]
BEFORE = "4669cd06834010b945f83dea84cac24795fab985"
_SOURCES = {}
MODULES = (
    "ai_inspector.documentation.identity", "ai_inspector.documentation.targets",
    "ai_inspector.documentation.refresh", "ai_inspector.documentation.conflict_exports",
    "ai_inspector.documentation.provenance", "ai_inspector.parts_manual.documentation",
    "ai_inspector.parts_manual.document", "ai_inspector.operations_manual.document",
    "ai_inspector.work_instructions.document", "ai_inspector.specification_sheet.document",
    "ai_inspector.parts_manual.artifacts", "ai_inspector.operations_manual.artifacts",
)


def original(relative):
    if relative not in _SOURCES:
        shown = subprocess.run(["git", "show", BEFORE + ":" + relative], cwd=ROOT,
            capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if shown.returncode != 0:
            # Supervisor: the comparison needs the commit before P5a-3. It ran at the P5a-3 gate; a clone or
            # a port without that commit skips it and keeps the tests below that need no old code.
            pytest.skip("the commit before P5a-3 (" + BEFORE[:7] + ") is not in this repository")
        _SOURCES[relative] = shown.stdout
    return _SOURCES[relative]


@contextmanager
def previous_path(monkeypatch):
    """Test-only old path, including local imports, without a checkout or old server startup.

    Use the current isolated roots/catalog fixture. Only definitions are loaded from server.py:
    no route registration, environment startup, saved sessions or real stores are touched.
    """
    import server
    with monkeypatch.context() as change:
        modules = {}
        for name in MODULES:
            current = importlib.import_module(name)
            relative = name.replace(".", "/") + ".py"
            alias = name + "_p5a2_oracle"
            module = types.ModuleType(alias)
            module.__file__, module.__package__ = str(ROOT / relative), current.__package__
            change.setitem(sys.modules, alias, module)
            exec(compile(original(relative), relative, "exec"), module.__dict__)
            # Preserve generated manuscript providers installed by this test, not old product definitions.
            for key, value in vars(current).items():
                if callable(value) and getattr(value, "__module__", "").startswith(("tests.", "unittest.mock")):
                    setattr(module, key, value)
            modules[name] = module
            change.setitem(sys.modules, name, module)
            change.setattr(sys.modules[current.__package__], name.rsplit(".", 1)[-1], module)
        namespace = dict(vars(server))
        for key, value in list(namespace.items()):
            owner = modules.get(getattr(value, "__module__", ""))
            if owner is not None and hasattr(owner, getattr(value, "__name__", "")):
                namespace[key] = getattr(owner, value.__name__)
        definitions = []
        for node in ast.parse(original("server.py").decode("utf-8-sig")).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                current = getattr(server, node.name, None)
                if callable(current) and getattr(current, "__module__", "server") != "server":
                    continue  # The synthetic catalogue/provider supplied by this test.
                node.decorator_list = []  # No FastAPI registration or process-wide caches in the oracle.
                definitions.append(node)
            elif isinstance(node, ast.ClassDef) and node.name in {"_DocumentationDocument", "_DocumentationAgentHost"}:
                definitions.append(node)
        tree = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                               *definitions], type_ignores=[])
        exec(compile(ast.fix_missing_locations(tree), "p5a2_server_definitions", "exec"), namespace)
        yield namespace, modules


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    from tools.documentation_benchmark_support import prepare
    root = tmp_path_factory.mktemp("p5a3")
    values = {}
    with patch.dict(os.environ, {"INSPECTORPRO_DOCUMENTATION_RICH_TEXT": "1"}):
        for kind in ("parts", "operations"):
            for authored in (False, True):
                folder = root / (kind[0] + str(int(authored)))
                inputs = prepare(folder, kind, 12 if authored else 1)
                values[kind, authored] = folder, inputs
    return values


def install_generated(monkeypatch, folder, inputs):
    import server
    from ai_inspector.operations_manual import document
    from tools.documentation_benchmark_support import sections
    for key in ("PARTS_MANUAL_ROOT", "OPERATIONS_MANUAL_ROOT", "WORK_INSTRUCTION_ROOT", "SPECIFICATION_SHEET_ROOT"):
        monkeypatch.setattr(server, key, folder)
    monkeypatch.setattr(server, "OPERATIONS_MANUAL_EVIDENCE_ROOT", folder / "e" / "source")
    monkeypatch.setattr(server, "_parts_manual_catalog_for_assembly", lambda number: (deepcopy(inputs["profile"]), deepcopy(inputs["catalog"])))
    monkeypatch.setattr(document, "prototype_sections", lambda *args, **kwargs: sections(inputs["sections"]))
    return server


@pytest.mark.parametrize("kind", ["parts", "operations"])
@pytest.mark.parametrize("authored", [False, True])
@pytest.mark.parametrize("rich_flag", ["0", "1"])
def test_generated_scene_response_exactly_matches_before(monkeypatch, generated, kind, authored, rich_flag):
    folder, inputs = generated[kind, authored]
    server = install_generated(monkeypatch, folder, inputs)
    monkeypatch.setenv("INSPECTORPRO_DOCUMENTATION_RICH_TEXT", rich_flag)
    name = kind + "_manual_documentation_scene_get"
    current = getattr(server, name)("BENCH")
    assert isinstance(current, dict), getattr(current, "body", current)
    with previous_path(monkeypatch) as (old, _):
        expected = old[name]("BENCH")
    assert canonical_bytes(current) == canonical_bytes(expected)
    # Returning a caller-owned document is still part of the API contract.
    current["document"]["pages"][0]["title"] = "Caller mutation"
    assert canonical_bytes(getattr(server, name)("BENCH")) == canonical_bytes(expected)


@pytest.mark.parametrize("kind,route", MMLE_ROUTES)
@pytest.mark.parametrize("rich_flag", ["0", "1"])
def test_mmle_scene_response_exactly_matches_before(mmle_client, monkeypatch, kind, route, rich_flag):
    monkeypatch.setenv("INSPECTORPRO_DOCUMENTATION_RICH_TEXT", rich_flag)
    current = _real(mmle_client, route)
    with previous_path(monkeypatch) as (old, _):
        expected = old[route.replace("-", "_") + "_documentation_scene_get"]("MMLE-50D")
    assert canonical_bytes(current) == canonical_bytes(expected)


def test_read_derivations_are_request_local_and_mutation_safe(tmp_path, monkeypatch):
    fixture = RichScene(tmp_path)
    before = fixture.load()
    reads = []
    read_text = Path.read_text
    def counted(path, *args, **kwargs):
        if path == fixture.path:
            reads.append(path)
        return read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", counted)
    with work_scope():
        first = fixture.load()
        first["scene"]["pages"].clear()
        second = fixture.load()
        assert canonical_bytes(second) == canonical_bytes(before)
        assert len(reads) == 1
        # A completed command replaces the file inside this same request. The pre-image cache must miss.
        changed = fixture.repo.apply_command(NUMBER, "source-a", "plan-a", base_revision=second["revision"],
            identity_document=fixture.base, page_targets={PAGE: {"document_object": [OBJECT]}},
            command={"operation": "update_text", "pageId": PAGE, "targetType": "document_object", "targetId": OBJECT, "text": "Changed"})
        assert fixture.load()["scene"] == changed["scene"]
        assert len(reads) == 2
    fixture.load()
    assert len(reads) == 3  # No store/cache authority survives a request.


def test_catalogue_inventory_once_per_identical_input_and_recomputed_after_mutation(monkeypatch):
    from tests.test_documentation_refresh import source_document
    raw = source_document()
    counts = {"compile": 0, "targets": 0}
    compiler = identity.compile_identities
    from ai_inspector.documentation import targets
    target_reader = targets.text_targets
    def compile_counted(value, **kwargs):
        counts["compile"] += 1
        return compiler(value, **kwargs)
    def targets_counted(*args, **kwargs):
        counts["targets"] += 1
        return target_reader(*args, **kwargs)
    monkeypatch.setattr(identity, "compile_identities", compile_counted)
    monkeypatch.setattr(refresh, "compile_identities", compile_counted)
    monkeypatch.setattr(targets, "text_targets", targets_counted)
    with work_scope():
        document = identity.compile_identities(raw)
        first = identity.catalog_from(document)
        first["identities"].clear()
        assert identity.catalog_from(document)["identities"]
        before = refresh.inventory(document)
        before.clear()
        assert refresh.inventory(document)
        assert counts == {"compile": 1, "targets": 1}
        document["pages"][0]["layoutBlocks"][0]["rows"].reverse()
        assert identity.catalog_from(document) != first
        assert counts["compile"] == 2


def _transaction_sequence(repo, baseline, monkeypatch, scene_module):
    numbers = iter(range(1, 100))
    monkeypatch.setattr(scene_module, "_utc_now", lambda: "2026-11-14T00:00:00.000000Z")
    monkeypatch.setattr(scene_module.secrets, "token_hex", lambda n: format(next(numbers), "x").zfill(n * 2))
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=next(numbers)))
    args = (NUMBER, "source-a", "plan-a")
    loaded = repo.read(*args, identity_document=baseline)
    results = []
    for action in ("edit", "undo", "redo"):
        if action == "edit":
            loaded = repo.apply_command(*args, base_revision=loaded["revision"], identity_document=baseline,
                page_targets={PAGE: {"document_object": [OBJECT]}}, command={"operation": "update_text",
                    "pageId": PAGE, "targetType": "document_object", "targetId": OBJECT, "text": "New text"})
        else:
            loaded = repo.move_history(*args, base_revision=loaded["revision"], direction=action, identity_document=baseline)
        results.append((canonical_bytes(loaded), repo._scene_path(NUMBER).read_bytes()))
    return results


def test_commands_undo_redo_keep_the_exact_store_and_answer(tmp_path, monkeypatch):
    fixture = RichScene(tmp_path / "seed")
    original_bytes = fixture.path.read_bytes()
    for directory in (tmp_path / "new", tmp_path / "old"):
        path = directory / NUMBER.lower() / "documentation-scene.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(original_bytes)
    with monkeypatch.context() as change:
        current = _transaction_sequence(scenes.DocumentationSceneRepository(tmp_path / "new", "operations_and_maintenance_manual"),
            fixture.base, change, scenes)
    with previous_path(monkeypatch) as (_, modules), monkeypatch.context() as change:
        previous = modules[scenes.__name__]
        expected = _transaction_sequence(previous.DocumentationSceneRepository(tmp_path / "old", "operations_and_maintenance_manual"),
            fixture.base, change, previous)
    assert current == expected


@pytest.mark.parametrize("kind", ["parts", "operations"])
def test_object_snapshot_matches_full_read_without_editor_target_work(monkeypatch, generated, kind):
    folder, inputs = generated[kind, True]
    server = install_generated(monkeypatch, folder, inputs)
    document_type = inputs["kind"]
    from tools.documentation_benchmark_support import KINDS
    from ai_inspector.documentation.objects import read_objects
    host = server._DocumentationAgentHost()
    full = host.document_snapshot("BENCH", KINDS[document_type])
    with previous_path(monkeypatch) as (old, _):
        previous = old["_DocumentationAgentHost"]().document_snapshot("BENCH", KINDS[document_type])
    assert canonical_bytes(full) == canonical_bytes(previous)
    page_ids = [p["pageId"] for p in full["document"]["pages"] if p.get("documentationObjects")][:8]
    expected = read_objects(full, page_ids, folder, "BENCH")
    def no_targets(*args, **kwargs):
        raise AssertionError("Object snapshots must not build an editor's target inventory")
    monkeypatch.setattr(server, "_documentation_editor_read", no_targets)
    monkeypatch.setattr(server, "documentation_text_targets", no_targets)
    assert host.read_document_objects("BENCH", KINDS[document_type], page_ids) == expected


def _object_batch_sequence(repo, baseline, state, document, monkeypatch, scene_module):
    from ai_inspector.documentation import objects
    numbers = iter(range(101, 200))
    monkeypatch.setattr(scene_module, "_utc_now", lambda: "2026-11-14T00:00:00.000000Z")
    monkeypatch.setattr(scene_module.secrets, "token_hex", lambda n: format(next(numbers), "x").zfill(n * 2))
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=next(numbers)))
    obj = state["scene"]["pages"][PAGE]["documentObjects"][OBJECT]
    operations = [{"operation": "set_object_frame", "pageId": PAGE, "objectId": OBJECT,
                   "expectedObjectHash": objects.object_hash(obj), "x": x} for x in (.2, .3)]
    commands, expected, current, results = objects.prepare_batch(state["scene"], document, operations, state["revision"])
    args = (NUMBER, "source-a", "plan-a")
    options = dict(base_revision=state["sceneRevision"], expected_revision=state["revision"], request_id="same-nudge",
        commands=commands, page_targets={PAGE: {"document_object": [OBJECT]}}, expected_hashes=expected,
        current_hashes=current, hashes_revision=state["sceneRevision"], object_results=results, identity_document=baseline)
    answers = []
    for retry in (False, True):
        loaded = repo.apply_batch(*args, **options)
        answers.append((canonical_bytes(loaded), repo._scene_path(NUMBER).read_bytes()))
    assert answers[0][1] == answers[1][1]
    for direction in ("undo", "redo"):
        loaded = repo.move_history(*args, base_revision=loaded["revision"], direction=direction, identity_document=baseline)
        answers.append((canonical_bytes(loaded), repo._scene_path(NUMBER).read_bytes()))
    return answers


def test_object_batch_retry_undo_redo_keep_the_exact_store_and_answer(tmp_path, monkeypatch):
    fixture = RichScene(tmp_path / "seed")
    state, document, _ = fixture.snapshot()
    raw = fixture.path.read_bytes()
    for directory in (tmp_path / "new", tmp_path / "old"):
        path = directory / NUMBER.lower() / "documentation-scene.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(raw)
    with monkeypatch.context() as change:
        current = _object_batch_sequence(scenes.DocumentationSceneRepository(tmp_path / "new", "operations_and_maintenance_manual"),
            fixture.base, state, document, change, scenes)
    with previous_path(monkeypatch) as (_, modules), monkeypatch.context() as change:
        previous = modules[scenes.__name__]
        expected = _object_batch_sequence(previous.DocumentationSceneRepository(tmp_path / "old", "operations_and_maintenance_manual"),
            fixture.base, state, document, change, previous)
    assert current == expected


def test_command_and_history_read_scene_json_once_and_reuse_generated_derivations(tmp_path, monkeypatch):
    fixture = RichScene(tmp_path)
    loaded = fixture.load()
    reads, compiles, inventories = [], [], []
    original_read = Path.read_text
    original_compile = identity.compile_identities
    original_inventory = refresh.inventory.__wrapped__
    def read_counted(path, *args, **kwargs):
        if path == fixture.path:
            reads.append(path)
        return original_read(path, *args, **kwargs)
    def compile_counted(*args, **kwargs):
        compiles.append(1)
        return original_compile(*args, **kwargs)
    # Count actual builds, not requests served from the request-local memo.
    from ai_inspector.documentation.request_work import memoized
    def inventory_counted(*args, **kwargs):
        inventories.append(1)
        return original_inventory(*args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read_counted)
    monkeypatch.setattr(identity, "compile_identities", compile_counted)
    monkeypatch.setattr(refresh, "compile_identities", compile_counted)
    monkeypatch.setattr(refresh, "inventory", memoized(inventory_counted))
    for action in ("edit", "undo", "redo"):
        reads.clear(); compiles.clear(); inventories.clear()
        if action == "edit":
            loaded = fixture.repo.apply_command(NUMBER, "source-a", "plan-a", base_revision=loaded["revision"],
                identity_document=fixture.base, page_targets={PAGE: {"document_object": [OBJECT]}},
                command={"operation": "update_text", "pageId": PAGE, "targetType": "document_object", "targetId": OBJECT,
                         "text": "One JSON read"})
        else:
            loaded = fixture.repo.move_history(NUMBER, "source-a", "plan-a", base_revision=loaded["revision"],
                identity_document=fixture.base, direction=action)
        assert len(reads) == 1, (action, reads)
        assert len(compiles) <= 1, (action, compiles)
        assert len(inventories) <= 1, (action, inventories)


@pytest.mark.parametrize("rich_flag", ["0", "1"])
def test_provenance_reuses_only_equal_source_and_effective_targets(tmp_path, monkeypatch, rich_flag):
    from ai_inspector.documentation import provenance
    monkeypatch.setenv("INSPECTORPRO_DOCUMENTATION_RICH_TEXT", rich_flag)
    fixture = RichScene(tmp_path)
    with monkeypatch.context() as flags:
        flags.setenv("INSPECTORPRO_DOCUMENTATION_RICH_TEXT", "1")
        fixture.edit()
    for command in (None, {"operation": "update_text", "pageId": PAGE, "targetType": "page_element",
                          "targetId": "generated-note", "text": "An edited generated value"}):
        if command:
            loaded = fixture.load()
            fixture.repo.apply_command(NUMBER, "source-a", "plan-a", base_revision=loaded["revision"],
                command=command, identity_document=fixture.base, page_targets={PAGE: {"page_element": ["generated-note"]}})
        state, document, _ = fixture.snapshot()
        expected_input = deepcopy(document)
        current = provenance.project_document(document, state["scene"])
        assert document == expected_input  # Public projection still owns its output.
        with previous_path(monkeypatch) as (_, modules):
            expected = modules[provenance.__name__].project_document(document, state["scene"])
        assert canonical_bytes(current) == canonical_bytes(expected)
