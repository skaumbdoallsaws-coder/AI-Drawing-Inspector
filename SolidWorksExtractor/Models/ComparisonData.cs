using System;
using System.Collections.Generic;

namespace SolidWorksExtractor.Models
{
    /// <summary>
    /// Comparison-ready data structure for drawing completeness checks.
    /// Organized for LLM to compare model truth vs drawing claims.
    /// </summary>
    public class ComparisonReadyData
    {
        public string SchemaVersion { get; set; } = "1.0.0";
        public DateTime ExtractedAt { get; set; }

        /// <summary>All holes grouped logically for pattern/instance checking</summary>
        public List<HoleGroup> HoleGroups { get; set; } = new List<HoleGroup>();

        /// <summary>Individual holes flattened for simple lookup</summary>
        public List<HoleInstance> AllHoles { get; set; } = new List<HoleInstance>();

        /// <summary>Slots (drawings often dimension differently than circles)</summary>
        public List<SlotInstance> Slots { get; set; } = new List<SlotInstance>();

        /// <summary>Sheet metal summary for bend/thickness callouts</summary>
        public SheetMetalSummary SheetMetal { get; set; }

        /// <summary>Required callouts derived from features</summary>
        public List<RequiredCallout> RequiredCallouts { get; set; } = new List<RequiredCallout>();

        /// <summary>Summary statistics for quick validation</summary>
        public ComparisonSummary Summary { get; set; } = new ComparisonSummary();
    }

    /// <summary>
    /// A group of similar holes (same size, type) that may be in a pattern
    /// </summary>
    public class HoleGroup
    {
        public string GroupId { get; set; }

        /// <summary>Canonical description for matching: "M8x1.25 THRU", "ø10.5mm x 15mm DEEP"</summary>
        public string Canonical { get; set; }

        /// <summary>Hole type: Through, Blind, Tapped, Counterbore, Countersink</summary>
        public string HoleType { get; set; }

        // === Diameter fields (separate intent vs ground truth) ===
        // Example for M6x1.0 tapped hole:
        //   NominalDiameter = 6.0mm (thread major diameter, the "M6")
        //   TapDrillDiameter = 5.0mm (from feature, the pilot hole size before threading)
        //   MeasuredDiameter = 5.0mm (from geometry, should match tap drill for cosmetic threads)

        /// <summary>
        /// Nominal diameter from feature definition.
        /// - For tapped holes: thread major diameter (e.g., M6 = 6.0mm)
        /// - For non-tapped: drill/hole size from feature
        /// </summary>
        public DimensionValue NominalDiameter { get; set; }

        /// <summary>
        /// Tap drill / pilot diameter from feature (tapped holes only).
        /// This is the actual hole size before threading - smaller than nominal.
        /// E.g., M6x1.0 has nominal=6mm but tap drill≈5mm.
        /// </summary>
        public DimensionValue TapDrillDiameter { get; set; }

        /// <summary>
        /// Measured diameter from geometry ground truth.
        /// This is what the cylindrical face actually measures.
        /// - For cosmetic threads: matches TapDrillDiameter (thread not modeled)
        /// - For cut threads: may differ slightly due to thread geometry
        /// </summary>
        public DimensionValue MeasuredDiameter { get; set; }

        /// <summary>Legacy: Diameter with units (use NominalDiameter/MeasuredDiameter instead)</summary>
        [Obsolete("Use NominalDiameter or MeasuredDiameter")]
        public DimensionValue Diameter { get; set; }

        /// <summary>Depth (null for through holes)</summary>
        public DimensionValue Depth { get; set; }

        /// <summary>Thread specification if tapped</summary>
        public ThreadSpec Thread { get; set; }

        /// <summary>Counterbore specification if applicable</summary>
        public CounterboreSpec Counterbore { get; set; }

        /// <summary>Countersink specification if applicable</summary>
        public CountersinkSpec Countersink { get; set; }

        /// <summary>Number of instances in this group</summary>
        public int Count { get; set; }

