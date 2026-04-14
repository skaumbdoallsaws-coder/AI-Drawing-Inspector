using System;
using System.Collections.Generic;

namespace SolidWorksExtractor.Models
{
    /// <summary>
    /// Complete extracted data for a SolidWorks assembly
    /// </summary>
    public class AssemblyData
    {
        public string FileName { get; set; }
        public string FilePath { get; set; }
        public DateTime ExtractionTime { get; set; }
        public string SolidWorksVersion { get; set; }

        // Assembly metadata
        public AssemblyIdentity Identity { get; set; } = new AssemblyIdentity();

        // Component hierarchy
        public List<ComponentData> Components { get; set; } = new List<ComponentData>();
        public ComponentData RootComponent { get; set; }

        // All mates in the assembly
        public List<MateData> Mates { get; set; } = new List<MateData>();

        // Mate relationships organized by component pair
        public List<MateRelationship> MateRelationships { get; set; } = new List<MateRelationship>();

        // Exploded view steps
        public List<ExplodeStepData> ExplodeSteps { get; set; } = new List<ExplodeStepData>();

        // Statistics
        public AssemblyStatistics Statistics { get; set; } = new AssemblyStatistics();

        // Assembly-level features (machining operations applied after assembly, e.g., weldment machining)
        public FeatureCollection AssemblyFeatures { get; set; } = new FeatureCollection();

        // Assembly view screenshots
        public ViewExportData ViewExports { get; set; } = new ViewExportData();

        // Color mapping for assembly view colorization (lowercase part filename -> hex color)
        public Dictionary<string, string> PartColorMapping { get; set; } = new Dictionary<string, string>();

        // Filename of exported GLB 3D model (if exported)
        public string GlbExportPath { get; set; }

        // Extracted part data (for all unique parts)
        public Dictionary<string, PartData> PartDataCache { get; set; } = new Dictionary<string, PartData>();
    }

    public class AssemblyIdentity
    {
        public string AssemblyNumber { get; set; }
        public string Description { get; set; }
        public string Revision { get; set; }
        public string Author { get; set; }
        public Dictionary<string, string> CustomProperties { get; set; } = new Dictionary<string, string>();
    }

    /// <summary>
    /// Data for a single component in the assembly
    /// </summary>
    public class ComponentData
    {
        // Identification
        public string Name { get; set; }            // Component name in assembly (e.g., "Part1-1")
        public string Name2 { get; set; }           // Name2 property
        public string ReferencedFileName { get; set; }  // Source file name
        public string ReferencedFilePath { get; set; }  // Full path to source file

        // Type
        public ComponentType Type { get; set; }     // Part, Assembly, Virtual
        public bool IsVirtual { get; set; }

        // State
        public ComponentState State { get; set; }   // Resolved, Lightweight, Suppressed
        public bool IsSuppressed { get; set; }
        public bool IsLightweight { get; set; }
        public bool IsHidden { get; set; }
        public bool IsFixed { get; set; }

        // Hierarchy
        public string ParentName { get; set; }
        public int Level { get; set; }              // Depth in tree (0 = root)
        public List<ComponentData> Children { get; set; } = new List<ComponentData>();

        // Transform (position in assembly)
        public TransformMatrix Transform { get; set; } = new TransformMatrix();

        // Instance info
        public int InstanceNumber { get; set; }     // Instance number for same part
        public int TotalInstances { get; set; }     // Total instances of this part in assembly

        // Configuration
        public string ActiveConfiguration { get; set; }

        // Custom properties from the component
        public Dictionary<string, string> Properties { get; set; } = new Dictionary<string, string>();

        // Reference to extracted part data (key into PartDataCache)
        public string PartDataKey { get; set; }
    }

    public enum ComponentType
    {
        Part,
        Assembly,
        Virtual
    }

    public enum ComponentState
    {
        Resolved,
        Lightweight,
        Suppressed,
        InternalIdMismatch,
        Unknown
    }

    /// <summary>
    /// 4x4 transformation matrix for component positioning
    /// </summary>
    public class TransformMatrix
    {
        // Rotation components (3x3)
        public double[,] Rotation { get; set; } = new double[3, 3];

