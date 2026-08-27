"""Fail-closed runtime feature policy for Facility Layout rollout."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping

from .errors import FacilityAuthorizationError


FACILITY_LAYOUT_FEATURE_FLAGS: tuple[str, ...] = (
    "INSPECTORPRO_FACILITY_LAYOUT_VIEWER_V2",
    "INSPECTORPRO_INDUSTRIAL_ASSET_LIBRARY",
    "INSPECTORPRO_FACILITY_LAYOUT_MANUAL_EDIT",
    "INSPECTORPRO_FACILITY_LAYOUT_CONSTRAINTS",
    "INSPECTORPRO_FACILITY_LAYOUT_ROUTING",
    "INSPECTORPRO_FACILITY_LAYOUT_AGENT_PREVIEW",
    "INSPECTORPRO_FACILITY_LAYOUT_AGENT_WRITE",
)

FACILITY_LAYOUT_CAPABILITY_FLAGS: Mapping[str, str] = {
    "viewer_v2": FACILITY_LAYOUT_FEATURE_FLAGS[0],
    "asset_library": FACILITY_LAYOUT_FEATURE_FLAGS[1],
    "manual_edit": FACILITY_LAYOUT_FEATURE_FLAGS[2],
    "constraints": FACILITY_LAYOUT_FEATURE_FLAGS[3],
    "routing": FACILITY_LAYOUT_FEATURE_FLAGS[4],
    "agent_preview": FACILITY_LAYOUT_FEATURE_FLAGS[5],
    "agent_write": FACILITY_LAYOUT_FEATURE_FLAGS[6],
}

FACILITY_LAYOUT_CAPABILITY_DEPENDENCIES: Mapping[str, tuple[str, ...]] = {
    "viewer_v2": (),
    "asset_library": ("viewer_v2",),
    "manual_edit": ("asset_library",),
    "constraints": ("manual_edit",),
    "routing": ("constraints",),
    "agent_preview": ("routing",),
    "agent_write": ("agent_preview",),
}

# Compatibility aliases for the frozen KF0 verifier and existing local callers.
_CAPABILITY_FLAGS = FACILITY_LAYOUT_CAPABILITY_FLAGS
_DEPENDENCIES = FACILITY_LAYOUT_CAPABILITY_DEPENDENCIES

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})


@dataclass(frozen=True)
class FacilityLayoutFeatureFlags:
    """Immutable startup snapshot of the staged Facility Layout rollout."""

    values: tuple[tuple[str, bool], ...]
    invalid: tuple[str, ...] = ()

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "FacilityLayoutFeatureFlags":
        source = os.environ if environ is None else environ
        values: list[tuple[str, bool]] = []
        invalid: list[str] = []
        for name in FACILITY_LAYOUT_FEATURE_FLAGS:
            raw = str(source.get(name, "") or "").strip().lower()
            if raw in _TRUE_VALUES:
                enabled = True
            elif raw in _FALSE_VALUES:
                enabled = False
            else:
                enabled = False
                invalid.append(name)
            values.append((name, enabled))
        return cls(tuple(values), tuple(sorted(invalid)))

    @classmethod
    def all_enabled(cls) -> "FacilityLayoutFeatureFlags":
        """Compatibility policy for isolated domain tests and adapters."""

        return cls(tuple((name, True) for name in FACILITY_LAYOUT_FEATURE_FLAGS))

    def configured(self, flag_name: str) -> bool:
        return dict(self.values).get(flag_name, False)

    def enabled(self, capability: str) -> bool:
        if capability not in FACILITY_LAYOUT_CAPABILITY_FLAGS:
            raise ValueError(
                f"unknown Facility Layout capability: {capability}"
            )
        if not self.configured(FACILITY_LAYOUT_CAPABILITY_FLAGS[capability]):
            return False
        return all(
            self.enabled(item)
            for item in FACILITY_LAYOUT_CAPABILITY_DEPENDENCIES[capability]
        )

    def require(self, capability: str) -> None:
        if self.enabled(capability):
            return
        flag_name = FACILITY_LAYOUT_CAPABILITY_FLAGS.get(capability)
        if flag_name is None:
            raise ValueError(
                f"unknown Facility Layout capability: {capability}"
            )
        raise FacilityAuthorizationError(
            "facility_feature_disabled",
            "This Facility Layout capability is disabled.",
            details={
                "capability": capability,
                "featureFlag": flag_name,
            },
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "configured": {
                name: self.configured(name)
                for name in FACILITY_LAYOUT_FEATURE_FLAGS
            },
            "effective": {
                capability: self.enabled(capability)
                for capability in FACILITY_LAYOUT_CAPABILITY_FLAGS
            },
            "invalid": list(self.invalid),
        }


__all__ = [
    "FACILITY_LAYOUT_CAPABILITY_DEPENDENCIES",
    "FACILITY_LAYOUT_CAPABILITY_FLAGS",
    "FACILITY_LAYOUT_FEATURE_FLAGS",
    "FacilityLayoutFeatureFlags",
]