        /// <summary>Individual hole instances with locations</summary>
        public List<HoleInstance> Instances { get; set; } = new List<HoleInstance>();

        /// <summary>Pattern info if holes are patterned</summary>
        public PatternInfo Pattern { get; set; }

        /// <summary>Source: "HoleWizard", "Cut", "GeometryOnly"</summary>
        public string Source { get; set; }

        /// <summary>Confidence: "High" (feature+geometry match), "Medium" (feature only), "Low" (geometry only)</summary>
        public string Confidence { get; set; }

        /// <summary>Reconciliation notes (e.g., "matched by center within 0.1mm")</summary>
        public string ReconciliationNote { get; set; }
    }

    /// <summary>
    /// Single hole instance with location
    /// </summary>
    public class HoleInstance
    {
        public string InstanceId { get; set; }
        public string GroupId { get; set; }

        /// <summary>Center point from geometry model (raw coordinates from cylinder axis)</summary>
        public Point3D ModelCenter { get; set; }

        /// <summary>Center point normalized to entry face (Z projected to face plane for consistent matching)</summary>
        public Point3D FaceEntryCenter { get; set; }

        /// <summary>Legacy: Center point of hole entry (use ModelCenter or FaceEntryCenter)</summary>
        public Point3D Center { get; set; }

        /// <summary>Hole axis direction (normalized)</summary>
        public Vector3D Axis { get; set; }

        /// <summary>Which face the hole starts on ("+X", "-Y", "+Z", etc.)</summary>
        public string StartFace { get; set; }

        /// <summary>Diameter from geometry (ground truth)</summary>
        public DimensionValue MeasuredDiameter { get; set; }

        /// <summary>Depth from geometry (ground truth)</summary>
        public DimensionValue MeasuredDepth { get; set; }

        /// <summary>Is this a through hole based on geometry?</summary>
        public bool IsThrough { get; set; }

        /// <summary>Feature name that created this hole (if known)</summary>
        public string FeatureName { get; set; }

        /// <summary>Instance number within pattern (1-based)</summary>
        public int PatternInstance { get; set; }

        // === Thread metadata (propagated from group for per-instance access) ===

        /// <summary>
        /// Does the FEATURE indicate this is a tapped hole? (from HoleWizard intent)
        /// True if the creating feature is a tapped hole, regardless of whether thread geometry exists.
        /// </summary>
        public bool HasThreadIntent { get; set; }

        /// <summary>Thread callout if threaded (e.g., "M6x1.0", "M5x0.8")</summary>
        public string ThreadCallout { get; set; }

        /// <summary>
        /// Is thread geometry actually modeled (helical edges present)?
        /// False for cosmetic threads, true for cut/modeled threads.
        /// Most tapped holes use cosmetic threads (ThreadModeled=false) but still have HasThreadIntent=true.
        /// </summary>
        public bool ThreadModeled { get; set; }
    }

    /// <summary>
    /// Thread specification for tapped holes
    /// </summary>
    public class ThreadSpec
    {
        /// <summary>Full thread callout: "M8x1.25", "#10-24 UNC"</summary>
        public string Callout { get; set; }

        /// <summary>Thread standard: "Metric", "UNC", "UNF", etc.</summary>
        public string Standard { get; set; }

        /// <summary>Nominal/major diameter of thread (e.g., M6 = 6mm)</summary>
        public DimensionValue NominalDiameter { get; set; }

        /// <summary>Tap drill diameter (hole size before threading, smaller than nominal)</summary>
        public DimensionValue TapDrillDiameter { get; set; }

        /// <summary>Pitch (for metric) or TPI (for unified)</summary>
        public double Pitch { get; set; }

        /// <summary>Thread class: "6H", "2B", etc.</summary>
        public string ThreadClass { get; set; }

        /// <summary>Thread depth (may differ from hole depth)</summary>
        public DimensionValue ThreadDepth { get; set; }
    }

