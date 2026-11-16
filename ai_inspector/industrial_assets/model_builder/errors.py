"""Dependency-free, bounded refusals shared by the kernel and worker protocol."""
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
    "job_invalid": "The build job inputs are missing, unsafe, or inconsistent.",
}
ERROR_BYTES = 8192
TRIANGLE_LIMIT = 60000


class ModelBuildError(ValueError):
    def __init__(self, code, path="$", problem=None, *, triangles=None):
        if code not in MESSAGES:
            raise ValueError("Unknown builder refusal")
        self.code = code
        self.message = MESSAGES[code]
        self.path = str(path)[:240]
        self.problem = str(problem or MESSAGES[code])[:500]
        self.path = "".join(c if ord(c) >= 32 else " " for c in self.path)
        self.problem = "".join(c if ord(c) >= 32 else " " for c in self.problem)
        if triangles is not None and (code != "budget_exceeded" or type(triangles) is not int
                                      or not TRIANGLE_LIMIT < triangles <= 30_000_000):
            raise ValueError("Invalid builder triangle diagnostic")
        self.triangles = triangles
        # ensure_ascii can encode one non-BMP character as twelve bytes. Keep
        # the complete wire envelope bounded even for an invalid Unicode key.
        excess = len(json_bytes(self.to_dict())) - ERROR_BYTES
        while excess > 0:
            excess -= len(json_bytes(self.problem[-1])) - 2
            self.problem = self.problem[:-1]
        super().__init__(f"{MESSAGES[code]} {self.path}: {self.problem}")

    def to_dict(self):
        details = {"path": self.path, "problem": self.problem}
        if self.triangles is not None:
            details.update(triangles=self.triangles, limit=TRIANGLE_LIMIT)
        return {"code": self.code, "message": self.message, "details": details}


def require(condition, path, problem, code="schema_invalid"):
    if not condition:
        raise ModelBuildError(code, path, problem)


def json_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def parse_json(payload, maximum):
    """Strict bounded JSON, including duplicate-key and non-finite rejection."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    if not isinstance(payload, bytes) or len(payload) > maximum:
        raise ValueError("JSON exceeds its byte limit")
    return json.loads(payload.decode("utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))


def decode_error(payload):
    """Return a validated refusal, never trust worker message text or a larger import limit."""
    value = parse_json(payload, ERROR_BYTES)
    if type(value) is not dict or set(value) != {"code", "message", "details"}:
        raise ValueError("Invalid builder refusal")
    code, detail = value["code"], value["details"]
    if not isinstance(code, str) or code not in MESSAGES or type(detail) is not dict:
        raise ValueError("Invalid builder refusal")
    keys = set(detail)
    if keys not in ({"path", "problem"}, {"path", "problem", "triangles", "limit"}):
        raise ValueError("Invalid builder diagnostic")
    for key, maximum in (("path", 240), ("problem", 500)):
        text = detail[key]
        if not isinstance(text, str) or not 0 < len(text) <= maximum or any(ord(c) < 32 for c in text):
            raise ValueError("Invalid builder diagnostic text")
    if detail["path"] != "$" and not detail["path"].startswith(("$.", "$[")):
        raise ValueError("Invalid builder JSON path")
    if "limit" in detail and (type(detail["limit"]) is not int or detail["limit"] != TRIANGLE_LIMIT):
        raise ValueError("Invalid builder triangle limit")
    result = ModelBuildError(code, detail["path"], detail["problem"], triangles=detail.get("triangles"))
    if result.to_dict() != value:
        raise ValueError("Noncanonical builder refusal")
    return result
