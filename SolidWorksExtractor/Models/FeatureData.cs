using System;
using System.Collections.Generic;

namespace SolidWorksExtractor.Models
{
    /// <summary>
    /// Collection of all features organized by type
    /// </summary>
    public class FeatureCollection
    {
        // Configuration tracking
        public string ActiveConfiguration { get; set; }
        public List<string> AllConfigurations { get; set; } = new List<string>();

        // Features by type
        public List<HoleWizardFeature> HoleWizardHoles { get; set; } = new List<HoleWizardFeature>();
        public List<ExtrudeFeature> Extrudes { get; set; } = new List<ExtrudeFeature>();
        public List<CutFeature> Cuts { get; set; } = new List<CutFeature>();
        public List<RevolveFeature> Revolves { get; set; } = new List<RevolveFeature>();
        public List<SweepFeature> Sweeps { get; set; } = new List<SweepFeature>();
        public List<LoftFeature> Lofts { get; set; } = new List<LoftFeature>();
        public List<FilletFeature> Fillets { get; set; } = new List<FilletFeature>();
        public List<ChamferFeature> Chamfers { get; set; } = new List<ChamferFeature>();
        public List<PatternFeature> Patterns { get; set; } = new List<PatternFeature>();
        public List<SheetMetalFeature> SheetMetal { get; set; } = new List<SheetMetalFeature>();
        public List<GenericFeature> OtherFeatures { get; set; } = new List<GenericFeature>();

        // Feature tree in order (for reference)
        public List<FeatureTreeNode> FeatureTree { get; set; } = new List<FeatureTreeNode>();

        // Summary counts
        public FeatureSummary Summary { get; set; } = new FeatureSummary();
    }

    /// <summary>
    /// Feature count summary for quick reference
    /// </summary>
    public class FeatureSummary
    {
        public int TotalFeatures { get; set; }
        public int SuppressedFeatures { get; set; }
        public int HoleCount { get; set; }
        public int FilletCount { get; set; }
        public int ChamferCount { get; set; }
        public int PatternCount { get; set; }
        public bool IsSheetMetal { get; set; }
    }

    /// <summary>
    /// Base class for all features
    /// </summary>
    public abstract class FeatureBase
    {
        public string Name { get; set; }
        public string TypeName { get; set; }
        public int TreeOrder { get; set; }

        /// <summary>Is feature suppressed in active configuration?</summary>
        public bool IsSuppressed { get; set; }

        /// <summary>Map of configuration name to suppression state</summary>
        public Dictionary<string, bool> SuppressionByConfig { get; set; } = new Dictionary<string, bool>();

        /// <summary>Configuration in which this feature was extracted</summary>
        public string ExtractedInConfig { get; set; }
    }

    /// <summary>
    /// Feature tree node for preserving hierarchy
    /// </summary>
    public class FeatureTreeNode
    {
        public string Name { get; set; }
        public string TypeName { get; set; }
        public int Level { get; set; }
        public List<FeatureTreeNode> SubFeatures { get; set; } = new List<FeatureTreeNode>();
    }

    #region Hole Wizard Features

    public class HoleWizardFeature : FeatureBase
    {
        public string HoleType { get; set; }        // Counterbore, Countersink, Hole, Straight Tap, Tapered Tap, etc.
        public string Standard { get; set; }        // ANSI Inch, ANSI Metric, ISO, etc.
        public string FastenerType { get; set; }    // All, Hex Bolt, Socket Head Cap Screw, etc.
        public string FastenerSize { get; set; }    // e.g., "M8x1.25", "#10-24"

        // Dimensions
        public double Diameter { get; set; }
        public double Depth { get; set; }
        public bool IsThrough { get; set; }

        // Thread info (for tapped holes)
        public bool IsTapped { get; set; }
        public string ThreadSize { get; set; }      // e.g., "M8x1.25"
        public string ThreadClass { get; set; }     // e.g., "2B"
        public double ThreadDepth { get; set; }

        // Counterbore info
        public double CounterboreDiameter { get; set; }
        public double CounterboreDepth { get; set; }

        // Countersink info
        public double CountersinkDiameter { get; set; }
        public double CountersinkAngle { get; set; }

        // Near/far side info
        public string EndCondition { get; set; }    // Blind, Through All, Up To Next, etc.

        // Instance count (for multi-instance placement)
        public int InstanceCount { get; set; } = 1;
        public List<double[]> InstanceLocations { get; set; } = new List<double[]>();
    }

    #endregion

    #region Extrude/Cut Features

    public class ExtrudeFeature : FeatureBase
    {
        public string Direction1EndCondition { get; set; }  // Blind, Through All, Up To Next, etc.
        public double Direction1Depth { get; set; }
        public bool Direction1ReverseDirection { get; set; }

        public bool IsTwoDirectional { get; set; }
        public string Direction2EndCondition { get; set; }
        public double Direction2Depth { get; set; }

        public bool HasDraft { get; set; }
        public double DraftAngle { get; set; }
        public bool DraftOutward { get; set; }

        public string SketchName { get; set; }
    }

    public class CutFeature : FeatureBase
    {
        public string Direction1EndCondition { get; set; }
        public double Direction1Depth { get; set; }
        public bool Direction1ReverseDirection { get; set; }

        public bool IsTwoDirectional { get; set; }
        public string Direction2EndCondition { get; set; }
        public double Direction2Depth { get; set; }

        public bool HasDraft { get; set; }
        public double DraftAngle { get; set; }

