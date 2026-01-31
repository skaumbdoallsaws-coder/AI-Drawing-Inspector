"""Extract inspection-relevant features from SolidWorks JSON data.

SolidWorks JSON structure (from VBA extractor v2):
{
    "identity": {"partNumber": "...", "description": "..."},
    "units": {"docUnitSystem": "IPS", "internalSystem": "SI (meters)"},
    "features": {
        "holeWizardHoles": [
            {"name": "M10x1.5 Tapped Hole1", "diameter": 0.01, "threadSize": "M10x1.5", ...},
            ...
        ],
        "fillets": [
            {"name": "Fillet1", "radius": 0.003175, "edgeCount": 4, ...},
            ...
        ],
        "chamfers": [...]
    }
}

Note: VBA extractor stores all dimensions in SI units (meters).
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import re

# Conversion factor: meters to inches
METERS_TO_INCHES = 39.3701


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

    Handles VBA extractor format with SI units (meters) and nested feature arrays.

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

    def __init__(self):
        """Initialize extractor."""
        pass

    def extract(self, sw_data: Dict[str, Any]) -> List[SwFeature]:
        """
        Extract all inspection-relevant features from SolidWorks JSON.

        Handles two JSON structures:
        1. Nested: features: { holeWizardHoles: [...], fillets: [...] }
        2. Flat: features: [ {type: "HoleWizard", ...}, ... ]

        Auto-detects SI units and converts to inches.

        Args:
            sw_data: Complete SolidWorks JSON data

        Returns:
            List of SwFeature objects
        """
        features = []
        features_section = sw_data.get("features", {})

        # Detect if units are SI (meters) - VBA extractor uses SI internally
        is_si_units = self._detect_si_units(sw_data)

        # Handle nested structure (from VBA extractor)
        if isinstance(features_section, dict):
            # Extract from holeWizardHoles array
            for hole in features_section.get("holeWizardHoles", []):
                extracted = self._extract_hole_wizard(hole, is_si_units)
                if extracted:
                    features.append(extracted)

            # Extract from fillets array
            for fillet in features_section.get("fillets", []):
                extracted = self._extract_fillet(fillet, is_si_units)
                if extracted:
                    features.append(extracted)

            # Extract from chamfers array
            for chamfer in features_section.get("chamfers", []):
                extracted = self._extract_chamfer(chamfer, is_si_units)
                if extracted:
                    features.append(extracted)

        # Handle flat list structure
        elif isinstance(features_section, list):
            for feat in features_section:
                extracted = self._extract_feature(feat, is_si_units)
                if extracted:
                    features.append(extracted)

        # Extract from top-level threads array (separate in some SW exports)
        for thread in sw_data.get("threads", []):
            extracted = self._extract_thread(thread, is_si_units)
            if extracted:
                features.append(extracted)

        # Extract from top-level holeWizard array (if separate)
        for hole in sw_data.get("holeWizard", []):
            extracted = self._extract_hole_wizard(hole, is_si_units)
            if extracted:
                features.append(extracted)

        # Extract from top-level fillets array (if separate)
        for fillet in sw_data.get("fillets", []):
            extracted = self._extract_fillet(fillet, is_si_units)
            if extracted:
                features.append(extracted)

        return features

    def _detect_si_units(self, sw_data: Dict[str, Any]) -> bool:
        """
        Detect if the JSON uses SI units (meters).

        Checks the units section for "SI" or "meters" indicators.
        """
        units = sw_data.get("units", {})

        # Check internalSystem field
        internal = units.get("internalSystem", "")
        if "SI" in internal or "meter" in internal.lower():
            return True

        # Check for explicit SI indicator
        if units.get("docUnitSystem") == "IPS":
            # IPS = Inch-Pound-Second, but internal values may still be SI
            internal = units.get("internalSystem", "")
            if "SI" in internal:
                return True

        # Heuristic: if diameter values are very small (< 0.1), probably meters
        features = sw_data.get("features", {})
        if isinstance(features, dict):
            holes = features.get("holeWizardHoles", [])
            if holes:
                dia = holes[0].get("diameter", 0)
                if 0 < dia < 0.1:  # Less than 0.1 suggests meters
                    return True

        return False

    def _to_inches(self, value: float, is_si: bool) -> float:
        """Convert value to inches if in SI units."""
        if is_si and value is not None:
            return value * METERS_TO_INCHES
        return value

    def _extract_feature(self, feat: Dict[str, Any], is_si: bool) -> Optional[SwFeature]:
        """Extract from generic feature dict."""
        feat_type = feat.get("type", feat.get("featureType", ""))

        if feat_type in self.HOLE_TYPES:
            return self._extract_hole(feat, is_si)
        elif feat_type in self.FILLET_TYPES:
            return self._extract_fillet(feat, is_si)
        elif feat_type in self.CHAMFER_TYPES:
            return self._extract_chamfer(feat, is_si)

        return None

    def _extract_hole(self, feat: Dict[str, Any], is_si: bool) -> Optional[SwFeature]:
        """Extract hole feature."""
        diameter = self._get_dimension(feat, ["diameter", "dia", "d", "size"])
        if diameter is None:
            return None

        diameter = self._to_inches(diameter, is_si)
        depth = self._get_dimension(feat, ["depth", "dp", "length"])
        if depth:
            depth = self._to_inches(depth, is_si)

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

    def _extract_hole_wizard(self, feat: Dict[str, Any], is_si: bool) -> Optional[SwFeature]:
        """
        Extract HoleWizard feature from VBA extractor format.

        VBA format fields:
        - diameter: Hole diameter (in meters if SI)
        - threadSize / fastenerSize: Thread spec like "M10x1.5"
        - isTapped: Boolean indicating if tapped
        - isThrough: Boolean
        - instanceCount: Number of instances
        """
        diameter = self._get_dimension(feat, ["diameter", "holeDiameter", "size"])
        if diameter is None:
            return None

        diameter = self._to_inches(diameter, is_si)

        depth = self._get_dimension(feat, ["depth", "holeDepth"])
        if depth:
            depth = self._to_inches(depth, is_si)

        # Check for through hole
        is_through = (
            feat.get("endCondition") == "Through All" or
            feat.get("endCondition") == "Through" or
            feat.get("isThrough", False)
        )

        # Extract thread info - VBA uses threadSize or fastenerSize
        thread = self._extract_thread_info(feat)

        # Also check isTapped flag
        if not thread and feat.get("isTapped", False):
            # Try to parse from name
            name = feat.get("name", "")
            thread = self._parse_thread_spec(name)

        return SwFeature(
            feature_type="TappedHole" if thread else "Hole",
            diameter_inches=diameter,
            depth_inches=depth if not is_through else None,
            thread=thread,
            quantity=feat.get("instanceCount", feat.get("quantity", 1)),
            location=feat.get("location", feat.get("name", "")),
            raw_data=feat,
        )

    def _extract_thread(self, feat: Dict[str, Any], is_si: bool) -> Optional[SwFeature]:
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
        if diameter:
            diameter = self._to_inches(diameter, is_si)

        depth = self._get_dimension(feat, ["depth", "threadDepth"])
        if depth:
            depth = self._to_inches(depth, is_si)

        return SwFeature(
            feature_type="TappedHole",
            diameter_inches=diameter,
            depth_inches=depth,
            thread=thread_info,
            quantity=feat.get("quantity", 1),
            location=feat.get("location", ""),
            raw_data=feat,
        )

    def _extract_fillet(self, feat: Dict[str, Any], is_si: bool) -> Optional[SwFeature]:
        """Extract fillet feature."""
        radius = self._get_dimension(feat, ["radius", "r", "filletRadius"])
        if radius is None:
            return None

        radius = self._to_inches(radius, is_si)

        return SwFeature(
            feature_type="Fillet",
            radius_inches=radius,
            quantity=feat.get("edgeCount", feat.get("quantity", 1)),
            location=feat.get("location", feat.get("name", "")),
            raw_data=feat,
        )

    def _extract_chamfer(self, feat: Dict[str, Any], is_si: bool) -> Optional[SwFeature]:
        """Extract chamfer feature."""
        distance = self._get_dimension(feat, ["distance", "d1", "chamferDistance"])
        if distance is None:
            return None

        distance = self._to_inches(distance, is_si)

        return SwFeature(
            feature_type="Chamfer",
            radius_inches=distance,  # Using radius field for chamfer distance
            quantity=feat.get("edgeCount", feat.get("quantity", 1)),
            location=feat.get("location", feat.get("name", "")),
            raw_data=feat,
        )

    def _extract_thread_info(self, feat: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract thread information from feature.

        VBA extractor fields:
        - threadSize: "M10x1.5"
        - fastenerSize: "M10x1.5"
        - threadType: Thread specification
        - isTapped: Boolean
        """
        # Try multiple field names used by different exporters
        thread_type = feat.get("threadSize") or feat.get("fastenerSize") or \
                      feat.get("threadType") or feat.get("thread") or feat.get("tapSize")

        if not thread_type:
            return None

        return self._parse_thread_spec(str(thread_type))

    def _parse_thread_spec(self, spec: str) -> Optional[Dict[str, Any]]:
        """Parse thread specification string."""
        if not spec:
            return None

        # Metric: M6x1.0, M10X1.5
        metric_match = re.search(r"M(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)", spec)
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
                    return float(val)
                except (ValueError, TypeError):
                    continue
        return None
