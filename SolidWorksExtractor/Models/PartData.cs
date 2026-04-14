using System;
using System.Collections.Generic;

namespace SolidWorksExtractor.Models
{
    /// <summary>
    /// Complete extracted data for a SolidWorks part
    /// </summary>
    public class PartData
    {
        // Schema versioning for compatibility
        public string SchemaVersion { get; set; } = "1.0.0";
        public string ExtractorVersion { get; set; } = "1.0.0";

        // Document info
        public string FileName { get; set; }
        public string FilePath { get; set; }
        public DateTime ExtractionTime { get; set; }
        public string SolidWorksVersion { get; set; }

        // Active configuration at extraction time
        public string ActiveConfiguration { get; set; }

        // Identity & Metadata
        public PartIdentity Identity { get; set; } = new PartIdentity();

        // Physical Properties
        public PhysicalProperties Physical { get; set; } = new PhysicalProperties();

        // All features organized by type (intent from feature tree)
        public FeatureCollection Features { get; set; } = new FeatureCollection();

        // Geometry-derived ground truth (independent verification)
        public GeometryGroundTruth Geometry { get; set; } = new GeometryGroundTruth();

        // Comparison-ready data for LLM drawing inspection
        public ComparisonReadyData Comparison { get; set; } = new ComparisonReadyData();

        // Configuration data (if multi-config part)
        public List<ConfigurationData> Configurations { get; set; } = new List<ConfigurationData>();

        // Exported standard view screenshots (front, top, right, isometric)
        public ViewExportData ViewExports { get; set; } = new ViewExportData();

        // Sketch dimensions + plane definitions for deterministic inspection
        public List<SketchInfo> Sketches { get; set; } = new List<SketchInfo>();

        // Generated verification checklist for inspector (legacy format)
        public List<string> VerificationChecklist { get; set; } = new List<string>();
    }

    public class PartIdentity
    {
        // Custom properties
        public string PartNumber { get; set; }
        public string Description { get; set; }
        public string Revision { get; set; }
        public string Author { get; set; }
        public string Material { get; set; }
        public string Finish { get; set; }

        // Additional custom properties (key-value)
        public Dictionary<string, string> CustomProperties { get; set; } = new Dictionary<string, string>();

        // Config-specific properties
        public Dictionary<string, string> ConfigProperties { get; set; } = new Dictionary<string, string>();
    }

    public class PhysicalProperties
    {
        // Document unit system
        public string DocUnitSystem { get; set; }  // IPS, MMGS, CGS, MKS
        public string LengthUnit { get; set; }     // mm, in, m
        public string MassUnit { get; set; }       // kg, lb, g
        public string AngleUnit { get; set; }      // deg, rad

        // Mass properties
        public double Mass { get; set; }
        public double Volume { get; set; }
        public double SurfaceArea { get; set; }
        public double[] CenterOfMass { get; set; }  // X, Y, Z

        // Bounding box
        public BoundingBox BoundingBox { get; set; } = new BoundingBox();

        // Material assignment
        public string AssignedMaterial { get; set; }
        public string MaterialDatabase { get; set; }
    }

    public class BoundingBox
    {
        public double MinX { get; set; }
        public double MinY { get; set; }
        public double MinZ { get; set; }
        public double MaxX { get; set; }
        public double MaxY { get; set; }
        public double MaxZ { get; set; }

        public double Length => MaxX - MinX;
        public double Width => MaxY - MinY;
        public double Height => MaxZ - MinZ;
    }

    public class ConfigurationData
    {
        public string Name { get; set; }
        public bool IsActive { get; set; }
        public string Description { get; set; }
        public Dictionary<string, string> Properties { get; set; } = new Dictionary<string, string>();
        public Dictionary<string, double> Parameters { get; set; } = new Dictionary<string, double>();
    }
}
