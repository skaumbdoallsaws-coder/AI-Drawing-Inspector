using System;
using System.Collections.Generic;

namespace SolidWorksExtractor.Services
{
    /// <summary>
    /// Routes feature type names to handlers with alias support and version tolerance.
    /// GetTypeName2() varies across SolidWorks versions - treat as routing hint, not guarantee.
    /// </summary>
    public static class FeatureTypeRouter
    {
        /// <summary>
        /// Canonical feature categories for routing
        /// </summary>
        public enum FeatureCategory
        {
            HoleWizard,
            Extrude,
            Cut,
            Revolve,
            RevolveCut,
            Sweep,
            SweepCut,
            Loft,
            LoftCut,
            Fillet,
            Chamfer,
            LinearPattern,
            CircularPattern,
            MirrorPattern,
            SketchPattern,
            SheetMetalBase,
            SheetMetalEdgeFlange,
            SheetMetalMiterFlange,
            SheetMetalHem,
            SheetMetalBends,
            SheetMetalFlatPattern,
            SheetMetalSketchedBend,
            SheetMetalJog,
            SheetMetalLoftedBend,
            Shell,
            Rib,
            Draft,
            Dome,
            Wrap,
            Reference,      // Planes, axes, points, coordinate systems
            Sketch,
            Folder,
            Origin,
            Unknown
        }

