using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorksExtractor.Models;

namespace SolidWorksExtractor.Services
{
    /// <summary>
    /// Reconciles Hole Wizard intent (feature definitions) with geometry ground truth (cylindrical faces).
    /// This dual-source approach prevents "Type_25" style outputs and catches API quirks.
    ///
    /// Source A (Intent): Thread, c'bore/c'sink, depth, standard/size from IWizardHoleFeatureData2
    /// Source B (Truth): Actual geometry scan - cylindrical faces/edges: diameter, axis, centers
    /// </summary>
    public class HoleReconciler
    {
        // Tolerance for matching hole diameters (meters)
        private const double DiameterTolerance = 0.0001;  // 0.1mm
        private const double PositionTolerance = 0.001;   // 1mm

        /// <summary>
        /// Reconcile hole features with geometry to produce comparison-ready hole groups
        /// </summary>
        public List<HoleGroup> ReconcileHoles(
            List<HoleWizardFeature> holeFeatures,
            List<CylindricalFeature> cylinders,
            List<PatternFeature> patterns)
        {
            var groups = new List<HoleGroup>();
            var matchedCylinders = new HashSet<string>();
            int groupCounter = 0;

            // Step 1: Process Hole Wizard features (intent)
            foreach (var hole in holeFeatures.Where(h => !h.IsSuppressed))
            {
                var group = CreateGroupFromHoleWizard(hole, ++groupCounter);

                // Find matching cylinders from geometry
                var matches = FindMatchingCylinders(hole, cylinders, matchedCylinders);

                if (matches.Any())
                {
                    // Reconcile: use feature intent for type/thread, geometry for actual dimensions
                    group.Instances = matches.Select((cyl, idx) => CreateInstanceFromCylinder(cyl, group.GroupId, idx + 1, hole.Name, group.Thread)).ToList();
                    group.Count = matches.Count;

                    // Set MeasuredDiameter from geometry ground truth
                    var firstMatch = matches.First();
                    group.MeasuredDiameter = DimensionValue.FromMeters(firstMatch.Diameter);

                    // Legacy field update
                    #pragma warning disable CS0618
                    if (hole.Diameter <= 0 && firstMatch.Diameter > 0)
                    {
                        group.Diameter = DimensionValue.FromMeters(firstMatch.Diameter);
                    }
                    #pragma warning restore CS0618

                    // Add reconciliation note with clear diameter labeling
                    double measuredMm = firstMatch.Diameter * 1000;

                    if (group.HoleType == "Tapped")
                    {
                        // For tapped holes: thread nominal (M6=6mm) vs tap drill (5mm) vs measured geometry
                        double threadNomMm = group.NominalDiameter?.Millimeters ?? 0;
                        double tapDrillMm = group.TapDrillDiameter?.Millimeters ?? (hole.Diameter * 1000);
                        double tapDrillDiff = Math.Abs(tapDrillMm - measuredMm);
                        group.ReconciliationNote = $"Matched by center; threadNominal={threadNomMm:F1}mm, tapDrill(feature)={tapDrillMm:F2}mm, measured(geometry)={measuredMm:F2}mm (diff={tapDrillDiff:F2}mm)";
                    }
                    else
                    {
                        // For non-tapped holes: nominal (feature) vs measured (geometry)
                        double nominalMm = group.NominalDiameter?.Millimeters ?? (hole.Diameter * 1000);
                        double diffMm = Math.Abs(nominalMm - measuredMm);
                        group.ReconciliationNote = $"Matched by center; nominal(feature)={nominalMm:F2}mm, measured(geometry)={measuredMm:F2}mm (diff={diffMm:F2}mm)";
                    }

                    // Validate instance count
                    if (hole.InstanceCount > 0 && matches.Count != hole.InstanceCount)
                    {
                        Console.WriteLine($"Warning: {hole.Name} - feature reports {hole.InstanceCount} instances, geometry found {matches.Count}");
                    }

                    group.Confidence = "High";  // Feature + geometry match
                    foreach (var cyl in matches)
                        matchedCylinders.Add(cyl.Id);
                }
                else
                {
                    // No geometry match - use feature data only
                    group.Instances = CreateInstancesFromFeature(hole, group.GroupId);
                    group.Confidence = "Medium";  // Feature only
                    group.ReconciliationNote = "No geometry match found - using feature data only";
                    Console.WriteLine($"Warning: {hole.Name} - no matching geometry found");
                }

                // Build canonical callout
                group.Canonical = BuildCanonicalCallout(group);

                groups.Add(group);
            }

            // Step 2: Find unmatched cylinders (geometry-only holes)
            // These might be holes from simple cuts, imported geometry, or features we couldn't identify
            var unmatchedCylinders = cylinders
                .Where(c => c.IsInternal && !matchedCylinders.Contains(c.Id))
                .ToList();

            if (unmatchedCylinders.Any())
            {
                // Group by diameter AND creating feature name (so holes from same feature stay together)
                var diameterFeatureGroups = unmatchedCylinders
                    .GroupBy(c => new {
                        Diameter = Math.Round(c.Diameter / DiameterTolerance) * DiameterTolerance,
                        Feature = c.AssociatedFeatureName ?? ""
                    })
                    .ToList();

                foreach (var diaGroup in diameterFeatureGroups)
                {
                    var measuredDia = DimensionValue.FromMeters(diaGroup.Key.Diameter);
                    var featureName = diaGroup.Key.Feature;
                    bool hasFeature = !string.IsNullOrEmpty(featureName);

                    // Determine confidence based on feature ownership
                    // - Has feature name: Medium (we know what created it)
                    // - No feature name: Low (pure geometry detection)
                    string confidence = hasFeature ? "Medium" : "Low";
                    string note = hasFeature
                        ? $"Geometry mapped to feature '{featureName}'"
                        : "Geometry-only detection - no feature ownership found [verify]";

                    var group = new HoleGroup
                    {
                        GroupId = $"GEOM_{++groupCounter}",
                        HoleType = diaGroup.First().IsThrough ? "Through" : "Blind",
                        MeasuredDiameter = measuredDia,  // Geometry-only uses measured
                        NominalDiameter = null,          // No feature intent
                        TapDrillDiameter = null,         // No feature intent
                        Depth = diaGroup.First().IsThrough ? null : DimensionValue.FromMeters(diaGroup.First().Length),
                        Count = diaGroup.Count(),
                        Source = hasFeature ? "GeometryWithFeature" : "GeometryOnly",
                        Confidence = confidence,
                        ReconciliationNote = note,
                        Instances = diaGroup.Select((cyl, idx) =>
                            CreateInstanceFromCylinder(cyl, $"GEOM_{groupCounter}", idx + 1, cyl.AssociatedFeatureName)).ToList()
                    };

                    #pragma warning disable CS0618
                    group.Diameter = measuredDia;  // Legacy field
                    #pragma warning restore CS0618

                    group.Canonical = BuildCanonicalCallout(group);
                    groups.Add(group);
                }
            }

            // Step 3: Apply pattern information from features
            ApplyPatternInfo(groups, patterns);

            // Step 4: Infer pattern descriptors for all groups (geometry-based analysis)
            foreach (var group in groups)
            {
                InferPatternDescriptors(group);
            }

            return groups;
        }

