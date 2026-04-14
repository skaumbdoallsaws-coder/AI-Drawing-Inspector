using System.Collections.Generic;

namespace SolidWorksExtractor.Models
{
    /// <summary>
    /// Sketch information including plane definition and parametric dimensions.
    /// Used for deterministic inspection: matching sketch dimensions to drawing annotations.
    /// </summary>
    public class SketchInfo
    {
        public string SketchName { get; set; }
        public string ParentFeatureName { get; set; }
        public string ParentFeatureType { get; set; }

        // Sketch plane definition (from ISketch.ModelToSketchTransform.Inverse())
        // All vectors in model-space meters
        public double[] PlaneOrigin { get; set; }   // [x, y, z]
        public double[] PlaneXAxis { get; set; }     // [dx, dy, dz] normalized
        public double[] PlaneYAxis { get; set; }     // [dx, dy, dz] normalized
        public double[] PlaneNormal { get; set; }    // [dx, dy, dz] = cross(X, Y)

        public List<SketchDimensionData> Dimensions { get; set; } = new List<SketchDimensionData>();
    }

    /// <summary>
    /// A single parametric dimension from a sketch.
    /// NormalizedKey is the primary match key for drawing annotation comparison.
    /// Includes SketchName/ParentFeatureName for flattened access by Phase 2 matcher
    /// (so consumers don't need to walk up to parent SketchInfo).
    /// </summary>
    public class SketchDimensionData
    {
        public string DimensionName { get; set; }    // "D1" (short display name)
        public string NormalizedKey { get; set; }     // "D1@Sketch43" (strip @docName suffix)
        public string RawFullName { get; set; }       // "D1@Sketch43@1020001.Part" (raw IDimension.FullName)
        public string SketchName { get; set; }        // "Sketch43" (from parent SketchInfo, for flattened access)
        public string ParentFeatureName { get; set; } // "Boss-Extrude1" (from parent SketchInfo)

        public double Value { get; set; }             // SI meters (or radians for angular)
        public string DimensionType { get; set; }     // "linear", "angular", "diametric", "radial"
        public double TolerancePlus { get; set; }
        public double ToleranceMinus { get; set; }
        public bool IsReference { get; set; }
        public bool IsDriven { get; set; }

        public List<SketchEntityData> AttachedEntities { get; set; } = new List<SketchEntityData>();
    }

    /// <summary>
    /// Geometry of a sketch entity (line, arc, point) attached to a dimension.
    /// Coordinates are in sketch-plane 2D (meters).
    /// NOTE: ISketchCircle does NOT exist in the installed interop.
    /// Circles are represented as ISketchArc with full sweep.
    /// </summary>
    public class SketchEntityData
    {
        public string EntityType { get; set; }       // "SketchLine", "SketchArc", "SketchPoint"

        // For SketchLine:
        public double[] StartPoint { get; set; }     // [x, y] in sketch-plane coords (meters)
        public double[] EndPoint { get; set; }       // [x, y]

        // For SketchArc (includes circles):
        public double[] Center { get; set; }         // [x, y]
        public double Radius { get; set; }           // meters
        public double StartAngle { get; set; }       // radians
        public double EndAngle { get; set; }         // radians (2*PI for full circles)

        // For SketchPoint:
        public double[] Point { get; set; }          // [x, y]
    }
}
