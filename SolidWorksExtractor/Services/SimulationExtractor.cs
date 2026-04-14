using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.cosworks;

namespace SolidWorksExtractor.Services
{
    /// <summary>
    /// Extracts FEA simulation results from SolidWorks Simulation studies.
    /// Produces a stress-colored GLB with morph target deformation and a results JSON summary.
    ///
    /// Requirements:
    ///   - SolidWorks Premium or Simulation license
    ///   - At least one completed static study with saved results
    ///
    /// Output:
    ///   - {partNumber}_fea.glb:          Stress-colored surface mesh with morph target for deformation
    ///   - {partNumber}_fea_results.json: Summary metadata (max stress, displacement, material, safety factor)
    /// </summary>
    public class SimulationExtractor
    {
        // GLB constants (shared with GlbExporter but kept local to avoid coupling)
        private const uint GLB_MAGIC = 0x46546C67;       // "glTF"
        private const uint GLB_VERSION = 2;
        private const uint JSON_CHUNK_TYPE = 0x4E4F534A;  // "JSON"
        private const uint BIN_CHUNK_TYPE = 0x004E4942;   // "BIN\0"

        private const int ARRAY_BUFFER = 34962;
        private const int ELEMENT_ARRAY_BUFFER = 34963;
        private const int FLOAT = 5126;
        private const int UNSIGNED_BYTE = 5121;
        private const int UNSIGNED_SHORT = 5123;
        private const int UNSIGNED_INT = 5125;

        /// <summary>
        /// Holds the extracted FEA surface mesh and result data.
        /// </summary>
        private class FeaMeshData
        {
            public float[] Positions;       // Flattened XYZ of undeformed surface nodes
            public float[] Normals;         // Flattened XYZ surface normals
            public uint[] Indices;          // Triangle indices
            public byte[] VertexColors;     // RGBA bytes per vertex (stress heatmap)
            public float[] MorphPositions;  // Flattened XYZ of deformed surface nodes (morph target)
            public float[] MorphNormals;    // Flattened XYZ of deformed normals (morph target)
            public float[] BoundsMin;       // [minX, minY, minZ] undeformed
            public float[] BoundsMax;       // [maxX, maxY, maxZ] undeformed
            public float[] MorphBoundsMin;  // [minX, minY, minZ] morph delta min
            public float[] MorphBoundsMax;  // [maxX, maxY, maxZ] morph delta max
            public int VertexCount;
            public int TriangleCount;
            public int UniqueNodeCount;  // Deduplicated surface node count (for JSON summary)
        }

        /// <summary>
        /// Holds the summary metadata from the study.
        /// </summary>
        private class FeaResultsSummary
        {
            public string StudyName;
            public string StudyType;
            public int SurfaceNodeCount = 0;
            public int ElementCount = 0;
            public double MaxVonMisesMpa = 0;
            public double MaxDisplacementMm = 0;
            public double[] MaxStressLocation = new double[] { 0, 0, 0 };
            public double ReactionFx = 0;
            public double ReactionFy = 0;
            public double ReactionFz = 0;
            public string MaterialName = "";
            public double YieldStrengthMpa = 0;
            public double SafetyFactor = 0;
            public bool HasMorphTarget = false;
        }

        /// <summary>
        /// Extract FEA simulation results from the active part document.
        /// Finds the first completed static study, extracts surface mesh with stress colors
        /// and displacement morph target, then writes GLB and JSON files.
        /// </summary>
        /// <param name="swApp">SolidWorks application instance</param>
        /// <param name="modelDoc">Open part document</param>
        /// <param name="outputFolder">Directory to write output files</param>
        /// <param name="partNumber">Part number for output filenames</param>
        /// <returns>Path to the GLB file, or null on failure</returns>
        public string ExtractSimulation(ISldWorks swApp, IModelDoc2 modelDoc, string outputFolder, string partNumber)
        {
            if (swApp == null || modelDoc == null)
            {
                Console.WriteLine("    FEA Warning: No application or document for simulation extraction");
                return null;
            }

            if (!Directory.Exists(outputFolder))
                Directory.CreateDirectory(outputFolder);

            Console.WriteLine("    FEA: Accessing Simulation add-in...");

            // Access the Simulation add-in via IModelDocExtension
            object cosAddinObj = null;
            ICosmosWorks cosWorks = null;
            dynamic studyMgr = null;
            dynamic study = null;

            try
            {
                // Get the SOLIDWORKS Simulation (CosmosWorks) add-in
                cosAddinObj = swApp.GetAddInObject("SldWorks.Simulation");
                if (cosAddinObj == null)
                {
                    Console.WriteLine("    FEA Error: Could not access Simulation add-in. Is Simulation license active?");
                    return null;
                }

                // The add-in object exposes a CosmosWorks property; use dynamic for late-bound access
                cosWorks = (ICosmosWorks)((dynamic)cosAddinObj).CosmosWorks;
                if (cosWorks == null)
                {
                    Console.WriteLine("    FEA Error: Could not get CosmosWorks interface");
                    return null;
                }

                // Get the active document in Simulation context
                CWModelDoc cwDoc = (CWModelDoc)cosWorks.ActiveDoc;
                if (cwDoc == null)
                {
                    Console.WriteLine("    FEA Error: No active document in Simulation context");
                    return null;
                }

                studyMgr = ((dynamic)cwDoc).StudyManager;
                if (studyMgr == null)
                {
                    Console.WriteLine("    FEA Error: No study manager available");
                    return null;
                }

                int studyCount = studyMgr.StudyCount;
                Console.WriteLine($"    FEA: Found {studyCount} simulation studies");

                if (studyCount == 0)
                {
                    Console.WriteLine("    FEA Warning: No simulation studies found in this document");
                    return null;
                }

                // Find the first completed static study
                study = FindCompletedStaticStudy(studyMgr, studyCount);
                if (study == null)
                {
                    Console.WriteLine("    FEA Warning: No completed static study found");
                    return null;
                }

                string studyName = study.Name as string ?? "Unknown Study";
                Console.WriteLine($"    FEA: Using study '{studyName}'");

                // Extract study metadata
                var summary = ExtractStudyMetadata(study, studyName);

                // Extract surface mesh with stress and displacement data
                var meshData = ExtractResultMesh(study, summary);
                if (meshData == null)
                {
                    Console.WriteLine("    FEA Error: Failed to extract result mesh");
                    return null;
                }

                summary.SurfaceNodeCount = meshData.UniqueNodeCount > 0 ? meshData.UniqueNodeCount : meshData.VertexCount;
                summary.HasMorphTarget = meshData.MorphPositions != null && meshData.MorphPositions.Length > 0;

                // Compute safety factor
                if (summary.YieldStrengthMpa > 0 && summary.MaxVonMisesMpa > 0)
                {
                    summary.SafetyFactor = Math.Round(summary.YieldStrengthMpa / summary.MaxVonMisesMpa, 2);
                }

                Console.WriteLine($"    FEA: Surface mesh: {meshData.VertexCount:N0} vertices, {meshData.TriangleCount:N0} triangles");
                Console.WriteLine($"    FEA: Max von Mises: {summary.MaxVonMisesMpa:F3} MPa");
                Console.WriteLine($"    FEA: Max displacement: {summary.MaxDisplacementMm:F5} mm");
                Console.WriteLine($"    FEA: Material: {summary.MaterialName ?? "N/A"}, Yield: {summary.YieldStrengthMpa:F1} MPa");
                Console.WriteLine($"    FEA: Safety factor: {summary.SafetyFactor:F2}");
                Console.WriteLine($"    FEA: Morph target: {(summary.HasMorphTarget ? "yes" : "no")}");

                // Build and write GLB
                string glbPath = Path.Combine(outputFolder, partNumber + "_fea.glb");
                WriteFeaGlb(meshData, glbPath);
                long glbSizeKb = new FileInfo(glbPath).Length / 1024;
                Console.WriteLine($"    FEA: GLB written: {Path.GetFileName(glbPath)} ({glbSizeKb} KB)");

                // Write results JSON
                string jsonPath = Path.Combine(outputFolder, partNumber + "_fea_results.json");
                WriteFeaResultsJson(summary, jsonPath);
                Console.WriteLine($"    FEA: Results JSON written: {Path.GetFileName(jsonPath)}");

                return glbPath;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    FEA Error: {ex.Message}");
                Console.WriteLine($"    FEA Stack: {ex.StackTrace}");
                return null;
            }
            finally
            {
                // Release COM objects in reverse order
                SafeReleaseCom(study);
                SafeReleaseCom(studyMgr);
                SafeReleaseCom(cosWorks);
                SafeReleaseCom(cosAddinObj);
            }
        }

