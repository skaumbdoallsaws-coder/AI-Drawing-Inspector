"""Real-kernel composition/adoption tests on isolated stores, not model qualification."""
from copy import deepcopy
import pytest

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.generation_composition import (
    COMPOSITION_FIELDS, composition_inventory, validate_composition_parameters)
from ai_inspector.facility_layout.generation_requirements import build_generation_ledger
from ai_inspector.facility_layout.generation_destination import create_generation_destination
from ai_inspector.facility_layout.host import _asset, _shell_document, _timestamp
from tests.test_facility_generation_admission import case, admitted, preview, inspect, assert_code
from tests.test_facility_generation_agent import chat, execute, generate
from tests.test_facility_generation_draft import client_for
from tests.test_facility_generation_requirements import editor
from tests.test_facility_layout_design_loop_contracts import _editor_frame
from tests.test_facility_layout_facility_planning import _package


def composed(case, *, copies=2, seed_count=2, large=False, operator=False):
    proposal = case["request"]["proposal"]
    if large:
        destination = create_generation_destination(case["host"], case["principal"], "site-local", "fl-main",
            {"requestKey": "wide", "expectedBaseRevision": layout_revision(case["saved"]),
             "displayName": "Isolated large composition", "widthMeters": 300, "depthMeters": 200,
             "confirmConceptualFloor": True}, _shell_document(), _timestamp())
        layout_id = destination["layoutId"]
        case["saved"] = case["host"].service.get_layout(case["principal"], "site-local", layout_id)["layout"]
        case["options"].update(layout_id=layout_id, editor_context=editor(case["saved"]))
        proposal["facilityEnvelope"].update(width=300, depth=200)
    layout_id = case["options"]["layout_id"]
    context = case["context"]
    context["processSteps"] = [deepcopy(context["processSteps"][1])]
    context["processSteps"][0]["predecessorProcessStepIds"] = []
    case["graph"]["document"].update(nodes=[{"nodeId": context["processSteps"][0]["processStepId"]}], edges=[])
    proposal["departments"] = [deepcopy(proposal["departments"][1])]
    proposal["departments"][0].update(areaShare=1, row=1)
    proposal["routes"] = []
    template = _package()
    group = template["areaGroups"][0]
    group["labels"] = [f"Assembly Cell {i}" for i in range(copies + 1)]
    group["zoneTypes"] = ["workcell"] * (copies + 1)
    group["proportions"] = [1 / (copies + 1)] * (copies + 1)
    proposal["areaGroups"] = [group]
    resource = proposal["equipmentRequirements"][0]
    resource.update(targetArea=group["labels"][0], quantity=seed_count)
    recipe = template["cellRecipes"][0]
    recipe.update(target_area=group["labels"][0], candidate_strategies=["grid"], selected_strategy_or_objective="grid")
    if operator:
        asset = _asset(asset_id="asset-operator", display_name="Operator", category="operators",
                       width=0.6, depth=0.6, height=1.8, description="Synthetic operator footprint for grid regression")
        case["host"]._catalog[asset["assetId"]] = asset
        case["host"]._asset_versions[(asset["assetId"], asset["assetDefinitionRevision"])] = asset
        person = deepcopy(resource)
        person.update(requirementId="operators", quantity=1, resourceRole="operator-position",
                      selectedCatalogIdentity={key: asset[key] for key in ("assetId", "assetDefinitionRevision", "displayName")})
        proposal["equipmentRequirements"].append(person)
        recipe["member_batches"].append(person["requirementId"])
        context["equipmentMappings"].append({**{key: asset[key] for key in ("assetId", "assetDefinitionRevision")},
            "processStepRefs": person["processStepRefs"], "evidenceRefs": person["evidenceRefs"]})
    proposal["cellRecipes"] = [recipe]
    family = template["moduleFamilies"][0]
    family["target_areas"] = group["labels"][1:]
    proposal["moduleFamilies"] = [family] if copies else []
    source = case["service"].publish_source_context(case["principal"], site_id="site-local", context=context)
    body = {key: deepcopy(value) for key, value in case["ledger"].items() if key != "ledgerRevision"}
    body.update(ledgerId="composed-ledger", parentLedgerRevision=None, layoutId=layout_id,
                baseRevision=layout_revision(case["saved"]), requirements=[], turns=[],
                sourceRefs=case["service"].ledger_source_refs(source, context))

    def requirement(kind, subject, parameters):
        key = f"c{len(body['requirements'])}"
        text = f"Requested {kind}: {subject}: {parameters}."
        body["turns"].append({"turnId": key, "text": text})
        body["requirements"].append({"requirementId": key, "source": {"turnId": key, "start": 0, "end": len(text)},
            "kind": "permission" if kind == "unsaved_preview" else "hard_constraint", "disposition": "represented",
            "predicate": {"kind": kind, "subjectId": subject, "parameters": parameters}, "reason": None, "supersededBy": []})

    requirement("envelope_dimensions", layout_id, {k: proposal["facilityEnvelope"][k] for k in ("width", "depth", "sourceUnit")})
    requirement("unsaved_preview", layout_id, {"saveAllowed": False})
    for batch in proposal["equipmentRequirements"]:
        requirement("resource_quantity", batch["requirementId"], {"quantity": batch["quantity"]})
        requirement("resource_total", batch["requirementId"], {"quantity": batch["quantity"] * (copies + 1)})
    requirement("resource_set", layout_id, {"requirementIds": [r["requirementId"] for r in proposal["equipmentRequirements"]]})
    requirement("route_count", layout_id, {"count": 0})
    for kind, (collection, key, fields) in COMPOSITION_FIELDS.items():
        for entry in proposal[collection]:
            requirement(kind, entry[key], {k: deepcopy(entry[k]) for k in fields})
    ledger = build_generation_ledger(body)
    case["host"].generation_requirement_repository.commit_ledger(tenant_id=case["principal"].tenant_id,
        site_id="site-local", ledger=ledger, expected_ledger_revision=None,
        request_key="composed-ledger", artifact_refs=[source])
    case["ledger"] = ledger
    case["request"].update(ledgerId=ledger["ledgerId"], ledgerRevision=ledger["ledgerRevision"], sourceContextRef=source)
    return case