    /// <summary>
    /// Counterbore specification
    /// </summary>
    public class CounterboreSpec
    {
        public DimensionValue Diameter { get; set; }
        public DimensionValue Depth { get; set; }

        /// <summary>Callout: "C'BORE ø12mm x 6mm DEEP"</summary>
        public string Callout { get; set; }
    }

    /// <summary>
    /// Countersink specification
    /// </summary>
    public class CountersinkSpec
    {
        public DimensionValue Diameter { get; set; }
        public DimensionValue Angle { get; set; }

        /// <summary>Callout: "C'SINK ø14mm x 82°"</summary>
        public string Callout { get; set; }
    }

    /// <summary>
    /// Pattern information for grouped features
    /// </summary>
    public class PatternInfo
    {
        public string PatternType { get; set; }  // Linear, Circular, Mirror, Sketch
        public string PatternName { get; set; }  // Feature name that created the pattern

        // Total instances (including seed)
        public int TotalInstances { get; set; }

        // Linear pattern
        public int Direction1Count { get; set; }
        public DimensionValue Direction1Spacing { get; set; }
        public Vector3D Direction1Vector { get; set; }
        public int Direction2Count { get; set; }
        public DimensionValue Direction2Spacing { get; set; }
        public Vector3D Direction2Vector { get; set; }

        // Circular pattern
        public DimensionValue TotalAngle { get; set; }
        public DimensionValue AnglePerInstance { get; set; }
        public bool EqualSpacing { get; set; }
        public Point3D AxisLocation { get; set; }
        public Vector3D AxisDirection { get; set; }

        // Bolt circle (derived for circular patterns)
        public DimensionValue BoltCircleDiameter { get; set; }
        public DimensionValue BoltCircleRadius { get; set; }

        // Explicit instance centers for direct comparison
        public List<PatternInstanceCenter> InstanceCenters { get; set; } = new List<PatternInstanceCenter>();

        /// <summary>Canonical description: "4X ON ø50mm B.C.", "3x4 GRID @ 10mm x 15mm"</summary>
        public string Canonical { get; set; }

        // === Pattern descriptors inferred from geometry ===

        /// <summary>Detected arrangement: "Linear", "Circular", "Grid", "Irregular", "Single"</summary>
        public string InferredArrangement { get; set; }

        /// <summary>Best-fit line direction if holes appear collinear (direction vector)</summary>
        public Vector3D BestFitLineDirection { get; set; }

        /// <summary>Collinearity R² value (1.0 = perfectly collinear, 0 = random)</summary>
        public double? CollinearityFit { get; set; }

        /// <summary>Estimated pitch/spacing between adjacent holes (if regular)</summary>
        public DimensionValue EstimatedPitch { get; set; }

        /// <summary>Is pitch uniform across all holes? (variation < 5%)</summary>
        public bool PitchIsUniform { get; set; }

        /// <summary>Symmetry axis if detected (about X, Y, or Z axis)</summary>
        public string SymmetryAxis { get; set; }

        /// <summary>Symmetry plane offset from origin (if symmetry detected)</summary>
        public DimensionValue SymmetryPlaneOffset { get; set; }

        /// <summary>Confidence of the inferred pattern: "High", "Medium", "Low"</summary>
        public string InferenceConfidence { get; set; }
    }

    /// <summary>
    /// Single pattern instance center for comparison
    /// </summary>
    public class PatternInstanceCenter
    {
        /// <summary>1-based instance number</summary>
        public int InstanceNumber { get; set; }

        /// <summary>Center point with units</summary>
        public Point3D Center { get; set; }

        /// <summary>For circular: angle from first instance</summary>
        public DimensionValue Angle { get; set; }

        /// <summary>Is this instance suppressed/skipped?</summary>
        public bool IsSkipped { get; set; }
    }

    /// <summary>
    /// Slot instance (rectangular with rounded ends)
    /// </summary>
    public class SlotInstance
    {
        public string SlotId { get; set; }

