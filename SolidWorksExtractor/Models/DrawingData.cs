using System;
using System.Collections.Generic;

namespace SolidWorksExtractor.Models
{
    /// <summary>
    /// Complete extracted data for a SolidWorks drawing (.SLDDRW)
    /// Contains sheet layout, view positions, and all annotations with spatial coordinates
    /// </summary>
    public class DrawingData
    {
        // Document info
        public string FileName { get; set; }
        public string FilePath { get; set; }
        public string PartNumber { get; set; }
        public DateTime ExtractionTime { get; set; }
        public string SolidWorksVersion { get; set; }
        public double? SheetWidth { get; set; }
        public double? SheetHeight { get; set; }

        // The part/assembly this drawing references (from the first real view)
        public string ReferencedModelPath { get; set; }

        // All sheets in the drawing
        public List<DrawingSheetData> Sheets { get; set; } = new List<DrawingSheetData>();

        // Extraction diagnostics — persisted for validation and debugging
        public ExtractionDiagnostics Diagnostics { get; set; }
    }

    /// <summary>
    /// Structured extraction report for fail-loud validation.
    /// </summary>
    public class ExtractionDiagnostics
    {
        public string Status { get; set; } = "success";  // "success", "partial", "failed_validation"
        public List<SheetDiagnostics> Sheets { get; set; } = new List<SheetDiagnostics>();
        public List<string> Warnings { get; set; } = new List<string>();
    }

    public class SheetDiagnostics
    {
        public string SheetName { get; set; }
        public bool Failed { get; set; }
        public List<string> ArrayViewNames { get; set; } = new List<string>();
        public List<string> LinkedViewNames { get; set; } = new List<string>();
        public List<string> ExtractedViewNames { get; set; } = new List<string>();
        public List<string> MissingViews { get; set; } = new List<string>();
        public List<string> ArrayOnlyViews { get; set; } = new List<string>();
        public List<string> LinkedOnlyViews { get; set; } = new List<string>();
        public List<string> Warnings { get; set; } = new List<string>();
        public List<ViewExtractionStatus> ViewStatuses { get; set; } = new List<ViewExtractionStatus>();
    }

    public class ViewExtractionStatus
    {
        public string ViewName { get; set; }
        public string Source { get; set; }        // "linked", "array_fallback"
        public bool MetadataOk { get; set; }
        public bool AnnotationsOk { get; set; }
        public bool DimensionsOk { get; set; }
        public bool PrimitivesOk { get; set; }
        public int AnnotationCount { get; set; }
        public int DimensionCount { get; set; }
        public int PrimitiveCount { get; set; }
        public string FailedPhase { get; set; }   // null if all phases succeeded
        public string FailureMessage { get; set; }
    }

    /// <summary>
    /// Data for a single sheet in a multi-sheet drawing
    /// </summary>
    public class DrawingSheetData
    {
        public string SheetName { get; set; }
        public double SheetWidth { get; set; }      // meters
        public double SheetHeight { get; set; }     // meters
        public string PaperSize { get; set; }       // e.g. "A3", "B", "Custom"
        public double Scale { get; set; }           // e.g. 2.0 means 2:1

        // Sheet format geometry (title block, border, revision block)
        public SheetFormatData SheetFormat { get; set; }

        // Drawing views on this sheet (Front, Top, Section, Detail, etc.)
        public List<DrawingViewData> Views { get; set; } = new List<DrawingViewData>();
    }

    /// <summary>
    /// Sheet format data: title block bounds, border insets, drawable area.
    /// All coordinates in sheet-space meters, origin at lower-left.
    /// </summary>
    public class SheetFormatData
    {
        /// <summary>Border inset from sheet edges [left, bottom, right, top] in meters</summary>
        public double[] BorderInset { get; set; }

        /// <summary>Inner drawable rectangle [x_min, y_min, x_max, y_max] in meters</summary>
        public double[] DrawableArea { get; set; }

        /// <summary>Title block bounding rectangle [x_min, y_min, x_max, y_max] in meters</summary>
        public double[] TitleBlockBounds { get; set; }

        /// <summary>Revision table bounding rectangle [x_min, y_min, x_max, y_max] in meters, null if none</summary>
        public double[] RevisionBlockBounds { get; set; }
    }

    /// <summary>
    /// Data for a single drawing view (e.g. Front, Section A-A, Detail B)
    /// </summary>
    public class DrawingViewData
    {
        public string ViewName { get; set; }
        public string ViewType { get; set; }            // "Standard", "Projected", "Section", "Detail", "Isometric", etc.
        public string ViewOrientation { get; set; }     // "Front", "Top", "Right", "Back", "Bottom", "Left", "Isometric", "Trimetric", "Dimetric", or null
        public double[] ViewOutline { get; set; }       // [x_min, y_min, x_max, y_max] in sheet-space meters
        public double[] ViewPosition { get; set; }      // [x, y] center of view in sheet-space meters
        public double ViewScale { get; set; }
        public string ReferencedConfiguration { get; set; }