def test_cells_execute_and_repeat_without_saving(case):
    composed(case)
    receipt = preview(case)
    result = inspect(case, receipt)
    assert receipt["counts"] == {"zones": 4, "placements": 6, "routes": 0, "floorMarkings": 0}
    assert receipt["compositionInventory"]["cellCount"] == 3
    assert len({p["placementId"] for p in result["candidateLayout"]["placements"]}) == 6
    assert sum("sourcePlacementId" in p["metadata"] for p in result["candidateLayout"]["placements"]) == 4
    assert preview(case) == receipt
    assert case["host"].service.get_layout(case["principal"], "site-local", case["options"]["layout_id"])["layout"] == case["saved"]


@pytest.mark.parametrize("mutation", [
    lambda p: p["cellRecipes"][0].update(member_batches=["unknown"]),
    lambda p: p["cellRecipes"][0].update(process_order=["assemble-product"]),
    lambda p: p["cellRecipes"][0].update(interfaces=[{"x": 1}]),
    lambda p: p["cellRecipes"][0]["authored_spacing"].update(unit="mm"),
    lambda p: p["moduleFamilies"][0].update(target_areas=["Assembly Cell 0"]),
    lambda p: p["moduleFamilies"][0].update(target_areas=["Assembly Cell 1", "assembly cell 1"]),
    lambda p: p["moduleFamilies"][0].update(source_recipe_or_cell="Assembly Cell 0"),
    lambda p: p["moduleFamilies"][0].update(preserve_source=False),
    lambda p: p["moduleFamilies"][0].update(composable_with=["another-family"]),
    lambda p: p["areaGroups"][0].update(labels=["Assembly"]),
])
def test_unsupported_or_ambiguous_composition_refused(case, mutation):
    composed(case)
    mutation(case["request"]["proposal"])
    with pytest.raises(Exception):
        admitted(case)


def test_expanded_budget_includes_copies(case):
    composed(case, copies=2, seed_count=300)
    case["request"]["proposal"]["equipmentRequirements"][0]["quantity"] = 301
    assert_code("generation_admission_budget_exceeded", lambda: admitted(case))


def test_copy_total_cannot_claim_only_seed_quantity(case):
    composed(case)
    case["request"]["proposal"]["moduleFamilies"][0]["target_areas"].pop()
    assert_code("generation_requirements_not_satisfied", lambda: admitted(case))