        /// <summary>
        /// Routing table: maps type name aliases to canonical category.
        /// Includes known aliases across SW versions and locales.
        /// </summary>
        private static readonly Dictionary<string, FeatureCategory> _routingTable = new Dictionary<string, FeatureCategory>(StringComparer.OrdinalIgnoreCase)
        {
            // Hole Wizard - various aliases
            { "HoleWzd", FeatureCategory.HoleWizard },
            { "HoleWizard", FeatureCategory.HoleWizard },
            { "HoleWzd2", FeatureCategory.HoleWizard },
            { "HoleWzdSlot", FeatureCategory.HoleWizard },  // Slot from hole wizard

            // Extrude - boss/base
            { "Extrusion", FeatureCategory.Extrude },
            { "Boss-Extrude", FeatureCategory.Extrude },
            { "Base-Extrude", FeatureCategory.Extrude },
            { "Extrude", FeatureCategory.Extrude },
            { "ICE", FeatureCategory.Extrude },  // Instant 3D - UNSTABLE, use with caution
            { "Boss", FeatureCategory.Extrude },

            // Cut extrude
            { "Cut", FeatureCategory.Cut },
            { "Cut-Extrude", FeatureCategory.Cut },
            { "ExtrudeCut", FeatureCategory.Cut },
            { "ICE-Cut", FeatureCategory.Cut },  // UNSTABLE alias

            // Revolve
            { "Revolution", FeatureCategory.Revolve },
            { "Revolve", FeatureCategory.Revolve },
            { "Boss-Revolve", FeatureCategory.Revolve },
            { "RevolveBoss", FeatureCategory.Revolve },

            // Revolve cut
            { "RevCut", FeatureCategory.RevolveCut },
            { "Cut-Revolve", FeatureCategory.RevolveCut },
            { "RevolveCut", FeatureCategory.RevolveCut },

            // Sweep
            { "Sweep", FeatureCategory.Sweep },
            { "Boss-Sweep", FeatureCategory.Sweep },
            { "SweepBoss", FeatureCategory.Sweep },

            // Sweep cut
            { "SweepCut", FeatureCategory.SweepCut },
            { "Cut-Sweep", FeatureCategory.SweepCut },

            // Loft
            { "Loft", FeatureCategory.Loft },
            { "Boss-Loft", FeatureCategory.Loft },
            { "LoftBoss", FeatureCategory.Loft },

            // Loft cut
            { "LoftCut", FeatureCategory.LoftCut },
            { "Cut-Loft", FeatureCategory.LoftCut },

            // Fillet
            { "Fillet", FeatureCategory.Fillet },
            { "ConstRadiusFillet", FeatureCategory.Fillet },
            { "VarFillet", FeatureCategory.Fillet },
            { "FullRoundFillet", FeatureCategory.Fillet },
            { "FaceFillet", FeatureCategory.Fillet },

            // Chamfer
            { "Chamfer", FeatureCategory.Chamfer },
            { "ChamferFlt", FeatureCategory.Chamfer },

            // Patterns
            { "LPattern", FeatureCategory.LinearPattern },
            { "LinearPattern", FeatureCategory.LinearPattern },
            { "LocalLPattern", FeatureCategory.LinearPattern },

            { "CirPattern", FeatureCategory.CircularPattern },
            { "CircularPattern", FeatureCategory.CircularPattern },
            { "LocalCirPattern", FeatureCategory.CircularPattern },

            { "MirrorPattern", FeatureCategory.MirrorPattern },
            { "Mirror", FeatureCategory.MirrorPattern },
            { "MirrorStock", FeatureCategory.MirrorPattern },

            { "SketchPattern", FeatureCategory.SketchPattern },
            { "SketchDrivePattern", FeatureCategory.SketchPattern },

            // Sheet Metal - comprehensive list
            { "SMBaseFlange", FeatureCategory.SheetMetalBase },
            { "SheetMetal", FeatureCategory.SheetMetalBase },
            { "BaseBend", FeatureCategory.SheetMetalBase },
            { "BaseFlange", FeatureCategory.SheetMetalBase },
            { "ConvertToSheetMetal", FeatureCategory.SheetMetalBase },

            { "EdgeFlange", FeatureCategory.SheetMetalEdgeFlange },
            { "SMEdgeFlange", FeatureCategory.SheetMetalEdgeFlange },

            { "MiterFlange", FeatureCategory.SheetMetalMiterFlange },
            { "SMMiterFlange", FeatureCategory.SheetMetalMiterFlange },

            { "Hem", FeatureCategory.SheetMetalHem },
            { "SMHem", FeatureCategory.SheetMetalHem },

            { "Bends", FeatureCategory.SheetMetalBends },
            { "ProcessBends", FeatureCategory.SheetMetalBends },
            { "FlattenBends", FeatureCategory.SheetMetalBends },

            { "FlatPattern", FeatureCategory.SheetMetalFlatPattern },
            { "SM-FLAT-PATTERN", FeatureCategory.SheetMetalFlatPattern },

            { "SketchedBend", FeatureCategory.SheetMetalSketchedBend },
            { "SMSketchedBend", FeatureCategory.SheetMetalSketchedBend },

            { "Jog", FeatureCategory.SheetMetalJog },
            { "SMJog", FeatureCategory.SheetMetalJog },

            { "LoftedBend", FeatureCategory.SheetMetalLoftedBend },
            { "SMLoftedBend", FeatureCategory.SheetMetalLoftedBend },

            // Other modeling features
            { "Shell", FeatureCategory.Shell },
            { "Rib", FeatureCategory.Rib },
            { "Draft", FeatureCategory.Draft },
            { "Dome", FeatureCategory.Dome },
            { "Wrap", FeatureCategory.Wrap },

            // Reference geometry
            { "RefPlane", FeatureCategory.Reference },
            { "RefAxis", FeatureCategory.Reference },
            { "RefPoint", FeatureCategory.Reference },
            { "CoordSys", FeatureCategory.Reference },
            { "RefSurface", FeatureCategory.Reference },

            // Sketches
            { "ProfileFeature", FeatureCategory.Sketch },
            { "3DProfileFeature", FeatureCategory.Sketch },
            { "Sketch", FeatureCategory.Sketch },

            // Folders and structural
            { "FtrFolder", FeatureCategory.Folder },
            { "FeatureFolder", FeatureCategory.Folder },
            { "CutListFolder", FeatureCategory.Folder },
            { "BodyFolder", FeatureCategory.Folder },
            { "SolidBodyFolder", FeatureCategory.Folder },
            { "SurfaceBodyFolder", FeatureCategory.Folder },
            { "SubWeldFolder", FeatureCategory.Folder },

            // Origin
            { "OriginProfileFeature", FeatureCategory.Origin },
            { "MaterialIdent", FeatureCategory.Origin },
            { "HistoryFolder", FeatureCategory.Origin },
            { "DetailCabinet", FeatureCategory.Origin },
        };

