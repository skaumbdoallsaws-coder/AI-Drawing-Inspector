"""Workflow-scoped provider policy for Sage Facility Layout calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


FACILITY_SAGE_PROVIDER_ENV = "INSPECTORPRO_FACILITY_LAYOUT_SAGE_PROVIDER"
FACILITY_SAGE_ANTHROPIC_MODEL_ENV = (
    "INSPECTORPRO_FACILITY_LAYOUT_SAGE_ANTHROPIC_MODEL"
)
FACILITY_SAGE_OPENAI_MODEL_ENV = "INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_MODEL"
FACILITY_SAGE_OPENAI_REASONING_EFFORT_ENV = (
    "INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_REASONING_EFFORT"
)

SHARED_SAGE_PROVIDER_ENV = "INSPECTORPRO_SAGE_PROVIDER"
SHARED_SAGE_ANTHROPIC_MODEL_ENV = "INSPECTORPRO_SAGE_ANTHROPIC_MODEL"
SHARED_SAGE_OPENAI_MODEL_ENV = "INSPECTORPRO_SAGE_OPENAI_MODEL"
SHARED_SAGE_OPENAI_REASONING_EFFORT_ENV = (
    "INSPECTORPRO_SAGE_OPENAI_REASONING_EFFORT"
)

FACILITY_FROZEN_PROVIDER = "anthropic"
FACILITY_FROZEN_MODEL = "claude-sonnet-4-5-20250929"
FACILITY_FROZEN_REASONING_EFFORT: str | None = None
FACILITY_DEFAULT_COMPATIBLE_MODELS = ("claude-sonnet",)
FACILITY_OPENAI_MODEL_DEFAULT = "gpt-5.6-sol"
FACILITY_OPENAI_REASONING_EFFORT_DEFAULT = "medium"
OPENAI_REASONING_EFFORTS = frozenset(
    {"none", "low", "medium", "high", "xhigh", "max"}
)


class FacilityProviderConfigurationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True)
class FacilityProviderConfig:
    provider: str
    model: str
    reasoning_effort: str | None
    provider_source: str
    model_source: str
    reasoning_effort_source: str
    compatibility_fallbacks_used: tuple[str, ...]

    def public_metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "reasoningEffort": self.reasoning_effort,
            "providerSource": self.provider_source,
            "modelSource": self.model_source,
            "reasoningEffortSource": self.reasoning_effort_source,
            "compatibilityFallbacksUsed": list(self.compatibility_fallbacks_used),
            "apiKeyRecorded": False,
        }


def _read(
    environ: Mapping[str, str],
    primary: str,
    fallback: str,
    default: str,
) -> tuple[str, str, tuple[str, ...]]:
    primary_value = str(environ.get(primary) or "").strip()
    if primary_value:
        return primary_value, primary, ()
    fallback_value = str(environ.get(fallback) or "").strip()
    if fallback_value:
        return fallback_value, fallback, (fallback,)
    return default, "built_in_default", ()


def _model_matches(model: str, patterns: Sequence[str]) -> bool:
    normalized = model.strip().casefold()
    for pattern in patterns:
        candidate = str(pattern or "").strip().casefold()
        if candidate and (normalized == candidate or normalized.startswith(candidate + "-")):
            return True
    return False


def assert_facility_provider_configuration(
    config: FacilityProviderConfig,
    *,
    compatible_models: Sequence[str] = FACILITY_DEFAULT_COMPATIBLE_MODELS,
    frozen_provider: str = FACILITY_FROZEN_PROVIDER,
    frozen_model: str = FACILITY_FROZEN_MODEL,
    frozen_reasoning_effort: str | None = FACILITY_FROZEN_REASONING_EFFORT,
) -> None:
    if config.provider != frozen_provider:
        raise FacilityProviderConfigurationError(
            "facility_provider_config_mismatch",
            "Effective Facility provider does not match the KF0-frozen provider.",
            details={
                "effectiveProvider": config.provider,
                "expectedProvider": frozen_provider,
            },
        )
    if config.model != frozen_model:
        raise FacilityProviderConfigurationError(
            "facility_model_mismatch",
            "Effective Facility model does not match the KF0-frozen model.",
            details={
                "effectiveModel": config.model,
                "expectedModel": frozen_model,
            },
        )
    if config.reasoning_effort != frozen_reasoning_effort:
        raise FacilityProviderConfigurationError(
            "facility_provider_config_mismatch",
            "Effective Facility reasoning effort does not match the KF0-frozen configuration.",
            details={
                "effectiveReasoningEffort": config.reasoning_effort,
                "expectedReasoningEffort": frozen_reasoning_effort,
            },
        )
    if not _model_matches(config.model, compatible_models):
        raise FacilityProviderConfigurationError(
            "facility_model_mismatch",
            "Effective Facility model is incompatible with the generation skill.",
            details={
                "effectiveModel": config.model,
                "compatibleModels": list(compatible_models),
            },
        )


def resolve_facility_provider_config(
    environ: Mapping[str, str],
    *,
    compatible_models: Sequence[str] = FACILITY_DEFAULT_COMPATIBLE_MODELS,
    enforce_frozen: bool = True,
) -> FacilityProviderConfig:
    provider, provider_source, provider_fallbacks = _read(
        environ,
        FACILITY_SAGE_PROVIDER_ENV,
        SHARED_SAGE_PROVIDER_ENV,
        FACILITY_FROZEN_PROVIDER,
    )
    provider = provider.casefold()
    if provider not in {"anthropic", "openai"}:
        raise FacilityProviderConfigurationError(
            "facility_provider_config_invalid",
            "Facility Sage provider must be anthropic or openai.",
            details={"environmentVariable": FACILITY_SAGE_PROVIDER_ENV},
        )
    fallbacks = list(provider_fallbacks)
    if provider == "anthropic":
        model, model_source, model_fallbacks = _read(
            environ,
            FACILITY_SAGE_ANTHROPIC_MODEL_ENV,
            SHARED_SAGE_ANTHROPIC_MODEL_ENV,
            FACILITY_FROZEN_MODEL,
        )
        reasoning_effort = None
        effort_source = "not_applicable_for_anthropic"
    else:
        model, model_source, model_fallbacks = _read(
            environ,
            FACILITY_SAGE_OPENAI_MODEL_ENV,
            SHARED_SAGE_OPENAI_MODEL_ENV,
            FACILITY_OPENAI_MODEL_DEFAULT,
        )
        effort, effort_source, effort_fallbacks = _read(
            environ,
            FACILITY_SAGE_OPENAI_REASONING_EFFORT_ENV,
            SHARED_SAGE_OPENAI_REASONING_EFFORT_ENV,
            FACILITY_OPENAI_REASONING_EFFORT_DEFAULT,
        )
        reasoning_effort = effort.casefold()
        if reasoning_effort not in OPENAI_REASONING_EFFORTS:
            raise FacilityProviderConfigurationError(
                "facility_provider_config_invalid",
                "Facility OpenAI reasoning effort is unsupported.",
                details={
                    "environmentVariable": FACILITY_SAGE_OPENAI_REASONING_EFFORT_ENV,
                    "supported": sorted(OPENAI_REASONING_EFFORTS),
                },
            )
        fallbacks.extend(effort_fallbacks)
    fallbacks.extend(model_fallbacks)
    config = FacilityProviderConfig(
        provider=provider,
        model=model,
        reasoning_effort=reasoning_effort,
        provider_source=provider_source,
        model_source=model_source,
        reasoning_effort_source=effort_source,
        compatibility_fallbacks_used=tuple(dict.fromkeys(fallbacks)),
    )
    if enforce_frozen:
        assert_facility_provider_configuration(
            config,
            compatible_models=compatible_models,
        )
    return config


__all__ = [
    "FACILITY_DEFAULT_COMPATIBLE_MODELS",
    "FACILITY_FROZEN_MODEL",
    "FACILITY_FROZEN_PROVIDER",
    "FACILITY_FROZEN_REASONING_EFFORT",
    "FACILITY_SAGE_ANTHROPIC_MODEL_ENV",
    "FACILITY_SAGE_OPENAI_MODEL_ENV",
    "FACILITY_SAGE_OPENAI_REASONING_EFFORT_ENV",
    "FACILITY_SAGE_PROVIDER_ENV",
    "FacilityProviderConfig",
    "FacilityProviderConfigurationError",
    "assert_facility_provider_configuration",
    "resolve_facility_provider_config",
]
