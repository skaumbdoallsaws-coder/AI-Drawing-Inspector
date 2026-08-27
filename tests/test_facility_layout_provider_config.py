from __future__ import annotations

import pytest

from ai_inspector.facility_layout.provider_config import (
    FACILITY_FROZEN_MODEL,
    FACILITY_SAGE_ANTHROPIC_MODEL_ENV,
    FACILITY_SAGE_OPENAI_REASONING_EFFORT_ENV,
    FACILITY_SAGE_PROVIDER_ENV,
    SHARED_SAGE_ANTHROPIC_MODEL_ENV,
    FacilityProviderConfigurationError,
    resolve_facility_provider_config,
)


def test_facility_provider_defaults_match_kf0_freeze() -> None:
    config = resolve_facility_provider_config({})
    assert config.provider == "anthropic"
    assert config.model == FACILITY_FROZEN_MODEL
    assert config.reasoning_effort is None
    assert config.public_metadata()["apiKeyRecorded"] is False


def test_facility_scoped_value_precedes_shared_compatibility_fallback() -> None:
    config = resolve_facility_provider_config(
        {
            SHARED_SAGE_ANTHROPIC_MODEL_ENV: "claude-opus-5",
            FACILITY_SAGE_ANTHROPIC_MODEL_ENV: FACILITY_FROZEN_MODEL,
        }
    )
    assert config.model == FACILITY_FROZEN_MODEL
    assert config.model_source == FACILITY_SAGE_ANTHROPIC_MODEL_ENV
    assert config.compatibility_fallbacks_used == ()


def test_shared_model_override_fails_instead_of_silently_moving_facility() -> None:
    with pytest.raises(FacilityProviderConfigurationError) as exc:
        resolve_facility_provider_config(
            {SHARED_SAGE_ANTHROPIC_MODEL_ENV: "claude-opus-5"}
        )
    assert exc.value.code == "facility_model_mismatch"


def test_provider_and_reasoning_mismatch_fail_closed() -> None:
    with pytest.raises(FacilityProviderConfigurationError) as provider:
        resolve_facility_provider_config(
            {
                FACILITY_SAGE_PROVIDER_ENV: "openai",
                FACILITY_SAGE_OPENAI_REASONING_EFFORT_ENV: "high",
            }
        )
    assert provider.value.code == "facility_provider_config_mismatch"


def test_skill_compatibility_is_checked_against_effective_model() -> None:
    with pytest.raises(FacilityProviderConfigurationError) as exc:
        resolve_facility_provider_config({}, compatible_models=("gpt",))
    assert exc.value.code == "facility_model_mismatch"


def test_invalid_openai_reasoning_effort_is_rejected_even_without_freeze() -> None:
    with pytest.raises(FacilityProviderConfigurationError) as exc:
        resolve_facility_provider_config(
            {
                FACILITY_SAGE_PROVIDER_ENV: "openai",
                FACILITY_SAGE_OPENAI_REASONING_EFFORT_ENV: "extreme",
            },
            enforce_frozen=False,
        )
    assert exc.value.code == "facility_provider_config_invalid"