        /// <summary>
        /// Find the first completed static study in the study manager.
        /// Prefers studies that have results already computed.
        /// </summary>
        private dynamic FindCompletedStaticStudy(dynamic studyMgr, int studyCount)
        {
            for (int i = 0; i < studyCount; i++)
            {
                dynamic candidate = null;
                try
                {
                    candidate = studyMgr.GetStudy(i);
                    if (candidate == null) continue;

                    // Check if it's a static study
                    // swsAnalysisStudyType_e.swsAnalysisStudyTypeStatic = 0
                    int studyType = (int)candidate.AnalysisType;
                    if (studyType != 0)
                    {
                        Console.WriteLine($"    FEA: Skipping study '{candidate.Name}' (type={studyType}, not static)");
                        SafeReleaseCom(candidate);
                        continue;
                    }

                    // Check if results are available
                    // HasResults() returns 0 if no results, 1 if results exist
                    try
                    {
                        ICWResults results = (ICWResults)candidate.Results;
                        if (results == null)
                        {
                            Console.WriteLine($"    FEA: Study '{candidate.Name}' has no results object");
                            SafeReleaseCom(candidate);
                            continue;
                        }
                        SafeReleaseCom(results);
                    }
                    catch
                    {
                        Console.WriteLine($"    FEA: Study '{candidate.Name}' results not accessible");
                        SafeReleaseCom(candidate);
                        continue;
                    }

                    Console.WriteLine($"    FEA: Found completed static study '{candidate.Name}' at index {i}");
                    return candidate;
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"    FEA: Error accessing study {i}: {ex.Message}");
                    SafeReleaseCom(candidate);
                }
            }

            return null;
        }

