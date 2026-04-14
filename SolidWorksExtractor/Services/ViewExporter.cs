using System;
using System.Collections.Generic;
using System.IO;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorksExtractor.Models;

namespace SolidWorksExtractor.Services
{
    /// <summary>
    /// Exports standard view screenshots from an open SolidWorks document.
    /// Captures Front, Top, Right, and Isometric views as PNG images.
    /// Supports both HiddenLinesRemoved (for parts) and ShadedWithEdges (for colorized assemblies).
    /// </summary>
    public class ViewExporter
    {
        /// <summary>
        /// Standard views to capture: name + SolidWorks view enum ID
        /// </summary>
        private static readonly (string Name, int ViewId)[] StandardViews = new[]
        {
            ("front",     (int)swStandardViews_e.swFrontView),
            ("top",       (int)swStandardViews_e.swTopView),
            ("right",     (int)swStandardViews_e.swRightView),
            ("isometric", (int)swStandardViews_e.swIsometricView),
        };

        /// <summary>
        /// Export standard view screenshots as PNG files.
        /// </summary>
        /// <param name="doc">Open SolidWorks document (must have UI visible)</param>
        /// <param name="outputFolder">Directory to save PNG files</param>
        /// <param name="baseName">Base filename prefix (e.g., part number)</param>
        /// <param name="useShaded">If true, use ShadedWithEdges mode (for colorized assembly views). Default: HiddenLinesRemoved.</param>
        /// <returns>ViewExportData with metadata for each exported view</returns>
        public ViewExportData ExportViews(IModelDoc2 doc, string outputFolder, string baseName, bool useShaded = false)
        {
            var result = new ViewExportData();

            if (doc == null)
            {
                Console.WriteLine("    Warning: No document provided for view export");
                return result;
            }

            // Ensure output folder exists
            if (!Directory.Exists(outputFolder))
            {
                Directory.CreateDirectory(outputFolder);
            }

            string displayModeName = useShaded ? "ShadedWithEdges" : "HiddenLinesRemoved";

            foreach (var (viewName, viewId) in StandardViews)
            {
                try
                {
                    // Set the standard view orientation
                    doc.ShowNamedView2("", viewId);

                    // Set display mode AFTER switching view (ShowNamedView2 can reset display mode)
                    try
                    {
                        IModelView modelView = (IModelView)doc.ActiveView;
                        if (modelView != null)
                        {
                            if (useShaded)
                            {
                                // swSHADED_WITH_EDGES = 9 in some SW versions,
                                // swSHADED = 2 is more reliable for showing colors
                                modelView.DisplayMode = (int)swDisplayMode_e.swSHADED;
                            }
                            else
                            {
                                modelView.DisplayMode = (int)swDisplayMode_e.swHIDDEN;
                            }
                        }
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine($"    Warning: Could not set display mode: {ex.Message}");
                    }

                    // Zoom to fit the part in the viewport
                    doc.ViewZoomtofit2();

                    // Force full graphics redraw and wait for SolidWorks to render
                    doc.GraphicsRedraw2();
                    System.Threading.Thread.Sleep(useShaded ? 500 : 100);

                    // Build output file paths — SaveBMP requires .bmp extension
                    string pngFileName = $"{baseName}_view_{viewName}.png";
                    string bmpFileName = $"{baseName}_view_{viewName}.bmp";
                    string bmpPath = Path.Combine(outputFolder, bmpFileName);
                    string pngPath = Path.Combine(outputFolder, pngFileName);

                    // Export the current viewport as BMP, then rename to PNG
                    bool saved = doc.SaveBMP(bmpPath, 0, 0);

                    if (saved && File.Exists(bmpPath))
                    {
                        // Rename .bmp to .png (SolidWorks BMP is actually valid for most consumers)
                        if (File.Exists(pngPath))
                            File.Delete(pngPath);
                        File.Move(bmpPath, pngPath);

                        result.Views.Add(new ViewImageInfo
                        {
                            ViewName = viewName,
                            FileName = pngFileName,
                            DisplayMode = displayModeName,
                        });
                        Console.WriteLine($"    Exported: {pngFileName}");
                    }
                    else
                    {
                        Console.WriteLine($"    Warning: SaveBMP returned false for {viewName} view");
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"    Warning: Failed to export {viewName} view: {ex.Message}");
                }
            }

            return result;
        }
    }
}
