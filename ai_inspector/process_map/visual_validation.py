"""Occurrence-level visual review for semantic process-map proposals.

The model reviews meaning only. Rendering, occurrence identity, correction
bounds, and final semantic validation remain deterministic.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from ai_inspector.assembly_knowledge.manifest import canonical_json_sha256
from ai_inspector.assembly_knowledge.provider import MultimodalEnrichmentProvider


PROCESS_MAP_VISUAL_VALIDATION_VERSION = 1
PROCESS_MAP_VISUAL_VALIDATION_PROMPT_VERSION = "process-map-visual-review-v3"
PROCESS_MAP_VISUAL_VALIDATION_MIN_CONFIDENCE = 0.90

_VIEW_ORDER = ("isometric", "front", "right", "top")
_DIRECT_COLOR = (245, 153, 45)
_INHERITED_COLOR = (42, 185, 214)
_BACKGROUND = (244, 247, 250)
_TEXT = (28, 38, 50)
_MUTED_TEXT = (81, 96, 112)

_SYSTEM_PROMPT = """\
You are reviewing a temporary manufacturing process-map proposal against fixed
assembly views. The images are occurrence-accurate visual evidence:
- orange identifies new direct part inputs assigned to the current operation;
- cyan identifies parts inherited from predecessor operations;
- gray identifies parts not yet assigned to that operation's cumulative state.

Review only whether an operation's label and direct part membership are
spatially coherent with the visible assembly. Product structure, proximity,
geometry, and mates do not prove manufacturing order. Do not invent operations,
precedence, tools, torque, dimensions, requirements, or manufacturing facts.

Audit every orange occurrence individually. A stage is coherent only when its
label accounts for every orange occurrence and those occurrences occupy a
spatially coherent assembly region. Do not accept a stage merely because its
label sounds plausible. Small numbered boxes identify direct occurrences that
would otherwise be easy to miss. If one direct occurrence clearly belongs to a
different visible product region, report it even when the other inputs fit.

You may propose only:
1. a clearer label for an existing operation; or
2. moving an existing direct occurrence from its current operation to another
   existing operation when the visual mismatch and destination are clear.