        /// <summary>
        /// Create a hole group from Hole Wizard feature (intent)
        /// </summary>
        private HoleGroup CreateGroupFromHoleWizard(HoleWizardFeature hole, int groupNum)
        {
            var group = new HoleGroup
            {
                GroupId = $"HW_{groupNum}",
                Source = "HoleWizard"
            };

            // Determine hole type and set diameter fields properly
            if (hole.IsTapped)
            {
                group.HoleType = "Tapped";

                // Parse thread info: M6x1.0 -> nominal=6mm, tap drill from feature diameter
                var threadInfo = ParseThreadInfo(hole.ThreadSize ?? hole.FastenerSize);

                group.Thread = new ThreadSpec
                {
                    Callout = hole.ThreadSize ?? hole.FastenerSize,
                    Standard = DetermineThreadStandard(hole.Standard, hole.ThreadSize),
                    NominalDiameter = threadInfo.nominalDia > 0 ? DimensionValue.FromMeters(threadInfo.nominalDia) : null,
                    TapDrillDiameter = hole.Diameter > 0 ? DimensionValue.FromMeters(hole.Diameter) : null,
                    Pitch = threadInfo.pitch,
                    ThreadClass = hole.ThreadClass,
                    ThreadDepth = hole.ThreadDepth > 0 ? DimensionValue.FromMeters(hole.ThreadDepth) : null
                };

                // For tapped holes: NominalDiameter = thread major dia, TapDrillDiameter = feature diameter
                group.NominalDiameter = group.Thread.NominalDiameter;
                group.TapDrillDiameter = group.Thread.TapDrillDiameter;
            }
            else if (hole.CounterboreDiameter > 0)
            {
                group.HoleType = "Counterbore";
                group.Counterbore = new CounterboreSpec
                {
                    Diameter = DimensionValue.FromMeters(hole.CounterboreDiameter),
                    Depth = DimensionValue.FromMeters(hole.CounterboreDepth),
                    Callout = $"C'BORE ø{hole.CounterboreDiameter * 1000:F2}mm x {hole.CounterboreDepth * 1000:F1}mm DEEP"
                };
                group.NominalDiameter = DimensionValue.FromMeters(hole.Diameter);
            }
            else if (hole.CountersinkDiameter > 0)
            {
                group.HoleType = "Countersink";
                group.Countersink = new CountersinkSpec
                {
                    Diameter = DimensionValue.FromMeters(hole.CountersinkDiameter),
                    Angle = DimensionValue.FromDegrees(hole.CountersinkAngle),
                    Callout = $"C'SINK ø{hole.CountersinkDiameter * 1000:F2}mm x {hole.CountersinkAngle:F0}°"
                };
                group.NominalDiameter = DimensionValue.FromMeters(hole.Diameter);
            }
            else if (hole.IsThrough)
            {
                group.HoleType = "Through";
                group.NominalDiameter = DimensionValue.FromMeters(hole.Diameter);
            }
            else
            {
                group.HoleType = "Blind";
                group.NominalDiameter = DimensionValue.FromMeters(hole.Diameter);
            }

            // Legacy field
            #pragma warning disable CS0618
            group.Diameter = DimensionValue.FromMeters(hole.Diameter);
            #pragma warning restore CS0618

            group.Depth = hole.IsThrough ? null : DimensionValue.FromMeters(hole.Depth);
            group.Count = Math.Max(1, hole.InstanceCount);

            return group;
        }

