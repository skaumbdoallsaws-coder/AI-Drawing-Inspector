"""Publish curated top-level CAD assets from the local machine library.

Internal assembly components are intentionally excluded. The generated
catalog contains no absolute source paths and is consumed only when private
Facility Layout assets are enabled.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from render_industrial_asset_thumbnail import (  # noqa: E402
    render_industrial_asset_thumbnail,
)
from render_industrial_asset_software_thumbnail import (  # noqa: E402
    render_software_thumbnail,
)


DEFAULT_SOURCE_ROOT = Path(
    r"C:\Users\might\OneDrive\Desktop\machine library"
)
DEFAULT_OUTPUT_ROOT = ROOT / "generated" / "industrial_assets" / "local_library"
DEFAULT_EXTRACTOR = ROOT / "SolidWorksExtractor" / "bin" / "Release" / "SolidWorksExtractor.exe"
CATALOG_PATH = DEFAULT_OUTPUT_ROOT / "catalog.json"
# Headless Chromium can close while decoding dense CAD GLBs well below 96 MB.
# Keep large catalog previews on the bounded software path; the full GLB is
# still preserved for the interactive Facility Layout viewer.
SOFTWARE_THUMBNAIL_THRESHOLD_BYTES = 64 * 1024 * 1024


def _windows_process_ids(image_name: str) -> set[int]:
    if os.name != "nt":
        return set()
    result = subprocess.run(
        [
            "tasklist",
            "/FI",
            f"IMAGENAME eq {image_name}",
            "/FO",
            "CSV",
            "/NH",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    process_ids = set()
    for row in csv.reader(io.StringIO(result.stdout or "")):
        if len(row) < 2 or row[0].casefold() != image_name.casefold():
            continue
        try:
            process_ids.add(int(row[1].replace(",", "")))
        except ValueError:
            continue
    return process_ids


def _close_new_solidworks_instances(existing: set[int]) -> tuple[int, ...]:
    created = sorted(_windows_process_ids("SLDWORKS.exe") - existing)
    for process_id in created:
        result = subprocess.run(
            ["taskkill", "/PID", str(process_id), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            print(
                "    warning: could not close extraction-owned "
                f"SolidWorks process {process_id}",
                flush=True,
            )
    return tuple(created)


@dataclass(frozen=True)
class SourceAsset:
    asset_id: str
    display_name: str
    category: str
    relative_path: str
    source_kind: str
    description: str
    tags: tuple[str, ...] = ()
    canonical_rotation_degrees: tuple[float, float, float] = (0.0, 0.0, 0.0)
    support_surfaces: tuple[Mapping[str, Any], ...] = ()

    @property
    def slug(self) -> str:
        return self.asset_id.removeprefix("asset-")


PART_ASSETS = (
    SourceAsset(
        "asset-machine-1d601",
        "1D601 Industrial Machine",
        "Machines",
        "User Library-1D601.sldprt",
        "part",
        "Local industrial machine model from the private equipment library.",
        ("1d601", "industrial equipment"),
    ),
    SourceAsset(
        "asset-bar-loader-lns-qls-lf",
        "LNS QLS-LF Bar Loader",
        "Material Handling",
        "User Library-BARLOADER_LNS-QLS_LF.sldprt",
        "part",
        "Bar-feeding equipment for compatible turning centers.",
        ("bar feeder", "lathe accessory", "lns"),
    ),
    SourceAsset(
        "asset-cnc-lathe",
        "CNC Lathe",
        "Machines",
        "User Library-CNC Lathe.sldprt",
        "part",
        "CNC turning-center model from the private equipment library.",
        ("turning", "turning center", "lathe"),
    ),
    SourceAsset(
        "asset-lathe-acer-1760g",
        "ACER 1760G Lathe",
        "Machines",
        "User Library-Lathe-ACER1760G.sldprt",
        "part",
        "ACER 1760G manual lathe model.",
        ("turning", "manual lathe", "acer"),
    ),
    SourceAsset(
        "asset-lathe-mori-cl200a",
        "Mori CL-200A CNC Lathe",
        "Machines",
        "User Library-Lathe-CNC-Mori-CL200A.sldprt",
        "part",
        "Mori CL-200A CNC turning-center model.",
        ("turning", "cnc lathe", "mori"),
    ),
    SourceAsset(
        "asset-lathe-hardinge-hlv",
        "Hardinge HLV Lathe",
        "Machines",
        "User Library-Lathe-HARDINGE-HLV.sldprt",
        "part",
        "Hardinge HLV precision lathe model.",
        ("turning", "precision lathe", "hardinge"),
    ),
    SourceAsset(
        "asset-operator",
        "Operator",
        "People",
        "User Library-operator-3.sldprt",
        "part",
        "Human-scale operator reference for workstation and aisle planning.",
        ("person", "ergonomics", "scale reference"),
    ),
    SourceAsset(
        "asset-industrial-oven",
        "Industrial Oven",
        "Machines",
        "User Library-OVEN-Industrial.sldprt",
        "part",
        "Industrial process-oven model.",
        ("oven", "heat treatment", "curing"),
    ),
    SourceAsset(
        "asset-vertical-band-saw",
        "Vertical Band Saw",
        "Machines",
        "User Library-SAW-VerticalBand-Large.sldprt",
        "part",
        "Large vertical band-saw model.",
        ("saw", "cutting", "band saw"),
    ),
    SourceAsset(
        "asset-sinker-edm",
        "Sinker EDM Machine",
        "Machines",
        "User Library-Shinker EDM machine.sldprt",
        "part",
        "Sinker electrical-discharge machining center model.",
        ("edm", "electrical discharge machining"),
    ),
    SourceAsset(
        "asset-nordson-3-axis-robot",
        "Nordson EFD 3-Axis Robot",
        "Automation",
        (
            "NORDSONEFD-7362101  ROBOT E6 TP 3 AXIS 620 X 500 X 150MM/"
            "NORDSONEFD-7362101  ROBOT E6 TP 3 AXIS 620 X 500 X 150MM.sldprt"
        ),
        "part",
        "Nordson EFD E6 benchtop three-axis dispensing robot.",
        ("robot", "dispensing", "three axis", "nordson"),
    ),
    SourceAsset(
        "asset-doosan-dbc130-ii",
        "Doosan DBC130 II",
        "Machines",
        "User Library-DOSSAN DBC130 II/User Library-DOSSAN DBC130 II.sldprt",
        "part",
        "Doosan DBC130 II horizontal boring-machine model.",
        ("boring mill", "doosan", "machining center"),
    ),
    SourceAsset(
        "asset-three-axis-cnc",
        "Three-Axis CNC Machine",
        "Machines",
        (
            "User Library-Three Axis CNC Machine/"
            "User Library-Three Axis CNC Machine.sldprt"
        ),
        "part",
        "Three-axis CNC machining-center model.",
        ("cnc", "milling", "three axis"),
    ),
    SourceAsset(
        "asset-haas-st30-lathe",
        "Haas ST-30 CNC Lathe",
        "Machines",
        "User Library-Torno Haas ST 30/User Library-Torno Haas ST 30.sldprt",
        "part",
        "Haas ST-30 CNC turning-center model.",
        ("haas", "turning", "cnc lathe"),
    ),
)


ASSEMBLY_ASSETS = (
    SourceAsset(
        "asset-adtech-sa6-robot",
        "ADTECH SA6-1440H Robot",
        "Automation",
        "188071816-7-sa6-1440h/sa6-1440h.SLDASM",
        "assembly",
        "ADTECH SA6-1440H six-axis industrial robot.",
        ("robot", "six axis", "adtech"),
    ),
    SourceAsset(
        "asset-machine-guard-gate",
        "Machine Guarding Gate",
        "Safety",
        "188072178-7-sgg_lh_0700_1500_0/sgg_lh_0700_1500_0.SLDASM",
        "assembly",
        "Left-hinged 700 x 1500 mm machine-guarding gate.",
        ("guarding", "safety gate", "mesh"),
    ),
    SourceAsset(
        "asset-wood-storage-cart",
        "Wood Storage Cart",
        "Material Handling",
        "8020-Wood Storage Cart/8020-Wood Storage Cart.sldasm",
        "assembly",
        "Mobile material-storage cart built from an 8020 frame.",
        ("cart", "mobile storage", "8020"),
    ),
    SourceAsset(
        "asset-abb-irb6650-robot",
        "ABB IRB 6650 Robot",
        "Automation",
        (
            "User Library-6-axis robot abb6650_320_125/"
            "User Library-6-axis robot abb6650_320_125.SLDASM"
        ),
        "assembly",
        "ABB IRB 6650 six-axis industrial robot.",
        ("robot", "six axis", "abb"),
    ),
    SourceAsset(
        "asset-fanuc-14tes2-robot",
        "FANUC 14tes2 Robot",
        "Automation",
        "User Library-Fanuc_14tes2/User Library-Fanuc_14tes2.sldasm",
        "assembly",
        "FANUC industrial robot model from the private equipment library.",
        ("robot", "fanuc", "automation"),
    ),
)


ADDITIONAL_LIBRARY_ASSETS = (
    SourceAsset(
        "asset-portable-platform-stair-ma613",
        "MA613 Portable Platform Stair",
        "Safety",
        "User Library-3939 PART.sldprt",
        "part",
        "Two-step portable stair with a 28-inch-high work platform.",
        ("portable stair", "access platform", "maintenance access", "ma613"),
    ),
    SourceAsset(
        "asset-okamoto-surface-grinder",
        "Okamoto Surface Grinder",
        "Machines",
        "User Library-Grinder-Surface-Okamoto.sldprt",
        "part",
        "Okamoto surface-grinding machine model.",
        ("grinder", "surface grinding", "okamoto"),
    ),
    SourceAsset(
        "asset-woodworking-jointer",
        "Woodworking Jointer",
        "Machines",
        "User Library-Jointer.sldprt",
        "part",
        "Woodworking jointer for flattening and squaring stock.",
        ("jointer", "woodworking", "stock preparation"),
    ),
    SourceAsset(
        "asset-kalamazoo-h9aw-horizontal-band-saw",
        "Kalamazoo H9AW Horizontal Band Saw",
        "Machines",
        "User Library-Kalamazoo H9AW Horizontal Bandsaw.sldprt",
        "part",
        "Kalamazoo H9AW horizontal band-saw model.",
        ("band saw", "horizontal saw", "cutting", "kalamazoo"),
    ),
    SourceAsset(
        "asset-mobile-folding-worktable",
        "Mobile Folding Worktable",
        "Workstations",
        "Folding worktable/8020-Mobile Folding Worktable.SLDASM",
        "assembly",
        "Mobile folding worktable built from an 8020 aluminum frame.",
        ("worktable", "folding table", "mobile workstation", "8020"),
    ),
    SourceAsset(
        "asset-mobile-access-stair",
        "Mobile Access Stair",
        "Safety",
        "Stair/User Library-Stair-2.sldasm",
        "assembly",
        "Mobile industrial access stair for elevated work areas.",
        ("stair", "mobile access", "maintenance access", "safety"),
    ),
)


WORKBENCH_PATTERN = re.compile(
    r"^RF--WA01-W(?P<width>\d+)-D(?P<depth>\d+)-H(?P<height>\d+)-.*\.sldprt$",
    re.IGNORECASE,
)


def _workbench_assets(source_root: Path) -> tuple[SourceAsset, ...]:
    assets = []
    for path in sorted(source_root.glob("RF--WA01-*.sldprt")):
        match = WORKBENCH_PATTERN.match(path.name)
        if match is None:
            continue
        width = match.group("width")
        depth = match.group("depth")
        if width == "48" and depth == "36":
            continue
        assets.append(SourceAsset(
            f"asset-workbench-w{width}-d{depth}",
            f"Assembly Workbench {width} x {depth} in",
            "Workstations",
            path.name,
            "part",
            f"WA01 assembly workstation with a {width} x {depth} inch top.",
            ("workbench", "assembly station", f"{width}x{depth}"),
        ))
    return tuple(assets)


def _manifest_assets(path: Path) -> tuple[SourceAsset, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("asset manifest must use schemaVersion 1")
    values = payload.get("assets")
    if not isinstance(values, list) or not values:
        raise ValueError("asset manifest assets must be a non-empty array")
    assets = []
    identifiers: set[str] = set()
    relative_paths: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise ValueError(f"asset manifest item {index} must be an object")

        def required(name: str) -> str:
            result = str(value.get(name, "") or "").strip()
            if not result:
                raise ValueError(
                    f"asset manifest item {index} is missing {name}"
                )
            return result

        asset_id = required("assetId")
        if not re.fullmatch(r"asset-[a-z0-9]+(?:-[a-z0-9]+)*", asset_id):
            raise ValueError(
                f"asset manifest item {index} has an invalid assetId"
            )
        if asset_id in identifiers:
            raise ValueError(f"duplicate asset manifest ID: {asset_id}")
        identifiers.add(asset_id)
        relative_path = required("relativePath").replace("/", os.sep)
        parsed_path = Path(relative_path)
        if parsed_path.is_absolute() or ".." in parsed_path.parts:
            raise ValueError(
                f"asset manifest item {index} must use a relative path"
            )
        path_key = parsed_path.as_posix().casefold()
        if path_key in relative_paths:
            raise ValueError(
                f"duplicate asset manifest path: {parsed_path.as_posix()}"
            )
        relative_paths.add(path_key)
        source_kind = required("sourceKind").lower()
        if source_kind not in {"part", "assembly"}:
            raise ValueError(
                f"asset manifest item {index} sourceKind must be part or assembly"
            )
        expected_suffix = ".sldprt" if source_kind == "part" else ".sldasm"
        if parsed_path.suffix.lower() != expected_suffix:
            raise ValueError(
                f"asset manifest item {index} path does not match sourceKind"
            )
        raw_tags = value.get("tags", [])
        if not isinstance(raw_tags, list) or any(
            not isinstance(tag, str) or not tag.strip() for tag in raw_tags
        ):
            raise ValueError(
                f"asset manifest item {index} tags must be non-empty strings"
            )
        raw_rotation = value.get("canonicalRotationDegrees", {})
        if raw_rotation is None:
            raw_rotation = {}
        if not isinstance(raw_rotation, dict):
            raise ValueError(
                f"asset manifest item {index} canonicalRotationDegrees "
                "must be an object"
            )
        unknown_rotation_fields = set(raw_rotation) - {"x", "y", "z"}
        if unknown_rotation_fields:
            raise ValueError(
                f"asset manifest item {index} canonicalRotationDegrees "
                f"contains unknown fields: {sorted(unknown_rotation_fields)}"
            )
        rotation = []
        for axis in ("x", "y", "z"):
            raw_value = raw_rotation.get(axis, 0.0)
            if isinstance(raw_value, bool) or not isinstance(
                raw_value, (int, float)
            ):
                raise ValueError(
                    f"asset manifest item {index} canonicalRotationDegrees."
                    f"{axis} must be a finite number"
                )
            number = float(raw_value)
            if not math.isfinite(number) or abs(number) > 360.0:
                raise ValueError(
                    f"asset manifest item {index} canonicalRotationDegrees."
                    f"{axis} must be between -360 and 360"
                )
            rotation.append(number)
        raw_surfaces = value.get("supportSurfaces", [])
        if not isinstance(raw_surfaces, list):
            raise ValueError(
                f"asset manifest item {index} supportSurfaces must be an array"
            )
        support_surfaces = []
        surface_ids: set[str] = set()
        for surface_index, raw_surface in enumerate(raw_surfaces):
            if not isinstance(raw_surface, dict):
                raise ValueError(
                    f"asset manifest item {index} support surface "
                    f"{surface_index} must be an object"
                )
            allowed_fields = {
                "surfaceId",
                "label",
                "elevationRatio",
                "originXRatio",
                "originZRatio",
                "widthRatio",
                "depthRatio",
                "allowedSides",
                "evidenceStatus",
            }
            unknown_fields = set(raw_surface) - allowed_fields
            if unknown_fields:
                raise ValueError(
                    f"asset manifest item {index} support surface "
                    f"{surface_index} contains unknown fields: "
                    f"{sorted(unknown_fields)}"
                )
            surface_id = str(raw_surface.get("surfaceId", "") or "").strip()
            if (
                not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", surface_id)
                or surface_id in surface_ids
            ):
                raise ValueError(
                    f"asset manifest item {index} support surface ID is invalid"
                )
            surface_ids.add(surface_id)
            label = str(raw_surface.get("label", "") or "").strip()
            if not label:
                raise ValueError(
                    f"asset manifest item {index} support surface label is missing"
                )

            def ratio(name: str, default: float, minimum: float) -> float:
                raw_value = raw_surface.get(name, default)
                if isinstance(raw_value, bool) or not isinstance(
                    raw_value,
                    (int, float),
                ):
                    raise ValueError(
                        f"asset manifest item {index} support surface "
                        f"{name} is invalid"
                    )
                result = float(raw_value)
                if not math.isfinite(result) or not minimum <= result <= 1.0:
                    raise ValueError(
                        f"asset manifest item {index} support surface "
                        f"{name} must be between {minimum} and 1"
                    )
                return result

            def signed_ratio(name: str, default: float = 0.0) -> float:
                raw_value = raw_surface.get(name, default)
                if isinstance(raw_value, bool) or not isinstance(
                    raw_value,
                    (int, float),
                ):
                    raise ValueError(
                        f"asset manifest item {index} support surface "
                        f"{name} is invalid"
                    )
                result = float(raw_value)
                if not math.isfinite(result) or not -1.0 <= result <= 1.0:
                    raise ValueError(
                        f"asset manifest item {index} support surface "
                        f"{name} must be between -1 and 1"
                    )
                return result

            allowed_sides = raw_surface.get("allowedSides", ["above"])
            if (
                not isinstance(allowed_sides, list)
                or not allowed_sides
                or len(allowed_sides) != len(set(allowed_sides))
                or any(side not in {"above", "below"} for side in allowed_sides)
            ):
                raise ValueError(
                    f"asset manifest item {index} support surface sides are invalid"
                )
            evidence_status = str(
                raw_surface.get("evidenceStatus", "derived") or ""
            ).strip()
            if evidence_status not in {
                "authored",
                "derived",
                "inferred",
                "unverified",
                "unknown",
            }:
                raise ValueError(
                    f"asset manifest item {index} support surface evidence is invalid"
                )
            support_surfaces.append({
                "surfaceId": surface_id,
                "label": label,
                "elevationRatio": ratio("elevationRatio", 1.0, 0.0),
                "originXRatio": signed_ratio("originXRatio"),
                "originZRatio": signed_ratio("originZRatio"),
                "widthRatio": ratio("widthRatio", 1.0, 0.01),
                "depthRatio": ratio("depthRatio", 1.0, 0.01),
                "allowedSides": tuple(allowed_sides),
                "evidenceStatus": evidence_status,
            })
        assets.append(SourceAsset(
            asset_id=asset_id,
            display_name=required("displayName"),
            category=required("category"),
            relative_path=str(parsed_path),
            source_kind=source_kind,
            description=required("description"),
            tags=tuple(tag.strip() for tag in raw_tags),
            canonical_rotation_degrees=tuple(rotation),
            support_surfaces=tuple(support_surfaces),
        ))
    return tuple(assets)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _console_safe(value: object) -> str:
    text = str(value)
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(
        encoding,
        errors="replace",
    )


def _catalog_assets(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        raise ValueError("existing catalog assets must be an array")
    return [entry for entry in assets if isinstance(entry, dict)]


def _merge_catalog_assets(
    existing: Iterable[dict],
    published: Iterable[dict],
) -> list[dict]:
    by_id = {
        str(entry.get("assetId", "")): entry
        for entry in existing
        if str(entry.get("assetId", "")).strip()
    }
    for entry in published:
        asset_id = str(entry.get("assetId", "")).strip()
        if not asset_id:
            raise ValueError("published catalog entry is missing assetId")
        by_id[asset_id] = entry
    return sorted(
        by_id.values(),
        key=lambda item: (
            str(item.get("category", "")),
            str(item.get("displayName", "")),
            str(item.get("assetId", "")),
        ),
    )


def _source_sha256(entry: dict) -> str:
    source = entry.get("source", {})
    if not isinstance(source, dict):
        return ""
    return str(source.get("sha256", "")).strip().lower()


def _missing_sources(
    sources: Iterable[SourceAsset],
    *,
    source_root: Path,
    existing: Iterable[dict],
) -> tuple[tuple[SourceAsset, ...], list[dict]]:
    existing_by_id = {
        str(entry.get("assetId", "")): entry
        for entry in existing
        if str(entry.get("assetId", "")).strip()
    }
    existing_by_sha = {
        _source_sha256(entry): entry
        for entry in existing
        if _source_sha256(entry)
    }
    missing = []
    skipped = []
    for source in sources:
        source_path = source_root / Path(source.relative_path)
        if not source_path.is_file():
            missing.append(source)
            continue
        source_hash = _sha256(source_path)
        current = existing_by_id.get(source.asset_id)
        duplicate = existing_by_sha.get(source_hash)
        if current is not None and _source_sha256(current) == source_hash:
            if _entry_rotation_degrees(
                current
            ) == source.canonical_rotation_degrees:
                skipped.append({
                    "assetId": source.asset_id,
                    "reason": "unchanged_asset",
                })
                continue
        if duplicate is not None and str(duplicate.get("assetId")) != source.asset_id:
            skipped.append({
                "assetId": source.asset_id,
                "existingAssetId": duplicate.get("assetId"),
                "reason": "duplicate_source",
            })
            continue
        missing.append(source)
    return tuple(missing), skipped


def _extract(
    source: SourceAsset,
    source_path: Path,
    target: Path,
    extractor: Path,
    *,
    start_solidworks: bool,
) -> Path:
    output = target / "extracted.json"
    command = [
        str(extractor),
        str(source_path),
        "--output",
        str(output),
        "--fast",
        "--no-views",
    ]
    if source.source_kind == "assembly":
        command.extend(("--no-parts", "--resolve", "--export-glb"))
    else:
        command.append("--part-glb")
    if start_solidworks:
        command.append("--start")
    attempts = [("custom", command)]
    if source.source_kind == "part":
        attempts.append(("body", [
            "--process-bodies" if value == "--part-glb" else value
            for value in command
        ]))
        attempts.append(("native", [
            "--native-glb" if value == "--part-glb" else value
            for value in command
        ]))

    transcript = []
    timeout_seconds = 600 if source.source_kind == "assembly" else 300
    last_error = "extractor did not produce a colored GLB"
    for attempt_index, (strategy, attempt_command) in enumerate(attempts):
        if attempt_index:
            fallback_label = (
                "body-level GLB export"
                if strategy == "body"
                else "native SolidWorks GLB export"
            )
            print(
                "    prior part GLB strategy did not complete; "
                f"retrying with {fallback_label}",
                flush=True,
            )
            for partial in target.glob("*.glb"):
                partial.unlink(missing_ok=True)
        try:
            result = _run_extraction_attempt(
                attempt_command,
                timeout_seconds=timeout_seconds,
                start_solidworks=start_solidworks,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            transcript.append(
                f"=== {strategy} export timed out ===\n{stdout}\n{stderr}"
            )
            last_error = (
                f"{strategy} extractor timed out after "
                f"{timeout_seconds} seconds"
            )
            continue

        output_text = (result.stdout or "") + "\n" + (result.stderr or "")
        transcript.append(f"=== {strategy} export ===\n{output_text}")
        candidate = _existing_glb(target)
        if result.returncode == 0 and candidate is not None:
            (target / "extractor.log").write_text(
                "\n".join(transcript),
                encoding="utf-8",
            )
            return candidate
        if result.returncode != 0:
            last_error = (
                f"{strategy} extractor failed ({result.returncode}): "
                f"{output_text[-1200:]}"
            )
        else:
            last_error = f"{strategy} extractor produced no colored GLB"

    (target / "extractor.log").write_text(
        "\n".join(transcript),
        encoding="utf-8",
    )
    raise RuntimeError(last_error)


def _run_extraction_attempt(
    command: list[str],
    *,
    timeout_seconds: int,
    start_solidworks: bool,
) -> subprocess.CompletedProcess:
    existing_solidworks = (
        _windows_process_ids("SLDWORKS.exe")
        if start_solidworks
        else set()
    )
    try:
        return subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    finally:
        if start_solidworks:
            closed = _close_new_solidworks_instances(existing_solidworks)
            if closed:
                print(
                    "    closed extraction-owned SolidWorks process(es): "
                    + ", ".join(str(value) for value in closed),
                    flush=True,
                )


def _finite_bounds(evidence: dict) -> tuple[list[float], list[float]]:
    bounds = evidence.get("geometry", {}).get("bounds", {})
    minimum = bounds.get("min")
    maximum = bounds.get("max")
    if (
        not isinstance(minimum, list)
        or not isinstance(maximum, list)
        or len(minimum) != 3
        or len(maximum) != 3
    ):
        raise ValueError("thumbnail evidence does not contain 3D bounds")
    lower = [float(value) for value in minimum]
    upper = [float(value) for value in maximum]
    if any(not math.isfinite(value) for value in (*lower, *upper)):
        raise ValueError("thumbnail evidence bounds are not finite")
    if any(upper[index] <= lower[index] for index in range(3)):
        raise ValueError("thumbnail evidence bounds are degenerate")
    return lower, upper


def _matrix4_multiply(
    left: tuple[float, ...] | list[float],
    right: tuple[float, ...] | list[float],
) -> list[float]:
    """Multiply column-major matrices using Three.js/glTF conventions."""

    if len(left) != 16 or len(right) != 16:
        raise ValueError("matrix4 multiplication requires two 4x4 matrices")
    result = [0.0] * 16
    for column in range(4):
        for row in range(4):
            result[column * 4 + row] = sum(
                float(left[inner * 4 + row])
                * float(right[column * 4 + inner])
                for inner in range(4)
            )
    return [
        0.0 if abs(value) < 1e-12 else float(value)
        for value in result
    ]


def _rotation_matrix_xyz_degrees(
    rotation_degrees: tuple[float, float, float],
) -> list[float]:
    """Return a Three.js-compatible XYZ Euler rotation matrix."""

    x, y, z = (math.radians(float(value)) for value in rotation_degrees)
    cosine_x, sine_x = math.cos(x), math.sin(x)
    cosine_y, sine_y = math.cos(y), math.sin(y)
    cosine_z, sine_z = math.cos(z), math.sin(z)
    rotate_x = [
        1.0, 0.0, 0.0, 0.0,
        0.0, cosine_x, sine_x, 0.0,
        0.0, -sine_x, cosine_x, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]
    rotate_y = [
        cosine_y, 0.0, -sine_y, 0.0,
        0.0, 1.0, 0.0, 0.0,
        sine_y, 0.0, cosine_y, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]
    rotate_z = [
        cosine_z, sine_z, 0.0, 0.0,
        -sine_z, cosine_z, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]
    return _matrix4_multiply(
        rotate_z,
        _matrix4_multiply(rotate_y, rotate_x),
    )


def _entry_rotation_degrees(entry: dict) -> tuple[float, float, float]:
    value = entry.get("canonicalOrientation", {})
    if not isinstance(value, dict):
        return (0.0, 0.0, 0.0)
    rotation = value.get("rotationDegrees", {})
    if not isinstance(rotation, dict):
        return (0.0, 0.0, 0.0)
    try:
        result = tuple(
            float(rotation.get(axis, 0.0)) for axis in ("x", "y", "z")
        )
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0)
    if not all(math.isfinite(item) for item in result):
        return (0.0, 0.0, 0.0)
    return result


def _catalog_entry(
    source: SourceAsset,
    source_path: Path,
    glb_path: Path,
    target: Path,
) -> dict:
    thumbnail = target / "thumbnail.webp"
    evidence_path = target / "thumbnail-evidence.json"
    evidence = None
    orientation_matrix = _rotation_matrix_xyz_degrees(
        source.canonical_rotation_degrees
    )
    if glb_path.stat().st_size > SOFTWARE_THUMBNAIL_THRESHOLD_BYTES:
        print("    oversized GLB; using bounded software thumbnail", flush=True)
        evidence = render_software_thumbnail(
            glb_path,
            thumbnail,
            evidence_path=evidence_path,
            width=480,
            height=300,
            source_transform=orientation_matrix,
        )
    else:
        for attempt in range(2):
            try:
                evidence = render_industrial_asset_thumbnail(
                    glb_path,
                    thumbnail,
                    evidence_path=evidence_path,
                    width=480,
                    height=300,
                    background="#eef3f7",
                    source_transform=orientation_matrix,
                )
                break
            except Exception as exc:  # noqa: BLE001 - browser retry boundary
                transient = (
                    "TargetClosed" in type(exc).__name__
                    or "browser has been closed" in str(exc)
                )
                if attempt > 0 or not transient:
                    raise
                print("    thumbnail browser closed; retrying once", flush=True)
    if evidence is None:
        raise RuntimeError("thumbnail renderer returned no evidence")
    lower, upper = _finite_bounds(evidence)
    dimensions = [upper[index] - lower[index] for index in range(3)]
    translation_matrix = [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        -(lower[0] + upper[0]) / 2.0,
        -lower[1],
        -(lower[2] + upper[2]) / 2.0,
        1.0,
    ]
    matrix = _matrix4_multiply(translation_matrix, orientation_matrix)
    support_surfaces = []
    for surface in source.support_surfaces:
        width = dimensions[0] * float(surface["widthRatio"])
        depth = dimensions[2] * float(surface["depthRatio"])
        elevation = dimensions[1] * float(surface["elevationRatio"])
        origin_x = dimensions[0] * float(surface["originXRatio"])
        origin_z = dimensions[2] * float(surface["originZRatio"])
        support_surfaces.append({
            "surfaceId": str(surface["surfaceId"]),
            "label": str(surface["label"]),
            "localFrame": {
                "origin": {"x": origin_x, "y": elevation, "z": origin_z},
                "xAxis": {"x": 1.0, "y": 0.0, "z": 0.0},
                "zAxis": {"x": 0.0, "y": 0.0, "z": 1.0},
                "normal": {"x": 0.0, "y": 1.0, "z": 0.0},
            },
            "bounds": {
                "minimumX": -width / 2.0,
                "maximumX": width / 2.0,
                "minimumZ": -depth / 2.0,
                "maximumZ": depth / 2.0,
            },
            "allowedSides": list(surface["allowedSides"]),
            "evidenceStatus": str(surface["evidenceStatus"]),
        })
    entry = {
        "artifact": glb_path.relative_to(ROOT).as_posix(),
        "assetId": source.asset_id,
        "category": source.category,
        "canonicalOrientation": {
            "method": "curated_manifest",
            "rotationDegrees": {
                "x": source.canonical_rotation_degrees[0],
                "y": source.canonical_rotation_degrees[1],
                "z": source.canonical_rotation_degrees[2],
            },
        },
        "description": source.description,
        "dimensions": {
            "depth": dimensions[2],
            "height": dimensions[1],
            "width": dimensions[0],
        },
        "displayName": source.display_name,
        "source": {
            "fileName": source_path.name,
            "kind": source.source_kind,
            "sha256": _sha256(source_path),
        },
        "sourceToCanonical": matrix,
        "tags": list(source.tags),
    }
    if support_surfaces:
        entry["supportSurfaces"] = support_surfaces
    return entry


def _existing_glb(target: Path) -> Path | None:
    for pattern in ("*_colored.glb", "*_body.glb", "*.glb"):
        candidates = sorted(target.glob(pattern))
        if candidates:
            return max(candidates, key=lambda path: path.stat().st_size)
    return None


def _current_cached_glb(target: Path, source_path: Path) -> Path | None:
    expected_sha = _sha256(source_path)
    marker_path = target / "extraction-source.json"
    if marker_path.is_file():
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            marker = {}
        if str(marker.get("sha256", "")).lower() == expected_sha:
            return _existing_glb(target)

    entry_path = target / "catalog-entry.json"
    if entry_path.is_file():
        try:
            entry = json.loads(entry_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            entry = {}
        if _source_sha256(entry) == expected_sha:
            return _existing_glb(target)

    extracted_path = target / "extracted.json"
    candidate = _existing_glb(target)
    if not extracted_path.is_file() or candidate is None:
        return None
    try:
        extracted = json.loads(extracted_path.read_text(encoding="utf-8"))
        extracted_source = Path(str(extracted.get("filePath", ""))).resolve()
    except (OSError, ValueError, TypeError):
        return None
    if extracted_source != source_path.resolve():
        return None
    if candidate.stat().st_mtime < source_path.stat().st_mtime:
        return None
    return candidate


def publish(
    sources: Iterable[SourceAsset],
    *,
    source_root: Path,
    output_root: Path,
    extractor: Path,
    force: bool,
    catalog_only: bool,
    start_solidworks: bool,
) -> tuple[list[dict], list[dict]]:
    entries = []
    failures = []
    for index, source in enumerate(sources, start=1):
        source_path = source_root / Path(source.relative_path)
        target = output_root / source.slug
        target.mkdir(parents=True, exist_ok=True)
        print(
            f"[{index}] {source.display_name}: "
            f"{source.source_kind}",
            flush=True,
        )
        try:
            if not source_path.is_file():
                raise FileNotFoundError(source_path)
            glb_path = (
                _current_cached_glb(target, source_path)
                if catalog_only
                else (
                    None
                    if force
                    else _current_cached_glb(target, source_path)
                )
            )
            if glb_path is None:
                if catalog_only:
                    raise RuntimeError("GLB is not published")
                glb_path = _extract(
                    source,
                    source_path,
                    target,
                    extractor,
                    start_solidworks=start_solidworks,
                )
                _write_json_atomic(target / "extraction-source.json", {
                    "fileName": source_path.name,
                    "sha256": _sha256(source_path),
                })
            entry = _catalog_entry(source, source_path, glb_path, target)
            _write_json_atomic(target / "catalog-entry.json", entry)
            entries.append(entry)
            print(
                "    published "
                f"{entry['dimensions']['width']:.3f} x "
                f"{entry['dimensions']['depth']:.3f} x "
                f"{entry['dimensions']['height']:.3f} m",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - per-asset batch boundary
            failure = {
                "assetId": source.asset_id,
                "error": f"{type(exc).__name__}: {exc}",
            }
            failures.append(failure)
            print(
                f"    FAILED: {_console_safe(failure['error'])}",
                flush=True,
            )
    return entries, failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish curated private machine-library assets."
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--extractor", type=Path, default=DEFAULT_EXTRACTOR)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Publish only the curated assets in a schemaVersion 1 manifest.",
    )
    parser.add_argument("--asset", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--catalog-only", action="store_true")
    parser.add_argument(
        "--start-solidworks",
        action="store_true",
        help="Start SolidWorks when the extractor cannot attach to it.",
    )
    parser.add_argument(
        "--replace-catalog",
        action="store_true",
        help="Replace the catalog instead of merging published assets into it.",
    )
    args = parser.parse_args()

    source_root = args.source_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    extractor = args.extractor.expanduser().resolve()
    all_sources = (
        _manifest_assets(args.manifest.expanduser().resolve())
        if args.manifest is not None
        else (
            *PART_ASSETS,
            *_workbench_assets(source_root),
            *ASSEMBLY_ASSETS,
            *ADDITIONAL_LIBRARY_ASSETS,
        )
    )
    requested = set(args.asset)
    if requested:
        sources = tuple(
            source for source in all_sources if source.asset_id in requested
        )
        missing = requested - {source.asset_id for source in sources}
        if missing:
            parser.error(f"Unknown asset IDs: {sorted(missing)}")
    else:
        sources = tuple(
            source
            for source in all_sources
            if (source_root / Path(source.relative_path)).is_file()
        )
        if not sources:
            parser.error(f"No curated top-level assets found in: {source_root}")
    if not args.catalog_only and not extractor.is_file():
        parser.error(f"Extractor not found: {extractor}")

    catalog_path = output_root / "catalog.json"
    existing_entries = (
        [] if args.replace_catalog else _catalog_assets(catalog_path)
    )
    skipped = []
    if not args.force:
        sources, skipped = _missing_sources(
            sources,
            source_root=source_root,
            existing=existing_entries,
        )

    entries, failures = publish(
        sources,
        source_root=source_root,
        output_root=output_root,
        extractor=extractor,
        force=args.force,
        catalog_only=args.catalog_only,
        start_solidworks=args.start_solidworks,
    )
    catalog_entries = (
        sorted(
            entries,
            key=lambda item: (
                item["category"], item["displayName"], item["assetId"]
            ),
        )
        if args.replace_catalog
        else _merge_catalog_assets(existing_entries, entries)
    )
    payload = {
        "schemaVersion": 1,
        "assets": catalog_entries,
        "summary": {
            "failed": len(failures),
            "published": len(entries),
            "skipped": len(skipped),
            "total": len(catalog_entries),
        },
    }
    _write_json_atomic(catalog_path, payload)
    _write_json_atomic(output_root / "publication-report.json", {
        **payload["summary"],
        "failures": failures,
        "skippedAssets": skipped,
    })
    print(
        "Catalog: "
        f"{len(entries)} published, {len(skipped)} skipped, "
        f"{len(failures)} failed, {len(catalog_entries)} total",
        flush=True,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
