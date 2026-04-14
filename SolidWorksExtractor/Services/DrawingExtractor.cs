using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorksExtractor.Models;

namespace SolidWorksExtractor.Services
{
    /// <summary>
    /// Extracts drawing data: sheets, views, annotations (dimensions, notes, GD&T, surface finish, datums)
    /// All coordinates are in sheet-space meters with origin at lower-left of sheet.
    /// </summary>
    public class DrawingExtractor
    {
        private readonly ISldWorks _swApp;
        private readonly List<string> _targetedExtractionOrder;
        private StreamWriter _trace;
        private bool _skipGeometryEnrichment; // Set per-view to gate deep COM calls

        // ================================================================
        // Fragile view extraction policy (section/detail views).
        //
        // Binary-search testing on Holder Rev C confirmed:
        //   - Metadata extraction: safe
        //   - Annotation chain traversal: safe
        //   - Semantic dimension extraction: safe
        //   - Dimension GEOMETRY enrichment (GetPosition, GetDisplayData,
        //     ExtractLeaderPoints, PopulateDisplayDimensionGeometry):
        //     KILLS the COM session after 2-3 views
        //
        // Production tradeoff: extract all semantic data, skip only the
        // geometry enrichment calls that poison the COM session. This
        // preserves dimension text, value, type, tolerance, reference
        // status, and feature name -- everything needed for diff/compare.
        // Position/bounds/leaders/textExtent will be null on fragile-view
        // dimensions.
        // ================================================================
        private const bool FRAGILE_EXTRACT_ANNOTATIONS = true;
        private const bool FRAGILE_EXTRACT_DIMENSIONS  = true;
        private const bool FRAGILE_EXTRACT_GEOMETRY    = false;
        private const bool EXTRACT_VISIBLE_PRIMITIVES  = true;
        private const short CROSSHATCH_EXCLUDE         = 1;

        public DrawingExtractor(ISldWorks swApp, IEnumerable<string> targetedExtractionOrder = null)
        {
            _swApp = swApp;
            _targetedExtractionOrder = targetedExtractionOrder != null
                ? new List<string>(targetedExtractionOrder)
                : null;
        }

        /// <summary>
        /// Write a breadcrumb to the trace log. If SolidWorks crashes, the last
        /// line identifies the exact sheet, view, and stage reached.
        /// </summary>
        private void Trace(string message)
        {
            if (_trace == null) return;
            try
            {
                _trace.WriteLine($"[{DateTime.Now:HH:mm:ss.fff}] {message}");
                _trace.Flush();  // Flush immediately -- crash safety
            }
            catch { }
        }

        /// <summary>
        /// Extract complete drawing data from a drawing document.
        /// </summary>
        /// <param name="doc">The active drawing document.</param>
        /// <param name="traceOutputDir">Directory for the breadcrumb trace log. Null to skip.</param>
        public DrawingData ExtractDrawing(IModelDoc2 doc, string traceOutputDir = null)
        {
            var drawDoc = doc as IDrawingDoc;
            if (drawDoc == null)
            {
                Console.WriteLine("Document is not a drawing");
                return new DrawingData
                {
                    FileName = Path.GetFileName(doc.GetPathName()),
                    FilePath = doc.GetPathName(),
                    ExtractionTime = DateTime.Now
                };
            }

            // Set up breadcrumb trace log
            string docPath = doc.GetPathName() ?? "";
            if (!string.IsNullOrEmpty(traceOutputDir))
            {
                try
                {
                    string baseName = Path.GetFileNameWithoutExtension(docPath);
                    string tracePath = Path.Combine(traceOutputDir, baseName + "_drawing_extract_trace.log");
                    _trace = new StreamWriter(tracePath, append: false) { AutoFlush = true };
                    Trace($"=== Drawing extraction started: {docPath} ===");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"  Warning: Could not create trace log: {ex.Message}");
                }
            }

            try
            {
                return ExtractDrawingInner(drawDoc, doc, docPath);
            }
            finally
            {
                if (_trace != null)
                {
                    Trace("=== Extraction finished ===");
                    _trace.Close();
                    _trace = null;
                }
            }
        }

        private DrawingData ExtractDrawingInner(IDrawingDoc drawDoc, IModelDoc2 doc, string docPath)
        {
            var data = new DrawingData
            {
                FileName = Path.GetFileName(docPath),
                FilePath = docPath,
                PartNumber = Path.GetFileNameWithoutExtension(docPath),
                ExtractionTime = DateTime.Now,
                Diagnostics = new ExtractionDiagnostics()
            };

            // Get SolidWorks version
            try { data.SolidWorksVersion = _swApp.RevisionNumber(); } catch { }

            // Get referenced model path
            Trace("Getting referenced model path");
            try { data.ReferencedModelPath = GetReferencedModelPath(drawDoc); }
            catch (Exception ex)
            {
                Console.WriteLine($"  Warning: Could not get referenced model path: {ex.Message}");
                data.Diagnostics.Warnings.Add($"ReferencedModelPath failed: {ex.Message}");
            }

            // Extract each sheet
            string[] sheetNames = null;
            try { sheetNames = (string[])drawDoc.GetSheetNames(); } catch { }

            if (sheetNames == null || sheetNames.Length == 0)
            {
                Console.WriteLine("  Warning: No sheets found in drawing");
                data.Diagnostics.Status = "failed_validation";
                data.Diagnostics.Warnings.Add("No sheets found");
                return data;
            }

            Console.WriteLine($"  Found {sheetNames.Length} sheet(s)");

            foreach (var sheetName in sheetNames)
            {
                try
                {
                    Trace($"ActivateSheet: {sheetName}");
                    bool activated = drawDoc.ActivateSheet(sheetName);
                    if (!activated)
                    {
                        Console.WriteLine($"  Warning: ActivateSheet('{sheetName}') returned false");
                        var failDiag = new SheetDiagnostics { SheetName = sheetName, Failed = true };
                        failDiag.Warnings.Add("ActivateSheet returned false");
                        data.Diagnostics.Sheets.Add(failDiag);
                        continue;
                    }

                    var (sheetData, sheetDiag) = ExtractSheet(drawDoc, doc, sheetName);
                    if (sheetData != null)
                    {
                        data.Sheets.Add(sheetData);
                        if (!data.SheetWidth.HasValue)
                            data.SheetWidth = sheetData.SheetWidth;
                        if (!data.SheetHeight.HasValue)
                            data.SheetHeight = sheetData.SheetHeight;
                    }
                    else
                    {
                        sheetDiag.Failed = true;
                        sheetDiag.Warnings.Add("ExtractSheet returned null");
                    }
                    data.Diagnostics.Sheets.Add(sheetDiag);
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"  Warning: Failed to extract sheet '{sheetName}': {ex.Message}");
                    var failDiag = new SheetDiagnostics { SheetName = sheetName, Failed = true };
                    failDiag.Warnings.Add($"Exception: {ex.Message}");
                    data.Diagnostics.Sheets.Add(failDiag);
                }
            }

            // Strict validation
            ValidateExtraction(data);