        /// <summary>
        /// Parse thread callout to extract nominal diameter and pitch
        /// E.g., "M6x1.0" -> nominal=0.006m, pitch=1.0
        /// </summary>
        private (double nominalDia, double pitch) ParseThreadInfo(string threadCallout)
        {
            if (string.IsNullOrEmpty(threadCallout))
                return (0, 0);

            // Metric: M6, M6x1.0, M10x1.5
            var metricMatch = System.Text.RegularExpressions.Regex.Match(
                threadCallout, @"M(\d+(?:\.\d+)?)\s*(?:x\s*(\d+(?:\.\d+)?))?",
                System.Text.RegularExpressions.RegexOptions.IgnoreCase);

            if (metricMatch.Success)
            {
                double nominalMm = double.Parse(metricMatch.Groups[1].Value);
                double pitch = metricMatch.Groups[2].Success ? double.Parse(metricMatch.Groups[2].Value) : 0;
                return (nominalMm / 1000.0, pitch);  // Convert mm to meters
            }

            // Unified: #10-24 UNC, 1/4-20 UNC
            var unifiedMatch = System.Text.RegularExpressions.Regex.Match(
                threadCallout, @"#?(\d+)(?:/(\d+))?-(\d+)",
                System.Text.RegularExpressions.RegexOptions.IgnoreCase);

            if (unifiedMatch.Success)
            {
                // This is a simplified conversion - proper implementation needs thread tables
                double tpi = double.Parse(unifiedMatch.Groups[3].Value);
                // Approximate nominal from number or fraction
                return (0, tpi);  // Would need thread table for actual diameter
            }

            return (0, 0);
        }

        /// <summary>
        /// Find cylinders that match a hole feature by center/axis position.
        /// This is more robust than diameter matching since tapped holes have different
        /// tap drill diameter vs thread nominal.
        /// </summary>
        private List<CylindricalFeature> FindMatchingCylinders(
            HoleWizardFeature hole,
            List<CylindricalFeature> cylinders,
            HashSet<string> alreadyMatched)
        {
            var matches = new List<CylindricalFeature>();

            // All internal cylinders that aren't already matched
            var candidates = cylinders
                .Where(c => c.IsInternal && !alreadyMatched.Contains(c.Id))
                .ToList();

            if (candidates.Count == 0)
                return matches;

            // Match by center/axis position (primary) - more robust than diameter
            if (hole.InstanceLocations != null && hole.InstanceLocations.Count > 0)
            {
                foreach (var loc in hole.InstanceLocations)
                {
                    // Find closest cylinder by axis distance (project point onto cylinder axis)
                    var closest = candidates
                        .Where(c => !matches.Contains(c))
                        .OrderBy(c => DistanceToAxis(loc, c))
                        .FirstOrDefault();

                    if (closest != null && DistanceToAxis(loc, closest) < PositionTolerance)
                    {
                        matches.Add(closest);
                    }
                }
            }
            else
            {
                // No position info from feature - try diameter-based matching as fallback
                double targetDia = hole.Diameter;
                if (targetDia <= 0)
                {
                    targetDia = ParseDiameterFromName(hole.Name);
                }

                if (targetDia > 0)
                {
                    // For tapped holes, geometry diameter won't match nominal
                    // Use a wider tolerance or match any internal cylinder at similar size
                    double tolerance = hole.IsTapped ? targetDia * 0.3 : DiameterTolerance;

                    var diaMatches = candidates
                        .Where(c => Math.Abs(c.Diameter - targetDia) < tolerance)
                        .Take(Math.Max(1, hole.InstanceCount))
                        .ToList();

                    matches.AddRange(diaMatches);
                }
            }

            return matches;
        }

        /// <summary>
        /// Create hole instance from cylinder geometry
        /// </summary>
        private HoleInstance CreateInstanceFromCylinder(CylindricalFeature cyl, string groupId, int instanceNum, string featureName, ThreadSpec threadSpec = null)
        {
            var modelCenter = Point3D.FromArray(cyl.AxisPoint);
            var axis = Vector3D.FromArray(cyl.AxisDirection);

            // Compute face entry center: project to face plane (set axis component to face Z)
            // For Z-axis holes, normalize Z to 0 at entry face
            Point3D faceEntryCenter = null;
            if (modelCenter != null && axis != null)
            {
                // Determine which axis is primary (hole direction)
                string primaryAxis = axis.GetPrimaryAxis();

                // Project center to entry face (zero out the axis component)
                faceEntryCenter = new Point3D
                {
                    X = primaryAxis == "+X" || primaryAxis == "-X" ? 0 : modelCenter.X,
                    Y = primaryAxis == "+Y" || primaryAxis == "-Y" ? 0 : modelCenter.Y,
                    Z = primaryAxis == "+Z" || primaryAxis == "-Z" ? 0 : modelCenter.Z
                };
            }

            return new HoleInstance
            {
                InstanceId = cyl.Id,
                GroupId = groupId,
                ModelCenter = modelCenter,
                FaceEntryCenter = faceEntryCenter,
                Center = modelCenter,  // Legacy: keep as model center
                Axis = axis,
                MeasuredDiameter = DimensionValue.FromMeters(cyl.Diameter),
                MeasuredDepth = cyl.Length > 0 ? DimensionValue.FromMeters(cyl.Length) : null,
                IsThrough = cyl.IsThrough,
                FeatureName = featureName,
                PatternInstance = instanceNum,
                StartFace = axis?.GetPrimaryAxis(),
                // Thread metadata propagated from group (intent vs modeled)
                HasThreadIntent = threadSpec != null,  // Feature says it's tapped
                ThreadCallout = threadSpec?.Callout,   // e.g., "M6x1.0"
                ThreadModeled = cyl.HasThread          // True only if helical geometry present (rare)
            };
        }

