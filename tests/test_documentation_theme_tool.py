"""Sage's document theme tool (2026-11-14): read, partial change, template, retry, staleness, fit and undo.

All stores are temporary (mmle_client). Run under pytest in the supervisor environment.
"""
from copy import deepcopy
import json

import fitz
import pytest

from ai_inspector.documentation import theme as document_theme
from ai_inspector.documentation.commands import DocumentEditError, operation_store
from ai_inspector.documentation.targets import ReadBindings
from ai_inspector.parts_manual.documentation import DEFAULT_DOCUMENT_THEME, _DOCUMENT_FONT_FAMILIES
from tests.test_documentation_refresh import mmle_client, MMLE_ROUTES  # noqa: F401 (fixture)
from tests.test_documentation_page_setup import _real, _sage_reader, _sage_read, assert_restored

OPS = "operations_and_maintenance_manual"


def refused(fn, code):
    with pytest.raises(DocumentEditError) as caught:
        fn()
    assert caught.value.code == code, caught.value
    return caught.value


def _sage_theme(reader, data, operation, request_id="theme-tool"):
    from tests.test_codex_documentation_tools import call
    return call(reader, "apply_document_edits", {"documentId": data["documentId"],
        "expectedRevision": data["themeRevision"], "requestId": request_id, "operations": [operation]})


def _ui_theme(client, route, payload, theme):
    document = payload["document"]
    return client.post(f"/api/{route}/MMLE-50D/documentation-scene/commands", json={
        "baseRevision": payload["revision"], "sourceRevision": document["sourceRevision"],
        "manualPlanRevision": document["manualPlanRevision"], "operation": "set_theme",
        "pageId": document["pages"][0]["pageId"], "targetType": "document_theme", "targetId": "company-theme",
        "theme": theme})


def test_theme_variants_are_closed_and_list_the_scene_fonts():
    from ai_inspector.codex_runtime.documentation_tools import tool_specs
    batch = next(s for s in tool_specs() if s["name"] == "apply_document_edits")
    variants = {v["properties"]["operation"]["enum"][0]: v
                for v in batch["input_schema"]["properties"]["operations"]["items"]["anyOf"]}
    theme = variants["set_document_theme"]
    assert theme["required"] == ["operation", "theme"] and theme["additionalProperties"] is False
    sections = theme["properties"]["theme"]["properties"]
    assert set(sections) == {"name", "companyName", "colors", "typography", "table", "annotation"}
    assert theme["properties"]["theme"]["additionalProperties"] is False
    assert set(sections["colors"]["properties"]) == set(DEFAULT_DOCUMENT_THEME["colors"])
    assert set(sections["table"]["properties"]) == set(DEFAULT_DOCUMENT_THEME["table"])
    assert set(sections["annotation"]["properties"]) == set(DEFAULT_DOCUMENT_THEME["annotation"])
    assert set(sections["typography"]["properties"]) == set(DEFAULT_DOCUMENT_THEME["typography"])
    assert set(sections["typography"]["properties"]["headingFont"]["enum"]) == set(_DOCUMENT_FONT_FAMILIES)
    assert sections["colors"]["properties"]["primary"]["pattern"] == "^#[0-9A-Fa-f]{6}$"
    for section in ("colors", "typography", "table", "annotation"):
        assert sections[section]["additionalProperties"] is False
    template = variants["apply_document_template"]
    assert set(template["properties"]) == {"operation", "templateId"}
    assert template["additionalProperties"] is False
    for phrase in ("themeRevision", "apply_document_template", "logo"):
        assert phrase in batch["description"]


def test_theme_operations_are_sent_alone_with_exact_fields():
    assert operation_store([{"operation": "set_document_theme", "theme": {"colors": {"primary": "#000000"}}}]) == "theme"
    assert operation_store([{"operation": "apply_document_template", "templateId": "acme"}]) == "theme"
    for ops in ([{"operation": "set_document_theme"}],
                [{"operation": "set_document_theme", "theme": {}, "targetId": "x"}],
                [{"operation": "apply_document_template", "theme": {}}],
                [{"operation": "set_document_theme", "theme": {}}, {"operation": "set_page_setup", "pageSetup": None}],
                [{"operation": "replace_text", "targetId": "a", "text": "x", "expectedContentHash": "0" * 64},
                 {"operation": "apply_document_template", "templateId": "acme"}]):
        refused(lambda: operation_store(ops), "invalid_document_operation")


