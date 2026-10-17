"""Synthetic contract tests, not reviewed manufacturing or live-Sage acceptance."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.design_brief import canonical_design_bytes, design_revision
from ai_inspector.facility_layout.design_repository import FacilityDesignRepositoryNotFoundError
from ai_inspector.facility_layout.g1_planner import compile_g1_envelope_operations
from ai_inspector.facility_layout.generation_requirement_repository import GenerationRequirementRepository
from ai_inspector.facility_layout.generation_requirements import (
    EMPTY_COLLECTIONS,
    GENERATION_LEDGER_SCHEMA,
    GenerationRequirementError,
    build_generation_ledger,
    evaluate_generation_requirements,
    guard_empty_generation_base,
    guard_generation_operations,
    validate_generation_amendment,
    validate_generation_ledger,
)
from ai_inspector.facility_layout.operations import apply_facility_layout_operations, create_layout_document


def base():
    return create_layout_document(
        layout_id="fl-generation-contract", display_name="Isolated empty layout",
        association={"siteId": "site-test"},
        coordinate_frame={"units": "m", "handedness": "right", "upAxis": "+Y",
                          "floorAxes": ["+X", "+Z"], "datumId": "datum-test", "floorElevation": 0},
        source_shell_ref={"shellId": "shell-test", "shellRevision": "a" * 64,
                          "coordinateFrameFingerprint": "b" * 64},
        policy_set_ref={"policySetId": "policy-test", "policySetRevision": "c" * 64},
        created_at="2026-09-17T12:00:00Z",
    )


def editor(document):
    digest = layout_revision(document)
    return {"baseRevision": digest, "draftRevision": digest, "dirty": False,
            "conflicted": False, "pending": False, "generationRunId": None, "designTransactionId": None}


def quantity_requirement(key, turn_id, text, quantity):
    return {"requirementId": key, "source": {"turnId": turn_id, "start": 0, "end": len(text)},
            "kind": "hard_constraint", "disposition": "represented",
            "predicate": {"kind": "resource_quantity", "subjectId": "assembly-benches",
                          "parameters": {"quantity": quantity}},
            "reason": None, "supersededBy": []}


def body():
    text = "Use two assembly benches."
    return {"schemaVersion": GENERATION_LEDGER_SCHEMA, "ledgerId": "gl-test",
            "tenantId": "tenant-test", "siteId": "site-test", "workspaceId": "workspace-test",
            "layoutId": base()["layoutId"], "baseRevision": layout_revision(base()),
            "authoringMode": "new_empty_layout", "parentLedgerRevision": None,
            "sourceRefs": [{"sourceKind": "process_map", "sourceId": "process-synthetic", "sourceRevision": "d" * 64}],
            "turns": [{"turnId": "turn-1", "text": text}],
            "requirements": [quantity_requirement("R-1", "turn-1", text, 2)]}


def amended(before, *, count=3, request_turn="turn-2"):
    after = {key: deepcopy(value) for key, value in before.items() if key != "ledgerRevision"}
    after["parentLedgerRevision"] = before["ledgerRevision"]
    text = f"Use {count} assembly benches instead."
    after["turns"].append({"turnId": request_turn, "text": text})
    after["requirements"][0].update(disposition="superseded", reason="User changed the quantity.", supersededBy=["R-2"])
    after["requirements"].append(quantity_requirement("R-2", request_turn, text, count))
    return build_generation_ledger(after)


def commit(repo, record, key="request-1", refs=()):
    return repo.commit_ledger(tenant_id="tenant-test", site_id="site-test", ledger=record,
                              expected_ledger_revision=record["parentLedgerRevision"],
                              request_key=key, artifact_refs=refs)


def assert_error(code, fn):
    with pytest.raises(GenerationRequirementError) as exc:
        fn()
    assert exc.value.code == code


@pytest.mark.parametrize("omitted", ["and", "but not both", "."])
def test_coverage_recovery_locates_exact_omission_without_changing_requirements(omitted):
    request = body()
    text = "Use tables and lifts. Read summaries " + omitted + " read the manual."
    request["turns"][0]["text"] = text
    start = len("Use tables and lifts. Read summaries ")
    left = request["requirements"][0]
    left["source"]["end"] = start
    right = deepcopy(left)
    right.update(requirementId="R-2")
    right["source"].update(start=start + len(omitted), end=len(text))
    request["requirements"].append(right)
    before = deepcopy(request)
    with pytest.raises(GenerationRequirementError) as caught:
        build_generation_ledger(request)
    assert caught.value.code == "generation_requirement_clause_unaccounted"
    gap, = caught.value.details["uncovered"]
    assert gap["start"] == start and gap["text"] == omitted
    context = gap["context"]
    assert context["text"] == text[context["start"]:context["end"]]
    assert len(context["text"]) <= 240
    assert "Read summaries" in context["text"]
    assert request == before


def test_clean_base_and_pure_kernel_generation_leave_original_unchanged():
    document = base()
    before = canonical_design_bytes(document)
    state = editor(document)
    guard_empty_generation_base(document, expected_revision=state["baseRevision"], editor_context=state)
    plan = compile_g1_envelope_operations(document, {
        "width": 40, "depth": 30, "sourceUnit": "m", "displayName": "New isolated preview", "gridSize": 1,
    })
    guard_generation_operations(plan["operations"])
    result = apply_facility_layout_operations(document, plan["operations"], base_revision=state["baseRevision"])
    assert result["document"]["displayName"] == "New isolated preview"
    assert layout_revision(result["document"]) != state["baseRevision"]
    assert canonical_design_bytes(document) == before
    guard_empty_generation_base(result["document"], expected_revision=layout_revision(result["document"]),
                                editor_context=editor(result["document"]))


@pytest.mark.parametrize("collection", EMPTY_COLLECTIONS)
def test_every_nonempty_collection_refuses_before_geometry_validation(collection):
    document = base()
    state = editor(document)
    document[collection] = ["existing-reference"]
    assert_error("generation_base_not_empty", lambda: guard_empty_generation_base(
        document, expected_revision=state["baseRevision"], editor_context=state))


@pytest.mark.parametrize("field,value", [("dirty", True), ("dirty", 0), ("pending", True),
                                         ("conflicted", True), ("generationRunId", "run-1"),
                                         ("designTransactionId", "transaction-1")])
def test_dirty_or_active_editor_refuses(field, value):
    document = base()
    state = editor(document)
    state[field] = value
    assert_error("generation_editor_not_clean", lambda: guard_empty_generation_base(
        document, expected_revision=layout_revision(document), editor_context=state))


@pytest.mark.parametrize("mode", ["authorized_replacement", "incremental_revision", None])
def test_other_authoring_modes_remain_disabled(mode):
    document = base()
    assert_error("generation_authoring_mode_unsupported", lambda: guard_empty_generation_base(
        document, expected_revision=layout_revision(document), editor_context=editor(document), mode=mode))


@pytest.mark.parametrize("extension", [{"facilityNavigation": {}}, {"unknown": {}}, {"facilityPlan": {}, "other": {}}])
def test_unknown_or_content_bearing_extensions_are_not_empty(extension):
    document = base()
    state = editor(document)
    document["extensions"] = extension
    assert_error("generation_base_extension_unsupported", lambda: guard_empty_generation_base(
        document, expected_revision=state["baseRevision"], editor_context=state))


def test_unknown_root_field_and_stale_editor_refuse():
    document = base()
    state = editor(document)
    document["futureContent"] = []
    assert_error("generation_base_extension_unsupported", lambda: guard_empty_generation_base(
        document, expected_revision=state["baseRevision"], editor_context=state))
    document.pop("futureContent")
    state["draftRevision"] = "0" * 64
    assert_error("generation_base_revision_conflict", lambda: guard_empty_generation_base(
        document, expected_revision=layout_revision(document), editor_context=state))


@pytest.mark.parametrize("operation", ["clear_layout_contents", "delete_placement", "archive_layout",
                                       "set_facility_navigation", "attach_process_binding", "unknown", []])
def test_unsupported_operations_fail_even_on_an_empty_base(operation):
    assert_error("generation_operation_unsupported", lambda: guard_generation_operations([{"op": operation}]))


def test_operation_guard_does_not_expand_the_kernel_batch_budget():
    operation = {"op": "rename_layout", "displayName": "Test"}
    guard_generation_operations([operation] * 500)
    assert_error("generation_requirement_budget_exceeded", lambda: guard_generation_operations([operation] * 501))


def test_ledger_is_closed_revision_bound_and_key_order_independent():
    request = body()
    before = deepcopy(request)
    record = build_generation_ledger(request)
    assert request == before
    reordered = json.loads(json.dumps(request, sort_keys=True))
    assert build_generation_ledger(reordered) == record
    assert validate_generation_ledger(record) == record
    changed = deepcopy(record)
    changed["requirements"][0]["predicate"]["parameters"]["quantity"] = 3
    assert_error("generation_requirement_integrity_mismatch", lambda: validate_generation_ledger(changed))
    request["productionEligible"] = True
    assert_error("generation_requirement_fields_invalid", lambda: build_generation_ledger(request))


def test_unconsumed_qualifier_requires_a_retained_blocker():
    request = body()
    request["turns"][0]["text"] += " Keep the unknown aisle fixed."
    assert_error("generation_requirement_clause_unaccounted", lambda: build_generation_ledger(request))
    start = request["requirements"][0]["source"]["end"]
    request["requirements"].append({"requirementId": "R-unknown",
        "source": {"turnId": "turn-1", "start": start, "end": len(request["turns"][0]["text"])},
        "kind": "hard_constraint", "disposition": "needs_clarification", "predicate": None,
        "reason": "Aisle identity is unresolved and preservation is unsupported.", "supersededBy": []})
    record = build_generation_ledger(request)
    result = evaluate_generation_requirements(record, {"equipmentRequirements": [{"requirementId": "assembly-benches", "quantity": 2}]})
    assert not result["requirementsSatisfied"]
    assert result["checks"][-1]["code"] == "generation_requirement_unresolved"
    assert not result["admissionGranted"]


@pytest.mark.parametrize("count", [0, -1, 901, True, 2.0, "2", None])
def test_invalid_quantities_refuse(count):
    request = body()
    request["requirements"][0]["predicate"]["parameters"]["quantity"] = count
    assert_error("generation_requirement_number_invalid", lambda: build_generation_ledger(request))


def test_unregistered_predicate_cannot_be_marked_represented():
    request = body()
    request["requirements"][0]["predicate"]["kind"] = "retain_required_adjacency"
    assert_error("generation_requirement_predicate_unsupported", lambda: build_generation_ledger(request))


def test_dimensions_compare_units_without_inventing_a_tolerance():
    request = body()
    request["requirements"][0]["predicate"] = {"kind": "envelope_dimensions", "subjectId": request["layoutId"],
                                              "parameters": {"width": 40, "depth": 30, "sourceUnit": "m"}}
    record = build_generation_ledger(request)
    package = {"facilityEnvelope": {"width": 40000, "depth": 30000, "sourceUnit": "mm"}}
    assert evaluate_generation_requirements(record, package)["requirementsSatisfied"]
    package["facilityEnvelope"]["width"] += 1
    assert not evaluate_generation_requirements(record, package)["requirementsSatisfied"]
    assert not evaluate_generation_requirements(record, {"facilityEnvelope": None})["requirementsSatisfied"]


@pytest.mark.parametrize("dimensions", [
    {"width": True, "depth": 30, "sourceUnit": "m"},
    {"width": 0, "depth": 30, "sourceUnit": "m"},
    {"width": 10001, "depth": 30, "sourceUnit": "m"},
])
def test_invalid_dimensions_refuse(dimensions):
    request = body()
    request["requirements"][0]["predicate"] = {"kind": "envelope_dimensions", "subjectId": request["layoutId"],
                                              "parameters": dimensions}
    assert_error("generation_requirement_number_invalid", lambda: build_generation_ledger(request))


def test_preview_permission_cannot_authorize_save():
    request = body()
    request["requirements"][0]["kind"] = "permission"
    request["requirements"][0]["predicate"] = {"kind": "unsaved_preview", "subjectId": request["layoutId"],
                                              "parameters": {"saveAllowed": True}}
    assert_error("generation_requirement_authority_invalid", lambda: build_generation_ledger(request))


def test_ambiguous_duplicate_resource_is_not_a_match():
    record = build_generation_ledger(body())
    matching = {"requirementId": "assembly-benches", "quantity": 2}
    assert not evaluate_generation_requirements(record, {"equipmentRequirements": [matching, matching]})["requirementsSatisfied"]
    assert not evaluate_generation_requirements(record, {"equipmentRequirements": [{**matching, "quantity": True}]})["requirementsSatisfied"]


def test_explicit_correction_preserves_old_requirements_and_advances_predicate():
    before = build_generation_ledger(body())
    after = amended(before)
    validate_generation_amendment(before, after)
    assert after["requirements"][0]["predicate"] == before["requirements"][0]["predicate"]
    assert evaluate_generation_requirements(after, {"equipmentRequirements": [{"requirementId": "assembly-benches", "quantity": 3}]})["requirementsSatisfied"]
    assert not evaluate_generation_requirements(after, {"equipmentRequirements": [{"requirementId": "assembly-benches", "quantity": 2}]})["requirementsSatisfied"]


def test_correction_cannot_drop_history_or_change_immutable_base():
    before = build_generation_ledger(body())
    after = amended(before)
    draft = {key: value for key, value in after.items() if key != "ledgerRevision"}
    draft["baseRevision"] = "0" * 64
    assert_error("generation_requirement_parent_conflict", lambda: validate_generation_amendment(before, build_generation_ledger(draft)))
    draft["baseRevision"] = before["baseRevision"]
    draft["turns"] = draft["turns"][1:]
    draft["requirements"] = draft["requirements"][1:]
    assert_error("generation_requirement_history_changed", lambda: validate_generation_amendment(before, build_generation_ledger(draft)))


def test_conflicting_active_counts_fail_without_supersession():
    before = build_generation_ledger(body())
    after = amended(before)
    draft = {key: value for key, value in after.items() if key != "ledgerRevision"}
    draft["requirements"][0] = before["requirements"][0]
    assert_error("generation_requirement_conflict", lambda: build_generation_ledger(draft))


def test_durable_retry_returns_original_even_after_new_head(tmp_path):
    repo = GenerationRequirementRepository(tmp_path)
    first = build_generation_ledger(body())
    commit(repo, first)
    second = amended(first)
    commit(repo, second, "request-2")
    restarted = GenerationRequirementRepository(tmp_path)
    retried = commit(restarted, json.loads(json.dumps(first, sort_keys=True)))
    assert retried["ledger"] == first
    assert not retried["isCurrent"]
    assert len(retried["head"]["commits"]) == 2
    assert_error("generation_ledger_superseded", lambda: restarted.require_current_ledger(
        "tenant-test", "site-test", first["ledgerId"], first["ledgerRevision"]))
    assert restarted.require_current_ledger("tenant-test", "site-test", second["ledgerId"], second["ledgerRevision"])["isCurrent"]


def test_retry_conflict_and_stale_correction_do_not_advance_head(tmp_path):
    repo = GenerationRequirementRepository(tmp_path)
    first = build_generation_ledger(body())
    commit(repo, first)
    changed = body()
    changed["requirements"][0]["predicate"]["parameters"]["quantity"] = 3
    assert_error("generation_ledger_idempotency_conflict", lambda: commit(repo, build_generation_ledger(changed)))
    second = amended(first)
    commit(repo, second, "request-2")
    assert_error("generation_ledger_revision_conflict", lambda: commit(repo, amended(first, count=4), "request-3"))
    assert repo.get_ledger("tenant-test", "site-test", first["ledgerId"])["ledger"] == second


def test_competing_repository_instances_have_one_cas_winner(tmp_path):
    first = build_generation_ledger(body())
    commit(GenerationRequirementRepository(tmp_path), first)

    def writer(count):
        try:
            return commit(GenerationRequirementRepository(tmp_path), amended(first, count=count), f"request-{count}")["isCurrent"]
        except GenerationRequirementError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, [3, 4]))
    assert results.count(True) == 1
    assert results.count("generation_ledger_revision_conflict") == 1


@pytest.mark.parametrize("after_commit", [False, True])
def test_head_write_failure_and_lost_response_retry(tmp_path, monkeypatch, after_commit):
    repo = GenerationRequirementRepository(tmp_path)
    first = build_generation_ledger(body())
    commit(repo, first)
    second = amended(first)
    atomic = repo._atomic_write

    def fail_head(path, value):
        if path.name == "head.json":
            if after_commit:
                atomic(path, value)
            raise OSError("Injected interruption at head commit")
        atomic(path, value)

    monkeypatch.setattr(repo, "_atomic_write", fail_head)
    with pytest.raises(OSError):
        commit(repo, second, "request-2")
    restarted = GenerationRequirementRepository(tmp_path)
    current = restarted.get_ledger("tenant-test", "site-test", first["ledgerId"])
    assert current["ledger"] == (second if after_commit else first)
    if not after_commit:
        assert_error("generation_ledger_revision_uncommitted", lambda: restarted.get_ledger(
            "tenant-test", "site-test", first["ledgerId"], ledger_revision=second["ledgerRevision"]))
    recovered = commit(restarted, second, "request-2")
    assert recovered["ledger"] == second
    assert len(recovered["head"]["commits"]) == 2


def test_ledger_dependencies_survive_correction_restart_and_artifact_collection(tmp_path):
    repo = GenerationRequirementRepository(tmp_path)
    evidence = {"kind": "synthetic-test-evidence", "value": 1}
    ref = {"artifactKind": "generation_source", "artifactId": "source-test", "artifactRevision": design_revision(evidence)}
    repo.store_artifact(tenant_id="tenant-test", site_id="site-test", artifact=evidence,
                       artifact_kind=ref["artifactKind"], artifact_id=ref["artifactId"], artifact_revision=ref["artifactRevision"])
    first = build_generation_ledger(body())
    commit(repo, first, refs=[ref])
    commit(repo, amended(first), "request-2")
    restarted = GenerationRequirementRepository(tmp_path)
    removed = restarted.collect_unpinned_artifacts("tenant-test", "site-test", older_than=datetime.now(timezone.utc) + timedelta(days=60))
    assert removed == []
    assert restarted.get_artifact("tenant-test", "site-test", ref["artifactKind"], ref["artifactId"], ref["artifactRevision"])["artifact"] == evidence
    assert restarted.get_ledger("tenant-test", "site-test", first["ledgerId"], ledger_revision=first["ledgerRevision"])["artifactRefs"] == [ref]


def test_wrong_namespace_and_missing_dependency_fail_without_head(tmp_path):
    repo = GenerationRequirementRepository(tmp_path)
    record = build_generation_ledger(body())
    assert_error("generation_ledger_scope_mismatch", lambda: repo.commit_ledger(
        tenant_id="another-tenant", site_id="site-test", ledger=record,
        expected_ledger_revision=None, request_key="request-1"))
    with pytest.raises(FacilityDesignRepositoryNotFoundError):
        commit(repo, record, refs=[{"artifactKind": "source", "artifactId": "missing", "artifactRevision": "0" * 64}])
    with pytest.raises(FacilityDesignRepositoryNotFoundError):
        repo.get_ledger("tenant-test", "site-test", record["ledgerId"])


def test_corrupt_head_fails_closed(tmp_path):
    repo = GenerationRequirementRepository(tmp_path)
    record = build_generation_ledger(body())
    commit(repo, record)
    path = repo._ledger_head_path("tenant-test", "site-test", record["ledgerId"])
    # Use the repository writer to simulate corrupted persisted data, not application mutation.
    repo._atomic_write(path, {"recordKind": "wrong"})
    assert_error("generation_ledger_head_corrupt", lambda: repo.get_ledger("tenant-test", "site-test", record["ledgerId"]))


@pytest.mark.parametrize("ledger_id", ["CON", "ledger:prototype", "LPT1", "Gl-Test"])
def test_ledger_identifiers_do_not_become_windows_paths(tmp_path, ledger_id):
    repo = GenerationRequirementRepository(tmp_path)
    request = body()
    request["ledgerId"] = ledger_id
    record = build_generation_ledger(request)
    assert commit(repo, record)["ledger"] == record
    root = repo._ledger_root("tenant-test", "site-test", ledger_id)
    assert root.is_relative_to(tmp_path)
    assert root.name == design_revision({"ledgerId": ledger_id})


def test_array_reordering_is_not_an_equivalent_retry(tmp_path):
    repo = GenerationRequirementRepository(tmp_path)
    request = body()
    request["sourceRefs"].append({"sourceKind": "catalog", "sourceId": "catalog-test", "sourceRevision": "e" * 64})
    commit(repo, build_generation_ledger(request))
    request["sourceRefs"].reverse()
    assert_error("generation_ledger_idempotency_conflict", lambda: commit(repo, build_generation_ledger(request)))


def test_revision_budget_refuses_before_writing_another_revision(tmp_path, monkeypatch):
    import ai_inspector.facility_layout.generation_requirement_repository as storage

    repo = GenerationRequirementRepository(tmp_path)
    record = build_generation_ledger(body())
    commit(repo, record)
    monkeypatch.setattr(storage, "MAX_LEDGER_REVISIONS", 1)
    assert_error("generation_ledger_revision_limit", lambda: commit(repo, amended(record), "request-2"))
    assert repo.get_ledger("tenant-test", "site-test", record["ledgerId"])["ledger"] == record


def test_revision_tampering_is_not_accepted_as_a_current_record(tmp_path):
    repo = GenerationRequirementRepository(tmp_path)
    record = build_generation_ledger(body())
    commit(repo, record)
    path = repo._ledger_path("tenant-test", "site-test", record["ledgerId"], record["ledgerRevision"])
    envelope = repo._read_ledger("tenant-test", "site-test", record["ledgerId"], record["ledgerRevision"])
    envelope["ledger"]["baseRevision"] = "0" * 64
    repo._atomic_write(path, envelope)
    assert_error("generation_ledger_record_corrupt", lambda: repo.get_ledger("tenant-test", "site-test", record["ledgerId"]))


@pytest.mark.parametrize("path,value", [
    (("sourceRefs", 0, "sourceKind"), []),
    (("sourceRefs", 0, "sourceRevision"), "not-a-revision"),
    (("requirements", 0, "source", "turnId"), {}),
    (("requirements", 0, "source", "start"), True),
    (("requirements", 0, "kind"), []),
    (("requirements", 0, "disposition"), {}),
    (("requirements", 0, "predicate", "kind"), []),
    (("requirements", 0, "predicate", "subjectId"), None),
    (("requirements", 0, "reason"), "Cannot silently attach a reason to an active check"),
    (("turns",), []),
    (("requirements",), []),
])
def test_malformed_semantic_fields_return_contract_errors(path, value):
    request = body()
    target = request
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(GenerationRequirementError):
        build_generation_ledger(request)


def test_ledger_payload_budget_is_enforced_before_storage():
    request = body()
    request["turns"][0]["text"] = "x" * 262145
    assert_error("generation_requirement_budget_exceeded", lambda: build_generation_ledger(request))


def test_failure_before_head_publish_keeps_referenced_artifact(tmp_path, monkeypatch):
    repo = GenerationRequirementRepository(tmp_path)
    artifact = {"synthetic": True, "kind": "captured-empty-base-test"}
    ref = {"artifactKind": "test_base", "artifactId": "base-test", "artifactRevision": design_revision(artifact)}
    repo.store_artifact(tenant_id="tenant-test", site_id="site-test", artifact=artifact,
                       artifact_kind=ref["artifactKind"], artifact_id=ref["artifactId"], artifact_revision=ref["artifactRevision"])
    atomic = repo._atomic_write

    def interrupt(path, value):
        if path.name == "head.json":
            raise OSError("Interrupted before the head commit")
        atomic(path, value)

    monkeypatch.setattr(repo, "_atomic_write", interrupt)
    record = build_generation_ledger(body())
    with pytest.raises(OSError):
        commit(repo, record, refs=[ref])
    restarted = GenerationRequirementRepository(tmp_path)
    assert restarted.collect_unpinned_artifacts("tenant-test", "site-test", older_than=datetime.now(timezone.utc) + timedelta(days=60)) == []
    with pytest.raises(FacilityDesignRepositoryNotFoundError):
        restarted.get_ledger("tenant-test", "site-test", record["ledgerId"])
    assert commit(restarted, record, refs=[ref])["ledger"] == record
