"""Extract inspection-relevant features from SolidWorks JSON data.

SolidWorks JSON structure (from VBA extractor):
{
    "identity": {"partNumber": "...", "description": "..."},
    "features": [
        {"type": "HoleWizard", "diameter": 0.5, "depth": 1.0, ...},
        {"type": "Fillet", "radius": 0.125, ...},
        ...
    ],
    "threads": [
        {"type": "M6x1.0", "depth": 10.0, "location": "..."},
        ...
    ]
}
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import re


@dataclass
class SwFeature:
    """
    A feature extracted from SolidWorks JSON for comparison.

    Attributes:
        feature_type: Canonical type (Hole, TappedHole, Fillet, Chamfer, etc.)
        diameter_inches: Hole diameter in inches (None for non-holes)
        depth_inches: Hole/feature depth in inches
        radius_inches: Fillet/chamfer radius in inches
        thread: Thread specification dict (for tapped holes)
        quantity: Number of instances
        location: Feature location description
        raw_data: Original SolidWorks feature data
        source: Always "solidworks"
    """

    feature_type: str
    diameter_inches: Optional[float] = None
    depth_inches: Optional[float] = None
    radius_inches: Optional[float] = None
    thread: Optional[Dict[str, Any]] = None
    quantity: int = 1
    location: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)
    source: str = "solidworks"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = {
            "featureType": self.feature_type,
            "quantity": self.quantity,
            "source": self.source,
        }
        if self.diameter_inches is not None:
            d["diameterInches"] = self.diameter_inches
        if self.depth_inches is not None:
            d["depthInches"] = self.depth_inches
        if self.radius_inches is not None:
            d["radiusInches"] = self.radius_inches
        if self.thread:
            d["thread"] = self.thread
        if self.location:
            d["location"] = self.location
        return d


class SwFeatureExtractor:
    """
    Extract inspection-relevant features from SolidWorks JSON.

    Extracts:
    - Holes (HoleWizard, Cut-Extrude with circular profile)
    - Tapped holes (threads)
    - Fillets
    - Chamfers

    Usage:
        extractor = SwFeatureExtractor()
        features = extractor.extract(sw_json_data)

        for f in features:
            print(f"{f.feature_type}: {f.diameter_inches}")
    """

    # SolidWorks feature type mappings
    HOLE_TYPES = ["HoleWizard", "Hole", "Cut-Extrude", "CutExtrude"]
    FILLET_TYPES = ["Fillet", "ConstRadiusFillet", "VariableRadiusFillet"]
    CHAMFER_TYPES = ["Chamfer"]

    def __init__(self, unit_conversion: float = 1.0):
        """
        Initialize extractor.

        Args:
            unit_conversion: Multiplier to convert SW units to inches
                             (1.0 if SW exports in inches, 25.4 if mm)
        """
        self.unit_conversion = unit_conversion

    def extract(self, sw_data: Dict[str, Any]) -> List[SwFeature]:
        """
        Extract all inspection-relevant features from SolidWorks JSON.

        Args:
            sw_data: Complete SolidWorks JSON data

        Returns:
            List of SwFeature objects
        """
        features = []

        # Extract from features array
        for feat in sw_data.get("features", []):
            extracted = self._extract_feature(feat)
            if extracted:
                features.append(extracted)

        # Extract from threads array (separate in some SW exports)
        for thread in sw_data.get("threads", []):
            extracted = self._extract_thread(thread)
            if extracted:
                features.append(extracted)

        # Extract from holeWizard array (if separate)
        for hole in sw_data.get("holeWizard", []):
            extracted = self._extract_hole_wizard(hole)
            if extracted:
                features.append(extracted)

        # Extract from fillets array (if separate)
        for fillet in sw_data.get("fillets", []):
            extracted = self._extract_fillet(fillet)
            if extracted:
                features.append(extracted)

        return features

    def _extract_feature(self, feat: Dict[str, Any]) -> Optional[SwFeature]:
        """Extract from generic feature dict."""
        feat_type = feat.get("type", feat.get("featureType", ""))

        if feat_type in self.HOLE_TYPES:
            return self._extract_hole(feat)
        elif feat_type in self.FILLET_TYPES:
            return self._extract_fillet(feat)
        elif feat_type in self.CHAMFER_TYPES:
            return self._extract_chamfer(feat)

        return None

    def _extract_hole(self, feat: Dict[str, Any]) -> Optional[SwFeature]:
        """Extract hole feature."""
        diameter = self._get_dimension(feat, ["diameter", "dia", "d", "size"])
        if diameter is None:
            return None

        depth = self._get_dimension(feat, ["depth", "dp", "length"])
        is_through = feat.get("isThrough", feat.get("thru", False))

        # Check for thread info
        thread = self._extract_thread_info(feat)

        return SwFeature(
            feature_type="TappedHole" if thread else "Hole",
            diameter_inches=diameter,
            depth_inches=depth if not is_through else None,
            thread=thread,
            quantity=feat.get("quantity", feat.get("count", 1)),
            location=feat.get("location", ""),
            raw_data=feat,
        )

    def _extract_hole_wizard(self, feat: Dict[str, Any]) -> Optional[SwFeature]:
        """Extract HoleWizard feature (often has more detail)."""
        diameter = self._get_dimension(feat, ["holeDiameter", "diameter", "size"])
        if diameter is None:
            return None

        depth = self._get_dimension(feat, ["holeDepth", "depth"])
        is_through = feat.get("endCondition") == "Through" or feat.get("isThrough", False)

        # Thread info
        thread = self._extract_thread_info(feat)

        # Counterbore/Countersink info
        cbore_dia = self._get_dimension(feat, ["cboreDiameter", "counterboreDia"])
        cbore_depth = self._get_dimension(feat, ["cboreDepth", "counterboreDepth"])

        return SwFeature(
            feature_type="TappedHole" if thread else "Hole",
            diameter_inches=diameter,
            depth_inches=depth if not is_through else None,
            thread=thread,
            quantity=feat.get("quantity", feat.get("instanceCount", 1)),
            location=feat.get("location", ""),
            raw_data=feat,
        )

    def _extract_thread(self, feat: Dict[str, Any]) -> Optional[SwFeature]:
        """Extract thread from threads array."""
        thread_type = feat.get("type", feat.get("threadType", ""))

        # Parse thread specification
        thread_info = self._parse_thread_spec(thread_type)
        if not thread_info:
            thread_info = {
                "raw": thread_type,
                "standard": "Unknown",
            }

        diameter = self._get_dimension(feat, ["diameter", "majorDiameter", "nominalDia"])
        depth = self._get_dimension(feat, ["depth", "threadDepth"])

        return SwFeature(
            feature_type="TappedHole",
            diameter_inches=diameter,
            depth_inches=depth,
            thread=thread_info,
            quantity=feat.get("quantity", 1),
            location=feat.get("location", ""),
            raw_data=feat,
        )

    def _extract_fillet(self, feat: Dict[str, Any]) -> Optional[SwFeature]:
        """Extract fillet feature."""
        radius = self._get_dimension(feat, ["radius", "r", "filletRadius"])
        if radius is None:
            return None

        return SwFeature(
            feature_type="Fillet",
            radius_inches=radius,
            quantity=feat.get("quantity", feat.get("edgeCount", 1)),
            location=feat.get("location", feat.get("edges", "")),
            raw_data=feat,
        )

    def _extract_chamfer(self, feat: Dict[str, Any]) -> Optional[SwFeature]:
        """Extract chamfer feature."""
        distance = self._get_dimension(feat, ["distance", "d1", "chamferDistance"])
        if distance is None:
            return None

        return SwFeature(
            feature_type="Chamfer",
            radius_inches=distance,  # Using radius field for chamfer distance
            quantity=feat.get("quantity", feat.get("edgeCount", 1)),
            location=feat.get("location", ""),
            raw_data=feat,
        )

    def _extract_thread_info(self, feat: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract thread information from feature."""
        thread_type = feat.get("threadType", feat.get("thread", feat.get("tapSize", "")))
        if not thread_type:
            return None

        return self._parse_thread_spec(str(thread_type))

    def _parse_thread_spec(self, spec: str) -> Optional[Dict[str, Any]]:
        """Parse thread specification string."""
        if not spec:
            return None

        # Metric: M6x1.0, M10X1.5
        metric_match = re.match(r"M(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)", spec)
        if metric_match:
            return {
                "standard": "Metric",
                "nominalDiameterMm": float(metric_match.group(1)),
                "pitch": float(metric_match.group(2)),
                "raw": spec,
            }

        # Imperial fraction: 1/2-13, 3/8-16
        imperial_match = re.match(r"(\d+/\d+)\s*-\s*(\d+)", spec)
        if imperial_match:
            return {
                "standard": "Imperial",
                "fraction": imperial_match.group(1),
                "tpi": int(imperial_match.group(2)),
                "raw": spec,
            }

        # Decimal imperial: .500-13, 0.375-16
        decimal_match = re.match(r"(\.?\d+\.?\d*)\s*-\s*(\d+)\s*(UNC|UNF)?", spec)
        if decimal_match:
            return {
                "standard": "Unified",
                "nominalDiameterInches": float(decimal_match.group(1)),
                "tpi": int(decimal_match.group(2)),
                "threadClass": decimal_match.group(3) or "UNC",
                "raw": spec,
            }

        return {"standard": "Unknown", "raw": spec}

    def _get_dimension(self, feat: Dict[str, Any], keys: List[str]) -> Optional[float]:
        """Get dimension value from feature, trying multiple key names."""
        for key in keys:
            val = feat.get(key)
            if val is not None:
                try:
                    return float(val) * self.unit_conversion
                except (ValueError, TypeError):
                    continue
        return None
