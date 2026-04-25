using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorksExtractor.Services;
using SolidWorksExtractor.Models;
using SolidWorksExtractor.Output;

namespace SolidWorksExtractor
{
    /// <summary>
    /// SolidWorks Data Extractor - Extracts comprehensive data from parts and assemblies
    ///
    /// Usage:
    ///   SolidWorksExtractor.exe                         - Extract from active document
    ///   SolidWorksExtractor.exe <file.sldprt>          - Extract from specific part
    ///   SolidWorksExtractor.exe <file.sldasm>          - Extract from specific assembly
    ///   SolidWorksExtractor.exe <file.slddrw>          - Extract from specific drawing
    ///   SolidWorksExtractor.exe --batch-parts <folder> - Batch extract all *.SLDPRT in folder
    ///   SolidWorksExtractor.exe --active               - Extract from active document
    ///   SolidWorksExtractor.exe --help                 - Show help
    ///
    /// Options:
    ///   --output <path>     Output JSON file path (default: same as input with .json)
    ///   --drawing-target-view <name>  Extract only the named drawing view (repeatable)
    ///   --drawing-target-views <list> Extract only the named drawing views (comma/semicolon/pipe separated)
    ///   --batch-parts       Scan folder recursively for *.SLDPRT files and extract all
    ///   --batch-output      Output folder for batch mode (default: same as source)
    ///   --no-parts          Skip extracting part data from assembly components
    ///   --resolve           Resolve lightweight components before extraction
    ///   --start             Start SolidWorks if not running
    ///   --fast              Fast mode: skip geometry analysis and per-config suppression
    ///   --full              Full mode: complete extraction (default)
    ///   --part-glb          Export per-feature colored GLB for a single part
    ///   --fea               Export FEA simulation results (stress GLB + results JSON)
    ///   --fea-list-studies  List all Simulation studies in the document and exit
    ///   --fea-preflight     Print FEA environment + study list (no extraction) and exit
    ///   --fea-study-name <name>   Force FEA extraction to use this study (case-insensitive)
    ///   --fea-study-index <n>     Force FEA extraction to use the study at 0-based index n
    ///   --fea-allow-remesh        If the picked study's mesh is stale, re-mesh + re-solve
    ///                             via study.MeshAndRun() before extraction (modifies analysis state)
    /// </summary>
    class Program
    {
        static int Main(string[] args)
        {
            Console.WriteLine("═══════════════════════════════════════════════════════════════");
            Console.WriteLine("  SolidWorks Data Extractor v1.0");
            Console.WriteLine("  Extracts features, geometry, mates and properties to JSON");
            Console.WriteLine("═══════════════════════════════════════════════════════════════");
            Console.WriteLine();

            // Quick check for colorize-only mode
            if (args.Length > 0 && args[0].ToLower() == "--colorize-only")
            {
                return ColorizeOnly.Run();
            }

            // Parse arguments
            string inputFile = null;
            string outputFile = null;
            string batchPartsFolder = null;
            string batchOutputFolder = null;
            var drawingTargetViews = new List<string>();
            bool useActive = false;
            bool startIfNotRunning = false;
            bool feaListStudies = false;
            bool feaPreflight = false;
            var options = ExtractionOptions.Full();

            for (int i = 0; i < args.Length; i++)
            {
                string arg = args[i].ToLower();

                if (arg == "--help" || arg == "-h" || arg == "/?")
                {
                    ShowHelp();
                    return 0;
                }
                else if (arg == "--active" || arg == "-a")
                {
                    useActive = true;
                }
                else if (arg == "--output" || arg == "-o")
                {
                    if (i + 1 < args.Length)
                        outputFile = args[++i];
                }
                else if (arg == "--drawing-target-view")
                {
                    if (i + 1 < args.Length)
                    {
                        string viewName = args[++i];
                        if (!string.IsNullOrWhiteSpace(viewName))
                            drawingTargetViews.Add(viewName);
                    }
                }
                else if (arg == "--drawing-target-views")
                {
                    if (i + 1 < args.Length)
                    {
                        string rawList = args[++i] ?? "";
                        foreach (var item in rawList.Split(new[] { ',', ';', '|' }, StringSplitOptions.RemoveEmptyEntries))
                        {
                            string viewName = item.Trim();
                            if (!string.IsNullOrWhiteSpace(viewName))
                                drawingTargetViews.Add(viewName);
                        }
                    }
                }
                else if (arg == "--batch-parts")
                {
                    if (i + 1 < args.Length)
                        batchPartsFolder = args[++i];
                }
                else if (arg == "--batch-output")
                {
                    if (i + 1 < args.Length)
                        batchOutputFolder = args[++i];
                }
                else if (arg == "--no-parts")
                {
                    options.ExtractPartsFromAssembly = false;
                }
                else if (arg == "--resolve")
                {
                    options.ResolveLightweight = true;
                }
                else if (arg == "--start")
                {
                    startIfNotRunning = true;
                }
                else if (arg == "--fast")
                {
                    options = ExtractionOptions.Fast();
                    Console.WriteLine("Mode: FAST (skipping geometry analysis and config tracking)");
                }
                else if (arg == "--full")
                {
                    options = ExtractionOptions.Full();
                    Console.WriteLine("Mode: FULL (complete extraction)");
                }
                else if (arg == "--views")
                {
                    options.ExportViews = true;
                }
                else if (arg == "--no-views")
                {
                    options.ExportViews = false;
                }
                else if (arg == "--color-parts")
                {
                    options.ColorParts = true;
                }
                else if (arg == "--no-color-parts")
                {
                    options.ColorParts = false;
                }
                else if (arg == "--export-glb")
                {
                    options.ExportGlb = true;
                }
                else if (arg == "--part-glb")
                {
                    options.ExportPartGlb = true;
                }
                else if (arg == "--fea")
                {
                    options.ExportFea = true;
                }

                else if (arg == "--fea-list-studies")
                {
                    feaListStudies = true;
                }
                else if (arg == "--fea-preflight")
                {
                    feaPreflight = true;
                }
                else if (arg == "--fea-study-name")
                {
                    if (i + 1 >= args.Length)
                    {
                        Console.WriteLine("ERROR: --fea-study-name requires a value (the study name).");
                        return 1;
                    }
                    string nameVal = args[++i];
                    if (string.IsNullOrWhiteSpace(nameVal))
                    {
                        Console.WriteLine("ERROR: --fea-study-name value cannot be empty.");
                        return 1;
                    }
                    options.FeaStudyName = nameVal;
                    options.ExportFea = true; // explicit selection implies extraction is wanted
                }
                else if (arg == "--fea-study-index")
                {
                    if (i + 1 >= args.Length)
                    {
                        Console.WriteLine("ERROR: --fea-study-index requires an integer value.");
                        return 1;
                    }
                    string raw = args[++i];
                    int idx;
                    if (!int.TryParse(raw, out idx))
                    {
                        Console.WriteLine($"ERROR: --fea-study-index requires an integer; got '{raw}'.");
                        return 1;
                    }
                    if (idx < 0)
                    {
                        Console.WriteLine($"ERROR: --fea-study-index must be >= 0; got {idx}.");
                        return 1;
                    }
                    options.FeaStudyIndex = idx;
                    options.ExportFea = true; // explicit selection implies extraction is wanted
                }
                else if (arg == "--fea-allow-remesh")
                {
                    options.AllowRemesh = true;
                }
                else if (!arg.StartsWith("-") && inputFile == null)
                {
                    inputFile = args[i];
                }
            }
            // Handle batch mode
            if (!string.IsNullOrEmpty(batchPartsFolder))
            {
                return RunBatchPartsMode(batchPartsFolder, batchOutputFolder, options, startIfNotRunning);
            }

            // Reject incompatible flag combinations BEFORE any dispatch.
            // Preflight and list-studies are inspect-only single-document modes; they do not
            // make sense when scanning an entire folder, so the combination is a hard error
            // rather than a silent ignore. (Per-document preflight inside batch is out of scope
            // for the FEA worker flow � see FEA_WORKER_README.md.)
            if ((feaPreflight || feaListStudies) && !string.IsNullOrEmpty(batchPartsFolder))
            {
                Console.WriteLine("ERROR: --fea-preflight / --fea-list-studies cannot be combined with --batch-parts.");
                Console.WriteLine("       Run them on a single document (--active or a path to one .sldprt).");
                return 1;
            }

            // If no input file and not using active, default to active
            if (inputFile == null)
            {
                useActive = true;
            }

            // Connect to SolidWorks
            using (var connection = new SolidWorksConnection())
            {
                if (!connection.Connect(startIfNotRunning))
                {
                    Console.WriteLine();
                    Console.WriteLine("ERROR: Could not connect to SolidWorks.");
                    Console.WriteLine("Make sure SolidWorks is running, or use --start flag.");
                    return 1;
                }

                Console.WriteLine($"SolidWorks Version: {connection.GetVersionString()}");
                Console.WriteLine();

                IModelDoc2 doc = null;

                // Get document
                if (useActive)
                {
                    doc = connection.GetActiveDocument();
                    if (doc == null)
                    {
                        Console.WriteLine("ERROR: No active document. Open a part or assembly first.");
                        return 1;
                    }
                    Console.WriteLine($"Using active document: {doc.GetPathName()}");
                }
                else
                {
                    if (!File.Exists(inputFile))
                    {
                        Console.WriteLine($"ERROR: File not found: {inputFile}");
                        return 1;
                    }
                    doc = connection.OpenDocument(inputFile);
                    if (doc == null)
                    {
                        return 1;
                    }
                }

                // Determine output file
                if (string.IsNullOrEmpty(outputFile))
                {
                    string basePath = doc.GetPathName();
                    outputFile = Path.ChangeExtension(basePath, ".json");
                }

                string documentPath = inputFile;
                try
                {
                    string livePath = doc.GetPathName();
                    if (!string.IsNullOrWhiteSpace(livePath))
                        documentPath = livePath;
                }
                catch { }

                // Enable batch mode for performance
                connection.EnableBatchMode(true);

                try
                {
                    int docType = doc.GetType();
                // FEA preflight / list-studies short-circuit. These are inspect-only
                // modes � no extraction, no JSON written, no batch mode side-effects.
                if (feaPreflight || feaListStudies)
                {
                    var simInspect = new SimulationExtractor();
                    if (feaPreflight)
                    {
                        bool addinOk = simInspect.RunPreflight(connection.Application, doc);
                        return addinOk ? 0 : 3;  // 3 = preflight ran but Simulation add-in unavailable
                    }
                    else // feaListStudies
                    {
                        var studies = simInspect.ListStudies(connection.Application, doc);
                        Console.WriteLine();
                        Console.WriteLine($"Studies ({studies.Count}):");
                        if (studies.Count == 0)
                        {
                            Console.WriteLine("  (no studies � Simulation add-in not loaded, or document has none)");
                        }
                        else
                        {
                            foreach (var s in studies)
                            {
                                string name = s.Name ?? "(unnamed)";
                                string type = s.AnalysisTypeLabel ?? "unknown";
                                Console.WriteLine($"  [{s.Index}] '{name}'  type={type}  results={(s.HasResults ? "yes" : "no")}");
                                if (!string.IsNullOrEmpty(s.Note))
                                    Console.WriteLine($"        Note: {s.Note}");
                            }
                        }
                        return 0;
                    }
                }

                    var serializer = new JsonSerializer(indented: true);

                    if (docType == (int)swDocumentTypes_e.swDocPART)
                    {
                        // Extract part
                        Console.WriteLine();
                        Console.WriteLine($"Extracting part data ({options.Mode} mode)...");
                        var partData = ExtractPart(doc, connection, options);

                        // Worker FEA packaging has a strict four-file contract:
                        // part JSON + solver-backed FEA GLB + results JSON + manifest.
                        // Do not emit view PNGs when FEA extraction is enabled.
                        if (options.ExportViews && !options.ExportFea)
                        {
                            Console.WriteLine("  - Exporting view screenshots...");
                            var viewExporter = new ViewExporter();
                            string viewOutputDir = Path.GetDirectoryName(outputFile);
                            string baseName = GetDeterministicPartNumber(partData, Path.GetFileName(doc.GetPathName()));
                            try
                            {
                                // SaveBMP can fail while CommandInProgress=true.
                                connection.EnableBatchMode(false);
                                partData.ViewExports = viewExporter.ExportViews(doc, viewOutputDir, baseName);
                            }
                            finally
                            {
                                connection.EnableBatchMode(true);
                            }
                        }

                        // Export per-feature colored GLB
                        if (options.ExportPartGlb)
                        {
                            Console.WriteLine("  - Exporting per-feature colored GLB...");
                            IPartDoc partDocInterface = doc as IPartDoc;
                            if (partDocInterface != null)
                            {
                                var glbExporter = new GlbExporter();
                                string glbOutputDir = Path.GetDirectoryName(outputFile);
                                string glbPartNumber = GetDeterministicPartNumber(partData, Path.GetFileName(doc.GetPathName()));
                                string glbPath = glbExporter.ExportPartFeatureGlb(partDocInterface, doc, glbOutputDir, glbPartNumber);
                                if (glbPath != null)
                                {
                                    Console.WriteLine($"    Per-feature GLB saved: {Path.GetFileName(glbPath)}");
                                }
                                else
                                {
                                    Console.WriteLine("    Warning: Per-feature GLB export produced no data");
                                }
                            }
                            else
                            {
                                Console.WriteLine("    Warning: Could not cast document to IPartDoc for GLB export");
                            }
                        }

                        // Export FEA simulation results
                        if (options.ExportFea)
                        {
                            Console.WriteLine("  - Extracting FEA simulation results...");
                            var simExtractor = new SimulationExtractor();
                            string feaOutputDir = Path.GetDirectoryName(outputFile);
                            string feaPartNumber = SanitizeFileName(Path.GetFileNameWithoutExtension(outputFile));
                            if (string.IsNullOrWhiteSpace(feaPartNumber) || feaPartNumber == "UNKNOWN")
                                feaPartNumber = GetDeterministicPartNumber(partData, Path.GetFileName(doc.GetPathName()));
                            string feaGlbPath = simExtractor.ExtractSimulation(
                                connection.Application, doc, feaOutputDir, feaPartNumber,
                                options.FeaStudyName, options.FeaStudyIndex, options.AllowRemesh);
                            if (feaGlbPath != null)
                            {
                                Console.WriteLine($"    FEA GLB saved: {Path.GetFileName(feaGlbPath)}");
                            }
                            else
                            {
                                Console.WriteLine("    Error: FEA extraction did not produce a solver-backed GLB/results package.");
                                return 2;
                            }
                        }

                        string json = serializer.Serialize(partData);
                        serializer.SaveToFile(json, outputFile);

                        PrintPartSummary(partData);
                    }
                    else if (docType == (int)swDocumentTypes_e.swDocASSEMBLY)
                    {
                        // Extract assembly
                        Console.WriteLine();
                        Console.WriteLine($"Extracting assembly data ({options.Mode} mode)...");

                        IAssemblyDoc assyDoc = (IAssemblyDoc)doc;

                        // Resolve lightweight if requested
                        if (options.ResolveLightweight)
                        {
                            Console.WriteLine("Resolving lightweight components...");
                            connection.ResolveLightweightComponents(assyDoc);
                        }

                        var assemblyExtractor = new AssemblyExtractor();
                        var assemblyData = assemblyExtractor.ExtractAssembly(doc, options.ExtractPartsFromAssembly);
                        assemblyData.SolidWorksVersion = connection.GetVersionString();

                        // Export assembly view screenshots
                        if (options.ExportViews)
                        {
                            var viewExporter = new ViewExporter();
                            string viewOutputDir = Path.GetDirectoryName(outputFile);
                            string assyName = assemblyData.Identity.AssemblyNumber
                                ?? Path.GetFileNameWithoutExtension(doc.GetPathName());

                            if (options.ColorParts)
                            {
                                // Colorize parts for VLM identification
                                Console.WriteLine("  - Colorizing parts for assembly views...");
                                var colorizer = new PartColorizer();
                                assemblyData.PartColorMapping = colorizer.ApplyColors(assyDoc);

                                // Force graphics redraw so colors are visible in SolidWorks
                                doc.GraphicsRedraw2();
                                doc.ViewZoomtofit2();

                                Console.WriteLine();
                                Console.WriteLine("  ╔══════════════════════════════════════════════════════════╗");
                                Console.WriteLine("  ║  Colors applied! Take screenshots manually in SolidWorks ║");
                                Console.WriteLine("  ║  Press ENTER here when done to restore original colors.  ║");
                                Console.WriteLine("  ╚══════════════════════════════════════════════════════════╝");
                                Console.ReadLine();

                                // Restore original appearances
                                Console.WriteLine("  - Restoring original appearances...");
                                colorizer.RestoreColors(assyDoc);
                                doc.GraphicsRedraw2();
                                Console.WriteLine("  - Original colors restored.");
                            }
                            else
                            {
                                // Standard hidden-lines-removed views
                                Console.WriteLine("  - Exporting assembly view screenshots...");
                                try
                                {
                                    // SaveBMP can fail while CommandInProgress=true.
                                    connection.EnableBatchMode(false);
                                    assemblyData.ViewExports = viewExporter.ExportViews(doc, viewOutputDir, assyName);
                                }
                                finally
                                {
                                    connection.EnableBatchMode(true);
                                }
                            }
                        }

                        // Export colored GLB 3D model
                        if (options.ExportGlb)
                        {
                            Console.WriteLine("  - Exporting colored GLB 3D model...");
                            var glbExporter = new GlbExporter();
                            string glbOutputDir = Path.GetDirectoryName(outputFile);
                            string glbAssyName = assemblyData.Identity.AssemblyNumber
                                ?? Path.GetFileNameWithoutExtension(doc.GetPathName());
                            string glbPath = glbExporter.ExportGlb(assyDoc, glbOutputDir, glbAssyName);
                            if (glbPath != null)
                            {
                                assemblyData.GlbExportPath = Path.GetFileName(glbPath);
                                Console.WriteLine($"    GLB saved: {assemblyData.GlbExportPath}");
                            }
                            else
                            {
                                Console.WriteLine("    Warning: GLB export produced no data");
                            }
                        }

                        string json = serializer.Serialize(assemblyData);
                        serializer.SaveToFile(json, outputFile);

                        PrintAssemblySummary(assemblyData);
                    }
                    else if (docType == (int)swDocumentTypes_e.swDocDRAWING)
                    {
                        // Extract drawing — disable batch mode for correctness.
                        // Drawing APIs are stateful; CommandInProgress=true can cause
                        // GetFirstView()/GetNextView() to silently skip views.
                        Console.WriteLine();
                        Console.WriteLine("Extracting drawing data...");
                        connection.EnableBatchMode(false);

                        if (drawingTargetViews.Count > 0)
                        {
                            Console.WriteLine($"Targeted drawing extraction: {string.Join(", ", drawingTargetViews)}");
                        }

                        var drawingExtractor = new DrawingExtractor(connection.Application, drawingTargetViews);
                        // Pass output dir for breadcrumb trace log
                        string traceDir = !string.IsNullOrEmpty(outputFile)
                            ? Path.GetDirectoryName(outputFile)
                            : Path.GetDirectoryName(documentPath);
                        var drawingData = drawingExtractor.ExtractDrawing(doc, traceDir);

                        // SolidWorksVersion is set inside ExtractDrawing via _swApp.RevisionNumber()
                        // but set it here too as a fallback in case it failed
                        if (string.IsNullOrEmpty(drawingData.SolidWorksVersion))
                            drawingData.SolidWorksVersion = connection.GetVersionString();

                        // Override output filename to use _drawing_map.json suffix
                        string fallbackDocPath = !string.IsNullOrWhiteSpace(documentPath)
                            ? documentPath
                            : drawingData.FilePath;
                        if (string.IsNullOrEmpty(outputFile) || (!string.IsNullOrWhiteSpace(fallbackDocPath) && outputFile == Path.ChangeExtension(fallbackDocPath, ".json")))
                        {
                            string baseName = Path.GetFileNameWithoutExtension(fallbackDocPath);
                            string outputDir = Path.GetDirectoryName(fallbackDocPath);
                            outputFile = Path.Combine(outputDir, baseName + "_drawing_map.json");
                        }

                        string json = serializer.Serialize(drawingData);
                        serializer.SaveToFile(json, outputFile);

                        PrintDrawingSummary(drawingData);

                        // Strict validation — fail loud if incomplete
                        string diagStatus = drawingData.Diagnostics?.Status ?? "success";
                        if (diagStatus == "failed_validation")
                        {
                            Console.WriteLine();
                            Console.WriteLine("═══════════════════════════════════════════════════════════════");
                            Console.WriteLine("  FAILED VALIDATION — extraction is incomplete.");
                            Console.WriteLine($"  Output written: {outputFile}");
                            Console.WriteLine("  Check diagnostics in the output JSON and trace log.");
                            Console.WriteLine("═══════════════════════════════════════════════════════════════");
                            return 2;  // Non-zero exit code for failed validation
                        }
                    }
                    else
                    {
                        Console.WriteLine("ERROR: Unknown document type.");
                        return 1;
                    }

                    Console.WriteLine();
                    Console.WriteLine("═══════════════════════════════════════════════════════════════");
                    Console.WriteLine("  Extraction complete!");
                    Console.WriteLine($"  Output: {outputFile}");
                    Console.WriteLine("═══════════════════════════════════════════════════════════════");

                    return 0;
                }
                finally
                {
                    connection.EnableBatchMode(false);
                }
            }
        }

