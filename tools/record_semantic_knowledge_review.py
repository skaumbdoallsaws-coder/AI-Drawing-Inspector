#!/usr/bin/env python
"""Record explicit human completion of the Revision 5 review artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Record a revision-bound semantic-pilot review. This confirms "
            "reviewed inferred claims without granting controlled authority."
        )
    )
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--attestation", required=True)
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    root = Path(args.repo_root).resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from ai_inspector.assembly_knowledge.semantic_human_review import (
        SemanticHumanReviewError,
        record_semantic_human_review,
    )

    try:
        result = record_semantic_human_review(
            root,
            reviewer=args.reviewer,
            attestation=args.attestation,
        )
    except SemanticHumanReviewError as exc:
        print(
            json.dumps(
                {"success": False, "status": "review_rejected", "error": str(exc)},
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