        /// <summary>
        /// Create instances from feature data when no geometry match
        /// </summary>
        private List<HoleInstance> CreateInstancesFromFeature(HoleWizardFeature hole, string groupId)
        {
            var instances = new List<HoleInstance>();

            if (hole.InstanceLocations != null && hole.InstanceLocations.Count > 0)
            {
                int idx = 0;
                foreach (var loc in hole.InstanceLocations)
                {
                    instances.Add(new HoleInstance
                    {
                        InstanceId = $"{groupId}_{++idx}",
                        GroupId = groupId,
                        Center = Point3D.FromArray(loc),
                        MeasuredDiameter = hole.Diameter > 0 ? DimensionValue.FromMeters(hole.Diameter) : null,
                        MeasuredDepth = hole.Depth > 0 ? DimensionValue.FromMeters(hole.Depth) : null,
                        IsThrough = hole.IsThrough,
                        FeatureName = hole.Name,
                        PatternInstance = idx
                    });
                }
            }
            else
            {
                // Single instance with no location
                instances.Add(new HoleInstance
                {
                    InstanceId = $"{groupId}_1",
                    GroupId = groupId,
                    MeasuredDiameter = hole.Diameter > 0 ? DimensionValue.FromMeters(hole.Diameter) : null,
                    MeasuredDepth = hole.Depth > 0 ? DimensionValue.FromMeters(hole.Depth) : null,
                    IsThrough = hole.IsThrough,
                    FeatureName = hole.Name,
                    PatternInstance = 1
                });
            }

            return instances;
        }

        /// <summary>
        /// Apply pattern information to hole groups with explicit instance centers
        /// </summary>
        private void ApplyPatternInfo(List<HoleGroup> groups, List<PatternFeature> patterns)
        {
            foreach (var pattern in patterns.Where(p => !p.IsSuppressed))
            {
                // Find groups that contain seed features from this pattern
                foreach (var seedName in pattern.SeedFeatures)
                {
                    var matchingGroup = groups.FirstOrDefault(g =>
                        g.Instances.Any(i => i.FeatureName == seedName));

                    if (matchingGroup != null)
                    {
                        matchingGroup.Pattern = new PatternInfo
                        {
                            PatternType = pattern.PatternType,
                            PatternName = pattern.Name,
                            TotalInstances = pattern.TotalInstances > 0 ? pattern.TotalInstances : matchingGroup.Count
                        };

                        if (pattern.PatternType == "Linear")
                        {
                            matchingGroup.Pattern.Direction1Count = pattern.Direction1Count;
                            matchingGroup.Pattern.Direction1Spacing = DimensionValue.FromMeters(pattern.Direction1Spacing);
                            matchingGroup.Pattern.Direction2Count = pattern.Direction2Count;
                            matchingGroup.Pattern.Direction2Spacing = DimensionValue.FromMeters(pattern.Direction2Spacing);

                            // Add direction vectors if available
                            if (pattern.Direction1Vector != null)
                            {
                                matchingGroup.Pattern.Direction1Vector = Vector3D.FromArray(pattern.Direction1Vector);
                            }
                            if (pattern.Direction2Vector != null)
                            {
                                matchingGroup.Pattern.Direction2Vector = Vector3D.FromArray(pattern.Direction2Vector);
                            }

                            // Build canonical for linear pattern
                            int d1 = pattern.Direction1Count;
                            int d2 = Math.Max(1, pattern.Direction2Count);
                            double s1 = pattern.Direction1Spacing * 1000;  // mm
                            double s2 = pattern.Direction2Spacing * 1000;  // mm

                            if (d2 > 1)
                            {
                                matchingGroup.Pattern.Canonical = $"{d1}x{d2} GRID @ {s1:F1}mm x {s2:F1}mm";
                            }
                            else
                            {
                                matchingGroup.Pattern.Canonical = $"{d1}X @ {s1:F1}mm SPACING";
                            }
                        }
                        else if (pattern.PatternType == "Circular")
                        {
                            matchingGroup.Pattern.TotalAngle = DimensionValue.FromDegrees(pattern.TotalAngle);
                            matchingGroup.Pattern.EqualSpacing = pattern.EqualSpacing;

                            // Axis information
                            if (pattern.AxisLocation != null)
                            {
                                matchingGroup.Pattern.AxisLocation = Point3D.FromArray(pattern.AxisLocation);
                            }
                            if (pattern.AxisDirection != null)
                            {
                                matchingGroup.Pattern.AxisDirection = Vector3D.FromArray(pattern.AxisDirection);
                            }

                            // Calculate angle per instance
                            if (pattern.TotalInstances > 1 && pattern.EqualSpacing)
                            {
                                double anglePerInstance = pattern.TotalAngle / pattern.TotalInstances;
                                matchingGroup.Pattern.AnglePerInstance = DimensionValue.FromDegrees(anglePerInstance);
                            }

                            // Calculate bolt circle diameter from actual instance positions
                            if (matchingGroup.Instances.Count >= 2)
                            {
                                var bcdResult = CalculateBoltCircleFromInstances(matchingGroup.Instances, pattern);
                                if (bcdResult.Diameter > 0)
                                {
                                    matchingGroup.Pattern.BoltCircleDiameter = DimensionValue.FromMeters(bcdResult.Diameter);
                                    matchingGroup.Pattern.BoltCircleRadius = DimensionValue.FromMeters(bcdResult.Radius);

                                    // Build canonical for circular pattern
                                    double bcdMm = bcdResult.Diameter * 1000;
                                    matchingGroup.Pattern.Canonical = $"{matchingGroup.Count}X ON ø{bcdMm:F1}mm B.C.";
                                }
                            }
                        }
                        else if (pattern.PatternType == "Mirror")
                        {
                            matchingGroup.Pattern.Canonical = "MIRRORED";
                        }

                        // Populate explicit instance centers from pattern locations
                        PopulateInstanceCenters(matchingGroup, pattern);
                    }
                }
            }
        }