        // Annotations inside this view (dimensions, notes, GD&T, etc.)
        public List<DrawingAnnotationData> Annotations { get; set; } = new List<DrawingAnnotationData>();

        // Native visible primitives for Phase 4+ geometry diff.
        // Additive only: existing annotation consumers can ignore this field.
        public List<DrawingPrimitiveData> Primitives { get; set; } = new List<DrawingPrimitiveData>();
    }

    /// <summary>
    /// Visible primitive geometry extracted from a drawing view.
    /// Coordinates are stored both in local view space and in sheet space so
    /// compare can use view-local stability while UI overlays can render directly.
    /// </summary>
    public class DrawingPrimitiveData
    {
        public string PrimitiveType { get; set; }      // "line", "polyline", "arc", "circle"
        public string SourceKind { get; set; }         // "modelEdge", "silhouetteEdge"
        public string GeometrySource { get; set; }     // "exact", "tessellated"
        public List<double[]> PointsView { get; set; } = new List<double[]>();
        public List<double[]> PointsSheet { get; set; } = new List<double[]>();
        public double[] BoundsView { get; set; }       // [x_min, y_min, x_max, y_max]
        public double[] BoundsSheet { get; set; }      // [x_min, y_min, x_max, y_max]
        public double[] CenterView { get; set; }       // [x, y]
        public double[] CenterSheet { get; set; }      // [x, y]
        public double? RadiusView { get; set; }
        public double? RadiusSheet { get; set; }
        public int? RotationDir { get; set; }          // -1 clockwise, +1 counterclockwise
    }

    /// <summary>
    /// A single annotation with FLAT top-level keys for consumer compatibility.
    /// The drawing_map.py consumer matches on: featureName, dimensionText, noteText, gtolText, visible.
    /// All type-specific text is promoted to top-level — no nested payload objects.
    /// </summary>
    public class DrawingAnnotationData
    {
        // === Common fields (all annotation types) ===
        public string AnnotationType { get; set; }      // "displayDimension", "note", "gtol", "surfaceFinish", "weldSymbol", "datumTag", "datumTarget", "balloon", "centerMark", "centerLine", "holeCallout"
        public string AnnotationName { get; set; }      // Internal SolidWorks name
        public double[] PositionSheet { get; set; }     // [x, y] in sheet-space meters (origin at lower-left)
        public double[] BoundsSheet { get; set; }       // [x_min, y_min, x_max, y_max] when exact/derived bounds are available
        public string AnchorKind { get; set; }          // Semantics of PositionSheet, e.g. "upperLeftTextBox"
        public string GeometrySource { get; set; }      // "exact", "derived", or "estimated"
        public List<double[]> Leaders { get; set; } = new List<double[]>();  // Leader points [[x,y,z], ...]
        public bool IsDangling { get; set; }
        public bool Visible { get; set; }               // "visible" in JSON (matches consumer key)
        public List<string> MatchKeys { get; set; } = new List<string>(); // extra match candidates for Iris/backend

        // === Annotation text geometry ===
        public double[] TextExtent { get; set; }       // Deprecated fallback [width, height] in meters when no better bounds exist
        public List<DrawingTextRunData> TextRuns { get; set; } = new List<DrawingTextRunData>();

        // === Flat matchable keys (populated based on annotation type) ===
        public string FeatureName { get; set; }         // "featureName" — model feature e.g. "D1@Sketch1" or "Datum A"
        public string DimensionText { get; set; }       // "dimensionText" — full display text e.g. "⌀25.0 +0.000/-0.013"
        public string NoteText { get; set; }            // "noteText" — note/balloon/surface finish text
        public string GtolText { get; set; }            // "gtolText" — GD&T frame text

        // === Dimension-specific fields (only for displayDimension) ===
        public double? DimensionValue { get; set; }     // Numeric value in meters (SI)
        public string DimensionType { get; set; }       // "linear", "angular", "radial", "diametric", "ordinate", "arcLength"
        public double? TolerancePlus { get; set; }
        public double? ToleranceMinus { get; set; }
        public string ToleranceType { get; set; }       // "symmetric", "bilateral", "limit", "basic", "none"
        public bool IsReference { get; set; }           // Reference (parenthetical) dimension
        public bool IsDriven { get; set; }              // Driven vs driving dimension
    }

    public class DrawingTextRunData
    {
        public string Text { get; set; }
        public double[] PositionSheet { get; set; }     // [x, y] in sheet-space meters
        public double? Height { get; set; }             // Text height in meters
        public double? Width { get; set; }              // Width in meters when the API exposes it
        public int? RefPosition { get; set; }           // SolidWorks reference-position enum value
        public double? Angle { get; set; }              // Rotation angle in radians
        public string PositionKind { get; set; }        // Semantics of PositionSheet, e.g. "upperLeftTextBox"
    }
}