        public string SketchName { get; set; }
    }

    public class RevolveFeature : FeatureBase
    {
        public string RevolutionType { get; set; }  // One-Direction, Mid-Plane, Two-Direction
        public double Angle { get; set; }           // Revolution angle in degrees
        public double Angle2 { get; set; }          // For two-direction
        public string AxisReference { get; set; }
        public string SketchName { get; set; }
    }

    public class SweepFeature : FeatureBase
    {
        public string ProfileSketch { get; set; }
        public string PathSketch { get; set; }
        public string Orientation { get; set; }     // Follow Path, Keep Normal Constant, etc.
        public bool IsThinFeature { get; set; }
        public double ThinWallThickness { get; set; }
    }

    public class LoftFeature : FeatureBase
    {
        public List<string> ProfileSketches { get; set; } = new List<string>();
        public List<string> GuideCurves { get; set; } = new List<string>();
        public bool IsThinFeature { get; set; }
    }

    #endregion

    #region Fillet/Chamfer Features

    public class FilletFeature : FeatureBase
    {
        public string FilletType { get; set; }      // Constant Size, Variable Size, Face Fillet, Full Round
        public double Radius { get; set; }
        public List<double> VariableRadii { get; set; } = new List<double>();
        public int EdgeCount { get; set; }
        public bool PropagateToTangentFaces { get; set; }
    }

    public class ChamferFeature : FeatureBase
    {
        public string ChamferType { get; set; }     // Angle-Distance, Distance-Distance, Vertex
        public double Distance { get; set; }
        public double Distance2 { get; set; }
        public double Angle { get; set; }
        public int EdgeCount { get; set; }
    }

    #endregion

    #region Pattern Features

    public class PatternFeature : FeatureBase
    {
        public string PatternType { get; set; }     // Linear, Circular, Mirror, Sketch-Driven, etc.
        public List<string> SeedFeatures { get; set; } = new List<string>();

        // Total instance count (including seed)
        public int TotalInstances { get; set; }

        // Linear pattern
        public int Direction1Count { get; set; }
        public double Direction1Spacing { get; set; }
        public double[] Direction1Vector { get; set; }    // Direction vector (X, Y, Z)
        public int Direction2Count { get; set; }
        public double Direction2Spacing { get; set; }
        public double[] Direction2Vector { get; set; }    // Direction vector (X, Y, Z)

        // Circular pattern
        public double TotalAngle { get; set; }
        public int InstanceCount { get; set; }
        public bool EqualSpacing { get; set; }
        public string AxisReference { get; set; }
        public double[] AxisLocation { get; set; }        // Point on axis (X, Y, Z) in meters
        public double[] AxisDirection { get; set; }       // Axis direction vector (normalized)

        // Bolt circle (derived for circular patterns of holes)
        public double BoltCircleDiameter { get; set; }    // Diameter of bolt circle in meters
        public double BoltCircleRadius { get; set; }      // Radius to instance centers

        // Mirror pattern
        public string MirrorPlane { get; set; }

        // Instances to skip
        public List<int> SkippedInstances { get; set; } = new List<int>();

        // Explicit instance centers (X, Y, Z for each instance in meters)
        public List<PatternInstanceLocation> InstanceLocations { get; set; } = new List<PatternInstanceLocation>();
    }

    /// <summary>
    /// Location of a single pattern instance
    /// </summary>
    public class PatternInstanceLocation
    {
        /// <summary>1-based instance number (1 = seed)</summary>
        public int InstanceNumber { get; set; }

        /// <summary>Instance center point in meters (X, Y, Z)</summary>
        public double[] Center { get; set; }

        /// <summary>Is this instance skipped/suppressed?</summary>
        public bool IsSkipped { get; set; }

        /// <summary>For circular patterns: angle from first instance in degrees</summary>
        public double AngleFromSeed { get; set; }

        /// <summary>For linear patterns: (row, column) position</summary>
        public int Row { get; set; }
        public int Column { get; set; }
    }

    #endregion

    #region Sheet Metal Features

    public class SheetMetalFeature : FeatureBase
    {
        public string SheetMetalType { get; set; }  // Base Flange, Edge Flange, Miter Flange, Hem, etc.

        // Global sheet metal parameters
        public double Thickness { get; set; }
        public double DefaultBendRadius { get; set; }
        public double KFactor { get; set; }
        public string BendAllowanceType { get; set; }  // K-Factor, Bend Allowance, Bend Deduction, Bend Table
        public double BendAllowance { get; set; }
        public string BendTableFile { get; set; }

        // Specific to feature type
        public double FlangeLength { get; set; }
        public double FlangeAngle { get; set; }
        public string ReliefType { get; set; }      // None, Rectangular, Obround, Tear
        public double ReliefRatio { get; set; }

        // Flat pattern info (if available)
        public FlatPatternInfo FlatPattern { get; set; }
    }

    public class FlatPatternInfo
    {
        public double FlatLength { get; set; }
        public double FlatWidth { get; set; }
        public int BendCount { get; set; }
        public List<BendInfo> Bends { get; set; } = new List<BendInfo>();
    }

    public class BendInfo
    {
        public string BendName { get; set; }
        public double Angle { get; set; }
        public double Radius { get; set; }
        public string Direction { get; set; }       // Up, Down
    }

    #endregion

    #region Generic Feature

    public class GenericFeature : FeatureBase
    {
        public Dictionary<string, object> Parameters { get; set; } = new Dictionary<string, object>();
    }

    #endregion
}
