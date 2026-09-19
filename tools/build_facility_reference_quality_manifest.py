"""Build the RQ0 pending-review manifest without changing the saved archive."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.host import LocalFacilityLayoutHost  # noqa: E402
from ai_inspector.facility_layout.reference_quality import (  # noqa: E402
    build_reference_manifest,
    build_reference_review_receipt,
)


DEFAULT_ARCHIVE = (
    ROOT
    / ".runtime"
    / "facility-layout"
    / "layouts"
    / "local"
    / "site-local"
    / "layouts"
    / "fl-reference-manual-20260812.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "reference_quality"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    archive = args.archive.resolve()
    source_bytes = archive.read_bytes()
    document = json.loads(source_bytes.decode("utf-8-sig"))
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()

    host = LocalFacilityLayoutHost(
        ROOT / ".runtime" / "facility-layout",
        process_map_root=ROOT / "generated" / "training",
        private_assets=True,
        private_asset_root=ROOT,
    )
    try:
        catalog = host.authoritative_asset_catalog()
    finally:
        host.close()

    manifest = build_reference_manifest(
        document,
        catalog,
        source_path=str(archive.relative_to(ROOT)).replace("\\", "/"),
        source_file_sha256=source_sha256,
    )
    receipt = build_reference_review_receipt(manifest)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != source_sha256:
        raise RuntimeError("Reference archive changed while the manifest was built.")

    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "reference-manifest-v1.json"
    receipt_path = args.output / "reference-review-receipt-v1.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "manifest": str(manifest_path.relative_to(ROOT)).replace("\\", "/"),
                "receipt": str(receipt_path.relative_to(ROOT)).replace("\\", "/"),
                "counts": manifest["counts"],
                "supportDependencies": len(manifest["supportDependencies"]),
                "contacts": manifest["contactAudit"]["countsByClass"],
                "unresolvedCount": len(manifest["unresolved"]),
                "reviewStatus": receipt["reviewStatus"],
                "archiveUnchanged": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