        // Translation (X, Y, Z) in meters
        public double[] Translation { get; set; } = new double[3];

        // Scale factor
        public double Scale { get; set; } = 1.0;

        // Raw array from SolidWorks (typically 13+ elements)
        public double[] RawMatrix { get; set; } = new double[16];

        // Euler angles (Roll, Pitch, Yaw) in degrees - ZYX convention
        public double[] EulerAngles { get; set; }

        // Quaternion (W, X, Y, Z) - unit quaternion
        public double[] Quaternion { get; set; }

        // Convenience properties for translation (in meters)
        public double X => Translation != null && Translation.Length > 0 ? Translation[0] : 0;
        public double Y => Translation != null && Translation.Length > 1 ? Translation[1] : 0;
        public double Z => Translation != null && Translation.Length > 2 ? Translation[2] : 0;

        // Convenience properties for Euler angles (in degrees)
        public double Roll => EulerAngles != null && EulerAngles.Length > 0 ? EulerAngles[0] : 0;
        public double Pitch => EulerAngles != null && EulerAngles.Length > 1 ? EulerAngles[1] : 0;
        public double Yaw => EulerAngles != null && EulerAngles.Length > 2 ? EulerAngles[2] : 0;
    }

    /// <summary>
    /// Data for a single mate with full parameters and limits
    /// </summary>
    public class MateData
    {
        public string Name { get; set; }
        public MateType Type { get; set; }
        public string TypeName { get; set; }        // String representation for readability

        // Participating entities
        public MateEntity Entity1 { get; set; } = new MateEntity();
        public MateEntity Entity2 { get; set; } = new MateEntity();

        // Mate parameters with explicit units
        public DimensionValue Distance { get; set; }     // For distance mates
        public DimensionValue Angle { get; set; }        // For angle mates

        // Mate limits (for distance/angle mates)
        public MateLimits Limits { get; set; }

        // State
        public bool IsFlipped { get; set; }
        public bool IsSuppressed { get; set; }
        public bool IsLocked { get; set; }

        // Alignment
        public MateAlignment Alignment { get; set; }

        // Configuration dependence
        public string ConfigurationName { get; set; }    // If mate is config-specific
        public bool IsConfigurationSpecific { get; set; }

        // For advanced mates (gear, cam, path, etc.)
        public string AdvancedMateType { get; set; }
        public Dictionary<string, double> AdvancedParameters { get; set; } = new Dictionary<string, double>();

        // For width/slot mates
        public DimensionValue WidthValue { get; set; }
        public double PercentAlongWidth { get; set; }
    }

    /// <summary>
    /// Mate limits for constrained mates
    /// </summary>
    public class MateLimits
    {
        public bool HasMinimum { get; set; }
        public bool HasMaximum { get; set; }
        public DimensionValue Minimum { get; set; }
        public DimensionValue Maximum { get; set; }
        public DimensionValue CurrentValue { get; set; }
    }

    /// <summary>
    /// Entity participating in a mate with full component path
    /// </summary>
    public class MateEntity
    {
        // Component identification
        public string ComponentPath { get; set; }        // Full path: "Assembly/SubAssy/Part-1"
        public string ComponentName { get; set; }        // Short name: "Part-1"
        public string ComponentFileName { get; set; }    // File name: "Part.sldprt"
        public int InstanceNumber { get; set; }          // Instance: 1

        // Entity identification
        public MateEntityType EntityType { get; set; }
        public string EntityTypeName { get; set; }       // String for readability
        public string EntityName { get; set; }           // If named (e.g., "Front Plane")
        public int EntityIndex { get; set; }             // Internal index for face/edge

        // Geometry info
        public string GeometryType { get; set; }         // Planar, Cylindrical, Conical, etc.
        public Point3D Point { get; set; }               // Reference point with units
        public Vector3D Direction { get; set; }          // Normal or axis direction
        public DimensionValue Radius { get; set; }       // For cylindrical/conical surfaces

        // Reference quality indicators
        public MateReferenceQuality Quality { get; set; }
        public string QualityReason { get; set; }        // Explanation of quality rating
    }

