"""Compile an assembly's inspection sheet: one section per part number, characteristics from the part's drawing
map (ballooned in the Report tab's order) or its inspection profile, an assembly check, and every value the app
does not have left as an open field. No file access: the server gathers the inputs."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

INSPECTION_SHEET_SCHEMA_VERSION = 1

# (key, label) of the job information the sheet needs before inspection; nothing in the app knows these.
HEADER_FIELDS = (
    ("customer", "Customer"),
    ("order", "Purchase order or job number"),
    ("lot", "Lot or serial number"),
    ("sample_size", "Sample size"),
)
SIGNOFF_ROLES = (("inspector", "Inspector"), ("reviewer", "Reviewer"))
VALUE_SOURCES = ("chat", "workspace", "returned_pdf")

_DIMENSION_TYPES = ("dimension", "displayDimension")
_TOKENS = {"<MOD-DIAM>": "\u00d8", "<MOD-DEG>": "\u00b0", "<MOD-PM>": "\u00b1", "<MOD-RAD>": "R"}
_NUMBER_RE = re.compile(r"[+-]?\d+(?:\.(\d+))?")
_SAFE_ASSEMBLY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")


class InspectionSheetError(ValueError):
    pass


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def display_text(text: Any) -> str:
    """SolidWorks dimension text as printed: <MOD-DIAM>30.00 THRU -> \u00d830.00 THRU."""
    result = str(text or "")
    for token, symbol in _TOKENS.items():
        result = result.replace(token, symbol)
    result = re.sub(r"<[^>]{1,40}>", "", result)
    return " ".join(result.replace("\r", " ").replace("\n", " ").split())


def _parse_nominal(text: str) -> Optional[Dict[str, Any]]:
    """The Report tab's rule (_parseFaiNominalFromText): drop the symbols and an 'Nx' count, take the first number."""
    raw = re.sub(r"[\u00d8\u2300(),]", " ", text).replace("\u00b0", " deg ")
    count = re.match(r"^\s*(\d+)\s*[xX]\s+", raw)
    raw = raw[count.end():] if count else raw
    match = _NUMBER_RE.search(raw)
    if not match:
        return None
    return {"value": float(match.group(0)), "decimals": len(match.group(1) or ""),
            "count": int(count.group(1)) if count else 1}


_INCH_RE = re.compile(r"(?:in|inch|inches|\")$")


def parse_tolerance(value: Any) -> Optional[Dict[str, float]]:
    """A general tolerance as the user writes it, in mm: '0.1', '\u00b10.10 mm', '+/-0.1', '+0.10 -0.05',
    '+0.1/-0.05', or the same in inches ('\u00b10.004 in', converted). None for anything else (two readings, a
    decimal-place block, a percentage): the limits then stay blank rather than wrong."""
    text = " ".join(str(value or "").casefold().replace(",", ".").replace("+/-", "\u00b1").replace("+-", "\u00b1")
                    .split())
    scale = 1.0
    if _INCH_RE.search(text):
        scale, text = 25.4, _INCH_RE.sub("", text).strip()
    elif text.endswith("mm"):
        text = text[:-2].strip()
    number = r"(\d+(?:\.\d+)?|\.\d+)"
    match = re.fullmatch(rf"\u00b1?\s*{number}", text)
    if match:
        plus = minus = float(match.group(1))
    else:
        match = re.fullmatch(rf"\+\s*{number}\s*/?\s*-\s*{number}", text)
        if not match:
            return None
        plus, minus = float(match.group(1)), float(match.group(2))
    if not (math.isfinite(plus) and math.isfinite(minus)) or plus <= 0 or minus < 0:
        return None
    return {"plus": round(plus * scale, 6), "minus": round(minus * scale, 6)}


