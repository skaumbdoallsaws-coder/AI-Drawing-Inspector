using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace SolidWorksExtractor.Services
{
    /// <summary>
    /// Applies a unique machine-readable color to each component occurrence.
    /// Unlike PartColorizer, identity is keyed by component Name2 and a
    /// canonical occurrence ID supplied by the package-preparation adapter.
    /// </summary>
    public sealed class OccurrenceMaskColorizer
    {
        private readonly Dictionary<string, string> _occurrenceByAlias;
        private readonly Dictionary<string, double[]> _originalAppearances =
            new Dictionary<string, double[]>(StringComparer.Ordinal);
        private IModelDocExtension _modelExtension;
        private DisplayStateSetting _displayStateSetting;
        private object _originalDisplayStateAppearances;

        public OccurrenceMaskColorizer(IDictionary<string, string> occurrenceByAlias)
        {
            _occurrenceByAlias = new Dictionary<string, string>(
                occurrenceByAlias ?? throw new ArgumentNullException(nameof(occurrenceByAlias)),
                StringComparer.Ordinal);
        }

        public static Dictionary<string, string> ReadOccurrenceMap(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
                throw new ArgumentException("Occurrence map path is required.", nameof(path));
            var result = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (string line in File.ReadLines(path))
            {
                if (string.IsNullOrWhiteSpace(line) || line.StartsWith("#", StringComparison.Ordinal))
                    continue;
                string[] fields = line.Split('\t');
                if (fields.Length != 2 || string.IsNullOrWhiteSpace(fields[0]) ||
                    string.IsNullOrWhiteSpace(fields[1]))
                    throw new InvalidDataException(
                        "Occurrence map rows must be: componentName<TAB>occurrenceId.");
                if (result.ContainsKey(fields[0]))
                    throw new InvalidDataException("Duplicate component alias: " + fields[0]);
                result.Add(fields[0], fields[1]);
            }
            if (result.Count == 0)
                throw new InvalidDataException("Occurrence map contains no entries.");
            return result;
        }

        public IReadOnlyList<OccurrenceMaskEntry> Apply(IAssemblyDoc assembly)
        {
            if (assembly == null) throw new ArgumentNullException(nameof(assembly));
            object[] rawComponents = assembly.GetComponents(false) as object[];
            if (rawComponents == null)
                return new List<OccurrenceMaskEntry>();

            var components = rawComponents
                .OfType<IComponent2>()
                .Where(component => !component.IsSuppressed())
                .OrderBy(component => component.Name2, StringComparer.Ordinal)
                .ToList();
            var missing = components
                .Select(component => component.Name2)
                .Where(alias => !_occurrenceByAlias.ContainsKey(alias))
                .ToList();
            if (missing.Count > 0)
                throw new InvalidDataException(
                    "Canonical occurrence map is missing component aliases: " +
                    string.Join(", ", missing.Take(8)));

            var orderedIds = components
                .Select(component => _occurrenceByAlias[component.Name2])
                .Distinct(StringComparer.Ordinal)
                .OrderBy(value => value, StringComparer.Ordinal)
                .ToList();
            if (orderedIds.Count > 4095)
                throw new InvalidOperationException(
                    "Occurrence mask v1 supports at most 4095 visible occurrences.");

            var colorByOccurrence = new Dictionary<string, RgbColor>(StringComparer.Ordinal);
            for (int index = 0; index < orderedIds.Count; index++)
                colorByOccurrence[orderedIds[index]] = ColorForIndex(index + 1);

            ApplyDisplayStateAppearances(assembly, components, colorByOccurrence);

            var entries = new List<OccurrenceMaskEntry>();
            _originalAppearances.Clear();
            foreach (IComponent2 component in components)
            {
                string alias = component.Name2;
                string occurrenceId = _occurrenceByAlias[alias];
                RgbColor color = colorByOccurrence[occurrenceId];
                double[] original = component.GetMaterialPropertyValues2(
                    (int)swInConfigurationOpts_e.swThisConfiguration, null) as double[];
                _originalAppearances[alias] = original;

                // SolidWorks requires diffuse, specular, and shininess to be
                // greater than zero before an RGB change is rendered.
                // Exact identity is still validated from the captured bitmap.
                double[] material =
                {
                    color.R / 255.0,
                    color.G / 255.0,
                    color.B / 255.0,
                    0.8,
                    0.9,
                    0.1,
                    0.1,
                    0.0,
                    0.0,
                };
                component.SetMaterialPropertyValues2(
                    material,
                    (int)swInConfigurationOpts_e.swThisConfiguration,
                    null);
                // SolidWorks 2024 can retain the configuration-aware values
                // without refreshing the active display-state graphics. The
                // legacy property targets the active occurrence and forces the
                // viewport override that SaveBMP captures.
                component.MaterialPropertyValues = material;
                double[] applied = component.GetMaterialPropertyValues2(
                    (int)swInConfigurationOpts_e.swThisConfiguration, null) as double[];
                if (applied == null || applied.Length < 3)
                    throw new InvalidOperationException(
                        "SolidWorks did not retain the occurrence appearance for " + alias);
                if (Math.Abs(applied[0] - material[0]) > 0.01 ||
                    Math.Abs(applied[1] - material[1]) > 0.01 ||
                    Math.Abs(applied[2] - material[2]) > 0.01)
                    throw new InvalidOperationException(
                        "SolidWorks returned a different occurrence appearance for " + alias);
                entries.Add(new OccurrenceMaskEntry
                {
                    ComponentAlias = alias,
                    OccurrenceId = occurrenceId,
                    HexColor = color.Hex,
                });
            }
            Console.WriteLine(
                $"    Applied {entries.Count} occurrence identity appearances");
            return entries
                .OrderBy(entry => entry.OccurrenceId, StringComparer.Ordinal)
                .ThenBy(entry => entry.ComponentAlias, StringComparer.Ordinal)
                .ToList();
        }

        public void Restore(IAssemblyDoc assembly)
        {
            if (assembly == null || _originalAppearances.Count == 0) return;
            object[] rawComponents = assembly.GetComponents(false) as object[];
            if (rawComponents == null) return;
            foreach (IComponent2 component in rawComponents.OfType<IComponent2>())
            {
                if (!_originalAppearances.TryGetValue(component.Name2, out double[] original))
                    continue;
                if (original != null && original.Length >= 9)
                {
                    component.SetMaterialPropertyValues2(
                        original,
                        (int)swInConfigurationOpts_e.swThisConfiguration,
                        null);
                    component.MaterialPropertyValues = original;
                }
                else
                {
                    component.RemoveMaterialProperty2(
                        (int)swInConfigurationOpts_e.swThisConfiguration,
                        null);
                }
            }
            if (_modelExtension != null && _displayStateSetting != null &&
                _originalDisplayStateAppearances != null)
            {
                _modelExtension.DisplayStateSpecMaterialPropertyValues[
                    _displayStateSetting] = _originalDisplayStateAppearances;
            }
            _modelExtension = null;
            _displayStateSetting = null;
            _originalDisplayStateAppearances = null;
            _originalAppearances.Clear();
        }

        private void ApplyDisplayStateAppearances(
            IAssemblyDoc assembly,
            IReadOnlyList<IComponent2> components,
            IReadOnlyDictionary<string, RgbColor> colorByOccurrence)
        {
            IModelDoc2 model = assembly as IModelDoc2;
            if (model == null || components.Count == 0) return;
            IConfiguration configuration = model.ConfigurationManager.ActiveConfiguration;
            string[] displayStates = configuration.GetDisplayStates() as string[];
            if (displayStates == null || displayStates.Length == 0) return;

            IModelDocExtension extension = model.Extension;
            DisplayStateSetting setting = extension.GetDisplayStateSetting(
                (int)swDisplayStateOpts_e.swSpecifyDisplayState);
            setting.Option = (int)swDisplayStateOpts_e.swSpecifyDisplayState;
            setting.Names = displayStates;
            setting.Entities = components.Cast<object>().ToArray();
            setting.PartLevel = false;
            setting.RemoveAppearance = false;

            object original = extension.DisplayStateSpecMaterialPropertyValues[setting];
            var appearances = new object[components.Count * displayStates.Length];
            int outputIndex = 0;
            foreach (IComponent2 component in components)
            {
                RgbColor color = colorByOccurrence[_occurrenceByAlias[component.Name2]];
                foreach (string ignored in displayStates)
                {
                    AppearanceSetting appearance = extension.GetAppearanceSetting();
                    appearance.Color = color.R | color.G << 8 | color.B << 16;
                    appearance.Diffuse = 0.9;
                    appearance.Specular = 0.1;
                    appearance.SpecularSpread = 0.1;
                    appearance.Transparent = 0.0;
                    appearance.Luminous = 0.0;
                    appearances[outputIndex++] = appearance;
                }
            }
            extension.DisplayStateSpecMaterialPropertyValues[setting] = appearances;
            _modelExtension = extension;
            _displayStateSetting = setting;
            _originalDisplayStateAppearances = original;
        }

        public static void WriteLegend(
            string path,
            IEnumerable<OccurrenceMaskEntry> entries)
        {
            var lines = new List<string>
            {
                "# hexColor\tcomponentAlias\toccurrenceId",
            };
            lines.AddRange(entries.Select(
                entry => entry.HexColor + "\t" + entry.ComponentAlias + "\t" + entry.OccurrenceId));
            File.WriteAllLines(path, lines);
        }

        private static RgbColor ColorForIndex(int index)
        {
            // A 12-bit permutation expanded to RGB. Every channel remains
            // away from black and white, and no color repeats for v1's cap.
            int value = (index * 2654435761L & 0xFFF) == 0
                ? index
                : (int)(index * 2654435761L & 0xFFF);
            int r4 = (value >> 8) & 0xF;
            int g4 = (value >> 4) & 0xF;
            int b4 = value & 0xF;
            byte r = (byte)(32 + r4 * 13);
            byte g = (byte)(32 + g4 * 13);
            byte b = (byte)(32 + b4 * 13);
            return new RgbColor(r, g, b);
        }

        private readonly struct RgbColor
        {
            public RgbColor(byte r, byte g, byte b)
            {
                R = r;
                G = g;
                B = b;
            }

            public byte R { get; }
            public byte G { get; }
            public byte B { get; }
            public string Hex => string.Format(
                CultureInfo.InvariantCulture, "#{0:X2}{1:X2}{2:X2}", R, G, B);
        }
    }

    public sealed class OccurrenceMaskEntry
    {
        public string ComponentAlias { get; set; }
        public string OccurrenceId { get; set; }
        public string HexColor { get; set; }
    }
}
