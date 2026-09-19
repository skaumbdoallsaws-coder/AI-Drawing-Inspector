"""Archive the manual reference factory and restore a blank default layout."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.errors import FacilityNotFoundError
from ai_inspector.facility_layout.host import (
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)
from ai_inspector.facility_layout.operations import create_layout_document

DEFAULT_RUNTIME_ROOT = ROOT / ".runtime" / "facility-layout"
REFERENCE_LAYOUT_ID = "fl-reference-manual-20260812"
REFERENCE_DISPLAY_NAME = "Reference Factory - Manual Build"
EXPECTED_SOURCE_REVISION = (
    "8551e0b324df6dc17413d0ef8b6ad7f3bab438ba8558dc00320149bf7f855aa0"
)


def _content_fingerprint(document: Mapping[str, Any]) -> str:
    value = deepcopy(dict(document))
    value["layoutId"] = "layout-content-placeholder"
    value["displayName"] = "Layout Content Placeholder"
    value["createdAt"] = "1970-01-01T00:00:00Z"
    value["updatedAt"] = "1970-01-01T00:00:00Z"
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _counts(document: Mapping[str, Any]) -> dict[str, int]:
    return {
        "zones": len(document.get("zones", [])),
        "routes": len(document.get("routes", [])),
        "placements": len(document.get("placements", [])),
        "floorMarkings": len(document.get("floorMarkings", [])),
    }


def archive_and_reset(runtime_root: Path) -> dict[str, Any]:
    host = LocalFacilityLayoutHost(
        runtime_root,
        process_map_root=ROOT / "generated" / "training",
        private_assets=True,
        private_asset_root=ROOT,
    )
    try:
        host.ensure_bootstrap()
        principal = host.principal()
        current = host.service.get_layout(
            principal,
            LOCAL_SITE_ID,
            LOCAL_LAYOUT_ID,
        )
        current_document = current["layout"]
        current_revision = str(current["revision"])
        current_counts = _counts(current_document)
        already_blank = not any(current_counts.values())

        try:
            archived = host.service.get_layout(
                principal,
                LOCAL_SITE_ID,
                REFERENCE_LAYOUT_ID,
            )
        except FacilityNotFoundError:
            archived = None

        if already_blank:
            if archived is None:
                raise RuntimeError(
                    "The default layout is blank but the reference archive is missing."
                )
            archive_document = archived["layout"]
            source_revision = EXPECTED_SOURCE_REVISION
        else:
            if current_revision != EXPECTED_SOURCE_REVISION:
                raise RuntimeError(
                    "The current default layout is not the recognized manual "
                    f"reference revision: {current_revision}"
                )
            source_revision = current_revision
            source_fingerprint = _content_fingerprint(current_document)
            if archived is None:
                archive_candidate = deepcopy(current_document)
                archive_candidate["layoutId"] = REFERENCE_LAYOUT_ID
                archive_candidate["displayName"] = REFERENCE_DISPLAY_NAME
                archived = host.service.create_layout(
                    principal,
                    LOCAL_SITE_ID,
                    archive_candidate,
                    make_default=False,
                )
            archive_document = archived["layout"]
            if _content_fingerprint(archive_document) != source_fingerprint:
                raise RuntimeError(
                    "The reference archive does not match the manual source layout."
                )

            blank = create_layout_document(
                layout_id=LOCAL_LAYOUT_ID,
                display_name="Blank Facility Layout",
                association=deepcopy(current_document["association"]),
                coordinate_frame=deepcopy(current_document["coordinateFrame"]),
                source_shell_ref=deepcopy(current_document["sourceShellRef"]),
                policy_set_ref=deepcopy(current_document["policySetRef"]),
                created_at=str(current_document["createdAt"]),
            )
            current = host.service.save_layout(
                principal,
                LOCAL_SITE_ID,
                LOCAL_LAYOUT_ID,
                blank,
                current_revision,
            )
            current_document = current["layout"]
            current_revision = str(current["revision"])
            current_counts = _counts(current_document)

        exact_source = host.service.get_layout_revision(
            principal,
            LOCAL_SITE_ID,
            LOCAL_LAYOUT_ID,
            source_revision,
        )
        registry = host.service.list_layouts(
            principal,
            LOCAL_SITE_ID,
            include_archived=True,
        )
        checks = {
            "default_is_blank": not any(current_counts.values()),
            "default_layout_id_unchanged": (
                registry["defaultLayoutId"] == LOCAL_LAYOUT_ID
            ),
            "reference_layout_registered": any(
                item["layoutId"] == REFERENCE_LAYOUT_ID
                for item in registry["layouts"]
            ),
            "reference_content_preserved": (
                _content_fingerprint(archive_document)
                == _content_fingerprint(exact_source["layout"])
            ),
            "exact_source_revision_retrievable": (
                exact_source["revision"] == source_revision
            ),
        }
        return {
            "schemaVersion": "facility-layout-default-reset-receipt-v1",
            "passed": all(checks.values()),
            "checks": checks,
            "defaultLayout": {
                "layoutId": LOCAL_LAYOUT_ID,
                "displayName": current_document["displayName"],
                "revision": current_revision,
                "counts": current_counts,
            },
            "referenceLayout": {
                "layoutId": REFERENCE_LAYOUT_ID,
                "displayName": archive_document["displayName"],
                "revision": archived["revision"],
                "sourceLayoutId": LOCAL_LAYOUT_ID,
                "sourceRevision": source_revision,
                "counts": _counts(archive_document),
            },
            "registry": {
                "defaultLayoutId": registry["defaultLayoutId"],
                "layoutIds": [
                    item["layoutId"] for item in registry["layouts"]
                ],
            },
        }
    finally:
        host.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=DEFAULT_RUNTIME_ROOT,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT
            / "tests"
            / "fixtures"
            / "facility_layout"
            / "knowledge_foundation"
            / "default-layout-reset-receipt.json"
        ),
    )
    args = parser.parse_args()
    receipt = archive_and_reset(args.runtime_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
