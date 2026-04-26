using System;

namespace SolidWorksExtractor.Models
{
    /// <summary>
    /// Options for controlling extraction depth and performance
    /// </summary>
    public class ExtractionOptions
    {
        /// <summary>
        /// Extraction mode: "Fast" or "Full"
        /// Fast: Skip expensive geometry analysis, per-config suppression
        /// Full: Complete extraction with all analysis
        /// </summary>
        public ExtractionMode Mode { get; set; } = ExtractionMode.Full;

        /// <summary>Extract part data from assembly components?</summary>
        public bool ExtractPartsFromAssembly { get; set; } = true;

        /// <summary>Resolve lightweight components before extraction?</summary>
        public bool ResolveLightweight { get; set; } = false;

        /// <summary>Extract geometry ground truth (cylinder/slot detection)?</summary>
        public bool ExtractGeometry { get; set; } = true;

        /// <summary>Track suppression state across all configurations?</summary>
        public bool TrackConfigSuppression { get; set; } = true;

        /// <summary>Calculate pattern instance locations?</summary>
        public bool CalculatePatternLocations { get; set; } = true;

        /// <summary>Extract reference geometry (planes, axes, coordinate systems)?</summary>
        public bool ExtractReferenceGeometry { get; set; } = true;

        /// <summary>Extract mate entity quality indicators?</summary>
        public bool ExtractMateQuality { get; set; } = true;

        /// <summary>Generate verification checklist?</summary>
        public bool GenerateChecklist { get; set; } = true;

        /// <summary>Export standard view screenshots as PNG?</summary>
        public bool ExportViews { get; set; } = true;

        /// <summary>Colorize parts in assembly views for VLM identification?</summary>
        public bool ColorParts { get; set; } = true;

        /// <summary>Export colored GLB 3D model for assembly?</summary>
        public bool ExportGlb { get; set; } = false;

        /// <summary>Export per-feature colored GLB for a single part?</summary>
        public bool ExportPartGlb { get; set; } = false;

        /// <summary>Export FEA simulation results (stress-colored GLB + results JSON)?</summary>
        public bool ExportFea { get; set; } = false;

        /// <summary>
        /// Force FEA extraction to use the study with this exact name (case-insensitive).
        /// Takes precedence over FeaStudyIndex. Null/empty means no name filter.
        /// </summary>
        public string FeaStudyName { get; set; } = null;

        /// <summary>
        /// Force FEA extraction to use the study at this 0-based index in the study manager.
        /// Used only when FeaStudyName is null/empty. Negative value (-1) means unset.
        /// </summary>
        public int FeaStudyIndex { get; set; } = -1;

        /// <summary>
        /// When the picked study's mesh is "ExistsAndNotCurrent" (the part has been modified
        /// since the mesh was generated), opt-in to call study.MeshAndRun() so the extractor
        /// re-meshes and re-solves before extraction. Default off — by default we refuse and
        /// tell the user to re-mesh in the UI, since re-meshing modifies analysis state.
        /// </summary>
        public bool AllowRemesh { get; set; } = false;

        /// <summary>
        /// Wall-clock budget (seconds) for the per-element-of-surface stress fallback.
        /// When all bulk/per-node stress APIs return DBNull (some COSMOSWorks builds), the
        /// extractor walks each surface-adjacent element and calls GetStress one-at-a-time.
        /// On slow COM hosts that loop is the only honest way to reach &gt;= 95% per-vertex
        /// coverage so the CAD-projection visualization can run.
        ///
        /// Default 60 keeps interactive runs from hanging.
        /// 0 means "no cap" — the loop completes the full surface-parent walk regardless of
        /// duration. Use 0 (or a much larger value) for batch worker reruns where coverage
        /// matters more than wall-clock.
        /// </summary>
        public int StressFallbackBudgetSeconds { get; set; } = 60;

        /// <summary>Cache key for this extraction (file path + config)</summary>
        public string CacheKey { get; set; }

        /// <summary>Create default options for Fast mode</summary>
        public static ExtractionOptions Fast()
        {
            return new ExtractionOptions
            {
                Mode = ExtractionMode.Fast,
                ExtractGeometry = false,
                TrackConfigSuppression = false,
                CalculatePatternLocations = false,
                ExtractReferenceGeometry = false,
                ExtractMateQuality = false,
                GenerateChecklist = false,
                ExportViews = false,
                ColorParts = false
            };
        }

        /// <summary>Create default options for Full mode</summary>
        public static ExtractionOptions Full()
        {
            return new ExtractionOptions
            {
                Mode = ExtractionMode.Full
            };
        }
    }

    /// <summary>
    /// Extraction mode enumeration
    /// </summary>
    public enum ExtractionMode
    {
        /// <summary>Fast extraction - skip expensive operations</summary>
        Fast,

        /// <summary>Full extraction - complete analysis</summary>
        Full
    }
}
