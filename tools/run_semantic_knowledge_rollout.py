"""Resume Revision 5 semantic-knowledge phases without repeating completed work."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable


def _repo_root(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def _load_environment(repo_root: Path) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(repo_root / ".env", override=False)


def _checkpoint(repo_root: Path, phase: int) -> dict[str, Any] | None:
    path = (
        repo_root
        / ".runtime"
        / "semantic-knowledge-rollout"
        / "checkpoints"
        / f"phase-{phase}.json"
    )
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text("utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _first_incomplete_phase(repo_root: Path) -> int:
    for phase in range(8):
        checkpoint = _checkpoint(repo_root, phase)
        if not checkpoint or checkpoint.get("machineGatePassed") is not True:
            return phase
    return 8


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run or resume Revision 5 semantic-knowledge phases 0-7. "
            "Human approval is never inferred."
        )
    )
    parser.add_argument("--repo-root")
    parser.add_argument("--from-phase", type=int, choices=range(8))
    parser.add_argument("--through-phase", type=int, choices=range(8), default=7)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rerun machine-complete phases. Phase 3 still requires explicit authorization.",
    )
    parser.add_argument(
        "--authorize-economy-v1",
        action="store_true",
        help=(
            "Authorize the bounded Phase 3 provider request under economy-v1. "
            "The request remains cache/idempotency protected."
        ),
    )
    parser.add_argument(
        "--skip-release-tests",
        action="store_true",
        help="Build the Phase 7 report without rerunning tests; its machine gate will fail.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = _repo_root(args.repo_root)
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    _load_environment(repo_root)

    from ai_inspector.assembly_knowledge.semantic_rollout import (
        run_phase0,
        run_phase1,
        run_phase2,
        run_phase3,
        run_phase4,
        run_phase5,
        run_phase6,
        run_phase7,
    )

    phase_functions: dict[int, Callable[..., dict[str, Any]]] = {
        0: run_phase0,
        1: run_phase1,
        2: run_phase2,
        3: run_phase3,
        4: run_phase4,
        5: run_phase5,
        6: run_phase6,
        7: run_phase7,
    }
    start = args.from_phase
    if start is None:
        start = _first_incomplete_phase(repo_root)
    if start > args.through_phase:
        print(
            json.dumps(
                {
                    "success": True,
                    "status": "nothing_to_resume",
                    "firstIncompletePhase": start,
                    "throughPhase": args.through_phase,
                },
                indent=2,
            )
        )
        return 0

    results = []
    for phase in range(start, args.through_phase + 1):
        existing = _checkpoint(repo_root, phase)
        if (
            not args.force
            and existing is not None
            and existing.get("machineGatePassed") is True
        ):
            results.append(
                {
                    "phase": phase,
                    "status": "skipped_machine_complete",
                    "checkpointStatus": existing.get("status"),
                }
            )
            continue

        if phase == 3:
            if not args.authorize_economy_v1:
                print(
                    "Phase 3 requires --authorize-economy-v1; no provider call was made.",
                    file=sys.stderr,
                )
                return 2
            api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
            if not api_key:
                print("OPENAI_API_KEY is unavailable; no provider call was made.", file=sys.stderr)
                return 2
            result = phase_functions[phase](repo_root, api_key=api_key)
        elif phase == 7:
            result = phase_functions[phase](
                repo_root,
                run_tests=not args.skip_release_tests,
            )
        else:
            result = phase_functions[phase](repo_root)
        results.append(
            {
                "phase": phase,
                "success": result.get("success"),
                "status": result.get("status"),
            }
        )
        if result.get("success") is not True:
            print(
                json.dumps(
                    {
                        "success": False,
                        "status": "stopped_on_machine_gate",
                        "results": results,
                    },
                    indent=2,
                )
            )
            return 1

    final_checkpoint = _checkpoint(repo_root, args.through_phase)
    print(
        json.dumps(
            {
                "success": True,
                "status": "machine_phases_complete",
                "humanAuthorityGranted": False,
                "results": results,
                "finalCheckpoint": final_checkpoint,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