        /// <summary>
        /// Extract data from a part document
        /// </summary>
        static PartData ExtractPart(IModelDoc2 doc, SolidWorksConnection connection, ExtractionOptions options)
        {
            var partData = new PartData
            {
                FileName = Path.GetFileName(doc.GetPathName()),
                FilePath = doc.GetPathName(),
                ExtractionTime = DateTime.Now,
                SolidWorksVersion = connection.GetVersionString()
            };

            var propertyExtractor = new PropertyExtractor();
            var featureExtractor = new FeatureExtractor();

            Console.WriteLine("  - Extracting identity and properties...");
            partData.Identity = propertyExtractor.ExtractIdentity(doc);

            Console.WriteLine("  - Extracting physical properties...");
            partData.Physical = propertyExtractor.ExtractPhysicalProperties(doc);

            Console.WriteLine("  - Extracting features...");
            partData.Features = featureExtractor.ExtractFeatures(doc);

            Console.WriteLine("  - Extracting sketch dimensions...");
            var sketchExtractor = new SketchExtractor();
            partData.Sketches = sketchExtractor.ExtractSketches(doc);

            // Geometry analysis (skip in fast mode)
            if (options.ExtractGeometry)
            {
                Console.WriteLine("  - Analyzing geometry...");
                var geometryAnalyzer = new GeometryAnalyzer();
                partData.Geometry = geometryAnalyzer.AnalyzeGeometry(doc);
            }
            else
            {
                Console.WriteLine("  - Skipping geometry analysis (fast mode)");
                partData.Geometry = new GeometryGroundTruth();
            }

            Console.WriteLine("  - Extracting configurations...");
            partData.Configurations = propertyExtractor.ExtractConfigurations(doc);

            // Reconcile holes (feature intent + geometry truth)
            if (options.ExtractGeometry)
            {
                Console.WriteLine("  - Reconciling holes (feature + geometry)...");
                var holeReconciler = new HoleReconciler();
                var holeGroups = holeReconciler.ReconcileHoles(
                    partData.Features.HoleWizardHoles,
                    partData.Geometry.Cylinders,
                    partData.Features.Patterns);

                // Populate comparison data
                partData.Comparison.ExtractedAt = partData.ExtractionTime;
                partData.Comparison.HoleGroups = holeGroups;

                // Flatten all hole instances for easy lookup
                foreach (var group in holeGroups)
                {
                    partData.Comparison.AllHoles.AddRange(group.Instances);
                }

                // Add slots from geometry
                foreach (var slot in partData.Geometry.Slots)
                {
                    partData.Comparison.Slots.Add(new SlotInstance
                    {
                        SlotId = slot.Id,
                        Length = DimensionValue.FromMeters(slot.Length),
                        Width = DimensionValue.FromMeters(slot.Width),
                        Depth = DimensionValue.FromMeters(slot.Depth),
                        IsThrough = slot.IsThrough
                    });
                }

                Console.WriteLine($"    Found {holeGroups.Count} hole groups with {partData.Comparison.AllHoles.Count} total instances");
            }

            // Generate verification checklist (skip in fast mode)
            if (options.GenerateChecklist)
            {
                partData.VerificationChecklist = GenerateVerificationChecklist(partData);
            }

            return partData;
        }

