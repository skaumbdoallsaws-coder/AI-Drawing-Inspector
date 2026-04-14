using System;
using System.Collections.Generic;

namespace SolidWorksExtractor.Models
{
    /// <summary>
    /// Index of all extracted parts in a batch run.
    /// Serves as a searchable "database" without needing a real DB.
    /// </summary>
    public class BatchIndex
    {
        public string SchemaVersion { get; set; } = "1.0.0";
        public string ExtractorVersion { get; set; } = "1.0.0";

        /// <summary>When the batch run started</summary>
        public DateTime BatchStartTime { get; set; }

        /// <summary>When the batch run completed</summary>
        public DateTime BatchEndTime { get; set; }

        /// <summary>Root folder that was scanned</summary>
        public string SourceFolder { get; set; }

        /// <summary>Output folder for JSON files</summary>
        public string OutputFolder { get; set; }

        /// <summary>Total files found</summary>
        public int TotalFilesFound { get; set; }

        /// <summary>Successfully extracted</summary>
        public int SuccessCount { get; set; }

        /// <summary>Failed extractions</summary>
        public int FailureCount { get; set; }

        /// <summary>Skipped (non-part documents)</summary>
        public int SkippedCount { get; set; }

        /// <summary>Individual part records</summary>
        public List<IndexRecord> Records { get; set; } = new List<IndexRecord>();

        /// <summary>Failed files with error info</summary>
        public List<FailureRecord> Failures { get; set; } = new List<FailureRecord>();
    }

    /// <summary>
    /// Single record for an extracted part
    /// </summary>
    public class IndexRecord
    {
        /// <summary>Original source file path</summary>
        public string SourceFilePath { get; set; }

        /// <summary>Source file name only</summary>
        public string SourceFileName { get; set; }

        /// <summary>Deterministic part number (from properties or filename)</summary>
        public string PartNumber { get; set; }

        /// <summary>Part description if available</summary>
        public string Description { get; set; }

        /// <summary>Material if available</summary>
        public string Material { get; set; }

        /// <summary>When extraction completed</summary>
        public DateTime ExtractionTime { get; set; }

        /// <summary>Output JSON file path</summary>
        public string JsonFilePath { get; set; }

        /// <summary>JSON file name only</summary>
        public string JsonFileName { get; set; }

        /// <summary>Extractor version used</summary>
        public string ExtractorVersion { get; set; }

        /// <summary>Schema version of output JSON</summary>
        public string SchemaVersion { get; set; }

        /// <summary>Number of holes found</summary>
        public int HoleCount { get; set; }

        /// <summary>Number of features found</summary>
        public int FeatureCount { get; set; }

        /// <summary>File size of output JSON in bytes</summary>
        public long JsonFileSize { get; set; }
    }

    /// <summary>
    /// Record of a failed extraction
    /// </summary>
    public class FailureRecord
    {
        /// <summary>Source file that failed</summary>
        public string SourceFilePath { get; set; }

        /// <summary>Source file name</summary>
        public string SourceFileName { get; set; }

        /// <summary>When failure occurred</summary>
        public DateTime FailureTime { get; set; }

        /// <summary>Error code from SolidWorks (if applicable)</summary>
        public int? SwErrorCode { get; set; }

        /// <summary>Error message</summary>
        public string ErrorMessage { get; set; }

        /// <summary>Failure stage: "Open", "Rebuild", "Extract", "Serialize"</summary>
        public string FailureStage { get; set; }
    }
}
