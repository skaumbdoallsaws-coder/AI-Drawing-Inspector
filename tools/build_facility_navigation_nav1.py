"""Publish deterministic NAV1 contract and field-ownership artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.navigation_contract import (  # noqa: E402
    navigation_contract_manifest,
    navigation_field_mapping_matrix,
)


OUTPUT_ROOT = ROOT / "tests" / "fixtures" / "facility_layout" / "navigation"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _write(path: Path, value: Any) -> dict[str, Any]:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    ).encode("ascii") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def build_nav1_artifacts() -> dict[str, Any]:
    contract = navigation_contract_manifest()
    mapping = {
        "schemaVersion": "facility-navigation-nav1-field-mapping-v1",
        "phase": "NAV1",
        "implementationStatus": "prototype_contract_frozen",
        "productionEligible": False,
        "rows": navigation_field_mapping_matrix(),
    }
    contract_path = OUTPUT_ROOT / "nav1-contract-manifest-v1.json"
    mapping_path = OUTPUT_ROOT / "nav1-field-mapping-v1.json"
    records = [_write(contract_path, contract), _write(mapping_path, mapping)]
    manifest = {
        "schemaVersion": "facility-navigation-nav1-artifact-manifest-v1",
        "phase": "NAV1",
        "productionEligible": False,
        "humanApproval": None,
        "artifacts": records,
        "canonicalContractFingerprint": hashlib.sha256(
            _canonical_bytes(contract)
        ).hexdigest(),
        "canonicalFieldMappingFingerprint": hashlib.sha256(
            _canonical_bytes(mapping)
        ).hexdigest(),
    }
    manifest_record = _write(
        OUTPUT_ROOT / "nav1-artifact-manifest-v1.json",
        manifest,
    )
    return {**manifest, "manifestArtifact": manifest_record}


def main() -> int:
    manifest = build_nav1_artifacts()
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
