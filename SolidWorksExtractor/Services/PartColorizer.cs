using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace SolidWorksExtractor.Services
{
    /// <summary>
    /// Assigns deterministic, distinct colors to each unique part in an assembly,
    /// applies them via the SolidWorks API, and can restore original appearances.
    /// Used for color-coded assembly view export so VLMs can identify components.
    /// </summary>
    public class PartColorizer
    {
        /// <summary>
        /// 20 maximally-distinct saturated colors (Sasha Trubetskoy palette).
        /// Sorted parts get assigned colors in order for deterministic mapping.
        /// </summary>
        private static readonly (int R, int G, int B, string Hex)[] Palette = new[]
        {
            (230,  25,  75, "#E6194B"),  // Red
            ( 60, 180,  75, "#3CB44B"),  // Green
            (255, 225,  25, "#FFE119"),  // Yellow
            (  0, 130, 200, "#0082C8"),  // Blue
            (245, 130,  48, "#F58230"),  // Orange
            (145,  30, 180, "#9130B4"),  // Purple
            ( 70, 240, 240, "#46F0F0"),  // Cyan
            (240,  50, 230, "#F032E6"),  // Magenta
            (210, 245,  60, "#D2F53C"),  // Lime
            (250, 190, 212, "#FABED4"),  // Pink
            (  0, 128, 128, "#008080"),  // Teal
            (220, 190, 255, "#DCBEFF"),  // Lavender
            (170, 110,  40, "#AA6E28"),  // Brown
            (255, 250, 200, "#FFFAC8"),  // Beige
            (128,   0,   0, "#800000"),  // Maroon
            (170, 255, 195, "#AAFFC3"),  // Mint
            (128, 128,   0, "#808000"),  // Olive
            (255, 215, 180, "#FFD8B4"),  // Apricot
            (  0,   0, 128, "#000080"),  // Navy
            (128, 128, 128, "#808080"),  // Grey
        };

        // Backup: component Name2 -> original material property values (null if no override)
        private Dictionary<string, double[]> _originalAppearances
            = new Dictionary<string, double[]>();

        /// <summary>
        /// Assign colors to all part components, apply via SolidWorks API,
        /// and return the part-filename-to-hex-color mapping.
        /// </summary>
        /// <param name="assyDoc">The open assembly document</param>
        /// <returns>Dictionary mapping lowercase part filename to hex color string</returns>
        public Dictionary<string, string> ApplyColors(IAssemblyDoc assyDoc)
        {
            var colorMapping = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            _originalAppearances.Clear();

            if (assyDoc == null)
                return colorMapping;

            // Get all components (flat list including nested sub-assemblies)
            object[] allComponents = (object[])assyDoc.GetComponents(false);
            if (allComponents == null || allComponents.Length == 0)
                return colorMapping;

            // Build sorted list of unique part filenames for deterministic color assignment
            var uniqueParts = new SortedSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (object obj in allComponents)
            {
                IComponent2 comp = (IComponent2)obj;
                if (comp == null) continue;

                // Skip suppressed components
                int suppState = comp.GetSuppression2();
                if (suppState == (int)swComponentSuppressionState_e.swComponentSuppressed)
                    continue;

                string pathName = comp.GetPathName();
                if (string.IsNullOrEmpty(pathName)) continue;

                string fileName = System.IO.Path.GetFileName(pathName);
                if (!string.IsNullOrEmpty(fileName) &&
                    fileName.EndsWith(".SLDPRT", StringComparison.OrdinalIgnoreCase))
                {
                    uniqueParts.Add(fileName.ToLower());
                }
            }

            // Assign palette index to each unique part (sorted order = deterministic)
            var partToColorIndex = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            int colorIndex = 0;
            foreach (string partFile in uniqueParts)
            {
                int paletteIdx = colorIndex % Palette.Length;
                partToColorIndex[partFile] = paletteIdx;
                colorMapping[partFile] = Palette[paletteIdx].Hex;
                colorIndex++;
            }

            // Apply colors to each component instance
            int applied = 0;
            foreach (object obj in allComponents)
            {
                IComponent2 comp = (IComponent2)obj;
                if (comp == null) continue;

                int suppState = comp.GetSuppression2();
                if (suppState == (int)swComponentSuppressionState_e.swComponentSuppressed)
                    continue;

                string pathName = comp.GetPathName();
                if (string.IsNullOrEmpty(pathName)) continue;

                string fileName = System.IO.Path.GetFileName(pathName)?.ToLower();
                if (string.IsNullOrEmpty(fileName) || !partToColorIndex.ContainsKey(fileName))
                    continue;

                try
                {
                    // Backup original appearance (may be null if no explicit override)
                    double[] original = (double[])comp.GetMaterialPropertyValues2(
                        (int)swInConfigurationOpts_e.swThisConfiguration, null);
                    _originalAppearances[comp.Name2] = original;

                    // Build new material property array
                    var palette = Palette[partToColorIndex[fileName]];
                    double r = palette.R / 255.0;
                    double g = palette.G / 255.0;
                    double b = palette.B / 255.0;

                    // [R, G, B, Ambient, Diffuse, Specular, Shininess, Transparency, Emission]
                    double[] colorValues = new double[]
                    {
                        r, g, b,
                        0.4,   // Ambient
                        0.8,   // Diffuse
                        0.3,   // Specular
                        0.3,   // Shininess
                        0.0,   // Transparency (fully opaque)
                        0.0    // Emission
                    };

                    comp.SetMaterialPropertyValues2(
                        colorValues,
                        (int)swInConfigurationOpts_e.swThisConfiguration,
                        null);
                    applied++;
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"    Warning: Could not colorize '{comp.Name2}': {ex.Message}");
                }
            }

            Console.WriteLine($"    Applied {uniqueParts.Count} distinct colors to {applied} component instances");
            return colorMapping;
        }

        /// <summary>
        /// Restore all original component appearances that were backed up during ApplyColors.
        /// </summary>
        public void RestoreColors(IAssemblyDoc assyDoc)
        {
            if (assyDoc == null || _originalAppearances.Count == 0)
                return;

            object[] allComponents = (object[])assyDoc.GetComponents(false);
            if (allComponents == null)
                return;

            int restored = 0;
            foreach (object obj in allComponents)
            {
                IComponent2 comp = (IComponent2)obj;
                if (comp == null) continue;

                if (_originalAppearances.TryGetValue(comp.Name2, out double[] original))
                {
                    try
                    {
                        if (original != null && original.Length >= 9)
                        {
                            // Restore the original appearance values
                            comp.SetMaterialPropertyValues2(
                                original,
                                (int)swInConfigurationOpts_e.swThisConfiguration,
                                null);
                        }
                        else
                        {
                            // Original had no explicit override — remove our color override
                            comp.RemoveMaterialProperty2(
                                (int)swInConfigurationOpts_e.swThisConfiguration, null);
                        }
                        restored++;
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine($"    Warning: Could not restore appearance for '{comp.Name2}': {ex.Message}");
                    }
                }
            }

            _originalAppearances.Clear();
            Console.WriteLine($"    Restored {restored} component appearances");
        }
    }
}