        /// <summary>
        /// Populate explicit instance centers in the pattern info from actual hole instances
        /// </summary>
        private void PopulateInstanceCenters(HoleGroup group, PatternFeature pattern)
        {
            group.Pattern.InstanceCenters = new List<PatternInstanceCenter>();

            int instanceNum = 0;
            foreach (var instance in group.Instances)
            {
                instanceNum++;

                var center = new PatternInstanceCenter
                {
                    InstanceNumber = instanceNum,
                    Center = instance.Center,
                    IsSkipped = pattern.SkippedInstances?.Contains(instanceNum) ?? false
                };

                // For circular patterns, calculate angle from first instance
                if (pattern.PatternType == "Circular" && instanceNum > 1 && group.Instances.Count > 0)
                {
                    var firstInstance = group.Instances[0];
                    if (firstInstance.Center != null && instance.Center != null && pattern.AxisLocation != null)
                    {
                        double angle = CalculateAngleBetweenInstances(
                            firstInstance.Center, instance.Center,
                            Point3D.FromArray(pattern.AxisLocation),
                            pattern.AxisDirection != null ? Vector3D.FromArray(pattern.AxisDirection) : null);
                        center.Angle = DimensionValue.FromDegrees(angle);
                    }
                }

                group.Pattern.InstanceCenters.Add(center);
            }
        }

        /// <summary>
        /// Calculate bolt circle from actual instance positions
        /// </summary>
        private (double Diameter, double Radius) CalculateBoltCircleFromInstances(List<HoleInstance> instances, PatternFeature pattern)
        {
            if (instances.Count < 2)
                return (0, 0);

            // If we have axis location, calculate radius from axis
            if (pattern.AxisLocation != null)
            {
                double axisX = pattern.AxisLocation[0];
                double axisY = pattern.AxisLocation[1];
                double axisZ = pattern.AxisLocation[2];

                var radii = instances
                    .Where(i => i.Center != null)
                    .Select(i =>
                    {
                        // Distance from axis to hole center
                        double dx = i.Center.X - axisX;
                        double dy = i.Center.Y - axisY;
                        double dz = i.Center.Z - axisZ;

                        // Project to plane perpendicular to axis if we have axis direction
                        if (pattern.AxisDirection != null)
                        {
                            double dot = dx * pattern.AxisDirection[0] +
                                        dy * pattern.AxisDirection[1] +
                                        dz * pattern.AxisDirection[2];
                            dx -= dot * pattern.AxisDirection[0];
                            dy -= dot * pattern.AxisDirection[1];
                            dz -= dot * pattern.AxisDirection[2];
                        }

                        return Math.Sqrt(dx * dx + dy * dy + dz * dz);
                    })
                    .ToList();

                if (radii.Any())
                {
                    double avgRadius = radii.Average();
                    return (avgRadius * 2, avgRadius);
                }
            }

            // Fallback: use centroid method
            double radius = CalculateBoltCircleDiameter(instances) / 2;
            return (radius * 2, radius);
        }