        /// <summary>
        /// Generate verification checklist for drawing inspection
        /// Uses reconciled hole groups when available for accurate instance counts
        /// </summary>
        static System.Collections.Generic.List<string> GenerateVerificationChecklist(PartData part)
        {
            var checklist = new System.Collections.Generic.List<string>();

            // Use reconciled hole groups if available (preferred - combines feature intent with geometry truth)
            if (part.Comparison.HoleGroups.Count > 0)
            {
                foreach (var group in part.Comparison.HoleGroups)
                {
                    // Use the canonical callout from reconciler, or build one
                    string callout;
                    if (!string.IsNullOrEmpty(group.Canonical))
                    {
                        callout = group.Canonical;
                    }
                    else
                    {
                        // Build callout from group data
                        if (group.Thread != null && !string.IsNullOrEmpty(group.Thread.Callout))
                        {
                            callout = $"Thread: {group.Thread.Callout}";
                            if (group.HoleType == "Through")
                                callout += " THRU";
                        }
                        else
                        {
                            double diamMm = group.Diameter?.Millimeters ?? 0;
                            callout = $"Hole: ø{diamMm:F2}mm";
                            if (group.HoleType == "Through")
                                callout += " THRU";
                            else if (group.Depth != null && group.Depth.Millimeters > 0)
                                callout += $" x {group.Depth.Millimeters:F1}mm DEEP";
                        }

                        if (group.Counterbore != null)
                            callout += $" with {group.Counterbore.Callout}";
                        if (group.Countersink != null)
                            callout += $" with {group.Countersink.Callout}";

                        if (group.Count > 1)
                            callout += $" ({group.Count}X)";
                    }

                    // Add pattern info if present
                    if (group.Pattern != null && !string.IsNullOrEmpty(group.Pattern.Canonical))
                    {
                        callout += $" - {group.Pattern.Canonical}";
                    }

                    // Add confidence indicator for low-confidence detections
                    if (group.Confidence == "Low")
                        callout += " [verify]";

                    checklist.Add(callout);
                }
            }
            else
            {
                // Fallback: use raw feature data (legacy behavior)
                foreach (var hole in part.Features.HoleWizardHoles)
                {
                    if (hole.IsSuppressed) continue;

                    double diamMm = hole.Diameter * 1000;
                    double depthMm = hole.Depth * 1000;

                    if (hole.IsTapped)
                    {
                        string callout = $"Thread callout: {hole.ThreadSize ?? hole.FastenerSize}";
                        if (hole.IsThrough)
                            callout += " THRU";
                        else if (depthMm > 0)
                            callout += $" x {depthMm:F1}mm deep";
                        if (hole.InstanceCount > 1)
                            callout += $" ({hole.InstanceCount}X)";
                        checklist.Add(callout);
                    }
                    else
                    {
                        string callout = $"Hole: ø{diamMm:F2}mm";
                        if (hole.IsThrough)
                            callout += " THRU";
                        else if (depthMm > 0)
                            callout += $" x {depthMm:F1}mm deep";

                        if (hole.CounterboreDiameter > 0)
                        {
                            double cbDiaMm = hole.CounterboreDiameter * 1000;
                            double cbDepthMm = hole.CounterboreDepth * 1000;
                            callout += $" with C'bore ø{cbDiaMm:F2}mm x {cbDepthMm:F1}mm";
                        }

                        if (hole.CountersinkDiameter > 0)
                        {
                            double csDiaMm = hole.CountersinkDiameter * 1000;
                            callout += $" with C'sink ø{csDiaMm:F2}mm x {hole.CountersinkAngle:F0}°";
                        }

                        if (hole.InstanceCount > 1)
                            callout += $" ({hole.InstanceCount}X)";

                        checklist.Add(callout);
                    }
                }

                // Add geometry-derived holes not captured by features
                foreach (var cyl in part.Geometry.Cylinders)
                {
                    if (!cyl.IsInternal) continue;

                    double diamMm = cyl.Diameter * 1000;

                    bool alreadyListed = false;
                    foreach (var existing in checklist)
                    {
                        if (existing.Contains($"ø{diamMm:F2}mm"))
                        {
                            alreadyListed = true;
                            break;
                        }
                    }

                    if (!alreadyListed && diamMm > 1)
                    {
                        string callout = $"Verify hole: ø{diamMm:F2}mm";
                        if (cyl.IsThrough)
                            callout += " (through)";
                        if (cyl.HasThread)
                            callout += " (threaded)";
                        checklist.Add(callout);
                    }
                }
            }

            // Add fillet callouts
            foreach (var fillet in part.Features.Fillets)
            {
                if (fillet.IsSuppressed) continue;
                double radiusMm = fillet.Radius * 1000;
                if (radiusMm > 0.5)
                {
                    checklist.Add($"Fillet: R{radiusMm:F2}mm");
                }
            }

            // Add chamfer callouts
            foreach (var chamfer in part.Features.Chamfers)
            {
                if (chamfer.IsSuppressed) continue;
                double distMm = chamfer.Distance * 1000;
                if (distMm > 0.5)
                {
                    if (chamfer.ChamferType == "Angle-Distance")
                        checklist.Add($"Chamfer: {distMm:F2}mm x {chamfer.Angle:F0}°");
                    else
                        checklist.Add($"Chamfer: {distMm:F2}mm x {chamfer.Distance2 * 1000:F2}mm");
                }
            }

            // Add slot callouts
            foreach (var slot in part.Comparison.Slots)
            {
                double lengthMm = slot.Length?.Millimeters ?? 0;
                double widthMm = slot.Width?.Millimeters ?? 0;
                if (lengthMm > 0 && widthMm > 0)
                {
                    string callout = $"Slot: {lengthMm:F1}mm x {widthMm:F1}mm";
                    if (slot.IsThrough)
                        callout += " THRU";
                    else if (slot.Depth != null && slot.Depth.Millimeters > 0)
                        callout += $" x {slot.Depth.Millimeters:F1}mm DEEP";
                    checklist.Add(callout);
                }
            }

            return checklist;
        }

