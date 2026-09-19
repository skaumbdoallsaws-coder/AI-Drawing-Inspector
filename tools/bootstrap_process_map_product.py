"""Bootstrap a blank Process Map product from an assembly-knowledge package."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_inspector.process_map.repository import (
    canonical_process_map_bytes,
    process_map_revision,
)
from ai_inspector.process_map.schema_v3 import (
    PROCESS_MAP_LAYOUT_VERSION,
    PROCESS_MAP_PLACEMENT_SCHEMA_VERSION,
    PRODUCT_STRUCTURE_SCHEMA_VERSION,
    validate_product_structure,
)


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _display_name(source: dict[str, Any], explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    root_id = source.get("rootOccurrenceId")
    for occurrence in source.get("occurrences", []):
        if isinstance(occurrence, dict) and occurrence.get("occurrenceId") == root_id:
            name = str(occurrence.get("name") or "").strip()
            if name:
                return name.removeprefix("SWPR-").replace("_", " ")
    return str(source.get("productId") or "Product").replace("-", " ").title()


def _process_product_structure(
    source: dict[str, Any],
    *,
    product_id: str,
    product_name: str,
) -> dict[str, Any]:
    occurrences = []
    for raw in source.get("occurrences", []):
        if not isinstance(raw, dict):
            continue
        occurrence_id = str(raw.get("occurrenceId") or "").strip()
        if not occurrence_id:
            continue
        kind = str(raw.get("kind") or "part").strip().lower()
        item_id = raw.get("itemId")
        name = str(raw.get("name") or occurrence_id)
        occurrence = {
            "occurrenceId": occurrence_id,
            "parentOccurrenceId": raw.get("parentOccurrenceId"),
            "itemId": item_id,
            "name": name,
            "kind": kind,
            "level": int(raw.get("level") or 0),
            "partIds": (
                [item_id]
                if kind == "part" and isinstance(item_id, str) and item_id
                else []
            ),
            "partNames": [name] if kind == "part" else [],
            "sourceOccurrenceId": str(
                raw.get("sourceOccurrenceId") or occurrence_id
            ),
        }
        for key in (
            "configuration",
            "quantity",
            "sourceHash",
            "sourceId",
            "sourcePath",
            "state",
            "transform",
            "properties",
        ):
            if key in raw:
                occurrence[key] = raw[key]
        occurrences.append(occurrence)
    return {
        "schemaVersion": PRODUCT_STRUCTURE_SCHEMA_VERSION,
        "productId": product_id,
        "productName": product_name,
        "occurrences": occurrences,
    }


def bootstrap(
    *,
    package_dir: Path,
    training_root: Path,
    product_id: str,
    product_name: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    source = _read_json_object(package_dir / "product_structure.json")
    package = _read_json_object(package_dir / "package.json")
    if source.get("productId") != product_id or package.get("productId") != product_id:
        raise ValueError("package productId does not match --product-id")

    product_name = _display_name(source, product_name)
    structure = _process_product_structure(
        source,
        product_id=product_id,
        product_name=product_name,
    )
    findings = validate_product_structure(structure)
    errors = [item for item in findings if item.get("severity") == "error"]
    if errors:
        raise ValueError(f"generated product structure is invalid: {errors}")

    product_dir = training_root / product_id
    process_maps_dir = product_dir / "process_maps"
    registry_path = process_maps_dir / "registry.json"
    if registry_path.exists() and not force:
        raise FileExistsError(
            f"{registry_path} already exists; omit bootstrap or pass --force"
        )
    if process_maps_dir.is_dir() and any(process_maps_dir.iterdir()) and force:
        raise FileExistsError(
            "refusing to replace an initialized process_maps directory"
        )

    stem = product_id.replace("-", "_")
    structure_path = product_dir / f"{stem}_product_structure.json"
    legacy_path = product_dir / f"{stem}_process_map_working_draft.json"
    unique_items_path = product_dir / f"{stem}_unique_items.json"
    structure_revision = process_map_revision(structure)
    process_map = {
        "schemaVersion": PROCESS_MAP_PLACEMENT_SCHEMA_VERSION,
        "productId": product_id,
        "productName": product_name,
        "sourceStructureRevision": structure_revision,
        "layoutVersion": PROCESS_MAP_LAYOUT_VERSION,
        "canvasNodes": [],
        "canvasEdges": [],
        "canvasGroups": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
    }
    unique_items = {
        "schemaVersion": 1,
        "productId": product_id,
        "items": [
            {
                "partId": occurrence["itemId"],
                "name": occurrence["name"],
                "sourceOccurrenceId": occurrence["occurrenceId"],
            }
            for occurrence in structure["occurrences"]
            if occurrence["kind"] == "part" and occurrence.get("itemId")
        ],
    }

    _write_atomic(structure_path, canonical_process_map_bytes(structure))
    _write_atomic(legacy_path, canonical_process_map_bytes(process_map))
    _write_atomic(unique_items_path, canonical_process_map_bytes(unique_items))
    return {
        "productId": product_id,
        "productName": product_name,
        "packageId": package.get("packageId"),
        "packageRevision": package.get("packageRevision"),
        "structureRevision": structure_revision,
        "occurrenceCount": len(structure["occurrences"]),
        "canvasNodeCount": 0,
        "assets": [
            str(structure_path),
            str(legacy_path),
            str(unique_items_path),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--training-root", type=Path, default=Path("generated/training"))
    parser.add_argument("--product-id", required=True)
    parser.add_argument("--product-name")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = bootstrap(
        package_dir=args.package_dir.resolve(),
        training_root=args.training_root.resolve(),
        product_id=args.product_id,
        product_name=args.product_name,
        force=args.force,
    )
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
