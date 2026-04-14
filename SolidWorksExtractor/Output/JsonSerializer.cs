using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using SolidWorksExtractor.Models;

namespace SolidWorksExtractor.Output
{
    /// <summary>
    /// Custom JSON serializer to avoid external dependencies
    /// Produces clean, readable JSON output
    /// </summary>
    public class JsonSerializer
    {
        private readonly bool _indented;
        private int _indentLevel;
        private StringBuilder _sb;

        public JsonSerializer(bool indented = true)
        {
            _indented = indented;
        }

        /// <summary>
        /// Serialize PartData to JSON string
        /// </summary>
        public string Serialize(PartData part)
        {
            _sb = new StringBuilder();
            _indentLevel = 0;
            WritePartData(part);
            return _sb.ToString();
        }

        /// <summary>
        /// Serialize AssemblyData to JSON string
        /// </summary>
        public string Serialize(AssemblyData assembly)
        {
            _sb = new StringBuilder();
            _indentLevel = 0;
            WriteAssemblyData(assembly);
            return _sb.ToString();
        }

        /// <summary>
        /// Serialize DrawingData to JSON string
        /// </summary>
        public string Serialize(DrawingData drawing)
        {
            _sb = new StringBuilder();
            _indentLevel = 0;
            WriteDrawingData(drawing);
            return _sb.ToString();
        }

        /// <summary>
        /// Serialize BatchIndex to JSON string
        /// </summary>
        public string SerializeBatchIndex(BatchIndex index)
        {
            _sb = new StringBuilder();
            _indentLevel = 0;
            WriteBatchIndex(index);
            return _sb.ToString();
        }