        /// <summary>
        /// Print part extraction summary
        /// </summary>
        static void PrintPartSummary(PartData part)
        {
            Console.WriteLine();
            Console.WriteLine("─── Part Summary ───────────────────────────────────────────────");
            Console.WriteLine($"  Part Number: {part.Identity.PartNumber ?? "N/A"}");
            Console.WriteLine($"  Description: {part.Identity.Description ?? "N/A"}");
            Console.WriteLine($"  Material: {part.Physical.AssignedMaterial ?? part.Identity.Material ?? "N/A"}");
            Console.WriteLine();
            Console.WriteLine("  Features extracted:");
            Console.WriteLine($"    - Hole Wizard holes: {part.Features.HoleWizardHoles.Count}");
            Console.WriteLine($"    - Extrudes: {part.Features.Extrudes.Count}");
            Console.WriteLine($"    - Cuts: {part.Features.Cuts.Count}");
            Console.WriteLine($"    - Fillets: {part.Features.Fillets.Count}");
            Console.WriteLine($"    - Chamfers: {part.Features.Chamfers.Count}");
            Console.WriteLine($"    - Patterns: {part.Features.Patterns.Count}");
            Console.WriteLine($"    - Sheet metal: {part.Features.SheetMetal.Count}");
            Console.WriteLine();
            Console.WriteLine("  Geometry analysis:");
            Console.WriteLine($"    - Cylindrical features: {part.Geometry.Cylinders.Count}");
            Console.WriteLine($"    - Planar faces: {part.Geometry.PlanarFaces.Count}");
            Console.WriteLine();
            Console.WriteLine($"  Verification checklist items: {part.VerificationChecklist.Count}");
        }

