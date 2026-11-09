"""Bounded field diagnostics shared by schema and selector refusals."""
from .errors import ModelImportError
from .validation import clean_text, json_bytes


def problem_details(problems, **extra) -> dict:
    items = [{"path": clean_text(path, 120) or "recipe", "problem": clean_text(problem, 240)}
             for path, problem in list(problems)[:5]]
    result = {**extra, "problems": items}
    while len(json_bytes(result)) > 6144:
        if len(items) > 1:
            items.pop()
        elif len(items[0]["problem"]) > 40:
            items[0]["problem"] = clean_text(items[0]["problem"], len(items[0]["problem"]) - 20)
        elif result.get("closest"):
            result["closest"].pop()
        else:
            items[0]["path"] = clean_text(items[0]["path"], 40)
            break
    return result


def recipe_error(problems) -> ModelImportError:
    return ModelImportError("recipe_invalid", problem_details(problems))