        /// <summary>Overall length (center to center of arcs + width)</summary>
        public DimensionValue Length { get; set; }

        /// <summary>Width (diameter of arc ends)</summary>
        public DimensionValue Width { get; set; }

        /// <summary>Depth for through slots</summary>
        public DimensionValue Depth { get; set; }

        /// <summary>Center point of slot</summary>
        public Point3D Center { get; set; }

        /// <summary>Direction along length</summary>
        public Vector3D Direction { get; set; }

        /// <summary>Is this a through slot?</summary>
        public bool IsThrough { get; set; }

        /// <summary>Canonical callout: "SLOT 8mm x 20mm THRU"</summary>
        public string Canonical { get; set; }
    }

    /// <summary>
    /// Sheet metal summary for drawing comparison
    /// </summary>
    public class SheetMetalSummary
    {
        public bool IsSheetMetal { get; set; }

        /// <summary>Material thickness</summary>
        public DimensionValue Thickness { get; set; }

        /// <summary>Default inside bend radius</summary>
        public DimensionValue BendRadius { get; set; }

        /// <summary>K-factor for bend calculations</summary>
        public double KFactor { get; set; }

        /// <summary>Bend allowance type: "K-Factor", "Bend Allowance", "Bend Deduction", "Bend Table"</summary>
        public string BendAllowanceType { get; set; }

        /// <summary>Number of bends in the part</summary>
        public int BendCount { get; set; }

        /// <summary>Flat pattern exists?</summary>
        public bool HasFlatPattern { get; set; }

        /// <summary>Flat pattern dimensions if available</summary>
        public DimensionValue FlatLength { get; set; }
        public DimensionValue FlatWidth { get; set; }

        /// <summary>Individual bend details</summary>
        public List<BendDetail> Bends { get; set; } = new List<BendDetail>();
    }

    /// <summary>
    /// Individual bend detail
    /// </summary>
    public class BendDetail
    {
        public string BendId { get; set; }
        public DimensionValue Angle { get; set; }
        public DimensionValue Radius { get; set; }
        public string Direction { get; set; }  // "Up", "Down"
    }

    /// <summary>
    /// Required callout for drawing inspection
    /// </summary>
    public class RequiredCallout
    {
        /// <summary>Unique ID for tracking</summary>
        public string CalloutId { get; set; }

        /// <summary>
        /// Category of callout:
        /// - "Hole": Plain holes, drilled holes
        /// - "Thread": Tapped holes with thread callout
        /// - "Counterbore": Counterbore specifications
        /// - "Countersink": Countersink specifications
        /// - "Slot": Slot dimensions (length x width)
        /// - "Fillet": Fillet radius callouts
        /// - "Chamfer": Chamfer specifications
        /// - "SheetMetal": Thickness, bend radius
        /// - "Material": Material specification
        /// - "Finish": Surface finish requirements
        /// - "BreakEdge": Break/deburr edge notes
        /// - "GD&T": Geometric tolerances
        /// - "Dimension": Critical dimensions
        /// - "Pattern": Pattern callouts (4X, bolt circle)
        /// - "Note": General notes
        /// </summary>
        public string Category { get; set; }

        /// <summary>Sub-category for more specific classification</summary>
        public string SubCategory { get; set; }

        /// <summary>The callout text that should appear on drawing</summary>
        public string ExpectedText { get; set; }

        /// <summary>Alternative acceptable formats</summary>
        public List<string> Alternatives { get; set; } = new List<string>();

        /// <summary>
        /// Priority level:
        /// - "Critical": Must appear on drawing (safety, assembly fit)
        /// - "Required": Should appear per standard practice
        /// - "Recommended": Good practice but may be implicit
        /// - "Optional": Nice to have
        /// </summary>
        public string Priority { get; set; }

        /// <summary>Reference to source feature/geometry</summary>
        public string SourceRef { get; set; }

        /// <summary>Count if multiple instances</summary>
        public int Count { get; set; } = 1;

