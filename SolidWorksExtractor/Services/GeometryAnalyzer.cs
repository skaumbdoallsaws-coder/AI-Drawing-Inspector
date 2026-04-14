using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorksExtractor.Models;

namespace SolidWorksExtractor.Services
{
    /// <summary>
    /// Analyzes body geometry to extract ground truth data independent of features
    /// </summary>
    public class GeometryAnalyzer
    {
        private int _cylinderId = 0;
        private int _faceId = 0;
        private int _slotId = 0;

        // Sheet metal detection
        private bool _isSheetMetal = false;
        private double _sheetMetalBendRadius = 0;
        private HashSet<double> _bendRadii = new HashSet<double>();

        /// <summary>
        /// Extract geometry ground truth from part
        /// </summary>
        public GeometryGroundTruth AnalyzeGeometry(IModelDoc2 doc)
        {
            var truth = new GeometryGroundTruth();
            _cylinderId = 0;
            _faceId = 0;
            _slotId = 0;
            _isSheetMetal = false;
            _sheetMetalBendRadius = 0;
            _bendRadii.Clear();

            if (doc == null)
                return truth;

            IPartDoc partDoc = doc as IPartDoc;
            if (partDoc == null)
                return truth;

            try
            {
                // Detect sheet metal and collect bend radii before geometry analysis
                DetectSheetMetalBends(doc);

                // Get all solid bodies
                object[] bodies = (object[])partDoc.GetBodies2((int)swBodyType_e.swSolidBody, true);

                if (bodies != null)
                {
                    foreach (object bodyObj in bodies)
                    {
                        IBody2 body = (IBody2)bodyObj;
                        AnalyzeBody(body, truth);
                    }
                }

                // Filter out sheet metal bend cylinders from holes
                if (_isSheetMetal)
                {
                    FilterSheetMetalBends(truth);
                }

                // Detect slots from planar faces with arc+line edge patterns
                DetectSlots(truth);

                // Deduplicate planar faces by orientation and location
                DeduplicatePlanarFaces(truth);

                // Extract reference geometry
                truth.References = ExtractReferenceGeometry(doc);

                // Extract stable reference frames
                truth.ReferenceFrame = ExtractReferenceFrame(doc, partDoc);

                // Group similar cylinders (holes at same diameter) - excluding bends
                GroupSimilarCylinders(truth.Cylinders);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Error analyzing geometry: {ex.Message}");
            }

            return truth;
        }