        /// <summary>
        /// Extract study metadata: material, yield strength, mesh info, result extremes.
        /// </summary>
        private FeaResultsSummary ExtractStudyMetadata(dynamic study, string studyName)
        {
            var summary = new FeaResultsSummary
            {
                StudyName = studyName,
                StudyType = "static",
                MaxStressLocation = new double[] { 0, 0, 0 }
            };

            // Get mesh info
            try
            {
                ICWMesh mesh = (ICWMesh)study.Mesh;
                if (mesh != null)
                {
                    try
                    {
                        summary.ElementCount = ((dynamic)mesh).ElementCount;
                        Console.WriteLine($"    FEA: Mesh has {((dynamic)mesh).NodeCount:N0} nodes, {((dynamic)mesh).ElementCount:N0} elements");
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine($"    FEA Warning: Could not read mesh info: {ex.Message}");
                    }
                    finally
                    {
                        SafeReleaseCom(mesh);
                    }
                }
            }
            catch { /* mesh info is non-critical */ }

            // Get material properties from the study's solid component
            try
            {
                ICWSolidManager solidMgr = (ICWSolidManager)study.SolidManager;
                if (solidMgr != null)
                {
                    try
                    {
                        int solidCount = solidMgr.ComponentCount;
                        if (solidCount > 0)
                        {
                            int compErrCode = 0;
                            ICWSolidComponent solidComp = (ICWSolidComponent)solidMgr.GetComponentAt(0, out compErrCode);
                            if (solidComp != null)
                            {
                                try
                                {
                                    int bodyErr = 0;
                                    CWSolidBody solidBody = (CWSolidBody)solidComp.GetSolidBodyAt(0, out bodyErr);
                                    if (solidBody != null)
                                    {
                                        try
                                        {
                                            ICWMaterial material = (ICWMaterial)((dynamic)solidBody).GetSolidBodyMaterial();
                                            if (material != null)
                                            {
                                                try
                                                {
                                                    summary.MaterialName = ((dynamic)material).MaterialName as string;

                                                    // Yield strength in SI (Pa) — convert to MPa
                                                    // GetPropertyByName(int NUnit, string SName, out int BTempDependent) -> double
                                                    int tempDependent = 0;
                                                    double yieldPa = material.GetPropertyByName(
                                                        (int)swsLinearUnit_e.swsLinearUnitMeters,
                                                        "SIGYLD",
                                                        out tempDependent);
                                                    if (yieldPa > 0)
                                                        summary.YieldStrengthMpa = yieldPa / 1e6;
                                                }
                                                catch (Exception ex)
                                                {
                                                    Console.WriteLine($"    FEA Warning: Could not read material properties: {ex.Message}");
                                                }
                                                finally
                                                {
                                                    SafeReleaseCom(material);
                                                }
                                            }
                                        }
                                        finally
                                        {
                                            SafeReleaseCom(solidBody);
                                        }
                                    }
                                }
                                finally
                                {
                                    SafeReleaseCom(solidComp);
                                }
                            }
                        }
                    }
                    finally
                    {
                        SafeReleaseCom(solidMgr);
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    FEA Warning: Could not extract material info: {ex.Message}");
            }

            // Get result extremes (max von Mises, max displacement, reaction forces)
            try
            {
                ICWResults results = (ICWResults)study.Results;
                if (results != null)
                {
                    try
                    {
                        ExtractResultExtremes(results, summary);
                    }
                    finally
                    {
                        SafeReleaseCom(results);
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    FEA Warning: Could not extract result extremes: {ex.Message}");
            }

            return summary;
        }

        /// <summary>
        /// Extract max stress, max displacement, and reaction forces from ICWResults.
        /// </summary>
        private void ExtractResultExtremes(ICWResults results, FeaResultsSummary summary)
        {
            // Get max von Mises stress
            // GetMinMaxStress(NComponent, NElementNumber, NStepNum, DispPlane, NUnits, out ErrorCode)
            // NComponent: swsStressComponentVON = 9
            // NElementNumber: 0 = all elements
            // NStepNum: 0 for static (last step)
            // DispPlane: null
            // NUnits: 0 = N/m^2 (Pa)
            try
            {
                int errCode = 0;
                object stressResult = results.GetMinMaxStress(
                    (int)swsStressComponent_e.swsStressComponentVON,
                    0,  // all elements
                    0,  // step number (0 for static)
                    null, // ref plane (null = global)
                    0,  // units: 0 = N/m^2 (Pa)
                    out errCode);

                if (errCode == 0 && stressResult != null)
                {
                    double[] stressValues = (double[])stressResult;
                    // stressValues[0] = min, stressValues[1] = max
                    if (stressValues.Length >= 2)
                    {
                        summary.MaxVonMisesMpa = stressValues[1] / 1e6;  // Pa to MPa
                    }
                }
                else
                {
                    Console.WriteLine($"    FEA Warning: GetMinMaxStress returned error code {errCode}");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    FEA Warning: Could not get max von Mises: {ex.Message}");
            }

            // Get max displacement
            // GetMinMaxDisplacement(NComponent, NStepNumber, DispPlane, NUnits, out ErrorCode)
            try
            {
                int errCode = 0;
                object dispResult = results.GetMinMaxDisplacement(
                    (int)swsDisplacementComponent_e.swsDisplacementComponentURES,
                    0,  // step number
                    null, // ref plane
                    (int)swsLinearUnit_e.swsLinearUnitMeters,
                    out errCode);

                if (errCode == 0 && dispResult != null)
                {
                    double[] dispValues = (double[])dispResult;
                    if (dispValues.Length >= 2)
                    {
                        summary.MaxDisplacementMm = dispValues[1] * 1000.0;  // meters to mm
                    }
                }
                else
                {
                    Console.WriteLine($"    FEA Warning: GetMinMaxDisplacement returned error code {errCode}");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    FEA Warning: Could not get max displacement: {ex.Message}");
            }

            // Get reaction forces
            // GetReactionForcesAndMoments(NStepNumber, DispPlane, NUnits, out ErrorCode)
            try
            {
                int errCode = 0;
                object reactionResult = results.GetReactionForcesAndMoments(
                    0,  // step number
                    null, // ref plane
                    (int)swsForceUnit_e.swsForceUnitNOrNm,
                    out errCode);

                if (errCode == 0 && reactionResult != null)
                {
                    double[] reactionValues = (double[])reactionResult;
                    // The reaction force array layout varies; typically [Fx, Fy, Fz, ...]
                    if (reactionValues.Length >= 3)
                    {
                        summary.ReactionFx = Math.Round(reactionValues[0], 2);
                        summary.ReactionFy = Math.Round(reactionValues[1], 2);
                        summary.ReactionFz = Math.Round(reactionValues[2], 2);
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    FEA Warning: Could not get reaction forces: {ex.Message}");
            }
        }

        /// <summary>
        /// Extract the solver's result mesh (surface triangles with nodal stress and displacement).
        /// Uses ICWMesh to get surface nodes and builds surface triangles from element connectivity.
        /// Maps per-element stress values onto surface nodes for vertex coloring.
        /// </summary>
        private FeaMeshData ExtractResultMesh(dynamic study, FeaResultsSummary summary)
        {
            // The installed COSMOSWorks interop does not expose ICWPlot.GetTriangleArray()
            // or GetResult() for direct mesh extraction from plots. Instead, we use the
            // node-based approach: read all nodes/elements from ICWMesh, extract the
            // surface boundary, and map element stress values onto surface nodes.
            return ExtractResultMeshFromNodes(study, summary);
        }

        /// <summary>
        /// Fallback: Extract mesh from the FE node/element data directly.
        /// This path is used when ICWPlot.GetTriangleArray() is not available.
        /// It reads all nodes and elements, extracts the surface boundary, then maps
        /// nodal results onto surface vertices.
        /// </summary>
        private FeaMeshData ExtractResultMeshFromNodes(dynamic study, FeaResultsSummary summary)
        {
            Console.WriteLine("    FEA: Using node-based mesh extraction...");

            ICWMesh mesh = null;
            ICWResults results = null;
            try
            {
                mesh = (ICWMesh)study.Mesh;
                results = (ICWResults)study.Results;

                if (mesh == null)
                {
                    Console.WriteLine("    FEA Error: No mesh object available");
                    return null;
                }

                int nodeCount = ((dynamic)mesh).NodeCount;
                int elemCount = ((dynamic)mesh).ElementCount;
                Console.WriteLine($"    FEA: FE mesh: {nodeCount:N0} nodes, {elemCount:N0} elements");

                if (nodeCount == 0 || elemCount == 0)
                {
                    Console.WriteLine("    FEA Error: Empty mesh");
                    return null;
                }

                // Read all node positions using GetNodeLocation (1-based node IDs)
                // GetNodeLocation(int NNodeNo, out double XVal, out double YVal, out double ZVal) -> int
                double[] nodeX = new double[nodeCount + 1]; // +1 for 1-based indexing
                double[] nodeY = new double[nodeCount + 1];
                double[] nodeZ = new double[nodeCount + 1];

                for (int i = 1; i <= nodeCount; i++)
                {
                    try
                    {
                        double xVal = 0, yVal = 0, zVal = 0;
                        int locErr = mesh.GetNodeLocation(i, out xVal, out yVal, out zVal);
                        if (locErr == 0)
                        {
                            nodeX[i] = xVal;
                            nodeY[i] = yVal;
                            nodeZ[i] = zVal;
                        }
                    }
                    catch { /* skip node */ }
                }

                // Read element connectivity and find surface faces
                // GetConnectivity returns all element connectivity as a flat array
                // For tet4: each element has 4 nodes, forming 4 triangular faces
                // A face that appears in exactly one element is on the surface boundary
                Console.WriteLine("    FEA: Extracting surface boundary from tet mesh...");
                var faceCount = new Dictionary<long, int>();  // canonical face key -> count
                var faceNodes = new Dictionary<long, int[]>(); // canonical face key -> [n0, n1, n2]

                // Try bulk connectivity first, fall back to per-element
                int connectErr = 0;
                object connectData = mesh.GetConnectivity(out connectErr);
                int[] allConnectivity = ConvertToIntArray(connectData);

                if (allConnectivity != null && allConnectivity.Length >= 4)
                {
                    // Connectivity is a flat array: [nodesPerElem, n0, n1, n2, n3, nodesPerElem, n0, n1, n2, n3, ...]
                    // or just [n0, n1, n2, n3, n0, n1, n2, n3, ...] with fixed stride
                    // Detect stride: if first entry is 4, it's a header-based format
                    int stride = 4; // assume tet4 corner nodes
                    int offset = 0;
                    if (allConnectivity.Length > 0 && allConnectivity[0] == 4)
                    {
                        stride = 5; // 4 nodes + 1 header per element
                        offset = 1; // skip the header
                    }
                    else if (allConnectivity.Length > 0 && allConnectivity[0] == 10)
                    {
                        stride = 11; // 10 nodes + 1 header per element (tet10)
                        offset = 1;
                    }

                    int connElemCount = allConnectivity.Length / stride;
                    for (int e = 0; e < connElemCount; e++)
                    {
                        int baseIdx = e * stride + offset;
                        if (baseIdx + 3 >= allConnectivity.Length) break;

                        int n0 = allConnectivity[baseIdx];
                        int n1 = allConnectivity[baseIdx + 1];
                        int n2 = allConnectivity[baseIdx + 2];
                        int n3 = allConnectivity[baseIdx + 3];

                        AddFace(faceCount, faceNodes, n0, n1, n2);
                        AddFace(faceCount, faceNodes, n0, n1, n3);
                        AddFace(faceCount, faceNodes, n0, n2, n3);
                        AddFace(faceCount, faceNodes, n1, n2, n3);
                    }
                }
                else
                {
                    // Fallback: use GetElements() bulk array
                    object elemBulk = mesh.GetElements();
                    int[] elemArray = ConvertToIntArray(elemBulk);
                    if (elemArray == null || elemArray.Length < 4)
                    {
                        Console.WriteLine("    FEA Error: Could not read element connectivity");
                        return null;
                    }

                    // Same stride detection
                    int stride = 4;
                    int offset2 = 0;
                    if (elemArray[0] == 4) { stride = 5; offset2 = 1; }
                    else if (elemArray[0] == 10) { stride = 11; offset2 = 1; }

                    int bulkElemCount = elemArray.Length / stride;
                    for (int e = 0; e < bulkElemCount; e++)
                    {
                        int baseIdx = e * stride + offset2;
                        if (baseIdx + 3 >= elemArray.Length) break;

                        int n0 = elemArray[baseIdx];
                        int n1 = elemArray[baseIdx + 1];
                        int n2 = elemArray[baseIdx + 2];
                        int n3 = elemArray[baseIdx + 3];

                        AddFace(faceCount, faceNodes, n0, n1, n2);
                        AddFace(faceCount, faceNodes, n0, n1, n3);
                        AddFace(faceCount, faceNodes, n0, n2, n3);
                        AddFace(faceCount, faceNodes, n1, n2, n3);
                    }
                }

                // Also try GetSurfaceNodesAndNormals for identifying surface node set
                HashSet<int> surfaceNodeHint = null;
                try
                {
                    object varNodeIDs = null, varNumNormals = null, varNormalVecs = null;
                    int surfErr = mesh.GetSurfaceNodesAndNormals(out varNodeIDs, out varNumNormals, out varNormalVecs);
                    if (surfErr == 0 && varNodeIDs != null)
                    {
                        int[] surfNodeIds = ConvertToIntArray(varNodeIDs);
                        if (surfNodeIds != null && surfNodeIds.Length > 0)
                        {
                            surfaceNodeHint = new HashSet<int>(surfNodeIds);
                            Console.WriteLine($"    FEA: GetSurfaceNodesAndNormals returned {surfaceNodeHint.Count:N0} surface nodes");
                        }
                    }
                }
                catch { /* surface node hint is optional */ }

                if (faceCount.Count == 0)
                {
                    Console.WriteLine("    FEA Error: No elements processed");
                    return null;
                }

                // Surface faces appear exactly once
                var surfaceFaces = new List<int[]>();
                foreach (var kvp in faceCount)
                {
                    if (kvp.Value == 1)
                    {
                        surfaceFaces.Add(faceNodes[kvp.Key]);
                    }
                }

                Console.WriteLine($"    FEA: Found {surfaceFaces.Count:N0} surface faces");

                if (surfaceFaces.Count == 0)
                {
                    Console.WriteLine("    FEA Error: No surface faces found");
                    return null;
                }

                // Collect unique surface node IDs and build index remapping
                var surfaceNodeSet = new HashSet<int>();
                foreach (var face in surfaceFaces)
                {
                    surfaceNodeSet.Add(face[0]);
                    surfaceNodeSet.Add(face[1]);
                    surfaceNodeSet.Add(face[2]);
                }

                var surfaceNodes = new List<int>(surfaceNodeSet);
                surfaceNodes.Sort();
                var nodeRemap = new Dictionary<int, int>();
                for (int i = 0; i < surfaceNodes.Count; i++)
                    nodeRemap[surfaceNodes[i]] = i;

                int surfVertCount = surfaceNodes.Count;
                Console.WriteLine($"    FEA: {surfVertCount:N0} surface nodes ({(100.0 * surfVertCount / nodeCount):F1}% of total)");

                // Build position array for surface nodes
                float[] posArray = new float[surfVertCount * 3];
                for (int i = 0; i < surfVertCount; i++)
                {
                    int nid = surfaceNodes[i];
                    posArray[i * 3 + 0] = (float)nodeX[nid];
                    posArray[i * 3 + 1] = (float)nodeY[nid];
                    posArray[i * 3 + 2] = (float)nodeZ[nid];
                }

                // Build index array
                uint[] indices = new uint[surfaceFaces.Count * 3];
                for (int i = 0; i < surfaceFaces.Count; i++)
                {
                    indices[i * 3 + 0] = (uint)nodeRemap[surfaceFaces[i][0]];
                    indices[i * 3 + 1] = (uint)nodeRemap[surfaceFaces[i][1]];
                    indices[i * 3 + 2] = (uint)nodeRemap[surfaceFaces[i][2]];
                }

                // Compute normals from face geometry
                float[] normArray = ComputeVertexNormals(posArray, indices, surfVertCount);

                // Get nodal von Mises stress for surface nodes
                double[] stressValues = new double[surfVertCount];
                double maxStress = 0;
                int peakIdx = 0;

                if (results != null)
                {
                    // The API does not have GetNodalStress(); use per-element GetStress()
                    // to get element stress and average at shared nodes.
                    // GetStress(NElementNumber, NStepNum, DispPlane, NUnits, out ErrorCode)
                    // returns array of stress components for that element.
                    // We build a node stress accumulator from elements that touch surface nodes.
                    try
                    {
                        // Build reverse map: surfaceNodeId -> list of element indices that contain it
                        // Since we have surface faces, we can query stress for a representative
                        // element per face, then spread to its nodes.
                        // Simpler approach: query stress for elements 1..elemCount, and for each
                        // element whose corner nodes are in surfaceNodeSet, accumulate at those nodes.
                        // This is expensive for large meshes, so we limit to surface-adjacent elements.
                        var nodeStressSum = new Dictionary<int, double>();
                        var nodeStressCount = new Dictionary<int, int>();

                        // Initialize for surface nodes
                        foreach (int nid in surfaceNodeSet)
                        {
                            nodeStressSum[nid] = 0.0;
                            nodeStressCount[nid] = 0;
                        }

                        // Re-read connectivity to find elements touching surface nodes
                        // We already have bulk connectivity above; re-iterate elements
                        int connErr2 = 0;
                        object connData2 = mesh.GetConnectivity(out connErr2);
                        int[] conn2 = ConvertToIntArray(connData2);
                        if (conn2 == null) conn2 = ConvertToIntArray(mesh.GetElements());

                        if (conn2 != null && conn2.Length >= 4)
                        {
                            int stride2 = 4;
                            int off2 = 0;
                            if (conn2[0] == 4) { stride2 = 5; off2 = 1; }
                            else if (conn2[0] == 10) { stride2 = 11; off2 = 1; }

                            int numElems = conn2.Length / stride2;
                            for (int e = 0; e < numElems; e++)
                            {
                                int bi = e * stride2 + off2;
                                if (bi + 3 >= conn2.Length) break;

                                int en0 = conn2[bi], en1 = conn2[bi + 1], en2 = conn2[bi + 2], en3 = conn2[bi + 3];

                                // Only process elements that have at least one surface node
                                bool hasSurf = surfaceNodeSet.Contains(en0) || surfaceNodeSet.Contains(en1)
                                            || surfaceNodeSet.Contains(en2) || surfaceNodeSet.Contains(en3);
                                if (!hasSurf) continue;

                                try
                                {
                                    int sErrCode = 0;
                                    // Element numbers are 1-based
                                    object stressData = results.GetStress(e + 1, 0, null, 0, out sErrCode);
                                    if (sErrCode == 0 && stressData != null)
                                    {
                                        double[] sVals = stressData as double[];
                                        if (sVals != null && sVals.Length > 0)
                                        {
                                            // GetStress returns [SX, SY, SZ, TXY, TXZ, TYZ, P1, P2, P3, VON, INT, ...]
                                            // VON is at index 9 (matching swsStressComponentVON)
                                            double vonMises = sVals.Length > 9 ? sVals[9] : sVals[0];

                                            // Distribute to surface nodes of this element
                                            foreach (int nid in new[] { en0, en1, en2, en3 })
                                            {
                                                if (surfaceNodeSet.Contains(nid))
                                                {
                                                    nodeStressSum[nid] += vonMises;
                                                    nodeStressCount[nid]++;
                                                }
                                            }
                                        }
                                    }
                                }
                                catch { /* skip element */ }
                            }
                        }

                        // Map averaged stress to surface vertices
                        for (int i = 0; i < surfVertCount; i++)
                        {
                            int nid = surfaceNodes[i];
                            if (nodeStressCount.ContainsKey(nid) && nodeStressCount[nid] > 0)
                            {
                                stressValues[i] = nodeStressSum[nid] / nodeStressCount[nid];
                                if (Math.Abs(stressValues[i]) > maxStress)
                                {
                                    maxStress = Math.Abs(stressValues[i]);
                                    peakIdx = i;
                                }
                            }
                        }

                        Console.WriteLine($"    FEA: Per-element stress mapped to {surfVertCount:N0} surface nodes");
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine($"    FEA Warning: Error reading element stress: {ex.Message}");
                    }
                }

                // Update max stress location
                if (maxStress > 0 && peakIdx < surfVertCount)
                {
                    int nid = surfaceNodes[peakIdx];
                    summary.MaxStressLocation = new double[] { nodeX[nid], nodeY[nid], nodeZ[nid] };
                    summary.MaxVonMisesMpa = maxStress / 1e6;
                }

                // Map stress to vertex colors
                byte[] vertexColors = MapStressToColors(stressValues, surfVertCount, maxStress > 0 ? maxStress : 1.0);

                // Get nodal displacements for morph target
                float[] morphPositions = null;
                float[] morphNormals = null;
                float[] morphBoundsMin = null;
                float[] morphBoundsMax = null;

                try
                {
                    double[] dispXArr = new double[surfVertCount];
                    double[] dispYArr = new double[surfVertCount];
                    double[] dispZArr = new double[surfVertCount];
                    bool hasDisp = false;

                    // GetTranslationalDisplacement returns all nodal displacements at once
                    // Signature: (NStepNumber, DispPlane, NUnits, out ErrorCode) -> object
                    // Returns a flat array of [UX1, UY1, UZ1, UX2, UY2, UZ2, ...] for all nodes
                    try
                    {
                        int dispErrCode = 0;
                        object dispBulk = results.GetTranslationalDisplacement(
                            0, // step
                            null, // ref plane
                            (int)swsLinearUnit_e.swsLinearUnitMeters,
                            out dispErrCode);

                        if (dispErrCode == 0 && dispBulk != null)
                        {
                            double[] allDisp = dispBulk as double[];
                            if (allDisp != null)
                            {
                                // allDisp is indexed by node: allDisp[(nodeId-1)*3 + component]
                                // nodeIds are 1-based
                                for (int i = 0; i < surfVertCount; i++)
                                {
                                    int nid = surfaceNodes[i];
                                    int dIdx = (nid - 1) * 3;
                                    if (dIdx + 2 < allDisp.Length)
                                    {
                                        dispXArr[i] = allDisp[dIdx];
                                        dispYArr[i] = allDisp[dIdx + 1];
                                        dispZArr[i] = allDisp[dIdx + 2];
                                        hasDisp = true;
                                    }
                                }
                            }
                        }
                    }
                    catch (Exception dispEx)
                    {
                        Console.WriteLine($"    FEA Warning: GetTranslationalDisplacement failed: {dispEx.Message}");
                    }

                    if (hasDisp)
                    {
                        // Morph target stores DELTA positions (deformed - undeformed)
                        morphPositions = new float[surfVertCount * 3];
                        float mMinX = float.MaxValue, mMinY = float.MaxValue, mMinZ = float.MaxValue;
                        float mMaxX = float.MinValue, mMaxY = float.MinValue, mMaxZ = float.MinValue;

                        for (int i = 0; i < surfVertCount; i++)
                        {
                            float dx = (float)dispXArr[i];
                            float dy = (float)dispYArr[i];
                            float dz = (float)dispZArr[i];
                            morphPositions[i * 3 + 0] = dx;
                            morphPositions[i * 3 + 1] = dy;
                            morphPositions[i * 3 + 2] = dz;

                            if (dx < mMinX) mMinX = dx; if (dx > mMaxX) mMaxX = dx;
                            if (dy < mMinY) mMinY = dy; if (dy > mMaxY) mMaxY = dy;
                            if (dz < mMinZ) mMinZ = dz; if (dz > mMaxZ) mMaxZ = dz;
                        }

                        morphBoundsMin = new float[] { mMinX, mMinY, mMinZ };
                        morphBoundsMax = new float[] { mMaxX, mMaxY, mMaxZ };

                        // Compute morph normal deltas
                        // Build deformed positions for normal computation
                        float[] deformedPos = new float[surfVertCount * 3];
                        for (int i = 0; i < surfVertCount * 3; i++)
                            deformedPos[i] = posArray[i] + morphPositions[i];

                        float[] deformedNormals = ComputeVertexNormals(deformedPos, indices, surfVertCount);
                        morphNormals = new float[deformedNormals.Length];
                        for (int i = 0; i < deformedNormals.Length; i++)
                            morphNormals[i] = deformedNormals[i] - normArray[i];

                        Console.WriteLine("    FEA: Displacement morph target extracted");
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"    FEA Warning: Could not extract displacement morph: {ex.Message}");
                }

                // Compute bounding box
                float bbMinX = float.MaxValue, bbMinY = float.MaxValue, bbMinZ = float.MaxValue;
                float bbMaxX = float.MinValue, bbMaxY = float.MinValue, bbMaxZ = float.MinValue;
                for (int i = 0; i < posArray.Length; i += 3)
                {
                    if (posArray[i] < bbMinX) bbMinX = posArray[i];
                    if (posArray[i] > bbMaxX) bbMaxX = posArray[i];
                    if (posArray[i + 1] < bbMinY) bbMinY = posArray[i + 1];
                    if (posArray[i + 1] > bbMaxY) bbMaxY = posArray[i + 1];
                    if (posArray[i + 2] < bbMinZ) bbMinZ = posArray[i + 2];
                    if (posArray[i + 2] > bbMaxZ) bbMaxZ = posArray[i + 2];
                }

                return new FeaMeshData
                {
                    Positions = posArray,
                    Normals = normArray,
                    Indices = indices,
                    VertexColors = vertexColors,
                    MorphPositions = morphPositions,
                    MorphNormals = morphNormals,
                    BoundsMin = new float[] { bbMinX, bbMinY, bbMinZ },
                    BoundsMax = new float[] { bbMaxX, bbMaxY, bbMaxZ },
                    MorphBoundsMin = morphBoundsMin,
                    MorphBoundsMax = morphBoundsMax,
                    VertexCount = surfVertCount,
                    TriangleCount = surfaceFaces.Count,
                    UniqueNodeCount = surfVertCount
                };
            }
            finally
            {
                SafeReleaseCom(results);
                SafeReleaseCom(mesh);
            }
        }

        /// <summary>
        /// Map stress values to RGBA vertex colors using the standard FEA heatmap:
        /// Blue (0%) -> Cyan (25%) -> Green (50%) -> Yellow (75%) -> Red (100%)
        /// </summary>
        private byte[] MapStressToColors(double[] stressValues, int vertexCount, double maxStress)
        {
            byte[] colors = new byte[vertexCount * 4]; // RGBA

            for (int i = 0; i < vertexCount; i++)
            {
                double normalized = Math.Abs(stressValues[i]) / maxStress;
                normalized = Math.Max(0.0, Math.Min(1.0, normalized)); // clamp [0, 1]

                byte r, g, b;
                StressToRgb(normalized, out r, out g, out b);

                colors[i * 4 + 0] = r;
                colors[i * 4 + 1] = g;
                colors[i * 4 + 2] = b;
                colors[i * 4 + 3] = 255;
            }

            return colors;
        }

        /// <summary>
        /// Convert a normalized stress value [0..1] to RGB using a 5-stop gradient:
        ///   0.00 = Blue    (0,   0,   255)
        ///   0.25 = Cyan    (0,   255, 255)
        ///   0.50 = Green   (0,   255, 0)
        ///   0.75 = Yellow  (255, 255, 0)
        ///   1.00 = Red     (255, 0,   0)
        /// </summary>
        private void StressToRgb(double t, out byte r, out byte g, out byte b)
        {
            if (t <= 0.0)
            {
                r = 0; g = 0; b = 255;
            }
            else if (t <= 0.25)
            {
                // Blue -> Cyan: increase green
                double f = t / 0.25;
                r = 0;
                g = (byte)(255 * f);
                b = 255;
            }
            else if (t <= 0.50)
            {
                // Cyan -> Green: decrease blue
                double f = (t - 0.25) / 0.25;
                r = 0;
                g = 255;
                b = (byte)(255 * (1.0 - f));
            }
            else if (t <= 0.75)
            {
                // Green -> Yellow: increase red
                double f = (t - 0.50) / 0.25;
                r = (byte)(255 * f);
                g = 255;
                b = 0;
            }
            else if (t < 1.0)
            {
                // Yellow -> Red: decrease green
                double f = (t - 0.75) / 0.25;
                r = 255;
                g = (byte)(255 * (1.0 - f));
                b = 0;
            }
            else
            {
                r = 255; g = 0; b = 0;
            }
        }

        /// <summary>
        /// Compute face normals for a triangle list (3 vertices per triangle, sequential).
        /// Returns per-vertex normals (flat shading — each triangle's 3 vertices share the face normal).
        /// </summary>
        private float[] ComputeFaceNormals(float[] positions, int vertexCount)
        {
            float[] normals = new float[vertexCount * 3];

            for (int tri = 0; tri < vertexCount / 3; tri++)
            {
                int i0 = tri * 3;
                int i1 = i0 + 1;
                int i2 = i0 + 2;

                float ax = positions[i1 * 3 + 0] - positions[i0 * 3 + 0];
                float ay = positions[i1 * 3 + 1] - positions[i0 * 3 + 1];
                float az = positions[i1 * 3 + 2] - positions[i0 * 3 + 2];

                float bx = positions[i2 * 3 + 0] - positions[i0 * 3 + 0];
                float by = positions[i2 * 3 + 1] - positions[i0 * 3 + 1];
                float bz = positions[i2 * 3 + 2] - positions[i0 * 3 + 2];

                float nx = ay * bz - az * by;
                float ny = az * bx - ax * bz;
                float nz = ax * by - ay * bx;

                float len = (float)Math.Sqrt(nx * nx + ny * ny + nz * nz);
                if (len > 1e-10f)
                {
                    nx /= len; ny /= len; nz /= len;
                }
                else
                {
                    nx = 0f; ny = 1f; nz = 0f;
                }

                // Assign same normal to all 3 vertices of this triangle
                normals[i0 * 3 + 0] = nx; normals[i0 * 3 + 1] = ny; normals[i0 * 3 + 2] = nz;
                normals[i1 * 3 + 0] = nx; normals[i1 * 3 + 1] = ny; normals[i1 * 3 + 2] = nz;
                normals[i2 * 3 + 0] = nx; normals[i2 * 3 + 1] = ny; normals[i2 * 3 + 2] = nz;
            }

            return normals;
        }

        /// <summary>
        /// Compute smooth vertex normals by averaging face normals of adjacent triangles.
        /// Used when mesh has indexed triangles (not sequential triangle list).
        /// </summary>
        private float[] ComputeVertexNormals(float[] positions, uint[] indices, int vertexCount)
        {
            float[] normals = new float[vertexCount * 3];

            // Accumulate face normals at each vertex
            for (int tri = 0; tri < indices.Length / 3; tri++)
            {
                uint i0 = indices[tri * 3 + 0];
                uint i1 = indices[tri * 3 + 1];
                uint i2 = indices[tri * 3 + 2];

                float ax = positions[i1 * 3 + 0] - positions[i0 * 3 + 0];
                float ay = positions[i1 * 3 + 1] - positions[i0 * 3 + 1];
                float az = positions[i1 * 3 + 2] - positions[i0 * 3 + 2];

                float bx = positions[i2 * 3 + 0] - positions[i0 * 3 + 0];
                float by = positions[i2 * 3 + 1] - positions[i0 * 3 + 1];
                float bz = positions[i2 * 3 + 2] - positions[i0 * 3 + 2];

                float nx = ay * bz - az * by;
                float ny = az * bx - ax * bz;
                float nz = ax * by - ay * bx;

                // Don't normalize yet — area-weighted accumulation
                normals[i0 * 3 + 0] += nx; normals[i0 * 3 + 1] += ny; normals[i0 * 3 + 2] += nz;
                normals[i1 * 3 + 0] += nx; normals[i1 * 3 + 1] += ny; normals[i1 * 3 + 2] += nz;
                normals[i2 * 3 + 0] += nx; normals[i2 * 3 + 1] += ny; normals[i2 * 3 + 2] += nz;
            }

            // Normalize all vertex normals
            for (int i = 0; i < vertexCount; i++)
            {
                float nx = normals[i * 3 + 0];
                float ny = normals[i * 3 + 1];
                float nz = normals[i * 3 + 2];
                float len = (float)Math.Sqrt(nx * nx + ny * ny + nz * nz);
                if (len > 1e-10f)
                {
                    normals[i * 3 + 0] = nx / len;
                    normals[i * 3 + 1] = ny / len;
                    normals[i * 3 + 2] = nz / len;
                }
                else
                {
                    normals[i * 3 + 0] = 0f;
                    normals[i * 3 + 1] = 1f;
                    normals[i * 3 + 2] = 0f;
                }
            }

            return normals;
        }

        /// <summary>
        /// Build a canonical key for a triangle face from 3 node IDs.
        /// Sorts the IDs and packs into a single long for fast hashing.
        /// </summary>
        private void AddFace(Dictionary<long, int> faceCount, Dictionary<long, int[]> faceNodes,
            int n0, int n1, int n2)
        {
            // Sort the three node IDs
            int a = n0, b = n1, c = n2;
            if (a > b) { int t = a; a = b; b = t; }
            if (b > c) { int t = b; b = c; c = t; }
            if (a > b) { int t = a; a = b; b = t; }

            // Pack into a long: a * 10^12 + b * 10^6 + c
            // Assumes node IDs < 1,000,000 (safe for typical FEA meshes)
            long key = (long)a * 1000000L * 1000000L + (long)b * 1000000L + (long)c;

            if (faceCount.ContainsKey(key))
            {
                faceCount[key]++;
            }
            else
            {
                faceCount[key] = 1;
                faceNodes[key] = new int[] { n0, n1, n2 }; // preserve original winding
            }
        }

        // --- GLB Output ---

        /// <summary>
        /// Write the FEA mesh as a GLB file with vertex colors and optional morph target.
        ///
        /// Buffer layout per mesh (single mesh):
        ///   BufferView 0: Positions (float32 VEC3)
        ///   BufferView 1: Normals (float32 VEC3)
        ///   BufferView 2: Vertex colors (uint8 VEC4, normalized)
        ///   BufferView 3: Indices (uint16 or uint32)
        ///   BufferView 4: Morph target positions (float32 VEC3) — if morph target present
        ///   BufferView 5: Morph target normals (float32 VEC3) — if morph target present
        /// </summary>
        private void WriteFeaGlb(FeaMeshData mesh, string outputPath)
        {
            bool hasMorph = mesh.MorphPositions != null && mesh.MorphPositions.Length > 0;
            bool useUint32 = mesh.VertexCount >= 65536;

            // Build binary buffer
            byte[] binData;
            int posViewIdx, normViewIdx, colorViewIdx, idxViewIdx;
            int morphPosViewIdx = -1, morphNormViewIdx = -1;
            int posAccessorIdx, normAccessorIdx, colorAccessorIdx, idxAccessorIdx;
            int morphPosAccessorIdx = -1, morphNormAccessorIdx = -1;
            int totalBufferViews, totalAccessors;

            using (var ms = new MemoryStream())
            using (var bw = new BinaryWriter(ms))
            {
                int bvIndex = 0;
                int accessorIndex = 0;

                // --- BufferView 0: Positions ---
                int posOffset = (int)ms.Position;
                for (int i = 0; i < mesh.Positions.Length; i++)
                    bw.Write(mesh.Positions[i]);
                int posLength = (int)ms.Position - posOffset;
                PadToAlignment(bw, ms, 4);
                posViewIdx = bvIndex++;
                posAccessorIdx = accessorIndex++;

                // --- BufferView 1: Normals ---
                int normOffset = (int)ms.Position;
                for (int i = 0; i < mesh.Normals.Length; i++)
                    bw.Write(mesh.Normals[i]);
                int normLength = (int)ms.Position - normOffset;
                PadToAlignment(bw, ms, 4);
                normViewIdx = bvIndex++;
                normAccessorIdx = accessorIndex++;

                // --- BufferView 2: Vertex Colors (RGBA, uint8 normalized) ---
                int colorOffset = (int)ms.Position;
                bw.Write(mesh.VertexColors);
                int colorLength = mesh.VertexColors.Length;
                PadToAlignment(bw, ms, 4);
                colorViewIdx = bvIndex++;
                colorAccessorIdx = accessorIndex++;

                // --- BufferView 3: Indices ---
                int idxOffset = (int)ms.Position;
                for (int i = 0; i < mesh.Indices.Length; i++)
                {
                    if (useUint32)
                        bw.Write(mesh.Indices[i]);
                    else
                        bw.Write((ushort)mesh.Indices[i]);
                }
                int idxLength = (int)ms.Position - idxOffset;
                PadToAlignment(bw, ms, 4);
                idxViewIdx = bvIndex++;
                idxAccessorIdx = accessorIndex++;

                // --- BufferView 4 & 5: Morph target (if present) ---
                int morphPosOffset = 0, morphPosLength = 0;
                int morphNormOffset = 0, morphNormLength = 0;

                if (hasMorph)
                {
                    // Morph positions (deltas)
                    morphPosOffset = (int)ms.Position;
                    for (int i = 0; i < mesh.MorphPositions.Length; i++)
                        bw.Write(mesh.MorphPositions[i]);
                    morphPosLength = (int)ms.Position - morphPosOffset;
                    PadToAlignment(bw, ms, 4);
                    morphPosViewIdx = bvIndex++;
                    morphPosAccessorIdx = accessorIndex++;

                    // Morph normals (deltas)
                    if (mesh.MorphNormals != null && mesh.MorphNormals.Length > 0)
                    {
                        morphNormOffset = (int)ms.Position;
                        for (int i = 0; i < mesh.MorphNormals.Length; i++)
                            bw.Write(mesh.MorphNormals[i]);
                        morphNormLength = (int)ms.Position - morphNormOffset;
                        PadToAlignment(bw, ms, 4);
                        morphNormViewIdx = bvIndex++;
                        morphNormAccessorIdx = accessorIndex++;
                    }
                }

                totalBufferViews = bvIndex;
                totalAccessors = accessorIndex;

                bw.Flush();
                binData = ms.ToArray();

                // Now build the glTF JSON
                var sb = new StringBuilder();
                sb.Append("{");

                // Asset
                sb.Append("\"asset\":{\"version\":\"2.0\",\"generator\":\"SolidWorksExtractor-FEA\"},");

                // Scene
                sb.Append("\"scene\":0,\"scenes\":[{\"nodes\":[0]}],");

                // Nodes
                sb.Append("\"nodes\":[{\"mesh\":0,\"name\":\"FEA_Result\"}],");

                // Meshes
                sb.Append("\"meshes\":[{\"name\":\"FEA_Stress_Mesh\",\"primitives\":[{");
                sb.Append("\"attributes\":{");
                sb.Append("\"POSITION\":").Append(posAccessorIdx);
                sb.Append(",\"NORMAL\":").Append(normAccessorIdx);
                sb.Append(",\"COLOR_0\":").Append(colorAccessorIdx);
                sb.Append("}");
                sb.Append(",\"indices\":").Append(idxAccessorIdx);
                sb.Append(",\"material\":0");

                // Morph targets
                if (hasMorph && morphPosAccessorIdx >= 0)
                {
                    sb.Append(",\"targets\":[{\"POSITION\":").Append(morphPosAccessorIdx);
                    if (morphNormAccessorIdx >= 0)
                        sb.Append(",\"NORMAL\":").Append(morphNormAccessorIdx);
                    sb.Append("}]");
                }

                sb.Append("}]");

                // Weights (default morph weight = 0, i.e. undeformed)
                if (hasMorph)
                    sb.Append(",\"weights\":[0.0]");

                sb.Append("}],");

                // Materials — unlit with vertex colors
                sb.Append("\"materials\":[{\"name\":\"FEA_Stress\",\"pbrMetallicRoughness\":{");
                sb.Append("\"metallicFactor\":0.0,\"roughnessFactor\":1.0");
                sb.Append("},\"extensions\":{\"KHR_materials_unlit\":{}}}],");

                // Extensions used
                sb.Append("\"extensionsUsed\":[\"KHR_materials_unlit\"],");

                // Accessors
                sb.Append("\"accessors\":[");
                bool firstAcc = true;

                // Position accessor (with min/max required by spec)
                AppendAccessor(sb, ref firstAcc, posViewIdx, FLOAT, mesh.VertexCount, "VEC3",
                    mesh.BoundsMin, mesh.BoundsMax);

                // Normal accessor
                AppendAccessor(sb, ref firstAcc, normViewIdx, FLOAT, mesh.VertexCount, "VEC3",
                    null, null);

                // Color accessor (normalized unsigned byte)
                AppendAccessor(sb, ref firstAcc, colorViewIdx, UNSIGNED_BYTE, mesh.VertexCount, "VEC4",
                    null, null, normalized: true);

                // Index accessor
                int idxComponentType = useUint32 ? UNSIGNED_INT : UNSIGNED_SHORT;
                AppendAccessor(sb, ref firstAcc, idxViewIdx, idxComponentType, mesh.Indices.Length, "SCALAR",
                    null, null);

                // Morph target accessors
                if (hasMorph && morphPosAccessorIdx >= 0)
                {
                    AppendAccessor(sb, ref firstAcc, morphPosViewIdx, FLOAT, mesh.VertexCount, "VEC3",
                        mesh.MorphBoundsMin, mesh.MorphBoundsMax);

                    if (morphNormAccessorIdx >= 0)
                    {
                        AppendAccessor(sb, ref firstAcc, morphNormViewIdx, FLOAT, mesh.VertexCount, "VEC3",
                            null, null);
                    }
                }

                sb.Append("],");

                // Buffer views
                sb.Append("\"bufferViews\":[");
                bool firstBv = true;

                // Positions
                AppendBufferView(sb, ref firstBv, posOffset, posLength, ARRAY_BUFFER);
                // Normals
                AppendBufferView(sb, ref firstBv, normOffset, normLength, ARRAY_BUFFER);
                // Colors
                AppendBufferView(sb, ref firstBv, colorOffset, colorLength, ARRAY_BUFFER);
                // Indices
                AppendBufferView(sb, ref firstBv, idxOffset, idxLength, ELEMENT_ARRAY_BUFFER);

                // Morph target bufferviews
                if (hasMorph)
                {
                    if (morphPosLength > 0)
                        AppendBufferView(sb, ref firstBv, morphPosOffset, morphPosLength, ARRAY_BUFFER);
                    if (morphNormLength > 0)
                        AppendBufferView(sb, ref firstBv, morphNormOffset, morphNormLength, ARRAY_BUFFER);
                }

                sb.Append("],");

                // Buffer
                sb.AppendFormat(CultureInfo.InvariantCulture,
                    "\"buffers\":[{{\"byteLength\":{0}}}]", binData.Length);

                sb.Append("}");

                // Write GLB file
                string jsonStr = sb.ToString();
                WriteGlbFile(jsonStr, binData, outputPath);
            }
        }

        /// <summary>
        /// Append an accessor entry to the glTF JSON.
        /// </summary>
        private void AppendAccessor(StringBuilder sb, ref bool first, int bufferView,
            int componentType, int count, string type, float[] min, float[] max, bool normalized = false)
        {
            if (!first) sb.Append(",");
            first = false;

            sb.Append("{\"bufferView\":").Append(bufferView);
            sb.AppendFormat(CultureInfo.InvariantCulture,
                ",\"componentType\":{0},\"count\":{1},\"type\":\"{2}\"",
                componentType, count, type);

            if (normalized)
                sb.Append(",\"normalized\":true");

            if (min != null && max != null && min.Length >= 3 && max.Length >= 3)
            {
                sb.AppendFormat(CultureInfo.InvariantCulture,
                    ",\"min\":[{0:G9},{1:G9},{2:G9}]", min[0], min[1], min[2]);
                sb.AppendFormat(CultureInfo.InvariantCulture,
                    ",\"max\":[{0:G9},{1:G9},{2:G9}]", max[0], max[1], max[2]);
            }

            sb.Append("}");
        }

        /// <summary>
        /// Append a bufferView entry to the glTF JSON.
        /// </summary>
        private void AppendBufferView(StringBuilder sb, ref bool first, int byteOffset, int byteLength, int target)
        {
            if (!first) sb.Append(",");
            first = false;

            sb.Append("{\"buffer\":0");
            sb.AppendFormat(CultureInfo.InvariantCulture,
                ",\"byteOffset\":{0},\"byteLength\":{1},\"target\":{2}",
                byteOffset, byteLength, target);
            sb.Append("}");
        }

        /// <summary>
        /// Write the complete GLB binary file (header + JSON chunk + BIN chunk).
        /// Same format as GlbExporter.WriteGlbFile — duplicated to keep SimulationExtractor self-contained.
        /// </summary>
        private void WriteGlbFile(string jsonStr, byte[] binData, string outputPath)
        {
            byte[] jsonBytes = Encoding.ASCII.GetBytes(jsonStr);

            // Pad JSON to 4-byte boundary with spaces
            int jsonPadding = (4 - (jsonBytes.Length % 4)) % 4;
            int jsonChunkLength = jsonBytes.Length + jsonPadding;

            // Pad BIN to 4-byte boundary with zeros
            int binPadding = (4 - (binData.Length % 4)) % 4;
            int binChunkLength = binData.Length + binPadding;

            // Total: 12 (header) + 8 (JSON chunk header) + jsonChunkLength + 8 (BIN chunk header) + binChunkLength
            uint totalLength = (uint)(12 + 8 + jsonChunkLength + 8 + binChunkLength);

            using (var fs = new FileStream(outputPath, FileMode.Create))
            using (var bw = new BinaryWriter(fs))
            {
                // GLB Header (12 bytes)
                bw.Write(GLB_MAGIC);
                bw.Write(GLB_VERSION);
                bw.Write(totalLength);

                // JSON Chunk
                bw.Write((uint)jsonChunkLength);
                bw.Write(JSON_CHUNK_TYPE);
                bw.Write(jsonBytes);
                for (int i = 0; i < jsonPadding; i++)
                    bw.Write((byte)0x20);  // space padding

                // BIN Chunk
                bw.Write((uint)binChunkLength);
                bw.Write(BIN_CHUNK_TYPE);
                bw.Write(binData);
                for (int i = 0; i < binPadding; i++)
                    bw.Write((byte)0x00);  // zero padding
            }
        }

        // --- JSON Output ---

        /// <summary>
        /// Write the FEA results summary JSON file.
        /// </summary>
        private void WriteFeaResultsJson(FeaResultsSummary summary, string outputPath)
        {
            var sb = new StringBuilder();
            sb.AppendLine("{");
            sb.AppendFormat(CultureInfo.InvariantCulture, "  \"study_name\": \"{0}\",\n", EscapeJson(summary.StudyName));
            sb.AppendFormat(CultureInfo.InvariantCulture, "  \"study_type\": \"{0}\",\n", EscapeJson(summary.StudyType));
            sb.AppendLine("  \"units\": \"SI\",");
            sb.AppendLine("  \"summary\": {");
            sb.AppendFormat(CultureInfo.InvariantCulture, "    \"surface_node_count\": {0},\n", summary.SurfaceNodeCount);
            sb.AppendFormat(CultureInfo.InvariantCulture, "    \"element_count\": {0},\n", summary.ElementCount);
            sb.AppendFormat(CultureInfo.InvariantCulture, "    \"max_von_mises_mpa\": {0:G6},\n", summary.MaxVonMisesMpa);
            sb.AppendFormat(CultureInfo.InvariantCulture, "    \"max_displacement_mm\": {0:G6},\n", summary.MaxDisplacementMm);
            sb.AppendFormat(CultureInfo.InvariantCulture,
                "    \"max_stress_location\": [{0:G9}, {1:G9}, {2:G9}],\n",
                summary.MaxStressLocation[0], summary.MaxStressLocation[1], summary.MaxStressLocation[2]);
            sb.AppendFormat(CultureInfo.InvariantCulture,
                "    \"reaction_forces\": {{ \"fx\": {0:G6}, \"fy\": {1:G6}, \"fz\": {2:G6} }},\n",
                summary.ReactionFx, summary.ReactionFy, summary.ReactionFz);
            sb.AppendFormat(CultureInfo.InvariantCulture, "    \"material\": \"{0}\",\n", EscapeJson(summary.MaterialName ?? "Unknown"));
            sb.AppendFormat(CultureInfo.InvariantCulture, "    \"yield_strength_mpa\": {0:G6},\n", summary.YieldStrengthMpa);
            sb.AppendFormat(CultureInfo.InvariantCulture, "    \"safety_factor\": {0:F2}\n", summary.SafetyFactor);
            sb.AppendLine("  },");
            sb.AppendFormat(CultureInfo.InvariantCulture, "  \"has_morph_target\": {0}\n", summary.HasMorphTarget ? "true" : "false");
            sb.Append("}");

            File.WriteAllText(outputPath, sb.ToString(), Encoding.UTF8);
        }

        // --- Utilities ---

        private void PadToAlignment(BinaryWriter bw, MemoryStream ms, int alignment)
        {
            int remainder = (int)(ms.Position % alignment);
            if (remainder != 0)
            {
                int padding = alignment - remainder;
                for (int i = 0; i < padding; i++)
                    bw.Write((byte)0);
            }
        }

        private string EscapeJson(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return s.Replace("\\", "\\\\")
                    .Replace("\"", "\\\"")
                    .Replace("\n", "\\n")
                    .Replace("\r", "\\r")
                    .Replace("\t", "\\t");
        }

        private int[] ConvertToIntArray(object obj)
        {
            if (obj == null) return null;
            if (obj is int[] iArr) return iArr;
            if (obj is double[] dArr)
            {
                int[] result = new int[dArr.Length];
                for (int i = 0; i < dArr.Length; i++)
                    result[i] = (int)dArr[i];
                return result;
            }
            if (obj is object[] oArr)
            {
                int[] result = new int[oArr.Length];
                for (int i = 0; i < oArr.Length; i++)
                    result[i] = Convert.ToInt32(oArr[i]);
                return result;
            }
            return null;
        }

        private void SafeReleaseCom(object comObj)
        {
            if (comObj != null)
            {
                try
                {
                    Marshal.ReleaseComObject(comObj);
                }
                catch { /* best effort */ }
            }
        }
    }
}