        /// <summary>Location hint for where callout should appear</summary>
        public string LocationHint { get; set; }

        /// <summary>Associated dimension value if applicable</summary>
        public DimensionValue Value { get; set; }

        /// <summary>Reason this callout is required</summary>
        public string Reason { get; set; }
    }

    /// <summary>
    /// Factory for creating common required callouts
    /// </summary>
    public static class RequiredCalloutFactory
    {
        private static int _calloutId = 0;

        /// <summary>Create a hole callout</summary>
        public static RequiredCallout Hole(double diameterMm, bool isThrough, double? depthMm = null, int count = 1)
        {
            string text = isThrough
                ? $"ø{diameterMm:F2}mm THRU"
                : $"ø{diameterMm:F2}mm x {depthMm:F1}mm DEEP";

            if (count > 1)
                text = $"{count}X " + text;

            return new RequiredCallout
            {
                CalloutId = $"HOLE_{++_calloutId}",
                Category = "Hole",
                ExpectedText = text,
                Priority = "Required",
                Count = count,
                Alternatives = new List<string>
                {
                    text.Replace("ø", "DIA "),
                    text.Replace("THRU", "THROUGH"),
                    text.Replace("DEEP", "DP")
                }
            };
        }

        /// <summary>Create a thread callout</summary>
        public static RequiredCallout Thread(string threadSize, bool isThrough, double? depthMm = null, int count = 1)
        {
            string text = isThrough
                ? $"{threadSize} THRU"
                : $"{threadSize} x {depthMm:F1}mm";

            if (count > 1)
                text = $"{count}X " + text;

            return new RequiredCallout
            {
                CalloutId = $"THREAD_{++_calloutId}",
                Category = "Thread",
                ExpectedText = text,
                Priority = "Critical",  // Threads are critical for assembly
                Count = count,
                Reason = "Thread callout required for fastener compatibility"
            };
        }

        /// <summary>Create a sheet metal thickness callout</summary>
        public static RequiredCallout SheetMetalThickness(double thicknessMm)
        {
            return new RequiredCallout
            {
                CalloutId = $"SM_THICK_{++_calloutId}",
                Category = "SheetMetal",
                SubCategory = "Thickness",
                ExpectedText = $"MATERIAL THICKNESS: {thicknessMm:F2}mm",
                Priority = "Critical",
                Alternatives = new List<string>
                {
                    $"{thicknessMm:F2}mm THK",
                    $"t = {thicknessMm:F2}",
                    $"{thicknessMm:F2} GA"  // Gauge reference if applicable
                },
                Reason = "Sheet thickness determines material stock and bend calculations"
            };
        }

        /// <summary>Create a bend radius callout</summary>
        public static RequiredCallout BendRadius(double radiusMm)
        {
            return new RequiredCallout
            {
                CalloutId = $"BEND_R_{++_calloutId}",
                Category = "SheetMetal",
                SubCategory = "BendRadius",
                ExpectedText = $"BEND R{radiusMm:F2}",
                Priority = "Required",
                Alternatives = new List<string>
                {
                    $"IR {radiusMm:F2}",
                    $"INSIDE RADIUS {radiusMm:F2}"
                },
                Reason = "Bend radius affects tooling selection and flat pattern"
            };
        }

        /// <summary>Create a material callout</summary>
        public static RequiredCallout Material(string material)
        {
            return new RequiredCallout
            {
                CalloutId = $"MAT_{++_calloutId}",
                Category = "Material",
                ExpectedText = $"MATERIAL: {material.ToUpper()}",
                Priority = "Critical",
                LocationHint = "Title block or general notes",
                Reason = "Material specification required for procurement"
            };
        }

        /// <summary>Create a surface finish callout</summary>
        public static RequiredCallout SurfaceFinish(string finish)
        {
            return new RequiredCallout
            {
                CalloutId = $"FINISH_{++_calloutId}",
                Category = "Finish",
                ExpectedText = $"FINISH: {finish.ToUpper()}",
                Priority = "Required",
                LocationHint = "Title block or general notes",
                Reason = "Finish specification for corrosion protection or appearance"
            };
        }

