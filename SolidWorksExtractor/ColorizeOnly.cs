using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace SolidWorksExtractor
{
    /// <summary>
    /// Standalone entry point that ONLY colorizes parts in the active assembly.
    /// No extraction, no view export, no restore. Just applies colors and exits.
    /// Run: SolidWorksExtractor.exe --colorize-only
    /// </summary>
    public static class ColorizeOnly
    {
        private static readonly (int R, int G, int B, string Hex, string Name)[] Palette = new[]
        {
            (230,  25,  75, "#E6194B", "Red"),
            ( 60, 180,  75, "#3CB44B", "Green"),
            (255, 225,  25, "#FFE119", "Yellow"),
            (  0, 130, 200, "#0082C8", "Blue"),
            (245, 130,  48, "#F58230", "Orange"),
            (145,  30, 180, "#9130B4", "Purple"),
            ( 70, 240, 240, "#46F0F0", "Cyan"),
            (240,  50, 230, "#F032E6", "Magenta"),
            (210, 245,  60, "#D2F53C", "Lime"),
            (250, 190, 212, "#FABED4", "Pink"),
            (  0, 128, 128, "#008080", "Teal"),
            (220, 190, 255, "#DCBEFF", "Lavender"),
            (170, 110,  40, "#AA6E28", "Brown"),
            (255, 250, 200, "#FFFAC8", "Beige"),
            (128,   0,   0, "#800000", "Maroon"),
            (170, 255, 195, "#AAFFC3", "Mint"),
            (128, 128,   0, "#808000", "Olive"),
            (255, 215, 180, "#FFD8B4", "Apricot"),
            (  0,   0, 128, "#000080", "Navy"),
            (128, 128, 128, "#808080", "Grey"),
        };

        public static int Run()
        {
            Console.WriteLine("Colorize-Only Mode: Applying colors to active assembly...");
            Console.WriteLine();

            // Connect to SolidWorks
            ISldWorks swApp;
            try
            {
                swApp = (ISldWorks)Marshal.GetActiveObject("SldWorks.Application");
            }
            catch
            {
                Console.WriteLine("ERROR: SolidWorks is not running.");
                return 1;
            }

            IModelDoc2 doc = (IModelDoc2)swApp.ActiveDoc;
            if (doc == null)
            {
                Console.WriteLine("ERROR: No active document.");
                return 1;
            }

            if (doc.GetType() != (int)swDocumentTypes_e.swDocASSEMBLY)
            {
                Console.WriteLine("ERROR: Active document is not an assembly.");
                return 1;
            }

            IAssemblyDoc assyDoc = (IAssemblyDoc)doc;
            object[] allComponents = (object[])assyDoc.GetComponents(false);
            if (allComponents == null || allComponents.Length == 0)
            {
                Console.WriteLine("ERROR: No components found.");
                return 1;
            }

            // Build sorted unique parts list
            var uniqueParts = new SortedSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (object obj in allComponents)
            {
                IComponent2 comp = (IComponent2)obj;
                if (comp == null) continue;
                if (comp.GetSuppression2() == (int)swComponentSuppressionState_e.swComponentSuppressed)
                    continue;
                string path = comp.GetPathName();
                if (string.IsNullOrEmpty(path)) continue;
                string fn = System.IO.Path.GetFileName(path);
                if (fn.EndsWith(".SLDPRT", StringComparison.OrdinalIgnoreCase))
                    uniqueParts.Add(fn.ToLower());
            }

            // Assign colors
            var partToColor = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            int idx = 0;
            foreach (string p in uniqueParts)
            {
                partToColor[p] = idx % Palette.Length;
                idx++;
            }

            // Apply colors
            int applied = 0;
            foreach (object obj in allComponents)
            {
                IComponent2 comp = (IComponent2)obj;
                if (comp == null) continue;
                if (comp.GetSuppression2() == (int)swComponentSuppressionState_e.swComponentSuppressed)
                    continue;
                string path = comp.GetPathName();
                if (string.IsNullOrEmpty(path)) continue;
                string fn = System.IO.Path.GetFileName(path)?.ToLower();
                if (string.IsNullOrEmpty(fn) || !partToColor.ContainsKey(fn)) continue;

                try
                {
                    var c = Palette[partToColor[fn]];
                    double[] vals = new double[]
                    {
                        c.R / 255.0, c.G / 255.0, c.B / 255.0,
                        0.4, 0.8, 0.3, 0.3, 0.0, 0.0
                    };
                    comp.SetMaterialPropertyValues2(vals,
                        (int)swInConfigurationOpts_e.swThisConfiguration, null);
                    applied++;
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"  Warning: {comp.Name2}: {ex.Message}");
                }
            }

            // Force redraw
            doc.GraphicsRedraw2();

            // Print mapping
            Console.WriteLine($"Done! Applied {uniqueParts.Count} colors to {applied} components.");
            Console.WriteLine();
            Console.WriteLine("Color mapping:");
            foreach (string p in uniqueParts)
            {
                var c = Palette[partToColor[p]];
                Console.WriteLine($"  {c.Hex} ({c.Name,-8})  {p}");
            }
            Console.WriteLine();
            Console.WriteLine("Colors are now visible in SolidWorks.");
            Console.WriteLine("Take your screenshots and export the GLB now.");
            Console.WriteLine("To restore original colors, close and reopen the assembly without saving.");
            Console.WriteLine();
            Console.WriteLine("Press ENTER when you are done...");
            Console.ReadLine();

            return 0;
        }
    }
}
