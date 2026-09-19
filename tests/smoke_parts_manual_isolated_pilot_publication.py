"""Run the customer-pilot publication proof against an isolated production server."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

from parts_manual_smoke_support import IsolatedPartsManualServer
from smoke_parts_manual_pilot_publication import ROOT, run


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a parts manual through an isolated production store."
    )
    parser.add_argument("--assembly", default="MMLE-50D")
    parser.add_argument("--minimum-occurrences", type=int, default=200)
    parser.add_argument("--expected-pages", type=int, default=15)
    parser.add_argument("--expected-technical-pages", type=int, default=12)
    args = parser.parse_args()

    output_dir = ROOT / ".runtime" / "parts_manual_isolated_pilot_proof"
    server = IsolatedPartsManualServer(ROOT, output_dir, args.assembly)
    try:
        server.start()
        assembly_slug = re.sub(
            r"[^a-z0-9]+", "-", args.assembly.lower()
        ).strip("-")
        source_dir = ROOT / "generated" / "parts_manual" / assembly_slug
        target_dir = server.store_root / assembly_slug
        target_dir.mkdir(parents=True, exist_ok=True)
        seeded = []
        for name in ("manual-plan.json", "documentation-scene.json"):
            source = source_dir / name
            if not source.is_file():
                raise FileNotFoundError(
                    f"Approved production input is unavailable: {source}"
                )
            target = target_dir / name
            shutil.copy2(source, target)
            seeded.append(
                {
                    "name": name,
                    "source": str(source),
                    "target": str(target),
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                }
            )
        (output_dir / "seeded-inputs.json").write_text(
            json.dumps(
                {
                    "assembly": args.assembly,
                    "purpose": "live-versus-isolated parity input",
                    "capturesCopied": False,
                    "documentsCopied": False,
                    "inputs": seeded,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return run(
            base_url=server.app_url,
            assembly=args.assembly,
            minimum_occurrences=args.minimum_occurrences,
            expected_pages=args.expected_pages,
            expected_technical_pages=args.expected_technical_pages,
            output_dir=Path(output_dir),
        )
    finally:
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