Use only operation IDs and occurrence IDs supplied in the request. Mark
uncertain cases for review instead of guessing. Return one review for every
operation. Corrections remain inferred and will be rejected unless deterministic
semantic validation still passes. Keep findings and reasons concise.
"""


class ProcessMapVisualValidationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _stable_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_artifact_root(path: str | Path) -> Path:
    root = Path(path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        ("arialbd.ttf" if bold else "arial.ttf"),
        ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _operation_contexts(
    semantic_plan: Mapping[str, Any],
    product_structure: Mapping[str, Any],
) -> list[Dict[str, Any]]:
    operations = [
        item
        for item in semantic_plan.get("operations", [])
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    ]
    if not operations:
        raise ProcessMapVisualValidationError(
            "visual_review_operations_missing",
            "The semantic plan has no operation stages to review.",
        )
    operation_by_id = {str(item["id"]): item for item in operations}
    if len(operation_by_id) != len(operations):
        raise ProcessMapVisualValidationError(
            "visual_review_operation_id_duplicate",
            "The semantic plan contains duplicate operation IDs.",
        )
    occurrence_names = {
        str(item["occurrenceId"]): str(item.get("name") or item["occurrenceId"])
        for item in product_structure.get("occurrences", [])
        if isinstance(item, Mapping) and isinstance(item.get("occurrenceId"), str)
    }
    produced_by = {
        str(item["id"]): str(item["producedBy"])
        for item in semantic_plan.get("intermediateResults", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("producedBy"), str)
    }
    direct_by_operation: Dict[str, set[str]] = {}
    predecessors: Dict[str, set[str]] = {}
    for operation_id, operation in operation_by_id.items():
        direct: set[str] = set()
        parents: set[str] = set()
        for input_item in operation.get("inputs", []):
            if not isinstance(input_item, Mapping):
                continue
            ref = input_item.get("ref")
            input_type = input_item.get("type")
            if not isinstance(ref, str):
                continue
            if input_type == "occurrence":
                direct.add(ref)
            elif input_type == "intermediateResult" and ref in produced_by:
                parents.add(produced_by[ref])
        direct_by_operation[operation_id] = direct
        predecessors[operation_id] = parents

    cumulative_cache: Dict[str, set[str]] = {}

    def cumulative(operation_id: str, stack: tuple[str, ...] = ()) -> set[str]:
        if operation_id in cumulative_cache:
            return set(cumulative_cache[operation_id])
        if operation_id in stack:
            raise ProcessMapVisualValidationError(
                "visual_review_precedence_cycle",
                "The semantic plan contains a precedence cycle.",
            )
        result = set(direct_by_operation[operation_id])
        for predecessor_id in sorted(predecessors[operation_id]):
            if predecessor_id not in operation_by_id:
                raise ProcessMapVisualValidationError(
                    "visual_review_predecessor_unknown",
                    f"Operation '{operation_id}' has an unknown predecessor.",
                )
            result.update(cumulative(predecessor_id, stack + (operation_id,)))
        cumulative_cache[operation_id] = set(result)
        return result

    contexts: list[Dict[str, Any]] = []
    for operation_id, operation in operation_by_id.items():
        direct_ids = sorted(direct_by_operation[operation_id])
        cumulative_ids = sorted(cumulative(operation_id))
        inherited_ids = sorted(set(cumulative_ids) - set(direct_ids))
        contexts.append(
            {
                "operationId": operation_id,
                "label": str(operation.get("label") or operation_id),
                "stageIndex": int(operation.get("stageIndex") or 0),
                "branchId": (
                    str(operation["branchId"])
                    if isinstance(operation.get("branchId"), str)
                    else None
                ),
                "predecessorOperationIds": sorted(predecessors[operation_id]),
                "directOccurrences": [
                    {
                        "occurrenceId": occurrence_id,
                        "name": occurrence_names.get(occurrence_id, occurrence_id),
                    }
                    for occurrence_id in direct_ids
                ],
                "inheritedOccurrences": [
                    {
                        "occurrenceId": occurrence_id,
                        "name": occurrence_names.get(occurrence_id, occurrence_id),
                    }
                    for occurrence_id in inherited_ids
                ],
                "cumulativeOccurrenceIds": cumulative_ids,
            }
        )
    return sorted(
        contexts,
        key=lambda item: (
            int(item["stageIndex"]),
            str(item["operationId"]),
        ),
    )


def build_process_map_visual_review_context(
    semantic_plan: Mapping[str, Any],
    assembly_knowledge: Mapping[str, Any],
) -> Dict[str, Any]:
    documents = assembly_knowledge.get("documents")
    binding = assembly_knowledge.get("binding")
    if not isinstance(documents, Mapping) or not isinstance(binding, Mapping):
        raise ProcessMapVisualValidationError(
            "visual_review_package_missing",
            "A resolved Assembly Knowledge Package is required.",
        )
    structure = documents.get("product_structure.json")
    visual = documents.get("visual_manifest.json")
    package = documents.get("package.json")
    if not all(
        isinstance(item, Mapping)
        for item in (structure, visual, package)
    ):
        raise ProcessMapVisualValidationError(
            "visual_review_package_incomplete",
            "The Assembly Knowledge Package lacks structure or visual evidence.",
        )
    views = [
        copy.deepcopy(dict(item))
        for item in visual.get("views", [])
        if isinstance(item, Mapping)
        and item.get("kind") == "presentation"
        and isinstance(item.get("assetPath"), str)
        and isinstance(item.get("maskAssetPath"), str)
    ]
    if not views:
        raise ProcessMapVisualValidationError(
            "visual_review_views_missing",
            "No paired assembly presentation and identity-mask views are available.",
        )
    order = {name: index for index, name in enumerate(_VIEW_ORDER)}
    views.sort(
        key=lambda item: (
            order.get(
                str((item.get("camera") or {}).get("namedView") or ""),
                len(order),
            ),
            str(item.get("viewId") or ""),
        )
    )
    return {
        "schemaVersion": PROCESS_MAP_VISUAL_VALIDATION_VERSION,
        "planId": str(semantic_plan.get("planId") or ""),
        "scope": copy.deepcopy(dict(semantic_plan.get("scope") or {})),
        "packageBinding": {
            field: binding.get(field)
            for field in (
                "packageId",
                "packageRevision",
                "sourceRevision",
                "evidenceFingerprint",
                "contextFingerprint",
            )
        },
        "operations": _operation_contexts(semantic_plan, structure),
        "views": views[:4],
        "assetHashes": copy.deepcopy(dict(package.get("assetHashes") or {})),
    }


def _verified_view_paths(
    context: Mapping[str, Any],
    package_dir: str | Path,
) -> list[Dict[str, Any]]:
    package_root = Path(package_dir).resolve()
    asset_hashes = context["assetHashes"]
    resolved: list[Dict[str, Any]] = []
    for view in context["views"]:
        item = copy.deepcopy(dict(view))
        for field, hash_field, target_field in (
            ("assetPath", "assetHash", "presentationPath"),
            ("maskAssetPath", "maskAssetHash", "maskPath"),
        ):
            relative_path = str(item[field])
            target = (package_root / relative_path).resolve()
            try:
                target.relative_to(package_root)
            except ValueError as exc:
                raise ProcessMapVisualValidationError(
                    "visual_review_asset_path_escape",
                    "A visual-review asset path escapes the package.",
                ) from exc
            expected = str(item.get(hash_field) or "")
            if (
                not target.is_file()
                or asset_hashes.get(relative_path) != expected
                or _sha256_file(target) != expected
            ):
                raise ProcessMapVisualValidationError(
                    "visual_review_asset_hash_mismatch",
                    f"Visual-review asset is missing or stale: {relative_path}",
                )
            item[target_field] = target
        resolved.append(item)
    return resolved


def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = str(hex_color or "").strip().lstrip("#")
    if len(value) != 6:
        raise ProcessMapVisualValidationError(
            "visual_review_color_invalid",
            f"Invalid identity-mask color: {hex_color}",
        )
    try:
        return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError as exc:
        raise ProcessMapVisualValidationError(
            "visual_review_color_invalid",
            f"Invalid identity-mask color: {hex_color}",
        ) from exc


def _identity_selection_mask(
    image: Image.Image,
    color_legend: Mapping[str, Any],
    occurrence_ids: Iterable[str],
) -> Image.Image:
    selected = set(str(item) for item in occurrence_ids)
    colors = {
        _rgb(color)
        for color, occurrence_id in color_legend.items()
        if str(occurrence_id) in selected
    }
    mask = Image.new("L", image.size, 0)
    if not colors:
        return mask
    pixels = image.convert("RGB").getdata()
    mask.putdata([255 if pixel in colors else 0 for pixel in pixels])
    return mask.filter(ImageFilter.MaxFilter(3))


def _outline(mask: Image.Image, width: int = 5) -> Image.Image:
    expanded = mask.filter(ImageFilter.MaxFilter(max(3, width | 1)))
    return ImageChops.subtract(expanded, mask)


def _occurrence_bboxes(
    image: Image.Image,
    color_legend: Mapping[str, Any],
) -> Dict[str, tuple[int, int, int, int]]:
    color_to_occurrence = {
        _rgb(color): str(occurrence_id)
        for color, occurrence_id in color_legend.items()
    }
    bounds: Dict[str, list[int]] = {}
    width, _ = image.size
    for index, pixel in enumerate(image.convert("RGB").getdata()):
        occurrence_id = color_to_occurrence.get(pixel)
        if occurrence_id is None:
            continue
        x = index % width
        y = index // width
        current = bounds.get(occurrence_id)
        if current is None:
            bounds[occurrence_id] = [x, y, x, y]
        else:
            current[0] = min(current[0], x)
            current[1] = min(current[1], y)
            current[2] = max(current[2], x)
            current[3] = max(current[3], y)
    return {
        occurrence_id: tuple(value)
        for occurrence_id, value in bounds.items()
    }


def _render_stage_view(
    presentation: Image.Image,
    identity_mask: Image.Image,
    color_legend: Mapping[str, Any],
    *,
    direct_occurrences: Sequence[Mapping[str, Any]],
    inherited_ids: Sequence[str],
    occurrence_bboxes: Mapping[str, tuple[int, int, int, int]],
    width: int,
) -> Image.Image:
    base = presentation.convert("RGB")
    dim = ImageEnhance.Brightness(
        ImageOps.grayscale(base).convert("RGB")
    ).enhance(0.58)
    direct_ids = [
        str(item["occurrenceId"])
        for item in direct_occurrences
    ]
    direct_mask = _identity_selection_mask(identity_mask, color_legend, direct_ids)
    inherited_mask = _identity_selection_mask(
        identity_mask,
        color_legend,
        inherited_ids,
    )
    direct_tint = Image.blend(
        base,
        Image.new("RGB", base.size, _DIRECT_COLOR),
        0.34,
    )
    inherited_tint = Image.blend(
        base,
        Image.new("RGB", base.size, _INHERITED_COLOR),
        0.24,
    )
    dim.paste(inherited_tint, mask=inherited_mask)
    dim.paste(direct_tint, mask=direct_mask)
    dim.paste(
        Image.new("RGB", base.size, _INHERITED_COLOR),
        mask=_outline(inherited_mask),
    )
    dim.paste(
        Image.new("RGB", base.size, _DIRECT_COLOR),
        mask=_outline(direct_mask),
    )
    height = max(1, round(dim.height * (width / dim.width)))
    rendered = dim.resize((width, height), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(rendered)
    scale_x = width / dim.width
    scale_y = height / dim.height
    for index, occurrence in enumerate(direct_occurrences, start=1):
        occurrence_id = str(occurrence["occurrenceId"])
        bbox = occurrence_bboxes.get(occurrence_id)
        if bbox is None:
            continue
        left = round(bbox[0] * scale_x)
        top = round(bbox[1] * scale_y)
        right = round((bbox[2] + 1) * scale_x)
        bottom = round((bbox[3] + 1) * scale_y)
        center_x = (left + right) // 2
        center_y = (top + bottom) // 2
        half_width = max(9, (right - left) // 2 + 4)
        half_height = max(9, (bottom - top) // 2 + 4)
        box = (
            max(1, center_x - half_width),
            max(1, center_y - half_height),
            min(width - 2, center_x + half_width),
            min(height - 2, center_y + half_height),
        )
        draw.rectangle(box, outline=_DIRECT_COLOR, width=2)
        label_box = (
            box[0],
            max(0, box[1] - 16),
            min(width - 1, box[0] + 18),
            box[1],
        )
        draw.rectangle(label_box, fill=_DIRECT_COLOR)
        draw.text(
            (label_box[0] + 5, label_box[1] + 1),
            str(index),
            fill=(20, 28, 36),
            font=_font(11, bold=True),
        )
    return rendered


def render_process_map_visual_review(
    semantic_plan: Mapping[str, Any],
    assembly_knowledge: Mapping[str, Any],
    *,
    package_dir: str | Path,
    artifact_root: str | Path,
    provider_name: str,
    model: str,
) -> Dict[str, Any]:
    context = build_process_map_visual_review_context(
        semantic_plan,
        assembly_knowledge,
    )
    resolved_views = _verified_view_paths(context, package_dir)
    plan_hash = canonical_json_sha256(semantic_plan)
    fingerprint = canonical_json_sha256(
        {
            "model": model,
            "packageBinding": context["packageBinding"],
            "planHash": plan_hash,
            "promptVersion": PROCESS_MAP_VISUAL_VALIDATION_PROMPT_VERSION,
            "provider": provider_name,
            "version": PROCESS_MAP_VISUAL_VALIDATION_VERSION,
            "views": [
                {
                    "assetHash": item["assetHash"],
                    "maskAssetHash": item["maskAssetHash"],
                    "viewId": item.get("viewId"),
                }
                for item in resolved_views
            ],
        }
    )
    root = _safe_artifact_root(artifact_root)
    artifact_path = root / f"{fingerprint}.png"
    cache_path = root / f"{fingerprint}.json"

    if not artifact_path.is_file():
        tile_width = 330
        tile_gap = 10
        page_margin = 18
        title_height = 55
        row_header = 58
        row_gap = 12
        opened_views: list[
            tuple[
                Dict[str, Any],
                Image.Image,
                Image.Image,
                Dict[str, tuple[int, int, int, int]],
            ]
        ] = []
        try:
            for item in resolved_views:
                presentation = Image.open(item["presentationPath"]).convert("RGB")
                identity = Image.open(item["maskPath"]).convert("RGB")
                if presentation.size != identity.size:
                    raise ProcessMapVisualValidationError(
                        "visual_review_view_size_mismatch",
                        "Presentation and identity-mask dimensions differ.",
                    )
                opened_views.append(
                    (
                        item,
                        presentation,
                        identity,
                        _occurrence_bboxes(
                            identity,
                            item.get("colorLegend") or {},
                        ),
                    )
                )
            tile_height = max(
                1,
                round(opened_views[0][1].height * (tile_width / opened_views[0][1].width)),
            )
            width = (
                page_margin * 2
                + len(opened_views) * tile_width
                + max(0, len(opened_views) - 1) * tile_gap
            )
            row_height = row_header + tile_height
            height = (
                title_height
                + page_margin
                + len(context["operations"]) * row_height
                + max(0, len(context["operations"]) - 1) * row_gap
                + page_margin
            )
            sheet = Image.new("RGB", (width, height), _BACKGROUND)
            draw = ImageDraw.Draw(sheet)
            draw.text(
                (page_margin, 12),
                "Process-map visual validation",
                fill=_TEXT,
                font=_font(20, bold=True),
            )
            legend_x = width - 375
            for color, label in (
                (_DIRECT_COLOR, "new inputs"),
                (_INHERITED_COLOR, "inherited"),
                ((150, 156, 164), "not yet assembled"),
            ):
                draw.rectangle(
                    (legend_x, 18, legend_x + 14, 32),
                    fill=color,
                )
                draw.text(
                    (legend_x + 20, 16),
                    label,
                    fill=_MUTED_TEXT,
                    font=_font(13),
                )
                legend_x += 120
            y = title_height
            for index, operation in enumerate(context["operations"], start=1):
                direct_ids = [
                    item["occurrenceId"]
                    for item in operation["directOccurrences"]
                ]
                inherited_ids = [
                    item["occurrenceId"]
                    for item in operation["inheritedOccurrences"]
                ]
                title = (
                    f"{index:02d}  S{operation['stageIndex']}  "
                    f"{operation['label']}  |  new {len(direct_ids)}  "
                    f"|  cumulative {len(operation['cumulativeOccurrenceIds'])}"
                )
                draw.text(
                    (page_margin, y + 5),
                    title[:170],
                    fill=_TEXT,
                    font=_font(15, bold=True),
                )
                direct_names = "; ".join(
                    f"{direct_index}. {item['name']}"
                    for direct_index, item in enumerate(
                        operation["directOccurrences"],
                        start=1,
                    )
                ) or "No new direct occurrences"
                draw.text(
                    (page_margin, y + 26),
                    direct_names[:210],
                    fill=_MUTED_TEXT,
                    font=_font(13),
                )
                tile_y = y + row_header
                for view_index, (
                    view,
                    presentation,
                    identity,
                    occurrence_bboxes,
                ) in enumerate(
                    opened_views
                ):
                    tile = _render_stage_view(
                        presentation,
                        identity,
                        view.get("colorLegend") or {},
                        direct_occurrences=operation["directOccurrences"],
                        inherited_ids=inherited_ids,
                        occurrence_bboxes=occurrence_bboxes,
                        width=tile_width,
                    )
                    x = page_margin + view_index * (tile_width + tile_gap)
                    sheet.paste(tile, (x, tile_y))
                    named_view = str(
                        (view.get("camera") or {}).get("namedView")
                        or view.get("viewId")
                        or "view"
                    )
                    draw.rectangle(
                        (x + 5, tile_y + 5, x + 92, tile_y + 26),
                        fill=(250, 252, 254),
                    )
                    draw.text(
                        (x + 10, tile_y + 7),
                        named_view[:12],
                        fill=_TEXT,
                        font=_font(12, bold=True),
                    )
                y += row_height + row_gap
            temporary = artifact_path.with_suffix(".tmp.png")
            sheet.save(temporary, format="PNG", optimize=True)
            os.replace(temporary, artifact_path)
        finally:
            for _, presentation, identity, _ in opened_views:
                presentation.close()
                identity.close()

    with Image.open(artifact_path) as image:
        dimensions = image.size
    return {
        "context": context,
        "fingerprint": fingerprint,
        "planHash": plan_hash,
        "artifact": {
            "artifactId": fingerprint,
            "absolutePath": str(artifact_path),
            "assetHash": _sha256_file(artifact_path),
            "width": dimensions[0],
            "height": dimensions[1],
        },
        "cachePath": str(cache_path),
    }


def process_map_visual_review_output_schema() -> Dict[str, Any]:
    finding = {
        "type": "object",
        "additionalProperties": False,
        "required": ["code", "message", "occurrenceIds"],
        "properties": {
            "code": {"type": "string", "minLength": 1, "maxLength": 80},
            "message": {"type": "string", "minLength": 1, "maxLength": 500},
            "occurrenceIds": {
                "type": "array",
                "maxItems": 40,
                "items": {"type": "string", "minLength": 1, "maxLength": 160},
            },
        },
    }
    move = {
        "type": "object",
        "additionalProperties": False,
        "required": ["occurrenceId", "toOperationId", "reason"],
        "properties": {
            "occurrenceId": {"type": "string", "minLength": 1, "maxLength": 160},
            "toOperationId": {"type": "string", "minLength": 1, "maxLength": 160},
            "reason": {"type": "string", "minLength": 1, "maxLength": 500},
        },
    }
    review = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "operationId",
            "verdict",
            "confidence",
            "findings",
            "proposedLabel",
            "moveOccurrences",
        ],
        "properties": {
            "operationId": {"type": "string", "minLength": 1, "maxLength": 160},
            "verdict": {
                "type": "string",
                "enum": ["coherent", "needs_correction", "needs_review"],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "findings": {"type": "array", "maxItems": 12, "items": finding},
            "proposedLabel": {"type": ["string", "null"], "maxLength": 120},
            "moveOccurrences": {"type": "array", "maxItems": 20, "items": move},
        },
    }
    unresolved = {
        "type": "object",
        "additionalProperties": False,
        "required": ["message", "operationIds", "occurrenceIds"],
        "properties": {
            "message": {"type": "string", "minLength": 1, "maxLength": 500},
            "operationIds": {
                "type": "array",
                "maxItems": 20,
                "items": {"type": "string", "minLength": 1, "maxLength": 160},
            },
            "occurrenceIds": {
                "type": "array",
                "maxItems": 40,
                "items": {"type": "string", "minLength": 1, "maxLength": 160},
            },
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schemaVersion",
            "overallVerdict",
            "operationReviews",
            "unresolvedItems",
        ],
        "properties": {
            "schemaVersion": {
                "type": "integer",
                "enum": [PROCESS_MAP_VISUAL_VALIDATION_VERSION],
            },
            "overallVerdict": {
                "type": "string",
                "enum": ["coherent", "corrected", "needs_review"],
            },
            "operationReviews": {
                "type": "array",
                "minItems": 1,
                "maxItems": 50,
                "items": review,
            },
            "unresolvedItems": {
                "type": "array",
                "maxItems": 40,
                "items": unresolved,
            },
        },
    }


def _provider_payload(
    rendered: Mapping[str, Any],
) -> Dict[str, Any]:
    context = rendered["context"]
    user_payload = {
        "task": "Review operation labels and direct occurrence membership.",
        "scope": context["scope"],
        "packageBinding": context["packageBinding"],
        "operationColorKey": {
            "orange": "direct occurrence inputs for this operation",
            "cyan": "occurrences inherited from predecessors",
            "gray": "not in this operation's cumulative assembly state",
        },
        "requiredChecks": [
            "Account for every numbered orange occurrence in the stage label.",
            "Flag any orange occurrence isolated in a different product region.",
            "Use needs_review when the views do not support a confident correction.",
            "Do not infer manufacturing order from the visual arrangement.",
        ],
        "operations": context["operations"],
    }
    artifact = rendered["artifact"]
    return {
        "systemPrompt": _SYSTEM_PROMPT,
        "userText": json.dumps(
            user_payload,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        "images": [
            {
                "absolutePath": artifact["absolutePath"],
                "assetHash": artifact["assetHash"],
                "width": artifact["width"],
                "height": artifact["height"],
                "kind": "process_map_stage_contact_sheet",
            }
        ],
        "outputSchema": process_map_visual_review_output_schema(),
        "maximumOutputTokens": 8_000,
        "cacheKey": rendered["fingerprint"],
    }


def validate_process_map_visual_review(
    output: Any,
    visual_context: Mapping[str, Any],
) -> Dict[str, Any]:
    if not isinstance(output, Mapping):
        raise ProcessMapVisualValidationError(
            "visual_review_output_invalid",
            "The visual reviewer returned no structured object.",
        )
    if output.get("schemaVersion") != PROCESS_MAP_VISUAL_VALIDATION_VERSION:
        raise ProcessMapVisualValidationError(
            "visual_review_version_invalid",
            "The visual-review schema version is invalid.",
        )
    if output.get("overallVerdict") not in {
        "coherent",
        "corrected",
        "needs_review",
    }:
        raise ProcessMapVisualValidationError(
            "visual_review_verdict_invalid",
            "The visual-review verdict is invalid.",
        )
    operation_contexts = {
        str(item["operationId"]): item
        for item in visual_context.get("operations", [])
        if isinstance(item, Mapping) and isinstance(item.get("operationId"), str)
    }
    known_occurrences = {
        str(occurrence["occurrenceId"])
        for operation in operation_contexts.values()
        for field in ("directOccurrences", "inheritedOccurrences")
        for occurrence in operation.get(field, [])
        if isinstance(occurrence, Mapping)
        and isinstance(occurrence.get("occurrenceId"), str)
    }
    raw_reviews = output.get("operationReviews")
    if not isinstance(raw_reviews, list):
        raise ProcessMapVisualValidationError(
            "visual_review_operations_invalid",
            "operationReviews must be an array.",
        )
    reviews: list[Dict[str, Any]] = []
    seen_operations: set[str] = set()
    moved_occurrences: set[str] = set()
    for raw in raw_reviews:
        if not isinstance(raw, Mapping):
            raise ProcessMapVisualValidationError(
                "visual_review_operation_invalid",
                "Every operation review must be an object.",
            )
        operation_id = str(raw.get("operationId") or "")
        if (
            operation_id not in operation_contexts
            or operation_id in seen_operations
        ):
            raise ProcessMapVisualValidationError(
                "visual_review_operation_unknown",
                f"Unknown or duplicate reviewed operation: {operation_id}",
            )
        seen_operations.add(operation_id)
        verdict = raw.get("verdict")
        confidence = raw.get("confidence")
        if verdict not in {"coherent", "needs_correction", "needs_review"}:
            raise ProcessMapVisualValidationError(
                "visual_review_operation_verdict_invalid",
                f"Invalid verdict for operation '{operation_id}'.",
            )
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= float(confidence) <= 1
        ):
            raise ProcessMapVisualValidationError(
                "visual_review_confidence_invalid",
                f"Invalid confidence for operation '{operation_id}'.",
            )
        proposed_label = raw.get("proposedLabel")
        if proposed_label is not None:
            if (
                not isinstance(proposed_label, str)
                or not proposed_label.strip()
                or len(proposed_label.strip()) > 120
            ):
                raise ProcessMapVisualValidationError(
                    "visual_review_label_invalid",
                    f"Invalid proposed label for operation '{operation_id}'.",
                )
            proposed_label = proposed_label.strip()
        findings = []
        for finding in raw.get("findings", []):
            if not isinstance(finding, Mapping):
                raise ProcessMapVisualValidationError(
                    "visual_review_finding_invalid",
                    "Visual-review findings must be objects.",
                )
            occurrence_ids = [
                str(item) for item in finding.get("occurrenceIds", [])
            ]
            if any(item not in known_occurrences for item in occurrence_ids):
                raise ProcessMapVisualValidationError(
                    "visual_review_occurrence_unknown",
                    "A visual finding references an unknown occurrence.",
                )
            code = str(finding.get("code") or "").strip()
            message = str(finding.get("message") or "").strip()
            if not code or not message:
                raise ProcessMapVisualValidationError(
                    "visual_review_finding_invalid",
                    "Visual-review finding code and message are required.",
                )
            findings.append(
                {
                    "code": code[:80],
                    "message": message[:500],
                    "occurrenceIds": sorted(set(occurrence_ids)),
                }
            )
        direct_ids = {
            str(item["occurrenceId"])
            for item in operation_contexts[operation_id]["directOccurrences"]
        }
        moves = []
        for move in raw.get("moveOccurrences", []):
            if not isinstance(move, Mapping):
                raise ProcessMapVisualValidationError(
                    "visual_review_move_invalid",
                    "Occurrence moves must be objects.",
                )
            occurrence_id = str(move.get("occurrenceId") or "")
            target_id = str(move.get("toOperationId") or "")
            reason = str(move.get("reason") or "").strip()
            if (
                occurrence_id not in direct_ids
                or occurrence_id in moved_occurrences
                or target_id not in operation_contexts
                or target_id == operation_id
                or not reason
            ):
                raise ProcessMapVisualValidationError(
                    "visual_review_move_invalid",
                    f"Invalid occurrence move from operation '{operation_id}'.",
                )
            moved_occurrences.add(occurrence_id)
            moves.append(
                {
                    "occurrenceId": occurrence_id,
                    "toOperationId": target_id,
                    "reason": reason[:500],
                }
            )
        reviews.append(
            {
                "operationId": operation_id,
                "verdict": verdict,
                "confidence": round(float(confidence), 4),
                "findings": findings,
                "proposedLabel": proposed_label,
                "moveOccurrences": moves,
            }
        )
    if seen_operations != set(operation_contexts):
        missing = sorted(set(operation_contexts) - seen_operations)
        raise ProcessMapVisualValidationError(
            "visual_review_operations_incomplete",
            "The visual review omitted operations: " + ", ".join(missing),
        )
    unresolved_items = []
    raw_unresolved = output.get("unresolvedItems")
    if not isinstance(raw_unresolved, list):
        raise ProcessMapVisualValidationError(
            "visual_review_unresolved_invalid",
            "unresolvedItems must be an array.",
        )
    for raw in raw_unresolved:
        if not isinstance(raw, Mapping):
            raise ProcessMapVisualValidationError(
                "visual_review_unresolved_invalid",
                "Every unresolved visual item must be an object.",
            )
        operation_ids = sorted(
            set(str(item) for item in raw.get("operationIds", []))
        )
        occurrence_ids = sorted(
            set(str(item) for item in raw.get("occurrenceIds", []))
        )
        message = str(raw.get("message") or "").strip()
        if (
            not message
            or any(item not in operation_contexts for item in operation_ids)
            or any(item not in known_occurrences for item in occurrence_ids)
        ):
            raise ProcessMapVisualValidationError(
                "visual_review_unresolved_invalid",
                "An unresolved visual item contains invalid references.",
            )
        unresolved_items.append(
            {
                "message": message[:500],
                "operationIds": operation_ids,
                "occurrenceIds": occurrence_ids,
            }
        )
    return {
        "schemaVersion": PROCESS_MAP_VISUAL_VALIDATION_VERSION,
        "overallVerdict": output["overallVerdict"],
        "operationReviews": sorted(
            reviews,
            key=lambda item: item["operationId"],
        ),
        "unresolvedItems": unresolved_items,
    }


def apply_process_map_visual_corrections(
    semantic_plan: Mapping[str, Any],
    visual_review: Mapping[str, Any],
    *,
    minimum_confidence: float = PROCESS_MAP_VISUAL_VALIDATION_MIN_CONFIDENCE,
) -> Dict[str, Any]:
    corrected = copy.deepcopy(dict(semantic_plan))
    operations = {
        str(item["id"]): item
        for item in corrected.get("operations", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    applied: list[Dict[str, Any]] = []
    deferred: list[Dict[str, Any]] = []
    for review in visual_review.get("operationReviews", []):
        operation_id = str(review["operationId"])
        confidence = float(review["confidence"])
        eligible = (
            review.get("verdict") == "needs_correction"
            and confidence >= minimum_confidence
        )
        if not eligible:
            if review.get("verdict") != "coherent":
                deferred.append(copy.deepcopy(dict(review)))
            continue
        operation = operations[operation_id]
        proposed_label = review.get("proposedLabel")
        if (
            isinstance(proposed_label, str)
            and proposed_label != operation.get("label")
        ):
            previous = str(operation.get("label") or "")
            operation["label"] = proposed_label
            applied.append(
                {
                    "kind": "rename_operation",
                    "operationId": operation_id,
                    "before": previous,
                    "after": proposed_label,
                    "confidence": confidence,
                }
            )
        for move in review.get("moveOccurrences", []):
            occurrence_id = str(move["occurrenceId"])
            target_id = str(move["toOperationId"])
            source_inputs = operation.get("inputs", [])
            source_index = next(
                (
                    index
                    for index, input_item in enumerate(source_inputs)
                    if isinstance(input_item, Mapping)
                    and input_item.get("type") == "occurrence"
                    and input_item.get("ref") == occurrence_id
                ),
                None,
            )
            if source_index is None or target_id not in operations:
                deferred.append(
                    {
                        "operationId": operation_id,
                        "verdict": "needs_review",
                        "confidence": confidence,
                        "findings": [
                            {
                                "code": "visual_correction_target_stale",
                                "message": (
                                    "The proposed occurrence move no longer "
                                    "matches the semantic plan."
                                ),
                                "occurrenceIds": [occurrence_id],
                            }
                        ],
                        "proposedLabel": None,
                        "moveOccurrences": [],
                    }
                )
                continue
            moved_input = source_inputs.pop(source_index)
            target_inputs = operations[target_id].setdefault("inputs", [])
            target_inputs.append(moved_input)
            target_inputs.sort(
                key=lambda item: (
                    str(item.get("type") or "")
                    if isinstance(item, Mapping)
                    else "",
                    str(item.get("ref") or "")
                    if isinstance(item, Mapping)
                    else "",
                )
            )
            applied.append(
                {
                    "kind": "move_occurrence",
                    "occurrenceId": occurrence_id,
                    "fromOperationId": operation_id,
                    "toOperationId": target_id,
                    "reason": str(move.get("reason") or ""),
                    "confidence": confidence,
                }
            )
    return {
        "plan": corrected,
        "appliedCorrections": applied,
        "deferredReviews": deferred,
    }


def review_semantic_process_plan_visuals(
    semantic_plan: Mapping[str, Any],
    assembly_knowledge: Mapping[str, Any],
    *,
    package_dir: str | Path,
    artifact_root: str | Path,
    provider: MultimodalEnrichmentProvider,
) -> Dict[str, Any]:
    rendered = render_process_map_visual_review(
        semantic_plan,
        assembly_knowledge,
        package_dir=package_dir,
        artifact_root=artifact_root,
        provider_name=provider.provider_name,
        model=provider.model,
    )
    cache_path = Path(rendered["cachePath"])
    from_cache = False
    usage: Dict[str, Any] = {}
    if cache_path.is_file():
        cached = json.loads(cache_path.read_text("ascii"))
        raw_output = cached.get("output")
        usage = copy.deepcopy(dict(cached.get("usage") or {}))
        from_cache = True
    else:
        result = provider.invoke(_provider_payload(rendered))
        raw_output = result.get("output")
        usage = copy.deepcopy(dict(result.get("usage") or {}))
    validated = validate_process_map_visual_review(
        raw_output,
        rendered["context"],
    )
    if not from_cache:
        payload = _stable_json_bytes(
            {
                "output": validated,
                "usage": usage,
            }
        )
        temporary = cache_path.with_suffix(".tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, cache_path)
    corrections = apply_process_map_visual_corrections(
        semantic_plan,
        validated,
    )
    applied = corrections["appliedCorrections"]
    deferred = corrections["deferredReviews"]
    unresolved = copy.deepcopy(validated["unresolvedItems"])
    unresolved.extend(
        {
            "message": (
                f"Visual review for {item['operationId']} requires user review "
                f"(confidence {float(item['confidence']):.2f})."
            ),
            "operationIds": [item["operationId"]],
            "occurrenceIds": sorted(
                {
                    occurrence_id
                    for finding in item.get("findings", [])
                    for occurrence_id in finding.get("occurrenceIds", [])
                }
            ),
        }
        for item in deferred
    )
    status = "corrected" if applied else "passed"
    if unresolved or any(
        item.get("verdict") == "needs_review"
        for item in validated["operationReviews"]
    ):
        status = "needs_review"
    reviewed_plan = corrections["plan"]
    reviewed_artifact = rendered["artifact"]
    if reviewed_plan != semantic_plan:
        reviewed_artifact = render_process_map_visual_review(
            reviewed_plan,
            assembly_knowledge,
            package_dir=package_dir,
            artifact_root=artifact_root,
            provider_name=provider.provider_name,
            model=provider.model,
        )["artifact"]
    report = {
        "schemaVersion": PROCESS_MAP_VISUAL_VALIDATION_VERSION,
        "status": status,
        "fingerprint": rendered["fingerprint"],
        "promptVersion": PROCESS_MAP_VISUAL_VALIDATION_PROMPT_VERSION,
        "provider": provider.provider_name,
        "model": provider.model,
        "fromCache": from_cache,
        "usage": usage,
        "originalPlanHash": rendered["planHash"],
        "reviewedPlanHash": canonical_json_sha256(reviewed_plan),
        "overallVerdict": validated["overallVerdict"],
        "operationReviews": validated["operationReviews"],
        "appliedCorrections": applied,
        "unresolvedItems": unresolved,
        "originalArtifact": rendered["artifact"],
        "artifact": reviewed_artifact,
    }
    return {
        "plan": reviewed_plan,
        "report": report,
    }


def public_process_map_visual_validation_report(
    report: Mapping[str, Any],
    *,
    artifact_url: str | None = None,
) -> Dict[str, Any]:
    artifact = report.get("artifact")
    applied = [
        item
        for item in report.get("appliedCorrections", [])
        if isinstance(item, Mapping)
    ]
    findings = [
        {
            "operationId": review.get("operationId"),
            "verdict": review.get("verdict"),
            "confidence": review.get("confidence"),
            "findings": copy.deepcopy(review.get("findings") or []),
        }
        for review in report.get("operationReviews", [])
        if isinstance(review, Mapping) and review.get("verdict") != "coherent"
    ]
    return {
        "schemaVersion": report.get("schemaVersion"),
        "status": report.get("status"),
        "fingerprint": report.get("fingerprint"),
        "promptVersion": report.get("promptVersion"),
        "provider": report.get("provider"),
        "model": report.get("model"),
        "fromCache": bool(report.get("fromCache")),
        "originalPlanHash": report.get("originalPlanHash"),
        "reviewedPlanHash": report.get("reviewedPlanHash"),
        "overallVerdict": report.get("overallVerdict"),
        "correctionCount": len(applied),
        "labelCorrectionCount": sum(
            1 for item in applied if item.get("kind") == "rename_operation"
        ),
        "membershipCorrectionCount": sum(
            1 for item in applied if item.get("kind") == "move_occurrence"
        ),
        "appliedCorrections": copy.deepcopy(applied),
        "findings": findings,
        "unresolvedItems": copy.deepcopy(report.get("unresolvedItems") or []),
        "artifact": (
            {
                "artifactId": artifact.get("artifactId"),
                "assetHash": artifact.get("assetHash"),
                "width": artifact.get("width"),
                "height": artifact.get("height"),
                "url": artifact_url,
            }
            if isinstance(artifact, Mapping)
            else None
        ),
    }