        /// <summary>
        /// Print assembly extraction summary
        /// </summary>
        static void PrintAssemblySummary(AssemblyData assy)
        {
            Console.WriteLine();
            Console.WriteLine("─── Assembly Summary ───────────────────────────────────────────");
            Console.WriteLine($"  Assembly: {assy.Identity.AssemblyNumber ?? assy.FileName}");
            Console.WriteLine($"  Description: {assy.Identity.Description ?? "N/A"}");
            Console.WriteLine();
            Console.WriteLine("  Components:");
            Console.WriteLine($"    - Total: {assy.Statistics.TotalComponents}");
            Console.WriteLine($"    - Unique parts: {assy.Statistics.UniquePartCount}");
            Console.WriteLine($"    - Sub-assemblies: {assy.Statistics.SubAssemblyCount}");
            Console.WriteLine($"    - Resolved: {assy.Statistics.ResolvedCount}");
            Console.WriteLine($"    - Lightweight: {assy.Statistics.LightweightCount}");
            Console.WriteLine($"    - Suppressed: {assy.Statistics.SuppressedCount}");
            Console.WriteLine();
            Console.WriteLine($"  Mates: {assy.Statistics.TotalMates}");
            foreach (var kvp in assy.Statistics.MateTypeCounts)
            {
                Console.WriteLine($"    - {kvp.Key}: {kvp.Value}");
            }
            Console.WriteLine();
            Console.WriteLine($"  Part data extracted: {assy.PartDataCache.Count} unique parts");

            // Assembly-level features
            int assyFeatureTotal = assy.AssemblyFeatures.HoleWizardHoles.Count +
                                   assy.AssemblyFeatures.Extrudes.Count +
                                   assy.AssemblyFeatures.Cuts.Count +
                                   assy.AssemblyFeatures.Fillets.Count +
                                   assy.AssemblyFeatures.Chamfers.Count;
            if (assyFeatureTotal > 0)
            {
                Console.WriteLine();
                Console.WriteLine("  Assembly-level features (machining):");
                if (assy.AssemblyFeatures.HoleWizardHoles.Count > 0)
                    Console.WriteLine($"    - Hole Wizard holes: {assy.AssemblyFeatures.HoleWizardHoles.Count}");
                if (assy.AssemblyFeatures.Extrudes.Count > 0)
                    Console.WriteLine($"    - Extrudes: {assy.AssemblyFeatures.Extrudes.Count}");
                if (assy.AssemblyFeatures.Cuts.Count > 0)
                    Console.WriteLine($"    - Cuts: {assy.AssemblyFeatures.Cuts.Count}");
                if (assy.AssemblyFeatures.Fillets.Count > 0)
                    Console.WriteLine($"    - Fillets: {assy.AssemblyFeatures.Fillets.Count}");
                if (assy.AssemblyFeatures.Chamfers.Count > 0)
                    Console.WriteLine($"    - Chamfers: {assy.AssemblyFeatures.Chamfers.Count}");
                if (assy.AssemblyFeatures.Patterns.Count > 0)
                    Console.WriteLine($"    - Patterns: {assy.AssemblyFeatures.Patterns.Count}");
            }

            // Color mapping
            if (assy.PartColorMapping.Count > 0)
            {
                Console.WriteLine();
                Console.WriteLine($"  Part colorization: {assy.PartColorMapping.Count} parts colored");
                foreach (var kvp in assy.PartColorMapping)
                {
                    Console.WriteLine($"    {kvp.Value}  {kvp.Key}");
                }
            }
        }