        /// <summary>
        /// Save to file
        /// </summary>
        public void SaveToFile(string json, string filePath)
        {
            File.WriteAllText(filePath, json, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
            Console.WriteLine($"Saved: {filePath}");
        }

        #region Part Serialization

        private void WritePartData(PartData part)
        {
            BeginObject();

            WriteString("fileName", part.FileName);
            WriteString("filePath", part.FilePath);
            WriteString("extractionTime", part.ExtractionTime.ToString("o"));
            WriteString("solidWorksVersion", part.SolidWorksVersion);

            // Units specification - detect from document and provide conversions
            WriteName("units");
            BeginObject();
            WriteString("docUnitSystem", part.Physical.DocUnitSystem ?? "Unknown");
            WriteString("docLengthUnit", part.Physical.LengthUnit ?? "unknown");
            WriteString("docMassUnit", part.Physical.MassUnit ?? "unknown");
            WriteString("docAngleUnit", part.Physical.AngleUnit ?? "deg");
            WriteString("internalSystem", "SI (meters)");
            WriteString("note", "All internal values in SI (meters). Also provided in mm and inches for convenience.");
            WriteName("conversions");
            BeginObject();
            WriteNumber("metersToMm", 1000);
            WriteNumber("metersToInches", 39.3701);
            WriteNumber("mmToInches", 0.0393701);
            WriteNumber("inchesToMm", 25.4, isLast: true);
            EndObject(isLast: true);
            EndObject();

            // Identity
            WriteName("identity");
            WriteIdentity(part.Identity);

            // Physical properties
            WriteName("physical");
            WritePhysicalProperties(part.Physical);

            // Features
            WriteName("features");
            WriteFeatureCollection(part.Features);

            // Geometry
            WriteName("geometry");
            WriteGeometryGroundTruth(part.Geometry);

            // Configurations
            WriteName("configurations");
            WriteArray(part.Configurations, WriteConfigurationData);

            // Comparison-ready data (reconciled holes)
            WriteName("comparison");
            WriteComparisonData(part.Comparison);

            // Sketch dimensions (for deterministic inspection)
            WriteName("sketches");
            WriteSketches(part.Sketches);

            // View exports (screenshot metadata)
            WriteName("viewExports");
            WriteViewExportData(part.ViewExports);

            // Verification checklist
            WriteStringArray("verificationChecklist", part.VerificationChecklist, isLast: true);

            EndObject(isLast: true);  // Root object - no trailing comma
        }

        private void WriteViewExportData(ViewExportData viewExports)
        {
            BeginObject();

            WriteBool("colorized", viewExports.Colorized);

            WriteName("views");
            BeginArray();
            for (int i = 0; i < viewExports.Views.Count; i++)
            {
                var view = viewExports.Views[i];
                bool isLast = i == viewExports.Views.Count - 1;
                BeginObject();
                WriteString("viewName", view.ViewName);
                WriteString("fileName", view.FileName);
                WriteString("displayMode", view.DisplayMode, isLast: true);
                EndObject(isLast: isLast);
            }
            EndArray(isLast: true);

            EndObject();
            WriteLine();
        }

        private void WriteComparisonData(ComparisonReadyData comparison)
        {
            BeginObject();

            WriteName("holeGroups");
            WriteArray(comparison.HoleGroups, WriteHoleGroup);

            WriteName("allHoles");
            WriteArray(comparison.AllHoles, WriteHoleInstance);

            WriteName("slots");
            WriteArray(comparison.Slots, WriteSlotInstance, isLast: true);

            EndObject();
            WriteLine();
        }

        #region Sketch Serialization

        private void WriteSketches(List<SketchInfo> sketches)
        {
            if (sketches == null || sketches.Count == 0)
            {
                _sb.Append("[]");
                _sb.Append(",");
                WriteLine();
                return;
            }
            WriteArray(sketches, WriteSketchInfo);
        }

        private void WriteSketchInfo(SketchInfo sketch)
        {
            BeginObject();
            WriteString("sketchName", sketch.SketchName);
            WriteString("parentFeatureName", sketch.ParentFeatureName);
            WriteString("parentFeatureType", sketch.ParentFeatureType);

            WriteDoubleArray("planeOrigin", sketch.PlaneOrigin);
            WriteDoubleArray("planeXAxis", sketch.PlaneXAxis);
            WriteDoubleArray("planeYAxis", sketch.PlaneYAxis);
            WriteDoubleArray("planeNormal", sketch.PlaneNormal);

            WriteName("dimensions");
            if (sketch.Dimensions == null || sketch.Dimensions.Count == 0)
            {
                _sb.Append("[]");
                WriteLine();
            }
            else
            {
                WriteArray(sketch.Dimensions, WriteSketchDimension, isLast: true);
            }

            EndObject(isLast: true);
        }

        private void WriteSketchDimension(SketchDimensionData dim)
        {
            BeginObject();
            WriteString("dimensionName", dim.DimensionName);
            WriteString("normalizedKey", dim.NormalizedKey);
            WriteString("rawFullName", dim.RawFullName);
            WriteString("sketchName", dim.SketchName);
            WriteString("parentFeatureName", dim.ParentFeatureName);
            WriteNumber("value", dim.Value);

            // Convenience values
            if (dim.DimensionType == "angular")
            {
                WriteNumber("valueDeg", dim.Value * (180.0 / Math.PI));
            }
            else
            {
                WriteNumber("valueMm", dim.Value * 1000.0);
                WriteNumber("valueInch", dim.Value * 39.3701);
            }

            WriteString("dimensionType", dim.DimensionType);
            WriteNumber("tolerancePlus", dim.TolerancePlus);
            WriteNumber("toleranceMinus", dim.ToleranceMinus);
            WriteBool("isReference", dim.IsReference);
            WriteBool("isDriven", dim.IsDriven);

            WriteName("attachedEntities");
            if (dim.AttachedEntities == null || dim.AttachedEntities.Count == 0)
            {
                _sb.Append("[]");
                WriteLine();
            }
            else
            {
                WriteArray(dim.AttachedEntities, WriteSketchEntity, isLast: true);
            }

            EndObject(isLast: true);
        }

        private void WriteSketchEntity(SketchEntityData entity)
        {
            BeginObject();

            switch (entity.EntityType)
            {
                case "SketchLine":
                    WriteString("entityType", entity.EntityType);
                    WriteDoubleArray("startPoint", entity.StartPoint);
                    WriteDoubleArray("endPoint", entity.EndPoint, isLast: true);
                    break;

                case "SketchArc":
                    WriteString("entityType", entity.EntityType);
                    WriteDoubleArray("center", entity.Center);
                    WriteNumber("radius", entity.Radius);
                    WriteNumber("startAngle", entity.StartAngle);
                    WriteNumber("endAngle", entity.EndAngle, isLast: true);
                    break;

                case "SketchPoint":
                    WriteString("entityType", entity.EntityType);
                    WriteDoubleArray("point", entity.Point, isLast: true);
                    break;

                default:
                    WriteString("entityType", entity.EntityType ?? "Unknown", isLast: true);
                    break;
            }

            EndObject(isLast: true);
        }

        #endregion

        private void WriteHoleGroup(HoleGroup group)
        {
            BeginObject();
            WriteString("groupId", group.GroupId);
            WriteString("canonical", group.Canonical);
            WriteString("holeType", group.HoleType);

            // Diameters section - clear separation of thread nominal vs pilot/measured
            WriteName("diameters");
            BeginObject();

            // For tapped holes: thread nominal (major dia, e.g., 6mm for M6)
            if (group.Thread != null && group.NominalDiameter != null)
            {
                WriteNumber("threadNominalDiameterMm", group.NominalDiameter.Millimeters);
                WriteNumber("threadNominalDiameterMeters", group.NominalDiameter.SystemValue);
                WriteNumber("threadNominalDiameterInches", group.NominalDiameter.SystemValue * 39.3701);
            }

            // Pilot/tap drill diameter - from geometry measurement (what's actually modeled)
            if (group.MeasuredDiameter != null)
            {
                double measuredMm = group.MeasuredDiameter.Millimeters;
                double measuredIn = group.MeasuredDiameter.SystemValue * 39.3701;

                WriteNumber("pilotOrTapDrillDiameterMm", measuredMm);
                WriteNumber("pilotOrTapDrillDiameterInches", measuredIn);
                WriteNumber("pilotOrTapDrillDiameterMeters", group.MeasuredDiameter.SystemValue);

                // Nearest standard sizes
                var (stdInch, stdInchStr) = GetNearestStandardInchSize(measuredIn);
                var (stdMm, stdMmStr) = GetNearestStandardMmSize(measuredMm);

                WriteString("nearestStandardInch", stdInchStr);
                WriteNumber("nearestStandardInchDecimal", stdInch);
                WriteString("nearestStandardMm", stdMmStr);
                WriteNumber("nearestStandardMmValue", stdMm);

                // Preferred callout based on nearest standard
                string calloutPreferred = BuildPreferredCallout(group, stdInchStr, stdMmStr);
                WriteString("calloutPreferred", calloutPreferred, isLast: true);
            }
            else
            {
                WriteNumber("pilotOrTapDrillDiameterMm", 0);
                WriteNumber("pilotOrTapDrillDiameterInches", 0);
                WriteNumber("pilotOrTapDrillDiameterMeters", 0, isLast: true);
            }
            EndObject();

            // Depth
            if (group.Depth != null)
            {
                WriteName("depth");
                BeginObject();
                WriteNumber("mm", group.Depth.Millimeters);
                WriteNumber("inches", group.Depth.SystemValue * 39.3701);
                WriteNumber("meters", group.Depth.SystemValue, isLast: true);
                EndObject();
            }

            // Thread info (for tapped holes)
            if (group.Thread != null)
            {
                WriteName("thread");
                BeginObject();
                WriteString("callout", group.Thread.Callout);
                WriteString("standard", group.Thread.Standard);
                if (group.Thread.NominalDiameter != null)
                {
                    WriteNumber("majorDiameterMm", group.Thread.NominalDiameter.Millimeters);
                    WriteNumber("majorDiameterInches", group.Thread.NominalDiameter.SystemValue * 39.3701);
                }
                WriteNumber("pitch", group.Thread.Pitch);
                WriteString("threadClass", group.Thread.ThreadClass, isLast: true);
                EndObject();
            }

            WriteInt("count", group.Count);
            WriteString("source", group.Source);
            WriteString("confidence", group.Confidence);
            WriteString("reconciliationNote", group.ReconciliationNote, isLast: true);
            EndObject(isLast: true);
        }

        private void WriteHoleInstance(HoleInstance instance)
        {
            BeginObject();
            WriteString("instanceId", instance.InstanceId);
            WriteString("groupId", instance.GroupId);

            // Model center (raw geometry coordinates)
            if (instance.ModelCenter != null)
            {
                WriteName("modelCenter");
                BeginObject();
                WriteNumber("xMeters", instance.ModelCenter.X);
                WriteNumber("yMeters", instance.ModelCenter.Y);
                WriteNumber("zMeters", instance.ModelCenter.Z);
                WriteNumber("xMm", instance.ModelCenter.X * 1000);
                WriteNumber("yMm", instance.ModelCenter.Y * 1000);
                WriteNumber("zMm", instance.ModelCenter.Z * 1000, isLast: true);
                EndObject();
            }

            // Face entry center (normalized to face plane for matching)
            if (instance.FaceEntryCenter != null)
            {
                WriteName("faceEntryCenter");
                BeginObject();
                WriteNumber("xMeters", instance.FaceEntryCenter.X);
                WriteNumber("yMeters", instance.FaceEntryCenter.Y);
                WriteNumber("zMeters", instance.FaceEntryCenter.Z);
                WriteNumber("xMm", instance.FaceEntryCenter.X * 1000);
                WriteNumber("yMm", instance.FaceEntryCenter.Y * 1000);
                WriteNumber("zMm", instance.FaceEntryCenter.Z * 1000, isLast: true);
                EndObject();
            }

            // Axis direction
            if (instance.Axis != null)
            {
                WriteDoubleArray("axis", new double[] { instance.Axis.X, instance.Axis.Y, instance.Axis.Z });
            }

            // Measured diameter (from geometry)
            if (instance.MeasuredDiameter != null)
            {
                WriteNumber("measuredDiameterMm", instance.MeasuredDiameter.Millimeters);
                WriteNumber("measuredDiameterMeters", instance.MeasuredDiameter.SystemValue);
            }

            // Measured depth
            if (instance.MeasuredDepth != null)
            {
                WriteNumber("measuredDepthMm", instance.MeasuredDepth.Millimeters);
                WriteNumber("measuredDepthMeters", instance.MeasuredDepth.SystemValue);
            }

            WriteBool("isThrough", instance.IsThrough);
            WriteString("featureName", instance.FeatureName);
            WriteString("startFace", instance.StartFace);

            // Thread metadata (intent vs modeled)
            WriteBool("hasThreadIntent", instance.HasThreadIntent);
            WriteString("threadCallout", instance.ThreadCallout);
            WriteBool("threadModeled", instance.ThreadModeled, isLast: true);
            EndObject(isLast: true);
        }

        private void WriteSlotInstance(SlotInstance slot)
        {
            BeginObject();
            WriteString("slotId", slot.SlotId);

            if (slot.Length != null)
                WriteNumber("lengthMm", slot.Length.Millimeters);
            if (slot.Width != null)
                WriteNumber("widthMm", slot.Width.Millimeters);
            if (slot.Depth != null)
                WriteNumber("depthMm", slot.Depth.Millimeters);

            WriteBool("isThrough", slot.IsThrough, isLast: true);
            EndObject(isLast: true);
        }

        private void WriteIdentity(PartIdentity identity)
        {
            BeginObject();

            WriteString("partNumber", identity.PartNumber);
            WriteString("description", identity.Description);
            WriteString("revision", identity.Revision);
            WriteString("author", identity.Author);
            WriteString("material", identity.Material);
            WriteString("finish", identity.Finish);

            WriteName("customProperties");
            WriteDictionary(identity.CustomProperties);

            WriteName("configProperties");
            WriteDictionary(identity.ConfigProperties, isLast: true);

            EndObject();
        }

        private void WritePhysicalProperties(PhysicalProperties props)
        {
            BeginObject();

            WriteString("lengthUnit", props.LengthUnit);
            WriteString("massUnit", props.MassUnit);
            WriteNumber("mass", props.Mass);
            WriteNumber("volume", props.Volume);
            WriteNumber("surfaceArea", props.SurfaceArea);
            WriteDoubleArray("centerOfMass", props.CenterOfMass);
            WriteString("assignedMaterial", props.AssignedMaterial);
            WriteString("materialDatabase", props.MaterialDatabase);

            WriteName("boundingBox");
            WriteBoundingBox(props.BoundingBox, isLast: true);

            EndObject();
        }

        private void WriteBoundingBox(BoundingBox box, bool isLast = false)
        {
            BeginObject();
            WriteNumber("minX", box.MinX);
            WriteNumber("minY", box.MinY);
            WriteNumber("minZ", box.MinZ);
            WriteNumber("maxX", box.MaxX);
            WriteNumber("maxY", box.MaxY);
            WriteNumber("maxZ", box.MaxZ);
            WriteNumber("length", box.Length);
            WriteNumber("width", box.Width);
            WriteNumber("height", box.Height, isLast: true);
            EndObject(isLast);
        }

        private void WriteConfigurationData(ConfigurationData config)
        {
            BeginObject();
            WriteString("name", config.Name);
            WriteBool("isActive", config.IsActive);
            WriteString("description", config.Description);
            WriteName("properties");
            WriteDictionary(config.Properties, isLast: true);
            EndObject(isLast: true);
        }

        private void WriteFeatureCollection(FeatureCollection features)
        {
            BeginObject();

            WriteName("holeWizardHoles");
            WriteArray(features.HoleWizardHoles, WriteHoleWizardFeature);

            WriteName("extrudes");
            WriteArray(features.Extrudes, WriteExtrudeFeature);

            WriteName("cuts");
            WriteArray(features.Cuts, WriteCutFeature);

            WriteName("revolves");
            WriteArray(features.Revolves, WriteRevolveFeature);

            WriteName("fillets");
            WriteArray(features.Fillets, WriteFilletFeature);

            WriteName("chamfers");
            WriteArray(features.Chamfers, WriteChamferFeature);

            WriteName("patterns");
            WriteArray(features.Patterns, WritePatternFeature);

            WriteName("sheetMetal");
            WriteArray(features.SheetMetal, WriteSheetMetalFeature);

            WriteName("otherFeatures");
            WriteArray(features.OtherFeatures, WriteGenericFeature, isLast: true);

            EndObject();
        }

        private void WriteHoleWizardFeature(HoleWizardFeature hole)
        {
            BeginObject();
            WriteString("name", hole.Name);
            WriteString("holeType", hole.HoleType);
            WriteString("standard", hole.Standard);
            WriteString("fastenerSize", hole.FastenerSize);
            WriteNumber("diameter", hole.Diameter);
            WriteNumber("depth", hole.Depth);
            WriteBool("isThrough", hole.IsThrough);
            WriteBool("isTapped", hole.IsTapped);
            WriteString("threadSize", hole.ThreadSize);
            WriteNumber("threadDepth", hole.ThreadDepth);
            WriteNumber("counterboreDiameter", hole.CounterboreDiameter);
            WriteNumber("counterboreDepth", hole.CounterboreDepth);
            WriteNumber("countersinkDiameter", hole.CountersinkDiameter);
            WriteNumber("countersinkAngle", hole.CountersinkAngle);
            WriteString("endCondition", hole.EndCondition);
            WriteInt("instanceCount", hole.InstanceCount);
            WriteBool("isSuppressed", hole.IsSuppressed, isLast: true);
            EndObject(isLast: true);  // Array handles commas
        }

        private void WriteExtrudeFeature(ExtrudeFeature ext)
        {
            BeginObject();
            WriteString("name", ext.Name);
            WriteString("typeName", ext.TypeName);
            WriteString("direction1EndCondition", ext.Direction1EndCondition);
            WriteNumber("direction1Depth", ext.Direction1Depth);
            WriteBool("isTwoDirectional", ext.IsTwoDirectional);
            WriteString("direction2EndCondition", ext.Direction2EndCondition);
            WriteNumber("direction2Depth", ext.Direction2Depth);
            WriteBool("hasDraft", ext.HasDraft);
            WriteNumber("draftAngle", ext.DraftAngle);
            WriteString("sketchName", ext.SketchName);
            WriteBool("isSuppressed", ext.IsSuppressed, isLast: true);
            EndObject(isLast: true);
        }

        private void WriteCutFeature(CutFeature cut)
        {
            BeginObject();
            WriteString("name", cut.Name);
            WriteString("typeName", cut.TypeName);
            WriteString("direction1EndCondition", cut.Direction1EndCondition);
            WriteNumber("direction1Depth", cut.Direction1Depth);
            WriteBool("isTwoDirectional", cut.IsTwoDirectional);
            WriteString("direction2EndCondition", cut.Direction2EndCondition);
            WriteNumber("direction2Depth", cut.Direction2Depth);
            WriteString("sketchName", cut.SketchName);
            WriteBool("isSuppressed", cut.IsSuppressed, isLast: true);
            EndObject(isLast: true);
        }

        private void WriteRevolveFeature(RevolveFeature rev)
        {
            BeginObject();
            WriteString("name", rev.Name);
            WriteString("typeName", rev.TypeName);
            WriteString("revolutionType", rev.RevolutionType);
            WriteNumber("angle", rev.Angle);
            WriteNumber("angle2", rev.Angle2);
            WriteBool("isSuppressed", rev.IsSuppressed, isLast: true);
            EndObject(isLast: true);
        }

        private void WriteFilletFeature(FilletFeature fillet)
        {
            BeginObject();
            WriteString("name", fillet.Name);
            WriteString("filletType", fillet.FilletType);
            WriteNumber("radius", fillet.Radius);
            WriteInt("edgeCount", fillet.EdgeCount);
            WriteBool("isSuppressed", fillet.IsSuppressed, isLast: true);
            EndObject(isLast: true);
        }

        private void WriteChamferFeature(ChamferFeature chamfer)
        {
            BeginObject();
            WriteString("name", chamfer.Name);
            WriteString("chamferType", chamfer.ChamferType);
            WriteNumber("distance", chamfer.Distance);
            WriteNumber("distance2", chamfer.Distance2);
            WriteNumber("angle", chamfer.Angle);
            WriteBool("isSuppressed", chamfer.IsSuppressed, isLast: true);
            EndObject(isLast: true);
        }

        private void WritePatternFeature(PatternFeature pattern)
        {
            BeginObject();
            WriteString("name", pattern.Name);
            WriteString("patternType", pattern.PatternType);
            WriteInt("direction1Count", pattern.Direction1Count);
            WriteNumber("direction1Spacing", pattern.Direction1Spacing);
            WriteInt("direction2Count", pattern.Direction2Count);
            WriteNumber("direction2Spacing", pattern.Direction2Spacing);
            WriteInt("instanceCount", pattern.InstanceCount);
            WriteNumber("totalAngle", pattern.TotalAngle);
            WriteBool("isSuppressed", pattern.IsSuppressed, isLast: true);
            EndObject(isLast: true);
        }

        private void WriteSheetMetalFeature(SheetMetalFeature sm)
        {
            BeginObject();
            WriteString("name", sm.Name);
            WriteString("sheetMetalType", sm.SheetMetalType);
            WriteNumber("thickness", sm.Thickness);
            WriteNumber("defaultBendRadius", sm.DefaultBendRadius);
            WriteNumber("kFactor", sm.KFactor);
            WriteString("bendAllowanceType", sm.BendAllowanceType);
            WriteBool("isSuppressed", sm.IsSuppressed, isLast: true);
            EndObject(isLast: true);
        }

        private void WriteGenericFeature(GenericFeature feat)
        {
            BeginObject();
            WriteString("name", feat.Name);
            WriteString("typeName", feat.TypeName);
            WriteBool("isSuppressed", feat.IsSuppressed, isLast: true);
            EndObject(isLast: true);
        }

        private void WriteGeometryGroundTruth(GeometryGroundTruth geo)
        {
            BeginObject();

            WriteName("cylinders");
            WriteArray(geo.Cylinders, WriteCylindricalFeature);

            WriteName("planarFaces");
            BeginArray();
            // Limit to 20 planar faces to keep JSON manageable
            for (int i = 0; i < Math.Min(20, geo.PlanarFaces.Count); i++)
            {
                WritePlanarFace(geo.PlanarFaces[i]);
                if (i < Math.Min(20, geo.PlanarFaces.Count) - 1)
                    _sb.Append(",");
                WriteLine();
            }
            EndArray();

            WriteName("edges");
            WriteEdgeSummary(geo.Edges, isLast: true);

            EndObject();
        }

        private void WriteCylindricalFeature(CylindricalFeature cyl)
        {
            BeginObject();
            WriteString("id", cyl.Id);
            WriteString("type", cyl.Type.ToString());
            WriteBool("isInternal", cyl.IsInternal);
            WriteNumber("diameter", cyl.Diameter);
            WriteNumber("radius", cyl.Radius);
            WriteNumber("length", cyl.Length);
            WriteDoubleArray("axisPoint", cyl.AxisPoint);
            WriteDoubleArray("axisDirection", cyl.AxisDirection);
            WriteBool("isThrough", cyl.IsThrough);
            WriteBool("hasThread", cyl.HasThread);
            WriteInt("groupId", cyl.GroupId);
            WriteInt("instanceInGroup", cyl.InstanceInGroup, isLast: true);
            EndObject(isLast: true);
        }

        private void WritePlanarFace(PlanarFace face)
        {
            BeginObject();
            WriteString("id", face.Id);
            WriteString("orientation", face.Orientation);
            WriteDoubleArray("normal", face.Normal);
            WriteNumber("area", face.Area, isLast: true);
            EndObject(isLast: true);
        }

        private void WriteEdgeSummary(EdgeSummary edges, bool isLast = false)
        {
            BeginObject();
            WriteInt("totalEdgeCount", edges.TotalEdgeCount);
            WriteInt("linearEdgeCount", edges.LinearEdgeCount);
            WriteInt("circularEdgeCount", edges.CircularEdgeCount);
            WriteInt("helicalEdgeCount", edges.HelicalEdgeCount);
            WriteInt("splineEdgeCount", edges.SplineEdgeCount, isLast: true);
            EndObject(isLast);
        }

        #endregion

        #region Assembly Serialization

        private void WriteAssemblyData(AssemblyData assy)
        {
            BeginObject();

            WriteString("fileName", assy.FileName);
            WriteString("filePath", assy.FilePath);
            WriteString("extractionTime", assy.ExtractionTime.ToString("o"));

            WriteName("identity");
            WriteAssemblyIdentity(assy.Identity);

            WriteName("statistics");
            WriteStatistics(assy.Statistics);

            WriteName("components");
            WriteArray(assy.Components, WriteComponentData);

            WriteName("mates");
            WriteArray(assy.Mates, WriteMateData);

            WriteName("mateRelationships");
            WriteArray(assy.MateRelationships, WriteMateRelationship);

            WriteName("explodeSteps");
            WriteArray(assy.ExplodeSteps, WriteExplodeStepData);

            WriteName("assemblyFeatures");
            WriteFeatureCollection(assy.AssemblyFeatures);

            WriteName("viewExports");
            WriteViewExportData(assy.ViewExports);

            WriteName("partColorMapping");
            WriteDictionary(assy.PartColorMapping);

            WriteName("partDataCache");
            WritePartDataCache(assy.PartDataCache, isLast: true);

            EndObject(isLast: true);  // Root object - no trailing comma
        }

        private void WriteAssemblyIdentity(AssemblyIdentity id)
        {
            BeginObject();
            WriteString("assemblyNumber", id.AssemblyNumber);
            WriteString("description", id.Description);
            WriteString("revision", id.Revision);
            WriteString("author", id.Author);
            WriteName("customProperties");
            WriteDictionary(id.CustomProperties, isLast: true);
            EndObject();
        }

        private void WriteStatistics(AssemblyStatistics stats)
        {
            BeginObject();
            WriteInt("totalComponents", stats.TotalComponents);
            WriteInt("uniquePartCount", stats.UniquePartCount);
            WriteInt("subAssemblyCount", stats.SubAssemblyCount);
            WriteInt("totalMates", stats.TotalMates);
            WriteInt("resolvedCount", stats.ResolvedCount);
            WriteInt("lightweightCount", stats.LightweightCount);
            WriteInt("suppressedCount", stats.SuppressedCount);

            WriteName("mateTypeCounts");
            WriteDictionary(stats.MateTypeCounts, isLast: true);

            EndObject();
        }

        private void WriteComponentData(ComponentData comp)
        {
            BeginObject();
            WriteString("name", comp.Name);
            WriteString("referencedFileName", comp.ReferencedFileName);
            WriteString("type", comp.Type.ToString());
            WriteString("state", comp.State.ToString());
            WriteInt("level", comp.Level);
            WriteString("parentName", comp.ParentName);
            WriteBool("isSuppressed", comp.IsSuppressed);
            WriteBool("isLightweight", comp.IsLightweight);
            WriteString("activeConfiguration", comp.ActiveConfiguration);
            WriteString("partDataKey", comp.PartDataKey);

            WriteName("transform");
            WriteTransform(comp.Transform, isLast: true);

            EndObject(isLast: true);
        }

        private void WriteTransform(TransformMatrix t, bool isLast = false)
        {
            BeginObject();
            WriteDoubleArray("translation", t.Translation);
            WriteNumber("scale", t.Scale);

            // Rotation matrix (3x3 flattened row-major)
            if (t.Rotation != null)
            {
                var flat = new double[9];
                for (int r = 0; r < 3; r++)
                    for (int c = 0; c < 3; c++)
                        flat[r * 3 + c] = t.Rotation[r, c];
                WriteDoubleArray("rotation", flat);
            }

            // Euler angles (degrees, ZYX convention)
            if (t.EulerAngles != null)
                WriteDoubleArray("eulerAngles", t.EulerAngles);

            // Quaternion (W, X, Y, Z)
            WriteDoubleArray("quaternion", t.Quaternion, isLast: true);
            EndObject(isLast);
        }

        private void WriteMateData(MateData mate)
        {
            BeginObject();
            WriteString("name", mate.Name);
            WriteString("type", mate.TypeName);
            WriteNumber("distance", mate.Distance?.SystemValue ?? 0);
            WriteNumber("angle", mate.Angle?.SystemValue ?? 0);
            WriteBool("isFlipped", mate.IsFlipped);
            WriteBool("isSuppressed", mate.IsSuppressed);
            WriteString("alignment", mate.Alignment.ToString());

            // Mate limits for motion range
            if (mate.Limits != null)
            {
                WriteName("limits");
                BeginObject();
                WriteBool("hasMinimum", mate.Limits.HasMinimum);
                WriteBool("hasMaximum", mate.Limits.HasMaximum);
                WriteNumber("minimum", mate.Limits.Minimum?.SystemValue ?? 0);
                WriteNumber("maximum", mate.Limits.Maximum?.SystemValue ?? 0);
                WriteNumber("currentValue", mate.Limits.CurrentValue?.SystemValue ?? 0, isLast: true);
                EndObject(false);
            }

            WriteName("entity1");
            WriteMateEntity(mate.Entity1);

            WriteName("entity2");
            WriteMateEntity(mate.Entity2, isLast: true);

            EndObject(isLast: true);
        }

        private void WriteMateEntity(MateEntity ent, bool isLast = false)
        {
            BeginObject();
            WriteString("componentName", ent.ComponentName);
            WriteString("componentFileName", ent.ComponentFileName);
            WriteInt("instanceNumber", ent.InstanceNumber);
            WriteString("entityType", ent.EntityType.ToString());
            WriteString("geometryType", ent.GeometryType);

            // Geometry data for motion simulation
            if (ent.Point != null)
                WriteDoubleArray("point", ent.Point.ToArray());
            else
                WriteDoubleArray("point", null);

            if (ent.Direction != null)
                WriteDoubleArray("direction", ent.Direction.ToArray());
            else
                WriteDoubleArray("direction", null);

            WriteNumber("radius", ent.Radius?.SystemValue ?? 0, isLast: true);
            EndObject(isLast);
        }

        private void WriteMateRelationship(MateRelationship rel)
        {
            BeginObject();
            WriteString("component1", rel.Component1);
            WriteString("component1FileName", rel.Component1FileName);
            WriteString("component2", rel.Component2);
            WriteString("component2FileName", rel.Component2FileName);
            WriteInt("mateCount", rel.Mates.Count);
            WriteStringArray("inspectionRequirements", rel.InspectionRequirements, isLast: true);
            EndObject(isLast: true);
        }

        private void WriteExplodeStepData(ExplodeStepData step)
        {
            BeginObject();
            WriteString("explodeViewName", step.ExplodeViewName);
            WriteInt("stepIndex", step.StepIndex);
            WriteString("name", step.Name);
            WriteString("stepType", step.StepType);
            WriteStringArray("componentNames", step.ComponentNames);
            WriteStringArray("componentFileNames", step.ComponentFileNames);
            WriteDoubleArray("direction", step.Direction);
            WriteNumber("distanceMeters", step.DistanceMeters);
            WriteBool("reverseDirection", step.ReverseDirection);
            WriteNumber("rotationAngleRadians", step.RotationAngleRadians);
            WriteBool("reverseRotation", step.ReverseRotation, isLast: true);
            EndObject(isLast: true);
        }

        private void WritePartDataCache(Dictionary<string, PartData> cache, bool isLast = false)
        {
            BeginObject();
            int count = 0;
            int total = cache.Count;
            foreach (var kvp in cache)
            {
                count++;
                WriteName(kvp.Key);
                WritePartData(kvp.Value);
                if (count < total)
                    _sb.Append(",");
                WriteLine();
            }
            EndObject(isLast);
        }

        #endregion

        #region Drawing Serialization

        private void WriteDrawingData(DrawingData drawing)
        {
            BeginObject();

            WriteString("fileName", drawing.FileName);
            WriteString("filePath", drawing.FilePath);
            WriteString("partNumber", drawing.PartNumber);
            WriteString("extractionTime", drawing.ExtractionTime.ToString("o"));
            WriteString("solidWorksVersion", drawing.SolidWorksVersion);
            WriteNullableNumber("sheetWidth", drawing.SheetWidth);
            WriteNullableNumber("sheetHeight", drawing.SheetHeight);
            WriteString("referencedModelPath", drawing.ReferencedModelPath);

            WriteName("sheets");
            BeginArray();
            for (int i = 0; i < drawing.Sheets.Count; i++)
            {
                WriteDrawingSheet(drawing.Sheets[i]);
                if (i < drawing.Sheets.Count - 1)
                    _sb.Append(",");
                WriteLine();
            }
            EndArray(isLast: true);
            WriteLine();

            EndObject(isLast: true);
        }

        private void WriteDrawingSheet(DrawingSheetData sheet)
        {
            BeginObject();

            WriteString("sheetName", sheet.SheetName);
            WriteNumber("sheetWidth", sheet.SheetWidth);
            WriteNumber("sheetHeight", sheet.SheetHeight);
            WriteString("paperSize", sheet.PaperSize);
            WriteNumber("scale", sheet.Scale);

            // Sheet format geometry (title block, border, revision block)
            if (sheet.SheetFormat != null)
            {
                WriteName("sheetFormat");
                BeginObject();
                WriteDoubleArray("borderInset", sheet.SheetFormat.BorderInset);
                WriteDoubleArray("drawableArea", sheet.SheetFormat.DrawableArea);
                WriteDoubleArray("titleBlockBounds", sheet.SheetFormat.TitleBlockBounds);
                // RevisionBlockBounds is null when no revision table exists — write null instead of []
                if (sheet.SheetFormat.RevisionBlockBounds != null)
                    WriteDoubleArray("revisionBlockBounds", sheet.SheetFormat.RevisionBlockBounds, isLast: true);
                else
                {
                    WriteIndent();
                    _sb.Append("\"revisionBlockBounds\": null");
                    WriteLine();
                }
                EndObject();
                WriteLine();
            }

            WriteName("views");
            BeginArray();
            for (int i = 0; i < sheet.Views.Count; i++)
            {
                WriteDrawingView(sheet.Views[i]);
                if (i < sheet.Views.Count - 1)
                    _sb.Append(",");
                WriteLine();
            }
            EndArray(isLast: true);
            WriteLine();

            EndObject(isLast: true);
        }

        private void WriteDrawingView(DrawingViewData view)
        {
            BeginObject();

            WriteString("viewName", view.ViewName);
            WriteString("viewType", view.ViewType);
            if (view.ViewOrientation != null)
                WriteString("viewOrientation", view.ViewOrientation);
            WriteDoubleArray("viewOutline", view.ViewOutline);
            WriteDoubleArray("viewPosition", view.ViewPosition);
            WriteNumber("viewScale", view.ViewScale);
            WriteString("referencedConfiguration", view.ReferencedConfiguration);

            WriteName("annotations");
            BeginArray();
            for (int i = 0; i < view.Annotations.Count; i++)
            {
                WriteDrawingAnnotation(view.Annotations[i]);
                if (i < view.Annotations.Count - 1)
                    _sb.Append(",");
                WriteLine();
            }
            bool hasPrimitives = view.Primitives != null && view.Primitives.Count > 0;
            EndArray(isLast: !hasPrimitives);
            WriteLine();

            if (hasPrimitives)
            {
                WriteName("primitives");
                BeginArray();
                for (int i = 0; i < view.Primitives.Count; i++)
                {
                    WriteDrawingPrimitive(view.Primitives[i]);
                    if (i < view.Primitives.Count - 1)
                        _sb.Append(",");
                    WriteLine();
                }
                EndArray(isLast: true);
                WriteLine();
            }

            EndObject(isLast: true);
        }

        private void WriteDrawingPrimitive(DrawingPrimitiveData primitive)
        {
            BeginObject();
            WriteString("primitiveType", primitive.PrimitiveType);
            WriteString("sourceKind", primitive.SourceKind);
            WriteString("geometrySource", primitive.GeometrySource);
            WriteDoubleArray("boundsView", primitive.BoundsView);
            WriteDoubleArray("boundsSheet", primitive.BoundsSheet);
            WriteDoubleArray("centerView", primitive.CenterView);
            WriteDoubleArray("centerSheet", primitive.CenterSheet);
            WriteNullableNumber("radiusView", primitive.RadiusView);
            WriteNullableNumber("radiusSheet", primitive.RadiusSheet);
            WriteNullableNumber("rotationDir", primitive.RotationDir);

            WriteName("pointsView");
            BeginArray();
            for (int i = 0; i < primitive.PointsView.Count; i++)
            {
                WriteIndent();
                WriteInlineDoubleArray(primitive.PointsView[i]);
                if (i < primitive.PointsView.Count - 1)
                    _sb.Append(",");
                WriteLine();
            }
            EndArray();
            WriteLine();

            WriteName("pointsSheet");
            BeginArray();
            for (int i = 0; i < primitive.PointsSheet.Count; i++)
            {
                WriteIndent();
                WriteInlineDoubleArray(primitive.PointsSheet[i]);
                if (i < primitive.PointsSheet.Count - 1)
                    _sb.Append(",");
                WriteLine();
            }
            EndArray(isLast: true);
            WriteLine();

            EndObject(isLast: true);
        }

        /// <summary>
        /// Write a FLAT annotation object. All matchable keys are at the top level
        /// to match the drawing_map.py consumer contract.
        /// Keys: annotationType, annotationName, positionSheet, boundsSheet, anchorKind,
        ///       geometrySource, leaders, isDangling, visible,
        ///       featureName, dimensionText, noteText, gtolText, matchKeys, textRuns,
        ///       dimensionValue, dimensionType, tolerancePlus, toleranceMinus, toleranceType,
        ///       isReference, isDriven
        /// </summary>
        private void WriteDrawingAnnotation(DrawingAnnotationData ann)
        {
            BeginObject();

            WriteString("annotationType", ann.AnnotationType);
            WriteString("annotationName", ann.AnnotationName);
            WriteDoubleArray("positionSheet", ann.PositionSheet);
            WriteDoubleArray("boundsSheet", ann.BoundsSheet);
            WriteString("anchorKind", ann.AnchorKind);
            WriteString("geometrySource", ann.GeometrySource);

            // Leaders: array of [x, y, z] triplets
            WriteName("leaders");
            BeginArray();
            for (int i = 0; i < ann.Leaders.Count; i++)
            {
                WriteIndent();
                WriteInlineDoubleArray(ann.Leaders[i]);
                if (i < ann.Leaders.Count - 1)
                    _sb.Append(",");
                WriteLine();
            }
            EndArray();
            WriteLine();

            WriteBool("isDangling", ann.IsDangling);
            WriteBool("visible", ann.Visible);

            // Flat matchable text keys
            bool isDim = ann.AnnotationType == "displayDimension";
            WriteString("featureName", ann.FeatureName);
            WriteString("dimensionText", ann.DimensionText);
            WriteString("noteText", ann.NoteText);
            WriteStringArray("matchKeys", ann.MatchKeys);

            // Text geometry
            if (ann.TextExtent != null && ann.TextExtent.Length == 2)
            {
                WriteDoubleArray("textExtent", new double[] { Math.Round(ann.TextExtent[0], 10), Math.Round(ann.TextExtent[1], 10) });
            }
            WriteName("textRuns");
            BeginArray();
            for (int i = 0; i < ann.TextRuns.Count; i++)
            {
                WriteDrawingTextRun(ann.TextRuns[i]);
                if (i < ann.TextRuns.Count - 1)
                    _sb.Append(",");
                WriteLine();
            }
            EndArray();
            WriteLine();

            if (isDim)
            {
                WriteString("gtolText", ann.GtolText);
                WriteNullableNumber("dimensionValue", ann.DimensionValue);
                WriteString("dimensionType", ann.DimensionType);
                WriteNullableNumber("tolerancePlus", ann.TolerancePlus);
                WriteNullableNumber("toleranceMinus", ann.ToleranceMinus);
                WriteString("toleranceType", ann.ToleranceType);
                WriteBool("isReference", ann.IsReference);
                WriteBool("isDriven", ann.IsDriven, isLast: true);
            }
            else
            {
                WriteString("gtolText", ann.GtolText, isLast: true);
            }

            EndObject(isLast: true);
        }

        private void WriteDrawingTextRun(DrawingTextRunData run)
        {
            BeginObject();
            WriteString("text", run.Text);
            WriteDoubleArray("positionSheet", run.PositionSheet);
            WriteNullableNumber("height", run.Height);
            WriteNullableNumber("width", run.Width);
            if (run.RefPosition.HasValue)
                WriteInt("refPosition", run.RefPosition.Value);
            else
                WriteNullableNumber("refPosition", null);
            WriteNullableNumber("angle", run.Angle);
            WriteString("positionKind", run.PositionKind, isLast: true);
            EndObject(isLast: true);
        }

        /// <summary>
        /// Write a nullable double value — writes "null" if value is null
        /// </summary>
        private void WriteNullableNumber(string name, double? value, bool isLast = false)
        {
            WriteIndent();
            _sb.Append($"\"{name}\": ");
            if (value.HasValue)
                _sb.Append($"{value.Value:G10}");
            else
                _sb.Append("null");
            if (!isLast)
                _sb.Append(",");
            WriteLine();
        }

        private void WriteNullableNumber(string name, int? value, bool isLast = false)
        {
            WriteIndent();
            _sb.Append($"\"{name}\": ");
            if (value.HasValue)
                _sb.Append(value.Value);
            else
                _sb.Append("null");
            if (!isLast)
                _sb.Append(",");
            WriteLine();
        }

        /// <summary>
        /// Write a double array inline (no name, just [1.0, 2.0, 3.0])
        /// Used for leader point arrays within the leaders array
        /// </summary>
        private void WriteInlineDoubleArray(double[] arr)
        {
            if (arr == null || arr.Length == 0)
            {
                _sb.Append("[]");
                return;
            }
            _sb.Append("[");
            for (int i = 0; i < arr.Length; i++)
            {
                _sb.Append($"{arr[i]:G10}");
                if (i < arr.Length - 1)
                    _sb.Append(", ");
            }
            _sb.Append("]");
        }

        #endregion

        #region Primitive Writers

        private void BeginObject()
        {
            _sb.Append("{");
            _indentLevel++;
            WriteLine();
        }

        private void EndObject(bool isLast = false)
        {
            _indentLevel--;
            WriteIndent();
            _sb.Append("}");
            if (!isLast)
                _sb.Append(",");
        }

        private void BeginArray()
        {
            _sb.Append("[");
            _indentLevel++;
            WriteLine();
        }

        private void EndArray(bool isLast = false)
        {
            _indentLevel--;
            WriteIndent();
            _sb.Append("]");
            if (!isLast)
                _sb.Append(",");
        }

        private void WriteName(string name)
        {
            WriteIndent();
            _sb.Append($"\"{name}\": ");
        }

        private void WriteString(string name, string value, bool isLast = false)
        {
            WriteIndent();
            _sb.Append($"\"{name}\": ");
            if (value == null)
                _sb.Append("null");
            else
                _sb.Append($"\"{EscapeString(value)}\"");
            if (!isLast)
                _sb.Append(",");
            WriteLine();
        }

        private void WriteNumber(string name, double value, bool isLast = false)
        {
            WriteIndent();
            _sb.Append($"\"{name}\": {value:G10}");
            if (!isLast)
                _sb.Append(",");
            WriteLine();
        }

        private void WriteInt(string name, int value, bool isLast = false)
        {
            WriteIndent();
            _sb.Append($"\"{name}\": {value}");
            if (!isLast)
                _sb.Append(",");
            WriteLine();
        }

        private void WriteBool(string name, bool value, bool isLast = false)
        {
            WriteIndent();
            _sb.Append($"\"{name}\": {(value ? "true" : "false")}");
            if (!isLast)
                _sb.Append(",");
            WriteLine();
        }

        private void WriteDoubleArray(string name, double[] arr, bool isLast = false)
        {
            WriteIndent();
            _sb.Append($"\"{name}\": ");
            if (arr == null || arr.Length == 0)
            {
                _sb.Append("[]");
            }
            else
            {
                _sb.Append("[");
                for (int i = 0; i < arr.Length; i++)
                {
                    _sb.Append($"{arr[i]:G10}");
                    if (i < arr.Length - 1)
                        _sb.Append(", ");
                }
                _sb.Append("]");
            }
            if (!isLast)
                _sb.Append(",");
            WriteLine();
        }

        private void WriteStringArray(string name, List<string> arr, bool isLast = false)
        {
            WriteIndent();
            _sb.Append($"\"{name}\": ");
            if (arr == null || arr.Count == 0)
            {
                _sb.Append("[]");
            }
            else
            {
                _sb.Append("[");
                for (int i = 0; i < arr.Count; i++)
                {
                    _sb.Append($"\"{EscapeString(arr[i])}\"");
                    if (i < arr.Count - 1)
                        _sb.Append(", ");
                }
                _sb.Append("]");
            }
            if (!isLast)
                _sb.Append(",");
            WriteLine();
        }

        private void WriteDictionary(Dictionary<string, string> dict, bool isLast = false)
        {
            BeginObject();
            int count = 0;
            int total = dict.Count;
            foreach (var kvp in dict)
            {
                count++;
                WriteString(kvp.Key, kvp.Value, count == total);
            }
            EndObject(isLast);
            WriteLine();
        }

        private void WriteDictionary(Dictionary<string, int> dict, bool isLast = false)
        {
            BeginObject();
            int count = 0;
            int total = dict.Count;
            foreach (var kvp in dict)
            {
                count++;
                WriteInt(kvp.Key, kvp.Value, count == total);
            }
            EndObject(isLast);
            WriteLine();
        }

        private void WriteArray<T>(List<T> items, Action<T> writeItem, bool isLast = false)
        {
            BeginArray();
            for (int i = 0; i < items.Count; i++)
            {
                WriteIndent();
                writeItem(items[i]);
                if (i < items.Count - 1)
                    _sb.Append(",");
                WriteLine();
            }
            EndArray(isLast);
            WriteLine();
        }

        private void WriteIndent()
        {
            if (_indented)
            {
                for (int i = 0; i < _indentLevel; i++)
                    _sb.Append("  ");
            }
        }

        private void WriteLine()
        {
            if (_indented)
                _sb.AppendLine();
        }

        private string EscapeString(string s)
        {
            if (s == null) return "";
            return s.Replace("\\", "\\\\")
                   .Replace("\"", "\\\"")
                   .Replace("\n", "\\n")
                   .Replace("\r", "\\r")
                   .Replace("\t", "\\t");
        }

        #endregion

        #region Standard Size Helpers

        /// <summary>
        /// Get nearest standard inch fractional size
        /// </summary>
        private (double size, string formatted) GetNearestStandardInchSize(double inches)
        {
            // Common fractional drill sizes in inches
            var stdSizes = new (double size, string name)[]
            {
                (1.0/64, "1/64\""), (1.0/32, "1/32\""), (3.0/64, "3/64\""), (1.0/16, "1/16\""),
                (5.0/64, "5/64\""), (3.0/32, "3/32\""), (7.0/64, "7/64\""), (1.0/8, "1/8\""),
                (9.0/64, "9/64\""), (5.0/32, "5/32\""), (11.0/64, "11/64\""), (3.0/16, "3/16\""),
                (13.0/64, "13/64\""), (7.0/32, "7/32\""), (15.0/64, "15/64\""), (1.0/4, "1/4\""),
                (17.0/64, "17/64\""), (9.0/32, "9/32\""), (19.0/64, "19/64\""), (5.0/16, "5/16\""),
                (21.0/64, "21/64\""), (11.0/32, "11/32\""), (23.0/64, "23/64\""), (3.0/8, "3/8\""),
                (25.0/64, "25/64\""), (13.0/32, "13/32\""), (27.0/64, "27/64\""), (7.0/16, "7/16\""),
                (29.0/64, "29/64\""), (15.0/32, "15/32\""), (31.0/64, "31/64\""), (1.0/2, "1/2\""),
                (33.0/64, "33/64\""), (17.0/32, "17/32\""), (35.0/64, "35/64\""), (9.0/16, "9/16\""),
                (37.0/64, "37/64\""), (19.0/32, "19/32\""), (39.0/64, "39/64\""), (5.0/8, "5/8\""),
                (41.0/64, "41/64\""), (21.0/32, "21/32\""), (43.0/64, "43/64\""), (11.0/16, "11/16\""),
                (45.0/64, "45/64\""), (23.0/32, "23/32\""), (47.0/64, "47/64\""), (3.0/4, "3/4\""),
                (49.0/64, "49/64\""), (25.0/32, "25/32\""), (51.0/64, "51/64\""), (13.0/16, "13/16\""),
                (53.0/64, "53/64\""), (27.0/32, "27/32\""), (55.0/64, "55/64\""), (7.0/8, "7/8\""),
                (57.0/64, "57/64\""), (29.0/32, "29/32\""), (59.0/64, "59/64\""), (15.0/16, "15/16\""),
                (61.0/64, "61/64\""), (31.0/32, "31/32\""), (63.0/64, "63/64\""), (1.0, "1\"")
            };

            double minDiff = double.MaxValue;
            var closest = stdSizes[0];

            foreach (var std in stdSizes)
            {
                double diff = Math.Abs(std.size - inches);
                if (diff < minDiff)
                {
                    minDiff = diff;
                    closest = std;
                }
            }

            return (closest.size, closest.name);
        }

        /// <summary>
        /// Get nearest standard metric size
        /// </summary>
        private (double size, string formatted) GetNearestStandardMmSize(double mm)
        {
            // Common metric drill sizes
            var stdSizes = new double[]
            {
                1.0, 1.5, 2.0, 2.5, 3.0, 3.2, 3.5, 4.0, 4.2, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5,
                8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0,
                18.0, 19.0, 20.0, 21.0, 22.0, 23.0, 24.0, 25.0
            };

            double minDiff = double.MaxValue;
            double closest = stdSizes[0];

            foreach (var std in stdSizes)
            {
                double diff = Math.Abs(std - mm);
                if (diff < minDiff)
                {
                    minDiff = diff;
                    closest = std;
                }
            }

            return (closest, $"ø{closest:F1}mm");
        }

        /// <summary>
        /// Build preferred callout string for drawing matching
        /// </summary>
        private string BuildPreferredCallout(HoleGroup group, string stdInch, string stdMm)
        {
            var parts = new List<string>();

            // Thread takes precedence
            if (group.Thread != null && !string.IsNullOrEmpty(group.Thread.Callout))
            {
                parts.Add(group.Thread.Callout);
            }
            else
            {
                // Use nearest standard inch size for IPS docs, mm for metric
                // Default to inch since that's common in manufacturing
                parts.Add($"ø{stdInch.Replace("\"", "")}");
            }

            // Through or depth
            if (group.HoleType == "Through")
            {
                parts.Add("THRU");
            }
            else if (group.Depth != null && group.Depth.Millimeters > 0)
            {
                double depthIn = group.Depth.SystemValue * 39.3701;
                parts.Add($"x {depthIn:F3}\" DEEP");
            }

            // Counterbore
            if (group.Counterbore != null)
            {
                parts.Add(group.Counterbore.Callout);
            }

            // Countersink
            if (group.Countersink != null)
            {
                parts.Add(group.Countersink.Callout);
            }

            // Count
            if (group.Count > 1)
            {
                parts.Add($"({group.Count}X)");
            }

            return string.Join(" ", parts);
        }

