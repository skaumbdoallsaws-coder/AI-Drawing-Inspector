"""Compare live and isolated parts-manual publication proof artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _capture_hashes(report: dict) -> dict[str, str]:
    return {
        str(row.get("pageId")): str(row.get("sha256"))
        for row in report.get("toolResult", {}).get("captureReceipts", [])
    }


def _page_evidence(path: Path) -> tuple[list[str], list[str], dict]:
    document = fitz.open(path)
    try:
        raster_hashes = []
        text_hashes = []
        for page in document:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            raster_hashes.append(hashlib.sha256(pixmap.samples).hexdigest())
            text_hashes.append(
                hashlib.sha256(page.get_text("text").encode("utf-8")).hexdigest()
            )
        return raster_hashes, text_hashes, dict(document.metadata or {})
    finally:
        document.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare live and isolated parts-manual publication proofs."
    )
    parser.add_argument(
        "--live-report",
        type=Path,
        default=ROOT / ".runtime" / "parts_manual_pilot_proof" / "report.json",
    )
    parser.add_argument(
        "--isolated-report",
        type=Path,
        default=ROOT
        / ".runtime"
        / "parts_manual_isolated_pilot_proof"
        / "report.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".runtime" / "parts_manual_pilot_parity" / "report.json",
    )
    args = parser.parse_args()

    live = _load(args.live_report.resolve())
    isolated = _load(args.isolated_report.resolve())
    live_pdf = Path(live["checks"]["published_pdf_matches_receipt"]["detail"]["path"])
    isolated_pdf = Path(
        isolated["checks"]["published_pdf_matches_receipt"]["detail"]["path"]
    )
    live_rasters, live_text, live_metadata = _page_evidence(live_pdf)
    isolated_rasters, isolated_text, isolated_metadata = _page_evidence(isolated_pdf)
    live_captures = _capture_hashes(live)
    isolated_captures = _capture_hashes(isolated)
    live_revision = str(live.get("toolResult", {}).get("documentRevision") or "")
    isolated_revision = str(
        isolated.get("toolResult", {}).get("documentRevision") or ""
    )
    live_pdf_sha = hashlib.sha256(live_pdf.read_bytes()).hexdigest()
    isolated_pdf_sha = hashlib.sha256(isolated_pdf.read_bytes()).hexdigest()
    checks = {
        "documentRevisionEqual": live_revision == isolated_revision and bool(live_revision),
        "captureManifestHashesEqual": live_captures == isolated_captures
        and bool(live_captures),
        "pageCountEqual": len(live_rasters) == len(isolated_rasters),
        "pagePixelsEqual": live_rasters == isolated_rasters and bool(live_rasters),
        "pageTextEqual": live_text == isolated_text and bool(live_text),
    }
    result = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "live": {
            "report": str(args.live_report.resolve()),
            "pdf": str(live_pdf.resolve()),
            "documentRevision": live_revision,
            "pdfSha256": live_pdf_sha,
            "metadata": live_metadata,
        },
        "isolated": {
            "report": str(args.isolated_report.resolve()),
            "pdf": str(isolated_pdf.resolve()),
            "documentRevision": isolated_revision,
            "pdfSha256": isolated_pdf_sha,
            "metadata": isolated_metadata,
        },
        "captureCount": len(live_captures),
        "pageCount": len(live_rasters),
        "binaryPdfEqual": live_pdf_sha == isolated_pdf_sha,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