        /// <summary>
        /// Print drawing extraction summary
        /// </summary>
        static void PrintDrawingSummary(Models.DrawingData drawing)
        {
            Console.WriteLine();
            Console.WriteLine("--- Drawing Summary --------------------------------------------------------");
            Console.WriteLine($"  File: {drawing.FileName}");
            Console.WriteLine($"  Referenced model: {drawing.ReferencedModelPath ?? "N/A"}");
            Console.WriteLine($"  Sheets: {drawing.Sheets.Count}");

            int totalViews = 0;
            int totalAnnotations = 0;
            int totalDimensions = 0;

            foreach (var sheet in drawing.Sheets)
            {
                int sheetDimensions = 0;
                int sheetViewAnnotations = 0;

                foreach (var view in sheet.Views)
                {
                    sheetViewAnnotations += view.Annotations.Count;
                    foreach (var ann in view.Annotations)
                    {
                        if (ann.AnnotationType == "displayDimension")
                            sheetDimensions++;
                    }
                }

                totalViews += sheet.Views.Count;
                totalAnnotations += sheetViewAnnotations;
                totalDimensions += sheetDimensions;

                Console.WriteLine();
                Console.WriteLine($"  Sheet '{sheet.SheetName}' ({sheet.PaperSize}, {sheet.SheetWidth * 1000:F0}x{sheet.SheetHeight * 1000:F0}mm, scale {sheet.Scale:G3}:1):");
                Console.WriteLine($"    Views: {sheet.Views.Count}");

                foreach (var view in sheet.Views)
                {
                    Console.WriteLine($"      - {view.ViewName} ({view.ViewType}, scale {view.ViewScale:G3}:1, {view.Annotations.Count} annotations)");
                }

                Console.WriteLine($"    Dimensions: {sheetDimensions}, Other annotations: {sheetViewAnnotations - sheetDimensions}");
            }

            Console.WriteLine();
            Console.WriteLine($"  Totals: {totalViews} views, {totalAnnotations} annotations, {totalDimensions} dimensions");
        }