        #endregion

        #region Batch Index Serialization

        private void WriteBatchIndex(BatchIndex index)
        {
            BeginObject();

            WriteString("schemaVersion", index.SchemaVersion);
            WriteString("extractorVersion", index.ExtractorVersion);
            WriteString("batchStartTime", index.BatchStartTime.ToString("O"));
            WriteString("batchEndTime", index.BatchEndTime.ToString("O"));
            WriteString("sourceFolder", index.SourceFolder);
            WriteString("outputFolder", index.OutputFolder);

            // Summary counts
            WriteName("summary");
            BeginObject();
            WriteInt("totalFilesFound", index.TotalFilesFound);
            WriteInt("successCount", index.SuccessCount);
            WriteInt("failureCount", index.FailureCount);
            WriteInt("skippedCount", index.SkippedCount);
            WriteString("duration", (index.BatchEndTime - index.BatchStartTime).ToString(@"hh\:mm\:ss"), isLast: true);
            EndObject();
            WriteLine();

            // Records array
            WriteName("records");
            BeginArray();
            for (int i = 0; i < index.Records.Count; i++)
            {
                WriteIndent();
                WriteIndexRecord(index.Records[i]);
                if (i < index.Records.Count - 1)
                    _sb.Append(",");
                WriteLine();
            }
            EndArray();
            WriteLine();

            // Failures array
            WriteName("failures");
            BeginArray();
            for (int i = 0; i < index.Failures.Count; i++)
            {
                WriteIndent();
                WriteFailureRecord(index.Failures[i]);
                if (i < index.Failures.Count - 1)
                    _sb.Append(",");
                WriteLine();
            }
            EndArray(isLast: true);
            WriteLine();

            EndObject(isLast: true);
        }

