"""Repairable recipe errors are bounded structured data, including through the worker."""
import pytest

from tests.model_import_test_support import module

recipes = module("recipe")
ModelImportError = module("errors").ModelImportError
BASE = {"importId": "mi-" + "0" * 24, "name": "Test", "category": "decor"}


@pytest.mark.parametrize("recipe,path,problem", [
    ({"name": "Test", "category": "decor"}, "importId", "required"),
    ({**BASE, "parts": [{"select": {"all": True}}] * 2 + [
        {"select": {"all": True}, "material": {"color": "red"}}]}, "parts[2].material.color", "expected #rrggbb"),
    ({**BASE, "size": {"dimension": "height", "meters": .001}}, "size.meters", "must be 0.01-30"),
    ({**BASE, "parts": [{"select": {"all": True}, "move": [0, 0, 0], "moveTo": [0, 0, 0]}]},
     "parts[0]", "move and moveTo"),
    ({**BASE, "surfaces": [{"id": "top", "label": "Top", "height": 1, "rect": [1, 0, 0, 1]}]},
     "surfaces[0].rect", "expected x0 < x1"),
    ({**BASE, "attribution": {"statedBy": "user", "sourceUrl": "http://example.test"}},
     "attribution.sourceUrl", "expected an https URL"),
])
def test_recipe_error_names_field_and_problem(recipe, path, problem):
    with pytest.raises(ModelImportError) as caught:
        recipes.normalize_recipe(recipe)
    error = caught.value
    assert error.code == "recipe_invalid"
    assert any(p["path"] == path and problem in p["problem"] for p in error.details["problems"])
    assert error.to_dict()["details"] == error.details


def test_up_to_five_problems_and_error_wire_budget():
    with pytest.raises(ModelImportError) as caught:
        recipes.normalize_recipe({"tags": [2], "rotate": {"x": 400}, "textureMaxPx": 4})
    assert 1 <= len(caught.value.details["problems"]) <= 5
    assert len(module("validation").json_bytes(caught.value.to_dict())) <= 8192
    details = module("diagnostics").problem_details([("\U0001f333" * 120, "\U0001f333" * 240)] * 5)
    error = ModelImportError("recipe_invalid", details)
    assert len(module("validation").json_bytes(error.to_dict())) <= 8192


def test_selector_error_has_rule_path_and_closest_names():
    from tests.model_import_test_support import textured_box
    source = module("reader").read_model(textured_box().bytes())
    raw = {**BASE, "parts": [{"select": {"material": "pait"}}]}
    with pytest.raises(ModelImportError) as caught:
        module("transforms").transform_model(source, recipes.normalize_recipe(raw))
    assert caught.value.details["closest"] == ["paint"]
    problem = caught.value.details["problems"][0]
    assert problem["path"] == "parts[0].select.material"
    assert "no part matches material 'pait'" in problem["problem"] and "paint" in problem["problem"]


def test_refusal_details_survive_real_worker_exit_mapping(tmp_path, monkeypatch):
    runner = module("runner")
    error = ModelImportError("recipe_invalid", {"problems": [{"path": "importId", "problem": "required"}]})
    stub = tmp_path / "stub.py"
    stub.write_bytes(("from pathlib import Path\nPath('error.json').write_bytes(" +
                      repr(module("validation").json_bytes(error.to_dict())) + ")\nraise SystemExit(2)\n").encode())
    monkeypatch.setattr(runner, "_WORKER", stub)
    import threading
    with pytest.raises(ModelImportError) as caught:
        runner._launch(tmp_path, tmp_path, "prepare", threading.Event(), 3)
    assert caught.value.to_dict() == error.to_dict()