        /// <summary>
        /// Run batch extraction on all *.SLDPRT files in a folder
        /// </summary>
        static int RunBatchPartsMode(string sourceFolder, string outputFolder, ExtractionOptions options, bool startIfNotRunning)
        {
            Console.WriteLine("═══════════════════════════════════════════════════════════════");
            Console.WriteLine("  BATCH MODE: Parts Only");
            Console.WriteLine("═══════════════════════════════════════════════════════════════");
            Console.WriteLine();

            // Validate source folder
            if (!Directory.Exists(sourceFolder))
            {
                Console.WriteLine($"ERROR: Source folder not found: {sourceFolder}");
                return 1;
            }

            // Use source folder as output if not specified
            if (string.IsNullOrEmpty(outputFolder))
            {
                outputFolder = sourceFolder;
            }

            // Ensure output folder exists
            if (!Directory.Exists(outputFolder))
            {
                Directory.CreateDirectory(outputFolder);
            }

            Console.WriteLine($"  Source folder: {sourceFolder}");
            Console.WriteLine($"  Output folder: {outputFolder}");
            Console.WriteLine();

            // Find all SLDPRT files recursively
            var partFiles = Directory.GetFiles(sourceFolder, "*.SLDPRT", SearchOption.AllDirectories)
                .OrderBy(f => f)
                .ToList();

            Console.WriteLine($"  Found {partFiles.Count} part files");
            Console.WriteLine();

            if (partFiles.Count == 0)
            {
                Console.WriteLine("No part files found. Nothing to do.");
                return 0;
            }

            // Initialize batch index
            var batchIndex = new BatchIndex
            {
                BatchStartTime = DateTime.Now,
                SourceFolder = sourceFolder,
                OutputFolder = outputFolder,
                TotalFilesFound = partFiles.Count
            };

            // Connect to SolidWorks
            using (var connection = new SolidWorksConnection())
            {
                if (!connection.Connect(startIfNotRunning))
                {
                    Console.WriteLine();
                    Console.WriteLine("ERROR: Could not connect to SolidWorks.");
                    Console.WriteLine("Make sure SolidWorks is running, or use --start flag.");
                    return 1;
                }

                Console.WriteLine($"SolidWorks Version: {connection.GetVersionString()}");
                Console.WriteLine();

                // Enable batch mode for performance
                connection.EnableBatchMode(true);

                var serializer = new JsonSerializer(indented: true);
                int current = 0;

                foreach (var partFile in partFiles)
                {
                    current++;
                    string fileName = Path.GetFileName(partFile);
                    Console.WriteLine($"[{current}/{partFiles.Count}] Processing: {fileName}");

                    try
                    {
                        // Open with UI visible when views are needed, otherwise silent
                        IModelDoc2 doc;
                        int errors, warnings;
                        if (options.ExportViews)
                        {
                            doc = connection.OpenDocument(partFile, readOnly: true, silent: false);
                            errors = 0;
                            warnings = 0;
                        }
                        else
                        {
                            (doc, errors, warnings) = connection.OpenDocumentSilent(partFile);
                        }

                        if (doc == null)
                        {
                            Console.WriteLine($"  FAILED: Could not open (error={errors}, warning={warnings})");
                            batchIndex.Failures.Add(new FailureRecord
                            {
                                SourceFilePath = partFile,
                                SourceFileName = fileName,
                                FailureTime = DateTime.Now,
                                SwErrorCode = errors,
                                ErrorMessage = $"Failed to open document (error={errors}, warning={warnings})",
                                FailureStage = "Open"
                            });
                            batchIndex.FailureCount++;
                            continue;
                        }

                        try
                        {
                            // Guard: verify it's actually a part
                            int docType = doc.GetType();
                            if (docType != (int)swDocumentTypes_e.swDocPART)
                            {
                                Console.WriteLine($"  SKIPPED: Not a part document (type={docType})");
                                batchIndex.SkippedCount++;
                                continue;
                            }

                            // Force rebuild
                            Console.WriteLine("  - Rebuilding...");
                            connection.ForceRebuild(doc);

                            // Extract
                            Console.WriteLine("  - Extracting...");
                            var partData = ExtractPart(doc, connection, options);

                            // Determine output filename using identity fallback
                            string partNumber = GetDeterministicPartNumber(partData, fileName);

                            // Export view screenshots in batch mode
                            if (options.ExportViews)
                            {
                                Console.WriteLine("  - Exporting views...");
                                var viewExporter = new ViewExporter();
                                try
                                {
                                    // SaveBMP can fail while CommandInProgress=true.
                                    connection.EnableBatchMode(false);
                                    partData.ViewExports = viewExporter.ExportViews(doc, outputFolder, partNumber);
                                }
                                finally
                                {
                                    connection.EnableBatchMode(true);
                                }
                            }

                            // Export per-feature colored GLB in batch mode
                            if (options.ExportPartGlb)
                            {
                                Console.WriteLine("  - Exporting per-feature GLB...");
                                IPartDoc partDocInterface = doc as IPartDoc;
                                if (partDocInterface != null)
                                {
                                    var glbExporter = new GlbExporter();
                                    string glbPath = glbExporter.ExportPartFeatureGlb(partDocInterface, doc, outputFolder, partNumber);
                                    if (glbPath != null)
                                        Console.WriteLine($"    GLB saved: {Path.GetFileName(glbPath)}");
                                    else
                                        Console.WriteLine("    Warning: Per-feature GLB produced no data");
                                }
                            }

                            // Export FEA simulation results in batch mode
                            if (options.ExportFea)
                            {
                                Console.WriteLine("  - Extracting FEA simulation results...");
                                var simExtractor = new SimulationExtractor();
                                string feaGlbPath = simExtractor.ExtractSimulation(
                                    connection.Application, doc, outputFolder, partNumber,
                                    options.FeaStudyName, options.FeaStudyIndex, options.AllowRemesh);
                                if (feaGlbPath != null)
                                    Console.WriteLine($"    FEA GLB saved: {Path.GetFileName(feaGlbPath)}");
                                else
                                    Console.WriteLine("    FEA: No simulation data (skipped)");
                            }

                            string jsonFileName = $"{partNumber}.json";
                            string jsonPath = Path.Combine(outputFolder, jsonFileName);

                            // Handle duplicates by appending counter
                            int counter = 1;
                            while (File.Exists(jsonPath))
                            {
                                jsonFileName = $"{partNumber}_{counter++}.json";
                                jsonPath = Path.Combine(outputFolder, jsonFileName);
                            }

                            // Serialize and save
                            Console.WriteLine($"  - Writing: {jsonFileName}");
                            string json = serializer.Serialize(partData);
                            serializer.SaveToFile(json, jsonPath);

                            // Create index record
                            var record = new IndexRecord
                            {
                                SourceFilePath = partFile,
                                SourceFileName = fileName,
                                PartNumber = partNumber,
                                Description = partData.Identity.Description,
                                Material = partData.Physical.AssignedMaterial ?? partData.Identity.Material,
                                ExtractionTime = DateTime.Now,
                                JsonFilePath = jsonPath,
                                JsonFileName = jsonFileName,
                                ExtractorVersion = partData.ExtractorVersion,
                                SchemaVersion = partData.SchemaVersion,
                                HoleCount = partData.Comparison.AllHoles.Count,
                                FeatureCount = partData.Features.HoleWizardHoles.Count +
                                              partData.Features.Extrudes.Count +
                                              partData.Features.Cuts.Count +
                                              partData.Features.Fillets.Count +
                                              partData.Features.Chamfers.Count,
                                JsonFileSize = new FileInfo(jsonPath).Length
                            };

                            batchIndex.Records.Add(record);
                            batchIndex.SuccessCount++;

                            Console.WriteLine($"  SUCCESS: {partNumber}");
                        }
                        catch (Exception ex)
                        {
                            Console.WriteLine($"  FAILED: {ex.Message}");
                            batchIndex.Failures.Add(new FailureRecord
                            {
                                SourceFilePath = partFile,
                                SourceFileName = fileName,
                                FailureTime = DateTime.Now,
                                ErrorMessage = ex.Message,
                                FailureStage = "Extract"
                            });
                            batchIndex.FailureCount++;
                        }
                        finally
                        {
                            // Always close the document
                            connection.CloseDocument(doc);
                        }
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine($"  FAILED: {ex.Message}");
                        batchIndex.Failures.Add(new FailureRecord
                        {
                            SourceFilePath = partFile,
                            SourceFileName = fileName,
                            FailureTime = DateTime.Now,
                            ErrorMessage = ex.Message,
                            FailureStage = "Open"
                        });
                        batchIndex.FailureCount++;
                    }

                    Console.WriteLine();
                }

                connection.EnableBatchMode(false);
            }

            // Finalize batch index
            batchIndex.BatchEndTime = DateTime.Now;

            // Write batch index
            string indexPath = Path.Combine(outputFolder, "_batch_index.json");
            var indexSerializer = new JsonSerializer(indented: true);
            string indexJson = indexSerializer.SerializeBatchIndex(batchIndex);
            indexSerializer.SaveToFile(indexJson, indexPath);

            // Print summary
            Console.WriteLine("═══════════════════════════════════════════════════════════════");
            Console.WriteLine("  BATCH COMPLETE");
            Console.WriteLine("═══════════════════════════════════════════════════════════════");
            Console.WriteLine($"  Total files:    {batchIndex.TotalFilesFound}");
            Console.WriteLine($"  Successful:     {batchIndex.SuccessCount}");
            Console.WriteLine($"  Failed:         {batchIndex.FailureCount}");
            Console.WriteLine($"  Skipped:        {batchIndex.SkippedCount}");
            Console.WriteLine($"  Duration:       {(batchIndex.BatchEndTime - batchIndex.BatchStartTime).TotalMinutes:F1} minutes");
            Console.WriteLine();
            Console.WriteLine($"  Index file:     {indexPath}");
            Console.WriteLine("═══════════════════════════════════════════════════════════════");

            return batchIndex.FailureCount > 0 ? 1 : 0;
        }

