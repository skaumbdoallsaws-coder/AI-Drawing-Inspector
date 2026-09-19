"""Isolated compiler/service tests; synthetic source review, not live Sage qualification."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.design_brief import canonical_design_bytes
from ai_inspector.facility_layout.generation_admission import ADMISSION_KIND, PREVIEW_KIND, SOURCE_SCHEMA
from ai_inspector.facility_layout.generation_requirements import build_generation_ledger
from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
from tests.test_facility_generation_requirements import editor
from tests.test_facility_layout_facility_planning import _package


@pytest.fixture
def case(tmp_path, monkeypatch):
    host = LocalFacilityLayoutHost(tmp_path / "isolated", private_assets=False)
    saved = host.ensure_bootstrap()["layout"]["layout"]
    service = host.generation_admission_service
    principal = host.principal()
    package = _package()
    package["facilityEnvelope"].update(width=40, depth=30)
    package.update(cellRecipes=[], moduleFamilies=[], areaGroups=[])
    resource = package["equipmentRequirements"][0]
    resource.update(quantity=2, targetArea="Assembly")
    context = {key: deepcopy(package[key]) for key in ("productRef", "processSteps", "evidenceRegister", "sourcePackageRefs")}
    context.update(schemaVersion=SOURCE_SCHEMA, contextId="synthetic-reviewed-context",
                   processMapRef={"processMapId": "synthetic-process", "processMapRevision": "d" * 64},
                   equipmentMappings=[{key: resource["selectedCatalogIdentity"][key] for key in ("assetId", "assetDefinitionRevision")}])
    context["equipmentMappings"][0].update(processStepRefs=resource["processStepRefs"], evidenceRefs=resource["evidenceRefs"])
    graph = {"revision": "d" * 64, "document": {
        "productId": context["productRef"]["productId"], "mapId": "synthetic-process",
        "nodes": [{"nodeId": step["processStepId"]} for step in context["processSteps"]],
        "edges": [{"edgeId": f"edge-{index}", "fromNodeId": prior, "toNodeId": step["processStepId"]}
                  for index, step in enumerate(context["processSteps"]) for prior in step["predecessorProcessStepIds"]],
    }}
    monkeypatch.setattr(service, "resolve_process_map", lambda *args: deepcopy(graph))
    source_ref = service.publish_source_context(principal, site_id=LOCAL_SITE_ID, context=context)
    proposal = {key: deepcopy(package[key]) for key in (
        "packageId", "displayName", "facilityEnvelope", "departments", "areaGroups", "equipmentRequirements",
        "routes", "cellRecipes", "moduleFamilies", "floorCommunication", "presentationIntent")}
    requirements, turns = [], []

    def require(kind, subject, params, text):
        key = f"R-{len(requirements)}"
        turns.append({"turnId": key, "text": text})
        requirements.append({"requirementId": key, "source": {"turnId": key, "start": 0, "end": len(text)},
                             "kind": "hard_constraint" if kind != "unsaved_preview" else "permission",
                             "disposition": "represented", "predicate": {"kind": kind, "subjectId": subject, "parameters": params},
                             "reason": None, "supersededBy": []})

    require("envelope_dimensions", LOCAL_LAYOUT_ID, {"width": 40, "depth": 30, "sourceUnit": "m"}, "Use a 40 by 30 metre envelope.")
    require("unsaved_preview", LOCAL_LAYOUT_ID, {"saveAllowed": False}, "Preview only; do not save.")
    require("resource_quantity", resource["requirementId"], {"quantity": 2}, "Use two assembly workbenches.")
    require("resource_mapping", resource["requirementId"], {
        **{key: resource["selectedCatalogIdentity"][key] for key in ("assetId", "assetDefinitionRevision")},
        "processStepRefs": resource["processStepRefs"], "targetArea": resource["targetArea"]}, "Use the reviewed assembly workbench mapping in Assembly.")
    require("resource_pattern", resource["requirementId"], {key: resource[key] for key in ("placementPattern", "semanticOrientation")}, "Arrange assembly benches east-west in rows.")
    require("resource_spacing", resource["requirementId"], deepcopy(resource["authoredSpacing"]), "Use 1.5 metre spacing.")
    for department in package["departments"]:
        require("department_allocation", department["departmentId"], {key: department[key] for key in ("label", "zoneType", "areaShare", "row")},
                f"Use the specified allocation for {department['label']}.")
    ledger = build_generation_ledger({
        "schemaVersion": "facility-generation-requirement-ledger-v1", "ledgerId": "ledger-test",
        "tenantId": principal.tenant_id, "siteId": LOCAL_SITE_ID, "workspaceId": "workspace-test",
        "layoutId": LOCAL_LAYOUT_ID, "baseRevision": layout_revision(saved), "authoringMode": "new_empty_layout",
        "parentLedgerRevision": None, "turns": turns, "requirements": requirements,
        "sourceRefs": [{"sourceKind": kind, "sourceId": key, "sourceRevision": rev} for kind, key, rev in (
            ("evidence", source_ref["artifactId"], source_ref["artifactRevision"]),
            ("process_map", context["processMapRef"]["processMapId"], context["processMapRef"]["processMapRevision"]),
            ("product", context["productRef"]["productId"], context["productRef"]["productRevision"]))],
    })
    host.generation_requirement_repository.commit_ledger(tenant_id=principal.tenant_id, site_id=LOCAL_SITE_ID,
        ledger=ledger, expected_ledger_revision=None, request_key="ledger-request", artifact_refs=[source_ref])
    options = {"site_id": LOCAL_SITE_ID, "layout_id": LOCAL_LAYOUT_ID, "workspace_id": "workspace-test", "editor_context": editor(saved)}
    request = {"requestKey": "admit-1", "ledgerId": ledger["ledgerId"], "ledgerRevision": ledger["ledgerRevision"],
               "sourceContextRef": source_ref, "proposal": proposal}
    monkeypatch.setattr(host.service, "save_layout", lambda *args, **kwargs: pytest.fail("Preview called Save"))
    try:
        yield {"host": host, "service": service, "principal": principal, "context": context, "graph": graph,
               "ledger": ledger, "options": options, "request": request, "saved": deepcopy(saved)}
    finally:
        host.close()


def admitted(case):
    return case["service"].admit(case["principal"], **case["options"], request=case["request"])


def preview(case, admission=None, key="preview-1"):
    receipt = admission or admitted(case)
    request = {"requestKey": key, "admissionId": receipt["admissionId"], "admissionRevision": receipt["admissionRevision"]}
    return case["service"].preview(case["principal"], **case["options"], request=request)


def inspect(case, receipt):
    return case["service"].get_preview(case["principal"], **case["options"],
        preview_id=receipt["previewId"], preview_revision=receipt["previewRevision"])


def assert_code(code, action):
    with pytest.raises(Exception) as exc:
        action()
    assert getattr(exc.value, "code", None) == code, str(exc.value)


def correct(case, *, quantity=None, width=None, depth=None, extra_sources=()):
    previous = case["ledger"]
    body = {key: deepcopy(value) for key, value in previous.items() if key != "ledgerRevision"}
    body["parentLedgerRevision"] = previous["ledgerRevision"]
    body["sourceRefs"].extend(extra_sources)
    replacements = {}
    if quantity is not None:
        replacements["resource_quantity"] = {"quantity": quantity}
        case["request"]["proposal"]["equipmentRequirements"][0]["quantity"] = quantity
    if width is not None:
        replacements["envelope_dimensions"] = {"width": width, "depth": depth, "sourceUnit": "m"}
        case["request"]["proposal"]["facilityEnvelope"].update(width=width, depth=depth)
    for item in list(body["requirements"]):
        kind = item["predicate"]["kind"]
        if kind not in replacements or item["disposition"] != "represented":
            continue
        replacement = deepcopy(item)
        key = f"{item['requirementId']}-correction"
        text = f"Use {replacements[kind]} instead."
        replacement.update(requirementId=key, source={"turnId": key, "start": 0, "end": len(text)})
        replacement["predicate"]["parameters"] = replacements[kind]
        item.update(disposition="superseded", reason="Explicit synthetic correction", supersededBy=[key])
        body["requirements"].append(replacement)
        body["turns"].append({"turnId": key, "text": text})
    ledger = build_generation_ledger(body)
    case["host"].generation_requirement_repository.commit_ledger(tenant_id=case["principal"].tenant_id, site_id=LOCAL_SITE_ID,
        ledger=ledger, expected_ledger_revision=previous["ledgerRevision"], request_key=f"ledger-{ledger['ledgerRevision']}")
    case["ledger"] = ledger
    case["request"].update(ledgerRevision=ledger["ledgerRevision"], requestKey="admit-correction")
    return ledger


def test_real_compilation_preview_retry_and_saved_isolation(case, monkeypatch):
    admission = admitted(case)
    assert admission == admitted(case)
    first = preview(case, admission)
    result = inspect(case, first)
    assert result["counts"]["placements"] == 2
    assert result["counts"]["zones"] == 3
    assert result["counts"]["routes"] >= 1
    assert result["receiptChain"]
    assert result["validationStatus"] == "prototype_geometry_valid"
    assert result["validation"]["spatialDiagnostics"]["valid"] is True
    assert result["validation"]["routingDiagnostics"]["valid"] is True
    assert result["candidateRevision"] == layout_revision(result["candidateLayout"])
    assert result["candidateRevision"] != case["ledger"]["baseRevision"]
    assert result["saved"] is result["editorChanged"] is result["productionEligible"] is False
    monkeypatch.setattr(case["host"].service, "preview_operations", lambda *args: pytest.fail("Retry recompiled geometry"))
    assert preview(case, admission) == first
    current = case["host"].service.get_layout(case["principal"], LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["layout"]
    assert canonical_design_bytes(current) == canonical_design_bytes(case["saved"])
    assert not case["service"].leases.inspect(case["principal"].tenant_id, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["active"]


@pytest.mark.parametrize("location", ["root", "nested"])
def test_model_cannot_assign_authority(case, location):
    target = case["request"]["proposal"] if location == "root" else case["request"]["proposal"]["equipmentRequirements"][0]
    target["reviewStatus"] = "accepted"
    assert_code("generation_model_authority_forbidden", lambda: admitted(case))


@pytest.mark.parametrize("field", ["dirty", "conflicted", "pending"])
def test_dirty_editor_rejected(case, field):
    case["options"]["editor_context"][field] = True
    assert_code("generation_editor_not_clean", lambda: admitted(case))


def test_incorrect_quantity_rejected(case):
    case["request"]["proposal"]["equipmentRequirements"][0]["quantity"] = 3
    assert_code("generation_requirements_not_satisfied", lambda: admitted(case))


@pytest.mark.parametrize("value,code", [(None, "facility_design_process_map_unavailable"),
    ("revision", "facility_design_process_map_revision_mismatch"), ("identity", "facility_design_process_map_identity_mismatch")])
def test_process_authority_fails_closed(case, monkeypatch, value, code):
    result = deepcopy(case["graph"])
    if value is None:
        result = None
    elif value == "revision":
        result["revision"] = "a" * 64
    else:
        result["document"]["mapId"] = "another-map"
    monkeypatch.setattr(case["service"], "resolve_process_map", lambda *args: result)
    assert_code(code, lambda: admitted(case))


def test_catalog_revision_stale_rejected(case, monkeypatch):
    monkeypatch.setattr(case["service"], "catalog_provider", lambda *args: [])
    assert_code("generation_source_catalog_stale", lambda: admitted(case))


def test_review_requires_curator(case):
    editor_principal = replace(case["principal"], roles=("editor",))
    with pytest.raises(Exception) as exc:
        case["service"].publish_source_context(editor_principal, site_id=LOCAL_SITE_ID, context=case["context"])
    assert getattr(exc.value, "status_code", None) == 403


def test_feature_disabled_before_sources(case, monkeypatch):
    from ai_inspector.facility_layout.feature_flags import FacilityLayoutFeatureFlags
    gate = FacilityLayoutFeatureFlags.from_environment({}).require
    monkeypatch.setattr(case["service"], "require_capability", gate)
    monkeypatch.setattr(case["service"], "_bundle", lambda *args: pytest.fail("Accessed sources before feature check"))
    with pytest.raises(Exception) as exc:
        admitted(case)
    assert getattr(exc.value, "status_code", None) == 403


def test_http_preview_only_contract(case):
    app = FastAPI()
    app.include_router(case["host"].create_router())
    payload = {"workspaceId": "workspace-test", "editorContext": case["options"]["editor_context"], "request": case["request"]}
    url = f"/api/facility-layout-planning/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
    with TestClient(app) as client:
        response = client.post(f"{url}/admit", json=payload)
        assert response.status_code == 200, response.text
        admission = response.json()
        payload["request"] = {"requestKey": "http-preview", "admissionId": admission["admissionId"], "admissionRevision": admission["admissionRevision"]}
        response = client.post(f"{url}/preview", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["counts"]["placements"] == 2
        for action in ("apply", "save", "publish-source"):
            assert client.post(f"{url}/{action}", json=payload).status_code == 404


def test_quantity_correction_produces_new_candidate_from_same_base(case):
    admission_a = admitted(case)
    a = preview(case, admission_a)
    old_candidate = inspect(case, a)
    correct(case, quantity=3)
    assert_code("generation_ledger_superseded", lambda: preview(case, admission_a))
    assert_code("generation_ledger_superseded", lambda: inspect(case, a))
    admission_b = admitted(case)
    b = preview(case, admission_b, "preview-b")
    assert b["counts"]["placements"] == 3
    assert a["candidateRevision"] != b["candidateRevision"]
    retained_a = case["service"]._load(case["principal"], LOCAL_SITE_ID, LOCAL_LAYOUT_ID, "workspace-test", PREVIEW_KIND, a["previewId"])
    assert retained_a["candidateLayout"] == old_candidate["candidateLayout"]
    assert retained_a["baseRevision"] == case["ledger"]["baseRevision"]
    assert case["host"].service.get_layout(case["principal"], LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["layout"] == case["saved"]


@pytest.mark.parametrize("width,depth,count", [(32, 24, 3), (38, 28, 4)])
def test_new_dimensions_and_counts_need_no_candidate_coordinates(case, width, depth, count):
    correct(case, quantity=count, width=width, depth=depth)
    result = preview(case)
    assert result["counts"]["placements"] == count
    assert inspect(case, result)["candidateLayout"]["processBindings"] == []
    assert result["optimizationAvailable"] is False


def test_failed_corrected_preview_keeps_base_but_not_old_eligibility(case):
    old = preview(case)
    correct(case, width=41, depth=30)
    assert_code("generation_envelope_outside_authored_floor", lambda: preview(case, key="preview-too-wide"))
    assert_code("generation_ledger_superseded", lambda: inspect(case, old))
    assert case["host"].service.get_layout(case["principal"], LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["layout"] == case["saved"]


def test_unknown_source_not_silently_ignored(case):
    correct(case, quantity=3, extra_sources=[{"sourceKind": "evidence", "sourceId": "unresolved", "sourceRevision": "e" * 64}])
    assert_code("generation_ledger_source_unsupported", lambda: admitted(case))


def test_retry_canonical_key_order_and_changed_payload(case):
    original = admitted(case)
    case["request"]["proposal"] = dict(reversed(list(case["request"]["proposal"].items())))
    case["request"] = dict(reversed(list(case["request"].items())))
    assert admitted(case) == original
    case["request"]["proposal"]["displayName"] = "Changed package"
    assert_code("generation_artifact_retry_conflict", lambda: admitted(case))


def test_preview_needs_exact_admission_revision(case):
    admission = admitted(case)
    admission["admissionRevision"] = "a" * 64
    assert_code("generation_admission_revision_mismatch", lambda: preview(case, admission))


@pytest.mark.parametrize("source", ["compiler", "catalog", "map"])
def test_changed_dependency_after_admission_invalidates_preview(case, monkeypatch, source):
    admission = admitted(case)
    if source == "compiler":
        monkeypatch.setattr("ai_inspector.facility_layout.generation_admission.generation_compiler_revision", lambda: "f" * 64)
    elif source == "catalog":
        original = case["service"].catalog_provider
        catalog = deepcopy(original(case["principal"], LOCAL_SITE_ID))
        catalog[0]["displayName"] += " changed"
        monkeypatch.setattr(case["service"], "catalog_provider", lambda *args: catalog)
    else:
        case["graph"]["document"]["description"] = "Changed bytes under the same revision"
    assert_code("generation_sources_changed", lambda: preview(case, admission))


def test_competing_lease_blocks_preview_without_touching_owner(case):
    admission = admitted(case)
    leases = case["service"].leases
    lease = leases.acquire(tenant_id=case["principal"].tenant_id, site_id=LOCAL_SITE_ID, layout_id=LOCAL_LAYOUT_ID,
        owner_kind="generation_run", owner_run_id="another-writer", base_saved_layout_revision=case["ledger"]["baseRevision"],
        current_draft_revision=case["ledger"]["baseRevision"])
    assert_code("generation_active_writer", lambda: preview(case, admission))
    assert leases.inspect(case["principal"].tenant_id, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["lease"] == lease


def test_preview_does_not_require_agent_write(case, monkeypatch):
    from ai_inspector.facility_layout.feature_flags import FacilityLayoutFeatureFlags
    flags = FacilityLayoutFeatureFlags(tuple((name, enabled and name != "INSPECTORPRO_FACILITY_LAYOUT_AGENT_WRITE")
                                           for name, enabled in FacilityLayoutFeatureFlags.all_enabled().values))
    monkeypatch.setattr(case["service"], "require_capability", flags.require)
    assert preview(case)["counts"]["placements"] == 2


@pytest.mark.parametrize("scope", ["workspace", "principal", "site"])
def test_wrong_scope_cannot_read_candidate(case, scope):
    result = preview(case)
    if scope == "workspace":
        case["options"]["workspace_id"] = "another-workspace"
    elif scope == "principal":
        case["principal"] = replace(case["principal"], principal_id="another-user")
    else:
        case["options"]["site_id"] = "another-site"
    with pytest.raises(Exception) as exc:
        inspect(case, result)
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.parametrize("phase", ["admission", "preview"])
def test_publication_failure_is_ineligible_and_retry_recovers(case, monkeypatch, phase):
    service = case["service"]
    repo = service.repository
    admission = admitted(case) if phase == "preview" else None
    original_write = repo._atomic_write

    def fail_marker(path, value):
        if path.parent.name == "generation-publications":
            raise OSError("injected publication interruption")
        return original_write(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(repo, "_atomic_write", fail_marker)
        with pytest.raises(OSError, match="publication interruption"):
            preview(case, admission) if phase == "preview" else admitted(case)
    kind, key = (PREVIEW_KIND, "preview-1") if phase == "preview" else (ADMISSION_KIND, "admit-1")
    artifact_id = service._identity(case["principal"], LOCAL_SITE_ID, LOCAL_LAYOUT_ID, "workspace-test", key, kind)
    assert_code("generation_artifact_unpublished", lambda: service._load(case["principal"], LOCAL_SITE_ID, LOCAL_LAYOUT_ID, "workspace-test", kind, artifact_id))
    receipt = preview(case, admission) if phase == "preview" else admitted(case)
    assert receipt["saved"] is False
    service._load(case["principal"], LOCAL_SITE_ID, LOCAL_LAYOUT_ID, "workspace-test", kind, artifact_id)


def test_correction_wins_race_with_artifact_publication(case, monkeypatch):
    original = case["service"].repository.publish_current_artifact

    def correct_first(**kwargs):
        correct(case, quantity=3)
        return original(**kwargs)

    monkeypatch.setattr(case["service"].repository, "publish_current_artifact", correct_first)
    assert_code("generation_ledger_superseded", lambda: admitted(case))


@pytest.mark.parametrize("kind,field,value", [
    ("resource_mapping", "targetArea", "Inspection"),
    ("resource_pattern", "semanticOrientation", "long_side_north_south"),
    ("resource_spacing", "value", 2),
    ("department_allocation", "areaShare", 0.3),
])
def test_each_new_predicate_rejects_nonconforming_package(case, kind, field, value):
    proposal = case["request"]["proposal"]
    target = proposal["departments"][0] if kind == "department_allocation" else proposal["equipmentRequirements"][0]
    if kind == "resource_spacing":
        target = target["authoredSpacing"]
    target[field] = value
    if kind == "department_allocation":
        proposal["departments"][1]["areaShare"] = 0.45
    assert_code("generation_requirements_not_satisfied", lambda: admitted(case))


def test_real_retained_map_resolver_and_restart(case, tmp_path, monkeypatch):
    from ai_inspector.process_map.repository import canonical_process_map_bytes, process_map_revision

    root = tmp_path / "retained-process-maps"
    context = deepcopy(case["context"])
    map_document = deepcopy(case["graph"]["document"])
    map_document["mapId"] = "default"
    context["processMapRef"]["processMapId"] = "default"
    directory = root / context["productRef"]["productId"] / "process_maps"
    directory.mkdir(parents=True)
    (directory / "registry.json").write_text(json.dumps({"registryVersion": 1, "defaultMapId": map_document["mapId"],
        "maps": [{"mapId": map_document["mapId"]}]}), encoding="utf-8")
    map_path = directory / f"{map_document['mapId']}.json"
    map_path.write_bytes(canonical_process_map_bytes(map_document))
    context["processMapRef"]["processMapRevision"] = process_map_revision(map_document)
    context["contextId"] = "reviewed-retained-map"
    host = case["host"]
    host.process_map_root = root
    monkeypatch.setattr(case["service"], "resolve_process_map", host._resolve_process_map)
    source_ref = case["service"].publish_source_context(case["principal"], site_id=LOCAL_SITE_ID, context=context)
    case["request"]["sourceContextRef"] = source_ref
    for ref in case["ledger"]["sourceRefs"]:
        if ref["sourceKind"] == "evidence":
            ref.update(sourceId=source_ref["artifactId"], sourceRevision=source_ref["artifactRevision"])
        if ref["sourceKind"] == "process_map":
            ref["sourceId"] = "default"
            ref["sourceRevision"] = context["processMapRef"]["processMapRevision"]
    correct(case, quantity=3)
    admission = admitted(case)
    first = preview(case, admission)
    bytes_before = map_path.read_bytes()
    reloaded = LocalFacilityLayoutHost(host.root, process_map_root=root, private_assets=False)
    try:
        result = reloaded.generation_admission_service.get_preview(case["principal"], **case["options"],
            preview_id=first["previewId"], preview_revision=first["previewRevision"])
        assert result["counts"]["placements"] == 3
        assert map_path.read_bytes() == bytes_before
        assert reloaded.generation_admission_service.preview(case["principal"], **case["options"], request={
            "requestKey": "preview-1", "admissionId": admission["admissionId"], "admissionRevision": admission["admissionRevision"]}) == first
        map_path.write_bytes(canonical_process_map_bytes({**map_document, "changed": True}))
        assert_code("facility_design_process_map_unavailable", lambda: reloaded.generation_admission_service.get_preview(
            case["principal"], **case["options"], preview_id=first["previewId"], preview_revision=first["previewRevision"]))
    finally:
        reloaded.close()


def test_model_coordinates_are_rejected(case):
    case["request"]["proposal"]["equipmentRequirements"][0]["position"] = {"x": 5, "z": 8}
    with pytest.raises(Exception) as exc:
        admitted(case)
    assert "coordinate" in str(exc.value).lower() or "unknown" in getattr(exc.value, "code", "")


def test_true_geometric_failure_is_not_a_fixture_lookup(case):
    from shapely.geometry import Polygon

    assets = case["service"].catalog_provider(case["principal"], LOCAL_SITE_ID)
    bench = next(item for item in assets if item["assetId"] == "asset-workbench")
    footprint = bench["definition"]["geometry"]["footprintPolygons"][0]
    # Even without aisles or spacing, the physical footprints exceed the whole site.
    assert 120 * Polygon([(p["x"], p["z"]) for p in footprint]).area > 10 * 10
    correct(case, quantity=120, width=10, depth=10)
    admission = admitted(case)
    with pytest.raises(Exception) as exc:
        preview(case, admission)
    assert getattr(exc.value, "code", None) == "facility_program_resource_set_unplaceable", str(exc.value)
    assert case["host"].service.get_layout(case["principal"], LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["layout"] == case["saved"]


def test_artifact_corruption_rejected(case):
    result = preview(case)
    ref = case["service"]._record_ref(PREVIEW_KIND, result["previewId"])
    repo = case["service"].repository
    path = repo._artifact_path(case["principal"].tenant_id, LOCAL_SITE_ID, PREVIEW_KIND, ref["artifactId"], ref["artifactRevision"])
    envelope = repo.get_artifact(case["principal"].tenant_id, LOCAL_SITE_ID, PREVIEW_KIND, ref["artifactId"], ref["artifactRevision"])
    envelope["artifact"]["candidateLayout"]["displayName"] = "Tampered candidate"
    repo._atomic_write(path, envelope)
    with pytest.raises(Exception) as exc:
        inspect(case, result)
    assert "mismatch" in getattr(exc.value, "code", "") or "corrupt" in getattr(exc.value, "code", "")


def test_failed_retention_is_not_published(case, monkeypatch):
    repo = case["service"].repository
    with monkeypatch.context() as patch:
        def fail_pins(*args):
            raise OSError("injected pin failure")
        patch.setattr(repo, "_replace_owner_pins_locked", fail_pins)
        with pytest.raises(OSError, match="pin failure"):
            admitted(case)
    artifact_id = case["service"]._identity(case["principal"], LOCAL_SITE_ID, LOCAL_LAYOUT_ID, "workspace-test", "admit-1", ADMISSION_KIND)
    assert_code("generation_artifact_unpublished", lambda: case["service"]._load(case["principal"], LOCAL_SITE_ID, LOCAL_LAYOUT_ID, "workspace-test", ADMISSION_KIND, artifact_id))
    assert admitted(case)["admissionId"] == artifact_id


def test_catalog_ineligibility_cannot_be_overridden_by_source_review(case, monkeypatch):
    catalog = deepcopy(case["service"].catalog_provider(case["principal"], LOCAL_SITE_ID))
    for asset in catalog:
        asset["previewPlanningEligible"] = False
    monkeypatch.setattr(case["service"], "catalog_provider", lambda *args: catalog)
    assert_code("generation_source_catalog_ineligible", lambda: admitted(case))


@pytest.mark.parametrize("context_id", ["source:assembly", "CON", "LPT1"])
def test_logical_source_ids_are_not_windows_path_components(case, context_id):
    context = deepcopy(case["context"])
    context["contextId"] = context_id
    ref = case["service"].publish_source_context(case["principal"], site_id=LOCAL_SITE_ID, context=context)
    assert len(ref["artifactId"]) == 64
    record, _, _ = case["service"]._source(case["principal"], LOCAL_SITE_ID, ref)
    assert record["context"]["contextId"] == context_id


@pytest.mark.parametrize("field,value", [("proposal", None), ("extra", True), ("proposal", {"bad": []})])
def test_malformed_admission_http_is_named_422(case, field, value):
    case["request"][field] = value
    app = FastAPI()
    app.include_router(case["host"].create_router())
    with TestClient(app) as client:
        response = client.post(f"/api/facility-layout-planning/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/admit", json={
            "workspaceId": "workspace-test", "request": case["request"], "editorContext": case["options"]["editor_context"]})
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error"]["code"] == "generation_admission_fields_invalid"


def test_unresolved_clause_blocks_admission_before_compilation(case):
    ledger = case["ledger"]
    body = {key: deepcopy(value) for key, value in ledger.items() if key != "ledgerRevision"}
    body["parentLedgerRevision"] = ledger["ledgerRevision"]
    text = "Also preserve the existing aisle."
    body["turns"].append({"turnId": "unresolved-turn", "text": text})
    body["requirements"].append({"requirementId": "unresolved-requirement", "source": {"turnId": "unresolved-turn", "start": 0, "end": len(text)},
        "kind": "unknown", "disposition": "unsupported", "predicate": None, "reason": "Existing-facility preservation is outside this slice.", "supersededBy": []})
    changed = build_generation_ledger(body)
    case["service"].repository.commit_ledger(tenant_id=case["principal"].tenant_id, site_id=LOCAL_SITE_ID,
        ledger=changed, expected_ledger_revision=ledger["ledgerRevision"], request_key="unresolved-correction")
    case["request"].update(ledgerRevision=changed["ledgerRevision"], requestKey="unresolved-admission")
    assert_code("generation_requirements_not_satisfied", lambda: admitted(case))


@pytest.mark.parametrize("name", ["spatialDiagnostics", "routingDiagnostics"])
@pytest.mark.parametrize("fault", ["missing", "no_verdict", "failed"])
def test_missing_or_failed_validation_is_never_a_pass(case, monkeypatch, name, fault):
    original = case["host"].service.preview_operations

    def faulty_validation(*args):
        result = original(*args)
        if fault == "missing":
            del result[name]
        elif fault == "no_verdict":
            del result[name]["valid"]
        else:
            result[name]["valid"] = False
        return result

    monkeypatch.setattr(case["host"].service, "preview_operations", faulty_validation)
    assert_code("generation_preview_validation_incomplete", lambda: preview(case))
