"""Operator-controlled Assembly Knowledge Package preparation pipeline."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .cache import AssemblyKnowledgeEnrichmentCache
from .cost_policy import authorize_enrichment_plan, plan_enrichment_request
from .enrichment import (
    ENRICHMENT_PROMPT_VERSION,
    execute_economy_enrichment,
)
from .evidence import compile_deterministic_evidence
from .extract_adapter import adapt_bridge_package, verify_sources_unchanged
from .repository import AssemblyKnowledgeRepository
from .validation import (
    validate_assembly_knowledge_package,
    validation_summary,
)
from .visuals import ingest_solidworks_visuals, write_occurrence_map_tsv


class AssemblyKnowledgePreparationError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _enabled(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def preparation_enabled() -> bool:
    return _enabled("INSPECTORPRO_ASSEMBLY_KNOWLEDGE_PREPARE")


def ai_enrichment_enabled() -> bool:
    return _enabled("INSPECTORPRO_ASSEMBLY_KNOWLEDGE_AI_ENRICHMENT")


def prepare_occurrence_map(
    *,
    extracted_package_dir: str | Path,
    source_root: str | Path,
    root_assembly: str | Path,
    product_id: str,
    output_path: str | Path,
    active_configuration: Optional[str] = None,
    require_feature_flag: bool = True,
) -> Dict[str, Any]:
    """Write the standalone extractor's canonical occurrence-ID input."""

    if require_feature_flag and not preparation_enabled():
        raise AssemblyKnowledgePreparationError(
            "preparation_disabled",
            "Assembly knowledge preparation is not enabled.",
        )
    adapted = adapt_bridge_package(
        extracted_package_dir,
        source_root=source_root,
        root_assembly=root_assembly,
        product_id=product_id,
        active_configuration=active_configuration,
    )
    source_findings = verify_sources_unchanged(adapted)
    source_errors = [
        item for item in source_findings if item.get("severity") == "error"
    ]
    if source_errors:
        raise AssemblyKnowledgePreparationError(
            "source_changed_during_preparation",
            "; ".join(str(item.get("message")) for item in source_errors[:5]),
        )
    output = write_occurrence_map_tsv(
        adapted.documents["product_structure.json"],
        output_path,
    )
    occurrences = adapted.documents["product_structure.json"].get(
        "occurrences", []
    )
    return {
        "success": True,
        "action": "prepare_occurrence_map",
        "productId": product_id,
        "packageId": adapted.documents["package.json"]["packageId"],
        "sourceRevision": adapted.documents["package.json"][
            "sourceRevision"
        ],
        "outputPath": str(output.resolve()),
        "occurrenceCount": len(occurrences),
        "mappedComponentCount": max(0, len(occurrences) - 1),
        "modelCalls": 0,
    }


def prepare_deterministic_package(
    *,
    training_root: str | Path,
    product_id: str,
    extracted_package_dir: str | Path,
    source_root: str | Path,
    root_assembly: str | Path,
    active_configuration: Optional[str] = None,
    capture_dir: str | Path | None = None,
    assembly_base_name: Optional[str] = None,
    glb_path: str | Path | None = None,
    base_revision: Optional[str] = None,
    require_feature_flag: bool = True,
) -> Dict[str, Any]:
    """Adapt, validate, publish, and source-bind one deterministic package."""

    if require_feature_flag and not preparation_enabled():
        raise AssemblyKnowledgePreparationError(
            "preparation_disabled",
            "Assembly knowledge preparation is not enabled.",
        )
    adapted = adapt_bridge_package(
        extracted_package_dir,
        source_root=source_root,
        root_assembly=root_assembly,
        product_id=product_id,
        active_configuration=active_configuration,
    )
    documents = deepcopy(adapted.documents)
    assets: Dict[str, bytes] = {}
    if capture_dir is not None:
        base_name = (
            assembly_base_name
            or Path(root_assembly).stem
        )
        documents, assets = ingest_solidworks_visuals(
            documents,
            capture_dir=capture_dir,
            assembly_base_name=base_name,
            glb_path=glb_path,
        )
    documents = compile_deterministic_evidence(documents)
    source_findings = verify_sources_unchanged(adapted)
    source_errors = [
        item for item in source_findings if item.get("severity") == "error"
    ]
    if source_errors:
        raise AssemblyKnowledgePreparationError(
            "source_changed_during_preparation",
            "; ".join(str(item.get("message")) for item in source_errors[:5]),
        )
    findings = validate_assembly_knowledge_package(documents)
    errors = [item for item in findings if item.get("severity") == "error"]
    if errors:
        raise AssemblyKnowledgePreparationError(
            "package_validation_failed",
            "; ".join(
                f"{item.get('code')}: {item.get('message')}"
                for item in errors[:8]
            ),
        )
    repository = AssemblyKnowledgeRepository(training_root)
    revision = repository.write(
        documents,
        base_revision=base_revision,
        assets=assets,
    )
    package_id = str(documents["package.json"]["packageId"])
    source_status = repository.bind_source_root(
        product_id,
        package_id,
        source_root,
    )
    published = repository.read(product_id, package_id)
    return {
        "success": True,
        "action": "prepare_deterministic_package",
        "productId": product_id,
        "packageId": package_id,
        "sourceRevision": published["package.json"]["sourceRevision"],
        "packageRevision": revision,
        "readiness": published["package.json"]["readiness"],
        "productionEligible": published["package.json"]["productionEligible"],
        "validation": validation_summary(findings),
        "sourceStatus": source_status,
        "assetCount": len(assets),
        "modelCalls": 0,
    }


