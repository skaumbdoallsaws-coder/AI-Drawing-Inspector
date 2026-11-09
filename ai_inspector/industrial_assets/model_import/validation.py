"""Strict JSON and scalar checks shared by reader and worker protocol."""
import json
import math
import unicodedata

from .errors import ModelImportError


def require(condition: bool, code: str = "gltf_invalid") -> None:
    if not condition:
        raise ModelImportError(code)


def integer(value, minimum: int = 0, maximum: int | None = None) -> int:
    require(type(value) is int and value >= minimum and (maximum is None or value <= maximum))
    return value


def number(value, minimum: float | None = None, maximum: float | None = None) -> float:
    require(type(value) in (int, float))
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise ModelImportError("gltf_invalid") from None
    require(math.isfinite(result) and (minimum is None or result >= minimum)
            and (maximum is None or result <= maximum))
    return result


def vector(value, count: int, minimum=None, maximum=None) -> list[float]:
    require(isinstance(value, list) and len(value) == count)
    return [number(item, minimum, maximum) for item in value]


def mapping(value) -> dict:
    require(isinstance(value, dict))
    return value


def sequence(value, maximum: int = 65536) -> list:
    require(isinstance(value, list))
    require(len(value) <= maximum, "gltf_too_complex")
    return value


def reference(value, values: list) -> int:
    return integer(value, 0, len(values) - 1)


def clean_text(value, limit: int = 80) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join("".join(c for c in value if not unicodedata.category(c).startswith("C")).split())[:limit].rstrip()


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"),
                      sort_keys=True).encode("utf-8")


def parse_json(payload: bytes, maximum: int) -> dict:
    require(len(payload) <= maximum, "gltf_too_complex")
    try:
        return mapping(json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_object,
                                  parse_constant=lambda _: (_ for _ in ()).throw(ValueError())))
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise ModelImportError("gltf_invalid") from None


def warn(warnings: list[str], message: str) -> None:
    message = clean_text(message, 300)
    if message not in warnings and len(warnings) < 20:
        warnings.append(message)
