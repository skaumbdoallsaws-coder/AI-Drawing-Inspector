import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def count_text_runs(annotation):
    return len(annotation.get("textRuns") or [])


def annotation_score(annotation):
    score = 0
    if annotation.get("boundsSheet"):
        score += 8
    if annotation.get("positionSheet"):
        score += 5
    if annotation.get("leaders"):
        score += 3
    if annotation.get("textExtent"):
        score += 2
    score += count_text_runs(annotation)
    for key in ("dimensionText", "noteText", "gtolText", "featureName"):
        if annotation.get(key):
            score += 1
    return score


def choose_annotation(existing, incoming):
    return incoming if annotation_score(incoming) > annotation_score(existing) else existing


def merge_annotations(existing_list, incoming_list):
    merged = []
    by_key = {}

    def ann_key(annotation):
        name = annotation.get("annotationName") or ""
        ann_type = annotation.get("annotationType") or ""
        return (name, ann_type)

    for annotation in existing_list:
        item = copy.deepcopy(annotation)
        merged.append(item)
        by_key[ann_key(item)] = len(merged) - 1

    for annotation in incoming_list:
        key = ann_key(annotation)
        if key in by_key:
            idx = by_key[key]
            merged[idx] = choose_annotation(merged[idx], annotation)
        else:
            item = copy.deepcopy(annotation)
            merged.append(item)
            by_key[key] = len(merged) - 1

    return merged


def view_score(view):
    annotations = view.get("annotations") or []
    score = len(annotations) * 10
    if view.get("viewOutline"):
        score += 6
    if view.get("viewPosition"):
        score += 4
    if view.get("referencedConfiguration"):
        score += 2
    score += sum(annotation_score(a) for a in annotations)
    return score


def choose_scalar(existing, incoming):
    return existing if existing not in (None, "", [], {}) else incoming


def merge_view(existing, incoming):
    merged = copy.deepcopy(existing)
    for key in (
        "viewType",
        "viewOrientation",
        "viewOutline",
        "viewPosition",
        "viewScale",
        "referencedConfiguration",
    ):
        merged[key] = choose_scalar(merged.get(key), incoming.get(key))
        if incoming.get(key) not in (None, "", [], {}):
            if key == "viewScale":
                merged[key] = incoming.get(key) if not merged.get(key) else merged.get(key)

    existing_annotations = merged.get("annotations") or []
    incoming_annotations = incoming.get("annotations") or []
    merged["annotations"] = merge_annotations(existing_annotations, incoming_annotations)

    existing_primitives = merged.get("primitives") or []
    incoming_primitives = incoming.get("primitives") or []
    if incoming_primitives:
        if not existing_primitives or len(incoming_primitives) >= len(existing_primitives):
            merged["primitives"] = copy.deepcopy(incoming_primitives)

    # If the incoming view is materially richer overall, take any remaining top-level fields from it.
    if view_score(incoming) > view_score(existing):
        for key in incoming:
            if key in ("annotations", "primitives"):
                continue
            if incoming.get(key) not in (None, "", [], {}):
                merged[key] = copy.deepcopy(incoming[key])

    return merged


def merge_sheet(existing, incoming):
    merged = copy.deepcopy(existing)
    for key in ("sheetWidth", "sheetHeight", "paperSize", "scale", "sheetFormat"):
        merged[key] = choose_scalar(merged.get(key), incoming.get(key))

    merged_views = []
    view_index = {}
    for view in merged.get("views") or []:
        item = copy.deepcopy(view)
        merged_views.append(item)
        view_index[item.get("viewName")] = len(merged_views) - 1

    for view in incoming.get("views") or []:
        name = view.get("viewName")
        if name in view_index:
            idx = view_index[name]
            merged_views[idx] = merge_view(merged_views[idx], view)
        else:
            merged_views.append(copy.deepcopy(view))
            view_index[name] = len(merged_views) - 1

    merged["views"] = merged_views
    return merged


def merge_diagnostics(sources, merged):
    warnings = []
    for src in sources:
        src_name = src.get("_source_name", "unknown")
        diag = src.get("diagnostics") or {}
        status = diag.get("status") or "unknown"
        warnings.append(f"merged source: {src_name} (status={status})")
        for item in diag.get("warnings") or []:
            warnings.append(f"{src_name}: {item}")

    merged["diagnostics"] = {
        "status": "merged_partial_runs",
        "warnings": warnings,
        "mergedAt": datetime.now(timezone.utc).isoformat(),
        "sourceFiles": [src.get("_source_name", "unknown") for src in sources],
    }


def merge_drawing_maps(input_paths):
    sources = []
    for path in input_paths:
        data = load_json(path)
        data["_source_name"] = str(path)
        sources.append(data)

    base = copy.deepcopy(sources[0])
    base.pop("_source_name", None)

    # Top-level fields: keep the first non-empty stable values.
    for src in sources[1:]:
        for key in (
            "fileName",
            "filePath",
            "partNumber",
            "solidWorksVersion",
            "sheetWidth",
            "sheetHeight",
            "referencedModelPath",
        ):
            base[key] = choose_scalar(base.get(key), src.get(key))

    sheet_order = []
    sheets = {}

    for src in sources:
        for sheet in src.get("sheets") or []:
            name = sheet.get("sheetName")
            if not name:
                continue
            if name not in sheets:
                sheets[name] = copy.deepcopy(sheet)
                sheet_order.append(name)
            else:
                sheets[name] = merge_sheet(sheets[name], sheet)

    base["sheets"] = [sheets[name] for name in sheet_order]
    merge_diagnostics(sources, base)
    base["extractionTime"] = datetime.now(timezone.utc).isoformat()
    return base


def main():
    parser = argparse.ArgumentParser(description="Merge partial SolidWorks drawing maps by sheet/view.")
    parser.add_argument("inputs", nargs="+", help="Input drawing map JSON files")
    parser.add_argument("-o", "--output", required=True, help="Output merged drawing map path")
    args = parser.parse_args()

    input_paths = [Path(p) for p in args.inputs]
    output_path = Path(args.output)

    merged = merge_drawing_maps(input_paths)
    output_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