        /// <summary>
        /// Route a feature type name to its canonical category.
        /// Returns Unknown if no match found - caller should handle gracefully.
        /// </summary>
        public static FeatureCategory GetCategory(string typeName)
        {
            if (string.IsNullOrEmpty(typeName))
                return FeatureCategory.Unknown;

            if (_routingTable.TryGetValue(typeName, out FeatureCategory category))
                return category;

            // Fallback: check for partial matches (handles localized names)
            string lowerType = typeName.ToLower();

            if (lowerType.Contains("hole") && lowerType.Contains("wz"))
                return FeatureCategory.HoleWizard;
            if (lowerType.Contains("extrude") || lowerType.Contains("extrusion"))
                return lowerType.Contains("cut") ? FeatureCategory.Cut : FeatureCategory.Extrude;
            if (lowerType.Contains("revolve") || lowerType.Contains("revolution"))
                return lowerType.Contains("cut") ? FeatureCategory.RevolveCut : FeatureCategory.Revolve;
            if (lowerType.Contains("fillet"))
                return FeatureCategory.Fillet;
            if (lowerType.Contains("chamfer"))
                return FeatureCategory.Chamfer;
            if (lowerType.Contains("pattern"))
            {
                if (lowerType.Contains("lin")) return FeatureCategory.LinearPattern;
                if (lowerType.Contains("cir")) return FeatureCategory.CircularPattern;
                if (lowerType.Contains("mirror")) return FeatureCategory.MirrorPattern;
            }
            if (lowerType.Contains("sheetmetal") || lowerType.Contains("sm") || lowerType.Contains("flange") || lowerType.Contains("bend"))
                return FeatureCategory.SheetMetalBase;  // Generic fallback for sheet metal

            return FeatureCategory.Unknown;
        }

        /// <summary>
        /// Check if this is a modeling feature (affects geometry) vs structural/reference
        /// </summary>
        public static bool IsModelingFeature(FeatureCategory category)
        {
            switch (category)
            {
                case FeatureCategory.Reference:
                case FeatureCategory.Sketch:
                case FeatureCategory.Folder:
                case FeatureCategory.Origin:
                case FeatureCategory.Unknown:
                    return false;
                default:
                    return true;
            }
        }

        /// <summary>
        /// Check if this is a sheet metal feature
        /// </summary>
        public static bool IsSheetMetalFeature(FeatureCategory category)
        {
            switch (category)
            {
                case FeatureCategory.SheetMetalBase:
                case FeatureCategory.SheetMetalEdgeFlange:
                case FeatureCategory.SheetMetalMiterFlange:
                case FeatureCategory.SheetMetalHem:
                case FeatureCategory.SheetMetalBends:
                case FeatureCategory.SheetMetalFlatPattern:
                case FeatureCategory.SheetMetalSketchedBend:
                case FeatureCategory.SheetMetalJog:
                case FeatureCategory.SheetMetalLoftedBend:
                    return true;
                default:
                    return false;
            }
        }

        /// <summary>
        /// Check if this is a pattern feature
        /// </summary>
        public static bool IsPatternFeature(FeatureCategory category)
        {
            switch (category)
            {
                case FeatureCategory.LinearPattern:
                case FeatureCategory.CircularPattern:
                case FeatureCategory.MirrorPattern:
                case FeatureCategory.SketchPattern:
                    return true;
                default:
                    return false;
            }
        }
    }
}