        /// <summary>
        /// Detect if part is sheet metal and collect bend radii
        /// </summary>
        private void DetectSheetMetalBends(IModelDoc2 doc)
        {
            try
            {
                IFeature feat = (IFeature)doc.FirstFeature();

                while (feat != null)
                {
                    string typeName = feat.GetTypeName2();

                    // Sheet metal base flange indicates sheet metal part
                    if (typeName == "SMBaseFlange")
                    {
                        _isSheetMetal = true;

                        IBaseFlangeFeatureData data = (IBaseFlangeFeatureData)feat.GetDefinition();
                        if (data != null)
                        {
                            _sheetMetalBendRadius = data.BendRadius;
                            if (_sheetMetalBendRadius > 0)
                            {
                                _bendRadii.Add(Math.Round(_sheetMetalBendRadius, 6));
                            }
                        }
                    }
                    // Edge flange can have different bend radius
                    else if (typeName == "EdgeFlange" || typeName == "MiterFlange")
                    {
                        _isSheetMetal = true;

                        IEdgeFlangeFeatureData edgeData = feat.GetDefinition() as IEdgeFlangeFeatureData;
                        if (edgeData != null)
                        {
                            double radius = edgeData.BendRadius;
                            if (radius > 0)
                            {
                                _bendRadii.Add(Math.Round(radius, 6));
                            }
                        }
                    }
                    // Also check for Bends feature which contains all bend info
                    else if (typeName == "Bends" || typeName == "ProcessBends")
                    {
                        _isSheetMetal = true;

                        // Get sub-features which are individual bends
                        IFeature subFeat = (IFeature)feat.GetFirstSubFeature();
                        while (subFeat != null)
                        {
                            // Each bend might have its own radius
                            // Store the bend name for later matching
                            subFeat = (IFeature)subFeat.GetNextSubFeature();
                        }
                    }

                    feat = (IFeature)feat.GetNextFeature();
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: Error detecting sheet metal bends: {ex.Message}");
            }
        }

        /// <summary>
        /// Filter out cylinders that are sheet metal bends (not holes)
        /// </summary>
        private void FilterSheetMetalBends(GeometryGroundTruth truth)
        {
            if (!_isSheetMetal || _bendRadii.Count == 0)
                return;

            const double radiusTolerance = 0.0001;  // 0.1mm

            foreach (var cylinder in truth.Cylinders)
            {
                // Skip external cylinders (bosses) - only check internal
                if (!cylinder.IsInternal)
                    continue;

                // Check if this cylinder's radius matches a bend radius
                double cylRadius = Math.Round(cylinder.Radius, 6);

                foreach (double bendRadius in _bendRadii)
                {
                    if (Math.Abs(cylRadius - bendRadius) < radiusTolerance)
                    {
                        // Additional check: bends are typically partial cylinders (not full 360°)
                        // and have their axis perpendicular to the sheet
                        // For now, mark any matching radius as potential bend

                        cylinder.IsSheetMetalBend = true;
                        cylinder.Type = CylinderType.ExternalCylinder;  // Reclassify as not a hole
                        break;
                    }
                }
            }

            // Log filtering results
            int bendCount = truth.Cylinders.Count(c => c.IsSheetMetalBend);
            if (bendCount > 0)
            {
                Console.WriteLine($"  Filtered {bendCount} sheet metal bend cylinder(s) from holes");
            }
        }

        /// <summary>
        /// Analyze a single body
        /// </summary>
        private void AnalyzeBody(IBody2 body, GeometryGroundTruth truth)
        {
            if (body == null)
                return;

            // Get all faces
            object[] faces = (object[])body.GetFaces();
            if (faces == null)
                return;

            foreach (object faceObj in faces)
            {
                IFace2 face = (IFace2)faceObj;
                AnalyzeFace(face, truth);
            }

            // Analyze edges for summary
            AnalyzeEdges(body, truth);
        }

        /// <summary>
        /// Analyze a single face and classify it
        /// </summary>
        private void AnalyzeFace(IFace2 face, GeometryGroundTruth truth)
        {
            if (face == null)
                return;

            ISurface surface = (ISurface)face.GetSurface();
            if (surface == null)
                return;

            // Cylindrical faces (holes and bosses)
            if (surface.IsCylinder())
            {
                var cylinder = ExtractCylinder(face, surface);
                if (cylinder != null)
                {
                    truth.Cylinders.Add(cylinder);
                }
            }
            // Planar faces
            else if (surface.IsPlane())
            {
                var planar = ExtractPlanarFace(face, surface);
                if (planar != null)
                {
                    truth.PlanarFaces.Add(planar);
                }

                // Check if this planar face is a slot (boundary: 2 arcs + 2 parallel lines)
                var slot = TryDetectSlotFromPlanarFace(face);
                if (slot != null)
                {
                    // Get depth from planar face area / (length * width approximation)
                    // or mark as needing body analysis
                    truth.Slots.Add(slot);
                }
            }
            // Could add cone, sphere, torus detection here
        }

        /// <summary>
        /// Extract cylinder data from a cylindrical face
        /// </summary>
        private CylindricalFeature ExtractCylinder(IFace2 face, ISurface surface)
        {
            try
            {
                double[] cylParams = (double[])surface.CylinderParams;
                if (cylParams == null || cylParams.Length < 7)
                    return null;

                var cylinder = new CylindricalFeature
                {
                    Id = $"CYL_{++_cylinderId}",
                    AxisPoint = new double[] { cylParams[0], cylParams[1], cylParams[2] },
                    AxisDirection = new double[] { cylParams[3], cylParams[4], cylParams[5] },
                    Radius = cylParams[6],
                    Diameter = cylParams[6] * 2
                };

                // Determine if internal (hole) or external (boss)
                // Use face normal direction relative to radial direction from cylinder axis
                bool isInternal = false;
                try
                {
                    double[] faceNormal = (double[])face.Normal;
                    if (faceNormal != null)
                    {
                        // Get a point on the face center
                        double[] uvRange = (double[])face.GetUVBounds();
                        if (uvRange != null)
                        {
                            double u = (uvRange[0] + uvRange[1]) / 2;
                            double v = (uvRange[2] + uvRange[3]) / 2;
                            double[] evalResult = (double[])surface.Evaluate(u, v, 0, 0);

                            if (evalResult != null && evalResult.Length >= 3)
                            {
                                // Radial direction: from axis to point on surface
                                double[] toPoint = new double[]
                                {
                                    evalResult[0] - cylParams[0],
                                    evalResult[1] - cylParams[1],
                                    evalResult[2] - cylParams[2]
                                };

                                // Project onto plane perpendicular to axis
                                double axisDot = toPoint[0] * cylParams[3] + toPoint[1] * cylParams[4] + toPoint[2] * cylParams[5];
                                double[] radialDir = new double[]
                                {
                                    toPoint[0] - axisDot * cylParams[3],
                                    toPoint[1] - axisDot * cylParams[4],
                                    toPoint[2] - axisDot * cylParams[5]
                                };

                                // Normalize radial direction
                                double radialMag = Math.Sqrt(radialDir[0] * radialDir[0] + radialDir[1] * radialDir[1] + radialDir[2] * radialDir[2]);
                                if (radialMag > 0.0001)
                                {
                                    radialDir[0] /= radialMag;
                                    radialDir[1] /= radialMag;
                                    radialDir[2] /= radialMag;

                                    // Dot product of face normal with radial direction
                                    // Positive = normal points outward (same as radial) = external cylinder (boss)
                                    // Negative = normal points inward (opposite to radial) = internal cylinder (hole)
                                    double radialDot = radialDir[0] * faceNormal[0] + radialDir[1] * faceNormal[1] + radialDir[2] * faceNormal[2];

                                    // SolidWorks face normals point away from material
                                    // For a hole: material surrounds the cylinder, so normal points INWARD (toward axis)
                                    // radialDot < 0 means normal opposes radial = points toward axis = HOLE
                                    isInternal = radialDot < 0;
                                }
                            }
                        }
                    }
                }
                catch { }

                // If still false, try alternate detection: check if it's a small diameter (likely a hole)
                // This is a heuristic fallback
                if (!isInternal && cylinder.Radius < 0.025) // Less than 25mm radius = likely a hole
                {
                    // Check edge count - through holes typically have exactly 2 circular edges
                    try
                    {
                        object[] edges = (object[])face.GetEdges();
                        if (edges != null)
                        {
                            int circleCount = 0;
                            foreach (object edgeObj in edges)
                            {
                                IEdge edge = (IEdge)edgeObj;
                                ICurve curve = (ICurve)edge.GetCurve();
                                if (curve != null && curve.IsCircle())
                                    circleCount++;
                            }
                            // 2 circular edges = through hole, 1 = blind hole
                            // Either way, if small radius with circular edges, likely a hole
                            if (circleCount >= 1 && circleCount <= 2)
                            {
                                isInternal = true;
                            }
                        }
                    }
                    catch { }
                }

                cylinder.IsInternal = isInternal;

                // Get cylinder length from face edges
                cylinder.Length = EstimateCylinderLength(face);

                // Perform comprehensive THRU/BLIND analysis with axis-extent logic
                cylinder.ThroughAnalysis = AnalyzeThroughHole(face, cylinder);

                // Set IsThrough based on analysis results
                cylinder.IsThrough = cylinder.ThroughAnalysis.OpensAtStart && cylinder.ThroughAnalysis.OpensAtEnd;

                // Update depth from analysis if available and more accurate
                if (cylinder.ThroughAnalysis.ComputedDepth > 0 &&
                    (cylinder.Length == 0 || Math.Abs(cylinder.ThroughAnalysis.ComputedDepth - cylinder.Length) > 0.0001))
                {
                    cylinder.Length = cylinder.ThroughAnalysis.ComputedDepth;
                }

                // Compute start and end points from axis extents
                if (cylinder.ThroughAnalysis.AxisMinExtent != 0 || cylinder.ThroughAnalysis.AxisMaxExtent != 0)
                {
                    cylinder.StartPoint = new double[]
                    {
                        cylinder.AxisPoint[0] + cylinder.ThroughAnalysis.AxisMinExtent * cylinder.AxisDirection[0],
                        cylinder.AxisPoint[1] + cylinder.ThroughAnalysis.AxisMinExtent * cylinder.AxisDirection[1],
                        cylinder.AxisPoint[2] + cylinder.ThroughAnalysis.AxisMinExtent * cylinder.AxisDirection[2]
                    };
                    cylinder.EndPoint = new double[]
                    {
                        cylinder.AxisPoint[0] + cylinder.ThroughAnalysis.AxisMaxExtent * cylinder.AxisDirection[0],
                        cylinder.AxisPoint[1] + cylinder.ThroughAnalysis.AxisMaxExtent * cylinder.AxisDirection[1],
                        cylinder.AxisPoint[2] + cylinder.ThroughAnalysis.AxisMaxExtent * cylinder.AxisDirection[2]
                    };
                }

                // Detect entry treatments (counterbore, countersink, chamfer)
                cylinder.EntryTreatment = DetectEntryTreatment(face, cylinder);

                // Check for thread (helical edges)
                cylinder.HasThread = CheckForThread(face);

                // Update flags based on entry treatment
                if (cylinder.EntryTreatment != null)
                {
                    cylinder.HasCounterbore = cylinder.EntryTreatment.TreatmentType == "Counterbore";
                    cylinder.HasCountersink = cylinder.EntryTreatment.TreatmentType == "Countersink";
                }

                // Classify type based on all gathered information
                cylinder.Type = ClassifyCylinder(cylinder, face);

                // Get the feature that created this face (face ownership)
                try
                {
                    IFeature creatingFeature = (IFeature)face.GetFeature();
                    if (creatingFeature != null)
                    {
                        cylinder.AssociatedFeatureName = creatingFeature.Name;
                    }
                }
                catch { }

                return cylinder;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: Could not extract cylinder: {ex.Message}");
                return null;
            }
        }

        /// <summary>
        /// Estimate cylinder length from face geometry
        /// </summary>
        private double EstimateCylinderLength(IFace2 face)
        {
            try
            {
                // Get the circular edges and measure distance between them
                object[] edges = (object[])face.GetEdges();
                if (edges == null || edges.Length < 2)
                    return 0;

                List<double[]> circlesCenters = new List<double[]>();

                foreach (object edgeObj in edges)
                {
                    IEdge edge = (IEdge)edgeObj;
                    ICurve curve = (ICurve)edge.GetCurve();

                    if (curve != null && curve.IsCircle())
                    {
                        double[] circleParams = (double[])curve.CircleParams;
                        if (circleParams != null && circleParams.Length >= 3)
                        {
                            circlesCenters.Add(new double[] { circleParams[0], circleParams[1], circleParams[2] });
                        }
                    }
                }

                if (circlesCenters.Count >= 2)
                {
                    // Distance between first two circle centers
                    double dx = circlesCenters[1][0] - circlesCenters[0][0];
                    double dy = circlesCenters[1][1] - circlesCenters[0][1];
                    double dz = circlesCenters[1][2] - circlesCenters[0][2];
                    return Math.Sqrt(dx * dx + dy * dy + dz * dz);
                }
            }
            catch { }

            return 0;
        }

        /// <summary>
        /// Classify cylinder type based on geometry context and analysis results
        /// </summary>
        private CylinderType ClassifyCylinder(CylindricalFeature cyl, IFace2 face)
        {
            if (!cyl.IsInternal)
                return CylinderType.ExternalCylinder;

            // Check for counterbore/countersink first (based on entry treatment)
            if (cyl.HasCounterbore)
                return CylinderType.CounterboredHole;

            if (cyl.HasCountersink)
                return CylinderType.CountersunkHole;

            if (cyl.HasThread)
                return CylinderType.TappedHole;

            // Use the through analysis for THRU vs BLIND classification
            if (cyl.ThroughAnalysis != null)
            {
                // High confidence through detection
                if (cyl.ThroughAnalysis.Confidence == "High")
                {
                    if (cyl.ThroughAnalysis.OpensAtStart && cyl.ThroughAnalysis.OpensAtEnd)
                        return CylinderType.ThroughHole;
                    else
                        return CylinderType.BlindHole;
                }

                // Medium confidence - use the analysis but note it's heuristic
                if (cyl.ThroughAnalysis.Confidence == "Medium")
                {
                    if (cyl.ThroughAnalysis.OpensAtStart && cyl.ThroughAnalysis.OpensAtEnd)
                        return CylinderType.ThroughHole;
                    else
                        return CylinderType.BlindHole;
                }
            }

            // Fallback to legacy check
            if (cyl.IsThrough)
                return CylinderType.ThroughHole;

            // If we know it's internal but couldn't classify further, use HoleWall
            return CylinderType.HoleWall;
        }

        /// <summary>
        /// Detect entry treatments (countersink, counterbore, chamfer) at hole entry
        /// by analyzing faces adjacent to the entry circular edge
        /// </summary>
        private EntryTreatment DetectEntryTreatment(IFace2 cylinderFace, CylindricalFeature cylinder)
        {
            try
            {
                object[] edges = (object[])cylinderFace.GetEdges();
                if (edges == null)
                    return null;

                // Find the entry edge (the one at the start/entry of the hole)
                IEdge entryEdge = null;
                double entryProjection = double.MaxValue;

                foreach (object edgeObj in edges)
                {
                    IEdge edge = (IEdge)edgeObj;
                    ICurve curve = (ICurve)edge.GetCurve();
                    if (curve == null || !curve.IsCircle())
                        continue;

                    // Get circle center projection
                    double[] circleParams = (double[])curve.CircleParams;
                    if (circleParams == null || circleParams.Length < 3)
                        continue;

                    double[] center = new double[] { circleParams[0], circleParams[1], circleParams[2] };
                    double proj = ProjectPointOntoAxis(center, cylinder.AxisPoint, cylinder.AxisDirection);

                    // Entry is typically at the minimum extent (start of hole)
                    if (proj < entryProjection)
                    {
                        entryProjection = proj;
                        entryEdge = edge;
                    }
                }

                if (entryEdge == null)
                    return null;

                // Analyze faces adjacent to the entry edge
                object[] adjFaces = (object[])entryEdge.GetTwoAdjacentFaces2();
                if (adjFaces == null || adjFaces.Length < 2)
                    return null;

                foreach (object faceObj in adjFaces)
                {
                    IFace2 adjFace = (IFace2)faceObj;
                    if (adjFace == null || adjFace.IsSame(cylinderFace))
                        continue;

                    ISurface adjSurface = (ISurface)adjFace.GetSurface();
                    if (adjSurface == null)
                        continue;

                    // Check for counterbore (larger cylinder adjacent to hole entry)
                    if (adjSurface.IsCylinder())
                    {
                        double[] adjCylParams = (double[])adjSurface.CylinderParams;
                        if (adjCylParams != null && adjCylParams.Length >= 7)
                        {
                            double adjRadius = adjCylParams[6];
                            // Counterbore has larger diameter than hole
                            if (adjRadius > cylinder.Radius * 1.1)  // At least 10% larger
                            {
                                return new EntryTreatment
                                {
                                    TreatmentType = "Counterbore",
                                    Diameter = adjRadius * 2,
                                    Depth = EstimateCounterboreDepth(adjFace),
                                    Confidence = "High"
                                };
                            }
                        }
                    }
                    // Check for countersink (cone adjacent to hole entry)
                    else if (adjSurface.IsCone())
                    {
                        double[] coneParams = (double[])adjSurface.ConeParams;
                        if (coneParams != null && coneParams.Length >= 8)
                        {
                            // Cone params: point on axis (0-2), axis direction (3-5), half-angle (6), base radius (7)
                            double halfAngle = coneParams[6];
                            double fullAngle = halfAngle * 2 * (180.0 / Math.PI);  // Convert to degrees

                            // Common countersink angles: 82°, 90°, 100°, 120°
                            return new EntryTreatment
                            {
                                TreatmentType = "Countersink",
                                Diameter = EstimateCountersinkDiameter(adjFace, adjSurface),
                                Angle = fullAngle,
                                Confidence = "High"
                            };
                        }
                    }
                    // Check for chamfer (small planar annular face at entry)
                    else if (adjSurface.IsPlane())
                    {
                        // Could be a chamfer if it's a small angled face
                        double area = adjFace.GetArea();
                        // Small area relative to hole suggests chamfer
                        double holeArea = Math.PI * cylinder.Radius * cylinder.Radius;

                        if (area < holeArea * 0.5 && area > 0.00001)  // Between tiny and half hole area
                        {
                            return new EntryTreatment
                            {
                                TreatmentType = "Chamfer",
                                Depth = EstimateChamferSize(adjFace, cylinder),
                                Confidence = "Medium"
                            };
                        }
                    }
                }
            }
            catch { }

            return null;
        }

        /// <summary>
        /// Estimate counterbore depth from the cylindrical counterbore face
        /// </summary>
        private double EstimateCounterboreDepth(IFace2 face)
        {
            try
            {
                object[] edges = (object[])face.GetEdges();
                if (edges == null)
                    return 0;

                List<double[]> centers = new List<double[]>();

                foreach (object edgeObj in edges)
                {
                    IEdge edge = (IEdge)edgeObj;
                    ICurve curve = (ICurve)edge.GetCurve();
                    if (curve != null && curve.IsCircle())
                    {
                        double[] circleParams = (double[])curve.CircleParams;
                        if (circleParams != null && circleParams.Length >= 3)
                        {
                            centers.Add(new double[] { circleParams[0], circleParams[1], circleParams[2] });
                        }
                    }
                }

                if (centers.Count >= 2)
                {
                    double dx = centers[1][0] - centers[0][0];
                    double dy = centers[1][1] - centers[0][1];
                    double dz = centers[1][2] - centers[0][2];
                    return Math.Sqrt(dx * dx + dy * dy + dz * dz);
                }
            }
            catch { }
            return 0;
        }

        /// <summary>
        /// Estimate countersink diameter from the conical face
        /// </summary>
        private double EstimateCountersinkDiameter(IFace2 face, ISurface surface)
        {
            try
            {
                object[] edges = (object[])face.GetEdges();
                if (edges == null)
                    return 0;

                double maxRadius = 0;

                foreach (object edgeObj in edges)
                {
                    IEdge edge = (IEdge)edgeObj;
                    ICurve curve = (ICurve)edge.GetCurve();
                    if (curve != null && curve.IsCircle())
                    {
                        double[] circleParams = (double[])curve.CircleParams;
                        if (circleParams != null && circleParams.Length >= 7)
                        {
                            if (circleParams[6] > maxRadius)
                                maxRadius = circleParams[6];
                        }
                    }
                }

                return maxRadius * 2;
            }
            catch { }
            return 0;
        }

        /// <summary>
        /// Estimate chamfer size from the chamfer face
        /// </summary>
        private double EstimateChamferSize(IFace2 face, CylindricalFeature hole)
        {
            try
            {
                // Get edges of the chamfer face
                object[] edges = (object[])face.GetEdges();
                if (edges == null)
                    return 0;

                double outerRadius = 0;

                foreach (object edgeObj in edges)
                {
                    IEdge edge = (IEdge)edgeObj;
                    ICurve curve = (ICurve)edge.GetCurve();
                    if (curve != null && curve.IsCircle())
                    {
                        double[] circleParams = (double[])curve.CircleParams;
                        if (circleParams != null && circleParams.Length >= 7)
                        {
                            if (circleParams[6] > outerRadius)
                                outerRadius = circleParams[6];
                        }
                    }
                }

                // Chamfer size is difference between outer edge and hole radius
                if (outerRadius > hole.Radius)
                    return outerRadius - hole.Radius;
            }
            catch { }
            return 0;
        }

        /// <summary>
        /// Perform comprehensive THRU/BLIND analysis with axis-extent logic.
        /// Returns detailed analysis including confidence level.
        /// </summary>
        private ThroughHoleAnalysis AnalyzeThroughHole(IFace2 face, CylindricalFeature cylinder)
        {
            var analysis = new ThroughHoleAnalysis
            {
                Confidence = "Low",
                ClassificationReason = "Incomplete analysis"
            };

            try
            {
                object[] edges = (object[])face.GetEdges();
                if (edges == null || edges.Length == 0)
                    return analysis;

                // Step 1: Compute axis-extent by projecting all edge points onto the cylinder axis
                var axisPoint = cylinder.AxisPoint;
                var axisDir = cylinder.AxisDirection;

                if (axisPoint == null || axisDir == null)
                    return analysis;

                double minExtent = double.MaxValue;
                double maxExtent = double.MinValue;
                var circularEdgeCenters = new List<EdgeInfo>();

                foreach (object edgeObj in edges)
                {
                    IEdge edge = (IEdge)edgeObj;
                    ICurve curve = (ICurve)edge.GetCurve();
                    if (curve == null)
                        continue;

                    if (curve.IsCircle())
                    {
                        // Get circle center and project onto axis
                        double[] circleParams = (double[])curve.CircleParams;
                        if (circleParams != null && circleParams.Length >= 7)
                        {
                            double[] center = new double[] { circleParams[0], circleParams[1], circleParams[2] };
                            double projection = ProjectPointOntoAxis(center, axisPoint, axisDir);

                            if (projection < minExtent) minExtent = projection;
                            if (projection > maxExtent) maxExtent = projection;

                            // Track circular edge info for face adjacency analysis
                            circularEdgeCenters.Add(new EdgeInfo
                            {
                                Edge = edge,
                                Center = center,
                                Radius = circleParams[6],
                                AxisProjection = projection,
                                IsFullCircle = IsFullCircle(edge)
                            });
                        }
                    }
                    else
                    {
                        // For non-circular edges, sample start/end points
                        IVertex startV = (IVertex)edge.GetStartVertex();
                        IVertex endV = (IVertex)edge.GetEndVertex();

                        if (startV != null)
                        {
                            double[] pt = (double[])startV.GetPoint();
                            if (pt != null)
                            {
                                double proj = ProjectPointOntoAxis(pt, axisPoint, axisDir);
                                if (proj < minExtent) minExtent = proj;
                                if (proj > maxExtent) maxExtent = proj;
                            }
                        }
                        if (endV != null)
                        {
                            double[] pt = (double[])endV.GetPoint();
                            if (pt != null)
                            {
                                double proj = ProjectPointOntoAxis(pt, axisPoint, axisDir);
                                if (proj < minExtent) minExtent = proj;
                                if (proj > maxExtent) maxExtent = proj;
                            }
                        }
                    }
                }

                // Store computed extents
                if (minExtent != double.MaxValue && maxExtent != double.MinValue)
                {
                    analysis.AxisMinExtent = minExtent;
                    analysis.AxisMaxExtent = maxExtent;
                    analysis.ComputedDepth = Math.Abs(maxExtent - minExtent);
                }

                // Step 2: Analyze circular edges to determine open faces
                int fullCircleCount = circularEdgeCenters.Count(e => e.IsFullCircle);

                // Sort edges by axis projection
                var sortedEdges = circularEdgeCenters.OrderBy(e => e.AxisProjection).ToList();

                // Step 3: Check adjacent faces for each circular edge to detect outer body faces
                int outerFaceOpenings = 0;
                string entryOrientation = null;
                string exitOrientation = null;

                foreach (var edgeInfo in sortedEdges.Where(e => e.IsFullCircle))
                {
                    var adjacentFaceInfo = AnalyzeAdjacentFace(edgeInfo.Edge, face);
                    if (adjacentFaceInfo.IsOuterBodyFace)
                    {
                        outerFaceOpenings++;

                        // Determine if this is entry or exit based on axis position
                        bool isAtStart = Math.Abs(edgeInfo.AxisProjection - minExtent) < 0.0001;
                        bool isAtEnd = Math.Abs(edgeInfo.AxisProjection - maxExtent) < 0.0001;

                        if (isAtStart)
                        {
                            analysis.OpensAtStart = true;
                            entryOrientation = adjacentFaceInfo.Orientation;
                        }
                        if (isAtEnd)
                        {
                            analysis.OpensAtEnd = true;
                            exitOrientation = adjacentFaceInfo.Orientation;
                        }
                    }
                }

                analysis.OuterFaceCount = outerFaceOpenings;
                analysis.EntryFaceOrientation = entryOrientation;
                analysis.ExitFaceOrientation = exitOrientation;

                // Step 4: Classify THRU vs BLIND with confidence
                if (outerFaceOpenings >= 2 && analysis.OpensAtStart && analysis.OpensAtEnd)
                {
                    analysis.Confidence = "High";
                    analysis.ClassificationReason = $"Two outer body face openings detected at both ends";
                }
                else if (outerFaceOpenings == 1)
                {
                    analysis.Confidence = "High";
                    analysis.ClassificationReason = "Single outer body face opening - blind hole";
                }
                else if (fullCircleCount == 2)
                {
                    // Fallback heuristic: 2 complete circles often means through
                    analysis.Confidence = "Medium";
                    analysis.OpensAtStart = true;
                    analysis.OpensAtEnd = true;
                    analysis.ClassificationReason = "Two complete circular edges detected (heuristic)";
                }
                else if (fullCircleCount == 1)
                {
                    // Fallback heuristic: 1 complete circle often means blind
                    analysis.Confidence = "Medium";
                    analysis.OpensAtStart = true;
                    analysis.OpensAtEnd = false;
                    analysis.ClassificationReason = "Single complete circular edge detected (heuristic)";
                }
                else
                {
                    analysis.Confidence = "Low";
                    analysis.ClassificationReason = $"Unable to determine - {fullCircleCount} full circles, {circularEdgeCenters.Count} total circular edges";
                }
            }
            catch (Exception ex)
            {
                analysis.ClassificationReason = $"Analysis error: {ex.Message}";
            }

            return analysis;
        }

        /// <summary>
        /// Project a point onto the cylinder axis and return the scalar distance along axis
        /// </summary>
        private double ProjectPointOntoAxis(double[] point, double[] axisPoint, double[] axisDir)
        {
            // Vector from axis point to the point
            double dx = point[0] - axisPoint[0];
            double dy = point[1] - axisPoint[1];
            double dz = point[2] - axisPoint[2];

            // Dot product with axis direction gives projection distance
            return dx * axisDir[0] + dy * axisDir[1] + dz * axisDir[2];
        }

        /// <summary>
        /// Check if a circular edge is a full 360° circle
        /// </summary>
        private bool IsFullCircle(IEdge edge)
        {
            try
            {
                // A full circle has same start and end vertex (or both null for closed curve)
                IVertex startV = (IVertex)edge.GetStartVertex();
                IVertex endV = (IVertex)edge.GetEndVertex();

                // Both null means closed curve (full circle)
                if (startV == null && endV == null)
                    return true;

                // Same vertex means full circle
                if (startV != null && endV != null)
                {
                    double[] startPt = (double[])startV.GetPoint();
                    double[] endPt = (double[])endV.GetPoint();

                    if (startPt != null && endPt != null)
                    {
                        double dist = Math.Sqrt(
                            Math.Pow(endPt[0] - startPt[0], 2) +
                            Math.Pow(endPt[1] - startPt[1], 2) +
                            Math.Pow(endPt[2] - startPt[2], 2));
                        return dist < 0.0001;  // Within tolerance
                    }
                }
            }
            catch { }
            return false;
        }

        /// <summary>
        /// Analyze the face adjacent to a circular edge to determine if it's an outer body face
        /// </summary>
        private AdjacentFaceInfo AnalyzeAdjacentFace(IEdge edge, IFace2 cylinderFace)
        {
            var info = new AdjacentFaceInfo();

            try
            {
                // Get adjacent faces
                object[] adjacentFaces = (object[])edge.GetTwoAdjacentFaces2();
                if (adjacentFaces == null || adjacentFaces.Length < 2)
                    return info;

                // Find the face that isn't the cylinder face
                foreach (object faceObj in adjacentFaces)
                {
                    IFace2 adjFace = (IFace2)faceObj;
                    if (adjFace == null || adjFace.IsSame(cylinderFace))
                        continue;

                    ISurface adjSurface = (ISurface)adjFace.GetSurface();
                    if (adjSurface == null)
                        continue;

                    // Check if it's a planar face (typical outer body face)
                    if (adjSurface.IsPlane())
                    {
                        double[] planeParams = (double[])adjSurface.PlaneParams;
                        if (planeParams != null && planeParams.Length >= 6)
                        {
                            double[] normal = new double[] { planeParams[0], planeParams[1], planeParams[2] };
                            info.Orientation = ClassifyPlaneOrientation(normal);

                            // Planar faces adjacent to hole edges are typically outer body faces
                            // unless they're internal features like counterbore floors
                            info.IsOuterBodyFace = true;
                            info.IsPlanar = true;
                        }
                    }
                    else if (adjSurface.IsCylinder())
                    {
                        // Adjacent cylinder could be counterbore
                        info.IsOuterBodyFace = false;
                        info.IsCylinder = true;
                    }
                    else if (adjSurface.IsCone())
                    {
                        // Adjacent cone could be countersink
                        info.IsOuterBodyFace = false;
                        info.IsCone = true;
                    }

                    break;  // Only need one adjacent face
                }
            }
            catch { }

            return info;
        }

        /// <summary>
        /// Helper class for edge analysis
        /// </summary>
        private class EdgeInfo
        {
            public IEdge Edge { get; set; }
            public double[] Center { get; set; }
            public double Radius { get; set; }
            public double AxisProjection { get; set; }
            public bool IsFullCircle { get; set; }
        }

        /// <summary>
        /// Helper class for adjacent face analysis
        /// </summary>
        private class AdjacentFaceInfo
        {
            public bool IsOuterBodyFace { get; set; }
            public string Orientation { get; set; }
            public bool IsPlanar { get; set; }
            public bool IsCylinder { get; set; }
            public bool IsCone { get; set; }
        }

        /// <summary>
        /// Legacy method - kept for compatibility, now uses AnalyzeThroughHole internally
        /// </summary>
        private bool CheckIfThrough(IFace2 face)
        {
            try
            {
                // Simple heuristic: A through hole typically has exactly 2 circular edges
                object[] edges = (object[])face.GetEdges();
                if (edges == null)
                    return false;

                int circularEdgeCount = 0;
                foreach (object edgeObj in edges)
                {
                    IEdge edge = (IEdge)edgeObj;
                    ICurve curve = (ICurve)edge.GetCurve();
                    if (curve != null && curve.IsCircle())
                    {
                        circularEdgeCount++;
                    }
                }

                // Through holes have 2 complete circles
                return circularEdgeCount == 2;
            }
            catch { }

            return false;
        }

        /// <summary>
        /// Check for thread by looking for helical edges
        /// </summary>
        private bool CheckForThread(IFace2 face)
        {
            try
            {
                object[] edges = (object[])face.GetEdges();
                if (edges == null)
                    return false;

                foreach (object edgeObj in edges)
                {
                    IEdge edge = (IEdge)edgeObj;
                    ICurve curve = (ICurve)edge.GetCurve();

                    // Check if it's a helix (spiral)
                    if (curve != null)
                    {
                        // Helical edges are typically B-splines in SolidWorks
                        // A more robust check would involve analyzing the curve geometry
                        if (!curve.IsLine() && !curve.IsCircle() && !curve.IsEllipse())
                        {
                            // Could be helical - count spline edges
                            // This is a heuristic; proper thread detection is complex
                        }
                    }
                }
            }
            catch { }

            return false;
        }

        /// <summary>
        /// Extract planar face data
        /// </summary>
        private PlanarFace ExtractPlanarFace(IFace2 face, ISurface surface)
        {
            try
            {
                double[] planeParams = (double[])surface.PlaneParams;
                if (planeParams == null || planeParams.Length < 6)
                    return null;

                var planar = new PlanarFace
                {
                    Id = $"PLANE_{++_faceId}",
                    Normal = new double[] { planeParams[0], planeParams[1], planeParams[2] },
                    PointOnPlane = new double[] { planeParams[3], planeParams[4], planeParams[5] },
                    Area = face.GetArea()
                };

                // Classify orientation
                planar.Orientation = ClassifyPlaneOrientation(planar.Normal);

                // Calculate D in plane equation
                planar.D = -(planeParams[0] * planeParams[3] + planeParams[1] * planeParams[4] + planeParams[2] * planeParams[5]);

                return planar;
            }
            catch { }

            return null;
        }

        /// <summary>
        /// Classify plane orientation based on normal.
        /// Returns descriptive name with axis sign (e.g., "Top (+Z)", "Bottom (-Z)")
        /// to keep +Z and -Z distinct for deduplication and comparison.
        /// </summary>
        private string ClassifyPlaneOrientation(double[] normal)
        {
            const double tolerance = 0.99;  // cos(~8 degrees)

            if (Math.Abs(normal[2]) > tolerance)
                return normal[2] > 0 ? "Top (+Z)" : "Bottom (-Z)";
            if (Math.Abs(normal[1]) > tolerance)
                return normal[1] > 0 ? "Back (+Y)" : "Front (-Y)";
            if (Math.Abs(normal[0]) > tolerance)
                return normal[0] > 0 ? "Right (+X)" : "Left (-X)";

            return "Angled";
        }

        /// <summary>
        /// Analyze edges and build summary
        /// </summary>
        private void AnalyzeEdges(IBody2 body, GeometryGroundTruth truth)
        {
            try
            {
                object[] edges = (object[])body.GetEdges();
                if (edges == null)
                    return;

                truth.Edges = new EdgeSummary
                {
                    TotalEdgeCount = edges.Length
                };

                foreach (object edgeObj in edges)
                {
                    IEdge edge = (IEdge)edgeObj;
                    ICurve curve = (ICurve)edge.GetCurve();

                    if (curve == null)
                    {
                        truth.Edges.OtherEdgeCount++;
                        continue;
                    }

                    if (curve.IsLine())
                        truth.Edges.LinearEdgeCount++;
                    else if (curve.IsCircle())
                        truth.Edges.CircularEdgeCount++;
                    else if (curve.IsEllipse())
                        truth.Edges.OtherEdgeCount++;
                    else
                        truth.Edges.SplineEdgeCount++;  // Includes helixes
                }
            }
            catch { }
        }

        /// <summary>
        /// Extract reference geometry (planes, axes)
        /// </summary>
        private ReferenceGeometry ExtractReferenceGeometry(IModelDoc2 doc)
        {
            var refs = new ReferenceGeometry
            {
                Origin = new double[] { 0, 0, 0 }
            };

            try
            {
                // Get standard planes
                IFeature feat = (IFeature)doc.FirstFeature();
                while (feat != null)
                {
                    string typeName = feat.GetTypeName2();

                    if (typeName == "RefPlane")
                    {
                        IRefPlane plane = (IRefPlane)feat.GetSpecificFeature2();
                        if (plane != null)
                        {
                            IMathTransform transform = (IMathTransform)plane.Transform;
                            if (transform != null)
                            {
                                double[] matrix = (double[])transform.ArrayData;
                                var planeDef = new PlaneDefinition
                                {
                                    Name = feat.Name,
                                    Normal = new double[] { matrix[6], matrix[7], matrix[8] },  // Z-axis of transform
                                    Point = new double[] { matrix[9], matrix[10], matrix[11] }  // Origin
                                };

                                // Classify standard planes
                                string name = feat.Name.ToLower();
                                if (name.Contains("front"))
                                    refs.FrontPlane = planeDef;
                                else if (name.Contains("top"))
                                    refs.TopPlane = planeDef;
                                else if (name.Contains("right"))
                                    refs.RightPlane = planeDef;
                                else
                                    refs.CustomPlanes.Add(planeDef);
                            }
                        }
                    }
                    else if (typeName == "RefAxis")
                    {
                        IRefAxis axis = (IRefAxis)feat.GetSpecificFeature2();
                        if (axis != null)
                        {
                            double[] axisParams = (double[])axis.GetRefAxisParams();
                            if (axisParams != null && axisParams.Length >= 6)
                            {
                                refs.Axes.Add(new AxisDefinition
                                {
                                    Name = feat.Name,
                                    Point = new double[] { axisParams[0], axisParams[1], axisParams[2] },
                                    Direction = new double[] { axisParams[3], axisParams[4], axisParams[5] }
                                });
                            }
                        }
                    }

                    feat = (IFeature)feat.GetNextFeature();
                }
            }
            catch { }

            return refs;
        }

        /// <summary>
        /// Detect slots from planar face boundary loops.
        /// Slots have boundaries with 2 semicircular arcs + 2 parallel lines.
        /// Dimensions come from actual boundary geometry, not cylinder distances.
        /// </summary>
        private void DetectSlots(GeometryGroundTruth truth)
        {
            // Slots are detected from planar faces, not cylinders
            // A slot boundary loop has: 2 arcs (same radius) + 2 parallel lines (same length)
            // This method is called after faces are analyzed but we need the raw face data
            // For now, clear any incorrectly detected slots and note limitation
            truth.Slots.Clear();

            // TODO: Proper slot detection requires iterating planar faces and analyzing
            // their boundary loops for the arc+line+arc+line pattern.
            // The boundary analysis needs access to the original IFace2 objects.
            // Current approach: slots will be detected during face analysis if we find
            // planar faces with the characteristic boundary pattern.
        }

        /// <summary>
        /// Detect slot from a planar face's boundary loop.
        /// Called during planar face analysis.
        /// </summary>
        private SlotFeature TryDetectSlotFromPlanarFace(IFace2 face)
        {
            try
            {
                // Get the outer loop
                object[] loops = (object[])face.GetLoops();
                if (loops == null || loops.Length == 0)
                    return null;

                ILoop2 outerLoop = null;
                foreach (object loopObj in loops)
                {
                    ILoop2 loop = (ILoop2)loopObj;
                    if (loop.IsOuter())
                    {
                        outerLoop = loop;
                        break;
                    }
                }

                if (outerLoop == null)
                    return null;

                // Get edges from the loop
                object[] loopEdges = (object[])outerLoop.GetEdges();
                if (loopEdges == null)
                    return null;

                // Analyze edges: looking for 2 arcs + 2 lines pattern
                var arcs = new List<(IEdge edge, double radius, double[] center)>();
                var lines = new List<(IEdge edge, double length, double[] direction)>();

                foreach (object edgeObj in loopEdges)
                {
                    IEdge edge = (IEdge)edgeObj;
                    ICurve curve = (ICurve)edge.GetCurve();
                    if (curve == null)
                        continue;

                    if (curve.IsCircle())
                    {
                        // Get arc parameters
                        double[] arcParams = (double[])curve.CircleParams;
                        if (arcParams != null && arcParams.Length >= 7)
                        {
                            double[] arcCenter = new double[] { arcParams[0], arcParams[1], arcParams[2] };
                            double radius = arcParams[6];
                            arcs.Add((edge, radius, arcCenter));
                        }
                    }
                    else if (curve.IsLine())
                    {
                        // Get line parameters - need to cast vertices
                        try
                        {
                            IVertex startVertex = (IVertex)edge.GetStartVertex();
                            IVertex endVertex = (IVertex)edge.GetEndVertex();

                            if (startVertex != null && endVertex != null)
                            {
                                double[] startPt = (double[])startVertex.GetPoint();
                                double[] endPt = (double[])endVertex.GetPoint();

                                if (startPt != null && endPt != null)
                                {
                                    double dx = endPt[0] - startPt[0];
                                    double dy = endPt[1] - startPt[1];
                                    double dz = endPt[2] - startPt[2];
                                    double edgeLength = Math.Sqrt(dx * dx + dy * dy + dz * dz);

                                    if (edgeLength > 0.0001)
                                    {
                                        double[] direction = new double[] { dx / edgeLength, dy / edgeLength, dz / edgeLength };
                                        lines.Add((edge, edgeLength, direction));
                                    }
                                }
                            }
                        }
                        catch { }
                    }
                }

                // Slot pattern: exactly 2 arcs with same radius, 2 parallel lines with same length
                if (arcs.Count != 2 || lines.Count != 2)
                    return null;

                // Check arcs have same radius (tolerance 0.01mm)
                if (Math.Abs(arcs[0].radius - arcs[1].radius) > 0.00001)
                    return null;

                // Check lines are parallel (dot product ~1 or ~-1)
                double lineDot = Math.Abs(
                    lines[0].direction[0] * lines[1].direction[0] +
                    lines[0].direction[1] * lines[1].direction[1] +
                    lines[0].direction[2] * lines[1].direction[2]);
                if (lineDot < 0.99)
                    return null;

                // Check lines have same length (tolerance 0.01mm)
                if (Math.Abs(lines[0].length - lines[1].length) > 0.00001)
                    return null;

                // This is a slot!
                double width = arcs[0].radius * 2;  // Diameter of arc = slot width
                double straightLength = lines[0].length;  // Line length
                double overallLength = straightLength + width;  // Total slot length

                // Calculate center point (midpoint between arc centers)
                double[] center = new double[]
                {
                    (arcs[0].center[0] + arcs[1].center[0]) / 2,
                    (arcs[0].center[1] + arcs[1].center[1]) / 2,
                    (arcs[0].center[2] + arcs[1].center[2]) / 2
                };

                // Get face normal for depth direction
                double[] faceNormal = (double[])face.Normal;

                // Slot depth needs body analysis - for now use 0 (unknown)
                // Proper depth requires finding the opposing face or body extent
                double depth = 0;

                var slot = new SlotFeature
                {
                    Id = $"SLOT_{++_slotId}",
                    Length = overallLength,
                    Width = width,
                    Depth = depth,
                    CenterLine = lines[0].direction,
                    CenterPoint = center,
                    StartCenter = arcs[0].center,
                    EndCenter = arcs[1].center,
                    IsThrough = false,  // Needs body analysis to determine
                    SlotType = "Straight"
                };

                return slot;
            }
            catch
            {
                return null;
            }
        }

        /// <summary>
        /// Extract stable reference frames for positioning
        /// </summary>
        private ReferenceFrame ExtractReferenceFrame(IModelDoc2 doc, IPartDoc partDoc)
        {
            var frame = new ReferenceFrame();

            try
            {
                // Part origin is always at (0,0,0) with standard axes
                frame.PartOrigin = new CoordinateSystem
                {
                    Name = "Origin",
                    IsDefault = true,
                    Origin = new double[] { 0, 0, 0 },
                    XAxis = new double[] { 1, 0, 0 },
                    YAxis = new double[] { 0, 1, 0 },
                    ZAxis = new double[] { 0, 0, 1 },
                    TransformMatrix = new double[]
                    {
                        1, 0, 0, 0,  // Column 1
                        0, 1, 0, 0,  // Column 2
                        0, 0, 1, 0,  // Column 3
                        0, 0, 0, 1   // Column 4
                    }
                };

                // Extract user-defined coordinate systems
                IFeature feat = (IFeature)doc.FirstFeature();
                while (feat != null)
                {
                    string typeName = feat.GetTypeName2();

                    if (typeName == "CoordSys")
                    {
                        var cs = ExtractCoordinateSystem(feat);
                        if (cs != null)
                        {
                            frame.UserCoordinateSystems.Add(cs);
                        }
                    }

                    feat = (IFeature)feat.GetNextFeature();
                }

                // Calculate bounding box center
                if (partDoc != null)
                {
                    object[] bodies = (object[])partDoc.GetBodies2((int)swBodyType_e.swSolidBody, true);
                    if (bodies != null && bodies.Length > 0)
                    {
                        double minX = double.MaxValue, minY = double.MaxValue, minZ = double.MaxValue;
                        double maxX = double.MinValue, maxY = double.MinValue, maxZ = double.MinValue;

                        foreach (object bodyObj in bodies)
                        {
                            IBody2 body = (IBody2)bodyObj;
                            double[] box = (double[])body.GetBodyBox();
                            if (box != null && box.Length >= 6)
                            {
                                minX = Math.Min(minX, box[0]);
                                minY = Math.Min(minY, box[1]);
                                minZ = Math.Min(minZ, box[2]);
                                maxX = Math.Max(maxX, box[3]);
                                maxY = Math.Max(maxY, box[4]);
                                maxZ = Math.Max(maxZ, box[5]);
                            }
                        }

                        if (minX != double.MaxValue)
                        {
                            frame.BoundingBoxCenter = new double[]
                            {
                                (minX + maxX) / 2,
                                (minY + maxY) / 2,
                                (minZ + maxZ) / 2
                            };
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: Could not extract reference frame: {ex.Message}");
            }

            return frame;
        }

        /// <summary>
        /// Extract a coordinate system feature
        /// </summary>
        private CoordinateSystem ExtractCoordinateSystem(IFeature feat)
        {
            try
            {
                ICoordinateSystemFeatureData csData = (ICoordinateSystemFeatureData)feat.GetDefinition();
                if (csData == null)
                    return null;

                var cs = new CoordinateSystem
                {
                    Name = feat.Name,
                    IsDefault = false
                };

                // Get the transform from the coordinate system
                IMathTransform transform = (IMathTransform)csData.Transform;
                if (transform != null)
                {
                    double[] matrix = (double[])transform.ArrayData;
                    if (matrix != null && matrix.Length >= 16)
                    {
                        // SolidWorks returns row-major: [R00 R01 R02 0 R10 R11 R12 0 R20 R21 R22 0 Tx Ty Tz Scale]
                        // Convert to column-major for standard 4x4 representation

                        cs.Origin = new double[] { matrix[9], matrix[10], matrix[11] };
                        cs.XAxis = new double[] { matrix[0], matrix[3], matrix[6] };
                        cs.YAxis = new double[] { matrix[1], matrix[4], matrix[7] };
                        cs.ZAxis = new double[] { matrix[2], matrix[5], matrix[8] };

                        // Store full transform matrix (column-major)
                        cs.TransformMatrix = new double[]
                        {
                            matrix[0], matrix[3], matrix[6], 0,  // Column 1 (X-axis)
                            matrix[1], matrix[4], matrix[7], 0,  // Column 2 (Y-axis)
                            matrix[2], matrix[5], matrix[8], 0,  // Column 3 (Z-axis)
                            matrix[9], matrix[10], matrix[11], 1 // Column 4 (Translation)
                        };
                    }
                }

                return cs;
            }
            catch
            {
                return null;
            }
        }

        /// <summary>
        /// Deduplicate planar faces by orientation and plane location.
        /// Multiple co-planar faces (same orientation and D value) are merged into one representative.
        /// Ensures both +Z and -Z (and other orientation pairs) are properly represented.
        /// </summary>
        private void DeduplicatePlanarFaces(GeometryGroundTruth truth)
        {
            if (truth.PlanarFaces == null || truth.PlanarFaces.Count == 0)
                return;

            const double dTolerance = 0.0001;  // 0.1mm tolerance for plane offset

            // Group by orientation AND D value (plane offset)
            var groups = truth.PlanarFaces
                .GroupBy(f => new
                {
                    Orientation = f.Orientation,
                    DRounded = Math.Round(f.D / dTolerance) * dTolerance
                })
                .ToList();

            var deduped = new List<PlanarFace>();

            foreach (var group in groups)
            {
                // Take the first face as representative, but sum up total area
                var representative = group.First();
                double totalArea = group.Sum(f => f.Area);

                // Create merged face entry
                var merged = new PlanarFace
                {
                    Id = representative.Id,
                    Normal = representative.Normal,
                    PointOnPlane = representative.PointOnPlane,
                    D = representative.D,
                    Area = totalArea,
                    Orientation = representative.Orientation
                };

                // If multiple faces were merged, update the ID to indicate count
                if (group.Count() > 1)
                {
                    merged.Id = $"{representative.Id}_merged_{group.Count()}";
                }

                deduped.Add(merged);
            }

            // Sort by orientation for consistent output
            truth.PlanarFaces = deduped
                .OrderBy(f => f.Orientation)
                .ThenBy(f => f.D)
                .ToList();

            // Log summary
            int originalCount = truth.PlanarFaces.Count;
            var orientations = truth.PlanarFaces.Select(f => f.Orientation).Distinct().ToList();
            Console.WriteLine($"  Planar faces: {deduped.Count} unique planes ({string.Join(", ", orientations)})");
        }

        /// <summary>
        /// Group cylinders by diameter (for hole instances), excluding sheet metal bends
        /// </summary>
        private void GroupSimilarCylinders(List<CylindricalFeature> cylinders)
        {
            const double tolerance = 0.0001;  // 0.1mm tolerance

            var groups = cylinders
                .Where(c => c.IsInternal && !c.IsSheetMetalBend)  // Only holes, not bends
                .GroupBy(c => Math.Round(c.Diameter / tolerance) * tolerance)
                .ToList();

            int groupId = 0;
            foreach (var group in groups)
            {
                groupId++;
                int instance = 0;
                foreach (var cyl in group)
                {
                    cyl.GroupId = groupId;
                    cyl.InstanceInGroup = ++instance;
                }
            }
        }
    }
}