def drawing_characteristics(drawing_map: Mapping[str, Any], descriptions: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Visible, attached dimensions of a normalized drawing map, numbered like the Report tab's FAI table: by sheet,
    view order, then top to bottom and left to right."""
    texts = (descriptions or {}).get("descriptions") or {}
    rows = []
    for sheet_order, sheet in enumerate(drawing_map.get("sheets") or []):
        for view_order, view in enumerate(sheet.get("views") or []):
            for annotation in view.get("annotations") or []:
                if annotation.get("annotationType") not in _DIMENSION_TYPES:
                    continue
                if annotation.get("isDangling") or annotation.get("visible") is False:
                    continue
                position = annotation.get("positionSheet") or {}
                name = str(annotation.get("annotationName") or "")
                view_name = str(view.get("viewName") or "")
                text = display_text(annotation.get("dimensionText"))
                parsed = _parse_nominal(text)
                dimension_type = str(annotation.get("dimensionType") or "")
                angular = "\u00b0" in text or "angular" in dimension_type.lower()
                value_m = _number(annotation.get("dimensionValue"))
                if value_m is not None and not angular:
                    nominal = value_m * 1000
                else:
                    nominal = parsed["value"] if parsed else None
                decimals = parsed["decimals"] if parsed else 2
                tolerance = None
                tolerance_type = str(annotation.get("toleranceType") or "").strip().lower()
                plus, minus = _number(annotation.get("tolerancePlus")), _number(annotation.get("toleranceMinus"))
                if tolerance_type == "basic":
                    tolerance = {"kind": "basic"}
                elif tolerance_type not in ("", "none") and (plus or minus):
                    scale = 180 / math.pi if angular else 1000
                    tolerance = {"kind": "drawing", "plus": abs(plus or 0) * scale, "minus": abs(minus or 0) * scale}
                rows.append({
                    "key": f"{sheet_order}|{view_name}|{name}",
                    "sheet": sheet_order,
                    "viewOrder": view_order,
                    "view": view_name,
                    "viewOutline": view.get("viewOutline"),
                    "annotationName": name,
                    "text": text,
                    "description": str(texts.get(f"{sheet_order}|{view_name}/{name}")
                                       or texts.get(f"{view_name}/{name}") or ""),
                    "nominal": None if nominal is None else round(nominal, 6),
                    "unit": "deg" if angular else "mm",
                    "decimals": decimals,
                    "count": parsed["count"] if parsed else 1,
                    "reference": bool(annotation.get("isReference")),
                    "ownTolerance": tolerance,
                    "anchor": {"x": _number(position.get("x")), "y": _number(position.get("y"))},
                })
    rows.sort(key=lambda row: (row["sheet"], row["viewOrder"], -(row["anchor"]["y"] or 0), row["anchor"]["x"] or 0))
    for number, row in enumerate(rows, start=1):
        row["number"] = number
    return rows


def field_token(part_number: str) -> str:
    """A part number as it appears in field names (letters, digits, _ and - only)."""
    token = re.sub(r"[^A-Za-z0-9_-]", "_", str(part_number or "").strip())[:60].strip("_")
    return token if token and token[0].isalnum() else "p" + token


def requirement_limits(text: Any) -> Optional[Dict[str, float]]:
    """Limits from a requirement as the user writes it: '40.00 +/-0.02', '40 +0.02 -0.01', '39.98 - 40.02'.
    None when it is not one of those forms (a note, a thread, a finish): the row then has no limits."""
    raw = re.sub(r"[\u00d8\u2300R]|mm", " ", str(text or "")).replace(",", ".").replace("+/-", "\u00b1")
    number = r"(\d+(?:\.\d+)?)"
    match = re.fullmatch(rf"\s*{number}\s*\u00b1\s*{number}\s*", raw)
    if match:
        nominal, tolerance = float(match.group(1)), float(match.group(2))
        return {"lower": round(nominal - tolerance, 6), "upper": round(nominal + tolerance, 6)}
    match = re.fullmatch(rf"\s*{number}\s*\+\s*{number}\s*/?\s*-\s*{number}\s*", raw)
    if match:
        nominal = float(match.group(1))
        return {"lower": round(nominal - float(match.group(3)), 6), "upper": round(nominal + float(match.group(2)), 6)}
    match = re.fullmatch(rf"\s*{number}\s*(?:-|to)\s*{number}\s*", raw)
    if match:
        low, high = sorted((float(match.group(1)), float(match.group(2))))
        return {"lower": low, "upper": high}
    return None


def _first_sentence(text: Any, limit: int = 220) -> str:
    sentence = re.split(r"(?<=[.;])\s", " ".join(str(text or "").split()), maxsplit=1)[0]
    sentence = sentence[:-1] + "." if sentence.endswith(";") else sentence
    return sentence if len(sentence) <= limit else sentence[:limit - 3].rstrip() + "..."


class _Fields:
    """Field definitions in document order; positions are added by the exporter."""

    def __init__(self, values: Mapping[str, Mapping[str, Any]]):
        self.values = values
        self.items: List[Dict[str, Any]] = []

    def add(self, name, label, *, kind="text", role="record", context=None):
        stored = self.values.get(name) or {}
        value = stored.get("value")
        if kind == "signature":
            value = None
        field = {"name": name, "label": label, "kind": kind, "role": role,
                 "value": None if value in (None, "") else value, "context": context}
        self.items.append(field)
        return name

    def value(self, name):
        return (self.values.get(name) or {}).get("value")

    def flag(self, name, problem):
        """A provided value the app cannot use: the field counts as open again, with the reason."""
        for field in self.items:
            if field["name"] == name:
                field["problem"] = problem


def build_inspection_sheet_document(
    *,
    assembly: Mapping[str, Any],
    bom: Iterable[Mapping[str, Any]],
    parts: Mapping[str, Mapping[str, Any]],
    values: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """assembly: {assemblyNumber, name, sourceRevision}; bom: the whole-assembly BOM rows {item, partNumber,
    description, quantity}; parts: per part number {drawingMap (normalized), descriptions, profile, hasDrawingPdf};
    values: the stored values by field name {value, source, at}."""
    assembly_number = str(assembly.get("assemblyNumber") or "")
    if not _SAFE_ASSEMBLY_RE.fullmatch(assembly_number):
        raise InspectionSheetError("invalid assembly number")
    fields = _Fields(values or {})
    for key, label in HEADER_FIELDS:
        fields.add(f"header.{key}", label, role="provide")
    fields.add("header.inspection_date", "Inspection date", role="record")

    sections = []
    bom_rows = []
    seen = set()
    for index, row in enumerate(bom, start=1):
        part_number = str(row.get("partNumber") or "").strip()
        item = row.get("item") or index
        bom_rows.append({
            "item": item, "partNumber": part_number or "Not specified",
            "description": str(row.get("description") or ""), "quantity": row.get("quantity"),
            "fields": {"found": fields.add(f"bom.{item}.found", f"Item {item}: quantity found"),
                       "conforms": fields.add(f"bom.{item}.conforms", f"Item {item}: correct part and quantity",
                                              kind="checkbox")},
        })
        if not part_number or part_number == "Not specified" or part_number in seen:
            continue
        seen.add(part_number)
        sources = parts.get(part_number) or {}
        token = field_token(part_number)
        base = f"part.{token}"
        section = {"item": item, "partNumber": part_number, "description": str(row.get("description") or ""),
                   "quantity": row.get("quantity")}
        drawing_map = sources.get("drawingMap")
        characteristics = drawing_characteristics(drawing_map, sources.get("descriptions") or {}) \
            if drawing_map else []
        if characteristics:
            section["source"] = "drawing"
            section["hasDrawingPdf"] = bool(sources.get("hasDrawingPdf"))
            section["sheets"] = [{"width": _number(sheet.get("sheetWidth")), "height": _number(sheet.get("sheetHeight")),
                                  "views": [{"name": view.get("viewName"), "outline": view.get("viewOutline")}
                                            for view in sheet.get("views") or []]}
                                 for sheet in drawing_map.get("sheets") or []]
            section["fields"] = {
                "drawingRevision": fields.add(f"{base}.drawing_revision", f"{part_number}: drawing revision",
                                              role="provide", context=part_number),
            }
            needs_general = any(not characteristic["ownTolerance"] and not characteristic["reference"] for characteristic in characteristics)
            general = None
            if needs_general:
                section["fields"]["generalTolerance"] = fields.add(
                    f"{base}.general_tolerance",
                    f"{part_number}: general tolerance (title block, for dimensions without their own)",
                    role="provide", context=part_number)
                given = fields.value(f"{base}.general_tolerance")
                general = parse_tolerance(given)
                section["generalTolerance"] = general
                if given not in (None, "") and general is None:
                    section["generalToleranceProblem"] = (
                        f"'{given}' is not one tolerance the app can read; give it as \u00b10.05 mm or "
                        "+0.10 -0.05 mm. Limits stay blank until then.")
                    fields.flag(f"{base}.general_tolerance", section["generalToleranceProblem"])
            for characteristic in characteristics:
                prefix = f"char.{token}.{characteristic['number']}"
                tolerance = characteristic["ownTolerance"]
                if tolerance is None and general is not None and not characteristic["reference"]:
                    tolerance = {"kind": "general", **general}
                characteristic["tolerance"] = tolerance
                if tolerance and tolerance.get("kind") in ("drawing", "general") and characteristic["nominal"] is not None:
                    characteristic["lower"] = round(characteristic["nominal"] - tolerance["minus"], 6)
                    characteristic["upper"] = round(characteristic["nominal"] + tolerance["plus"], 6)
                else:
                    characteristic["lower"] = characteristic["upper"] = None
                if characteristic["reference"]:
                    characteristic["fields"] = {}
                    continue
                label = f"{part_number} #{characteristic['number']} {characteristic['text']}"
                characteristic["fields"] = {
                    "measured": fields.add(f"{prefix}.measured", f"{label}: measured value, {characteristic['unit']}"),
                    "conforms": fields.add(f"{prefix}.conforms", f"{label}: conforms", kind="checkbox"),
                    "gauge": fields.add(f"{prefix}.gauge", f"{label}: gauge or method"),
                }
            section["characteristics"] = characteristics
        else:
            profile = sources.get("profile") or {}
            features = [feature for feature in profile.get("features") or [] if isinstance(feature, Mapping)]
            section["source"] = "profile" if features else "none"
            section["fields"] = {
                "drawingRevision": fields.add(f"{base}.drawing_revision",
                                              f"{part_number}: drawing number and revision", role="provide",
                                              context=part_number),
            }
            rows = []
            for number, feature in enumerate(features or [{"name": "Inspect to drawing"}], start=1):
                prefix = f"char.{token}.{number}"
                name = " ".join(str(feature.get("name") or f"Feature {number}").split())
                limits = requirement_limits(fields.value(f"{prefix}.requirement")) or {}
                rows.append({
                    "number": number, "name": name, "type": feature.get("type"),
                    "lower": limits.get("lower"), "upper": limits.get("upper"),
                    "count": feature.get("count") or 1,
                    "reason": _first_sentence(feature.get("inspection_reason")),
                    "fields": {
                        "requirement": fields.add(f"{prefix}.requirement",
                                                  f"{part_number} {name}: requirement (from the drawing)",
                                                  role="provide", context=part_number),
                        "measured": fields.add(f"{prefix}.measured", f"{part_number} {name}: measured"),
                        "conforms": fields.add(f"{prefix}.conforms", f"{part_number} {name}: conforms",
                                               kind="checkbox"),
                        "gauge": fields.add(f"{prefix}.gauge", f"{part_number} {name}: gauge or method"),
                    },
                })
            section["features"] = rows
        sections.append(section)

    for role, title in SIGNOFF_ROLES:
        fields.add(f"signoff.{role}.name", f"{title} name")
        fields.add(f"signoff.{role}.date", f"{title} date")
        fields.add(f"signoff.{role}.signature", f"{title} signature", kind="signature")
    fields.add("result.accept", "Result: accept", kind="checkbox")
    fields.add("result.reject", "Result: reject", kind="checkbox")
    fields.add("signoff.notes", "Notes", kind="multiline")

    # Each measured row's result against the limits the app has (the same rule as a returned copy's check).
    results = conformance({"sections": sections}, values or {})
    statuses = {(row["partNumber"], row["number"]): row["status"] for row in results["rows"]}
    for section in sections:
        for row in (section.get("characteristics") or []) + (section.get("features") or []):
            if (section["partNumber"], row["number"]) in statuses:
                row["status"] = statuses[(section["partNumber"], row["number"])]

    open_fields = [{"name": field["name"], "label": field["label"], "part": field["context"],
                    **({"problem": field["problem"]} if field.get("problem") else {})}
                   for field in fields.items
                   if field["role"] == "provide" and (field["value"] in (None, "") or field.get("problem"))]
    characteristic_count = sum(len(section.get("characteristics") or section.get("features") or [])
                               for section in sections)
    body = {
        "schemaVersion": INSPECTION_SHEET_SCHEMA_VERSION,
        "documentType": "inspection_sheet",
        "assemblyNumber": assembly_number,
        "assemblyName": str(assembly.get("name") or assembly_number),
        "sourceRevision": str(assembly.get("sourceRevision") or ""),
        "sections": sections,
        "bom": bom_rows,
        "fields": fields.items,
        "openFields": open_fields,
        "summary": {
            "parts": len(sections),
            "partsWithDrawing": sum(1 for section in sections if section["source"] == "drawing"),
            "partsWithProfileOnly": sum(1 for section in sections if section["source"] == "profile"),
            "partsWithNothing": sum(1 for section in sections if section["source"] == "none"),
            "characteristics": characteristic_count,
            "balloonedCharacteristics": sum(len(section.get("characteristics") or []) for section in sections),
            "openFields": len(open_fields),
            "fields": len(fields.items),
            "results": results["counts"],
            "disagreements": results["disagreements"],
        },
    }
    body["documentRevision"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("ascii")
    ).hexdigest()
    return body


def _measured_number(value: Any) -> Optional[float]:
    match = _NUMBER_RE.fullmatch(str(value or "").strip().replace(",", "."))
    return float(match.group(0)) if match else None


def conformance(document: Mapping[str, Any], values: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """Each controlled characteristic's measured value against the limits the app has: PASS, FAIL, NO_LIMITS (the
    tolerance or requirement is still open), PENDING (not measured) or UNREADABLE. The inspector's own tick is
    reported next to it; a ticked FAIL is flagged as a disagreement, never overridden."""
    rows = []
    for section in document.get("sections") or []:
        for row in (section.get("characteristics") or []) + (section.get("features") or []):
            names = row.get("fields") or {}
            if "measured" not in names:
                continue
            measured_raw = (values.get(names["measured"]) or {}).get("value")
            ticked = (values.get(names.get("conforms", "")) or {}).get("value")
            lower, upper = row.get("lower"), row.get("upper")
            if measured_raw in (None, ""):
                status = "PENDING"
            elif lower is None or upper is None:
                status = "NO_LIMITS"
            else:
                measured = _measured_number(measured_raw)
                status = "UNREADABLE" if measured is None else (
                    "PASS" if lower - 1e-9 <= measured <= upper + 1e-9 else "FAIL")
            rows.append({
                "partNumber": section["partNumber"], "number": row["number"],
                "characteristic": row.get("text") or row.get("name"),
                "measured": measured_raw, "lower": lower, "upper": upper, "status": status,
                "inspectorConforms": bool(ticked),
                "disagreement": status == "FAIL" and bool(ticked),
            })
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"rows": rows, "counts": counts, "disagreements": sum(1 for row in rows if row["disagreement"])}