        /// <summary>
        /// Calculate angle between two instance positions around an axis
        /// </summary>
        private double CalculateAngleBetweenInstances(Point3D first, Point3D second, Point3D axisPoint, Vector3D axisDir)
        {
            if (first == null || second == null || axisPoint == null)
                return 0;

            // Vectors from axis to each instance (projected to plane perpendicular to axis)
            double[] v1 = { first.X - axisPoint.X, first.Y - axisPoint.Y, first.Z - axisPoint.Z };
            double[] v2 = { second.X - axisPoint.X, second.Y - axisPoint.Y, second.Z - axisPoint.Z };

            // Project to perpendicular plane if we have axis direction
            if (axisDir != null)
            {
                double dot1 = v1[0] * axisDir.X + v1[1] * axisDir.Y + v1[2] * axisDir.Z;
                v1[0] -= dot1 * axisDir.X;
                v1[1] -= dot1 * axisDir.Y;
                v1[2] -= dot1 * axisDir.Z;

                double dot2 = v2[0] * axisDir.X + v2[1] * axisDir.Y + v2[2] * axisDir.Z;
                v2[0] -= dot2 * axisDir.X;
                v2[1] -= dot2 * axisDir.Y;
                v2[2] -= dot2 * axisDir.Z;
            }

            // Angle between v1 and v2
            double mag1 = Math.Sqrt(v1[0] * v1[0] + v1[1] * v1[1] + v1[2] * v1[2]);
            double mag2 = Math.Sqrt(v2[0] * v2[0] + v2[1] * v2[1] + v2[2] * v2[2]);

            if (mag1 < 0.0001 || mag2 < 0.0001)
                return 0;

            double dot = (v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]) / (mag1 * mag2);
            dot = Math.Max(-1, Math.Min(1, dot));  // Clamp to [-1, 1]

            return Math.Acos(dot) * (180.0 / Math.PI);
        }