        /// <summary>Create a break edges note</summary>
        public static RequiredCallout BreakEdges(double maxMm = 0.5)
        {
            return new RequiredCallout
            {
                CalloutId = $"BREAK_{++_calloutId}",
                Category = "BreakEdge",
                ExpectedText = $"BREAK ALL SHARP EDGES {maxMm:F1}mm MAX",
                Priority = "Recommended",
                LocationHint = "General notes",
                Alternatives = new List<string>
                {
                    "DEBURR ALL EDGES",
                    "REMOVE ALL BURRS",
                    $"BREAK EDGES {maxMm:F1} MAX"
                },
                Reason = "Safety and handling requirement"
            };
        }

        /// <summary>Create a fillet callout</summary>
        public static RequiredCallout Fillet(double radiusMm, int count = 1)
        {
            string text = count > 1
                ? $"{count}X R{radiusMm:F2}"
                : $"R{radiusMm:F2}";

            return new RequiredCallout
            {
                CalloutId = $"FILLET_{++_calloutId}",
                Category = "Fillet",
                ExpectedText = text,
                Priority = radiusMm >= 3 ? "Required" : "Recommended",
                Count = count
            };
        }

        /// <summary>Create a chamfer callout</summary>
        public static RequiredCallout Chamfer(double distanceMm, double angle = 45)
        {
            string text = angle == 45
                ? $"{distanceMm:F2} X 45°"
                : $"{distanceMm:F2} X {angle:F0}°";

            return new RequiredCallout
            {
                CalloutId = $"CHAMFER_{++_calloutId}",
                Category = "Chamfer",
                ExpectedText = text,
                Priority = "Required",
                Alternatives = new List<string>
                {
                    $"CHAMFER {distanceMm:F2} X {angle:F0}°",
                    $"C{distanceMm:F2}"
                }
            };
        }

        /// <summary>Create a pattern callout</summary>
        public static RequiredCallout Pattern(int count, string patternType, double? boltCircleDiaMm = null)
        {
            string text = boltCircleDiaMm.HasValue
                ? $"{count}X ON ø{boltCircleDiaMm:F1}mm B.C."
                : $"{count}X {patternType}";

            return new RequiredCallout
            {
                CalloutId = $"PATTERN_{++_calloutId}",
                Category = "Pattern",
                ExpectedText = text,
                Priority = "Required",
                Count = count
            };
        }

        /// <summary>Create a GD&T callout placeholder</summary>
        public static RequiredCallout GDT(string feature, string tolerance, string datumRefs = null)
        {
            string text = string.IsNullOrEmpty(datumRefs)
                ? $"{feature}: {tolerance}"
                : $"{feature}: {tolerance} |{datumRefs}|";

            return new RequiredCallout
            {
                CalloutId = $"GDT_{++_calloutId}",
                Category = "GD&T",
                SubCategory = feature,
                ExpectedText = text,
                Priority = "Critical",
                Reason = "Geometric tolerance for critical assembly fit"
            };
        }
    }

    /// <summary>
    /// Summary statistics for quick validation
    /// </summary>
    public class ComparisonSummary
    {
        public int TotalHoles { get; set; }
        public int TappedHoles { get; set; }
        public int ThroughHoles { get; set; }
        public int BlindHoles { get; set; }
        public int CounterboredHoles { get; set; }
        public int CountersunkHoles { get; set; }

        public int TotalSlots { get; set; }

        public int HoleGroups { get; set; }
        public int PatternedHoles { get; set; }

        public int TotalFillets { get; set; }
        public int TotalChamfers { get; set; }

        public int RequiredCallouts { get; set; }
        public int CriticalCallouts { get; set; }

        /// <summary>Diameter histogram for quick matching</summary>
        public Dictionary<string, int> HoleDiameterCounts { get; set; } = new Dictionary<string, int>();
    }
}
