"""Operator CLI for deterministic preparation, bounded enrichment, and rollout checks."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_inspector.assembly_knowledge import (
    AnthropicMultimodalProvider,
    AssemblyKnowledgeEnrichmentCache,
    AssemblyKnowledgeRepository,
    OpenAIMultimodalProvider,
    enrich_published_package,
    evaluate_assembly_knowledge_package,
    prepare_deterministic_package,
    prepare_occurrence_map,
)


def _ascii_json(value: Any) -> str:
    return (
        json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    )


def _write_report(path: str | None, value: Any) -> None:
    if not path:
        return
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_ascii_json(value), encoding="ascii")


def _provider(name: str, model: str):
    if name == "openai":
        return OpenAIMultimodalProvider(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=model,
        )
    if name == "anthropic":
        return AnthropicMultimodalProvider(
            api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            model=model,
        )
    raise ValueError(f"Unsupported provider: {name}")


def _deterministic(args: argparse.Namespace) -> dict:
    return prepare_deterministic_package(
        training_root=args.training_root,
        product_id=args.product_id,
        extracted_package_dir=args.extracted_package,
        source_root=args.source_root,
        root_assembly=args.root_assembly,
        active_configuration=args.configuration,
        capture_dir=args.capture_dir,
        assembly_base_name=args.assembly_base_name,
        glb_path=args.glb,
        base_revision=args.base_revision,
    )


def _occurrence_map(args: argparse.Namespace) -> dict:
    return prepare_occurrence_map(
        extracted_package_dir=args.extracted_package,
        source_root=args.source_root,
        root_assembly=args.root_assembly,
        product_id=args.product_id,
        output_path=args.output,
        active_configuration=args.configuration,
    )


def _enrich(args: argparse.Namespace) -> dict:
    provider = _provider(args.provider, args.model)
    cache = AssemblyKnowledgeEnrichmentCache(args.cache_root)
    return enrich_published_package(
        training_root=args.training_root,
        product_id=args.product_id,
        package_id=args.package_id,
        provider_name=args.provider,
        model=args.model,
        provider=provider,
        explicit_approval=args.approve_spend,
        user_id=args.user_id,
        session_id=args.session_id,
        idempotency_key=args.idempotency_key,
        unknown_pricing_acknowledged=args.acknowledge_unknown_pricing,
        cache=cache,
    )


def _evaluate(args: argparse.Namespace) -> dict:
    repository = AssemblyKnowledgeRepository(args.training_root)
    documents = repository.read(args.product_id, args.package_id)
    source_status = repository.source_status(args.product_id, args.package_id)
    runtime_guards = {
        "stalePackageProposalBlocked": args.runtime_guards_verified,
        "unapprovedWriteBlocked": args.runtime_guards_verified,
        "stalePackageProposalEvidence": (
            args.runtime_guard_evidence
            if args.runtime_guards_verified
            else "not verified in this invocation"
        ),
        "unapprovedWriteEvidence": (
            args.runtime_guard_evidence
            if args.runtime_guards_verified
            else "not verified in this invocation"
        ),
    }
    return evaluate_assembly_knowledge_package(
        documents,
        source_status=source_status,
        runtime_guards=runtime_guards,
    )


def _status(args: argparse.Namespace) -> dict:
    repository = AssemblyKnowledgeRepository(args.training_root)
    return {
        "success": True,
        "productId": args.product_id,
        "packages": repository.list_packages(args.product_id),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare revisioned Assembly Knowledge Packages without mutating "
            "a Process Map."
        )
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    occurrence_map = subcommands.add_parser(
        "occurrence-map",
        help=(
            "Create the canonical occurrence mapping used by identity-mask "
            "capture."
        ),
    )
    occurrence_map.add_argument("--product-id", required=True)
    occurrence_map.add_argument("--extracted-package", required=True)
    occurrence_map.add_argument("--source-root", required=True)
    occurrence_map.add_argument("--root-assembly", required=True)
    occurrence_map.add_argument("--configuration")
    occurrence_map.add_argument("--output", required=True)
    occurrence_map.add_argument("--report")
    occurrence_map.set_defaults(handler=_occurrence_map)

    deterministic = subcommands.add_parser(
        "deterministic",
        help="Adapt an extracted assembly package and publish deterministic evidence.",
    )
    deterministic.add_argument("--training-root", required=True)
    deterministic.add_argument("--product-id", required=True)
    deterministic.add_argument("--extracted-package", required=True)
    deterministic.add_argument("--source-root", required=True)
    deterministic.add_argument("--root-assembly", required=True)
    deterministic.add_argument("--configuration")
    deterministic.add_argument("--capture-dir")
    deterministic.add_argument("--assembly-base-name")
    deterministic.add_argument("--glb")
    deterministic.add_argument("--base-revision")
    deterministic.add_argument("--report")
    deterministic.set_defaults(handler=_deterministic)

    enrich = subcommands.add_parser(
        "enrich",
        help="Run one explicitly approved, bounded multimodal enrichment.",
    )
    enrich.add_argument("--training-root", required=True)
    enrich.add_argument("--product-id", required=True)
    enrich.add_argument("--package-id", required=True)
    enrich.add_argument("--provider", choices=("openai", "anthropic"), required=True)
    enrich.add_argument("--model", required=True)
    enrich.add_argument("--user-id", required=True)
    enrich.add_argument("--session-id", required=True)
    enrich.add_argument("--idempotency-key", required=True)
    enrich.add_argument("--cache-root", required=True)
    enrich.add_argument("--approve-spend", action="store_true")
    enrich.add_argument("--acknowledge-unknown-pricing", action="store_true")
    enrich.add_argument("--report")
    enrich.set_defaults(handler=_enrich)

    evaluate = subcommands.add_parser(
        "evaluate",
        help="Compute rollout metrics without invoking a model.",
    )
    evaluate.add_argument("--training-root", required=True)
    evaluate.add_argument("--product-id", required=True)
    evaluate.add_argument("--package-id", required=True)
    evaluate.add_argument("--runtime-guards-verified", action="store_true")
    evaluate.add_argument(
        "--runtime-guard-evidence",
        default="test_assembly_knowledge_process_map_integration.py",
    )
    evaluate.add_argument("--report")
    evaluate.set_defaults(handler=_evaluate)

    status = subcommands.add_parser("status", help="List published packages.")
    status.add_argument("--training-root", required=True)
    status.add_argument("--product-id", required=True)
    status.add_argument("--report")
    status.set_defaults(handler=_status)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = args.handler(args)
    _write_report(args.report, result)
    print(_ascii_json(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