def test_theme_bindings_require_a_read_and_keep_the_retry_preimage():
    bindings = ReadBindings("theme-turn")
    args = {"documentId": "d", "expectedRevision": 3, "requestId": "t", "operations": [
        {"operation": "set_document_theme", "theme": {"colors": {"primary": "#000000"}}}]}
    refused(lambda: bindings.bind_operations(OPS, args), "document_read_required")
    first = {"documentId": "d", "expectedRevision": 3, "sourceRevision": "s", "manualPlanRevision": "m",
             "sceneRevision": "a", "themeHash": "old"}
    bindings.record(OPS, {"themeBinding": first})
    assert bindings.bind_operations(OPS, args) == {**first, **args}
    bindings.record(OPS, {"themeBinding": {**first, "sceneRevision": "b", "themeHash": "new"}})
    assert bindings.bind_operations(OPS, args) == {**first, **args}
    assert bindings.bind_operations(OPS, {**args, "requestId": "next"})["themeHash"] == "new"
    refused(lambda: bindings.bind_operations(OPS, {**args, "requestId": "other", "documentId": "e"}),
            "document_binding_changed")


def test_partial_merge_keeps_every_other_setting_and_refuses_no_ops_and_unknown_settings():
    current = deepcopy(DEFAULT_DOCUMENT_THEME)
    current["logo"] = None
    result = document_theme.merged(current, {"colors": {"primary": "#1f3a5f"}, "typography": {"headingFont": "Georgia"},
                                             "companyName": "Acme Lifts"})
    assert result["colors"] == {**DEFAULT_DOCUMENT_THEME["colors"], "primary": "#1F3A5F"}
    assert result["typography"] == {**DEFAULT_DOCUMENT_THEME["typography"], "headingFont": "Georgia"}
    assert result["companyName"] == "Acme Lifts" and result["name"] == DEFAULT_DOCUMENT_THEME["name"]
    assert result["table"] == DEFAULT_DOCUMENT_THEME["table"]
    assert result["annotation"] == DEFAULT_DOCUMENT_THEME["annotation"]
    assert result["version"] == DEFAULT_DOCUMENT_THEME["version"] + 1
    assert result["themeId"] == DEFAULT_DOCUMENT_THEME["themeId"]
    refused(lambda: document_theme.merged(current, {}), "invalid_document_theme")
    refused(lambda: document_theme.merged(current, {"colors": {"primary": "#071b2a"}}), "document_theme_unchanged")
    refused(lambda: document_theme.merged(current, {"logo": None}), "invalid_document_theme")
    refused(lambda: document_theme.merged(current, {"colors": {"brand": "#000000"}}), "invalid_document_theme")
    refused(lambda: document_theme.merged(current, {"colors": {"primary": "navy"}}), "invalid_document_theme")
    refused(lambda: document_theme.merged(current, {"typography": {"bodyFont": "Comic Sans MS"}}), "invalid_document_theme")
    refused(lambda: document_theme.merged(current, {"companyName": "   "}), "invalid_document_theme")
    view = document_theme.view({**current, "logo": {"assetId": "asset-1", "path": "never shown"}})
    assert view["hasLogo"] is True and "logo" not in view
    assert document_theme.view(None)["colors"] == DEFAULT_DOCUMENT_THEME["colors"]


@pytest.mark.parametrize("kind,route", MMLE_ROUTES)
def test_sage_theme_change_retry_and_named_undo_on_every_document(mmle_client, kind, route):
    from tests.test_codex_documentation_tools import call
    before = _real(mmle_client, route)
    reader = _sage_reader()
    data = _sage_read(reader, kind)
    assert data["theme"] == document_theme.view(before["scene"]["theme"])
    assert data["themeRevision"] == data["pageSetupRevision"] == before["scene"]["editRevision"]
    assert data["themeOptions"]["fonts"] == sorted(_DOCUMENT_FONT_FAMILIES)
    assert data["themeOptions"]["templates"] == []
    assert _real(mmle_client, route)["scene"] == before["scene"]
    operation = {"operation": "set_document_theme", "theme": {"colors": {"primary": "#1F3A5F", "accent": "#C99B39"},
                                                              "typography": {"headingFont": "Helvetica"}}}
    result = _sage_theme(reader, data, operation)
    assert result["ok"], result
    changed = _real(mmle_client, route)
    theme = changed["scene"]["theme"]
    assert theme["colors"] == {**before["scene"]["theme"]["colors"], "primary": "#1F3A5F", "accent": "#C99B39"}
    assert theme["typography"] == {**before["scene"]["theme"]["typography"], "headingFont": "Helvetica"}
    assert {k: v for k, v in theme.items() if k not in {"colors", "typography", "version"}} == {
        k: v for k, v in before["scene"]["theme"].items() if k not in {"colors", "typography", "version"}}
    assert changed["document"]["theme"]["colors"]["primary"] == "#1F3A5F"
    assert changed["scene"]["pageMasters"] == before["scene"]["pageMasters"]
    assert changed["scene"]["commands"][-1]["change"]["actor"] == "sage"
    assert changed["scene"]["historyCursor"] == before["scene"]["historyCursor"] + 1
    assert result["data"]["theme"] == document_theme.view(theme)
    assert _sage_theme(reader, data, operation) == result
    assert _real(mmle_client, route)["scene"] == changed["scene"]
    assert _sage_read(reader, kind)["theme"] == document_theme.view(theme)
    receipt = result["data"]["receipt"]
    undone = call(reader, "undo_document_change", {"documentId": data["documentId"],
        "expectedRevision": receipt["revision"], "requestId": "theme-undo", "changeId": receipt["changeId"]})
    assert undone["ok"], undone
    assert_restored(before, _real(mmle_client, route))


