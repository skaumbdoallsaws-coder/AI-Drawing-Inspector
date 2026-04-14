using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorksExtractor.Models;

namespace SolidWorksExtractor.Services
{
    /// <summary>
    /// Extracts assembly data: components, hierarchy, mates, transforms
    /// </summary>
    public class AssemblyExtractor
    {
        private readonly PropertyExtractor _propertyExtractor;
        private readonly FeatureExtractor _featureExtractor;
        private readonly GeometryAnalyzer _geometryAnalyzer;
        private readonly HashSet<string> _processedParts;

        public AssemblyExtractor()
        {
            _propertyExtractor = new PropertyExtractor();
            _featureExtractor = new FeatureExtractor();
            _geometryAnalyzer = new GeometryAnalyzer();
            _processedParts = new HashSet<string>();
        }

        /// <summary>
        /// Extract complete assembly data
        /// </summary>
        public AssemblyData ExtractAssembly(IModelDoc2 doc, bool extractPartData = true)
        {
            var assembly = new AssemblyData
            {
                FileName = System.IO.Path.GetFileName(doc.GetPathName()),
                FilePath = doc.GetPathName(),
                ExtractionTime = DateTime.Now
            };

            _processedParts.Clear();

            IAssemblyDoc assyDoc = doc as IAssemblyDoc;
            if (assyDoc == null)
            {
                Console.WriteLine("Document is not an assembly");
                return assembly;
            }

            try
            {
                // Extract assembly identity
                assembly.Identity = ExtractAssemblyIdentity(doc);

                // Extract component hierarchy
                Console.WriteLine("Extracting component hierarchy...");
                assembly.RootComponent = ExtractComponentHierarchy(assyDoc, extractPartData, assembly);

                // Flatten component list
                FlattenComponents(assembly.RootComponent, assembly.Components);

                // Extract mates
                Console.WriteLine("Extracting mates...");
                assembly.Mates = ExtractMates(doc, assyDoc);

                // Build mate relationships
                assembly.MateRelationships = BuildMateRelationships(assembly.Mates);

                // Extract exploded view steps
                Console.WriteLine("Extracting exploded views...");
                assembly.ExplodeSteps = ExtractExplodeSteps(doc, assyDoc);

                // Extract assembly-level features (machining operations on the assembly itself)
                Console.WriteLine("Extracting assembly-level features...");
                assembly.AssemblyFeatures = _featureExtractor.ExtractFeatures(doc);

                // Calculate statistics
                assembly.Statistics = CalculateStatistics(assembly);

                Console.WriteLine($"Extracted: {assembly.Statistics.TotalComponents} components, {assembly.Statistics.TotalMates} mates");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Error extracting assembly: {ex.Message}");
            }

            return assembly;
        }

        /// <summary>
        /// Extract assembly identity/metadata
        /// </summary>
        private AssemblyIdentity ExtractAssemblyIdentity(IModelDoc2 doc)
        {
            var identity = new AssemblyIdentity();

            ICustomPropertyManager propMgr = doc.Extension.CustomPropertyManager[""];

            identity.AssemblyNumber = GetProperty(propMgr, "PartNumber", "Number", "AssemblyNumber");
            identity.Description = GetProperty(propMgr, "Description", "Title");
            identity.Revision = GetProperty(propMgr, "Revision", "Rev");
            identity.Author = GetProperty(propMgr, "Author", "DrawnBy");
            identity.CustomProperties = GetAllProperties(propMgr);

            return identity;
        }

        /// <summary>
        /// Extract component hierarchy starting from root
        /// </summary>
        private ComponentData ExtractComponentHierarchy(IAssemblyDoc assyDoc, bool extractPartData, AssemblyData assembly)
        {
            // Get root component
            IConfiguration config = (IConfiguration)((IModelDoc2)assyDoc).GetActiveConfiguration();
            IComponent2 rootComp = (IComponent2)config.GetRootComponent3(true);

            return ExtractComponent(rootComp, null, 0, extractPartData, assembly);
        }

