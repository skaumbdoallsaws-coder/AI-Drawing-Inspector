using System;
using System.Collections.Generic;

namespace SolidWorksExtractor.Models
{
    /// <summary>
    /// Geometry-derived ground truth extracted from actual body geometry
    /// This provides verification data independent of feature definitions
    /// </summary>
    public class GeometryGroundTruth
    {
        // Cylindrical features (holes, pins, bosses)
        public List<CylindricalFeature> Cylinders { get; set; } = new List<CylindricalFeature>();

        // Planar faces with normals
        public List<PlanarFace> PlanarFaces { get; set; } = new List<PlanarFace>();

        // Slot features (detected from geometry)
        public List<SlotFeature> Slots { get; set; } = new List<SlotFeature>();

        // Reference geometry (planes, axes)
        public ReferenceGeometry References { get; set; } = new ReferenceGeometry();

        // Stable reference frames for positioning
        public ReferenceFrame ReferenceFrame { get; set; } = new ReferenceFrame();

        // Edge summary
        public EdgeSummary Edges { get; set; } = new EdgeSummary();
    }

    /// <summary>
    /// Cylindrical surface detected in geometry (holes, bosses, etc.)
    /// </summary>
    public class CylindricalFeature
    {
        public string Id { get; set; }              // Unique identifier

        // Classification
        public CylinderType Type { get; set; }      // Hole, Boss, Through, Blind, etc.
        public bool IsInternal { get; set; }        // True = hole, False = external cylinder

        // Geometry
        public double Diameter { get; set; }
        public double Radius { get; set; }
        public double Length { get; set; }          // Depth for holes

        // Axis definition
        public double[] AxisPoint { get; set; }     // Point on axis (X, Y, Z)
        public double[] AxisDirection { get; set; } // Axis direction vector (X, Y, Z)

        // Position (center of one end)
        public double[] StartPoint { get; set; }
        public double[] EndPoint { get; set; }

        // THRU/BLIND classification with axis-extent analysis
        public bool IsThrough { get; set; }         // Goes completely through
        public ThroughHoleAnalysis ThroughAnalysis { get; set; }

        // Entry treatment detection
        public EntryTreatment EntryTreatment { get; set; }

        // Thread detection
        public bool HasThread { get; set; }         // Detected thread (helical edge)
        public bool HasCounterbore { get; set; }
        public bool HasCountersink { get; set; }

        // Associated features (if can be determined)
        public string AssociatedFeatureName { get; set; }

        // For grouped holes (same size at multiple locations)
        public int GroupId { get; set; }
        public int InstanceInGroup { get; set; }

        // Sheet metal filtering
        public bool IsSheetMetalBend { get; set; }      // True if this is a bend cylinder
        public string BendFeatureName { get; set; }     // Name of associated bend feature
    }

    /// <summary>
    /// Detailed analysis of through vs blind hole classification
    /// </summary>
    public class ThroughHoleAnalysis
    {
        /// <summary>Min projection of boundary edges onto hole axis (meters)</summary>
        public double AxisMinExtent { get; set; }

        /// <summary>Max projection of boundary edges onto hole axis (meters)</summary>
        public double AxisMaxExtent { get; set; }

        /// <summary>Computed depth from axis extents (meters)</summary>
        public double ComputedDepth { get; set; }

        /// <summary>Does hole open on the entry side (start)?</summary>
        public bool OpensAtStart { get; set; }

        /// <summary>Does hole open on the exit side (end)?</summary>
        public bool OpensAtEnd { get; set; }

        /// <summary>Number of outer body faces the hole intersects</summary>
        public int OuterFaceCount { get; set; }

        /// <summary>Entry face classification (Top, Bottom, Front, etc.)</summary>
        public string EntryFaceOrientation { get; set; }

        /// <summary>Exit face classification if through</summary>
        public string ExitFaceOrientation { get; set; }

        /// <summary>Confidence: "High" (2 open faces), "Medium" (geometry heuristics), "Low" (edge count only)</summary>
        public string Confidence { get; set; }

        /// <summary>Reasoning for the classification decision</summary>
        public string ClassificationReason { get; set; }
    }

    /// <summary>
    /// Entry treatment detected from geometry (countersink, counterbore, chamfer at hole entry)
    /// </summary>
    public class EntryTreatment
    {
        /// <summary>Type: "None", "Counterbore", "Countersink", "Chamfer"</summary>
        public string TreatmentType { get; set; }

        /// <summary>Diameter of the treatment (larger than hole)</summary>
        public double Diameter { get; set; }

        /// <summary>Depth for counterbore, or distance for chamfer</summary>
        public double Depth { get; set; }

        /// <summary>Angle for countersink (typically 82° or 90°)</summary>
        public double Angle { get; set; }

        /// <summary>Confidence in treatment detection</summary>
        public string Confidence { get; set; }
    }

    public enum CylinderType
    {
        Unknown,
        HoleWall,            // Generic internal cylinder (hole) - couldn't classify further
        ThroughHole,
        BlindHole,
        CounterboredHole,
        CountersunkHole,
        TappedHole,
        ExternalCylinder     // Boss, pin
        // Note: Slots are detected separately as SlotFeature entities, not cylinder types
    }

    /// <summary>
    /// Planar face with orientation info
    /// </summary>
    public class PlanarFace
    {
        public string Id { get; set; }