def test_sage_theme_is_stale_after_a_user_theme_change_and_mixed_or_unchanged_requests_write_nothing(mmle_client):
    reader = _sage_reader()
    data = _sage_read(reader, OPS)
    before = _real(mmle_client, "operations-manual")
    unchanged = _sage_theme(reader, data, {"operation": "set_document_theme",
        "theme": {"colors": {"primary": before["scene"]["theme"]["colors"]["primary"]}}}, "same-theme")
    assert unchanged["error"]["code"] == "document_theme_unchanged", unchanged
    from tests.test_codex_documentation_tools import call
    mixed = call(reader, "apply_document_edits", {"documentId": data["documentId"],
        "expectedRevision": data["themeRevision"], "requestId": "mixed-theme", "operations": [
            {"operation": "set_document_theme", "theme": {"colors": {"primary": "#000000"}}},
            {"operation": "set_page_setup", "pageSetup": None}]})
    assert mixed["error"]["code"] == "invalid_document_operation", mixed
    unknown = _sage_theme(reader, data, {"operation": "apply_document_template", "templateId": "missing"}, "no-template")
    assert unknown["error"]["code"] == "unknown_document_template", unknown
    assert _real(mmle_client, "operations-manual")["scene"] == before["scene"]
    user = deepcopy(before["scene"]["theme"])
    user["colors"]["secondary"] = "#EEEEEE"
    response = _ui_theme(mmle_client, "operations-manual", before, user)
    assert response.status_code == 200, response.text
    later = _real(mmle_client, "operations-manual")
    stale = _sage_theme(reader, data, {"operation": "set_document_theme",
                                       "theme": {"colors": {"primary": "#000000"}}}, "stale-theme")
    assert stale["error"]["code"] == "content_hash_mismatch", stale
    assert _real(mmle_client, "operations-manual")["scene"] == later["scene"]
    fresh = _sage_theme(reader, _sage_read(reader, OPS), {"operation": "set_document_theme",
                                                         "theme": {"colors": {"primary": "#000000"}}}, "fresh-theme")
    assert fresh["ok"], fresh
    theme = _real(mmle_client, "operations-manual")["scene"]["theme"]
    assert theme["colors"]["secondary"] == "#EEEEEE" and theme["colors"]["primary"] == "#000000"


def _tight_text_box(client, key):
    before = _real(client, "operations-manual")
    page = next(p for p in before["document"]["pages"] if p["pageType"] == "operations_content")
    text = "A measured line with little room"
    width = fitz.get_text_length(text, fontname="helv", fontsize=12) + 6.1
    response = client.post("/api/operations-manual/MMLE-50D/documentation-scene/commands", json={
        "baseRevision": before["revision"], "sourceRevision": before["scene"]["sourceRevision"],
        "manualPlanRevision": before["scene"]["manualPlanRevision"], "operation": "add_object",
        "pageId": page["pageId"], "targetType": "document_object", "targetId": key,
        "documentObject": {"objectId": key, "type": "text", "name": "Theme fit", "source": "user", "content": text,
            "frame": {"x": .1, "y": .2, "width": width / 960, "height": 20.5 / 540}, "styleOverrides": {"fontSize": 12}}})
    assert response.status_code == 200, response.text
    return page


