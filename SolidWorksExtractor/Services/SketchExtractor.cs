using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorksExtractor.Models;

namespace SolidWorksExtractor.Services
{
    /// <summary>
    /// Extracts sketch dimensions and attached entity geometry from all sketches in a part.
    /// Produces data for deterministic inspection: programmatic matching of part-side
    /// sketch dimensions to drawing-side annotations via normalized identity keys.
    /// </summary>
    public class SketchExtractor
    {
        private HashSet<string> _processedSketches = new HashSet<string>();

        /// <summary>
        /// Extract all sketches with their dimensions from a part document.
        /// Walks the feature tree to find all ProfileFeature nodes (consumed and unconsumed).
        /// </summary>
        public List<SketchInfo> ExtractSketches(IModelDoc2 doc)
        {
            var sketches = new List<SketchInfo>();
            _processedSketches.Clear();

            if (doc == null)
                return sketches;

            try
            {
                // Two-pass approach: consumed sketches first (with parent context),
                // then unconsumed sketches. The flat feature list returns sketches
                // BEFORE their consuming features (e.g., Sketch1 appears before
                // Boss-Extrude1), so a single-pass would miss the parent info.

                // Pass 1: Walk all features, extract consumed sketches from sub-features
                IFeature feat = (IFeature)doc.FirstFeature();
                while (feat != null)
                {
                    try
                    {
                        string typeName = feat.GetTypeName2();

                        IFeature sub = (IFeature)feat.GetFirstSubFeature();
                        while (sub != null)
                        {
                            try
                            {
                                string subType = sub.GetTypeName2();
                                if (subType == "ProfileFeature" || subType == "3DProfileFeature")
                                {
                                    TryExtractSketch(sub, feat.Name, typeName, sketches);
                                }
                            }
                            catch (Exception ex)
                            {
                                Console.WriteLine($"    Warning: Error processing sub-feature: {ex.Message}");
                            }
                            sub = (IFeature)sub.GetNextSubFeature();
                        }
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine($"    Warning: Error walking feature '{feat.Name}': {ex.Message}");
                    }
                    feat = (IFeature)feat.GetNextFeature();
                }

                // Pass 2: Walk again for unconsumed sketches (top-level, no parent)
                feat = (IFeature)doc.FirstFeature();
                while (feat != null)
                {
                    try
                    {
                        string typeName = feat.GetTypeName2();
                        if (typeName == "ProfileFeature" || typeName == "3DProfileFeature")
                        {
                            TryExtractSketch(feat, null, null, sketches);
                        }
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine($"    Warning: Error walking feature '{feat.Name}': {ex.Message}");
                    }
                    feat = (IFeature)feat.GetNextFeature();
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Error extracting sketches: {ex.Message}");
            }

            int totalDims = sketches.Sum(s => s.Dimensions.Count);
            Console.WriteLine($"    Found {sketches.Count} sketches with {totalDims} total dimensions");
            return sketches;
        }

        /// <summary>
        /// Attempt to extract a sketch, skipping if already processed.
        /// Only adds sketches that contain at least one dimension.
        /// </summary>
        private void TryExtractSketch(IFeature sketchFeat, string parentName, string parentType, List<SketchInfo> sketches)
        {
            string sketchName = sketchFeat.Name;
            if (_processedSketches.Contains(sketchName))
                return;
            _processedSketches.Add(sketchName);

            try
            {
                var sketchInfo = ExtractSketchData(sketchFeat, parentName, parentType);
                if (sketchInfo != null && sketchInfo.Dimensions.Count > 0)
                {
                    sketches.Add(sketchInfo);
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    Warning: Could not extract sketch '{sketchName}': {ex.Message}");
            }
        }

        /// <summary>
        /// Extract full sketch data: plane definition + all display dimensions + entity geometry.
        /// </summary>
        private SketchInfo ExtractSketchData(IFeature sketchFeat, string parentName, string parentType)
        {
            var info = new SketchInfo
            {
                SketchName = sketchFeat.Name,
                ParentFeatureName = parentName ?? "",
                ParentFeatureType = parentType ?? ""
            };

            // Get ISketch for plane transform
            try
            {
                ISketch sketch = (ISketch)sketchFeat.GetSpecificFeature2();
                if (sketch != null)
                {
                    ExtractSketchPlane(sketch, info);
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    Warning: Could not get ISketch for '{info.SketchName}': {ex.Message}");
            }

            // Extract display dimensions
            ExtractDisplayDimensions(sketchFeat, info);

            return info;
        }

        #region Sketch Plane Extraction

        /// <summary>
        /// Extract the sketch plane definition from the sketch-to-model transform.
        /// Uses ISketch.ModelToSketchTransform.Inverse() to get the sketch-to-model matrix.
        ///
        /// SolidWorks ArrayData layout (row-vector convention, verified against GlbExporter.cs:285):
        ///   [R00 R01 R02  R10 R11 R12  R20 R21 R22  Tx Ty Tz  Scale]
        ///   indices:  0   1   2    3   4   5    6   7   8   9  10  11   12
        ///
        /// Transform: P' = scale * (M * P) + T  where M uses columns of stored matrix.
        /// Basis vectors map as:
        ///   X-axis: (1,0,0) -> (m[0], m[1], m[2])
        ///   Y-axis: (0,1,0) -> (m[3], m[4], m[5])
        ///   Normal: (0,0,1) -> (m[6], m[7], m[8])
        ///   Origin: translation = (m[9], m[10], m[11])
        /// </summary>
        private void ExtractSketchPlane(ISketch sketch, SketchInfo info)
        {
            try
            {
                IMathTransform modelToSketch = sketch.ModelToSketchTransform;
                if (modelToSketch == null)
                {
                    SetDefaultPlane(info);
                    return;
                }

                // We need sketch-to-model (the inverse)
                // IMathTransform.Inverse() returns object in the installed interop
                IMathTransform sketchToModel = (IMathTransform)modelToSketch.Inverse();
                if (sketchToModel == null)
                {
                    SetDefaultPlane(info);
                    return;
                }

                double[] m = (double[])sketchToModel.ArrayData;
                if (m == null || m.Length < 13)
                {
                    SetDefaultPlane(info);
                    return;
                }

                info.PlaneOrigin = new double[] { m[9], m[10], m[11] };
                info.PlaneXAxis = new double[] { m[0], m[1], m[2] };
                info.PlaneYAxis = new double[] { m[3], m[4], m[5] };
                info.PlaneNormal = new double[] { m[6], m[7], m[8] };
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    Warning: Could not extract sketch plane for '{info.SketchName}': {ex.Message}");
                SetDefaultPlane(info);
            }
        }

        private void SetDefaultPlane(SketchInfo info)
        {
            // Default to Front plane if transform extraction fails
            info.PlaneOrigin = new double[] { 0, 0, 0 };
            info.PlaneXAxis = new double[] { 1, 0, 0 };
            info.PlaneYAxis = new double[] { 0, 1, 0 };
            info.PlaneNormal = new double[] { 0, 0, 1 };
        }

        #endregion

        #region Dimension Extraction

        /// <summary>
        /// Enumerate all display dimensions on a sketch feature.
        /// Uses IFeature.GetFirstDisplayDimension() / GetNextDisplayDimension()
        /// which return System.Object (cast to IDisplayDimension).
        /// </summary>
        private void ExtractDisplayDimensions(IFeature sketchFeat, SketchInfo info)
        {
            try
            {
                int maxDims = 1000; // Safety limit against infinite loops
                int dimCount = 0;

                object rawDispDim = sketchFeat.GetFirstDisplayDimension();

                while (rawDispDim != null && dimCount < maxDims)
                {
                    dimCount++;

                    IDisplayDimension dispDim = rawDispDim as IDisplayDimension;
                    if (dispDim != null)
                    {
                        var dimData = ExtractDimensionData(dispDim, info.SketchName);
                        if (dimData != null)
                        {
                            // Populate parent context for flattened Phase 2 access
                            dimData.SketchName = info.SketchName;
                            dimData.ParentFeatureName = info.ParentFeatureName;
                            info.Dimensions.Add(dimData);
                        }
                    }

                    // Move to next display dimension
                    try
                    {
                        rawDispDim = sketchFeat.GetNextDisplayDimension(rawDispDim);
                    }
                    catch
                    {
                        break;
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    Warning: Could not enumerate dimensions for '{info.SketchName}': {ex.Message}");
            }
        }

        /// <summary>
        /// Extract data from a single display dimension: name, value, type, tolerance, entities.
        /// </summary>
        private SketchDimensionData ExtractDimensionData(IDisplayDimension dispDim, string sketchName)
        {
            var dimData = new SketchDimensionData();

            try
            {
                IDimension dim = (IDimension)dispDim.GetDimension2(0);
                if (dim == null)
                    return null;

                // Raw full name: "D1@Sketch43@Part1.Part"
                try { dimData.RawFullName = dim.FullName ?? ""; }
                catch { dimData.RawFullName = ""; }

                // Normalized key: strip document qualifier -> "D1@Sketch43"
                dimData.NormalizedKey = NormalizeKey(dimData.RawFullName);

                // Short display name: "D1"
                dimData.DimensionName = GetShortName(dimData.RawFullName);

                // Value in SI units (meters for length, radians for angles)
                ExtractDimensionValue(dim, dimData);

                // Dimension type
                ExtractDimensionType(dispDim, dimData);

                // Tolerance
                ExtractTolerance(dim, dimData);

                // Reference dimension flag — use IsReferenceDim(), aligned with DrawingExtractor.cs:508
                try { dimData.IsReference = dispDim.IsReferenceDim(); } catch { }

                // Driven state
                try
                {
                    dimData.IsDriven = dim.DrivenState == (int)swDimensionDrivenState_e.swDimensionDriven;
                }
                catch { }

                // Attached entities (sketch geometry this dimension constrains)
                try
                {
                    dimData.AttachedEntities = ExtractAttachedEntities(dispDim);
                }
                catch { }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    Warning: Error extracting dimension in {sketchName}: {ex.Message}");
                return null;
            }

            return dimData;
        }

        private void ExtractDimensionValue(IDimension dim, SketchDimensionData dimData)
        {
            // Try multiple approaches to get SI value — API varies by interop version
            try
            {
                dimData.Value = dim.SystemValue;
                return;
            }
            catch { }

            try
            {
                object valObj = dim.GetSystemValue3(
                    (int)swInConfigurationOpts_e.swThisConfiguration, null);
                if (valObj is double dVal)
                    dimData.Value = dVal;
                else if (valObj is double[] dArr && dArr.Length > 0)
                    dimData.Value = dArr[0];
                return;
            }
            catch { }

            try
            {
                dimData.Value = dim.Value;
            }
            catch { }
        }

        private void ExtractDimensionType(IDisplayDimension dispDim, SketchDimensionData dimData)
        {
            try
            {
                dimData.DimensionType = GetDimensionTypeString(dispDim.Type2);
            }
            catch
            {
                try
                {
                    // Fallback: try dynamic access
                    dynamic dynDispDim = dispDim;
                    dimData.DimensionType = GetDimensionTypeString((int)dynDispDim.Type);
                }
                catch { dimData.DimensionType = "unknown"; }
            }
        }

        private void ExtractTolerance(IDimension dim, SketchDimensionData dimData)
        {
            try
            {
                // Use dynamic for tolerance since exact API varies
                dynamic dynDim = dim;
                double tolMax = 0, tolMin = 0;
                int tolType = dynDim.GetToleranceType();
                if (tolType != 0) // swTolNONE = 0
                {
                    tolMax = dynDim.GetToleranceMaxValue();
                    tolMin = dynDim.GetToleranceMinValue();
                    dimData.TolerancePlus = tolMax;
                    dimData.ToleranceMinus = tolMin;
                }
            }
            catch
            {
                // Tolerance info not available in this interop version
            }
        }

        #endregion

        #region Entity Geometry Extraction

        /// <summary>
        /// Extract the sketch entities (lines, arcs, points) attached to a dimension.
        /// Uses defensive COM casting pattern (Codex Round 4 Fix #1):
        ///   - Never direct-cast COM returns
        ///   - Always use 'as' cast with null guard
        ///   - Handle types array as int[] or object[]
        /// </summary>
        private List<SketchEntityData> ExtractAttachedEntities(IDisplayDimension dispDim)
        {
            var entities = new List<SketchEntityData>();

            try
            {
                // IDisplayDimension.GetAnnotation() returns object in the installed interop
                IAnnotation ann = (IAnnotation)dispDim.GetAnnotation();
                if (ann == null) return entities;

                // Defensive COM casting — never direct-cast.
                // COM SAFEARRAYs may marshal as object[], int[], or generic System.Array.
                object entitiesObj = ann.GetAttachedEntities3();
                object typesObj = ann.GetAttachedEntityTypes();

                if (entitiesObj == null || typesObj == null) return entities;

                // Handle entities: object[], or generic Array → cast each element
                object[] entityArr = entitiesObj as object[];
                if (entityArr == null && entitiesObj is Array entArr)
                {
                    entityArr = new object[entArr.Length];
                    for (int i = 0; i < entArr.Length; i++)
                        entityArr[i] = entArr.GetValue(i);
                }
                if (entityArr == null) return entities;

                // Handle types: int[], object[], or generic Array
                int[] types = null;
                if (typesObj is int[] intArr)
                {
                    types = intArr;
                }
                else if (typesObj is object[] objArr)
                {
                    try
                    {
                        types = objArr.Select(o => Convert.ToInt32(o)).ToArray();
                    }
                    catch { return entities; }
                }
                else if (typesObj is Array typArr)
                {
                    try
                    {
                        types = new int[typArr.Length];
                        for (int i = 0; i < typArr.Length; i++)
                            types[i] = Convert.ToInt32(typArr.GetValue(i));
                    }
                    catch { return entities; }
                }

                if (types == null || entityArr.Length != types.Length) return entities;

                for (int i = 0; i < entityArr.Length; i++)
                {
                    if (entityArr[i] == null) continue;

                    try
                    {
                        var entityData = ExtractSingleEntity(entityArr[i]);
                        if (entityData != null)
                            entities.Add(entityData);
                    }
                    catch { /* Skip entities that fail extraction */ }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    Warning: Could not extract attached entities: {ex.Message}");
            }

            return entities;
        }

        /// <summary>
        /// Extract geometry from a single sketch entity using try-each-cast pattern.
        /// Coordinates are in sketch-plane 2D (meters) from ISketchPoint.X/.Y.
        /// </summary>
        private SketchEntityData ExtractSingleEntity(object entityObj)
        {
            // Try SketchLine
            ISketchLine line = entityObj as ISketchLine;
            if (line != null)
            {
                var data = new SketchEntityData { EntityType = "SketchLine" };
                try
                {
                    ISketchPoint startPt = (ISketchPoint)line.GetStartPoint2();
                    ISketchPoint endPt = (ISketchPoint)line.GetEndPoint2();
                    if (startPt != null)
                        data.StartPoint = new double[] { startPt.X, startPt.Y };
                    if (endPt != null)
                        data.EndPoint = new double[] { endPt.X, endPt.Y };
                }
                catch { }
                return data;
            }

            // Try SketchArc (also covers full circles — no ISketchCircle in installed interop)
            ISketchArc arc = entityObj as ISketchArc;
            if (arc != null)
            {
                var data = new SketchEntityData { EntityType = "SketchArc" };
                try
                {
                    ISketchPoint centerPt = (ISketchPoint)arc.GetCenterPoint2();
                    if (centerPt != null)
                        data.Center = new double[] { centerPt.X, centerPt.Y };

                    data.Radius = arc.GetRadius();

                    // Compute start/end angles from arc endpoints relative to center
                    ISketchPoint startPt = (ISketchPoint)arc.GetStartPoint2();
                    ISketchPoint endPt = (ISketchPoint)arc.GetEndPoint2();
                    if (startPt != null && endPt != null && centerPt != null)
                    {
                        data.StartAngle = Math.Atan2(startPt.Y - centerPt.Y, startPt.X - centerPt.X);
                        data.EndAngle = Math.Atan2(endPt.Y - centerPt.Y, endPt.X - centerPt.X);

                        // Normalize to [0, 2*PI]
                        if (data.StartAngle < 0) data.StartAngle += 2 * Math.PI;
                        if (data.EndAngle < 0) data.EndAngle += 2 * Math.PI;

                        // Detect full circle: start point ≈ end point
                        double dist = Math.Sqrt(
                            Math.Pow(startPt.X - endPt.X, 2) +
                            Math.Pow(startPt.Y - endPt.Y, 2));
                        if (dist < 1e-10)
                        {
                            data.StartAngle = 0;
                            data.EndAngle = 2 * Math.PI;
                        }
                    }
                }
                catch { }
                return data;
            }

            // Try SketchPoint
            ISketchPoint point = entityObj as ISketchPoint;
            if (point != null)
            {
                var data = new SketchEntityData { EntityType = "SketchPoint" };
                data.Point = new double[] { point.X, point.Y };
                return data;
            }

            return null;
        }

        #endregion

        #region Helper Methods

        /// <summary>
        /// Normalize a dimension full name by stripping the document qualifier.
        /// "D1@Sketch43@Part1.Part" -> "D1@Sketch43"
        /// </summary>
        private string NormalizeKey(string fullName)
        {
            if (string.IsNullOrEmpty(fullName)) return "";
            int firstAt = fullName.IndexOf('@');
            if (firstAt < 0) return fullName;
            int secondAt = fullName.IndexOf('@', firstAt + 1);
            if (secondAt < 0) return fullName;
            return fullName.Substring(0, secondAt);
        }

        /// <summary>
        /// Extract the short dimension name from the full name.
        /// "D1@Sketch43@Part1.Part" -> "D1"
        /// </summary>
        private string GetShortName(string fullName)
        {
            if (string.IsNullOrEmpty(fullName)) return "";
            int atIdx = fullName.IndexOf('@');
            return atIdx < 0 ? fullName : fullName.Substring(0, atIdx);
        }

        /// <summary>
        /// Convert swDimensionType_e int to normalized string.
        /// Normalizes SolidWorks subtypes to base categories for Phase 2 matching:
        ///   Base types: 2=linear, 3=angular, 4=arcLength, 5=radial, 6=diametric
        ///   Subtypes:  11=swHorLinearDimension, 12=swVertLinearDimension → "linear"
        ///              14=swRadialLinearDimension → "radial"
        ///              15=swDiametricLinearDimension → "diametric"
        /// </summary>
        private string GetDimensionTypeString(int type)
        {
            switch (type)
            {
                // Base types
                case 2: return "linear";
                case 3: return "angular";
                case 4: return "arcLength";
                case 5: return "radial";
                case 6: return "diametric";

                // Linear subtypes → normalize to "linear"
                case 11: return "linear";   // swHorLinearDimension
                case 12: return "linear";   // swVertLinearDimension

                // Radial/diametric subtypes → normalize to base
                case 14: return "radial";    // swRadialLinearDimension
                case 15: return "diametric"; // swDiametricLinearDimension

                default: return "unknown";
            }
        }

        #endregion
    }
}