        // Normal vector
        public double[] Normal { get; set; }        // Unit normal (X, Y, Z)

        // Position (point on plane)
        public double[] PointOnPlane { get; set; }

        // Plane equation coefficients (Ax + By + Cz + D = 0)
        public double D { get; set; }

        // Area
        public double Area { get; set; }

        // Classification
        public string Orientation { get; set; }     // Top, Bottom, Front, Back, Left, Right, Angled

        // Bounding rectangle (in plane coordinates)
        public double[] BoundingMin { get; set; }
        public double[] BoundingMax { get; set; }
    }

    /// <summary>
    /// Slot feature detected from geometry
    /// </summary>
    public class SlotFeature
    {
        public string Id { get; set; }

        // Slot dimensions
        public double Length { get; set; }          // Overall length
        public double Width { get; set; }           // Width (diameter of end radius)
        public double Depth { get; set; }           // For cut slots

        // Orientation
        public double[] CenterLine { get; set; }    // Direction vector
        public double[] CenterPoint { get; set; }   // Midpoint

        // End points
        public double[] StartCenter { get; set; }
        public double[] EndCenter { get; set; }

        // Classification
        public bool IsThrough { get; set; }
        public string SlotType { get; set; }        // Straight, Arc, etc.
    }

    /// <summary>
    /// Reference geometry (planes, axes, origins)
    /// </summary>
    public class ReferenceGeometry
    {
        // Standard planes
        public PlaneDefinition FrontPlane { get; set; }
        public PlaneDefinition TopPlane { get; set; }
        public PlaneDefinition RightPlane { get; set; }

        // Custom reference planes
        public List<PlaneDefinition> CustomPlanes { get; set; } = new List<PlaneDefinition>();

        // Reference axes
        public List<AxisDefinition> Axes { get; set; } = new List<AxisDefinition>();

        // Origin
        public double[] Origin { get; set; } = new double[] { 0, 0, 0 };

        // Coordinate system (if custom)
        public List<CoordinateSystem> CoordinateSystems { get; set; } = new List<CoordinateSystem>();
    }

    public class PlaneDefinition
    {
        public string Name { get; set; }
        public double[] Normal { get; set; }
        public double[] Point { get; set; }
    }

    public class AxisDefinition
    {
        public string Name { get; set; }
        public double[] Direction { get; set; }
        public double[] Point { get; set; }
    }

    public class CoordinateSystem
    {
        public string Name { get; set; }
        public double[] Origin { get; set; }        // Origin point in meters
        public double[] XAxis { get; set; }         // X-axis direction (normalized)
        public double[] YAxis { get; set; }         // Y-axis direction (normalized)
        public double[] ZAxis { get; set; }         // Z-axis direction (normalized)

        /// <summary>Is this the part's default coordinate system (origin)?</summary>
        public bool IsDefault { get; set; }

        /// <summary>Transform matrix (4x4 column-major for OpenGL compatibility)</summary>
        public double[] TransformMatrix { get; set; }
    }

    /// <summary>
    /// Reference frame information for stable positioning across part/assembly contexts
    /// </summary>
    public class ReferenceFrame
    {
        /// <summary>Part's default coordinate system (origin)</summary>
        public CoordinateSystem PartOrigin { get; set; }

        /// <summary>User-defined coordinate systems in the part</summary>
        public List<CoordinateSystem> UserCoordinateSystems { get; set; } = new List<CoordinateSystem>();

        /// <summary>Bounding box center (useful for centering)</summary>
        public double[] BoundingBoxCenter { get; set; }

        /// <summary>Assembly transform (when extracted in assembly context)</summary>
        public AssemblyTransform AssemblyContext { get; set; }
    }

    /// <summary>
    /// Transform data when a part is in an assembly context
    /// </summary>
    public class AssemblyTransform
    {
        /// <summary>Parent assembly name</summary>
        public string AssemblyName { get; set; }

        /// <summary>Component path in assembly (e.g., "Assembly1/SubAssy/Part-1")</summary>
        public string ComponentPath { get; set; }

        /// <summary>Instance number of this component</summary>
        public int InstanceNumber { get; set; }

        /// <summary>Transform from part coordinates to assembly coordinates</summary>
        public double[] PartToAssemblyMatrix { get; set; }  // 4x4 column-major

        /// <summary>Translation component (X, Y, Z) in meters</summary>
        public double[] Translation { get; set; }

        /// <summary>Rotation component as Euler angles (degrees)</summary>
        public double[] RotationEuler { get; set; }

        /// <summary>Rotation component as quaternion (W, X, Y, Z)</summary>
        public double[] RotationQuaternion { get; set; }

        /// <summary>Scale factor (usually 1.0)</summary>
        public double Scale { get; set; } = 1.0;
    }

    /// <summary>
    /// Summary of edge geometry
    /// </summary>
    public class EdgeSummary
    {
        public int TotalEdgeCount { get; set; }
        public int LinearEdgeCount { get; set; }
        public int CircularEdgeCount { get; set; }
        public int HelicalEdgeCount { get; set; }   // Indicates threads
        public int SplineEdgeCount { get; set; }
        public int OtherEdgeCount { get; set; }

        // Fillet/chamfer edge detection
        public int FilletedEdgeCount { get; set; }
        public int ChamferedEdgeCount { get; set; }
    }
}