        private void WriteIndexRecord(IndexRecord record)
        {
            BeginObject();
            WriteString("sourceFilePath", record.SourceFilePath);
            WriteString("sourceFileName", record.SourceFileName);
            WriteString("partNumber", record.PartNumber);
            WriteString("description", record.Description);
            WriteString("material", record.Material);
            WriteString("extractionTime", record.ExtractionTime.ToString("O"));
            WriteString("jsonFilePath", record.JsonFilePath);
            WriteString("jsonFileName", record.JsonFileName);
            WriteString("extractorVersion", record.ExtractorVersion);
            WriteString("schemaVersion", record.SchemaVersion);
            WriteInt("holeCount", record.HoleCount);
            WriteInt("featureCount", record.FeatureCount);
            WriteNumber("jsonFileSizeBytes", record.JsonFileSize, isLast: true);
            EndObject(isLast: true);
        }

        private void WriteFailureRecord(FailureRecord failure)
        {
            BeginObject();
            WriteString("sourceFilePath", failure.SourceFilePath);
            WriteString("sourceFileName", failure.SourceFileName);
            WriteString("failureTime", failure.FailureTime.ToString("O"));
            if (failure.SwErrorCode.HasValue)
                WriteInt("swErrorCode", failure.SwErrorCode.Value);
            WriteString("errorMessage", failure.ErrorMessage);
            WriteString("failureStage", failure.FailureStage, isLast: true);
            EndObject(isLast: true);
        }

        #endregion
    }
}
