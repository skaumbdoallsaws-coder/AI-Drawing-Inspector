"""Match drawing callouts against SolidWorks features.

Matching strategy:
1. Group features by type (Hole, TappedHole, Fillet, Chamfer)
2. For each drawing callout, find best matching SW feature
3. Use tolerances from config for fuzzy matching
4. Track matched, unmatched, and extra features
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum

from ..config import default_config
from .sw_extractor import SwFeature


class MatchStatus(Enum):
    """Status of a feature match."""
    MATCHED = "matched"           # Drawing callout matches SW feature
    MISSING = "missing"           # SW feature not found on drawing
    EXTRA = "extra"               # Drawing callout not in SW model
    TOLERANCE_FAIL = "tolerance"  # Match found but outside tolerance


@dataclass
class MatchResult:
    """
    Result of matching a single feature.

    Attributes:
        status: Match status (MATCHED, MISSING, EXTRA, TOLERANCE_FAIL)
        drawing_callout: The callout from drawing evidence (None if MISSING)
        sw_feature: The SolidWorks feature (None if EXTRA)
        delta: Difference value for numeric comparisons
        notes: Explanation of match/mismatch
    """
    status: MatchStatus
    drawing_callout: Optional[Dict[str, Any]] = None
    sw_feature: Optional[SwFeature] = None
    delta: Optional[float] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = {
            "status": self.status.value,
            "notes": self.notes,
        }
        if self.drawing_callout:
            d["drawingCallout"] = self.drawing_callout
        if self.sw_feature:
            d["swFeature"] = self.sw_feature.to_dict()
        if self.delta is not None:
            d["delta"] = self.delta
        return d


class FeatureMatcher:
    """
    Match drawing callouts against SolidWorks features.

    Uses configurable tolerances for fuzzy matching:
    - Holes: ±0.015" (default)
    - Threads: ±0.1mm nominal diameter
    - Fillets/Chamfers: ±0.015"

    Usage:
        matcher = FeatureMatcher()
        results = matcher.match_all(drawing_callouts, sw_features)

        matched = [r for r in results if r.status == MatchStatus.MATCHED]
        missing = [r for r in results if r.status == MatchStatus.MISSING]
    """

    def __init__(
        self,
        hole_tolerance: float = None,
        thread_tolerance_mm: float = None,
        fillet_tolerance: float = None,
        chamfer_tolerance: float = None,
    ):
        """
        Initialize matcher with tolerances.

        Args:
            hole_tolerance: Hole diameter tolerance in inches
            thread_tolerance_mm: Thread nominal diameter tolerance in mm
            fillet_tolerance: Fillet radius tolerance in inches
            chamfer_tolerance: Chamfer distance tolerance in inches
        """
        self.hole_tolerance = hole_tolerance or default_config.hole_tolerance_inches
        self.thread_tolerance_mm = thread_tolerance_mm or default_config.thread_tolerance_mm
        self.fillet_tolerance = fillet_tolerance or default_config.fillet_tolerance_inches
        self.chamfer_tolerance = chamfer_tolerance or default_config.chamfer_tolerance_inches

    def match_all(
        self,
        drawing_callouts: List[Dict[str, Any]],
        sw_features: List[SwFeature],
    ) -> List[MatchResult]:
        """
        Match all drawing callouts against SW features.

        Args:
            drawing_callouts: Callouts from drawing evidence
            sw_features: Features extracted from SolidWorks

        Returns:
            List of MatchResult for all features
        """
        results = []
        used_sw_indices = set()
        used_callout_indices = set()

        # Match by type
        for callout_type in ["TappedHole", "Hole", "Fillet", "Chamfer"]:
            type_results, sw_used, callout_used = self._match_by_type(
                drawing_callouts,
                sw_features,
                callout_type,
                used_sw_indices,
                used_callout_indices,
            )
            results.extend(type_results)
            used_sw_indices.update(sw_used)
            used_callout_indices.update(callout_used)

        # Add unmatched SW features as MISSING
        for i, sw_feat in enumerate(sw_features):
            if i not in used_sw_indices:
                results.append(MatchResult(
                    status=MatchStatus.MISSING,
                    sw_feature=sw_feat,
                    notes=f"SW {sw_feat.feature_type} not found on drawing",
                ))

        # Add unmatched drawing callouts as EXTRA
        for i, callout in enumerate(drawing_callouts):
            if i not in used_callout_indices:
                results.append(MatchResult(
                    status=MatchStatus.EXTRA,
                    drawing_callout=callout,
                    notes=f"Drawing callout not in SW model: {callout.get('raw', '')}",
                ))

        return results

    def _match_by_type(
        self,
        drawing_callouts: List[Dict],
        sw_features: List[SwFeature],
        callout_type: str,
        exclude_sw: set,
        exclude_callout: set,
    ) -> Tuple[List[MatchResult], set, set]:
        """Match features of a specific type."""
        results = []
        sw_used = set()
        callout_used = set()

        # Filter to this type
        type_callouts = [
            (i, c) for i, c in enumerate(drawing_callouts)
            if c.get("calloutType") == callout_type and i not in exclude_callout
        ]
        type_sw = [
            (i, f) for i, f in enumerate(sw_features)
            if f.feature_type == callout_type and i not in exclude_sw
        ]

        # Try to match each callout to a SW feature
        for callout_idx, callout in type_callouts:
            best_match = None
            best_delta = float("inf")
            best_sw_idx = None

            for sw_idx, sw_feat in type_sw:
                if sw_idx in sw_used:
                    continue

                match_result, delta = self._try_match(callout, sw_feat, callout_type)
                if match_result and abs(delta) < abs(best_delta):
                    best_match = match_result
                    best_delta = delta
                    best_sw_idx = sw_idx

            if best_match:
                results.append(best_match)
                sw_used.add(best_sw_idx)
                callout_used.add(callout_idx)

        return results, sw_used, callout_used

    def _try_match(
        self,
        callout: Dict[str, Any],
        sw_feat: SwFeature,
        callout_type: str,
    ) -> Tuple[Optional[MatchResult], float]:
        """Try to match a single callout to a SW feature."""

        if callout_type == "TappedHole":
            return self._match_thread(callout, sw_feat)
        elif callout_type == "Hole":
            return self._match_hole(callout, sw_feat)
        elif callout_type == "Fillet":
            return self._match_fillet(callout, sw_feat)
        elif callout_type == "Chamfer":
            return self._match_chamfer(callout, sw_feat)

        return None, float("inf")

    def _match_thread(
        self,
        callout: Dict[str, Any],
        sw_feat: SwFeature,
    ) -> Tuple[Optional[MatchResult], float]:
        """Match tapped hole / thread features."""
        callout_thread = callout.get("thread", {})
        sw_thread = sw_feat.thread or {}

        # Compare nominal diameter (metric)
        callout_nom = callout_thread.get("nominalDiameterMm")
        sw_nom = sw_thread.get("nominalDiameterMm")

        if callout_nom and sw_nom:
            delta = callout_nom - sw_nom
            if abs(delta) <= self.thread_tolerance_mm:
                # Also check pitch if available
                callout_pitch = callout_thread.get("pitch")
                sw_pitch = sw_thread.get("pitch")
                if callout_pitch and sw_pitch and abs(callout_pitch - sw_pitch) > 0.01:
                    return MatchResult(
                        status=MatchStatus.TOLERANCE_FAIL,
                        drawing_callout=callout,
                        sw_feature=sw_feat,
                        delta=callout_pitch - sw_pitch,
                        notes=f"Thread pitch mismatch: drawing={callout_pitch}, SW={sw_pitch}",
                    ), delta

                return MatchResult(
                    status=MatchStatus.MATCHED,
                    drawing_callout=callout,
                    sw_feature=sw_feat,
                    delta=delta,
                    notes=f"Thread match: M{callout_nom}x{callout_pitch or '?'}",
                ), delta

        # Compare TPI for imperial
        callout_tpi = callout_thread.get("tpi")
        sw_tpi = sw_thread.get("tpi")
        if callout_tpi and sw_tpi:
            if callout_tpi == sw_tpi:
                return MatchResult(
                    status=MatchStatus.MATCHED,
                    drawing_callout=callout,
                    sw_feature=sw_feat,
                    delta=0,
                    notes=f"Thread match: {callout_tpi} TPI",
                ), 0
            else:
                return MatchResult(
                    status=MatchStatus.TOLERANCE_FAIL,
                    drawing_callout=callout,
                    sw_feature=sw_feat,
                    delta=callout_tpi - sw_tpi,
                    notes=f"TPI mismatch: drawing={callout_tpi}, SW={sw_tpi}",
                ), abs(callout_tpi - sw_tpi)

        return None, float("inf")

    def _match_hole(
        self,
        callout: Dict[str, Any],
        sw_feat: SwFeature,
    ) -> Tuple[Optional[MatchResult], float]:
        """Match plain hole features."""
        callout_dia = callout.get("diameterInches")
        sw_dia = sw_feat.diameter_inches

        if callout_dia is None or sw_dia is None:
            return None, float("inf")

        delta = callout_dia - sw_dia

        if abs(delta) <= self.hole_tolerance:
            return MatchResult(
                status=MatchStatus.MATCHED,
                drawing_callout=callout,
                sw_feature=sw_feat,
                delta=delta,
                notes=f"Hole match: {callout_dia:.4f}\" (delta={delta:+.4f}\")",
            ), delta
        else:
            # Close but outside tolerance
            if abs(delta) <= self.hole_tolerance * 3:
                return MatchResult(
                    status=MatchStatus.TOLERANCE_FAIL,
                    drawing_callout=callout,
                    sw_feature=sw_feat,
                    delta=delta,
                    notes=f"Hole size mismatch: drawing={callout_dia:.4f}\", SW={sw_dia:.4f}\"",
                ), delta

        return None, float("inf")

    def _match_fillet(
        self,
        callout: Dict[str, Any],
        sw_feat: SwFeature,
    ) -> Tuple[Optional[MatchResult], float]:
        """Match fillet features."""
        callout_radius = callout.get("radiusInches")
        sw_radius = sw_feat.radius_inches

        if callout_radius is None or sw_radius is None:
            return None, float("inf")

        delta = callout_radius - sw_radius

        if abs(delta) <= self.fillet_tolerance:
            return MatchResult(
                status=MatchStatus.MATCHED,
                drawing_callout=callout,
                sw_feature=sw_feat,
                delta=delta,
                notes=f"Fillet match: R{callout_radius:.3f}\"",
            ), delta

        return None, float("inf")

    def _match_chamfer(
        self,
        callout: Dict[str, Any],
        sw_feat: SwFeature,
    ) -> Tuple[Optional[MatchResult], float]:
        """Match chamfer features."""
        callout_dist = callout.get("distance1Inches")
        sw_dist = sw_feat.radius_inches  # Stored in radius field

        if callout_dist is None or sw_dist is None:
            return None, float("inf")

        delta = callout_dist - sw_dist

        if abs(delta) <= self.chamfer_tolerance:
            return MatchResult(
                status=MatchStatus.MATCHED,
                drawing_callout=callout,
                sw_feature=sw_feat,
                delta=delta,
                notes=f"Chamfer match: {callout_dist:.3f}\" x 45°",
            ), delta

        return None, float("inf")