            return data;
        }

        /// <summary>
        /// Extract data from a single sheet. Returns (sheetData, diagnostics).
        /// Sheet-format extraction runs AFTER view extraction to avoid poisoning
        /// COM state before view traversal.
        /// </summary>
        private (DrawingSheetData, SheetDiagnostics) ExtractSheet(IDrawingDoc drawDoc, IModelDoc2 doc, string sheetName)
        {
            var diag = new SheetDiagnostics { SheetName = sheetName };

            ISheet sheet = null;
            try { sheet = (ISheet)drawDoc.Sheet[sheetName]; }
            catch { }

            if (sheet == null)
            {
                Console.WriteLine($"  Warning: Could not access sheet '{sheetName}'");
                diag.Failed = true;
                diag.Warnings.Add("drawDoc.Sheet[sheetName] returned null");
                return (null, diag);
            }

            // Get sheet dimensions
            double sheetWidth = 0, sheetHeight = 0;
            try { sheet.GetSize(ref sheetWidth, ref sheetHeight); } catch { }

            var sheetData = new DrawingSheetData
            {
                SheetName = sheetName,
                SheetWidth = sheetWidth,
                SheetHeight = sheetHeight,
                Scale = GetSheetScale(sheet),
                PaperSize = GetPaperSizeName(sheet)
            };

            // == Phase 1: Discovery via ISheet.GetViews (names only) ==
            // Used for diagnostics and to detect views missed by linked traversal.
            // Does NOT extract -- only collects expected view names.
            var arrayViewNames = new List<string>();
            Trace($"  [{sheetName}] Enumerating ISheet.GetViews()");
            try
            {
                object viewsRaw = sheet.GetViews();
                if (viewsRaw is object[] viewArray)
                {
                    foreach (object vObj in viewArray)
                    {
                        var v = vObj as IView;
                        if (v == null) continue;
                        string vName = "";
                        try { vName = v.GetName2() ?? ""; } catch { continue; }
                        if (!IsRealDrawingViewOnSheet(v, vName, sheetWidth, sheetHeight)) continue;
                        if (!arrayViewNames.Contains(vName))
                            arrayViewNames.Add(vName);
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    Warning: ISheet.GetViews() failed: {ex.Message}");
                diag.Warnings.Add($"ISheet.GetViews failed: {ex.Message}");
            }
            diag.ArrayViewNames = new List<string>(arrayViewNames);

            // == Phase 2: Linked traversal for discovery only ==
            // Walk the linked list to discover view names. No extraction here --
            // holding IView handles across deep extraction is unsafe (confirmed
            // by live testing: even prefetched handles die after extraction).
            var linkedViewNames = new List<string>();
            Trace($"  [{sheetName}] Linked traversal (discovery only)");
            try
            {
                IView view = (IView)drawDoc.GetFirstView();
                while (view != null)
                {
                    string vName = "";
                    try { vName = view.GetName2() ?? ""; } catch { }
                    if (IsRealDrawingViewOnSheet(view, vName, sheetWidth, sheetHeight))
                    {
                        if (!linkedViewNames.Contains(vName))
                            linkedViewNames.Add(vName);
                    }
                    try { view = (IView)view.GetNextView(); }
                    catch { view = null; }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    Warning: Linked-list traversal failed: {ex.Message}");
                diag.Warnings.Add($"Linked traversal failed: {ex.Message}");
            }
            diag.LinkedViewNames = new List<string>(linkedViewNames);

            // Merge discovered names from both sources
            var allDiscovered = new List<string>(arrayViewNames);
            foreach (var n in linkedViewNames)
                if (!allDiscovered.Contains(n)) allDiscovered.Add(n);

            var arrayOnlyNames = arrayViewNames.FindAll(n => !linkedViewNames.Contains(n));
            var linkedOnlyNames = linkedViewNames.FindAll(n => !arrayViewNames.Contains(n));
            diag.ArrayOnlyViews = arrayOnlyNames;
            diag.LinkedOnlyViews = linkedOnlyNames;

            Console.WriteLine($"    Sheet '{sheetName}' view diagnostics:");
            Console.WriteLine($"      ISheet.GetViews: {string.Join(", ", arrayViewNames)}");
            Console.WriteLine($"      Linked traversal: {string.Join(", ", linkedViewNames)}");
            if (arrayOnlyNames.Count > 0)
                Console.WriteLine($"      Missing from linked traversal: {string.Join(", ", arrayOnlyNames)}");
            if (linkedOnlyNames.Count > 0)
                Console.WriteLine($"      Missing from ISheet.GetViews: {string.Join(", ", linkedOnlyNames)}");

            // == Phase 3: Fresh-traversal-per-target extraction ==
            // For each target view, start a FRESH linked-list traversal, find the
            // target by name, and extract immediately at that point. No IView
            // handles are held across extractions. This is the only architecture
            // confirmed safe for section/detail views.
            //
            // Extraction order: fragile views first (Section, Detail), then others.
            // Rationale: fragile views should be attempted in the cleanest COM state.
            var extractionOrder = BuildExtractionOrder(allDiscovered);
            var extractedNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            int viewCount = 0;

            Console.WriteLine($"      Extraction order: {string.Join(", ", extractionOrder)}");

            foreach (var targetName in extractionOrder)
            {
                // COM-state reset before each target extraction.
                // Re-activate the sheet and force a graphics redraw to keep
                // the COM session alive across multiple view extractions.
                Trace($"  [{sheetName}] COM reset before: {targetName}");
                try
                {
                    drawDoc.ActivateSheet(sheetName);
                    doc.GraphicsRedraw2();
                    Trace($"  [{sheetName}] COM reset OK");
                }
                catch (Exception ex)
                {
                    Trace($"  [{sheetName}] COM reset FAILED: {ex.Message}");
                    Console.WriteLine($"      Warning: COM reset failed before '{targetName}': {ex.Message}");
                    diag.Warnings.Add($"COM reset failed before '{targetName}': {ex.Message}");
                    // Continue anyway -- extraction may still work
                }

                Trace($"  [{sheetName}] Target: {targetName}");
                var viewStatus = new ViewExtractionStatus { ViewName = targetName };

                try
                {
                    var viewData = ExtractViewByFreshTraversal(drawDoc, targetName, sheetName, sheetWidth, sheetHeight, viewStatus);

                    if (viewData == null && viewStatus.Source == "not_found_in_traversal")
                    {
                        // Fresh traversal did not find it -- try array fallback
                        Trace($"  [{sheetName}] Array fallback for: {targetName}");
                        viewData = ExtractViewFromArray(sheet, targetName, viewStatus);
                    }

                    if (viewData != null && IsExtractedViewUsable(viewData))
                    {
                        if (string.IsNullOrWhiteSpace(viewData.ViewName))
                            viewData.ViewName = targetName;
                        sheetData.Views.Add(viewData);
                        extractedNames.Add(targetName);
                        viewCount++;
                    }
                    else if (viewStatus.FailedPhase == null)
                    {
                        viewStatus.FailedPhase = "usability";
                        viewStatus.FailureMessage = "No usable data produced";
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"    Warning: Error extracting view '{targetName}': {ex.Message}");
                    viewStatus.FailedPhase = "exception";
                    viewStatus.FailureMessage = ex.Message;
                }
                diag.ViewStatuses.Add(viewStatus);
            }

            // Missing views
            diag.ExtractedViewNames = new List<string>(extractedNames);
            diag.MissingViews = allDiscovered.FindAll(n => !extractedNames.Contains(n));

            if (diag.MissingViews.Count > 0)
                Console.WriteLine($"      WARNING: Missing views: {string.Join(", ", diag.MissingViews)}");

            Console.WriteLine($"    Sheet '{sheetName}': {viewCount} views extracted");

            // == Phase 4: Sheet format extraction (AFTER all views) ==
            Trace($"  [{sheetName}] Extracting sheet format");
            try { sheetData.SheetFormat = ExtractSheetFormat(drawDoc, sheet, sheetWidth, sheetHeight); }
            catch (Exception ex)
            {
                Console.WriteLine($"    Warning: Could not extract sheet format: {ex.Message}");
                diag.Warnings.Add($"SheetFormat failed: {ex.Message}");
            }

            return (sheetData, diag);
        }

        /// <summary>
        /// Find a view by name in ISheet.GetViews() array (fallback).
        /// </summary>
        private IView FindViewInArray(ISheet sheet, string targetName)
        {
            try
            {
                object viewsRaw = sheet.GetViews();
                if (viewsRaw is object[] viewArray)
                {
                    foreach (object vObj in viewArray)
                    {
                        var v = vObj as IView;
                        if (v == null) continue;
                        string vName = "";
                        try { vName = v.GetName2() ?? ""; } catch { continue; }
                        if (string.Equals(vName, targetName, StringComparison.OrdinalIgnoreCase))
                            return v;
                    }
                }
            }
            catch { }
            return null;
        }

        private List<string> BuildExtractionOrder(List<string> allViewNames)
        {
            // Targeted test mode: override with explicit list
            if (_targetedExtractionOrder != null && _targetedExtractionOrder.Count > 0)
            {
                var targeted = new List<string>();
                foreach (var name in _targetedExtractionOrder)
                {
                    if (allViewNames.Contains(name))
                        targeted.Add(name);
                }
                return targeted;
            }

            // Production: fragile-first (section, detail, then others)
            var section = new List<string>();
            var detail = new List<string>();
            var other = new List<string>();

            foreach (var name in allViewNames)
            {
                string lower = name.ToLowerInvariant();
                if (lower.Contains("section"))
                    section.Add(name);
                else if (lower.Contains("detail"))
                    detail.Add(name);
                else
                    other.Add(name);
            }

            var result = new List<string>();
            result.AddRange(section);
            result.AddRange(detail);
            result.AddRange(other);
            return result;
        }

        /// <summary>
        /// Extract a specific view by starting a fresh linked-list traversal,
        /// finding the target by name, and extracting immediately at that point.
        /// No IView handles are held across extractions.
        /// Returns null if the target was not found in the traversal.
        /// </summary>
        private DrawingViewData ExtractViewByFreshTraversal(
            IDrawingDoc drawDoc, string targetName, string sheetName,
            double sheetWidth, double sheetHeight, ViewExtractionStatus status)
        {
            Trace($"  [{sheetName}] Fresh traversal for: {targetName}");
            status.Source = "target_fresh_traversal";

            try
            {
                IView view = (IView)drawDoc.GetFirstView();
                while (view != null)
                {
                    string vName = "";
                    try { vName = view.GetName2() ?? ""; } catch { }

                    if (string.Equals(vName, targetName, StringComparison.OrdinalIgnoreCase)
                        && IsRealDrawingViewOnSheet(view, vName, sheetWidth, sheetHeight))
                    {
                        // Found target -- extract immediately
                        Console.WriteLine($"      Extracting view '{targetName}' (source=target_fresh_traversal, type={GetViewType(view)})");
                        return ExtractViewPhased(view, targetName, status);
                    }

                    try { view = (IView)view.GetNextView(); }
                    catch { view = null; }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"      Warning: Fresh traversal failed for '{targetName}': {ex.Message}");
                status.FailedPhase = "fresh_traversal";
                status.FailureMessage = ex.Message;
                return null;
            }

            // Target not found in linked traversal
            Trace($"  [{sheetName}] '{targetName}' not found in fresh traversal");
            status.Source = "not_found_in_traversal";
            return null;
        }

        /// <summary>
        /// Extract a view from ISheet.GetViews() array (fallback for views not
        /// reachable via linked traversal).
        /// </summary>
        private DrawingViewData ExtractViewFromArray(ISheet sheet, string targetName, ViewExtractionStatus status)
        {
            status.Source = "array_fallback";

            try
            {
                IView v = FindViewInArray(sheet, targetName);
                if (v == null)
                {
                    Console.WriteLine($"      Warning: Array fallback could not find '{targetName}'");
                    status.FailedPhase = "array_fallback";
                    status.FailureMessage = "View not found in ISheet.GetViews()";
                    return null;
                }

                Console.WriteLine($"      Extracting view '{targetName}' (source=array_fallback, type={GetViewType(v)})");
                return ExtractViewPhased(v, targetName, status);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"      Warning: Array fallback extraction failed for '{targetName}': {ex.Message}");
                status.FailedPhase = "array_fallback";
                status.FailureMessage = ex.Message;
                return null;
            }
        }

        private bool IsExtractedViewUsable(DrawingViewData viewData)
        {
            if (viewData == null) return false;
            if (viewData.ViewOutline != null && viewData.ViewOutline.Length >= 4) return true;
            if (viewData.ViewPosition != null && viewData.ViewPosition.Length >= 2) return true;
            if (viewData.Annotations != null && viewData.Annotations.Count > 0) return true;
            return false;
        }

        /// <summary>
        /// Strict validation: inspect diagnostics and set status accordingly.
        /// </summary>
        private void ValidateExtraction(DrawingData data)
        {
            var diag = data.Diagnostics;
            if (diag == null) return;

            bool anyFailure = false;

            foreach (var sheetDiag in diag.Sheets)
            {
                // Whole-sheet failure
                if (sheetDiag.Failed)
                {
                    string msg = $"Sheet '{sheetDiag.SheetName}': sheet extraction failed";
                    Console.WriteLine($"  VALIDATION FAILURE: {msg}");
                    diag.Warnings.Add(msg);
                    anyFailure = true;
                    continue;
                }

                // Check: all discovered views should be in extracted set
                int maxDiscovered = Math.Max(sheetDiag.ArrayViewNames.Count, sheetDiag.LinkedViewNames.Count);
                int extracted = sheetDiag.ExtractedViewNames.Count;

                if (sheetDiag.MissingViews.Count > 0)
                {
                    string msg = $"Sheet '{sheetDiag.SheetName}': missing views: {string.Join(", ", sheetDiag.MissingViews)}";
                    Console.WriteLine($"  VALIDATION FAILURE: {msg}");
                    diag.Warnings.Add(msg);
                    anyFailure = true;
                }

                if (extracted == 0 && maxDiscovered > 0)
                {
                    string msg = $"Sheet '{sheetDiag.SheetName}': zero views extracted but {maxDiscovered} discovered";
                    Console.WriteLine($"  VALIDATION FAILURE: {msg}");
                    diag.Warnings.Add(msg);
                    anyFailure = true;
                }

                // Any per-view phase failure on a discovered real view is a hard failure
                foreach (var vs in sheetDiag.ViewStatuses)
                {
                    if (vs.FailedPhase != null)
                    {
                        string msg = $"View '{vs.ViewName}': failed at phase '{vs.FailedPhase}': {vs.FailureMessage}";
                        Console.WriteLine($"  VALIDATION FAILURE: {msg}");
                        diag.Warnings.Add(msg);
                        anyFailure = true;
                    }
                }
            }

            if (anyFailure)
                diag.Status = "failed_validation";
            else if (diag.Warnings.Count > 0)
                diag.Status = "partial";
            else
                diag.Status = "success";
        }

        /// <summary>
        /// Extract data from a single drawing view in explicit phases.
        /// If one phase fails, keep partial data and record which phase failed.
        /// </summary>
        private bool IsFragileViewType(string viewType)
        {
            if (string.IsNullOrEmpty(viewType)) return false;
            string lower = viewType.ToLowerInvariant();
            return lower.Contains("section") || lower.Contains("detail");
        }

        private DrawingViewData ExtractViewPhased(IView view, string viewName, ViewExtractionStatus status)
        {
            var viewData = new DrawingViewData
            {
                ViewName = viewName,
                ViewType = "Unknown",
                ViewScale = 1.0
            };

            // Phase 1: basic metadata (always runs)
            Trace($"    [{viewName}] Phase 1: metadata");
            try
            {
                Trace($"    [{viewName}]   GetName2");
                try { viewData.ViewName = view.GetName2() ?? viewName; } catch { }
                Trace($"    [{viewName}]   GetViewType");
                try { viewData.ViewType = GetViewType(view); } catch { }
                Trace($"    [{viewName}]   GetViewOrientation");
                try { viewData.ViewOrientation = GetViewOrientation(view); } catch { }
                Trace($"    [{viewName}]   GetViewScale");
                try { viewData.ViewScale = GetViewScale(view); } catch { }

                Trace($"    [{viewName}]   GetOutline");
                try
                {
                    var outline = (double[])view.GetOutline();
                    if (outline != null && outline.Length >= 4)
                        viewData.ViewOutline = new double[] { outline[0], outline[1], outline[2], outline[3] };
                }
                catch { }

                Trace($"    [{viewName}]   Position");
                try
                {
                    var pos = (double[])view.Position;
                    if (pos != null && pos.Length >= 2)
                        viewData.ViewPosition = new double[] { pos[0], pos[1] };
                }
                catch { }

                Trace($"    [{viewName}]   ReferencedConfiguration");
                try { viewData.ReferencedConfiguration = view.ReferencedConfiguration; } catch { }

                status.MetadataOk = true;
                Trace($"    [{viewName}] Phase 1: OK");
            }
            catch (Exception ex)
            {
                status.FailedPhase = "metadata";
                status.FailureMessage = ex.Message;
                Trace($"    [{viewName}] Phase 1: FAILED - {ex.Message}");
                return viewData;
            }

            // Determine if this is a fragile view type (section/detail)
            bool fragile = IsFragileViewType(viewData.ViewType) || IsFragileViewType(viewName);

            // Set geometry enrichment gate for downstream helpers
            _skipGeometryEnrichment = fragile && !FRAGILE_EXTRACT_GEOMETRY;
            Trace($"    [{viewName}] fragile={fragile}, skipGeometry={_skipGeometryEnrichment}");

            // Phase 2: non-dimension annotations
            bool doAnnotations = !fragile || FRAGILE_EXTRACT_ANNOTATIONS;
            if (doAnnotations)
            {
                Trace($"    [{viewName}] Phase 2: annotations (fragile={fragile})");
                try
                {
                    Trace($"    [{viewName}]   GetFirstAnnotation3");
                    ExtractNonDimensionAnnotations(view, viewData.Annotations);
                    status.AnnotationsOk = true;
                    Trace($"    [{viewName}] Phase 2: OK ({viewData.Annotations.Count} annotations)");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"      Warning: annotation extraction failed for '{viewName}': {ex.Message}");
                    status.FailedPhase = "annotations";
                    status.FailureMessage = ex.Message;
                    Trace($"    [{viewName}] Phase 2: FAILED - {ex.Message}");
                }
            }
            else
            {
                Trace($"    [{viewName}] Phase 2: SKIPPED (FRAGILE_EXTRACT_ANNOTATIONS=false)");
                status.AnnotationsOk = false;
            }

            // Phase 3: display dimensions
            int dimCount = 0;
            bool doDimensions = !fragile || FRAGILE_EXTRACT_DIMENSIONS;
            if (doDimensions)
            {
                Trace($"    [{viewName}] Phase 3: dimensions (fragile={fragile})");
                try
                {
                    Trace($"    [{viewName}]   GetFirstDisplayDimension5");
                    ExtractDisplayDimensions(view, viewData.Annotations, out dimCount);
                    status.DimensionsOk = true;
                    Trace($"    [{viewName}] Phase 3: OK ({dimCount} dimensions)");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"      Warning: dimension extraction failed for '{viewName}': {ex.Message}");
                    if (status.FailedPhase == null)
                    {
                        status.FailedPhase = "dimensions";
                        status.FailureMessage = ex.Message;
                    }
                    Trace($"    [{viewName}] Phase 3: FAILED - {ex.Message}");
                }
            }
            else
            {
                Trace($"    [{viewName}] Phase 3: SKIPPED (FRAGILE_EXTRACT_DIMENSIONS=false)");
                status.DimensionsOk = false;
            }

            status.AnnotationCount = viewData.Annotations.Count;
            status.DimensionCount = dimCount;

            // Phase 4: native visible primitives (Phase 4+)
            // Conservative first slice:
            // - standard/projected views only
            // - model-edge display data only (GetPolylines7)
            // - never let this phase poison the validated annotation workflow
            if (EXTRACT_VISIBLE_PRIMITIVES && SupportsVisiblePrimitiveExtraction(viewData.ViewType))
            {
                Trace($"    [{viewName}] Phase 4: visible primitives");
                try
                {
                    ExtractVisiblePrimitives(view, viewData);
                    status.PrimitivesOk = true;
                    status.PrimitiveCount = viewData.Primitives.Count;
                    Trace($"    [{viewName}] Phase 4: OK ({viewData.Primitives.Count} primitives)");
                }
                catch (Exception ex)
                {
                    status.PrimitivesOk = false;
                    Trace($"    [{viewName}] Phase 4: FAILED - {ex.Message}");
                    Console.WriteLine($"      Warning: primitive extraction failed for '{viewName}': {ex.Message}");
                }
            }
            else
            {
                Trace($"    [{viewName}] Phase 4: SKIPPED");
                status.PrimitivesOk = false;
            }

            _skipGeometryEnrichment = false;  // Reset for next view

            int totalAnnotations = viewData.Annotations.Count;
            if (totalAnnotations > 0)
            {
                Console.WriteLine($"      View '{viewName}': {totalAnnotations} annotations ({dimCount} dimensions)");
            }

            return viewData;
        }

        private bool SupportsVisiblePrimitiveExtraction(string viewType)
        {
            if (string.IsNullOrWhiteSpace(viewType)) return false;
            string lower = viewType.ToLowerInvariant();
            return lower.Contains("standard")
                || lower.Contains("projected")
                || lower.Contains("named")
                || lower.Contains("detail");
        }

        private void ExtractVisiblePrimitives(IView view, DrawingViewData viewData)
        {
            object polyDataObj = null;
            object edgeArrayObj = view.GetPolylines7(CROSSHATCH_EXCLUDE, out polyDataObj);

            var polyData = CoerceDoubleArray(polyDataObj);
            if (polyData == null || polyData.Length == 0)
                return;

            var edgeArray = CoerceObjectArray(edgeArrayObj);
            var xform = GetViewToSheetTransform(view, viewData);

            int idx = 0;
            int primitiveIndex = 0;
            while (idx < polyData.Length)
            {
                if (idx + 9 > polyData.Length)
                    break;

                int geomType = SafeInt(polyData[idx++]);
                int geomDataSize = SafeInt(polyData[idx++]);
                if (geomDataSize < 0 || idx + geomDataSize > polyData.Length)
                    break;

                double[] geomData = new double[geomDataSize];
                Array.Copy(polyData, idx, geomData, 0, geomDataSize);
                idx += geomDataSize;

                // Line display/style metadata currently ignored for compare.
                if (idx + 7 > polyData.Length)
                    break;
                idx += 6; // color, style, font, weight, layerId, layerOverride

                int numPoints = SafeInt(polyData[idx++]);
                int pointValueCount = Math.Max(numPoints * 3, 0);
                if (idx + pointValueCount > polyData.Length)
                    break;

                var primitive = new DrawingPrimitiveData
                {
                    PrimitiveType = "polyline",
                    SourceKind = edgeArray != null && primitiveIndex < edgeArray.Length && edgeArray[primitiveIndex] != null
                        ? "modelEdge"
                        : "silhouetteEdge",
                    GeometrySource = "tessellated"
                };

                for (int p = 0; p < numPoints; p++)
                {
                    double x = polyData[idx++];
                    double y = polyData[idx++];
                    idx++; // z in view space; not used in 2D overlay
                    primitive.PointsView.Add(new[] { x, y });
                    primitive.PointsSheet.Add(TransformViewPointToSheet(x, y, xform));
                }

                if (geomType == 1 && geomData.Length >= 9)
                {
                    double cx = geomData[0];
                    double cy = geomData[1];
                    double sx = geomData[3];
                    double sy = geomData[4];
                    double ex = geomData[6];
                    double ey = geomData[7];
                    primitive.CenterView = new[] { cx, cy };
                    primitive.CenterSheet = TransformViewPointToSheet(cx, cy, xform);
                    primitive.RadiusView = Distance2D(cx, cy, sx, sy);
                    primitive.RadiusSheet = primitive.RadiusView * xform[2];
                    primitive.GeometrySource = "exact";
                    primitive.PrimitiveType = Distance2D(sx, sy, ex, ey) <= 1e-9 ? "circle" : "arc";
                }
                else if (primitive.PointsView.Count == 2)
                {
                    primitive.PrimitiveType = "line";
                    primitive.GeometrySource = "exact";
                }

                primitive.BoundsView = ComputeBounds(primitive.PointsView);
                primitive.BoundsSheet = ComputeBounds(primitive.PointsSheet);

                if (primitive.PointsView.Count >= 2 || primitive.CenterView != null)
                    viewData.Primitives.Add(primitive);

                primitiveIndex++;
            }
        }

        private double[] GetViewToSheetTransform(IView view, DrawingViewData viewData)
        {
            try
            {
                var xform = CoerceDoubleArray(view.GetXform());
                if (xform != null && xform.Length >= 3)
                    return new[] { xform[0], xform[1], xform[2] };
            }
            catch { }

            double tx = 0.0;
            double ty = 0.0;
            double scale = viewData?.ViewScale > 0 ? viewData.ViewScale : 1.0;
            if (viewData?.ViewPosition != null && viewData.ViewPosition.Length >= 2)
            {
                tx = viewData.ViewPosition[0];
                ty = viewData.ViewPosition[1];
            }
            return new[] { tx, ty, scale };
        }

        private static double[] TransformViewPointToSheet(double x, double y, double[] xform)
        {
            double tx = xform != null && xform.Length >= 1 ? xform[0] : 0.0;
            double ty = xform != null && xform.Length >= 2 ? xform[1] : 0.0;
            double scale = xform != null && xform.Length >= 3 ? xform[2] : 1.0;
            return new[] { tx + x * scale, ty + y * scale };
        }

        private static double[] ComputeBounds(List<double[]> points)
        {
            if (points == null || points.Count == 0)
                return null;

            double minX = double.PositiveInfinity;
            double minY = double.PositiveInfinity;
            double maxX = double.NegativeInfinity;
            double maxY = double.NegativeInfinity;

            foreach (var pt in points)
            {
                if (pt == null || pt.Length < 2)
                    continue;
                minX = Math.Min(minX, pt[0]);
                minY = Math.Min(minY, pt[1]);
                maxX = Math.Max(maxX, pt[0]);
                maxY = Math.Max(maxY, pt[1]);
            }

            if (double.IsInfinity(minX) || double.IsInfinity(minY))
                return null;

            return new[] { minX, minY, maxX, maxY };
        }

        private static double Distance2D(double ax, double ay, double bx, double by)
        {
            double dx = ax - bx;
            double dy = ay - by;
            return Math.Sqrt(dx * dx + dy * dy);
        }

        private static int SafeInt(double value)
        {
            return (int)Math.Round(value);
        }

        private static double[] CoerceDoubleArray(object value)
        {
            if (value is double[] doubles)
                return doubles;
            if (value is object[] objects)
            {
                var result = new double[objects.Length];
                for (int i = 0; i < objects.Length; i++)
                {
                    try { result[i] = Convert.ToDouble(objects[i]); }
                    catch { return null; }
                }
                return result;
            }
            if (value is Array arr)
            {
                var result = new double[arr.Length];
                for (int i = 0; i < arr.Length; i++)
                {
                    try { result[i] = Convert.ToDouble(arr.GetValue(i)); }
                    catch { return null; }
                }
                return result;
            }
            return null;
        }

        private static object[] CoerceObjectArray(object value)
        {
            if (value is object[] objects)
                return objects;
            if (value is Array arr)
            {
                var result = new object[arr.Length];
                for (int i = 0; i < arr.Length; i++)
                    result[i] = arr.GetValue(i);
                return result;
            }
            return null;
        }

        #region Annotation Extraction

        /// <summary>
        /// Extract non-dimension annotations from the IAnnotation chain.
        /// Skips swDisplayDimension type to avoid duplicating what ExtractDisplayDimensions captures.
        /// (Finding #3: dimension duplication fix)
        /// </summary>
        private void ExtractNonDimensionAnnotations(IView view, List<DrawingAnnotationData> annotations)
        {
            IAnnotation ann = null;
            try { ann = (IAnnotation)view.GetFirstAnnotation3(); } catch { }

            int annIndex = 0;
            while (ann != null)
            {
                annIndex++;
                try
                {
                    int rawType = 0;
                    try { rawType = ann.GetType(); } catch { }
                    var annType = (swAnnotationType_e)rawType;

                    string annName = "";
                    try { annName = ann.GetName() ?? ""; } catch { }
                    Trace($"      ann[{annIndex}] type={annType} name={annName}");

                    // Skip display dimensions -- handled by ExtractDisplayDimensions
                    if (annType != swAnnotationType_e.swDisplayDimension)
                    {
                        Trace($"      ann[{annIndex}] GetSpecificAnnotation");
                        var annData = ExtractAnnotation(ann, annType);
                        if (annData != null)
                            annotations.Add(annData);
                        Trace($"      ann[{annIndex}] done");
                    }
                }
                catch (Exception ex)
                {
                    Trace($"      ann[{annIndex}] FAILED: {ex.Message}");
                    Console.WriteLine($"      Warning: Failed to extract annotation: {ex.Message}");
                }

                try { ann = (IAnnotation)ann.GetNext3(); }
                catch { ann = null; }
            }
            Trace($"      annotation chain: {annIndex} total");
        }

        /// <summary>
        /// Extract a single annotation's common fields and type-specific payload.
        /// Output is FLAT " type-specific text fields are promoted to top-level keys
        /// to match the drawing_map.py consumer contract. (Finding #2)
        /// </summary>
        private DrawingAnnotationData ExtractAnnotation(IAnnotation ann, swAnnotationType_e annType)
        {
            if (ann == null) return null;

            var data = new DrawingAnnotationData
            {
                AnnotationName = "",
                AnchorKind = "annotationPosition",
                GeometrySource = "exact",
                Visible = true,
                IsDangling = false
            };

            try { data.AnnotationName = ann.GetName() ?? ""; } catch { }
            try { data.Visible = IsAnnotationVisible(ann); } catch { }
            try { data.IsDangling = IsAnnotationDangling(ann); } catch { }

            AddMatchKey(data.MatchKeys, data.AnnotationName);

            // Position in sheet-space (meters, origin at lower-left)
            try
            {
                var pos = (double[])ann.GetPosition();
                if (pos != null && pos.Length >= 2)
                    data.PositionSheet = new double[] { pos[0], pos[1] };
            }
            catch { }

            // Leader points (skip for fragile views when geometry enrichment is off)
            if (!_skipGeometryEnrichment)
                ExtractLeaderPoints(ann, data.Leaders);

            // Map the annotation type enum to our string identifier
            data.AnnotationType = MapAnnotationType(annType);

            // Type-specific extraction -- promote text to flat top-level keys
            // GetSpecificAnnotation() and the type-specific helpers are deep COM calls
            try
            {
                object specificAnn = ann.GetSpecificAnnotation();

                switch (annType)
                {
                    case swAnnotationType_e.swNote:
                        ExtractNoteFlat(specificAnn as INote, data);
                        break;

                    case swAnnotationType_e.swGTol:
                        ExtractGtolFlat(specificAnn as IGtol, data);
                        break;

                    case swAnnotationType_e.swSFSymbol:
                        ExtractSurfaceFinishFlat(specificAnn as ISFSymbol, data);
                        break;

                    case swAnnotationType_e.swDatumTag:
                        ExtractDatumTagFlat(specificAnn as IDatumTag, data);
                        break;

                    case swAnnotationType_e.swDatumTargetSym:
                        ExtractDatumTargetFlat(specificAnn as IDatumTargetSym, data);
                        break;

                    case swAnnotationType_e.swWeldSymbol:
                        ExtractWeldSymbolFlat(specificAnn as IWeldSymbol, data);
                        break;
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"      Warning: Could not extract specific annotation data for '{data.AnnotationName}': {ex.Message}");
            }

            if (_skipGeometryEnrichment)
                data.GeometrySource = "semantic_only";

            return data;
        }

        /// <summary>
        /// Extract display dimensions using the separate IDisplayDimension traversal.
        /// This is the ONLY path that creates displayDimension annotations. (Finding #3)
        /// </summary>
        private void ExtractDisplayDimensions(IView view, List<DrawingAnnotationData> annotations, out int dimCount)
        {
            dimCount = 0;
            IDisplayDimension dispDim = null;
            Trace($"      dims: GetViewDimensionDisplayStrings");
            var viewDisplayStrings = GetViewDimensionDisplayStrings(view);
            int displayStringIndex = 0;
            Trace($"      dims: GetFirstDisplayDimension5");
            try { dispDim = (IDisplayDimension)view.GetFirstDisplayDimension5(); } catch { }

            int dimIndex = 0;
            while (dispDim != null)
            {
                dimIndex++;
                try
                {
                    string viewDisplayText = null;
                    if (displayStringIndex < viewDisplayStrings.Count)
                        viewDisplayText = viewDisplayStrings[displayStringIndex];

                    Trace($"      dim[{dimIndex}] ExtractDisplayDimension");
                    var annData = ExtractDisplayDimension(dispDim, viewDisplayText);
                    if (annData != null)
                    {
                        annotations.Add(annData);
                        dimCount++;
                    }
                    Trace($"      dim[{dimIndex}] done (name={annData?.AnnotationName})");
                }
                catch (Exception ex)
                {
                    Trace($"      dim[{dimIndex}] FAILED: {ex.Message}");
                    Console.WriteLine($"      Warning: Failed to extract dimension: {ex.Message}");
                }

                try { dispDim = (IDisplayDimension)dispDim.GetNext5(); }
                catch { dispDim = null; }
                displayStringIndex++;
            }
        }

        private List<string> GetViewDimensionDisplayStrings(IView view)
        {
            var result = new List<string>();

            try
            {
                object raw = view.GetDimensionDisplayString4();
                if (raw == null)
                    return result;

                var values = new List<string>();

                if (raw is object[] objArray)
                {
                    foreach (var item in objArray)
                        values.Add(item == null ? "" : item.ToString());
                }
                else if (raw is string[] strArray)
                {
                    values.AddRange(strArray);
                }

                // GetDimensionDisplayString4 returns 10 string slots per dimension.
                for (int i = 0; i + 9 < values.Count; i += 10)
                {
                    var parts = new List<string>();
                    for (int j = 0; j < 10; j++)
                    {
                        string text = values[i + j];
                        if (string.IsNullOrWhiteSpace(text))
                            continue;
                        text = text.Trim();
                        if (!parts.Contains(text))
                            parts.Add(text);
                    }
                    result.Add(string.Join(" ", parts.ToArray()));
                }
            }
            catch { }

            return result;
        }

        /// <summary>
        /// Extract a single display dimension with FLAT output matching consumer contract.
        /// (Finding #2: flatten + Finding #4: correct IsReference/IsDriven)
        /// </summary>
        private DrawingAnnotationData ExtractDisplayDimension(IDisplayDimension dispDim, string viewDisplayText)
        {
            if (dispDim == null) return null;

            Trace($"        ddim: GetAnnotation");
            IAnnotation ann = null;
            try { ann = (IAnnotation)dispDim.GetAnnotation(); } catch { }
            if (ann == null) return null;

            var data = new DrawingAnnotationData
            {
                AnnotationType = "displayDimension",
                AnnotationName = "",
                AnchorKind = "upperLeftTextBox",
                GeometrySource = "exact",
                Visible = true,
                IsDangling = false
            };

            Trace($"        ddim: GetName");
            try { data.AnnotationName = ann.GetName() ?? ""; } catch { }
            try { data.Visible = IsAnnotationVisible(ann); } catch { }
            try { data.IsDangling = IsAnnotationDangling(ann); } catch { }

            AddMatchKey(data.MatchKeys, data.AnnotationName);

            // Position + leader + geometry enrichment -- gated for fragile views
            if (!_skipGeometryEnrichment)
            {
                Trace($"        ddim: GetPosition");
                try
                {
                    var pos = (double[])ann.GetPosition();
                    if (pos != null && pos.Length >= 2)
                        data.PositionSheet = new double[] { pos[0], pos[1] };
                }
                catch { }

                Trace($"        ddim: ExtractLeaderPoints");
                ExtractLeaderPoints(ann, data.Leaders);
            }

            // Dimension text (semantic -- always extracted)
            Trace($"        ddim: GetText(all)");
            try
            {
                data.DimensionText = dispDim.GetText((int)swDimensionTextParts_e.swDimensionTextAll) ?? "";
            }
            catch { }

            if (string.IsNullOrWhiteSpace(data.DimensionText) && !string.IsNullOrWhiteSpace(viewDisplayText))
                data.DimensionText = viewDisplayText;

            if (string.IsNullOrWhiteSpace(data.DimensionText))
            {
                var textParts = new List<string>();
                foreach (swDimensionTextParts_e textPart in new[]
                {
                    swDimensionTextParts_e.swDimensionTextPrefix,
                    swDimensionTextParts_e.swDimensionTextCalloutAbove,
                    swDimensionTextParts_e.swDimensionTextCalloutBelow,
                    swDimensionTextParts_e.swDimensionTextSuffix
                })
                {
                    try
                    {
                        string text = dispDim.GetText((int)textPart) ?? "";
                        if (!string.IsNullOrWhiteSpace(text) && !textParts.Contains(text))
                            textParts.Add(text);
                    }
                    catch { }
                }

                if (textParts.Count > 0)
                    data.DimensionText = string.Join(" ", textParts.ToArray());
            }

            AddMatchKey(data.MatchKeys, data.DimensionText);

            // Geometry enrichment -- gated for fragile views
            if (!_skipGeometryEnrichment)
            {
                Trace($"        ddim: PopulateDisplayDimensionGeometry");
                PopulateDisplayDimensionGeometry(dispDim, data);
            }

            // Dimension type (semantic -- always extracted)
            Trace($"        ddim: Type2");
            try
            {
                var dimType = (swDimensionType_e)dispDim.Type2;
                data.DimensionType = MapDimensionType(dimType);
            }
            catch { }

            // Reference dimension check
            Trace($"        ddim: IsReferenceDim");
            try { data.IsReference = dispDim.IsReferenceDim(); } catch { }

            // Get the IDimension for numeric value and tolerance
            Trace($"        ddim: GetDimension2");
            IDimension dim = null;
            try { dim = (IDimension)dispDim.GetDimension2(0); } catch { }
            if (dim == null)
            {
                Trace($"        ddim: GetDimension (fallback)");
                try { dim = (IDimension)dispDim.GetDimension(); } catch { }
            }

            if (dim != null)
            {
                Trace($"        ddim: GetSystemValue2");
                try
                {
                    data.DimensionValue = dim.GetSystemValue2("");
                }
                catch { }

                if (!data.DimensionValue.HasValue)
                {
                    Trace($"        ddim: SystemValue (fallback)");
                    try { data.DimensionValue = dim.SystemValue; } catch { }
                }

                Trace($"        ddim: FullName");
                try { data.FeatureName = dim.FullName ?? ""; } catch { }
                AddDimensionMatchKeys(dim, data);

                Trace($"        ddim: DrivenState");
                try
                {
                    int drivenState = (int)dim.DrivenState;
                    data.IsDriven = (drivenState == (int)swDimensionDrivenState_e.swDimensionDriven);
                }
                catch { }

                Trace($"        ddim: Tolerance");
                try
                {
                    int tolTypeInt = dim.GetToleranceType();
                    var tolType = (swTolType_e)tolTypeInt;
                    data.ToleranceType = MapToleranceType(tolType);

                    IDimensionTolerance dimTol = (IDimensionTolerance)dim.Tolerance;
                    if (dimTol != null)
                    {
                        data.TolerancePlus = dimTol.GetMaxValue();
                        data.ToleranceMinus = dimTol.GetMinValue();
                    }
                }
                catch { }
            }

            // Mark geometry source when enrichment was intentionally skipped
            if (_skipGeometryEnrichment)
                data.GeometrySource = "semantic_only";

            Trace($"        ddim: complete (name={data.AnnotationName}, geom={data.GeometrySource})");
            return data;
        }

        #endregion

        #region Flat Type-Specific Extractors (Finding #2)

        private void ExtractNoteFlat(INote note, DrawingAnnotationData data)
        {
            if (note == null) return;
            try { data.NoteText = note.GetText() ?? ""; } catch { }
            AddMatchKey(data.MatchKeys, data.NoteText);
            if (!_skipGeometryEnrichment)
                PopulateNoteGeometry(note, data);

            // BOM balloons are represented as notes in the annotation chain.
            // GetBalloonStyle() > 0 alone is NOT sufficient to classify as a balloon "
            // general notes with border shapes (circle, box, triangle) also return > 0.
            // A true BOM balloon has actual BOM text content from GetBomBalloonText().
            // Only reclassify when BOTH the balloon style AND BOM text are present.
            try
            {
                int balloonStyle = note.GetBalloonStyle();
                string bomText = "";
                try { bomText = note.GetBomBalloonText(false) ?? ""; } catch { }

                if (balloonStyle > 0 && !string.IsNullOrWhiteSpace(bomText))
                {
                    // True BOM balloon " reclassify
                    data.AnnotationType = "balloon";
                    data.FeatureName = "Balloon";
                    data.AnchorKind = "upperLeftTextBox";
                    data.GeometrySource = "exact";
                    data.NoteText = bomText;
                    AddMatchKey(data.MatchKeys, data.NoteText);
                }
                else if (balloonStyle > 0)
                {
                    // Note with border style but no BOM text -- keep as note.
                    // Log for diagnostics in case this needs refinement.
                    Console.WriteLine($"        Note '{data.AnnotationName}' has balloonStyle={balloonStyle} but no BOM text -- keeping as note (text: \"{data.NoteText?.Trim()}\")");
                }
            }
            catch { }
        }

        private void ExtractGtolFlat(IGtol gtol, DrawingAnnotationData data)
        {
            if (gtol == null) return;

            var textParts = new List<string>();

            // Extract frame values from the legacy GTol API.
            try
            {
                int frameCount = 0;
                try { frameCount = gtol.GetFrameCount(); } catch { }

                for (short frameNumber = 1; frameNumber <= frameCount; frameNumber++)
                {
                    try
                    {
                        object valuesObj = gtol.GetFrameValues(frameNumber);
                        if (valuesObj is object[] values)
                        {
                            foreach (var value in values)
                            {
                                string text = value as string;
                                if (!string.IsNullOrWhiteSpace(text) && !textParts.Contains(text))
                                    textParts.Add(text);
                            }
                        }
                        else if (valuesObj is string[] stringValues)
                        {
                            foreach (string text in stringValues)
                            {
                                if (!string.IsNullOrWhiteSpace(text) && !textParts.Contains(text))
                                    textParts.Add(text);
                            }
                        }
                    }
                    catch { }
                }
            }
            catch { }

            // Fallback to above/below/prefix/suffix text items when frame values are empty.
            if (textParts.Count == 0)
            {
                foreach (swGTolTextParts_e textPart in Enum.GetValues(typeof(swGTolTextParts_e)))
                {
                    try
                    {
                        string text = gtol.GetText((int)textPart) ?? "";
                        if (!string.IsNullOrWhiteSpace(text) && !textParts.Contains(text))
                            textParts.Add(text);
                    }
                    catch { }
                }
            }

            data.GtolText = string.Join(" | ", textParts.ToArray());
            AddMatchKey(data.MatchKeys, data.GtolText);
            PopulateGtolGeometry(gtol, data);
        }

        private void ExtractSurfaceFinishFlat(ISFSymbol sf, DrawingAnnotationData data)
        {
            if (sf == null) return;

            var textParts = new List<string>();

            foreach (swSurfaceFinishSymbolText_e textPart in Enum.GetValues(typeof(swSurfaceFinishSymbolText_e)))
            {
                try
                {
                    string sfText = sf.GetText((int)textPart) ?? "";
                    if (!string.IsNullOrWhiteSpace(sfText) && !textParts.Contains(sfText))
                        textParts.Add(sfText);
                }
                catch { }
            }

            data.NoteText = string.Join(" ", textParts.ToArray());
            data.FeatureName = "Surface Finish";
            AddMatchKey(data.MatchKeys, data.FeatureName);
            AddMatchKey(data.MatchKeys, data.NoteText);
        }

        private void ExtractDatumTagFlat(IDatumTag datum, DrawingAnnotationData data)
        {
            if (datum == null) return;
            try { data.FeatureName = "Datum " + (datum.GetLabel() ?? ""); } catch { }
            try { data.NoteText = datum.GetLabel() ?? ""; } catch { }
            AddMatchKey(data.MatchKeys, data.FeatureName);
            AddMatchKey(data.MatchKeys, data.NoteText);
        }

        private void ExtractDatumTargetFlat(IDatumTargetSym datumTarget, DrawingAnnotationData data)
        {
            if (datumTarget == null) return;

            var labels = new List<string>();

            // Datum target labels are 0-based in the SolidWorks API.
            for (int index = 0; index < 3; index++)
            {
                try
                {
                    string label = datumTarget.GetDatumReferenceLabel(index) ?? "";
                    if (!string.IsNullOrWhiteSpace(label) && !labels.Contains(label))
                        labels.Add(label);
                }
                catch { }
            }

            if (labels.Count == 0)
            {
                try
                {
                    int textCount = datumTarget.GetTextCount();
                    for (int index = 0; index < textCount; index++)
                    {
                        string text = datumTarget.GetTextAtIndex(index) ?? "";
                        if (!string.IsNullOrWhiteSpace(text) && !labels.Contains(text))
                            labels.Add(text);
                    }
                }
                catch { }
            }

            string combinedLabel = string.Join(", ", labels.ToArray());
            data.FeatureName = string.IsNullOrWhiteSpace(combinedLabel)
                ? "Datum Target"
                : "Datum Target " + combinedLabel;
            data.NoteText = combinedLabel;
            AddMatchKey(data.MatchKeys, data.FeatureName);
            AddMatchKey(data.MatchKeys, data.NoteText);
        }

        /// <summary>
        /// Extract weld symbol text (Finding #6: partial type coverage)
        /// </summary>
        private void ExtractWeldSymbolFlat(IWeldSymbol weld, DrawingAnnotationData data)
        {
            if (weld == null) return;

            var textParts = new List<string>();

            try
            {
                int textCount = weld.GetTextCount();
                for (int index = 0; index < textCount; index++)
                {
                    string text = weld.GetTextAtIndex(index) ?? "";
                    if (!string.IsNullOrWhiteSpace(text) && !textParts.Contains(text))
                        textParts.Add(text);
                }
            }
            catch { }

            data.NoteText = string.Join(" ", textParts.ToArray());
            data.FeatureName = "Weld Symbol";
            AddMatchKey(data.MatchKeys, data.FeatureName);
            AddMatchKey(data.MatchKeys, data.NoteText);
        }

        /// <summary>
        /// Extract balloon text (Finding #6: partial type coverage)
        /// Balloons are INote-based in SolidWorks
        /// </summary>
        private void ExtractBalloonFlat(INote note, DrawingAnnotationData data)
        {
            if (note == null) return;
            try { data.NoteText = note.GetText() ?? ""; } catch { }
            data.FeatureName = "Balloon";
        }

        #endregion

        #region Geometry Helpers

        private void PopulateNoteGeometry(INote note, DrawingAnnotationData data)
        {
            if (note == null || data == null) return;

            data.AnchorKind = "upperLeftTextBox";
            data.GeometrySource = "exact";

            double[] extent = null;
            try { extent = ToDoubleArray(note.GetExtent()); } catch { }
            if (TrySetBoundsFromExtent(extent, data))
            {
                if ((data.PositionSheet == null || data.PositionSheet.Length < 2) && data.BoundsSheet != null)
                    data.PositionSheet = new double[] { data.BoundsSheet[0], data.BoundsSheet[3] };
                data.TextExtent = new double[] { data.BoundsSheet[2] - data.BoundsSheet[0], data.BoundsSheet[3] - data.BoundsSheet[1] };
            }

            try
            {
                int textCount = note.GetTextCount();
                for (int i = 0; i < textCount; i++)
                {
                    int apiIndex = i + 1;
                    string text = TryGetTextAtIndex(() => note.GetTextAtIndex(apiIndex), () => note.GetTextAtIndex(i));
                    double[] position = TryGetPositionAtIndex(() => note.GetTextPositionAtIndex(apiIndex), () => note.GetTextPositionAtIndex(i));
                    double? height = TryGetPositiveDouble(() => note.GetTextHeightAtIndex(apiIndex), () => note.GetTextHeightAtIndex(i));
                    int? refPosition = TryGetInt(() => note.GetTextRefPositionAtIndex(apiIndex), () => note.GetTextRefPositionAtIndex(i));
                    double? angle = TryGetAnyDouble(() => note.GetTextAngleAtIndex(apiIndex), () => note.GetTextAngleAtIndex(i));
                    AddTextRun(data, text, position, height, null, refPosition, angle, "noteTextPosition");
                }
            }
            catch { }
        }

        private void PopulateGtolGeometry(IGtol gtol, DrawingAnnotationData data)
        {
            if (gtol == null || data == null) return;

            double[] textPoint = null;
            try { textPoint = ToDoubleArray(gtol.GetTextPoint()); } catch { }
            if (textPoint != null && textPoint.Length >= 2)
            {
                data.PositionSheet = new double[] { textPoint[0], textPoint[1] };
                data.AnchorKind = "upperLeftBoundingRect";
                data.GeometrySource = "exact";
            }

            try
            {
                int textCount = gtol.GetTextCount();
                for (int i = 0; i < textCount; i++)
                {
                    int apiIndex = i + 1;
                    string text = TryGetTextAtIndex(() => gtol.GetTextAtIndex(apiIndex), () => gtol.GetTextAtIndex(i));
                    double[] offset = TryGetPositionAtIndex(() => gtol.GetTextPositionAtIndex(apiIndex), () => gtol.GetTextPositionAtIndex(i));
                    double[] absolutePosition = AddOffset(textPoint, offset);
                    if (absolutePosition == null)
                        absolutePosition = offset;

                    double? height = TryGetPositiveDouble(() => gtol.GetTextHeightAtIndex(apiIndex), () => gtol.GetTextHeightAtIndex(i));
                    int? refPosition = TryGetInt(() => gtol.GetTextRefPositionAtIndex(apiIndex), () => gtol.GetTextRefPositionAtIndex(i));
                    double? angle = TryGetAnyDouble(() => gtol.GetTextAngleAtIndex(apiIndex), () => gtol.GetTextAngleAtIndex(i));
                    AddTextRun(data, text, absolutePosition, height, null, refPosition, angle, "gtolTextPosition");
                }
            }
            catch { }
        }

        private void PopulateDisplayDimensionGeometry(IDisplayDimension dispDim, DrawingAnnotationData data)
        {
            if (dispDim == null || data == null || data.PositionSheet == null || data.PositionSheet.Length < 2)
                return;

            double? textHeight = null;
            double? textWidth = null;

            try
            {
                IDisplayData displayData = dispDim.GetDisplayData() as IDisplayData;
                if (displayData != null && displayData.GetTextCount() > 0)
                {
                    textHeight = TryGetPositiveDouble(() => displayData.GetTextHeightAtIndex(0));

                    double widthCandidate = 0.0;
                    try { widthCandidate = displayData.GetTextInBoxWidthAtIndex(0); } catch { }
                    if (widthCandidate > 0)
                        textWidth = widthCandidate;

                    double heightCandidate = 0.0;
                    try { heightCandidate = displayData.GetTextInBoxHeightAtIndex(0); } catch { }
                    if (heightCandidate > 0)
                        textHeight = heightCandidate;
                }
            }
            catch { }

            AddTextRun(
                data,
                data.DimensionText,
                data.PositionSheet,
                textHeight,
                textWidth,
                null,
                null,
                "upperLeftTextBox"
            );

            if (textWidth.HasValue && textHeight.HasValue)
                data.TextExtent = new double[] { textWidth.Value, textHeight.Value };
        }

        private bool TrySetBoundsFromExtent(double[] extent, DrawingAnnotationData data)
        {
            if (extent == null || data == null)
                return false;

            if (extent.Length >= 6)
            {
                data.BoundsSheet = new double[]
                {
                    extent[0],
                    extent[1],
                    extent[3],
                    extent[4]
                };
                return true;
            }

            if (extent.Length >= 4)
            {
                data.BoundsSheet = new double[]
                {
                    extent[0],
                    extent[1],
                    extent[2],
                    extent[3]
                };
                return true;
            }

            return false;
        }

        private void AddTextRun(
            DrawingAnnotationData data,
            string text,
            double[] position,
            double? height,
            double? width,
            int? refPosition,
            double? angle,
            string positionKind
        )
        {
            if (data == null)
                return;

            bool hasText = !string.IsNullOrWhiteSpace(text);
            bool hasPosition = position != null && position.Length >= 2;
            bool hasHeight = height.HasValue && height.Value > 0;

            if (!hasText && !hasPosition && !hasHeight)
                return;

            data.TextRuns.Add(new DrawingTextRunData
            {
                Text = string.IsNullOrWhiteSpace(text) ? null : text,
                PositionSheet = hasPosition ? new double[] { position[0], position[1] } : null,
                Height = hasHeight ? height : null,
                Width = width.HasValue && width.Value > 0 ? width : null,
                RefPosition = refPosition,
                Angle = angle,
                PositionKind = string.IsNullOrWhiteSpace(positionKind) ? null : positionKind
            });
        }

        private double[] AddOffset(double[] origin, double[] offset)
        {
            if (origin == null || origin.Length < 2 || offset == null || offset.Length < 2)
                return null;

            return new double[]
            {
                origin[0] + offset[0],
                origin[1] + offset[1]
            };
        }

        private double[] TryGetPositionAtIndex(params Func<object>[] getters)
        {
            foreach (var getter in getters)
            {
                try
                {
                    double[] values = ToDoubleArray(getter());
                    if (values != null && values.Length >= 2)
                        return new double[] { values[0], values[1] };
                }
                catch { }
            }

            return null;
        }

        private string TryGetTextAtIndex(params Func<string>[] getters)
        {
            foreach (var getter in getters)
            {
                try
                {
                    string value = getter();
                    if (!string.IsNullOrWhiteSpace(value))
                        return value;
                }
                catch { }
            }

            return null;
        }

        private double? TryGetPositiveDouble(params Func<double>[] getters)
        {
            foreach (var getter in getters)
            {
                try
                {
                    double value = getter();
                    if (!double.IsNaN(value) && !double.IsInfinity(value) && value > 0)
                        return value;
                }
                catch { }
            }

            return null;
        }

        private double? TryGetAnyDouble(params Func<double>[] getters)
        {
            foreach (var getter in getters)
            {
                try
                {
                    double value = getter();
                    if (!double.IsNaN(value) && !double.IsInfinity(value))
                        return value;
                }
                catch { }
            }

            return null;
        }

        private int? TryGetInt(params Func<int>[] getters)
        {
            foreach (var getter in getters)
            {
                try
                {
                    return getter();
                }
                catch { }
            }

            return null;
        }

        private double[] ToDoubleArray(object value)
        {
            if (value == null)
                return null;

            if (value is double[] doubles)
                return doubles;

            if (value is object[] objArray)
            {
                var result = new List<double>();
                foreach (var item in objArray)
                {
                    if (item == null)
                        continue;

                    try { result.Add(Convert.ToDouble(item)); }
                    catch { }
                }

                return result.Count > 0 ? result.ToArray() : null;
            }

            return null;
        }

        #endregion

        #region Helper Methods

        /// <summary>
        /// Get the referenced model path from the first real drawing view
        /// </summary>
        private string GetReferencedModelPath(IDrawingDoc drawDoc)
        {
            IView view = (IView)drawDoc.GetFirstView();
            // First view is the sheet itself " skip to the first real view
            if (view != null)
                view = (IView)view.GetNextView();
            if (view != null)
                return view.GetReferencedModelName() ?? "";
            return "";
        }

        /// <summary>
        /// Extract leader points from an annotation
        /// </summary>
        private void ExtractLeaderPoints(IAnnotation ann, List<double[]> leaders)
        {
            try
            {
                int leaderCount = ann.GetLeaderCount();
                for (int i = 0; i < leaderCount; i++)
                {
                    var points = (double[])ann.GetLeaderPointsAtIndex(i);
                    if (points != null)
                    {
                        // Points come in triplets (x, y, z)
                        for (int j = 0; j + 2 < points.Length; j += 3)
                        {
                            leaders.Add(new double[] { points[j], points[j + 1], points[j + 2] });
                        }
                    }
                }
            }
            catch { }
        }

        /// <summary>
        /// Check if an annotation is visible.
        /// Checks both the Visible property and layer visibility. (Finding #5)
        /// </summary>
        private bool IsAnnotationVisible(IAnnotation ann)
        {
            try
            {
                int visState = ann.Visible;

                // swAnnotationVisible = 1, swAnnotationHidden = 0
                if (visState != (int)swAnnotationVisibilityState_e.swAnnotationVisible)
                    return false;

                // Also check if the annotation's layer is hidden
                try
                {
                    string layerName = ann.Layer;
                    if (!string.IsNullOrEmpty(layerName))
                    {
                        IModelDoc2 activeDoc = null;
                        try { activeDoc = (IModelDoc2)_swApp.ActiveDoc; } catch { }

                        ILayerMgr layerMgr = null;
                        if (activeDoc != null)
                            layerMgr = activeDoc.GetLayerManager() as ILayerMgr;

                        if (layerMgr != null)
                        {
                            ILayer layer = layerMgr.GetLayer(layerName) as ILayer;
                            if (layer != null && !layer.Visible)
                                return false;
                        }
                    }
                }
                catch { } // Layer check is best-effort

                return true;
            }
            catch { return false; } // Default to NOT visible on error (Finding #5: safer default)
        }

        /// <summary>
        /// Check if an annotation is dangling (attached entities missing or invalid)
        /// </summary>
        private bool IsAnnotationDangling(IAnnotation ann)
        {
            try
            {
                var entities = ann.GetAttachedEntities3();
                var types = (int[])ann.GetAttachedEntityTypes();
                if (entities == null && types == null) return true;
                if (types != null)
                {
                    foreach (var t in types)
                    {
                        if (t == (int)swSelectType_e.swSelNOTHING) return true;
                    }
                }
                return false;
            }
            catch { return false; }
        }

        /// <summary>
        /// Determine if a view is the sheet-level pseudo-view
        /// </summary>
        private bool IsSheetView(IView view)
        {
            try
            {
                var viewType = (swDrawingViewTypes_e)view.Type;
                return viewType == swDrawingViewTypes_e.swDrawingSheet;
            }
            catch { return false; }
        }

        /// <summary>
        /// Filter the real drawing views shown on the sheet from the internal
        /// standard-view palette entries that ISheet.GetViews() can return.
        /// </summary>
        private bool IsRealDrawingViewOnSheet(IView view, string viewName, double sheetWidth, double sheetHeight)
        {
            if (view == null) return false;
            if (IsSheetView(view)) return false;
            if (string.IsNullOrWhiteSpace(viewName)) return false;

            // Internal standard view palette entries are named *Front, *Top, etc.
            // They usually sit off-sheet with negative coordinates and should not
            // become drawing_map views.
            if (viewName.StartsWith("*")) return false;

            try
            {
                var outline = (double[])view.GetOutline();
                if (outline == null || outline.Length < 4) return false;

                double minX = Math.Min(outline[0], outline[2]);
                double maxX = Math.Max(outline[0], outline[2]);
                double minY = Math.Min(outline[1], outline[3]);
                double maxY = Math.Max(outline[1], outline[3]);

                if (maxX <= minX || maxY <= minY) return false;

                // Keep views that intersect the actual sheet. Off-sheet palette
                // views from ISheet.GetViews() are rejected here.
                bool intersectsSheet =
                    maxX >= 0 && minX <= sheetWidth &&
                    maxY >= 0 && minY <= sheetHeight;

                return intersectsSheet;
            }
            catch
            {
                // If the outline cannot be read, do not trust this view object.
                return false;
            }
        }

        /// <summary>
        /// Get the sheet scale as a single ratio (numerator / denominator)
        /// </summary>
        private double GetSheetScale(ISheet sheet)
        {
            try
            {
                var props = (double[])sheet.GetProperties2();
                // props[1] = scale denominator, props[2] = scale numerator
                if (props != null && props.Length >= 3 && props[1] != 0)
                    return props[2] / props[1];
            }
            catch { }
            return 1.0;
        }

        /// <summary>
        /// Get human-readable paper size name from sheet
        /// </summary>
        private string GetPaperSizeName(ISheet sheet)
        {
            try
            {
                double w = 0, h = 0;
                int sizeEnum = sheet.GetSize(ref w, ref h);
                var size = (swDwgPaperSizes_e)sizeEnum;

                switch (size)
                {
                    case swDwgPaperSizes_e.swDwgPaperAsize: return "A";
                    case swDwgPaperSizes_e.swDwgPaperBsize: return "B";
                    case swDwgPaperSizes_e.swDwgPaperCsize: return "C";
                    case swDwgPaperSizes_e.swDwgPaperDsize: return "D";
                    case swDwgPaperSizes_e.swDwgPaperEsize: return "E";
                    case swDwgPaperSizes_e.swDwgPaperA4size: return "A4";
                    case swDwgPaperSizes_e.swDwgPaperA3size: return "A3";
                    case swDwgPaperSizes_e.swDwgPaperA2size: return "A2";
                    case swDwgPaperSizes_e.swDwgPaperA1size: return "A1";
                    case swDwgPaperSizes_e.swDwgPaperA0size: return "A0";
                    default: return "Custom";
                }
            }
            catch { return "Custom"; }
        }

        /// <summary>
        /// Get the view scale as a single ratio
        /// </summary>
        private double GetViewScale(IView view)
        {
            try
            {
                var scale = (double[])view.ScaleRatio;
                if (scale != null && scale.Length >= 2 && scale[1] != 0)
                    return scale[0] / scale[1];
            }
            catch { }
            return 1.0;
        }

        /// <summary>
        /// Get the projection orientation of a drawing view.
        /// Uses IView.GetOrientationName() for user-assigned names, then falls back
        /// to analyzing the ModelToViewTransform to infer standard orthographic orientations.
        /// Returns "Front", "Top", "Right", "Back", "Bottom", "Left", "Isometric",
        /// "Trimetric", "Dimetric", or null if unknown.
        /// </summary>
        private string GetViewOrientation(IView view)
        {
            // Try the named orientation first (e.g. "*Front", "*Top", "*Right", "*Isometric")
            try
            {
                string orientName = view.GetOrientationName();
                if (!string.IsNullOrWhiteSpace(orientName))
                {
                    // SolidWorks prefixes standard orientations with "*"
                    string clean = orientName.TrimStart('*').Trim();
                    if (!string.IsNullOrWhiteSpace(clean))
                        return clean;
                }
            }
            catch { }

            // Section and Detail views don't have standard orientations
            try
            {
                var vt = (swDrawingViewTypes_e)view.Type;
                if (vt == swDrawingViewTypes_e.swDrawingSectionView ||
                    vt == swDrawingViewTypes_e.swDrawingDetailView ||
                    vt == swDrawingViewTypes_e.swDrawingAuxiliaryView)
                    return null;
            }
            catch { }

            // Fallback: analyze the view's model-to-sheet transform to infer orientation.
            // SolidWorks ArrayData is row-major row-vector: [a b c d e f g h i Tx Ty Tz Scale]
            // The local Z-axis (view normal) is indices [6],[7],[8] per codebase convention
            // (see GlbExporter.cs:285 and GeometryAnalyzer.cs:1262).
            try
            {
                var xform = (double[])view.ModelToViewTransform.ArrayData;
                if (xform != null && xform.Length >= 9)
                {
                    double zx = xform[6], zy = xform[7], zz = xform[8];
                    double threshold = 0.9;

                    if (zz > threshold) return "Front";
                    if (zz < -threshold) return "Back";
                    if (zy > threshold) return "Bottom";
                    if (zy < -threshold) return "Top";
                    if (zx > threshold) return "Left";
                    if (zx < -threshold) return "Right";

                    // No dominant axis " likely isometric/trimetric/dimetric
                    double absMax = Math.Max(Math.Abs(zx), Math.Max(Math.Abs(zy), Math.Abs(zz)));
                    if (absMax < 0.8) return "Isometric";
                }
            }
            catch { }

            return null;
        }

        /// <summary>
        /// Extract sheet format data: title block bounds, border insets, revision block,
        /// and the resulting drawable area.
        /// Uses ISheet.TitleBlock and ISheet.RevisionTable properties (not methods).
        /// Border insets derived from sheet format sketch geometry with heuristic fallback.
        /// </summary>
        private SheetFormatData ExtractSheetFormat(IDrawingDoc drawDoc, ISheet sheet, double sheetWidth, double sheetHeight)
        {
            var format = new SheetFormatData();

            // --- Title Block bounds ---
            // ISheet.TitleBlock returns the title block table annotation (property, not method)
            try
            {
                var titleBlockTable = sheet.TitleBlock;
                if (titleBlockTable != null)
                {
                    var tableAnn = (ITableAnnotation)titleBlockTable;
                    int rowCount = tableAnn.RowCount;
                    int colCount = tableAnn.ColumnCount;

                    if (rowCount > 0 && colCount > 0)
                    {
                        try
                        {
                            var ann = (IAnnotation)tableAnn.GetAnnotation();
                            if (ann != null)
                            {
                                var pos = (double[])ann.GetPosition();
                                if (pos != null && pos.Length >= 2)
                                {
                                    double tableX = pos[0];
                                    double tableY = pos[1];

                                    double totalHeight = 0;
                                    for (int r = 0; r < rowCount; r++)
                                    {
                                        try { totalHeight += tableAnn.GetRowHeight(r); } catch { }
                                    }

                                    double totalWidth = 0;
                                    for (int c = 0; c < colCount; c++)
                                    {
                                        try { totalWidth += tableAnn.GetColumnWidth(c); } catch { }
                                    }

                                    if (totalWidth > 0 && totalHeight > 0)
                                    {
                                        // Use AnchorType to determine table growth direction.
                                        // swTableHeaderPosition_e: 0=TopLeft, 1=TopRight, 2=BottomLeft, 3=BottomRight
                                        int anchor = 0; // default: top-left
                                        try { anchor = tableAnn.AnchorType; } catch { }

                                        double x1, x2, y1, y2;
                                        bool anchorIsRight = (anchor == 1 || anchor == 3); // TopRight or BottomRight
                                        bool anchorIsBottom = (anchor == 2 || anchor == 3); // BottomLeft or BottomRight

                                        // X: anchor is left edge ' grows right; anchor is right edge ' grows left
                                        if (anchorIsRight) { x2 = tableX; x1 = tableX - totalWidth; }
                                        else               { x1 = tableX; x2 = tableX + totalWidth; }

                                        // Y: anchor is top ' grows downward (negative Y); anchor is bottom ' grows upward
                                        if (anchorIsBottom) { y1 = tableY; y2 = tableY + totalHeight; }
                                        else                { y2 = tableY; y1 = tableY - totalHeight; }

                                        format.TitleBlockBounds = new double[]
                                        {
                                            Math.Max(0, Math.Min(x1, x2)),
                                            Math.Max(0, Math.Min(y1, y2)),
                                            Math.Min(sheetWidth, Math.Max(x1, x2)),
                                            Math.Min(sheetHeight, Math.Max(y1, y2))
                                        };
                                        Console.WriteLine($"    Title block (anchor={anchor}): ({format.TitleBlockBounds[0]:F4}, {format.TitleBlockBounds[1]:F4}) to ({format.TitleBlockBounds[2]:F4}, {format.TitleBlockBounds[3]:F4})");
                                    }
                                }
                            }
                        }
                        catch (Exception ex) { Console.WriteLine($"    Warning: Title block extent calc failed: {ex.Message}"); }
                    }
                }
            }
            catch { /* No title block table " that's ok */ }

            // --- Revision Table bounds ---
            // ISheet.RevisionTable property (not method)
            try
            {
                var revTable = sheet.RevisionTable;
                if (revTable != null)
                {
                    var tableAnn = (ITableAnnotation)revTable;
                    var ann = (IAnnotation)tableAnn.GetAnnotation();
                    if (ann != null)
                    {
                        var pos = (double[])ann.GetPosition();
                        if (pos != null && pos.Length >= 2)
                        {
                            double totalHeight = 0;
                            for (int r = 0; r < tableAnn.RowCount; r++)
                            {
                                try { totalHeight += tableAnn.GetRowHeight(r); } catch { }
                            }
                            double totalWidth = 0;
                            for (int c = 0; c < tableAnn.ColumnCount; c++)
                            {
                                try { totalWidth += tableAnn.GetColumnWidth(c); } catch { }
                            }

                            if (totalWidth > 0 && totalHeight > 0)
                            {
                                int anchor = 0;
                                try { anchor = tableAnn.AnchorType; } catch { }

                                double x1, x2, y1, y2;
                                bool anchorIsRight = (anchor == 1 || anchor == 3);
                                bool anchorIsBottom = (anchor == 2 || anchor == 3);

                                if (anchorIsRight) { x2 = pos[0]; x1 = pos[0] - totalWidth; }
                                else               { x1 = pos[0]; x2 = pos[0] + totalWidth; }

                                if (anchorIsBottom) { y1 = pos[1]; y2 = pos[1] + totalHeight; }
                                else                { y2 = pos[1]; y1 = pos[1] - totalHeight; }

                                format.RevisionBlockBounds = new double[]
                                {
                                    Math.Max(0, Math.Min(x1, x2)),
                                    Math.Max(0, Math.Min(y1, y2)),
                                    Math.Min(sheetWidth, Math.Max(x1, x2)),
                                    Math.Min(sheetHeight, Math.Max(y1, y2))
                                };
                                Console.WriteLine($"    Revision block (anchor={anchor}): ({format.RevisionBlockBounds[0]:F4}, {format.RevisionBlockBounds[1]:F4}) to ({format.RevisionBlockBounds[2]:F4}, {format.RevisionBlockBounds[3]:F4})");
                            }
                        }
                    }
                }
            }
            catch { /* No revision table " that's ok */ }

            // --- Border insets ---
            // Enter sheet format editing mode to read sketch geometry, then exit.
            // EditTemplate() switches to format editing; EditSheet() switches back.
            // EditSheet() returns void " we just call it in finally to ensure cleanup.
            bool borderFound = false;
            try
            {
                drawDoc.EditTemplate();  // Enter sheet format editing mode

                try
                {
                    var modelDoc = (IModelDoc2)drawDoc;
                    var sketchMgr = modelDoc.SketchManager;
                    var activeSketch = sketchMgr.ActiveSketch;

                    if (activeSketch != null)
                    {
                        var segments = (object[])activeSketch.GetSketchSegments();
                        if (segments != null && segments.Length > 0)
                        {
                            double minX = double.MaxValue, minY = double.MaxValue;
                            double maxX = double.MinValue, maxY = double.MinValue;
                            int lineCount = 0;

                            foreach (var segObj in segments)
                            {
                                var seg = segObj as ISketchSegment;
                                if (seg == null) continue;

                                try
                                {
                                    // Cast to ISketchLine " only succeeds for line segments
                                    var skLine = seg as ISketchLine;
                                    if (skLine == null) continue;

                                    var startPt = skLine.GetStartPoint2() as ISketchPoint;
                                    var endPt = skLine.GetEndPoint2() as ISketchPoint;

                                    if (startPt != null && endPt != null)
                                    {
                                        double x1 = startPt.X, y1 = startPt.Y;
                                        double x2 = endPt.X, y2 = endPt.Y;

                                        bool isHorizontal = Math.Abs(y1 - y2) < 0.0001;
                                        bool isVertical = Math.Abs(x1 - x2) < 0.0001;

                                        if (isHorizontal || isVertical)
                                        {
                                            minX = Math.Min(minX, Math.Min(x1, x2));
                                            minY = Math.Min(minY, Math.Min(y1, y2));
                                            maxX = Math.Max(maxX, Math.Max(x1, x2));
                                            maxY = Math.Max(maxY, Math.Max(y1, y2));
                                            lineCount++;
                                        }
                                    }
                                }
                                catch { }
                            }

                            if (lineCount >= 4 && maxX > minX && maxY > minY)
                            {
                                format.BorderInset = new double[]
                                {
                                    minX,
                                    minY,
                                    sheetWidth - maxX,
                                    sheetHeight - maxY
                                };

                                format.DrawableArea = new double[] { minX, minY, maxX, maxY };
                                borderFound = true;
                                Console.WriteLine($"    Border: ({minX:F4}, {minY:F4}) to ({maxX:F4}, {maxY:F4}) from {lineCount} format lines");
                            }
                        }
                    }
                }
                catch (Exception ex) { Console.WriteLine($"    Warning: Sheet format sketch scan failed: {ex.Message}"); }
                finally
                {
                    // Always exit sheet format mode back to drawing sheet
                    try { drawDoc.EditSheet(); } catch { }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    Warning: Could not enter sheet format mode: {ex.Message}");
                // Ensure we're back in sheet mode even if EditTemplate() threw
                try { drawDoc.EditSheet(); } catch { }
            }

            // Heuristic fallback: approximate border insets by paper size.
            // These are typical values, NOT verified ASME Y14.1 standard dimensions.
            if (!borderFound)
            {
                string paperSize = "";
                try { paperSize = GetPaperSizeName(sheet); } catch { }

                double inset = 0.0095; // ~3/8" = 9.5mm typical margin
                if (paperSize == "A4" || paperSize == "A")
                    inset = 0.00635; // ~1/4" typical for small sheets

                format.BorderInset = new double[] { inset, inset, inset, inset };
                format.DrawableArea = new double[]
                {
                    inset,
                    inset,
                    sheetWidth - inset,
                    sheetHeight - inset
                };
                Console.WriteLine($"    Border: heuristic inset {inset:F4}m for paper size '{paperSize}'");
            }

            return format;
        }

        /// <summary>
        /// Map SolidWorks view type enum to human-readable string
        /// </summary>
        private string GetViewType(IView view)
        {
            try
            {
                var vt = (swDrawingViewTypes_e)view.Type;
                switch (vt)
                {
                    case swDrawingViewTypes_e.swDrawingStandardView: return "Standard";
                    case swDrawingViewTypes_e.swDrawingProjectedView: return "Projected";
                    case swDrawingViewTypes_e.swDrawingSectionView: return "Section";
                    case swDrawingViewTypes_e.swDrawingDetailView: return "Detail";
                    case swDrawingViewTypes_e.swDrawingAuxiliaryView: return "Auxiliary";
                    case swDrawingViewTypes_e.swDrawingRelativeView: return "Relative";
                    case swDrawingViewTypes_e.swDrawingNamedView: return "Named";
                    default: return vt.ToString();
                }
            }
            catch { return "Unknown"; }
        }

        #endregion

        #region Enum Mappers

        private string MapAnnotationType(swAnnotationType_e type)
        {
            switch (type)
            {
                case swAnnotationType_e.swDisplayDimension: return "displayDimension";
                case swAnnotationType_e.swNote: return "note";
                case swAnnotationType_e.swGTol: return "gtol";
                case swAnnotationType_e.swSFSymbol: return "surfaceFinish";
                case swAnnotationType_e.swWeldSymbol: return "weldSymbol";
                case swAnnotationType_e.swWeldBeadSymbol: return "weldBeadSymbol";
                case swAnnotationType_e.swDatumTag: return "datumTag";
                case swAnnotationType_e.swDatumTargetSym: return "datumTarget";
                case swAnnotationType_e.swCenterMarkSym: return "centerMark";
                case swAnnotationType_e.swCenterLine: return "centerLine";
                case swAnnotationType_e.swBlock: return "block";
                case swAnnotationType_e.swCThread: return "cosmeticThread";
                case swAnnotationType_e.swDatumOrigin: return "datumOrigin";
                case swAnnotationType_e.swDowelSym: return "dowelSymbol";
                default: return type.ToString();
            }
        }

        private void AddDimensionMatchKeys(IDimension dim, DrawingAnnotationData data)
        {
            if (dim == null || data == null) return;

            try { AddMatchKey(data.MatchKeys, dim.FullName); } catch { }
            try { AddMatchKey(data.MatchKeys, dim.GetNameForSelection()); } catch { }
            try { AddMatchKey(data.MatchKeys, dim.Name); } catch { }

            try
            {
                var owner = dim.GetFeatureOwner();
                string ownerName = owner != null ? owner.Name : null;
                if (!string.IsNullOrWhiteSpace(ownerName))
                {
                    AddMatchKey(data.MatchKeys, ownerName);

                    // Prefer the owning feature/sketch name over the fully-qualified dimension name.
                    if (string.IsNullOrWhiteSpace(data.FeatureName) || CountNameSegments(data.FeatureName) > CountNameSegments(ownerName))
                        data.FeatureName = ownerName;
                }
            }
            catch { }

            if (string.IsNullOrWhiteSpace(data.FeatureName))
                data.FeatureName = data.AnnotationName;

            AddMatchKey(data.MatchKeys, data.FeatureName);
        }

        private void AddMatchKey(List<string> matchKeys, string rawValue)
        {
            if (matchKeys == null || string.IsNullOrWhiteSpace(rawValue))
                return;

            string value = rawValue.Trim();
            if (!matchKeys.Contains(value))
                matchKeys.Add(value);

            foreach (var variant in ExpandMatchKeyVariants(value))
            {
                if (!matchKeys.Contains(variant))
                    matchKeys.Add(variant);
            }
        }

        private IEnumerable<string> ExpandMatchKeyVariants(string value)
        {
            var variants = new List<string>();
            if (string.IsNullOrWhiteSpace(value))
                return variants;

            string trimmed = value.Trim();

            if (trimmed.Contains("@"))
            {
                string[] segments = trimmed.Split(new[] { '@' }, StringSplitOptions.RemoveEmptyEntries);
                foreach (var segment in segments)
                {
                    string piece = segment.Trim();
                    if (!string.IsNullOrWhiteSpace(piece) && !variants.Contains(piece))
                        variants.Add(piece);
                }

                if (segments.Length > 0)
                {
                    string first = segments[0].Trim();
                    if (!string.IsNullOrWhiteSpace(first) && !variants.Contains(first))
                        variants.Add(first);
                }
            }

            string normalized = trimmed.Replace('_', ' ').Replace('-', ' ');
            if (!string.Equals(normalized, trimmed, StringComparison.Ordinal) && !variants.Contains(normalized))
                variants.Add(normalized);

            return variants;
        }

        private int CountNameSegments(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
                return int.MaxValue;
            return value.Split(new[] { '@' }, StringSplitOptions.RemoveEmptyEntries).Length;
        }

        private string MapDimensionType(swDimensionType_e type)
        {
            switch (type)
            {
                case swDimensionType_e.swLinearDimension: return "linear";
                case swDimensionType_e.swAngularDimension: return "angular";
                case swDimensionType_e.swRadialDimension: return "radial";
                case swDimensionType_e.swDiameterDimension: return "diametric";
                case swDimensionType_e.swOrdinateDimension: return "ordinate";
                case swDimensionType_e.swArcLengthDimension: return "arcLength";
                default: return type.ToString();
            }
        }

        private string MapToleranceType(swTolType_e type)
        {
            switch (type)
            {
                case swTolType_e.swTolNONE: return "none";
                case swTolType_e.swTolBASIC: return "basic";
                case swTolType_e.swTolBILAT: return "bilateral";
                case swTolType_e.swTolSYMMETRIC: return "symmetric";
                case swTolType_e.swTolLIMIT: return "limit";
                case swTolType_e.swTolFIT: return "fit";
                case swTolType_e.swTolFITWITHTOL: return "fitWithTolerance";
                case swTolType_e.swTolFITTOLONLY: return "fitToleranceOnly";
                case swTolType_e.swTolMIN: return "min";
                case swTolType_e.swTolMAX: return "max";
                default: return type.ToString();
            }
        }

        #endregion
    }
}
