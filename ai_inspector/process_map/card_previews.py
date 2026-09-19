"""Deterministic occurrence previews for Process Map cards.

The renderer consumes only hash-verified Assembly Knowledge presentation and
identity-mask assets. It never calls a model and never mutates process-map data.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from PIL import Image, ImageChops, ImageEnhance, ImageFilter

from ai_inspector.assembly_knowledge.manifest import canonical_json_sha256

from .visual_validation import (
    ProcessMapVisualValidationError,
    _DIRECT_COLOR,
    _INHERITED_COLOR,
    _rgb,
    _safe_artifact_root,
    _sha256_file,
    _verified_view_paths,
)


PROCESS_MAP_CARD_PREVIEW_VERSION = 2
PROCESS_MAP_CARD_PREVIEW_WIDTH = 420
PROCESS_MAP_CARD_PREVIEW_HEIGHT = 112
PROCESS_MAP_CARD_PREVIEW_LIMIT = 96
PROCESS_MAP_CARD_PREVIEW_OCCURRENCE_LIMIT = 128


def _normalize_ids(values: Any) -> list[str]:
    if not isinstance(values, list):
        raise ProcessMapVisualValidationError(
            "card_preview_occurrences_invalid",
            "Card preview occurrence IDs must be an array.",
        )
    result = sorted(
        {
            str(value).strip()
            for value in values
            if isinstance(value, str) and str(value).strip()
        }
    )
    if len(result) > PROCESS_MAP_CARD_PREVIEW_OCCURRENCE_LIMIT:
        raise ProcessMapVisualValidationError(
            "card_preview_occurrences_exceeded",
            "A card preview references too many occurrences.",
        )
    return result


def _normalize_descriptors(
    descriptors: Sequence[Mapping[str, Any]],
    known_occurrences: set[str],
) -> list[Dict[str, Any]]:
    if len(descriptors) > PROCESS_MAP_CARD_PREVIEW_LIMIT:
        raise ProcessMapVisualValidationError(
            "card_preview_limit_exceeded",
            "Too many card previews were requested.",
        )
    normalized: list[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for descriptor in descriptors:
        if not isinstance(descriptor, Mapping):
            raise ProcessMapVisualValidationError(
                "card_preview_descriptor_invalid",
                "Every card preview descriptor must be an object.",
            )
        preview_id = str(descriptor.get("previewId") or "").strip()
        kind = str(descriptor.get("kind") or "").strip()
        if (
            not preview_id
            or len(preview_id) > 160
            or preview_id in seen_ids
            or kind not in {"occurrence", "stage"}
        ):
            raise ProcessMapVisualValidationError(
                "card_preview_descriptor_invalid",
                "A card preview descriptor has an invalid ID or kind.",
            )
        occurrence_ids = _normalize_ids(descriptor.get("occurrenceIds"))
        direct_ids = _normalize_ids(descriptor.get("directOccurrenceIds") or [])
        if not occurrence_ids:
            continue
        unknown = (set(occurrence_ids) | set(direct_ids)) - known_occurrences
        if unknown:
            raise ProcessMapVisualValidationError(
                "card_preview_occurrence_unknown",
                "A card preview references an unknown product occurrence.",
            )
        if not set(direct_ids).issubset(occurrence_ids):
            raise ProcessMapVisualValidationError(
                "card_preview_direct_occurrence_invalid",
                "Direct stage occurrences must belong to the preview state.",
            )
        seen_ids.add(preview_id)
        normalized.append(
            {
                "previewId": preview_id,
                "kind": kind,
                "occurrenceIds": occurrence_ids,
                "directOccurrenceIds": direct_ids,
            }
        )
    return sorted(normalized, key=lambda item: item["previewId"])


def _selection_pixel_count(mask: Image.Image) -> int:
    histogram = mask.histogram()
    return int(histogram[255]) if len(histogram) > 255 else 0


def _exact_color_mask(
    image: Image.Image,
    color: tuple[int, int, int],
) -> Image.Image:
    difference = ImageChops.difference(
        image,
        Image.new("RGB", image.size, color),
    )
    red, green, blue = difference.split()
    maximum = ImageChops.lighter(red, ImageChops.lighter(green, blue))
    return maximum.point([255] + [0] * 255)


def _occurrence_masks(
    image: Image.Image,
    color_legend: Mapping[str, Any],
    requested_occurrences: set[str],
) -> Dict[str, Image.Image]:
    masks: Dict[str, Image.Image] = {}
    for color, occurrence_id in color_legend.items():
        normalized_id = str(occurrence_id)
        if normalized_id not in requested_occurrences:
            continue
        masks[normalized_id] = _exact_color_mask(image, _rgb(color))
    return masks


def _cached_selection_mask(
    view: Mapping[str, Any],
    occurrence_ids: Sequence[str],
) -> Image.Image:
    selected = [
        view["occurrenceMasks"][occurrence_id]
        for occurrence_id in occurrence_ids
        if occurrence_id in view["occurrenceMasks"]
    ]
    mask = Image.new("L", view["identity"].size, 0)
    for item in selected:
        combined = ImageChops.lighter(mask, item)
        mask.close()
        mask = combined
    return mask.filter(ImageFilter.MaxFilter(3))


def _best_view(
    opened_views: Sequence[Dict[str, Any]],
    occurrence_ids: Sequence[str],
) -> tuple[Dict[str, Any], Image.Image]:
    candidates: list[tuple[int, int, Dict[str, Any], Image.Image]] = []
    for index, item in enumerate(opened_views):
        selection = _cached_selection_mask(item, occurrence_ids)
        candidates.append(
            (
                _selection_pixel_count(selection),
                -index,
                item,
                selection,
            )
        )
    best = max(candidates, key=lambda item: item[:2]) if candidates else None
    if best is None or best[0] <= 0:
        raise ProcessMapVisualValidationError(
            "card_preview_occurrence_not_visible",
            "The requested occurrence is not visible in any prepared assembly view.",
        )
    isometric = next(
        (
            item
            for item in candidates
            if str(
                (item[2].get("camera") or {}).get("namedView") or ""
            ).lower() == "isometric"
        ),
        None,
    )
    chosen = (
        isometric
        if isometric is not None
        and isometric[0] >= max(8, round(best[0] * 0.15))
        else best
    )
    for candidate in candidates:
        if candidate is not chosen:
            candidate[3].close()
    return chosen[2], chosen[3]


def _padded_box(
    mask: Image.Image,
    *,
    padding_ratio: float = 0.12,
) -> tuple[int, int, int, int]:
    box = mask.getbbox()
    if box is None:
        raise ProcessMapVisualValidationError(
            "card_preview_occurrence_not_visible",
            "The requested occurrence has no visible identity-mask pixels.",
        )
    width = max(1, box[2] - box[0])
    height = max(1, box[3] - box[1])
    padding = max(6, round(max(width, height) * padding_ratio))
    return (
        max(0, box[0] - padding),
        max(0, box[1] - padding),
        min(mask.width, box[2] + padding),
        min(mask.height, box[3] + padding),
    )


def _tinted_selection(
    presentation: Image.Image,
    mask: Image.Image,
    color: tuple[int, int, int],
    strength: float,
) -> Image.Image:
    base = presentation.convert("RGB")
    tinted = Image.blend(
        base,
        Image.new("RGB", base.size, color),
        strength,
    )
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    layer.paste(tinted.convert("RGBA"), mask=mask)
    outline = ImageChops.subtract(
        mask.filter(ImageFilter.MaxFilter(5)),
        mask,
    )
    layer.paste(Image.new("RGBA", base.size, (*color, 255)), mask=outline)
    return layer


def _render_descriptor(
    descriptor: Mapping[str, Any],
    view: Mapping[str, Any],
    selection_mask: Image.Image,
) -> Image.Image:
    presentation = view["presentation"]
    if descriptor["kind"] == "stage":
        direct_ids = descriptor["directOccurrenceIds"]
        inherited_ids = sorted(
            set(descriptor["occurrenceIds"]) - set(direct_ids)
        )
        direct_mask = _cached_selection_mask(view, direct_ids)
        inherited_mask = _cached_selection_mask(view, inherited_ids)
        rendered = Image.new("RGBA", presentation.size, (0, 0, 0, 0))
        try:
            if inherited_ids:
                rendered.alpha_composite(
                    _tinted_selection(
                        presentation,
                        inherited_mask,
                        _INHERITED_COLOR,
                        0.28,
                    )
                )
            if direct_ids:
                rendered.alpha_composite(
                    _tinted_selection(
                        presentation,
                        direct_mask,
                        _DIRECT_COLOR,
                        0.38,
                    )
                )
        finally:
            direct_mask.close()
            inherited_mask.close()
    else:
        base = ImageEnhance.Contrast(
            presentation.convert("RGB")
        ).enhance(1.04)
        rendered = Image.new("RGBA", presentation.size, (0, 0, 0, 0))
        rendered.paste(base.convert("RGBA"), mask=selection_mask)
        outline = ImageChops.subtract(
            selection_mask.filter(ImageFilter.MaxFilter(5)),
            selection_mask,
        )
        rendered.paste(
            Image.new("RGBA", presentation.size, (*_INHERITED_COLOR, 255)),
            mask=outline,
        )

    cropped = rendered.crop(_padded_box(selection_mask))
    cropped.thumbnail(
        (PROCESS_MAP_CARD_PREVIEW_WIDTH - 12, PROCESS_MAP_CARD_PREVIEW_HEIGHT - 8),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new(
        "RGBA",
        (PROCESS_MAP_CARD_PREVIEW_WIDTH, PROCESS_MAP_CARD_PREVIEW_HEIGHT),
        (0, 0, 0, 0),
    )
    canvas.alpha_composite(
        cropped,
        (
            (canvas.width - cropped.width) // 2,
            (canvas.height - cropped.height) // 2,
        ),
    )
    return canvas


def render_process_map_card_previews(
    assembly_knowledge: Mapping[str, Any],
    descriptors: Sequence[Mapping[str, Any]],
    *,
    package_dir: str | Path,
    artifact_root: str | Path,
) -> Dict[str, Any]:
    """Render a bounded batch of stable occurrence/stage card images."""

    documents = assembly_knowledge.get("documents")
    binding = assembly_knowledge.get("binding")
    if not isinstance(documents, Mapping) or not isinstance(binding, Mapping):
        raise ProcessMapVisualValidationError(
            "card_preview_package_missing",
            "A resolved Assembly Knowledge Package is required.",
        )
    structure = documents.get("product_structure.json")
    visual = documents.get("visual_manifest.json")
    package = documents.get("package.json")
    if not all(isinstance(item, Mapping) for item in (structure, visual, package)):
        raise ProcessMapVisualValidationError(
            "card_preview_package_incomplete",
            "The Assembly Knowledge Package lacks structure or visual evidence.",
        )
    known_occurrences = {
        str(item.get("occurrenceId"))
        for item in structure.get("occurrences", [])
        if isinstance(item, Mapping) and item.get("occurrenceId")
    }
    normalized = _normalize_descriptors(descriptors, known_occurrences)
    requested_occurrences = {
        occurrence_id
        for descriptor in normalized
        for occurrence_id in descriptor["occurrenceIds"]
    }
    context = {
        "views": [
            dict(item)
            for item in visual.get("views", [])
            if isinstance(item, Mapping)
            and item.get("kind") == "presentation"
            and isinstance(item.get("assetPath"), str)
            and isinstance(item.get("maskAssetPath"), str)
        ],
        "assetHashes": dict(package.get("assetHashes") or {}),
    }
    if not context["views"]:
        raise ProcessMapVisualValidationError(
            "card_preview_views_missing",
            "No paired presentation and identity-mask views are available.",
        )
    resolved_views = _verified_view_paths(context, package_dir)
    opened_views: list[Dict[str, Any]] = []
    try:
        for item in resolved_views:
            presentation = Image.open(item["presentationPath"]).convert("RGB")
            identity = Image.open(item["maskPath"]).convert("RGB")
            if presentation.size != identity.size:
                raise ProcessMapVisualValidationError(
                    "card_preview_view_size_mismatch",
                    "Presentation and identity-mask dimensions differ.",
                )
            opened_views.append(
                {
                    **item,
                    "presentation": presentation,
                    "identity": identity,
                    "colorLegend": dict(item.get("colorLegend") or {}),
                    "occurrenceMasks": _occurrence_masks(
                        identity,
                        dict(item.get("colorLegend") or {}),
                        requested_occurrences,
                    ),
                }
            )

        root = _safe_artifact_root(artifact_root)
        rendered_previews = []
        warnings = []
        for descriptor in normalized:
            try:
                view, selection_mask = _best_view(
                    opened_views,
                    descriptor["occurrenceIds"],
                )
                fingerprint = canonical_json_sha256(
                    {
                        "descriptor": descriptor,
                        "packageRevision": binding.get("packageRevision"),
                        "presentationHash": view.get("assetHash"),
                        "identityMaskHash": view.get("maskAssetHash"),
                        "version": PROCESS_MAP_CARD_PREVIEW_VERSION,
                    }
                )
                target = root / f"{fingerprint}.png"
                if not target.is_file():
                    image = None
                    try:
                        image = _render_descriptor(
                            descriptor,
                            view,
                            selection_mask,
                        )
                        temporary = target.with_suffix(".tmp")
                        image.save(temporary, format="PNG", optimize=True)
                        os.replace(temporary, target)
                    finally:
                        if image is not None:
                            image.close()
                selection_mask.close()
                rendered_previews.append(
                    {
                        **descriptor,
                        "artifactId": fingerprint,
                        "assetHash": _sha256_file(target),
                        "width": PROCESS_MAP_CARD_PREVIEW_WIDTH,
                        "height": PROCESS_MAP_CARD_PREVIEW_HEIGHT,
                        "viewName": str(
                            (view.get("camera") or {}).get("namedView") or ""
                        ),
                    }
                )
            except ProcessMapVisualValidationError as exc:
                if exc.code != "card_preview_occurrence_not_visible":
                    raise
                warnings.append(
                    {
                        "previewId": descriptor["previewId"],
                        "code": exc.code,
                        "message": str(exc),
                    }
                )
        return {
            "schemaVersion": PROCESS_MAP_CARD_PREVIEW_VERSION,
            "packageId": binding.get("packageId"),
            "packageRevision": binding.get("packageRevision"),
            "previews": rendered_previews,
            "warnings": warnings,
        }
    finally:
        for item in opened_views:
            item["presentation"].close()
            item["identity"].close()
            for mask in item["occurrenceMasks"].values():
                mask.close()


def resolve_process_map_card_preview_artifact(
    artifact_root: str | Path,
    artifact_id: str,
) -> Path:
    if (
        not isinstance(artifact_id, str)
        or len(artifact_id) != 64
        or any(char not in "0123456789abcdef" for char in artifact_id)
    ):
        raise ProcessMapVisualValidationError(
            "card_preview_artifact_invalid",
            "The card-preview artifact ID is invalid.",
        )
    root = Path(artifact_root).resolve()
    target = (root / f"{artifact_id}.png").resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ProcessMapVisualValidationError(
            "card_preview_artifact_invalid",
            "The card-preview artifact path is invalid.",
        ) from exc
    if not target.is_file():
        raise ProcessMapVisualValidationError(
            "card_preview_artifact_not_found",
            "The card-preview artifact is unavailable.",
        )
    return target
