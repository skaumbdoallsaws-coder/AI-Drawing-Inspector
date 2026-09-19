"""Publication-safe component nomenclature for operations-manual figures."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Mapping


NOMENCLATURE_FILENAME = "publication-nomenclature.json"

_TOOLBOX_CONFIGURATION_RE = re.compile(
    r"^B18(?:\.\d+)+M\s*-\s*(?P<description>.+?)(?:\s+--[A-Za-z0-9]+)?$",
    re.IGNORECASE,
)
_CAD_EXTENSION_RE = re.compile(r"\.(?:sldprt|sldasm)\b", re.IGNORECASE)
_MODEL_PREFIX_RE = re.compile(r"^(?:USER\s+LIBRARY[-_ ]*)?MMLE[-_ ]?50D[-_ ]*", re.IGNORECASE)
_PRODUCT_TOKEN_RE = re.compile(r"^MMLE\s+", re.IGNORECASE)
_INTERNAL_SUFFIX_RE = re.compile(r"\s+--[A-Za-z0-9]+\b")
_GENERIC_GRADE_SUFFIX_RE = re.compile(r",\s*regular\s*$", re.IGNORECASE)
_DEFAULT_CONFIGURATION_SUFFIX_RE = re.compile(
    r"\s*[-,(]?\s*Default\s*\)?\s*$", re.IGNORECASE
)
_SPACE_RE = re.compile(r"\s+")
_METRIC_VALUE_RE = re.compile(r"^(?P<value>\d+(?:\.\d+)?)\s*mm$", re.IGNORECASE)
_METRIC_PAIR_RE = re.compile(
    r"^(?P<first>\d+(?:\.\d+)?)\s*[xX]\s*(?P<second>\d+(?:\.\d+)?)(?:\s*mm)?$",
    re.IGNORECASE,
)
_SHAFT_DIMENSION_SUFFIX_RE = re.compile(
    r"^(?P<base>(?:shaft|shaft tube))\s*-\s*"
    r"(?P<dimension>\d+(?:\.\d+)?(?:\s*[xX]\s*\d+(?:\.\d+)?)?(?:\s*mm)?)$",
    re.IGNORECASE,
)

_FORBIDDEN_PUBLICATION_PATTERNS = (
    (re.compile(r"\bDefault\b", re.IGNORECASE), "default CAD configuration"),
    (re.compile(r"\bB18(?:\.\d+)+", re.IGNORECASE), "Toolbox standard designator"),
    (re.compile(r"--[A-Za-z0-9]+\b"), "Toolbox configuration suffix"),
    (_CAD_EXTENSION_RE, "CAD filename extension"),
    (re.compile(r"\bUser\s+Library\b", re.IGNORECASE), "library prefix"),
    (re.compile(r"\bA02\s*A2\s*PTN\b", re.IGNORECASE), "unresolved CAD code"),
    (re.compile(r"^SV08(?:\b|[-_])", re.IGNORECASE), "unresolved CAD model code"),
    (re.compile(r"^BDI$", re.IGNORECASE), "unexpanded CAD abbreviation"),
    (re.compile(r"\bCHGR\b", re.IGNORECASE), "unexpanded CAD abbreviation"),
    (re.compile(r"\bSW\b", re.IGNORECASE), "unexpanded CAD abbreviation"),
    (re.compile(r"\bVintage Battery\b", re.IGNORECASE), "placeholder CAD name"),
)

_WORD_CASE = {
    "bdi": "BDI",
    "dc": "DC",
    "id": "ID",
    "mm": "mm",
}


class OperationsManualNomenclatureError(ValueError):
    """Raised when internal CAD nomenclature would reach publication content."""


def _title_component_description(value: str) -> str:
    words = []
    for word in _SPACE_RE.sub(" ", value).strip().split(" "):
        lowered = word.casefold()
        if lowered in _WORD_CASE:
            words.append(_WORD_CASE[lowered])
        elif re.fullmatch(r"M\d+(?:\.\d+)?", word, flags=re.IGNORECASE):
            words.append(word.upper())
        elif re.fullmatch(r"\d+(?:\.\d+)?", word):
            words.append(word)
        else:
            words.append(word[:1].upper() + word[1:].lower())
    return " ".join(words)


def _normalize_metric_configuration(value: Any, *, assume_mm: bool = False) -> str:
    text = _SPACE_RE.sub(" ", str(value or "").strip())
    if not text or text.casefold() == "default":
        return ""
    match = _METRIC_VALUE_RE.fullmatch(text)
    if match:
        return f"{match.group('value')} mm"
    match = _METRIC_PAIR_RE.fullmatch(text)
    if match:
        return f"{match.group('first')} x {match.group('second')} mm"
    if assume_mm and re.fullmatch(r"\d+(?:\.\d+)?", text):
        return f"{text} mm"
    return ""


def _normalize_toolbox_description(configuration: Any) -> str:
    text = _SPACE_RE.sub(" ", str(configuration or "").strip())
    match = _TOOLBOX_CONFIGURATION_RE.fullmatch(text)
    if not match:
        return ""
    description = _INTERNAL_SUFFIX_RE.sub("", match.group("description")).strip(" ,-_")
    description = _GENERIC_GRADE_SUFFIX_RE.sub("", description).strip(" ,-_ ")
    description = re.sub(r"(?<=\d)\s*[xX]\s*(?=\d)", " x ", description)
    if "," in description:
        component, specification = description.split(",", 1)
        return f"{_title_component_description(component)}, {specification.strip()}"
    metric = re.search(r"\bM\d+(?:\.\d+)?\b", description, flags=re.IGNORECASE)
    if metric:
        component = description[: metric.start()].strip(" ,-_")
        specification = description[metric.start() :].strip()
        return f"{_title_component_description(component)}, {specification}"
    return _title_component_description(description)


def _normalize_base_description(value: Any) -> str:
    text = str(value or "").replace("_", " ").strip()
    text = _CAD_EXTENSION_RE.sub("", text)
    text = _MODEL_PREFIX_RE.sub("", text)
    text = _PRODUCT_TOKEN_RE.sub("", text)
    text = _INTERNAL_SUFFIX_RE.sub("", text)
    text = _DEFAULT_CONFIGURATION_SUFFIX_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text).strip(" ,-_")
    return _title_component_description(text) if text else ""


def _split_shaft_dimension(value: str) -> tuple[str, str]:
    """Separate dimensions embedded in CAD shaft names from the publication noun."""
    match = _SHAFT_DIMENSION_SUFFIX_RE.fullmatch(str(value or "").strip())
    if not match:
        return value, ""
    dimension = _normalize_metric_configuration(
        match.group("dimension"),
        assume_mm=True,
    )
    if not dimension:
        return value, ""
    return _title_component_description(match.group("base")), dimension


def load_publication_aliases(
    evidence_root: str | Path,
    assembly_number: str,
) -> Dict[str, Dict[str, Any]]:
    path = Path(evidence_root) / NOMENCLATURE_FILENAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperationsManualNomenclatureError(
            f"cannot load publication nomenclature: {path}"
        ) from exc
    registered_assembly = str(payload.get("assemblyNumber") or "").strip()
    if registered_assembly.casefold() != str(assembly_number).strip().casefold():
        raise OperationsManualNomenclatureError(
            "publication nomenclature is bound to a different assembly"
        )
    result: Dict[str, Dict[str, Any]] = {}
    for source in payload.get("aliases") or []:
        if not isinstance(source, Mapping):
            continue
        definition_id = str(source.get("definitionId") or "").strip()
        description = str(source.get("displayDescription") or "").strip()
        if not definition_id or not description:
            raise OperationsManualNomenclatureError(
                "publication nomenclature aliases require definitionId and displayDescription"
            )
        if definition_id in result:
            raise OperationsManualNomenclatureError(
                f"duplicate publication nomenclature alias: {definition_id}"
            )
        result[definition_id] = dict(source)
    return result


def resolve_publication_description(
    row: Mapping[str, Any],
    aliases: Mapping[str, Mapping[str, Any]],
) -> Dict[str, str]:
    definition_id = str(row.get("definitionId") or "")
    alias = aliases.get(definition_id)
    if isinstance(alias, Mapping):
        description = str(alias.get("displayDescription") or "").strip()
        source = str(alias.get("source") or "authored_publication_alias")
    else:
        configuration = str(row.get("configuration") or "")
        description = _normalize_toolbox_description(configuration)
        source = "derived_toolbox_configuration" if description else ""
        if not description:
            base = _normalize_base_description(
                row.get("description") or row.get("name") or ""
            )
            dimension = _normalize_metric_configuration(
                configuration,
                assume_mm=base.casefold() in {"shaft", "shaft tube"},
            )
            base, embedded_dimension = _split_shaft_dimension(base)
            if embedded_dimension:
                dimension = embedded_dimension
            description = f"{base}, {dimension}" if base and dimension else base
            source = "derived_cad_description"
    description = _SPACE_RE.sub(" ", description).strip(" ,-_")
    if not description:
        description = "Description not specified"
        source = "missing"
    validate_publication_description(description)
    return {
        "displayDescription": description,
        "nomenclatureSource": source,
    }


def validate_publication_description(description: Any) -> None:
    text = str(description or "").strip()
    if not text:
        raise OperationsManualNomenclatureError("empty publication description")
    for pattern, label in _FORBIDDEN_PUBLICATION_PATTERNS:
        if pattern.search(text):
            raise OperationsManualNomenclatureError(
                f"publication description contains {label}: {text}"
            )
    if re.search(r"\d(?:MM|Mm|mM)\b", text):
        raise OperationsManualNomenclatureError(
            f"publication description contains inconsistent metric units: {text}"
        )


def validate_figure_nomenclature(
    figure_id: str,
    items: Iterable[Mapping[str, Any]],
) -> None:
    labels: Dict[str, str] = {}
    for item in items:
        description = str(item.get("description") or "")
        validate_publication_description(description)
        key = description.casefold()
        definition_id = str(item.get("definitionId") or "")
        previous = labels.get(key)
        if previous and previous != definition_id:
            raise OperationsManualNomenclatureError(
                f"{figure_id} publishes duplicate component description: {description}"
            )
        labels[key] = definition_id