def enrich_published_package(
    *,
    training_root: str | Path,
    product_id: str,
    package_id: str,
    provider_name: str,
    model: str,
    provider: Any,
    explicit_approval: bool,
    user_id: str,
    session_id: str,
    idempotency_key: str,
    unknown_pricing_acknowledged: bool = False,
    cache: AssemblyKnowledgeEnrichmentCache | None = None,
    require_feature_flag: bool = True,
) -> Dict[str, Any]:
    """Run one bounded enrichment and CAS-publish its inferred candidates."""

    if require_feature_flag and not ai_enrichment_enabled():
        raise AssemblyKnowledgePreparationError(
            "ai_enrichment_disabled",
            "Assembly knowledge AI enrichment is not enabled.",
        )
    repository = AssemblyKnowledgeRepository(training_root)
    documents = repository.read(product_id, package_id)
    source_status = repository.source_status(product_id, package_id)
    if not source_status["current"]:
        raise AssemblyKnowledgePreparationError(
            "stale_source_revision",
            "Bound CAD sources are unavailable or changed.",
        )
    base_revision = str(documents["package.json"]["packageRevision"])
    plan = plan_enrichment_request(
        documents,
        provider=provider_name,
        model=model,
        prompt_version=ENRICHMENT_PROMPT_VERSION,
    )
    authorization = authorize_enrichment_plan(
        plan,
        explicit_approval=explicit_approval,
        user_id=user_id,
        session_id=session_id,
        idempotency_key=idempotency_key,
        unknown_pricing_acknowledged=unknown_pricing_acknowledged,
    )
    if not authorization.get("authorized"):
        raise AssemblyKnowledgePreparationError(
            "ai_spend_not_authorized",
            str(authorization.get("reason") or "AI spend was not authorized."),
        )
    result = execute_economy_enrichment(
        documents,
        package_dir=repository.package_dir(product_id, package_id),
        budget_plan=plan,
        authorization=authorization,
        provider=provider,
        cache=cache,
    )
    findings = validate_assembly_knowledge_package(result["documents"])
    errors = [item for item in findings if item.get("severity") == "error"]
    if errors:
        raise AssemblyKnowledgePreparationError(
            "enriched_package_validation_failed",
            "; ".join(
                f"{item.get('code')}: {item.get('message')}"
                for item in errors[:8]
            ),
        )
    revision = repository.write(
        result["documents"],
        base_revision=base_revision,
    )
    return {
        "success": True,
        "action": "enrich_published_package",
        "productId": product_id,
        "packageId": package_id,
        "baseRevision": base_revision,
        "packageRevision": revision,
        "sourceRevision": result["documents"]["package.json"][
            "sourceRevision"
        ],
        "readiness": result["documents"]["package.json"]["readiness"],
        "productionEligible": result["documents"]["package.json"][
            "productionEligible"
        ],
        "validation": validation_summary(findings),
        "budget": {
            "policyVersion": plan["policyVersion"],
            "estimatedMaximumCostUsd": plan["estimatedMaximumCostUsd"],
            "pricingConfidence": plan["pricingConfidence"],
            "maximumProviderAttempts": plan["maximumProviderAttempts"],
            "imageCount": len(plan.get("images", [])),
        },
        "usage": deepcopy(result.get("usage") or {}),
        "fromCache": bool(result.get("fromCache")),
    }