        /// <summary>
        /// Build canonical callout string for a hole group
        /// </summary>
        private string BuildCanonicalCallout(HoleGroup group)
        {
            var parts = new List<string>();

            // Thread callout (for tapped holes)
            if (group.Thread != null && !string.IsNullOrEmpty(group.Thread.Callout))
            {
                parts.Add(group.Thread.Callout);
            }
            else
            {
                // Non-tapped: use measured diameter (ground truth) if available, else nominal
                double? diamMm = group.MeasuredDiameter?.Millimeters
                              ?? group.NominalDiameter?.Millimeters;

                if (diamMm.HasValue && diamMm.Value > 0)
                {
                    parts.Add($"ø{diamMm.Value:F2}mm");
                }
            }

            // Depth or THRU
            if (group.HoleType == "Through")
            {
                parts.Add("THRU");
            }
            else if (group.Depth != null && group.Depth.Millimeters > 0)
            {
                parts.Add($"x {group.Depth.Millimeters:F1}mm DEEP");
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

        /// <summary>
        /// Determine thread standard from hole wizard data
        /// </summary>
        private string DetermineThreadStandard(string holeStandard, string threadSize)
        {
            if (string.IsNullOrEmpty(threadSize))
                return holeStandard ?? "Unknown";

            if (threadSize.StartsWith("M"))
                return "Metric";
            if (threadSize.Contains("UNC"))
                return "UNC";
            if (threadSize.Contains("UNF"))
                return "UNF";
            if (threadSize.StartsWith("#") || threadSize.Contains("-"))
                return "Unified";

            return holeStandard ?? "Unknown";
        }

        /// <summary>
        /// Parse diameter from hole feature name (fallback for API bug)
        /// </summary>
        private double ParseDiameterFromName(string name)
        {
            if (string.IsNullOrEmpty(name))
                return 0;

            // Pattern: "(0.51563)" - value in parentheses (likely inches)
            var match = System.Text.RegularExpressions.Regex.Match(name, @"\(([0-9.]+)\)");
            if (match.Success && double.TryParse(match.Groups[1].Value, out double inches))
            {
                return inches * 0.0254;  // Convert to meters
            }

            // Pattern: "M8" or "M10" - metric thread nominal
            match = System.Text.RegularExpressions.Regex.Match(name, @"M(\d+(?:\.\d+)?)", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
            if (match.Success && double.TryParse(match.Groups[1].Value, out double mm))
            {
                return mm / 1000.0;  // Convert to meters
            }

            // Pattern: "10.5mm" - explicit mm
            match = System.Text.RegularExpressions.Regex.Match(name, @"(\d+(?:\.\d+)?)\s*mm", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
            if (match.Success && double.TryParse(match.Groups[1].Value, out mm))
            {
                return mm / 1000.0;
            }

            return 0;
        }

        /// <summary>
        /// Calculate distance from a point to a cylinder axis
        /// </summary>
        private double DistanceToAxis(double[] point, CylindricalFeature cyl)
        {
            if (point == null || point.Length < 3 || cyl.AxisPoint == null)
                return double.MaxValue;

            // Vector from axis point to test point
            double dx = point[0] - cyl.AxisPoint[0];
            double dy = point[1] - cyl.AxisPoint[1];
            double dz = point[2] - cyl.AxisPoint[2];

            // Project onto axis direction
            double dot = dx * cyl.AxisDirection[0] + dy * cyl.AxisDirection[1] + dz * cyl.AxisDirection[2];

            // Perpendicular distance
            double px = dx - dot * cyl.AxisDirection[0];
            double py = dy - dot * cyl.AxisDirection[1];
            double pz = dz - dot * cyl.AxisDirection[2];

            return Math.Sqrt(px * px + py * py + pz * pz);
        }

        /// <summary>
        /// Infer pattern descriptors from hole instance locations.
        /// Analyzes collinearity, pitch, and symmetry for drawing comparison.
        /// </summary>
        private void InferPatternDescriptors(HoleGroup group)
        {
            if (group.Instances == null || group.Instances.Count < 2)
            {
                // Single hole - no pattern
                if (group.Pattern == null)
                    group.Pattern = new PatternInfo();
                group.Pattern.InferredArrangement = "Single";
                group.Pattern.InferenceConfidence = "High";
                return;
            }

            if (group.Pattern == null)
                group.Pattern = new PatternInfo();

            var centers = group.Instances
                .Where(i => i.Center != null)
                .Select(i => new double[] { i.Center.X, i.Center.Y, i.Center.Z })
                .ToList();

            if (centers.Count < 2)
                return;

            // 1. Check for collinearity (best-fit line)
            var collinearityResult = AnalyzeCollinearity(centers);
            group.Pattern.CollinearityFit = collinearityResult.R2;
            if (collinearityResult.IsCollinear)
            {
                group.Pattern.BestFitLineDirection = Vector3D.FromArray(collinearityResult.Direction);
                group.Pattern.InferredArrangement = "Linear";
            }

            // 2. Calculate pitch/spacing
            var pitchResult = AnalyzePitch(centers, collinearityResult.Direction);
            if (pitchResult.AvgPitch > 0)
            {
                group.Pattern.EstimatedPitch = DimensionValue.FromMeters(pitchResult.AvgPitch);
                group.Pattern.PitchIsUniform = pitchResult.IsUniform;
            }

            // 3. Check for symmetry
            var symmetryResult = AnalyzeSymmetry(centers);
            if (symmetryResult.HasSymmetry)
            {
                group.Pattern.SymmetryAxis = symmetryResult.Axis;
                group.Pattern.SymmetryPlaneOffset = DimensionValue.FromMeters(symmetryResult.PlaneOffset);
            }

            // 4. Determine overall confidence
            if (collinearityResult.IsCollinear && pitchResult.IsUniform)
                group.Pattern.InferenceConfidence = "High";
            else if (collinearityResult.IsCollinear || symmetryResult.HasSymmetry)
                group.Pattern.InferenceConfidence = "Medium";
            else
                group.Pattern.InferenceConfidence = "Low";

            // 5. Set inferred arrangement if not already set
            if (string.IsNullOrEmpty(group.Pattern.InferredArrangement))
            {
                if (symmetryResult.HasSymmetry && !collinearityResult.IsCollinear)
                    group.Pattern.InferredArrangement = "Symmetric";
                else if (centers.Count > 4 && !collinearityResult.IsCollinear)
                    group.Pattern.InferredArrangement = "Grid";
                else
                    group.Pattern.InferredArrangement = "Irregular";
            }
        }

        /// <summary>
        /// Analyze collinearity of points using least squares fit
        /// </summary>
        private (bool IsCollinear, double R2, double[] Direction) AnalyzeCollinearity(List<double[]> points)
        {
            if (points.Count < 2)
                return (false, 0, null);

            if (points.Count == 2)
            {
                // Two points are always collinear
                var dir = new double[]
                {
                    points[1][0] - points[0][0],
                    points[1][1] - points[0][1],
                    points[1][2] - points[0][2]
                };
                double len = Math.Sqrt(dir[0]*dir[0] + dir[1]*dir[1] + dir[2]*dir[2]);
                if (len > 0.0001)
                {
                    dir[0] /= len; dir[1] /= len; dir[2] /= len;
                }
                return (true, 1.0, dir);
            }

            // Calculate centroid
            double cx = points.Average(p => p[0]);
            double cy = points.Average(p => p[1]);
            double cz = points.Average(p => p[2]);

            // Find principal direction using simplified PCA (largest variance direction)
            // For simplicity, check variance along each axis and use 2D plane with most variance
            double varX = points.Sum(p => (p[0] - cx) * (p[0] - cx));
            double varY = points.Sum(p => (p[1] - cy) * (p[1] - cy));
            double varZ = points.Sum(p => (p[2] - cz) * (p[2] - cz));

            // Find primary direction (eigenvector of covariance)
            // Simplified: use direction from first to last point
            double dx = points.Last()[0] - points.First()[0];
            double dy = points.Last()[1] - points.First()[1];
            double dz = points.Last()[2] - points.First()[2];
            double dirLen = Math.Sqrt(dx*dx + dy*dy + dz*dz);
            if (dirLen < 0.0001)
                return (false, 0, null);

            double[] direction = { dx/dirLen, dy/dirLen, dz/dirLen };

            // Calculate R² (coefficient of determination)
            // Project points onto line and calculate residuals
            double ssRes = 0;  // Sum of squared residuals
            double ssTot = 0;  // Total sum of squares

            foreach (var pt in points)
            {
                // Vector from centroid to point
                double vx = pt[0] - cx;
                double vy = pt[1] - cy;
                double vz = pt[2] - cz;

                // Projection onto direction
                double proj = vx*direction[0] + vy*direction[1] + vz*direction[2];

                // Perpendicular distance (residual)
                double perpX = vx - proj*direction[0];
                double perpY = vy - proj*direction[1];
                double perpZ = vz - proj*direction[2];
                double residual = Math.Sqrt(perpX*perpX + perpY*perpY + perpZ*perpZ);

                ssRes += residual * residual;
                ssTot += vx*vx + vy*vy + vz*vz;
            }

            double r2 = ssTot > 0.0001 ? 1 - (ssRes / ssTot) : 0;

            // Consider collinear if R² > 0.95
            bool isCollinear = r2 > 0.95;

            return (isCollinear, r2, direction);
        }

        /// <summary>
        /// Analyze pitch/spacing between adjacent holes
        /// </summary>
        private (double AvgPitch, bool IsUniform) AnalyzePitch(List<double[]> points, double[] direction)
        {
            if (points.Count < 2)
                return (0, false);

            // Calculate distances between adjacent points
            var distances = new List<double>();

            if (direction != null)
            {
                // Sort points along the direction and calculate spacing
                var sortedPoints = points
                    .OrderBy(p => p[0]*direction[0] + p[1]*direction[1] + p[2]*direction[2])
                    .ToList();

                for (int i = 1; i < sortedPoints.Count; i++)
                {
                    double dx = sortedPoints[i][0] - sortedPoints[i-1][0];
                    double dy = sortedPoints[i][1] - sortedPoints[i-1][1];
                    double dz = sortedPoints[i][2] - sortedPoints[i-1][2];
                    distances.Add(Math.Sqrt(dx*dx + dy*dy + dz*dz));
                }
            }
            else
            {
                // No direction - just use sequential distances
                for (int i = 1; i < points.Count; i++)
                {
                    double dx = points[i][0] - points[i-1][0];
                    double dy = points[i][1] - points[i-1][1];
                    double dz = points[i][2] - points[i-1][2];
                    distances.Add(Math.Sqrt(dx*dx + dy*dy + dz*dz));
                }
            }

            if (distances.Count == 0)
                return (0, false);

            double avgPitch = distances.Average();
            double maxDev = distances.Max(d => Math.Abs(d - avgPitch));

            // Uniform if variation is less than 5%
            bool isUniform = avgPitch > 0 && (maxDev / avgPitch) < 0.05;

            return (avgPitch, isUniform);
        }

        /// <summary>
        /// Analyze symmetry about principal axes
        /// </summary>
        private (bool HasSymmetry, string Axis, double PlaneOffset) AnalyzeSymmetry(List<double[]> points)
        {
            if (points.Count < 2)
                return (false, null, 0);

            // Check symmetry about YZ plane (X=offset)
            double avgX = points.Average(p => p[0]);
            bool xSymmetric = CheckAxisSymmetry(points, 0, avgX);

            // Check symmetry about XZ plane (Y=offset)
            double avgY = points.Average(p => p[1]);
            bool ySymmetric = CheckAxisSymmetry(points, 1, avgY);

            // Check symmetry about XY plane (Z=offset)
            double avgZ = points.Average(p => p[2]);
            bool zSymmetric = CheckAxisSymmetry(points, 2, avgZ);

            // Return the most significant symmetry (prefer origin-centered)
            if (xSymmetric && Math.Abs(avgX) < 0.001)
                return (true, "X=0 (YZ plane)", avgX);
            if (ySymmetric && Math.Abs(avgY) < 0.001)
                return (true, "Y=0 (XZ plane)", avgY);
            if (zSymmetric && Math.Abs(avgZ) < 0.001)
                return (true, "Z=0 (XY plane)", avgZ);

            if (xSymmetric) return (true, $"X={avgX*1000:F1}mm", avgX);
            if (ySymmetric) return (true, $"Y={avgY*1000:F1}mm", avgY);
            if (zSymmetric) return (true, $"Z={avgZ*1000:F1}mm", avgZ);

            return (false, null, 0);
        }

        /// <summary>
        /// Check if points are symmetric about a plane perpendicular to given axis
        /// </summary>
        private bool CheckAxisSymmetry(List<double[]> points, int axisIndex, double planeOffset)
        {
            const double tolerance = 0.001;  // 1mm tolerance

            foreach (var pt in points)
            {
                // Calculate mirror position
                double mirroredCoord = 2 * planeOffset - pt[axisIndex];

                // Check if there's a matching point
                bool hasMatch = points.Any(other =>
                {
                    if (Math.Abs(other[axisIndex] - mirroredCoord) > tolerance)
                        return false;

                    // Check other coordinates match
                    for (int i = 0; i < 3; i++)
                    {
                        if (i != axisIndex && Math.Abs(other[i] - pt[i]) > tolerance)
                            return false;
                    }
                    return true;
                });

                if (!hasMatch && Math.Abs(pt[axisIndex] - planeOffset) > tolerance)
                    return false;  // Not on plane and no mirror
            }

            return true;
        }

        /// <summary>
        /// Calculate bolt circle diameter from hole instances
        /// </summary>
        private double CalculateBoltCircleDiameter(List<HoleInstance> instances)
        {
            if (instances.Count < 2)
                return 0;

            // Find centroid
            double cx = instances.Average(i => i.Center?.X ?? 0);
            double cy = instances.Average(i => i.Center?.Y ?? 0);
            double cz = instances.Average(i => i.Center?.Z ?? 0);

            // Average distance from centroid (radius)
            double avgRadius = instances.Average(i =>
            {
                if (i.Center == null) return 0;
                double dx = i.Center.X - cx;
                double dy = i.Center.Y - cy;
                double dz = i.Center.Z - cz;
                return Math.Sqrt(dx * dx + dy * dy + dz * dz);
            });

            return avgRadius * 2;  // Diameter
        }
    }
}