    /// <summary>
    /// Quality indicator for mate entity references
    /// </summary>
    public class MateReferenceQuality
    {
        /// <summary>Overall quality: "High", "Medium", "Low"</summary>
        public string Level { get; set; }

        /// <summary>Is this a named reference (plane, axis) vs anonymous face/edge?</summary>
        public bool IsNamed { get; set; }

        /// <summary>Can we determine the geometry type reliably?</summary>
        public bool HasGeometryInfo { get; set; }

        /// <summary>Is the component fully resolved?</summary>
        public bool ComponentResolved { get; set; }

        /// <summary>Can this reference be reliably re-found if model changes?</summary>
        public bool IsStable { get; set; }

        /// <summary>For cylindrical references: did we get valid radius?</summary>
        public bool HasDimensions { get; set; }
    }

    /// <summary>
    /// Mate entity types matching swSelectType_e
    /// </summary>
    public enum MateEntityType
    {
        Unknown = 0,
        Face = 1,
        Edge = 2,
        Vertex = 3,
        Plane = 4,          // Reference plane
        Axis = 5,           // Reference axis
        Point = 6,          // Reference point
        SketchSegment = 7,
        SketchPoint = 8,
        CoordinateSystem = 9,
        Body = 10,
        MateReference = 11
    }

    /// <summary>
    /// Mate types matching swMateType_e - comprehensive list
    /// </summary>
    public enum MateType
    {
        Coincident = 0,
        Concentric = 1,
        Perpendicular = 2,
        Parallel = 3,
        Tangent = 4,
        Distance = 5,
        Angle = 6,
        Unknown = 7,
        Symmetric = 8,
        CamFollower = 9,
        Gear = 10,
        Width = 11,
        Lock = 12,
        RackPinion = 13,
        MaxMates = 14,
        Path = 15,
        Linear_Coupler = 16,
        Slot = 17,
        Hinge = 18,
        UniversalJoint = 19,
        Profile_Center = 20,
        Screw = 21
    }

    /// <summary>
    /// Mate alignment
    /// </summary>
    public enum MateAlignment
    {
        Aligned = 0,
        AntiAligned = 1,
        Closest = 2
    }

    /// <summary>
    /// Mate relationship between two components (aggregated view)
    /// </summary>
    public class MateRelationship
    {
        public string Component1 { get; set; }
        public string Component1FileName { get; set; }
        public string Component2 { get; set; }
        public string Component2FileName { get; set; }

        // All mates between these components
        public List<MateData> Mates { get; set; } = new List<MateData>();

        // Derived requirements (for inspection)
        public List<string> InspectionRequirements { get; set; } = new List<string>();
    }

    /// <summary>
    /// Data for a single explode step in an exploded view
    /// </summary>
    public class ExplodeStepData
    {
        public string ExplodeViewName { get; set; }
        public int StepIndex { get; set; }
        public string Name { get; set; }
        public string StepType { get; set; }  // "Translate", "Radial", "SubAssembly"

        // Components affected by this step
        public List<string> ComponentNames { get; set; } = new List<string>();
        public List<string> ComponentFileNames { get; set; } = new List<string>();

        // Translation
        public double[] Direction { get; set; }  // [x, y, z] unit vector
        public double DistanceMeters { get; set; }
        public bool ReverseDirection { get; set; }

        // Rotation (if applicable)
        public double RotationAngleRadians { get; set; }
        public bool ReverseRotation { get; set; }
    }

    /// <summary>
    /// Assembly statistics summary
    /// </summary>
    public class AssemblyStatistics
    {
        public int TotalComponents { get; set; }
        public int UniquePartCount { get; set; }
        public int SubAssemblyCount { get; set; }
        public int TotalMates { get; set; }

        // State counts
        public int ResolvedCount { get; set; }
        public int LightweightCount { get; set; }
        public int SuppressedCount { get; set; }

        // Mate type breakdown
        public Dictionary<string, int> MateTypeCounts { get; set; } = new Dictionary<string, int>();

        // Assembly-level feature count (machining operations on the assembly itself)
        public int AssemblyFeatureCount { get; set; }

        // Component breakdown by file
        public Dictionary<string, int> ComponentCounts { get; set; } = new Dictionary<string, int>();
    }
}
