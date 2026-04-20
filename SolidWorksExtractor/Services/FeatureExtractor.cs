using System;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorksExtractor.Models;

namespace SolidWorksExtractor.Services
{
    /// <summary>
    /// Extracts typed feature data from the feature tree
    /// </summary>
    public class FeatureExtractor
    {
        private int _featureOrder = 0;
        private string _activeConfigName = "";
        private List<string> _allConfigNames = new List<string>();

        /// <summary>
        /// Extract all features from a part document
        /// </summary>
        public FeatureCollection ExtractFeatures(IModelDoc2 doc)
        {
            var collection = new FeatureCollection();
            _featureOrder = 0;

            if (doc == null)
                return collection;

            try
            {
                // Get configuration info
                IConfiguration activeConfig = (IConfiguration)doc.GetActiveConfiguration();
                _activeConfigName = activeConfig?.Name ?? "";
                collection.ActiveConfiguration = _activeConfigName;

                // Get all configuration names for suppression tracking
                _allConfigNames.Clear();
                string[] configNames = (string[])doc.GetConfigurationNames();
                if (configNames != null)
                {
                    _allConfigNames.AddRange(configNames);
                    collection.AllConfigurations = new List<string>(_allConfigNames);
                }

                IFeature feat = (IFeature)doc.FirstFeature();

                while (feat != null)
                {
                    ProcessFeature(doc, feat, collection, 0);
                    feat = (IFeature)feat.GetNextFeature();
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Error extracting features: {ex.Message}");
            }

            return collection;
        }

        /// <summary>
        /// Process a single feature and its sub-features
        /// </summary>
        private void ProcessFeature(IModelDoc2 doc, IFeature feat, FeatureCollection collection, int level)
        {
            if (feat == null)
                return;

            string typeName = feat.GetTypeName2();
            string name = feat.Name;

            // Get suppression state for active config
            bool isSuppressed = false;
            try
            {
                object suppResult = feat.IsSuppressed2((int)swInConfigurationOpts_e.swThisConfiguration, null);
                if (suppResult is bool[] suppArray && suppArray.Length > 0)
                    isSuppressed = suppArray[0];
            }
            catch { }

            // Get suppression states for all configurations
            var suppressionByConfig = GetSuppressionByConfig(feat);

            // Add to feature tree
            collection.FeatureTree.Add(new FeatureTreeNode
            {
                Name = name,
                TypeName = typeName,
                Level = level
            });

            // Extract typed feature data based on type
            try
            {
                switch (typeName)
                {
                    case "HoleWzd":
                        ExtractHoleWizard(doc, feat, collection, isSuppressed, suppressionByConfig);
                        break;

                    case "Extrusion":
                        ExtractExtrude(doc, feat, collection, isSuppressed, suppressionByConfig, false);
                        break;

                    case "ICE":
                        // ICE is used for both boss and cut extrudes - check feature name
                        bool isIceCut = name.ToLower().Contains("cut");
                        ExtractExtrude(doc, feat, collection, isSuppressed, suppressionByConfig, isIceCut);
                        break;

                    case "Cut":
                    case "ICE-Cut":
                    case "Cut-Thicken":
                        ExtractExtrude(doc, feat, collection, isSuppressed, suppressionByConfig, true);
                        break;

                    case "Revolution":
                    case "RevCut":
                    case "Revolve":
                    case "RevolveCut":
                        ExtractRevolve(doc, feat, collection, isSuppressed, suppressionByConfig);
                        break;

                    case "Sweep":
                    case "SweepCut":
                        ExtractSweep(doc, feat, collection, isSuppressed, suppressionByConfig);
                        break;

                    case "Loft":
                    case "LoftCut":
                        ExtractLoft(doc, feat, collection, isSuppressed, suppressionByConfig);
                        break;

                    case "Fillet":
                    case "VarFillet":
                        ExtractFillet(doc, feat, collection, isSuppressed, suppressionByConfig);
                        break;

                    case "Chamfer":
                        ExtractChamfer(doc, feat, collection, isSuppressed, suppressionByConfig);
                        break;

                    case "LPattern":
                        ExtractLinearPattern(doc, feat, collection, isSuppressed, suppressionByConfig);
                        break;

                    case "CirPattern":
                        ExtractCircularPattern(doc, feat, collection, isSuppressed, suppressionByConfig);
                        break;

                    case "MirrorPattern":
                        ExtractMirrorPattern(doc, feat, collection, isSuppressed, suppressionByConfig);
                        break;

                    case "SMBaseFlange":
                    case "EdgeFlange":
                    case "MiterFlange":
                    case "Hem":
                    case "SheetMetal":
                    case "FlatPattern":
                    case "Bends":
                        ExtractSheetMetal(doc, feat, collection, isSuppressed, suppressionByConfig, typeName);
                        break;

                    default:
                        // Store as generic feature if it's a modeling feature
                        if (IsModelingFeature(typeName))
                        {
                            var genericFeat = new GenericFeature
                            {
                                Name = name,
                                TypeName = typeName,
                                TreeOrder = _featureOrder++
                            };
                            SetFeatureBaseProperties(genericFeat, feat, isSuppressed, suppressionByConfig);
                            collection.OtherFeatures.Add(genericFeat);
                        }
                        break;
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: Error processing feature '{name}' ({typeName}): {ex.Message}");
            }

            // Process sub-features
            IFeature subFeat = (IFeature)feat.GetFirstSubFeature();
            while (subFeat != null)
            {
                ProcessFeature(doc, subFeat, collection, level + 1);
                subFeat = (IFeature)subFeat.GetNextSubFeature();
            }
        }

        #region Hole Wizard Extraction

        private void ExtractHoleWizard(IModelDoc2 doc, IFeature feat, FeatureCollection collection, bool isSuppressed, Dictionary<string, bool> suppressionByConfig)
        {
            var hole = new HoleWizardFeature
            {
                Name = feat.Name,
                TypeName = "HoleWzd",
                TreeOrder = _featureOrder++
            };

            SetFeatureBaseProperties(hole, feat, isSuppressed, suppressionByConfig);

            try
            {
                IWizardHoleFeatureData2 holeData = (IWizardHoleFeatureData2)feat.GetDefinition();

                if (holeData != null && holeData.AccessSelections(doc, null))
                {
                    // Hole type - use int directly
                    int holeType = holeData.Type;
                    hole.HoleType = GetHoleTypeString(holeType);

                    // Fallback: detect hole type from feature name if Unknown
                    if (hole.HoleType == "Unknown")
                    {
                        string nameLower = feat.Name.ToLower();
                        if (nameLower.Contains("tap drill") || nameLower.Contains("tapped"))
                            hole.HoleType = "Tap Drill";
                        else if (nameLower.Contains("counterbore") || nameLower.Contains("c'bore") || nameLower.Contains("cbore"))
                            hole.HoleType = "Counterbore";
                        else if (nameLower.Contains("countersink") || nameLower.Contains("c'sink") || nameLower.Contains("csink"))
                            hole.HoleType = "Countersink";
                        else if (nameLower.Contains("thru") || nameLower.Contains("through"))
                            hole.HoleType = "Hole";
                    }

                    // Standard is a string in this API version
                    try { hole.Standard = holeData.Standard ?? "Unknown"; }
                    catch { hole.Standard = "Unknown"; }

                    // Fastener info - wrap in try-catch
                    try { hole.FastenerType = holeData.FastenerType?.ToString() ?? ""; } catch { }
                    try { hole.FastenerSize = holeData.FastenerSize ?? ""; } catch { }

                    // Dimensions
                    try { hole.Diameter = holeData.HoleDiameter; } catch { }  // In meters
                    try { hole.Depth = holeData.HoleDepth; } catch { }
                    try { hole.IsThrough = holeData.EndCondition == (int)swEndConditions_e.swEndCondThroughAll; } catch { }

                    // Thread info - check both hole type and feature name
                    hole.IsTapped = hole.HoleType.Contains("Tap") || feat.Name.ToLower().Contains("tap");
                    if (hole.IsTapped)
                    {
                        try { hole.ThreadSize = holeData.FastenerSize ?? ""; } catch { }
                        try { hole.ThreadDepth = holeData.ThreadDepth; } catch { }
                        try { hole.ThreadClass = holeData.ThreadClass?.ToString() ?? ""; } catch { }

                        // Fallback: parse thread size from feature name (e.g., "Tap Drill for M6x1.0 Tap1")
                        if (string.IsNullOrEmpty(hole.ThreadSize))
                        {
                            var match = System.Text.RegularExpressions.Regex.Match(feat.Name, @"(M\d+(?:\.\d+)?(?:x\d+(?:\.\d+)?)?)", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
                            if (match.Success)
                                hole.ThreadSize = match.Groups[1].Value;
                        }
                    }

                    // Counterbore info (type 1)
                    if (holeType == 1)
                    {
                        try { hole.CounterboreDiameter = holeData.CounterBoreDiameter; } catch { }
                        try { hole.CounterboreDepth = holeData.CounterBoreDepth; } catch { }
                    }

                    // Countersink info (type 2)
                    if (holeType == 2)
                    {
                        try { hole.CountersinkDiameter = holeData.CounterSinkDiameter; } catch { }
                        try { hole.CountersinkAngle = holeData.CounterSinkAngle * (180.0 / Math.PI); } catch { }
                    }

                    // End condition
                    try { hole.EndCondition = GetEndConditionString((swEndConditions_e)holeData.EndCondition); } catch { }

                    // Instance count
                    try
                    {
                        // Get instance count from sketch points if available
                        IFeature sketch = (IFeature)feat.GetFirstSubFeature();
                        if (sketch != null && sketch.GetTypeName2() == "ProfileFeature")
                        {
                            ISketch sk = (ISketch)sketch.GetSpecificFeature2();
                            if (sk != null)
                            {
                                object[] points = (object[])sk.GetSketchPoints2();
                                hole.InstanceCount = points?.Length ?? 1;

                                foreach (object ptObj in points ?? new object[0])
                                {
                                    ISketchPoint pt = (ISketchPoint)ptObj;
                                    if (pt != null)
                                    {
                                        hole.InstanceLocations.Add(new double[] { pt.X, pt.Y, pt.Z });
                                    }
                                }
                            }
                        }
                    }
                    catch { hole.InstanceCount = 1; }

                    holeData.ReleaseSelectionAccess();
                }

                // If diameter is 0, try to parse from feature name
                if (hole.Diameter == 0 && !string.IsNullOrEmpty(feat.Name))
                {
                    hole.Diameter = ParseDiameterFromName(feat.Name);
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: Could not fully extract hole wizard data for '{feat.Name}': {ex.Message}");
            }

            collection.HoleWizardHoles.Add(hole);
        }

        /// <summary>
        /// Parse diameter from hole feature name (fallback for API bug)
        /// </summary>
        private double ParseDiameterFromName(string name)
        {
            try
            {
                // Pattern: Look for (X.XXXXX) or just a number followed by "mm" or "Diameter"
                var match = System.Text.RegularExpressions.Regex.Match(name, @"\(([0-9.]+)\)");
                if (match.Success)
                {
                    if (double.TryParse(match.Groups[1].Value, out double diameter))
                    {
                        // Assume inches, convert to meters
                        return diameter * 0.0254;
                    }
                }

                // Try pattern: "M8" -> 8mm
                match = System.Text.RegularExpressions.Regex.Match(name, @"M(\d+(?:\.\d+)?)");
                if (match.Success)
                {
                    if (double.TryParse(match.Groups[1].Value, out double diameter))
                    {
                        return diameter / 1000.0;  // mm to meters
                    }
                }
            }
            catch { }

            return 0;
        }

        #endregion

        #region Extrude/Cut Extraction

        private void ExtractExtrude(IModelDoc2 doc, IFeature feat, FeatureCollection collection, bool isSuppressed, Dictionary<string, bool> suppressionByConfig, bool isCut)
        {
            var extrudeData = new ExtrudeFeature
            {
                Name = feat.Name,
                TypeName = feat.GetTypeName2(),
                TreeOrder = _featureOrder++
            };

            SetFeatureBaseProperties(extrudeData, feat, isSuppressed, suppressionByConfig);

            try
            {
                IExtrudeFeatureData2 data = (IExtrudeFeatureData2)feat.GetDefinition();

                if (data != null && data.AccessSelections(doc, null))
                {
                    // Direction 1
                    try { extrudeData.Direction1EndCondition = GetEndConditionString((swEndConditions_e)data.GetEndCondition(true)); } catch { }
                    try { extrudeData.Direction1Depth = data.GetDepth(true); } catch { }
                    try { extrudeData.Direction1ReverseDirection = data.ReverseDirection; } catch { }

                    // Direction 2 (if bidirectional)
                    try
                    {
                        int endCond2 = data.GetEndCondition(false);
                        double depth2 = data.GetDepth(false);
                        extrudeData.IsTwoDirectional = endCond2 != (int)swEndConditions_e.swEndCondBlind || depth2 > 0;
                        if (extrudeData.IsTwoDirectional)
                        {
                            extrudeData.Direction2EndCondition = GetEndConditionString((swEndConditions_e)endCond2);
                            extrudeData.Direction2Depth = depth2;
                        }
                    }
                    catch { }

                    // Draft - these properties may not exist, use reflection or skip
                    try
                    {
                        // Use dynamic to safely try accessing properties that may not exist
                        dynamic dynData = data;
                        extrudeData.HasDraft = dynData.Draft;
                        if (extrudeData.HasDraft)
                        {
                            extrudeData.DraftAngle = dynData.DraftAngle * (180.0 / Math.PI);
                            extrudeData.DraftOutward = dynData.DraftOutward;
                        }
                    }
                    catch { extrudeData.HasDraft = false; }

                    // Get sketch name - use safer approach
                    try
                    {
                        IFeature sketchFeat = (IFeature)feat.GetFirstSubFeature();
                        if (sketchFeat != null)
                        {
                            extrudeData.SketchName = sketchFeat.Name;
                        }
                    }
                    catch { }

                    data.ReleaseSelectionAccess();
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: Could not fully extract extrude data for '{feat.Name}': {ex.Message}");
            }

            if (isCut)
            {
                collection.Cuts.Add(new CutFeature
                {
                    Name = extrudeData.Name,
                    TypeName = extrudeData.TypeName,
                    TreeOrder = extrudeData.TreeOrder,
                    IsSuppressed = extrudeData.IsSuppressed,
                    Direction1EndCondition = extrudeData.Direction1EndCondition,
                    Direction1Depth = extrudeData.Direction1Depth,
                    Direction1ReverseDirection = extrudeData.Direction1ReverseDirection,
                    IsTwoDirectional = extrudeData.IsTwoDirectional,
                    Direction2EndCondition = extrudeData.Direction2EndCondition,
                    Direction2Depth = extrudeData.Direction2Depth,
                    HasDraft = extrudeData.HasDraft,
                    DraftAngle = extrudeData.DraftAngle,
                    SketchName = extrudeData.SketchName
                });
            }
            else
            {
                collection.Extrudes.Add(extrudeData);
            }
        }

        #endregion

        #region Revolve/Sweep/Loft Extraction

        private void ExtractRevolve(IModelDoc2 doc, IFeature feat, FeatureCollection collection, bool isSuppressed, Dictionary<string, bool> suppressionByConfig)
        {
            var revolve = new RevolveFeature
            {
                Name = feat.Name,
                TypeName = feat.GetTypeName2(),
                TreeOrder = _featureOrder++
            };

            SetFeatureBaseProperties(revolve, feat, isSuppressed, suppressionByConfig);

            try
            {
                IRevolveFeatureData2 data = (IRevolveFeatureData2)feat.GetDefinition();

                if (data != null && data.AccessSelections(doc, null))
                {
                    try { revolve.RevolutionType = GetRevolveTypeString(data.Type); } catch { }

                    // Get angle using available properties
                    try
                    {
                        dynamic dynData = data;
                        revolve.Angle = dynData.RevolutionAngle * (180.0 / Math.PI);
                    }
                    catch
                    {
                        // Try alternative property names
                        try { revolve.Angle = data.GetRevolutionAngle(true) * (180.0 / Math.PI); } catch { }
                    }

                    data.ReleaseSelectionAccess();
                }
            }
            catch { }

            collection.Revolves.Add(revolve);
        }

        private void ExtractSweep(IModelDoc2 doc, IFeature feat, FeatureCollection collection, bool isSuppressed, Dictionary<string, bool> suppressionByConfig)
        {
            var sweep = new SweepFeature
            {
                Name = feat.Name,
                TypeName = feat.GetTypeName2(),
                TreeOrder = _featureOrder++
            };

            SetFeatureBaseProperties(sweep, feat, isSuppressed, suppressionByConfig);
            collection.Sweeps.Add(sweep);
        }

        private void ExtractLoft(IModelDoc2 doc, IFeature feat, FeatureCollection collection, bool isSuppressed, Dictionary<string, bool> suppressionByConfig)
        {
            var loft = new LoftFeature
            {
                Name = feat.Name,
                TypeName = feat.GetTypeName2(),
                TreeOrder = _featureOrder++
            };

            SetFeatureBaseProperties(loft, feat, isSuppressed, suppressionByConfig);
            collection.Lofts.Add(loft);
        }

        #endregion

        #region Fillet/Chamfer Extraction

        private void ExtractFillet(IModelDoc2 doc, IFeature feat, FeatureCollection collection, bool isSuppressed, Dictionary<string, bool> suppressionByConfig)
        {
            var fillet = new FilletFeature
            {
                Name = feat.Name,
                TypeName = "Fillet",
                TreeOrder = _featureOrder++
            };

            SetFeatureBaseProperties(fillet, feat, isSuppressed, suppressionByConfig);

            try
            {
                ISimpleFilletFeatureData2 data = (ISimpleFilletFeatureData2)feat.GetDefinition();

                if (data != null && data.AccessSelections(doc, null))
                {
                    try { fillet.FilletType = GetFilletTypeString(data.Type); } catch { }
                    try { fillet.Radius = data.DefaultRadius; } catch { }
                    try { fillet.PropagateToTangentFaces = data.PropagateFeatureToParts; } catch { }

                    // Get edge count
                    try
                    {
                        object edgesObj = data.Edges;
                        if (edgesObj is object[] edges)
                        {
                            fillet.EdgeCount = edges.Length;
                        }
                    }
                    catch { }

                    data.ReleaseSelectionAccess();
                }
            }
            catch { }

            collection.Fillets.Add(fillet);
        }

        private void ExtractChamfer(IModelDoc2 doc, IFeature feat, FeatureCollection collection, bool isSuppressed, Dictionary<string, bool> suppressionByConfig)
        {
            var chamfer = new ChamferFeature
            {
                Name = feat.Name,
                TypeName = "Chamfer",
                TreeOrder = _featureOrder++
            };

            SetFeatureBaseProperties(chamfer, feat, isSuppressed, suppressionByConfig);

            try
            {
                IChamferFeatureData2 data = (IChamferFeatureData2)feat.GetDefinition();

                if (data != null && data.AccessSelections(doc, null))
                {
                    try { chamfer.ChamferType = GetChamferTypeString(data.Type); } catch { }

                    // Get dimensions using dynamic to safely try accessing properties
                    try
                    {
                        dynamic dynData = data;
                        chamfer.Distance = dynData.Distance1;
                        chamfer.Distance2 = dynData.Distance2;
                        chamfer.Angle = dynData.Angle * (180.0 / Math.PI);
                    }
                    catch { /* Properties may not exist in this API version */ }

                    data.ReleaseSelectionAccess();
                }
            }
            catch { }

            collection.Chamfers.Add(chamfer);
        }

        #endregion

        #region Pattern Extraction

        private void ExtractLinearPattern(IModelDoc2 doc, IFeature feat, FeatureCollection collection, bool isSuppressed, Dictionary<string, bool> suppressionByConfig)
        {
            var pattern = new PatternFeature
            {
                Name = feat.Name,
                TypeName = "LPattern",
                TreeOrder = _featureOrder++,
                PatternType = "Linear"
            };

            SetFeatureBaseProperties(pattern, feat, isSuppressed, suppressionByConfig);

            try
            {
                ILinearPatternFeatureData data = (ILinearPatternFeatureData)feat.GetDefinition();

                if (data != null && data.AccessSelections(doc, null))
                {
                    try { pattern.Direction1Count = data.D1TotalInstances; } catch { }
                    try { pattern.Direction1Spacing = data.D1Spacing; } catch { }
                    try { pattern.Direction2Count = data.D2TotalInstances; } catch { }
                    try { pattern.Direction2Spacing = data.D2Spacing; } catch { }

                    // Calculate total instances
                    pattern.TotalInstances = pattern.Direction1Count * Math.Max(1, pattern.Direction2Count);

                    // Get seed features
                    try
                    {
                        object seedObj = data.PatternFeatureArray;
                        if (seedObj is object[] seeds)
                        {
                            foreach (object s in seeds)
                            {
                                if (s is IFeature seedFeat)
                                    pattern.SeedFeatures.Add(seedFeat.Name);
                            }
                        }
                    }
                    catch { }

                    // Get skipped instances
                    try
                    {
                        object skippedObj = data.SkippedItemArray;
                        if (skippedObj is int[] skipped)
                        {
                            pattern.SkippedInstances.AddRange(skipped);
                        }
                    }
                    catch { }

                    data.ReleaseSelectionAccess();
                }
            }
            catch { }

            collection.Patterns.Add(pattern);
        }

        private void ExtractCircularPattern(IModelDoc2 doc, IFeature feat, FeatureCollection collection, bool isSuppressed, Dictionary<string, bool> suppressionByConfig)
        {
            var pattern = new PatternFeature
            {
                Name = feat.Name,
                TypeName = "CirPattern",
                TreeOrder = _featureOrder++,
                PatternType = "Circular"
            };

            SetFeatureBaseProperties(pattern, feat, isSuppressed, suppressionByConfig);

            try
            {
                ICircularPatternFeatureData data = (ICircularPatternFeatureData)feat.GetDefinition();

                if (data != null && data.AccessSelections(doc, null))
                {
                    try { pattern.InstanceCount = data.TotalInstances; } catch { }
                    try { pattern.TotalInstances = data.TotalInstances; } catch { }
                    try { pattern.TotalAngle = data.Spacing * (180.0 / Math.PI); } catch { }
                    try { pattern.EqualSpacing = data.EqualSpacing; } catch { }

                    // Get seed features
                    try
                    {
                        object seedObj = data.PatternFeatureArray;
                        if (seedObj is object[] seeds)
                        {
                            foreach (object s in seeds)
                            {
                                if (s is IFeature seedFeat)
                                    pattern.SeedFeatures.Add(seedFeat.Name);
                            }
                        }
                    }
                    catch { }

                    // Get skipped instances
                    try
                    {
                        object skippedObj = data.SkippedItemArray;
                        if (skippedObj is int[] skipped)
                        {
                            pattern.SkippedInstances.AddRange(skipped);
                        }
                    }
                    catch { }

                    data.ReleaseSelectionAccess();
                }
            }
            catch { }

            collection.Patterns.Add(pattern);
        }

        private void ExtractMirrorPattern(IModelDoc2 doc, IFeature feat, FeatureCollection collection, bool isSuppressed, Dictionary<string, bool> suppressionByConfig)
        {
            var pattern = new PatternFeature
            {
                Name = feat.Name,
                TypeName = "MirrorPattern",
                TreeOrder = _featureOrder++,
                PatternType = "Mirror",
                TotalInstances = 2  // Original + mirror
            };

            SetFeatureBaseProperties(pattern, feat, isSuppressed, suppressionByConfig);

            try
            {
                IMirrorPatternFeatureData data = (IMirrorPatternFeatureData)feat.GetDefinition();

                if (data != null && data.AccessSelections(doc, null))
                {
                    // Get mirror plane - try dynamic access
                    try
                    {
                        dynamic dynData = data;
                        object planeRef = dynData.MirrorPlane;
                        if (planeRef is IFeature planeFeature)
                        {
                            pattern.MirrorPlane = planeFeature.Name;
                        }
                    }
                    catch { }

                    // Get seed features
                    try
                    {
                        object seedObj = data.PatternFeatureArray;
                        if (seedObj is object[] seeds)
                        {
                            foreach (object s in seeds)
                            {
                                if (s is IFeature seedFeat)
                                    pattern.SeedFeatures.Add(seedFeat.Name);
                            }
                        }
                    }
                    catch { }

                    data.ReleaseSelectionAccess();
                }
            }
            catch { }

            collection.Patterns.Add(pattern);
        }

        #endregion

        #region Sheet Metal Extraction

        private void ExtractSheetMetal(IModelDoc2 doc, IFeature feat, FeatureCollection collection, bool isSuppressed, Dictionary<string, bool> suppressionByConfig, string smType)
        {
            var sheetMetal = new SheetMetalFeature
            {
                Name = feat.Name,
                TypeName = smType,
                TreeOrder = _featureOrder++,
                SheetMetalType = smType
            };

            SetFeatureBaseProperties(sheetMetal, feat, isSuppressed, suppressionByConfig);

            try
            {
                // For base flange, get sheet metal parameters
                if (smType == "SMBaseFlange")
                {
                    IBaseFlangeFeatureData data = (IBaseFlangeFeatureData)feat.GetDefinition();

                    if (data != null && data.AccessSelections(doc, null))
                    {
                        try { sheetMetal.Thickness = data.Thickness; } catch { }
                        try { sheetMetal.DefaultBendRadius = data.BendRadius; } catch { }
                        try { sheetMetal.KFactor = data.KFactor; } catch { }

                        data.ReleaseSelectionAccess();
                    }
                }
                else if (smType == "FlatPattern")
                {
                    // Extract flat pattern info if available
                    sheetMetal.FlatPattern = new FlatPatternInfo();
                }
            }
            catch { }

            collection.SheetMetal.Add(sheetMetal);
        }

        #endregion

        #region Helper Methods

        private bool IsModelingFeature(string typeName)
        {
            // Filter out non-modeling features (folders, sketches, reference geometry, display items, etc.)
            string[] nonModelingTypes = {
                // Sketch and profile features
                "ProfileFeature", "3DProfileFeature", "Sketch",
                // Reference geometry
                "RefPlane", "RefAxis", "RefPoint", "OriginProfileFeature",
                // Folder types
                "HistoryFolder", "DetailCabinet", "BodyFolder", "SolidBodyFolder", "SurfaceBodyFolder",
                "FavoriteFolder", "SelectionSetFolder", "SensorFolder", "DocsFolder",
                "NotesAreaFtrFolder", "InkMarkupFolder", "EnvFolder", "CommentsFolder", "EqnFolder",
                // Display and annotation features
                "AmbientLight", "DirectionLight", "AnnotationViewFeat",
                // Material
                "MaterialIdent", "MaterialFolder",
                // Other system features
                "LiveSectionFolder", "FlatPatternFolder", "CosmeticWeldFolder",
                "MateGroup", "MateReferenceGroupFolder", "CutListFolder"
            };

            // Also filter anything ending with "Folder"
            if (typeName.EndsWith("Folder", StringComparison.OrdinalIgnoreCase))
                return false;

            return !Array.Exists(nonModelingTypes, t => t.Equals(typeName, StringComparison.OrdinalIgnoreCase));
        }

        /// <summary>
        /// Get suppression state for a feature in all configurations
        /// </summary>
        private Dictionary<string, bool> GetSuppressionByConfig(IFeature feat)
        {
            var result = new Dictionary<string, bool>();

            foreach (string configName in _allConfigNames)
            {
                try
                {
                    // Check suppression state in this configuration
                    object suppResult = feat.IsSuppressed2(
                        (int)swInConfigurationOpts_e.swSpecifyConfiguration,
                        new string[] { configName });

                    if (suppResult is bool[] suppState && suppState.Length > 0)
                        result[configName] = suppState[0];
                    else
                        result[configName] = false;
                }
                catch
                {
                    result[configName] = false;  // Assume not suppressed if we can't determine
                }
            }

            return result;
        }

        /// <summary>
        /// Set common feature properties including suppression states
        /// </summary>
        private void SetFeatureBaseProperties(FeatureBase feature, IFeature feat, bool isSuppressed, Dictionary<string, bool> suppressionByConfig)
        {
            feature.IsSuppressed = isSuppressed;
            feature.SuppressionByConfig = suppressionByConfig;
            feature.ExtractedInConfig = _activeConfigName;
        }

        private string GetHoleTypeString(int type)
        {
            // swWzdHoleTypes_e values
            switch (type)
            {
                case 0: return "Hole";              // swWzdHole
                case 1: return "Counterbore";       // swWzdCounterBore
                case 2: return "Countersink";       // swWzdCounterSink
                case 3: return "Straight Tap";      // swWzdStraightTap
                case 4: return "Tapered Tap";       // swWzdTaperedTap
                case 5: return "Pipe Tap (Drilled)";// swWzdPipeTapDrilled
                case 6: return "Pipe Tap (Tapered)";// swWzdPipeTapTapered
                case 7: return "Legacy Hole";       // swWzdLegacy
                default: return "Unknown";
            }
        }

        private string GetHoleStandardString(int std)
        {
            // swWzdGeneralStandardTypes_e values
            switch (std)
            {
                case 0: return "ANSI Inch";      // swWzdANSIInch
                case 1: return "ANSI Metric";   // swWzdANSIMetric
                case 2: return "ISO";           // swWzdISO
                case 3: return "DIN";           // swWzdDIN
                case 4: return "JIS";           // swWzdJIS
                case 5: return "BSI";           // swWzdBSI
                case 6: return "GB";            // swWzdGB
                default: return "Unknown";
            }
        }

        private string GetEndConditionString(swEndConditions_e cond)
        {
            switch (cond)
            {
                case swEndConditions_e.swEndCondBlind: return "Blind";
                case swEndConditions_e.swEndCondThroughAll: return "Through All";
                case swEndConditions_e.swEndCondThroughAllBoth: return "Through All Both";
                case swEndConditions_e.swEndCondUpToNext: return "Up To Next";
                case swEndConditions_e.swEndCondUpToSurface: return "Up To Surface";
                case swEndConditions_e.swEndCondUpToBody: return "Up To Body";
                case swEndConditions_e.swEndCondMidPlane: return "Mid Plane";
                case swEndConditions_e.swEndCondOffsetFromSurface: return "Offset From Surface";
                case swEndConditions_e.swEndCondUpToVertex: return "Up To Vertex";
                default: return "Unknown";
            }
        }

        private string GetRevolveTypeString(int type)
        {
            // swRevolveType_e values
            switch (type)
            {
                case 0: return "One-Direction";
                case 1: return "Mid-Plane";
                case 2: return "Two-Direction";
                default: return "Unknown";
            }
        }

        private string GetFilletTypeString(int type)
        {
            // swFilletType_e values
            switch (type)
            {
                case 0: return "Constant Size";
                case 1: return "Variable Size";
                case 2: return "Face Fillet";
                case 3: return "Full Round";
                default: return "Unknown";
            }
        }

        private string GetChamferTypeString(int type)
        {
            // swChamferType_e values
            switch (type)
            {
                case 0: return "Angle-Distance";
                case 1: return "Distance-Distance";
                case 2: return "Vertex";
                case 3: return "Offset Face";
                default: return "Unknown";
            }
        }

        #endregion
    }
}
