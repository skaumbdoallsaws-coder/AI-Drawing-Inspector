#!/usr/bin/env python3
"""Start, record, and inspect the real Facility Layout self-use soak."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.soak_evidence import (
    SoakEvidenceError,
    append_soak_event,
    facility_build_identity,
    load_soak_events,
    start_soak_campaign,
    summarize_soak_events,
    verified_apply_evidence,
    verified_dismissal_evidence,
    verified_reopen_evidence,
)


DEFAULT_LEDGER = (
    ROOT / ".runtime" / "facility_layout" / "p11-real-soak-events.json"
)
DEFAULT_RECEIPT_STORE = (
    ROOT / ".runtime" / "facility-layout" / "transactions"
)


def _common_identity() -> dict:
    return facility_build_identity(ROOT)


def _record(args: argparse.Namespace) -> dict:
    evidence: dict
    if args.kind == "editing_session":
        evidence = {
            "layoutId": args.layout_id,
            "sessionId": args.session_id,
            "layoutRevision": args.layout_revision,
        }
    elif args.kind == "agent_preview":
        evidence = {
            "layoutId": args.layout_id,
            "proposalId": args.proposal_id,
            "baseRevision": args.layout_revision,
            "displayedForReview": True,
        }
    elif args.kind == "approved_apply":
        evidence = verified_apply_evidence(
            DEFAULT_RECEIPT_STORE.resolve(),
            receipt_id=args.receipt_id,
            layout_id=args.layout_id,
        )
    elif args.kind == "byte_identical_dismissal":
        evidence = verified_dismissal_evidence(
            args.before_file.resolve(),
            args.after_file.resolve(),
            layout_id=args.layout_id,
            proposal_id=args.proposal_id,
        )
    elif args.kind == "rejected_attempt":
        evidence = {
            "layoutId": args.layout_id,
            "errorCode": args.error_code,
            "statusCode": args.status_code,
        }
    elif args.kind == "layout_reopen":
        evidence = verified_reopen_evidence(
            args.layout_file.resolve(),
            layout_id=args.layout_id,
            layout_revision=args.layout_revision,
        )
    elif args.kind == "workflow_exercised":
        evidence = {"workflow": args.workflow}
    else:
        raise SoakEvidenceError("The soak event kind is unsupported.")
    return append_soak_event(
        args.ledger.resolve(),
        kind=args.kind,
        evidence=evidence,
        build_identity=_common_identity(),
    )


def _add_record_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "kind",
        choices=(
            "editing_session",
            "agent_preview",
            "approved_apply",
            "byte_identical_dismissal",
            "rejected_attempt",
            "layout_reopen",
            "workflow_exercised",
        ),
    )
    parser.add_argument("--layout-id")
    parser.add_argument("--session-id")
    parser.add_argument("--proposal-id")
    parser.add_argument("--layout-revision")
    parser.add_argument("--receipt-id")
    parser.add_argument("--before-file", type=Path)
    parser.add_argument("--after-file", type=Path)
    parser.add_argument("--layout-file", type=Path)
    parser.add_argument("--error-code")
    parser.add_argument("--status-code", type=int)
    parser.add_argument(
        "--workflow",
        choices=("warehouse", "manufacturing_cell", "rollback"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Maintain source-bound, append-only evidence for the literal "
            "Facility Layout self-use soak."
        )
    )
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("start")
    _add_record_arguments(subparsers.add_parser("record"))
    subparsers.add_parser("status")
    args = parser.parse_args()
    try:
        if args.command == "start":
            value = start_soak_campaign(
                args.ledger.resolve(),
                build_identity=_common_identity(),
            )
        elif args.command == "record":
            value = _record(args)
        else:
            value = summarize_soak_events(
                load_soak_events(args.ledger.resolve())
            )
    except (SoakEvidenceError, OSError) as error:
        print(f"ERROR\t{error}", file=sys.stderr)
        return 2
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
