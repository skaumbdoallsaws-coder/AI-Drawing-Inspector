"""Deterministic visual evidence ingestion and identity-mask validation."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageOps

from .identity import finding_id
from .manifest import refresh_package_revision


VIEW_NAMES = ("front", "top", "right", "isometric")
MASK_MATCH_TOLERANCE = 72
MIN_OCCURRENCE_PIXELS = 8


class VisualEvidenceError(ValueError):
    pass


def occurrence_alias_map(product_structure: Mapping[str, Any]) -> Dict[str, str]:
    root_id = product_structure.get("rootOccurrenceId")
    result: Dict[str, str] = {}
    for occurrence in product_structure.get("occurrences", []):
        if not isinstance(occurrence, dict) or occurrence.get("occurrenceId") == root_id:
            continue
        alias = str(occurrence.get("name") or "").strip()
        occurrence_id = str(occurrence.get("occurrenceId") or "").strip()
        if not alias or not occurrence_id:
            raise VisualEvidenceError("Every component occurrence requires alias and ID.")
        if alias in result:
            raise VisualEvidenceError(f"Duplicate component alias: {alias}")
        result[alias] = occurrence_id
    return dict(sorted(result.items()))


def write_occurrence_map_tsv(
    product_structure: Mapping[str, Any],
    path: str | Path,
) -> Path:
    aliases = occurrence_alias_map(product_structure)
    lines = ["# componentAlias\toccurrenceId"]
    for alias, occurrence_id in aliases.items():
        if any(character in alias + occurrence_id for character in "\t\r\n"):
            raise VisualEvidenceError("Occurrence map values may not contain tabs/newlines.")
        lines.append(f"{alias}\t{occurrence_id}")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    return output


def read_occurrence_legend(path: str | Path) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    seen_colors = set()
    seen_aliases = set()
    for line in Path(path).read_text("ascii").splitlines():
        if not line or line.startswith("# "):
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            raise VisualEvidenceError("Mask legend rows require color, alias, and ID.")
        color, alias, occurrence_id = fields
        normalized_color = color.upper()
        if (
            len(normalized_color) != 7
            or not normalized_color.startswith("#")
            or any(character not in "0123456789ABCDEF" for character in normalized_color[1:])
        ):
            raise VisualEvidenceError(f"Invalid identity-mask color: {color}")
        if normalized_color in seen_colors:
            raise VisualEvidenceError(f"Duplicate identity-mask color: {color}")
        if alias in seen_aliases:
            raise VisualEvidenceError(f"Duplicate identity-mask alias: {alias}")
        seen_colors.add(normalized_color)
        seen_aliases.add(alias)
        entries.append(
            {
                "hexColor": normalized_color,
                "componentAlias": alias,
                "occurrenceId": occurrence_id,
            }
        )
    if not entries:
        raise VisualEvidenceError("Mask legend is empty.")
    return sorted(entries, key=lambda item: item["occurrenceId"])


def _real_png_bytes(path: Path) -> Tuple[bytes, Tuple[int, int], Image.Image]:
    try:
        with Image.open(path) as image:
            converted = image.convert("RGB")
    except (OSError, ValueError) as exc:
        raise VisualEvidenceError(f"Could not decode visual asset {path}: {exc}") from exc
    output = io.BytesIO()
    converted.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue(), converted.size, converted


def _rgb(hex_color: str) -> Tuple[int, int, int]:
    return tuple(int(hex_color[index : index + 2], 16) for index in (1, 3, 5))


def _pixel_distance(left: Tuple[int, int, int], right: Tuple[int, int, int]) -> int:
    return sum((int(left[index]) - int(right[index])) ** 2 for index in range(3))


def _visible_occurrences(
    image: Image.Image,
    entries: Sequence[Mapping[str, str]],
) -> Tuple[List[str], float, Mapping[str, int]]:
    expected = [(_rgb(item["hexColor"]), item["occurrenceId"]) for item in entries]
    tolerance_squared = MASK_MATCH_TOLERANCE**2
    counts = {occurrence_id: 0 for _, occurrence_id in expected}
    foreground = 0
    matched = 0
    # Sampling every second pixel bounds work while retaining thousands of
    # samples for standard SolidWorks captures.
    for y in range(0, image.height, 2):
        for x in range(0, image.width, 2):
            pixel = image.getpixel((x, y))
            if min(pixel) >= 245:
                continue
            foreground += 1
            distance, occurrence_id = min(
                (_pixel_distance(pixel, color), occurrence_id)
                for color, occurrence_id in expected
            )
            if distance <= tolerance_squared:
                counts[occurrence_id] += 1
                matched += 1
    visible = sorted(
        occurrence_id
        for occurrence_id, count in counts.items()
        if count >= MIN_OCCURRENCE_PIXELS
    )
    fidelity = matched / foreground if foreground else 0.0
    return visible, fidelity, counts


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    subject_refs: Iterable[str] = (),
    details: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    refs = sorted(set(str(item) for item in subject_refs if item))
    normalized_details = dict(details or {})
    result: Dict[str, Any] = {
        "findingId": finding_id(code, subject_refs=refs, details=normalized_details),
        "severity": severity,
        "code": code,
        "message": message,
    }
    if refs:
        result["subjectRefs"] = refs
    if normalized_details:
        result["details"] = normalized_details
    return result


def _content_bbox(image: Image.Image) -> Tuple[int, int, int, int]:
    background = Image.new("RGB", image.size, image.getpixel((0, 0)))
    difference = ImageChops.difference(image, background).convert("L")
    difference = difference.point(lambda value: 255 if value > 10 else 0)
    box = difference.getbbox()
    if box is None:
        return (0, 0, image.width, image.height)
    left, top, right, bottom = box
    padding = 24
    return (
        max(0, left - padding),
        max(0, top - padding),
        min(image.width, right + padding),
        min(image.height, bottom + padding),
    )


def build_contact_sheet(
    views: Sequence[Tuple[str, Image.Image]],
    *,
    maximum_pixels: int = 4_000_000,
    cell_size: Tuple[int, int] = (900, 650),
) -> bytes:
    if not views:
        raise VisualEvidenceError("At least one view is required for a contact sheet.")
    columns = 2
    rows = (len(views) + columns - 1) // columns
    width = columns * cell_size[0]
    height = rows * cell_size[1]
    if width * height > maximum_pixels:
        scale = (maximum_pixels / float(width * height)) ** 0.5
        cell_size = (
            max(200, int(cell_size[0] * scale)),
            max(160, int(cell_size[1] * scale)),
        )
        width = columns * cell_size[0]
        height = rows * cell_size[1]
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (label, image) in enumerate(views):
        column = index % columns
        row = index // columns
        cell_left = column * cell_size[0]
        cell_top = row * cell_size[1]
        label_height = 28
        cropped = image.crop(_content_bbox(image))
        fitted = ImageOps.contain(
            cropped,
            (cell_size[0] - 24, cell_size[1] - label_height - 16),
        )
        x = cell_left + (cell_size[0] - fitted.width) // 2
        y = cell_top + label_height + (
            cell_size[1] - label_height - fitted.height
        ) // 2
        sheet.paste(fitted, (x, y))
        draw.text((cell_left + 12, cell_top + 8), label, fill=(20, 32, 45))
    output = io.BytesIO()
    sheet.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue()


def ingest_solidworks_visuals(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    capture_dir: str | Path,
    assembly_base_name: str,
    glb_path: str | Path | None = None,
    mask_capture_system: str = "solidworks-com",
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, bytes]]:
    capture_root = Path(capture_dir)
    legend_path = capture_root / f"{assembly_base_name}_identity_mask_legend.tsv"
    entries = read_occurrence_legend(legend_path)
    known_ids = {
        occurrence["occurrenceId"]
        for occurrence in documents["product_structure.json"]["occurrences"]
    }
    legend_ids = {entry["occurrenceId"] for entry in entries}
    if not legend_ids.issubset(known_ids):
        raise VisualEvidenceError("Mask legend references unknown occurrence IDs.")
    if len(legend_ids) != len(entries):
        raise VisualEvidenceError("Mask legend reuses an occurrence ID.")

    assets: Dict[str, bytes] = {}
    view_records = []
    findings: List[Dict[str, Any]] = []
    presentation_images: List[Tuple[str, Image.Image]] = []
    legend = {entry["hexColor"]: entry["occurrenceId"] for entry in entries}
    for view_name in VIEW_NAMES:
        presentation_source = capture_root / (
            f"{assembly_base_name}_view_{view_name}.png"
        )
        mask_source = capture_root / (
            f"{assembly_base_name}_identity_mask_view_{view_name}.png"
        )
        if not presentation_source.is_file() or not mask_source.is_file():
            raise VisualEvidenceError(f"Missing paired SolidWorks view: {view_name}")
        presentation_bytes, presentation_size, presentation_image = _real_png_bytes(
            presentation_source
        )
        mask_bytes, mask_size, mask_image = _real_png_bytes(mask_source)
        if presentation_size != mask_size:
            raise VisualEvidenceError(
                f"Presentation and mask dimensions differ for {view_name}."
            )
        visible, fidelity, counts = _visible_occurrences(mask_image, entries)
        if not visible:
            raise VisualEvidenceError(
                f"Identity mask contains no resolvable occurrence pixels: {view_name}"
            )
        if fidelity < 0.30:
            raise VisualEvidenceError(
                f"Identity-mask fidelity is too low for {view_name}: {fidelity:.3f}"
            )
        if fidelity < 0.70:
            findings.append(
                _finding(
                    "warning",
                    "identity_mask_fidelity_limited",
                    f"Identity-mask color fidelity is limited in {view_name}.",
                    subject_refs=visible,
                    details={"fidelity": round(fidelity, 4)},
                )
            )
        presentation_path = f"visuals/presentation/{view_name}.png"
        mask_path = f"visuals/identity_masks/{view_name}.png"
        assets[presentation_path] = presentation_bytes
        assets[mask_path] = mask_bytes
        presentation_images.append((view_name, presentation_image))
        view_records.append(
            {
                "viewId": f"assembly-{view_name}-001",
                "kind": "presentation",
                "assetPath": presentation_path,
                "assetHash": hashlib.sha256(presentation_bytes).hexdigest(),
                "maskAssetPath": mask_path,
                "maskAssetHash": hashlib.sha256(mask_bytes).hexdigest(),
                "camera": {
                    "captureSystem": "solidworks-com",
                    "maskCaptureSystem": mask_capture_system,
                    "namedView": view_name,
                    "pairedCapture": True,
                },
                "projection": "orthographic",
                "width": presentation_size[0],
                "height": presentation_size[1],
                "visibleOccurrenceIds": visible,
                "colorLegend": legend,
                "mateIds": [],
                "featureIds": [],
            }
        )
        missing_in_view = sorted(
            occurrence_id
            for occurrence_id, count in counts.items()
            if count < MIN_OCCURRENCE_PIXELS
        )
        if missing_in_view:
            findings.append(
                _finding(
                    "info",
                    "occurrence_not_visible_in_view",
                    f"{len(missing_in_view)} occurrences are not visible in {view_name}.",
                    subject_refs=missing_in_view,
                    details={"view": view_name},
                )
            )

    contact_sheet = build_contact_sheet(presentation_images)
    contact_path = "visuals/presentation/contact-sheet.png"
    assets[contact_path] = contact_sheet
    contact_hash = hashlib.sha256(contact_sheet).hexdigest()
    if glb_path is not None:
        glb_source = Path(glb_path)
        if not glb_source.is_file():
            raise VisualEvidenceError(f"GLB asset does not exist: {glb_source}")
        assets["visuals/assembly.glb"] = glb_source.read_bytes()

    updated = {
        name: dict(value) for name, value in documents.items()
    }
    updated["visual_manifest.json"] = {
        "schemaVersion": 1,
        "sourceRevision": documents["package.json"]["sourceRevision"],
        "views": view_records,
        "contactSheets": [
            {
                "contactSheetId": "assembly-overview-001",
                "assetPath": contact_path,
                "assetHash": contact_hash,
                "viewIds": [record["viewId"] for record in view_records],
                "width": Image.open(io.BytesIO(contact_sheet)).width,
                "height": Image.open(io.BytesIO(contact_sheet)).height,
            }
        ],
        "findings": sorted(findings, key=lambda item: item["findingId"]),
    }
    asset_hashes = {
        path: hashlib.sha256(payload).hexdigest()
        for path, payload in sorted(assets.items())
    }
    refreshed = refresh_package_revision(updated, asset_hashes=asset_hashes)
    return refreshed, assets