@pytest.mark.parametrize("seed_count", [150, 225])
def test_large_program_keeps_batches_through_apply_and_undo(case, monkeypatch, seed_count):
    composed(case, copies=3, seed_count=seed_count, large=True)
    monkeypatch.setattr(case["host"].service, "preview_operations", lambda *a: pytest.fail("Flattened large program"))
    receipt = preview(case)
    assert receipt["counts"]["placements"] == seed_count * 4
    assert receipt["execution"]["operations"] > 500
    assert preview(case) == receipt
    request = {key: receipt[key] for key in ("previewId", "previewRevision")}
    selected = case["host"].generation_draft_adapter.publish(case["principal"], **case["options"], request=request)
    frame = _editor_frame({"document": case["saved"]})
    with client_for(case) as client:
        base = f"/api/facility-layout-design/site-local/{case['options']['layout_id']}"
        response = client.post(base + f"/proposals/{selected['proposalId']}/apply/prepare", json={
            "proposalRevision": selected["proposalRevision"], "rootUndoFrame": frame, "previousInstallationState": frame,
            "expectedResultEditorGenerationId": "large-editor", "expectedResultCommandJournalHash": "8" * 64})
        assert response.status_code == 200, response.text
        prepared = response.json()
        assert "candidateOperations" not in prepared
        batches = prepared["candidateOperationBatches"]
        assert max(len(b["operations"]) for b in batches) <= 500
        assert sum(len(b["operations"]) for b in batches) > 500
        transaction = prepared["transaction"]
        url = base + "/transactions/" + transaction["transaction"]["transactionId"]
        commit = client.post(url + "/apply/commit", json={"expectedTransactionRevision": transaction["transactionRevision"],
            "adoptionToken": prepared["adoption"]["adoptionToken"]})
        assert commit.status_code == 200, commit.text
        ack = client.post(url + "/apply/acknowledge", json={"expectedTransactionRevision": commit.json()["transaction"]["transactionRevision"],
            "adoptionToken": prepared["adoption"]["adoptionToken"],
            "observedInstallationFingerprint": prepared["expectedInstallationFingerprint"]})
        assert ack.status_code == 200, ack.text
        undo = client.post(url + "/undo/prepare", json={"expectedTransactionRevision": ack.json()["transaction"]["transactionRevision"]})
        assert undo.status_code == 200, undo.text
        assert undo.json()["rootUndoFrame"] == frame
        restored = client.post(url + "/undo/acknowledge", json={"expectedTransactionRevision": undo.json()["transaction"]["transactionRevision"],
            "observedDraftRevision": frame["draftRevision"], "observedCommandJournalHash": frame["commandJournalHash"]})
        assert restored.status_code == 200, restored.text
    assert case["host"].service.get_layout(case["principal"], "site-local", case["options"]["layout_id"])["layout"] == case["saved"]


def test_composition_tool_schemas_publish_supported_fields():
    from ai_inspector.facility_layout.generation_agent import generation_tool_specs, PREVIEW_TOOL
    schema = next(t["input_schema"] for t in generation_tool_specs() if t["name"] == PREVIEW_TOOL)
    fields = schema["properties"]["proposal"]["properties"]
    assert fields["equipmentRequirements"]["items"]["properties"]["quantity"]["maximum"] == 900
    for kind, (collection, key, keys) in COMPOSITION_FIELDS.items():
        assert set(fields[collection]["items"]["properties"]) == keys | {key}
    assert fields["moduleFamilies"]["items"]["properties"]["target_areas"]["maxItems"] == 20


def test_replication_target_limit_matches_the_compiler(case):
    composed(case)
    family = deepcopy(case["request"]["proposal"]["moduleFamilies"][0])
    family.pop("family_id")
    family["target_areas"] = [f"Cell {i}" for i in range(21)]
    assert_code("generation_composition_invalid", lambda: validate_composition_parameters("module_repetition", family))


@pytest.mark.parametrize("benches", [1, 2, 4])
def test_operator_occupies_grid_slot_in_each_repeated_cell(case, benches):
    composed(case, seed_count=benches, operator=True)
    receipt = preview(case)
    result = inspect(case, receipt)
    assert receipt["counts"]["placements"] == 3 * (benches + 1)
    assert receipt["compositionInventory"]["resourceTotals"]["operators"] == 3
    assert len([p for p in result["candidateLayout"]["placements"] if p["assetId"] == "asset-operator"]) == 3
    assert result["validation"]["spatialDiagnostics"]["valid"] is True