def test_sage_body_font_that_would_overflow_is_refused_with_page_and_nothing_changes(mmle_client):
    key = "document-object-theme-fit"
    page = _tight_text_box(mmle_client, key)
    before = _real(mmle_client, "operations-manual")
    reader = _sage_reader()
    result = _sage_theme(reader, _sage_read(reader, OPS), {"operation": "set_document_theme",
                                                          "theme": {"typography": {"bodyFont": "Courier New"}}})
    assert result["error"]["code"] == "layout_overflow", result
    assert "with this theme" in result["error"]["message"]
    item = next(t for t in result["error"]["details"]["targets"] if t["targetId"] == key)
    assert item["reason"] == "text_does_not_fit"
    assert isinstance(item["pageNumber"], int) and item["pageNumber"] > 0
    assert item["pageTitle"] == page["title"]
    assert _real(mmle_client, "operations-manual")["scene"] == before["scene"]
    colors_only = _sage_theme(reader, _sage_read(reader, OPS), {"operation": "set_document_theme",
                                                               "theme": {"colors": {"primary": "#202020"}}}, "colors")
    assert colors_only["ok"], colors_only


def test_parts_list_headers_refuse_serif_and_mono_heading_fonts(mmle_client):
    # The 11 pt parts-list header cells shrink for width only; Times/Georgia/Courier bold lines are too tall
    # for them at 6.5 pt, and PyMuPDF then draws nothing. The theme tool refuses instead of dropping headers.
    before = _real(mmle_client, "parts-manual")
    reader = _sage_reader()
    for font in ("Times New Roman", "Georgia", "Courier New"):
        result = _sage_theme(reader, _sage_read(reader, "illustrated_parts_manual"),
                             {"operation": "set_document_theme", "theme": {"typography": {"headingFont": font}}}, font)
        assert result["error"]["code"] == "layout_overflow", result
        targets = result["error"]["details"]["targets"]
        assert targets and {t["targetId"] for t in targets} <= {f"bom_header_{i}" for i in range(4)}
        assert all(t["pageTitle"] and t["pageNumber"] for t in targets)
    assert _real(mmle_client, "parts-manual")["scene"] == before["scene"]
    sans = _sage_theme(reader, _sage_read(reader, "illustrated_parts_manual"),
                       {"operation": "set_document_theme", "theme": {"typography": {"headingFont": "Inter"}}}, "inter")
    assert sans["ok"], sans


def test_workspace_theme_dialog_keeps_its_unchecked_path(mmle_client):
    _tight_text_box(mmle_client, "document-object-theme-dialog")
    before = _real(mmle_client, "operations-manual")
    theme = deepcopy(before["scene"]["theme"])
    theme["typography"]["bodyFont"] = "Courier New"
    response = _ui_theme(mmle_client, "operations-manual", before, theme)
    assert response.status_code == 200, response.text
    assert _real(mmle_client, "operations-manual")["scene"]["theme"]["typography"]["bodyFont"] == "Courier New"


def test_sage_applies_a_saved_template_with_its_page_masters(mmle_client):
    import server
    before = _real(mmle_client, "operations-manual")
    template_theme = deepcopy(before["scene"]["theme"])
    template_theme.update(themeId="acme", name="Acme Technical", companyName="Acme Lifts")
    template_theme["colors"]["primary"] = "#123456"
    masters = deepcopy(before["scene"]["pageMasters"])
    first = next(iter(masters))
    masters[first]["showFooter"] = not masters[first]["showFooter"]
    directory = server._documentation_template_directory()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "acme-technical.json").write_text(json.dumps({"templateId": "acme-technical", "name": "Acme Technical",
        "version": 1, "theme": template_theme, "pageMasters": masters}), encoding="ascii")
    (directory / "broken.json").write_text("{not json", encoding="ascii")
    reader = _sage_reader()
    data = _sage_read(reader, OPS)
    assert data["themeOptions"]["templates"] == [{"templateId": "acme-technical", "name": "Acme Technical"}]
    result = _sage_theme(reader, data, {"operation": "apply_document_template", "templateId": "acme-technical"})
    assert result["ok"], result
    assert result["data"]["templateApplied"] == "acme-technical"
    scene = _real(mmle_client, "operations-manual")["scene"]
    assert scene["theme"]["companyName"] == "Acme Lifts" and scene["theme"]["colors"]["primary"] == "#123456"
    assert scene["pageMasters"][first]["showFooter"] == masters[first]["showFooter"]
    again = _sage_theme(reader, _sage_read(reader, OPS),
                        {"operation": "apply_document_template", "templateId": "acme-technical"}, "again")
    assert again["error"]["code"] == "document_theme_unchanged", again
