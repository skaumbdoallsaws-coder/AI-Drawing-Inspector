"""Dependency-free, bounded refusals. Worker transport is added in MB1b."""
import json

MESSAGES = {
    "schema_invalid": "Check the recipe field and its allowed values.",
    "budget_exceeded": "The build exceeds a recipe or geometry budget.",
    "scatter_bounds_too_small": "A scattered copy cannot fit inside its bounds.",
    "composition_unavailable": "Composition arrives in MB3; include entries cannot be built yet.",
    "include_mismatch": "The included artifact does not match its pinned identity.",
    "print_invalid": "The printed panel contains unsupported text or drawing data.",
    "font_missing": "The pinned print font is unavailable.",
    "geometry_invalid": "The shape or transformed geometry is degenerate or out of bounds.",
}


class ModelBuildError(ValueError):
    def __init__(self, code, path="$", problem=None):
        if code not in MESSAGES:
            raise ValueError("Unknown builder refusal")
        self.code = code
        self.path = str(path)[:240]
        self.problem = str(problem or MESSAGES[code])[:500]
        self.path = "".join(c if ord(c) >= 32 else " " for c in self.path)
        self.problem = "".join(c if ord(c) >= 32 else " " for c in self.problem)
        super().__init__(f"{MESSAGES[code]} {self.path}: {self.problem}")

    def to_dict(self):
        return {"code": self.code, "message": MESSAGES[self.code],
                "details": {"path": self.path, "problem": self.problem}}


def require(condition, path, problem, code="schema_invalid"):
    if not condition:
        raise ModelBuildError(code, path, problem)


def json_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")