def test_mixed_cell_correction_preserves_composition_and_retries_without_execution(case, request, monkeypatch):
    from ai_inspector.facility_layout.generation_agent import CONTEXT_TOOL, REQUIREMENTS_TOOL, REVISE_TOOL

    composed(case, seed_count=2, operator=True)
    conversation = request.getfixturevalue("chat")
    original = deepcopy(conversation["request"]["proposal"])
    initial, _ = generate(conversation)
    assert initial["counts"]["placements"] == 9
    prior = execute(conversation, CONTEXT_TOOL, {"section": "requirements"})["items"]
    bench_id = original["equipmentRequirements"][0]["requirementId"]
    changed = [item for item in prior if item["predicate"]["subjectId"] == bench_id
               and item["predicate"]["kind"] in ("resource_quantity", "resource_total")]
    assert len(changed) == 2
    conversation.update(message="Use one bench and one operator in each of the three cells; keep everything else.",
                        turn="mixed-cell-correction")
    common = {"sourceText": conversation["message"], "kind": "hard_constraint",
              "disposition": "represented", "reason": None}
    replacements = [{**common, "requirementId": f"correct-{item['predicate']['kind']}",
        "supersedes": [item["requirementId"]], "predicate": {**item["predicate"],
            "parameters": {"quantity": 1 if item["predicate"]["kind"] == "resource_quantity" else 3}}}
        for item in changed]
    replacements.append({**common, "requirementId": "preserve-composition", "supersedes": [],
        "predicate": {"kind": "preserve_prior_requirements", "subjectId": conversation["binding"]["ledgerId"],
            "parameters": {"exceptRequirementIds": [item["requirementId"] for item in changed]}}})
    ledger = execute(conversation, REQUIREMENTS_TOOL,
        {"expectedLedgerRevision": initial["ledgerRevision"], "requirements": replacements})
    args = {"requestKey": "mixed-cell-correction", "expectedLedgerRevision": ledger["ledgerRevision"],
        "previewId": initial["previewId"], "previewRevision": initial["previewRevision"],
        "changes": [{"collection": "equipmentRequirements", "entityId": bench_id, "values": {"quantity": 1}}]}
    revised = execute(conversation, REVISE_TOOL, args)
    assert revised["counts"]["placements"] == 6
    assert revised["compositionInventory"]["cellCount"] == 3
    assert revised["compositionInventory"]["resourceTotals"] == {bench_id: 3, "operators": 3}
    assert revised["candidateRevision"] != initial["candidateRevision"]
    original["equipmentRequirements"][0]["quantity"] = 1
    retained = conversation["service"].prior_package(conversation["principal"], conversation["binding"])
    assert retained["package"] == original
    original["equipmentRequirements"][0]["quantity"] = 2
    retained_old = conversation["service"].prior_package(conversation["principal"], conversation["binding"],
        preview_ref={key: initial[key] for key in ("previewId", "previewRevision")})
    assert retained_old["package"] == original
    monkeypatch.setattr(case["host"].service, "preview_program", lambda *a, **k: pytest.fail("Retry executed geometry"))
    assert execute(conversation, REVISE_TOOL, dict(reversed(list(args.items())))) == revised
    saved = case["host"].service.get_layout(case["principal"], "site-local", case["options"]["layout_id"])["layout"]
    assert saved == case["saved"]


@pytest.mark.parametrize("diagnostic", ["spatialDiagnostics", "routingDiagnostics"])
@pytest.mark.parametrize("fault", ["missing", "no_verdict", "failed"])
def test_staged_composition_needs_complete_authoritative_validation(case, monkeypatch, diagnostic, fault):
    composed(case)
    original = case["host"].service.preview_program

    def incomplete(*args, **kwargs):
        result = original(*args, **kwargs)
        if fault == "missing":
            result.pop(diagnostic)
        elif fault == "no_verdict":
            result[diagnostic].pop("valid")
        else:
            result[diagnostic]["valid"] = False
        return result

    monkeypatch.setattr(case["host"].service, "preview_program", incomplete)
    assert_code("generation_preview_validation_incomplete", lambda: preview(case))
    saved = case["host"].service.get_layout(case["principal"], "site-local", case["options"]["layout_id"])["layout"]
    assert saved == case["saved"]