        /// <summary>
        /// Get deterministic part number with fallback chain:
        /// 1. identity.PartNumber (already populated from various props)
        /// 2. PART_NUMBER custom property
        /// 3. ID custom property
        /// 4. Filename without extension
        /// </summary>
        static string GetDeterministicPartNumber(PartData partData, string fileName)
        {
            // 1. Already-populated PartNumber (from PropertyExtractor)
            if (!string.IsNullOrWhiteSpace(partData.Identity.PartNumber))
            {
                return SanitizeFileName(partData.Identity.PartNumber);
            }

            // 2. Try PART_NUMBER from custom properties
            if (partData.Identity.CustomProperties != null)
            {
                if (partData.Identity.CustomProperties.TryGetValue("PART_NUMBER", out string pn) && !string.IsNullOrWhiteSpace(pn))
                {
                    return SanitizeFileName(pn);
                }
            }

            // 3. Try ID from custom properties
            if (partData.Identity.CustomProperties != null)
            {
                if (partData.Identity.CustomProperties.TryGetValue("ID", out string id) && !string.IsNullOrWhiteSpace(id))
                {
                    return SanitizeFileName(id);
                }
            }

            // 4. Fallback to filename without extension
            return SanitizeFileName(Path.GetFileNameWithoutExtension(fileName));
        }

        /// <summary>
        /// Sanitize a string for use as a filename
        /// </summary>
        static string SanitizeFileName(string name)
        {
            if (string.IsNullOrWhiteSpace(name))
                return "UNKNOWN";

            // Remove invalid filename characters
            char[] invalid = Path.GetInvalidFileNameChars();
            foreach (char c in invalid)
            {
                name = name.Replace(c, '_');
            }

            // Trim and remove leading/trailing dots
            name = name.Trim().Trim('.');

            // Limit length
            if (name.Length > 100)
                name = name.Substring(0, 100);

            return string.IsNullOrWhiteSpace(name) ? "UNKNOWN" : name;
        }

        /// <summary>
        /// Show help message
        /// </summary>
        static void ShowHelp()
        {
            Console.WriteLine("Usage:");
            Console.WriteLine("  SolidWorksExtractor.exe                         Extract from active document");
            Console.WriteLine("  SolidWorksExtractor.exe <file.sldprt>          Extract from specific part");
            Console.WriteLine("  SolidWorksExtractor.exe <file.sldasm>          Extract from specific assembly");
            Console.WriteLine("  SolidWorksExtractor.exe <file.slddrw>          Extract from specific drawing");
            Console.WriteLine("  SolidWorksExtractor.exe --batch-parts <folder> Batch extract all *.SLDPRT");
            Console.WriteLine();
            Console.WriteLine("Options:");
            Console.WriteLine("  --help, -h             Show this help message");
            Console.WriteLine("  --active, -a           Use the currently active document");
            Console.WriteLine("  --output, -o           Specify output JSON file path");
            Console.WriteLine("  --drawing-target-view <name>  Extract only the named drawing view (repeatable)");
            Console.WriteLine("  --drawing-target-views <list> Extract only the named drawing views");
            Console.WriteLine("  --batch-parts <folder> Scan folder recursively for *.SLDPRT and extract all");
            Console.WriteLine("  --batch-output <folder> Output folder for batch (default: same as source)");
            Console.WriteLine("  --no-parts             Skip extracting part data from assembly components");
            Console.WriteLine("  --resolve              Resolve lightweight components before extraction");
            Console.WriteLine("  --start                Start SolidWorks if not running");
            Console.WriteLine("  --fast                 Fast mode: skip geometry analysis, per-config tracking");
            Console.WriteLine("  --full                 Full mode: complete extraction with all analysis (default)");
            Console.WriteLine("  --views                Export standard view screenshots as PNG (default in full mode)");
            Console.WriteLine("  --no-views             Skip view screenshot export");
            Console.WriteLine("  --color-parts          Colorize parts in assembly views (default for full mode)");
            Console.WriteLine("  --no-color-parts       Skip part colorization in assembly views");
            Console.WriteLine("  --export-glb           Export colored GLB 3D model for assembly");
            Console.WriteLine("  --part-glb             Export per-feature colored GLB for a single part");
            Console.WriteLine("  --fea                  Export FEA simulation results (stress GLB + results JSON)");
            Console.WriteLine();
            Console.WriteLine("Batch Mode:");
            Console.WriteLine("  --batch-parts scans a folder recursively for *.SLDPRT files");
            Console.WriteLine("  Each part is: opened silently → rebuilt → extracted → closed");
            Console.WriteLine("  Failures are logged but don't stop the batch");
            Console.WriteLine("  Output JSON files are named by part number (with fallback to filename)");
            Console.WriteLine("  A _batch_index.json file is created with metadata for all extracted parts");
            Console.WriteLine("  --fea-list-studies     List Simulation studies in the document and exit");
            Console.WriteLine("  --fea-preflight        Print FEA environment + study list and exit");
            Console.WriteLine("  --fea-study-name <s>   Force FEA extraction to use the named study (case-insensitive)");
            Console.WriteLine("  --fea-study-index <n>  Force FEA extraction to use the study at 0-based index n");
            Console.WriteLine("  --fea-allow-remesh     If the picked study's mesh is stale, re-mesh + re-solve");
            Console.WriteLine("                         via study.MeshAndRun() before extraction (modifies analysis state)");
            Console.WriteLine();
            Console.WriteLine("  FAST - Extracts features and properties only. Skips:");
            Console.WriteLine("         - Geometry ground truth analysis (cylinder/slot detection)");
            Console.WriteLine("         - Per-configuration suppression tracking");
            Console.WriteLine("         - Pattern location calculation");
            Console.WriteLine("         - Verification checklist generation");
            Console.WriteLine();
            Console.WriteLine("  FULL - Complete extraction including:");
            Console.WriteLine("         - Geometry ground truth with THRU/BLIND analysis");
            Console.WriteLine("         - Entry treatment detection (countersink/counterbore)");
            Console.WriteLine("         - Pattern instance centers and bolt circles");
            Console.WriteLine("         - Configuration-specific suppression states");
            Console.WriteLine("         - Mate entity quality indicators");
            Console.WriteLine();
            Console.WriteLine("Examples:");
            Console.WriteLine("  SolidWorksExtractor.exe                              # Active document, full");
            Console.WriteLine("  SolidWorksExtractor.exe bracket.sldprt --fast        # Fast extraction");
            Console.WriteLine("  SolidWorksExtractor.exe machine.sldasm --resolve     # Assembly, resolve LW");
            Console.WriteLine("  SolidWorksExtractor.exe part.sldprt -o output.json   # Custom output path");
            Console.WriteLine("  SolidWorksExtractor.exe --active --drawing-target-view \"Drawing View1\"");
            Console.WriteLine("  SolidWorksExtractor.exe --active --drawing-target-views \"Drawing View1;Drawing View2\"");
            Console.WriteLine("  SolidWorksExtractor.exe plate.sldprt --fea-preflight                 # show env + studies");
            Console.WriteLine("  SolidWorksExtractor.exe plate.sldprt --fea-list-studies              # studies only");
            Console.WriteLine("  SolidWorksExtractor.exe plate.sldprt --fea --fea-study-name \"Static 1\"");
            Console.WriteLine("  SolidWorksExtractor.exe plate.sldprt --fea --fea-study-index 2");
        }
    }
}
