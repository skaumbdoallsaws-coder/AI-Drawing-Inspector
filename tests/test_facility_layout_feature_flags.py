from __future__ import annotations

from itertools import combinations

import pytest

from ai_inspector.facility_layout.errors import FacilityAuthorizationError
from ai_inspector.facility_layout.feature_flags import (
    FACILITY_ALL_FEATURE_FLAGS,
    FACILITY_DESIGN_LOOP_CAPABILITY_FLAGS,
    FACILITY_DESIGN_LOOP_FEATURE_FLAGS,
    FACILITY_LAYOUT_FEATURE_FLAGS,
    FACILITY_NAVIGATION_CAPABILITY_FLAGS,
    FACILITY_NAVIGATION_FEATURE_FLAGS,
    FacilityLayoutFeatureFlags,
)


def _environment(*enabled: str) -> dict[str, str]:
    selected = set(enabled)
    return {
        name: "1" if name in selected else "0"
        for name in FACILITY_LAYOUT_FEATURE_FLAGS
    }


def test_default_policy_is_fail_closed():
    flags = FacilityLayoutFeatureFlags.from_environment({})
    assert not any(flags.to_dict()["configured"].values())
    assert not any(flags.to_dict()["effective"].values())


def test_dependency_chain_keeps_write_disabled_without_preview():
    viewer, _, _, constraints, _, _, write = (
        FACILITY_LAYOUT_FEATURE_FLAGS
    )
    flags = FacilityLayoutFeatureFlags.from_environment(
        _environment(viewer, constraints, write)
    )
    assert flags.configured(write)
    assert flags.enabled("agent_preview") is False
    assert flags.enabled("agent_write") is False


def test_every_out_of_order_flag_combination_fails_closed():
    capabilities = (
        "viewer_v2",
        "asset_library",
        "manual_edit",
        "constraints",
        "routing",
        "agent_preview",
        "agent_write",
    )
    for count in range(len(FACILITY_LAYOUT_FEATURE_FLAGS) + 1):
        for indexes in combinations(
            range(len(FACILITY_LAYOUT_FEATURE_FLAGS)),
            count,
        ):
            enabled_indexes = set(indexes)
            flags = FacilityLayoutFeatureFlags.from_environment(
                _environment(
                    *(
                        flag
                        for index, flag in enumerate(
                            FACILITY_LAYOUT_FEATURE_FLAGS
                        )
                        if index in enabled_indexes
                    )
                )
            )
            for capability_index, capability in enumerate(capabilities):
                expected = all(
                    prerequisite_index in enabled_indexes
                    for prerequisite_index in range(capability_index + 1)
                )
                assert flags.enabled(capability) is expected, (
                    capability,
                    sorted(enabled_indexes),
                )


@pytest.mark.parametrize(
    ("capability", "enabled_count"),
    (
        ("asset_library", 0),
        ("manual_edit", 1),
        ("constraints", 2),
        ("routing", 3),
        ("agent_preview", 4),
        ("agent_write", 5),
    ),
)
def test_later_stage_cannot_skip_any_preceding_stage(
    capability: str,
    enabled_count: int,
):
    enabled = list(FACILITY_LAYOUT_FEATURE_FLAGS[:enabled_count])
    enabled.append(FACILITY_LAYOUT_FEATURE_FLAGS[enabled_count + 1])
    flags = FacilityLayoutFeatureFlags.from_environment(
        _environment(*enabled)
    )
    assert flags.enabled(capability) is False


def test_invalid_values_fail_closed_and_remain_observable():
    viewer = FACILITY_LAYOUT_FEATURE_FLAGS[0]
    flags = FacilityLayoutFeatureFlags.from_environment(
        {viewer: "sometimes"}
    )
    assert flags.enabled("viewer_v2") is False
    assert flags.invalid == (viewer,)


def test_require_returns_stable_flag_and_capability_details():
    flags = FacilityLayoutFeatureFlags.from_environment({})
    with pytest.raises(FacilityAuthorizationError) as captured:
        flags.require("manual_edit")
    assert captured.value.code == "facility_feature_disabled"
    assert captured.value.details == {
        "capability": "manual_edit",
        "featureFlag": FACILITY_LAYOUT_FEATURE_FLAGS[2],
    }


def test_all_enabled_policy_satisfies_every_effective_capability():
    flags = FacilityLayoutFeatureFlags.all_enabled()
    assert all(flags.to_dict()["effective"].values())


def test_navigation_rollout_is_ordered_and_requires_general_prerequisites():
    base = set(FACILITY_LAYOUT_FEATURE_FLAGS)
    for index, flag in enumerate(FACILITY_NAVIGATION_FEATURE_FLAGS):
        enabled = base | set(FACILITY_NAVIGATION_FEATURE_FLAGS[: index + 1])
        flags = FacilityLayoutFeatureFlags.from_environment({
            item: "1" if item in enabled else "0"
            for item in FACILITY_ALL_FEATURE_FLAGS
        })
        capability = tuple(FACILITY_NAVIGATION_CAPABILITY_FLAGS)[index]
        assert flags.enabled(capability) is True
        for later in tuple(FACILITY_NAVIGATION_CAPABILITY_FLAGS)[index + 1:]:
            assert flags.enabled(later) is False


def test_navigation_sage_write_fails_closed_without_agent_write():
    enabled = set(FACILITY_ALL_FEATURE_FLAGS)
    enabled.remove("INSPECTORPRO_FACILITY_LAYOUT_AGENT_WRITE")
    flags = FacilityLayoutFeatureFlags.from_environment({
        item: "1" if item in enabled else "0"
        for item in FACILITY_ALL_FEATURE_FLAGS
    })
    assert flags.enabled("navigation_multi_actor") is True
    assert flags.enabled("navigation_sage_write") is False


def test_design_loop_rollout_is_ordered_and_requires_general_prerequisites():
    base = set(FACILITY_LAYOUT_FEATURE_FLAGS)
    base.update(FACILITY_NAVIGATION_FEATURE_FLAGS)
    for index, flag in enumerate(FACILITY_DESIGN_LOOP_FEATURE_FLAGS):
        enabled = base | set(FACILITY_DESIGN_LOOP_FEATURE_FLAGS[: index + 1])
        flags = FacilityLayoutFeatureFlags.from_environment({
            item: "1" if item in enabled else "0"
            for item in FACILITY_ALL_FEATURE_FLAGS
        })
        capability = tuple(FACILITY_DESIGN_LOOP_CAPABILITY_FLAGS)[index]
        assert flags.enabled(capability) is True


def test_design_loop_apply_fails_closed_without_agent_write():
    enabled = set(FACILITY_ALL_FEATURE_FLAGS)
    enabled.remove("INSPECTORPRO_FACILITY_LAYOUT_AGENT_WRITE")
    flags = FacilityLayoutFeatureFlags.from_environment({
        item: "1" if item in enabled else "0"
        for item in FACILITY_ALL_FEATURE_FLAGS
    })
    assert flags.enabled("design_loop_preview") is True
    assert flags.enabled("design_loop_apply") is False
    assert flags.enabled("design_loop_lab") is True
    assert flags.enabled("design_loop_sage") is True