        /// <summary>
        /// Extract a single component and its children recursively
        /// </summary>
        private ComponentData ExtractComponent(IComponent2 comp, ComponentData parent, int level, bool extractPartData, AssemblyData assembly)
        {
            if (comp == null)
                return null;

            var compData = new ComponentData
            {
                Name = comp.Name2,
                Name2 = comp.Name2,
                Level = level,
                ParentName = parent?.Name
            };

            try
            {
                // Get referenced file info
                compData.ReferencedFilePath = comp.GetPathName();
                compData.ReferencedFileName = System.IO.Path.GetFileName(compData.ReferencedFilePath);

                // Determine type
                IModelDoc2 refDoc = (IModelDoc2)comp.GetModelDoc2();
                if (refDoc != null)
                {
                    int docType = refDoc.GetType();
                    compData.Type = docType == (int)swDocumentTypes_e.swDocASSEMBLY
                        ? ComponentType.Assembly
                        : ComponentType.Part;
                }

                // State
                int suppState = comp.GetSuppression2();
                compData.State = GetComponentState(suppState);
                compData.IsSuppressed = suppState == (int)swComponentSuppressionState_e.swComponentSuppressed;
                compData.IsLightweight = suppState == (int)swComponentSuppressionState_e.swComponentLightweight;
                compData.IsHidden = comp.Visible == 0;
                compData.IsFixed = comp.IsFixed();

                // Virtual component check
                compData.IsVirtual = comp.IsVirtual;
                if (compData.IsVirtual)
                    compData.Type = ComponentType.Virtual;

                // Configuration
                compData.ActiveConfiguration = comp.ReferencedConfiguration;

                // Transform
                compData.Transform = ExtractTransform(comp);

                // Custom properties from component
                compData.Properties = GetComponentProperties(comp);

                // Extract part data if requested and not already processed
                if (extractPartData && compData.Type == ComponentType.Part && !compData.IsSuppressed)
                {
                    string partKey = compData.ReferencedFileName.ToLower();
                    if (!_processedParts.Contains(partKey) && refDoc != null)
                    {
                        _processedParts.Add(partKey);
                        compData.PartDataKey = partKey;

                        // Extract part data
                        var partData = ExtractPartFromComponent(refDoc, comp);
                        if (partData != null)
                        {
                            assembly.PartDataCache[partKey] = partData;
                        }
                    }
                    else
                    {
                        compData.PartDataKey = partKey;
                    }
                }

                // Count instances
                compData.InstanceNumber = GetInstanceNumber(comp.Name2);

                // Get children
                object[] children = (object[])comp.GetChildren();
                if (children != null)
                {
                    foreach (object childObj in children)
                    {
                        IComponent2 childComp = (IComponent2)childObj;
                        var childData = ExtractComponent(childComp, compData, level + 1, extractPartData, assembly);
                        if (childData != null)
                        {
                            compData.Children.Add(childData);
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: Error extracting component '{comp.Name2}': {ex.Message}");
            }

            return compData;
        }

        /// <summary>
        /// Extract part data from a component's referenced document
        /// </summary>
        private PartData ExtractPartFromComponent(IModelDoc2 refDoc, IComponent2 comp)
        {
            try
            {
                var partData = new PartData
                {
                    FileName = System.IO.Path.GetFileName(refDoc.GetPathName()),
                    FilePath = refDoc.GetPathName(),
                    ExtractionTime = DateTime.Now
                };

                partData.Identity = _propertyExtractor.ExtractIdentity(refDoc);
                partData.Physical = _propertyExtractor.ExtractPhysicalProperties(refDoc);

                // Only extract features if component is resolved
                int suppState = comp.GetSuppression2();
                if (suppState == (int)swComponentSuppressionState_e.swComponentFullyResolved)
                {
                    partData.Features = _featureExtractor.ExtractFeatures(refDoc);
                    partData.Geometry = _geometryAnalyzer.AnalyzeGeometry(refDoc);

                    // Set assembly context in reference frame
                    if (partData.Geometry != null && partData.Geometry.ReferenceFrame != null)
                    {
                        partData.Geometry.ReferenceFrame.AssemblyContext = CreateAssemblyContext(comp);
                    }
                }

                partData.Configurations = _propertyExtractor.ExtractConfigurations(refDoc);

                return partData;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: Could not extract part data: {ex.Message}");
                return null;
            }
        }

        /// <summary>
        /// Create assembly context for a component (transform from part to assembly)
        /// </summary>
        private AssemblyTransform CreateAssemblyContext(IComponent2 comp)
        {
            var context = new AssemblyTransform
            {
                ComponentPath = comp.Name2,
                InstanceNumber = GetInstanceNumber(comp.Name2)
            };

            try
            {
                // Get parent assembly name
                IComponent2 parent = (IComponent2)comp.GetParent();
                if (parent != null)
                {
                    context.AssemblyName = System.IO.Path.GetFileName(parent.GetPathName());
                }

                // Get transform
                IMathTransform mathTransform = comp.Transform2;
                if (mathTransform != null)
                {
                    double[] matrix = (double[])mathTransform.ArrayData;
                    if (matrix != null && matrix.Length >= 13)
                    {
                        // Store full matrix (column-major for OpenGL compatibility)
                        context.PartToAssemblyMatrix = new double[]
                        {
                            matrix[0], matrix[3], matrix[6], 0,  // Column 1
                            matrix[1], matrix[4], matrix[7], 0,  // Column 2
                            matrix[2], matrix[5], matrix[8], 0,  // Column 3
                            matrix[9], matrix[10], matrix[11], 1 // Column 4
                        };

                        context.Translation = new double[] { matrix[9], matrix[10], matrix[11] };
                        context.Scale = matrix.Length > 12 ? matrix[12] : 1.0;

                        // Calculate Euler angles
                        double[,] R = new double[3, 3]
                        {
                            { matrix[0], matrix[1], matrix[2] },
                            { matrix[3], matrix[4], matrix[5] },
                            { matrix[6], matrix[7], matrix[8] }
                        };
                        context.RotationEuler = RotationMatrixToEulerAngles(R);
                        context.RotationQuaternion = RotationMatrixToQuaternion(R);
                    }
                }
            }
            catch { }

            return context;
        }

        /// <summary>
        /// Extract transform matrix from component with Euler angles and quaternion
        /// </summary>
        private TransformMatrix ExtractTransform(IComponent2 comp)
        {
            var transform = new TransformMatrix();

            try
            {
                IMathTransform mathTransform = comp.Transform2;
                if (mathTransform != null)
                {
                    double[] matrix = (double[])mathTransform.ArrayData;
                    transform.RawMatrix = matrix;

                    if (matrix != null && matrix.Length >= 13)
                    {
                        // SolidWorks returns: [R00 R01 R02 R10 R11 R12 R20 R21 R22 Tx Ty Tz Scale ...]
                        // Rotation matrix (3x3)
                        transform.Rotation = new double[3, 3]
                        {
                            { matrix[0], matrix[1], matrix[2] },
                            { matrix[3], matrix[4], matrix[5] },
                            { matrix[6], matrix[7], matrix[8] }
                        };

                        // Translation (in meters)
                        transform.Translation = new double[] { matrix[9], matrix[10], matrix[11] };

                        // Scale
                        transform.Scale = matrix.Length > 12 ? matrix[12] : 1.0;

                        // Calculate Euler angles (ZYX convention, in degrees)
                        transform.EulerAngles = RotationMatrixToEulerAngles(transform.Rotation);

                        // Calculate Quaternion (W, X, Y, Z)
                        transform.Quaternion = RotationMatrixToQuaternion(transform.Rotation);
                    }
                }
            }
            catch { }

            return transform;
        }

        /// <summary>
        /// Convert rotation matrix to Euler angles (ZYX convention)
        /// Returns [Roll, Pitch, Yaw] in degrees
        /// </summary>
        private double[] RotationMatrixToEulerAngles(double[,] R)
        {
            double sy = Math.Sqrt(R[0, 0] * R[0, 0] + R[1, 0] * R[1, 0]);

            bool singular = sy < 1e-6;

            double x, y, z;
            if (!singular)
            {
                x = Math.Atan2(R[2, 1], R[2, 2]);
                y = Math.Atan2(-R[2, 0], sy);
                z = Math.Atan2(R[1, 0], R[0, 0]);
            }
            else
            {
                x = Math.Atan2(-R[1, 2], R[1, 1]);
                y = Math.Atan2(-R[2, 0], sy);
                z = 0;
            }

            // Convert to degrees
            return new double[]
            {
                x * (180.0 / Math.PI),
                y * (180.0 / Math.PI),
                z * (180.0 / Math.PI)
            };
        }

        /// <summary>
        /// Convert rotation matrix to quaternion (W, X, Y, Z)
        /// </summary>
        private double[] RotationMatrixToQuaternion(double[,] R)
        {
            double trace = R[0, 0] + R[1, 1] + R[2, 2];
            double w, x, y, z;

            if (trace > 0)
            {
                double s = 0.5 / Math.Sqrt(trace + 1.0);
                w = 0.25 / s;
                x = (R[2, 1] - R[1, 2]) * s;
                y = (R[0, 2] - R[2, 0]) * s;
                z = (R[1, 0] - R[0, 1]) * s;
            }
            else if (R[0, 0] > R[1, 1] && R[0, 0] > R[2, 2])
            {
                double s = 2.0 * Math.Sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]);
                w = (R[2, 1] - R[1, 2]) / s;
                x = 0.25 * s;
                y = (R[0, 1] + R[1, 0]) / s;
                z = (R[0, 2] + R[2, 0]) / s;
            }
            else if (R[1, 1] > R[2, 2])
            {
                double s = 2.0 * Math.Sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]);
                w = (R[0, 2] - R[2, 0]) / s;
                x = (R[0, 1] + R[1, 0]) / s;
                y = 0.25 * s;
                z = (R[1, 2] + R[2, 1]) / s;
            }
            else
            {
                double s = 2.0 * Math.Sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]);
                w = (R[1, 0] - R[0, 1]) / s;
                x = (R[0, 2] + R[2, 0]) / s;
                y = (R[1, 2] + R[2, 1]) / s;
                z = 0.25 * s;
            }

            return new double[] { w, x, y, z };
        }

        /// <summary>
        /// Extract all mates from assembly
        /// </summary>
        private List<MateData> ExtractMates(IModelDoc2 doc, IAssemblyDoc assyDoc)
        {
            var mates = new List<MateData>();

            try
            {
                // Traverse features looking for MateGroup
                IFeature feat = (IFeature)doc.FirstFeature();

                while (feat != null)
                {
                    if (feat.GetTypeName2() == "MateGroup")
                    {
                        // Get mate sub-features
                        IFeature mateFeat = (IFeature)feat.GetFirstSubFeature();

                        while (mateFeat != null)
                        {
                            var mateData = ExtractMate(mateFeat);
                            if (mateData != null)
                            {
                                mates.Add(mateData);
                            }

                            mateFeat = (IFeature)mateFeat.GetNextSubFeature();
                        }
                    }

                    feat = (IFeature)feat.GetNextFeature();
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Error extracting mates: {ex.Message}");
            }

            return mates;
        }

        /// <summary>
        /// Extract a single mate
        /// </summary>
        private MateData ExtractMate(IFeature mateFeat)
        {
            try
            {
                IMate2 mate = (IMate2)mateFeat.GetSpecificFeature2();
                if (mate == null)
                    return null;

                // Check suppression state
                bool isSuppressed = false;
                try
                {
                    object suppResult = mateFeat.IsSuppressed2((int)swInConfigurationOpts_e.swThisConfiguration, null);
                    if (suppResult is bool[] suppArray && suppArray.Length > 0)
                        isSuppressed = suppArray[0];
                }
                catch { }

                var mateData = new MateData
                {
                    Name = mateFeat.Name,
                    Type = (MateType)mate.Type,
                    TypeName = GetMateTypeString(mate.Type),
                    IsSuppressed = isSuppressed
                };

                // Get mate entities
                int entityCount = mate.GetMateEntityCount();

                if (entityCount >= 1)
                {
                    mateData.Entity1 = ExtractMateEntity(mate, 0);
                }
                if (entityCount >= 2)
                {
                    mateData.Entity2 = ExtractMateEntity(mate, 1);
                }

                // Get mate parameters based on type
                switch (mate.Type)
                {
                    case (int)swMateType_e.swMateDISTANCE:
                        IDistanceMateFeatureData distData = (IDistanceMateFeatureData)mateFeat.GetDefinition();
                        if (distData != null)
                        {
                            mateData.Distance = DimensionValue.FromMeters(distData.Distance);
                            mateData.IsFlipped = distData.FlipDimension;
                        }
                        break;

                    case (int)swMateType_e.swMateANGLE:
                        IAngleMateFeatureData angleData = (IAngleMateFeatureData)mateFeat.GetDefinition();
                        if (angleData != null)
                        {
                            mateData.Angle = DimensionValue.FromRadians(angleData.Angle);
                        }
                        break;
                }

                // Alignment
                try
                {
                    int alignment = mate.Alignment;
                    mateData.Alignment = (MateAlignment)alignment;
                }
                catch { }

                return mateData;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: Could not extract mate '{mateFeat.Name}': {ex.Message}");
                return null;
            }
        }

        /// <summary>
        /// Extract mate entity info with quality indicators
        /// </summary>
        private Models.MateEntity ExtractMateEntity(IMate2 mate, int index)
        {
            var entity = new Models.MateEntity();
            var quality = new MateReferenceQuality
            {
                Level = "Low",
                IsNamed = false,
                HasGeometryInfo = false,
                ComponentResolved = false,
                IsStable = false,
                HasDimensions = false
            };

            try
            {
                IMateEntity2 mateEntity = (IMateEntity2)mate.MateEntity(index);
                if (mateEntity == null)
                {
                    entity.Quality = quality;
                    entity.QualityReason = "Could not access mate entity";
                    return entity;
                }

                // Get component
                IComponent2 comp = (IComponent2)mateEntity.ReferenceComponent;
                if (comp != null)
                {
                    entity.ComponentName = comp.Name2;
                    entity.ComponentFileName = System.IO.Path.GetFileName(comp.GetPathName());
                    entity.InstanceNumber = GetInstanceNumber(comp.Name2);

                    // Check if component is resolved
                    int suppState = comp.GetSuppression2();
                    quality.ComponentResolved = suppState == (int)swComponentSuppressionState_e.swComponentFullyResolved;
                }

                // Get entity type
                int entityType = mateEntity.ReferenceType2;
                entity.EntityTypeName = GetEntityTypeString(entityType);

                // Check if this is a named reference (plane, axis, point)
                bool isNamedRef = entityType == (int)swSelectType_e.swSelDATUMPLANES ||
                                  entityType == (int)swSelectType_e.swSelDATUMAXES ||
                                  entityType == (int)swSelectType_e.swSelDATUMPOINTS;

                if (isNamedRef)
                {
                    quality.IsNamed = true;
                    quality.IsStable = true;  // Named refs are stable

                    // Try to get the name
                    try
                    {
                        object refEntity = mateEntity.Reference;
                        if (refEntity is IFeature feat)
                        {
                            entity.EntityName = feat.Name;
                        }
                    }
                    catch { }
                }

                // Get geometry info if available
                try
                {
                    object refEntity = mateEntity.Reference;
                    if (refEntity is IFace2 face)
                    {
                        ISurface surface = (ISurface)face.GetSurface();
                        if (surface.IsPlane())
                        {
                            entity.GeometryType = "Planar";
                            quality.HasGeometryInfo = true;

                            double[] planeParams = (double[])surface.PlaneParams;
                            if (planeParams != null && planeParams.Length >= 6)
                            {
                                entity.Direction = Vector3D.FromArray(new double[] { planeParams[0], planeParams[1], planeParams[2] });
                                entity.Point = Point3D.FromArray(new double[] { planeParams[3], planeParams[4], planeParams[5] });
                            }
                        }
                        else if (surface.IsCylinder())
                        {
                            entity.GeometryType = "Cylindrical";
                            quality.HasGeometryInfo = true;

                            double[] cylParams = (double[])surface.CylinderParams;
                            if (cylParams != null && cylParams.Length >= 7)
                            {
                                entity.Point = Point3D.FromArray(new double[] { cylParams[0], cylParams[1], cylParams[2] });
                                entity.Direction = Vector3D.FromArray(new double[] { cylParams[3], cylParams[4], cylParams[5] });
                                entity.Radius = DimensionValue.FromMeters(cylParams[6]);
                                quality.HasDimensions = true;
                            }
                        }
                        else if (surface.IsCone())
                        {
                            entity.GeometryType = "Conical";
                            quality.HasGeometryInfo = true;
                        }
                        else if (surface.IsSphere())
                        {
                            entity.GeometryType = "Spherical";
                            quality.HasGeometryInfo = true;
                        }
                        else
                        {
                            entity.GeometryType = "Other";
                        }
                    }
                    else if (refEntity is IEdge edge)
                    {
                        ICurve curve = (ICurve)edge.GetCurve();
                        if (curve != null)
                        {
                            if (curve.IsLine())
                            {
                                entity.GeometryType = "Linear";
                                quality.HasGeometryInfo = true;
                            }
                            else if (curve.IsCircle())
                            {
                                entity.GeometryType = "Circular";
                                quality.HasGeometryInfo = true;
                            }
                        }
                    }
                    else if (refEntity is IVertex vertex)
                    {
                        entity.GeometryType = "Point";
                        quality.HasGeometryInfo = true;

                        double[] pt = (double[])vertex.GetPoint();
                        if (pt != null)
                        {
                            entity.Point = Point3D.FromArray(pt);
                        }
                    }
                }
                catch { }

                // Calculate overall quality level
                quality.Level = CalculateQualityLevel(quality, isNamedRef);
                entity.QualityReason = BuildQualityReason(quality, isNamedRef);
            }
            catch (Exception ex)
            {
                entity.QualityReason = $"Error: {ex.Message}";
            }

            entity.Quality = quality;
            return entity;
        }

        /// <summary>
        /// Calculate overall quality level based on indicators
        /// </summary>
        private string CalculateQualityLevel(MateReferenceQuality quality, bool isNamedRef)
        {
            int score = 0;

            if (quality.ComponentResolved) score += 2;
            if (isNamedRef) score += 3;
            if (quality.HasGeometryInfo) score += 2;
            if (quality.HasDimensions) score += 1;

            if (score >= 6) return "High";
            if (score >= 3) return "Medium";
            return "Low";
        }

        /// <summary>
        /// Build human-readable quality reason
        /// </summary>
        private string BuildQualityReason(MateReferenceQuality quality, bool isNamedRef)
        {
            var reasons = new List<string>();

            if (isNamedRef)
                reasons.Add("named reference (stable)");
            else
                reasons.Add("face/edge reference (may change)");

            if (quality.ComponentResolved)
                reasons.Add("component resolved");
            else
                reasons.Add("component not resolved");

            if (quality.HasGeometryInfo)
                reasons.Add("geometry extracted");
            else
                reasons.Add("no geometry info");

            return string.Join(", ", reasons);
        }

        /// <summary>
        /// Build mate relationships (component pairs)
        /// </summary>
        private List<MateRelationship> BuildMateRelationships(List<MateData> mates)
        {
            var relationships = new Dictionary<string, MateRelationship>();

            foreach (var mate in mates)
            {
                if (mate.Entity1 == null || mate.Entity2 == null)
                    continue;

                string comp1 = mate.Entity1.ComponentFileName ?? "";
                string comp2 = mate.Entity2.ComponentFileName ?? "";

                // Create ordered key for the pair
                string key = string.Compare(comp1, comp2) < 0
                    ? $"{comp1}|{comp2}"
                    : $"{comp2}|{comp1}";

                if (!relationships.ContainsKey(key))
                {
                    relationships[key] = new MateRelationship
                    {
                        Component1 = mate.Entity1.ComponentName,
                        Component1FileName = comp1,
                        Component2 = mate.Entity2.ComponentName,
                        Component2FileName = comp2
                    };
                }

                relationships[key].Mates.Add(mate);

                // Generate inspection requirement
                string requirement = GenerateInspectionRequirement(mate);
                if (!string.IsNullOrEmpty(requirement))
                {
                    relationships[key].InspectionRequirements.Add(requirement);
                }
            }

            return relationships.Values.ToList();
        }

        /// <summary>
        /// Generate inspection requirement from mate
        /// </summary>
        private string GenerateInspectionRequirement(MateData mate)
        {
            switch (mate.Type)
            {
                case MateType.Concentric:
                    if (mate.Entity1.GeometryType == "Cylindrical")
                        return "Verify hole alignment for concentric mate";
                    break;

                case MateType.Distance:
                    return $"Verify distance: {mate.Distance?.Millimeters:F2}mm";

                case MateType.Parallel:
                    return "Verify parallel surfaces";

                case MateType.Perpendicular:
                    return "Verify perpendicular surfaces";
            }

            return null;
        }

        /// <summary>
        /// Flatten component hierarchy to list
        /// </summary>
        private void FlattenComponents(ComponentData comp, List<ComponentData> list)
        {
            if (comp == null)
                return;

            list.Add(comp);

            foreach (var child in comp.Children)
            {
                FlattenComponents(child, list);
            }
        }

        /// <summary>
        /// Calculate assembly statistics
        /// </summary>
        private AssemblyStatistics CalculateStatistics(AssemblyData assembly)
        {
            var stats = new AssemblyStatistics
            {
                TotalComponents = assembly.Components.Count,
                TotalMates = assembly.Mates.Count
            };

            // Count by state
            stats.ResolvedCount = assembly.Components.Count(c => c.State == ComponentState.Resolved);
            stats.LightweightCount = assembly.Components.Count(c => c.State == ComponentState.Lightweight);
            stats.SuppressedCount = assembly.Components.Count(c => c.State == ComponentState.Suppressed);

            // Count unique parts
            var uniqueParts = assembly.Components
                .Where(c => c.Type == ComponentType.Part)
                .Select(c => c.ReferencedFileName?.ToLower())
                .Where(f => !string.IsNullOrEmpty(f))
                .Distinct();
            stats.UniquePartCount = uniqueParts.Count();

            // Count sub-assemblies
            stats.SubAssemblyCount = assembly.Components.Count(c => c.Type == ComponentType.Assembly) - 1;  // Exclude root

            // Mate type counts
            foreach (var mate in assembly.Mates)
            {
                string typeName = mate.TypeName;
                if (!stats.MateTypeCounts.ContainsKey(typeName))
                    stats.MateTypeCounts[typeName] = 0;
                stats.MateTypeCounts[typeName]++;
            }

            // Component counts by file
            foreach (var comp in assembly.Components.Where(c => c.Type == ComponentType.Part))
            {
                string fileName = comp.ReferencedFileName ?? "Unknown";
                if (!stats.ComponentCounts.ContainsKey(fileName))
                    stats.ComponentCounts[fileName] = 0;
                stats.ComponentCounts[fileName]++;
            }

            // Assembly-level feature count
            if (assembly.AssemblyFeatures != null)
            {
                stats.AssemblyFeatureCount =
                    assembly.AssemblyFeatures.HoleWizardHoles.Count +
                    assembly.AssemblyFeatures.Extrudes.Count +
                    assembly.AssemblyFeatures.Cuts.Count +
                    assembly.AssemblyFeatures.Fillets.Count +
                    assembly.AssemblyFeatures.Chamfers.Count +
                    assembly.AssemblyFeatures.Patterns.Count;
            }

            return stats;
        }

        /// <summary>
        /// Extract exploded view steps from the assembly
        /// </summary>
        private List<ExplodeStepData> ExtractExplodeSteps(IModelDoc2 doc, IAssemblyDoc assyDoc)
        {
            var steps = new List<ExplodeStepData>();

            try
            {
                // Get exploded view names for the active configuration
                object viewNamesObj = assyDoc.GetExplodedViewNames();
                if (viewNamesObj == null)
                {
                    Console.WriteLine("  No exploded views found");
                    return steps;
                }

                string[] viewNames = null;
                if (viewNamesObj is string[] stringNames)
                {
                    viewNames = stringNames;
                }
                else if (viewNamesObj is object[] objectNames)
                {
                    viewNames = objectNames
                        .OfType<string>()
                        .Where(name => !string.IsNullOrWhiteSpace(name))
                        .ToArray();
                }

                if (viewNames == null)
                {
                    Console.WriteLine("  Could not read exploded view names");
                    return steps;
                }

                if (viewNames.Length == 0)
                {
                    Console.WriteLine("  No exploded views found");
                    return steps;
                }

                Console.WriteLine($"  Found {viewNames.Length} exploded view(s): {string.Join(", ", viewNames)}");

                // Get the active configuration to access explode steps
                IConfiguration config = (IConfiguration)doc.GetActiveConfiguration();
                if (config == null)
                {
                    Console.WriteLine("  Could not get active configuration");
                    return steps;
                }

                foreach (string activeViewName in viewNames)
                {
                    if (string.IsNullOrWhiteSpace(activeViewName))
                        continue;

                    bool explodedShown = false;
                    try
                    {
                        assyDoc.ShowExploded2(true, activeViewName);
                        explodedShown = true;

                        int stepCount = config.GetNumberOfExplodeSteps();
                        Console.WriteLine($"  Exploded view '{activeViewName}' has {stepCount} steps");

                        for (int i = 0; i < stepCount; i++)
                        {
                            try
                            {
                                object stepObj = config.GetExplodeStep(i);
                                if (stepObj == null)
                                    continue;

                                IExplodeStep explodeStep = stepObj as IExplodeStep;
                                if (explodeStep == null)
                                    continue;

                                var stepData = new ExplodeStepData
                                {
                                    ExplodeViewName = activeViewName,
                                    StepIndex = i,
                                    Name = explodeStep.Name ?? $"Step{i + 1}",
                                    DistanceMeters = explodeStep.ExplodeDistance,
                                    ReverseDirection = explodeStep.ReverseTranslationDirection,
                                    RotationAngleRadians = explodeStep.RotationAngle,
                                    ReverseRotation = explodeStep.ReverseRotationDirection,
                                    Direction = ExtractExplodeDirection(explodeStep)
                                };

                                // Step type
                                int stepType = explodeStep.ExplodeStepType;
                                stepData.StepType = stepType == 0 ? "Translate" :
                                                   stepType == 1 ? "Radial" :
                                                   stepType == 2 ? "SubAssembly" : "Unknown";

                                int compCount = 0;
                                try
                                {
                                    compCount = explodeStep.GetNumOfComponents();
                                }
                                catch (Exception compCountEx)
                                {
                                    Console.WriteLine($"    Warning: could not read component count for step {i}: {compCountEx.Message}");
                                }

                                for (int j = 0; j < compCount; j++)
                                {
                                    try
                                    {
                                        string compName = null;
                                        try
                                        {
                                            compName = explodeStep.GetComponentName(j);
                                        }
                                        catch { }

                                        string compFileName = null;
                                        object compObj = null;
                                        try
                                        {
                                            compObj = explodeStep.GetComponent(j);
                                        }
                                        catch { }

                                        if (compObj is IComponent2 comp)
                                        {
                                            if (string.IsNullOrWhiteSpace(compName))
                                                compName = comp.Name2;

                                            string refModel = comp.GetPathName();
                                            if (!string.IsNullOrWhiteSpace(refModel))
                                                compFileName = System.IO.Path.GetFileName(refModel);
                                        }

                                        if (!string.IsNullOrWhiteSpace(compName))
                                            stepData.ComponentNames.Add(compName);

                                        if (!string.IsNullOrWhiteSpace(compFileName))
                                            stepData.ComponentFileNames.Add(compFileName);
                                    }
                                    catch (Exception compEx)
                                    {
                                        Console.WriteLine($"    Warning: could not get component {j} in step {i}: {compEx.Message}");
                                    }
                                }

                                steps.Add(stepData);
                                Console.WriteLine($"    Step {i}: {stepData.StepType}, {compCount} components, " +
                                                $"distance={stepData.DistanceMeters:F4}m, " +
                                                $"dir=[{stepData.Direction[0]:F2},{stepData.Direction[1]:F2},{stepData.Direction[2]:F2}]");
                            }
                            catch (Exception stepEx)
                            {
                                Console.WriteLine($"    Error extracting step {i}: {stepEx.Message}");
                            }
                        }
                    }
                    catch (Exception viewEx)
                    {
                        Console.WriteLine($"  Error extracting exploded view '{activeViewName}': {viewEx.Message}");
                    }
                    finally
                    {
                        if (explodedShown)
                        {
                            try
                            {
                                assyDoc.ShowExploded2(false, activeViewName);
                            }
                            catch (Exception collapseEx)
                            {
                                Console.WriteLine($"  Warning: could not collapse exploded view '{activeViewName}': {collapseEx.Message}");
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"  Error extracting exploded views: {ex.Message}");
            }

            return steps;
        }

        private double[] ExtractExplodeDirection(IExplodeStep explodeStep)
        {
            var direction = new double[] { 0.0, 0.0, 0.0 };

            try
            {
                int dirIndex = -1;
                explodeStep.GetExplodeDirection(out dirIndex);

                if (dirIndex >= 0 && dirIndex <= 2)
                {
                    direction[dirIndex] = explodeStep.ReverseTranslationDirection ? -1.0 : 1.0;
                }
            }
            catch
            {
                // Leave unknown direction as [0,0,0]
            }

            return direction;
        }

        #region Helper Methods

        private string GetProperty(ICustomPropertyManager propMgr, params string[] names)
        {
            if (propMgr == null)
                return null;

            foreach (string name in names)
            {
                string valOut, resolvedValOut;
                bool wasResolved, linkToProperty;

                int result = propMgr.Get6(name, false, out valOut, out resolvedValOut, out wasResolved, out linkToProperty);
                if (result == (int)swCustomInfoGetResult_e.swCustomInfoGetResult_ResolvedValue ||
                    result == (int)swCustomInfoGetResult_e.swCustomInfoGetResult_CachedValue)
                {
                    string value = !string.IsNullOrEmpty(resolvedValOut) ? resolvedValOut : valOut;
                    if (!string.IsNullOrEmpty(value))
                        return value;
                }
            }

            return null;
        }

        private Dictionary<string, string> GetAllProperties(ICustomPropertyManager propMgr)
        {
            var props = new Dictionary<string, string>();
            if (propMgr == null)
                return props;

            try
            {
                object propNamesObj = null, propTypesObj = null, propValuesObj = null;
                object resolvedValuesObj = null, propLinkedObj = null;

                int count = propMgr.GetAll3(ref propNamesObj, ref propTypesObj, ref propValuesObj,
                                            ref resolvedValuesObj, ref propLinkedObj);

                if (count > 0)
                {
                    string[] propNames = (string[])propNamesObj;
                    string[] resolvedValues = (string[])resolvedValuesObj;
                    string[] propValues = (string[])propValuesObj;

                    for (int i = 0; i < count; i++)
                    {
                        string value = !string.IsNullOrEmpty(resolvedValues[i]) ? resolvedValues[i] : propValues[i];
                        if (!string.IsNullOrEmpty(propNames[i]))
                        {
                            props[propNames[i]] = value ?? "";
                        }
                    }
                }
            }
            catch { }

            return props;
        }

        private Dictionary<string, string> GetComponentProperties(IComponent2 comp)
        {
            var props = new Dictionary<string, string>();

            try
            {
                IModelDoc2 refDoc = (IModelDoc2)comp.GetModelDoc2();
                if (refDoc != null)
                {
                    ICustomPropertyManager propMgr = refDoc.Extension.CustomPropertyManager[""];
                    return GetAllProperties(propMgr);
                }
            }
            catch { }

            return props;
        }

        private ComponentState GetComponentState(int suppState)
        {
            switch ((swComponentSuppressionState_e)suppState)
            {
                case swComponentSuppressionState_e.swComponentFullyResolved:
                    return ComponentState.Resolved;
                case swComponentSuppressionState_e.swComponentLightweight:
                    return ComponentState.Lightweight;
                case swComponentSuppressionState_e.swComponentSuppressed:
                    return ComponentState.Suppressed;
                default:
                    return ComponentState.Unknown;
            }
        }

        private int GetInstanceNumber(string compName)
        {
            // Component names are like "Part-1", "Part-2", etc.
            int lastDash = compName.LastIndexOf('-');
            if (lastDash >= 0 && lastDash < compName.Length - 1)
            {
                if (int.TryParse(compName.Substring(lastDash + 1), out int num))
                    return num;
            }
            return 1;
        }

        private string GetMateTypeString(int type)
        {
            switch ((swMateType_e)type)
            {
                case swMateType_e.swMateCOINCIDENT: return "Coincident";
                case swMateType_e.swMateCONCENTRIC: return "Concentric";
                case swMateType_e.swMatePERPENDICULAR: return "Perpendicular";
                case swMateType_e.swMatePARALLEL: return "Parallel";
                case swMateType_e.swMateTANGENT: return "Tangent";
                case swMateType_e.swMateDISTANCE: return "Distance";
                case swMateType_e.swMateANGLE: return "Angle";
                case swMateType_e.swMateSYMMETRIC: return "Symmetric";
                case swMateType_e.swMateCAMFOLLOWER: return "Cam Follower";
                case swMateType_e.swMateGEAR: return "Gear";
                case swMateType_e.swMateWIDTH: return "Width";
                case swMateType_e.swMateLOCK: return "Lock";
                default: return $"Unknown({type})";
            }
        }

        private string GetEntityTypeString(int type)
        {
            switch ((swSelectType_e)type)
            {
                case swSelectType_e.swSelFACES: return "Face";
                case swSelectType_e.swSelEDGES: return "Edge";
                case swSelectType_e.swSelVERTICES: return "Vertex";
                case swSelectType_e.swSelDATUMPLANES: return "Plane";
                case swSelectType_e.swSelDATUMAXES: return "Axis";
                case swSelectType_e.swSelDATUMPOINTS: return "Point";
                default: return $"Unknown({type})";
            }
        }

        #endregion
    }
}
