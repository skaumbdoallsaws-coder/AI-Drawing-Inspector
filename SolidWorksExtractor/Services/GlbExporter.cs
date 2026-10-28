using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace SolidWorksExtractor.Services
{
    /// <summary>
    /// Exports a color-coded GLB (binary glTF 2.0) file from an assembly.
    /// Each unique part gets its own mesh + material using the same Sasha Trubetskoy
    /// palette as PartColorizer, ensuring color consistency with 2D view images.
    /// Zero external dependencies — writes raw GLB binary directly.
    /// </summary>
    public class GlbExporter
    {
        // Identical palette as PartColorizer.cs — must stay in sync
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

        // Color names matching palette indices above
        private static readonly string[] PaletteNames = new[]
        {
            "red", "green", "yellow", "blue", "orange",
            "purple", "cyan", "magenta", "lime", "pink",
            "teal", "lavender", "brown", "beige", "maroon",
            "mint", "olive", "apricot", "navy", "grey"
        };

        // Light steel blue for base feature — visually distinct from the #888888 unhighlighted gray
        private static readonly (int R, int G, int B, string Hex) BaseFeatureColor = (176, 196, 222, "#B0C4DE");

        // GLB constants
        private const uint GLB_MAGIC = 0x46546C67;       // "glTF"
        private const uint GLB_VERSION = 2;
        private const uint JSON_CHUNK_TYPE = 0x4E4F534A;  // "JSON"
        private const uint BIN_CHUNK_TYPE = 0x004E4942;   // "BIN\0"

        // glTF constants
        private const int ARRAY_BUFFER = 34962;
        private const int ELEMENT_ARRAY_BUFFER = 34963;
        private const int FLOAT = 5126;
        private const int UNSIGNED_SHORT = 5123;
        private const int UNSIGNED_INT = 5125;

        /// <summary>
        /// Intermediate per-component mesh data.
        /// </summary>
        private class MeshData
        {
            public string Name;
            public string PartFilename;
            public int PaletteIndex;
            public float[] Positions;   // flattened XYZ triplets in assembly space
            public float[] Normals;     // flattened XYZ triplets in assembly space
            public uint[] Indices;      // triangle indices
            public float[] BoundsMin;   // [minX, minY, minZ]
            public float[] BoundsMax;   // [maxX, maxY, maxZ]
            // True when this component's mesh was tessellated EXCLUSIVELY from
            // sheet (surface) bodies. The GLB material is then written with
            // doubleSided=true so thin surfaces are visible from both sides in
            // three.js -- single-sided culling would hide half of every panel.
            // Mixed solid+sheet components stay single-sided (the solid faces
            // dominate visually).
            public bool IsSheetBody;
            // The CAD faces of the mesh in the order their triangles were appended; each face's triangles
            // are one unbroken run of the index buffer. Null where they were not recorded.
            public List<FaceRun> Faces;
        }

        // One CAD face of a mesh: its run of triangles in the index buffer, the kind of surface it lies on,
        // the feature that made it, and its radius in metres when it is a cylinder or a sphere (0 otherwise).
        private class FaceRun
        {
            public int FirstTriangle;
            public int TriangleCount;
            public string Kind;
            public string Feature;
            public double Radius;
        }

        // Cross-method helper return shape for "enumerate every visible body on
        // a part, tagged with whether it's a sheet body". Replaces the legacy
        // GetBodies2(swSolidBody, true) call sites that silently dropped every
        // surface body -- a surface-modeled part (e.g. 1030034 Vintage Plane,
        // built from NetBlend lofts) would produce an effectively empty GLB.
        private struct TaggedBody
        {
            public IBody2 Body;
            public bool   IsSheet;
        }

        private class BodyProcessRecord
        {
            public string BodyId;
            public string BodyName;
            public string BodyType;
            public string GlbNodeName;
            public List<string> FolderPath = new List<string>();
            public string ColorHex;
            public int FaceCount;
            public int VertexCount;
            public int TriangleCount;
            public float[] BoundsMin;
            public float[] BoundsMax;
        }

        /// <summary>
        /// Enumerate both solid and sheet bodies on a part document, in
        /// deterministic order (solids first, then sheets). Empty / null
        /// returns from GetBodies2 are tolerated so a pure-surface part still
        /// yields a body list instead of aborting at the legacy
        /// "No solid bodies found" guard.
        /// </summary>
        private static List<TaggedBody> EnumerateVisibleBodies(IPartDoc partDoc)
        {
            var result = new List<TaggedBody>();
            if (partDoc == null) return result;
            AppendBodies(result, partDoc, swBodyType_e.swSolidBody, isSheet: false);
            AppendBodies(result, partDoc, swBodyType_e.swSheetBody, isSheet: true);
            return result;
        }

        private static void AppendBodies(List<TaggedBody> dest, IPartDoc partDoc, swBodyType_e bodyType, bool isSheet)
        {
            object raw;
            try { raw = partDoc.GetBodies2((int)bodyType, true); }
            catch { return; }
            if (raw == null) return;
            object[] arr = raw as object[];
            if (arr == null || arr.Length == 0) return;
            foreach (object o in arr)
            {
                IBody2 body = o as IBody2;
                if (body != null)
                    dest.Add(new TaggedBody { Body = body, IsSheet = isSheet });
            }
        }

        private class BufferViewInfo
        {
            public int ByteOffset;
            public int ByteLength;
            public int Target;
            public bool UseUint32;
        }

        /// <summary>
        /// Intermediate per-feature mesh data for part-level GLB export.
        /// Each feature owns one or more faces whose tessellation is merged here.
        /// </summary>
        private class FeatureMeshData
        {
            public string CadFeatureId;       // Canonical key: e.g. "holewizard_hole_wizard_1"
            public string SwName;             // Raw SolidWorks feature name: "Hole Wizard 1"
            public string FeatureType;        // Normalized type name from GetTypeName2()
            public int ColorR, ColorG, ColorB;
            public string ColorHex;
            public string ColorName;
            public int FaceCount;
            public Dictionary<string, object> Parameters = new Dictionary<string, object>();
            public List<float> Positions = new List<float>();
            public List<float> Normals = new List<float>();
            public List<uint> Indices = new List<uint>();
            public float[] BoundsMin;
            public float[] BoundsMax;
            // True when ALL faces contributing to this feature mesh came from
            // sheet bodies. Drives doubleSided=true in the GLB material so the
            // panel is visible from both sides in three.js. Mixed solid+sheet
            // features stay single-sided -- the solid hull dominates visually
            // and double-siding it can darken interior shading.
            public bool IsSheetBody;
        }

        /// <summary>
        /// Generate a stable, deterministic cad_feature_id from a SolidWorks feature.
        /// Rules: all lowercase, only [a-z0-9_], type-prefixed, collision-safe.
        /// </summary>
        private static string GenerateFeatureId(IFeature feature, Dictionary<string, int> seenIds)
        {
            string name = feature.Name ?? "unknown";
            string typeName = "unknown";
            try
            {
                typeName = (feature.GetTypeName2() ?? "unknown").ToLower();
            }
            catch { /* fallback to "unknown" */ }

            // 1. Slug: lowercase, replace non-alphanumeric runs with underscore, trim
            string slug = Regex.Replace(name.ToLower(), @"[^a-z0-9]+", "_").Trim('_');
            if (string.IsNullOrEmpty(slug))
                slug = "feature";

            // 2. Prefix with feature type for disambiguation
            if (!slug.StartsWith(typeName))
                slug = typeName + "_" + slug;

            // 3. Uniqueness: append _2, _3, etc. if slug already used
            if (seenIds.ContainsKey(slug))
            {
                seenIds[slug]++;
                slug = slug + "_" + seenIds[slug];
            }
            else
            {
                seenIds[slug] = 1;
            }

            return slug;
        }

        /// <summary>
        /// Normalize a SolidWorks feature type name into a camelCase type string
        /// matching the conventions used in FeatureExtractor.
        /// </summary>
        private static string NormalizeFeatureType(string swTypeName)
        {
            if (string.IsNullOrEmpty(swTypeName)) return "unknown";

            switch (swTypeName)
            {
                case "HoleWzd": return "holeWizard";
                case "ICE": return "extrude";
                case "Boss": return "extrude";
                case "Cut": return "cut";
                case "Fillet": return "fillet";
                case "ChamferFeature": return "chamfer";
                case "Chamfer": return "chamfer";
                case "LPattern": return "linearPattern";
                case "CirPattern": return "circularPattern";
                case "Revolve": return "revolve";
                case "RevCut": return "revolveCut";
                case "Sweep": return "sweep";
                case "SweepCut": return "sweepCut";
                case "Loft": return "loft";
                case "LoftCut": return "loftCut";
                case "Shell": return "shell";
                case "Mirror": return "mirror";
                case "Rib": return "rib";
                case "FlatPattern": return "flatPattern";
                case "SMBaseFlange": return "sheetMetalBaseFlange";
                case "EdgeFlange": return "edgeFlange";
                case "SketchBend": return "sketchBend";
                default: return swTypeName.ToLower();
            }
        }

        /// <summary>
        /// Export a single part document as a per-feature colored GLB.
        /// Each SolidWorks feature gets its own named node in the GLB scene,
        /// with deterministic color assignment (gray for the first/base feature,
        /// then Sasha palette for subsequent features).
        /// Also writes a {partNumber}_feature_colors.json sidecar file.
        /// </summary>
        /// <param name="partDoc">Open part document (IPartDoc)</param>
        /// <param name="modelDoc">Same document as IModelDoc2</param>
        /// <param name="outputFolder">Directory to write output files</param>
        /// <param name="partNumber">Part number for output filenames</param>
        /// <returns>Full path of written GLB, or null on failure</returns>
        public string ExportPartFeatureGlb(IPartDoc partDoc, IModelDoc2 modelDoc, string outputFolder, string partNumber)
        {
            if (partDoc == null || modelDoc == null)
            {
                Console.WriteLine("    Warning: No part document for per-feature GLB export");
                return null;
            }

            if (!Directory.Exists(outputFolder))
                Directory.CreateDirectory(outputFolder);

            // Enumerate every visible body, tagged with whether each is a
            // sheet (surface) body. The legacy code only pulled swSolidBody
            // and silently dropped every surface body, which produced a near-
            // empty GLB for surface-modeled parts (1030034 Vintage Plane:
            // 10 mesh nodes for a model the engineer built almost entirely
            // from NetBlend lofts + Surface-Trim).
            var taggedBodies = EnumerateVisibleBodies(partDoc);
            if (taggedBodies.Count == 0)
            {
                Console.WriteLine("    Warning: No solid or sheet bodies found for per-feature GLB export");
                return null;
            }

            // Suppress flat pattern if active (to get folded geometry)
            IFeature flatPatternFeature = null;
            bool needRestore = false;
            try
            {
                IFeature feat = (IFeature)modelDoc.FirstFeature();
                while (feat != null)
                {
                    if (feat.GetTypeName2() == "FlatPattern" && !feat.IsSuppressed())
                    {
                        flatPatternFeature = feat;
                        feat.SetSuppression2(
                            (int)swFeatureSuppressionAction_e.swSuppressFeature,
                            (int)swInConfigurationOpts_e.swThisConfiguration, null);
                        modelDoc.ForceRebuild3(false);
                        needRestore = true;
                        Console.WriteLine("    Note: Suppressed flat pattern for folded geometry");
                        break;
                    }
                    feat = (IFeature)feat.GetNextFeature();
                }
            }
            catch { /* proceed without flat pattern handling */ }

            try
            {
                // Phase 1: Walk all faces on all bodies, group by owning feature name
                // Key = feature Name (raw SolidWorks), Value = (IFeature ref, list of IFace2)
                // HasSolid/HasSheet track per-bucket origin so the final mesh
                // can be marked doubleSided when every contributing face came
                // from a sheet body.
                var featureFaces = new Dictionary<string, (IFeature Feature, List<IFace2> Faces, bool HasSolid, bool HasSheet)>(StringComparer.Ordinal);
                int totalFaces = 0;
                int sheetBodyIndex = 0;  // 1-based counter, only advanced for sheet bodies

                foreach (var tagged in taggedBodies)
                {
                    IBody2 body = tagged.Body;
                    if (body == null) continue;
                    bool isSheet = tagged.IsSheet;
                    if (isSheet) sheetBodyIndex++;

                    IFace2 face = (IFace2)body.GetFirstFace();
                    while (face != null)
                    {
                        totalFaces++;
                        IFeature ownerFeature = null;
                        string ownerName = null;

                        try
                        {
                            ownerFeature = (IFeature)face.GetFeature();
                            if (ownerFeature != null && !string.IsNullOrEmpty(ownerFeature.Name))
                                ownerName = ownerFeature.Name;
                        }
                        catch { /* owner lookup failed -> handled by fallback below */ }

                        if (ownerName == null)
                        {
                            // Sheet-body faces with no owner get a stable
                            // per-body fallback name so each surface body
                            // becomes its own GLB node (instead of all
                            // ownerless faces collapsing into a single
                            // __unowned__ bucket that spans every surface
                            // body in the part). Solid-body unowned faces
                            // keep the legacy __unowned__ bucket, which
                            // _ExportPartFeatureGlb renames to "base_unowned".
                            ownerName = isSheet
                                ? $"surface_body_{sheetBodyIndex}"
                                : "__unowned__";
                        }

                        if (!featureFaces.ContainsKey(ownerName))
                            featureFaces[ownerName] = (ownerFeature, new List<IFace2>(), false, false);
                        var entry = featureFaces[ownerName];
                        entry.Faces.Add(face);
                        if (isSheet) entry.HasSheet = true;
                        else         entry.HasSolid = true;
                        featureFaces[ownerName] = entry;

                        face = (IFace2)face.GetNextFace();
                    }
                }

                int sheetOnlyBuckets = 0;
                foreach (var kv in featureFaces)
                    if (kv.Value.HasSheet && !kv.Value.HasSolid) sheetOnlyBuckets++;
                Console.WriteLine($"    Found {totalFaces} faces across {featureFaces.Count} features ({sheetOnlyBuckets} sheet-body groups)");

                if (featureFaces.Count == 0)
                {
                    Console.WriteLine("    Warning: No faces found for per-feature GLB export");
                    return null;
                }

                // Phase 2: Tessellate faces per feature and build FeatureMeshData list
                var featureMeshes = new List<FeatureMeshData>();
                var seenIds = new Dictionary<string, int>(StringComparer.Ordinal);
                int paletteIdx = 0;
                bool isFirst = true;

                // Iterate features in the order they appear in the feature tree
                // to ensure deterministic ordering and stable color assignment.
                // First, build ordered list from feature tree, then append any orphans.
                var orderedFeatureNames = new List<string>();
                try
                {
                    IFeature treeFeature = (IFeature)modelDoc.FirstFeature();
                    while (treeFeature != null)
                    {
                        string fname = treeFeature.Name;
                        if (!string.IsNullOrEmpty(fname) && featureFaces.ContainsKey(fname))
                        {
                            if (!orderedFeatureNames.Contains(fname))
                                orderedFeatureNames.Add(fname);
                        }
                        treeFeature = (IFeature)treeFeature.GetNextFeature();
                    }
                }
                catch { /* fallback to dictionary order below */ }

                // Append any faces not found via tree traversal (e.g., "__unowned__")
                foreach (var key in featureFaces.Keys)
                {
                    if (!orderedFeatureNames.Contains(key))
                        orderedFeatureNames.Add(key);
                }

                foreach (string featureName in orderedFeatureNames)
                {
                    var entry = featureFaces[featureName];
                    IFeature swFeature = entry.Feature;
                    List<IFace2> faces = entry.Faces;
                    // doubleSided is correct only when every face came from a
                    // sheet body; mixed solid+sheet buckets keep single-sided.
                    bool sheetOnlyBucket = entry.HasSheet && !entry.HasSolid;

                    // Generate cad_feature_id
                    string cadFeatureId;
                    string swTypeName = "unknown";
                    if (swFeature != null)
                    {
                        cadFeatureId = GenerateFeatureId(swFeature, seenIds);
                        try { swTypeName = swFeature.GetTypeName2() ?? "unknown"; } catch { }
                    }
                    else if (featureName.StartsWith("surface_body_", StringComparison.Ordinal))
                    {
                        // Sheet body fallback bucket -- the name is already
                        // the final stable id, no "base_" prefix.
                        cadFeatureId = featureName;
                        if (seenIds.ContainsKey(cadFeatureId))
                        {
                            seenIds[cadFeatureId]++;
                            cadFeatureId = cadFeatureId + "_" + seenIds[cadFeatureId];
                        }
                        else
                        {
                            seenIds[cadFeatureId] = 1;
                        }
                        swTypeName = "SurfaceBody";
                    }
                    else
                    {
                        // Unowned faces — synthesize an id
                        string slug = Regex.Replace(featureName.ToLower(), @"[^a-z0-9]+", "_").Trim('_');
                        if (string.IsNullOrEmpty(slug)) slug = "unowned";
                        cadFeatureId = "base_" + slug;
                        if (seenIds.ContainsKey(cadFeatureId))
                        {
                            seenIds[cadFeatureId]++;
                            cadFeatureId = cadFeatureId + "_" + seenIds[cadFeatureId];
                        }
                        else
                        {
                            seenIds[cadFeatureId] = 1;
                        }
                    }

                    // Assign color: first feature gets neutral gray, rest get palette
                    int cr, cg, cb;
                    string cHex, cName;
                    if (isFirst)
                    {
                        cr = BaseFeatureColor.R;
                        cg = BaseFeatureColor.G;
                        cb = BaseFeatureColor.B;
                        cHex = BaseFeatureColor.Hex;
                        cName = "light blue";
                        isFirst = false;
                    }
                    else
                    {
                        int pi = paletteIdx % Palette.Length;
                        cr = Palette[pi].R;
                        cg = Palette[pi].G;
                        cb = Palette[pi].B;
                        cHex = Palette[pi].Hex;
                        cName = PaletteNames[pi];
                        paletteIdx++;
                    }

                    // Tessellate all faces for this feature
                    var meshData = new FeatureMeshData
                    {
                        CadFeatureId = cadFeatureId,
                        SwName = featureName,
                        FeatureType = NormalizeFeatureType(swTypeName),
                        ColorR = cr,
                        ColorG = cg,
                        ColorB = cb,
                        ColorHex = cHex,
                        ColorName = cName,
                        FaceCount = faces.Count,
                        IsSheetBody = sheetOnlyBucket
                    };

                    // Extract dimensional parameters for diff detection
                    if (swFeature != null)
                    {
                        meshData.Parameters = ExtractFeatureParameters(swFeature, modelDoc, swTypeName);
                    }

                    uint indexOffset = 0;

                    foreach (IFace2 f in faces)
                    {
                        float[] triVerts = null;
                        float[] triNorms = null;

                        try
                        {
                            triVerts = ConvertToFloatArray(f.GetTessTriangles(true));
                            triNorms = ConvertToFloatArray(f.GetTessNorms());
                        }
                        catch { /* skip this face */ }

                        if (triVerts == null || triVerts.Length < 9)
                            continue;

                        int vertexCount = triVerts.Length / 3;

                        // Ensure normals array matches
                        if (triNorms == null || triNorms.Length != triVerts.Length)
                        {
                            triNorms = new float[triVerts.Length];
                            for (int i = 0; i < vertexCount; i++)
                            {
                                triNorms[i * 3 + 0] = 0f;
                                triNorms[i * 3 + 1] = 1f;
                                triNorms[i * 3 + 2] = 0f;
                            }
                        }

                        // No transform needed — part-local coordinates
                        for (int v = 0; v < vertexCount; v++)
                        {
                            meshData.Positions.Add(triVerts[v * 3 + 0]);
                            meshData.Positions.Add(triVerts[v * 3 + 1]);
                            meshData.Positions.Add(triVerts[v * 3 + 2]);

                            meshData.Normals.Add(triNorms[v * 3 + 0]);
                            meshData.Normals.Add(triNorms[v * 3 + 1]);
                            meshData.Normals.Add(triNorms[v * 3 + 2]);
                        }

                        // Sequential indices
                        for (uint i = 0; i < (uint)vertexCount; i++)
                            meshData.Indices.Add(indexOffset + i);
                        indexOffset += (uint)vertexCount;
                    }

                    // Skip features with no tessellated geometry
                    if (meshData.Positions.Count == 0)
                    {
                        Console.WriteLine($"    Skipping feature '{featureName}' (no tessellation)");
                        continue;
                    }

                    // Compute bounding box
                    float minX = float.MaxValue, minY = float.MaxValue, minZ = float.MaxValue;
                    float maxX = float.MinValue, maxY = float.MinValue, maxZ = float.MinValue;
                    for (int i = 0; i < meshData.Positions.Count; i += 3)
                    {
                        float x = meshData.Positions[i], y = meshData.Positions[i + 1], z = meshData.Positions[i + 2];
                        if (x < minX) minX = x; if (x > maxX) maxX = x;
                        if (y < minY) minY = y; if (y > maxY) maxY = y;
                        if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
                    }
                    meshData.BoundsMin = new float[] { minX, minY, minZ };
                    meshData.BoundsMax = new float[] { maxX, maxY, maxZ };

                    int verts = meshData.Positions.Count / 3;
                    Console.WriteLine($"    Feature '{cadFeatureId}': {meshData.FaceCount} faces, {verts:N0} verts, color={cHex}");

                    featureMeshes.Add(meshData);
                }

                if (featureMeshes.Count == 0)
                {
                    Console.WriteLine("    Warning: No feature meshes generated");
                    return null;
                }

                // Phase 3: Build GLB from feature meshes
                // Per-feature meshes use their own color (not PaletteIndex),
                // so we use dedicated BuildFeature* methods instead of the assembly path.

                // Build binary buffer from feature meshes
                List<BufferViewInfo> bufferViews;
                byte[] binData = BuildFeatureBinaryBuffer(featureMeshes, out bufferViews);

                // Build glTF JSON with per-feature nodes and materials
                string gltfJson = BuildFeatureGltfJson(featureMeshes, bufferViews, binData.Length);

                // Write GLB file
                string glbPath = Path.Combine(outputFolder, partNumber + "_colored.glb");
                WriteGlbFile(gltfJson, binData, glbPath);

                long fileSizeKb = new FileInfo(glbPath).Length / 1024;
                Console.WriteLine($"    Per-feature GLB: {featureMeshes.Count} nodes, {fileSizeKb} KB");

                // Phase 4: Write _feature_colors.json sidecar
                string jsonPath = Path.Combine(outputFolder, partNumber + "_feature_colors.json");
                WriteFeatureColorsJson(featureMeshes, partNumber, jsonPath);
                Console.WriteLine($"    Feature colors JSON: {jsonPath}");

                return glbPath;
            }
            finally
            {
                // Restore flat pattern if suppressed
                if (needRestore && flatPatternFeature != null)
                    RestoreFlatPattern(flatPatternFeature, modelDoc);
            }
        }

        /// <summary>
        /// Export a multibody part with one GLB node per visible body, plus a
        /// process-body sidecar JSON that records body names, body-folder paths,
        /// bounding boxes, and GLB node names. This is intended for imported
        /// plant/process models where the SolidWorks file is a single SLDPRT
        /// containing hundreds of bodies rather than a true SLDASM.
        /// </summary>
        public string ExportPartBodyGlb(IPartDoc partDoc, IModelDoc2 modelDoc, string outputFolder, string baseName)
        {
            if (partDoc == null || modelDoc == null)
            {
                Console.WriteLine("    Warning: No part document for body-level GLB export");
                return null;
            }

            if (!Directory.Exists(outputFolder))
                Directory.CreateDirectory(outputFolder);

            var taggedBodies = EnumerateVisibleBodies(partDoc);
            if (taggedBodies.Count == 0)
            {
                Console.WriteLine("    Warning: No visible solid or sheet bodies found");
                return null;
            }

            var folderMap = BuildBodyFolderPathMap(modelDoc);
            var meshes = new List<MeshData>();
            var records = new List<BodyProcessRecord>();
            int bodyIndex = 0;

            foreach (var tagged in taggedBodies)
            {
                bodyIndex++;
                IBody2 body = tagged.Body;
                if (body == null) continue;

                string bodyName = GetBodyDisplayName(body, bodyIndex);
                string bodyId = MakeBodyId(bodyIndex, bodyName);
                string nodeName = bodyId;
                int paletteIndex = (bodyIndex - 1) % Palette.Length;

                var positions = new List<float>();
                var normals = new List<float>();
                var indices = new List<uint>();
                var faces = new List<FaceRun>();
                uint indexOffset = 0;
                int faceCount = 0;

                IFace2 face = null;
                try { face = (IFace2)body.GetFirstFace(); } catch { face = null; }
                while (face != null)
                {
                    float[] triVerts = null;
                    float[] triNorms = null;

                    try
                    {
                        triVerts = ConvertToFloatArray(face.GetTessTriangles(true));
                        triNorms = ConvertToFloatArray(face.GetTessNorms());
                    }
                    catch { }

                    if (triVerts != null && triVerts.Length >= 9)
                    {
                        faceCount++;
                        int vertexCount = triVerts.Length / 3;
                        if (triNorms == null || triNorms.Length != triVerts.Length)
                        {
                            triNorms = new float[triVerts.Length];
                            for (int i = 0; i < vertexCount; i++)
                            {
                                triNorms[i * 3 + 0] = 0f;
                                triNorms[i * 3 + 1] = 1f;
                                triNorms[i * 3 + 2] = 0f;
                            }
                        }

                        for (int v = 0; v < vertexCount; v++)
                        {
                            positions.Add(triVerts[v * 3 + 0]);
                            positions.Add(triVerts[v * 3 + 1]);
                            positions.Add(triVerts[v * 3 + 2]);
                            normals.Add(triNorms[v * 3 + 0]);
                            normals.Add(triNorms[v * 3 + 1]);
                            normals.Add(triNorms[v * 3 + 2]);
                        }

                        faces.Add(DescribeFace(face, indices.Count / 3, vertexCount / 3));
                        for (uint i = 0; i < (uint)vertexCount; i++)
                            indices.Add(indexOffset + i);
                        indexOffset += (uint)vertexCount;
                    }

                    try { face = (IFace2)face.GetNextFace(); }
                    catch { face = null; }
                }

                if (positions.Count == 0)
                {
                    Console.WriteLine($"    Skipping body '{bodyName}' (no tessellation)");
                    continue;
                }

                float minX = float.MaxValue, minY = float.MaxValue, minZ = float.MaxValue;
                float maxX = float.MinValue, maxY = float.MinValue, maxZ = float.MinValue;
                for (int i = 0; i < positions.Count; i += 3)
                {
                    float x = positions[i], y = positions[i + 1], z = positions[i + 2];
                    if (x < minX) minX = x; if (x > maxX) maxX = x;
                    if (y < minY) minY = y; if (y > maxY) maxY = y;
                    if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
                }

                var boundsMin = new float[] { minX, minY, minZ };
                var boundsMax = new float[] { maxX, maxY, maxZ };
                var folderPath = folderMap.ContainsKey(bodyName)
                    ? new List<string>(folderMap[bodyName])
                    : new List<string>();
                var color = Palette[paletteIndex];

                meshes.Add(new MeshData
                {
                    Name = nodeName,
                    PartFilename = nodeName,
                    PaletteIndex = paletteIndex,
                    Positions = positions.ToArray(),
                    Normals = normals.ToArray(),
                    Indices = indices.ToArray(),
                    Faces = faces,
                    BoundsMin = boundsMin,
                    BoundsMax = boundsMax,
                    IsSheetBody = tagged.IsSheet
                });

                records.Add(new BodyProcessRecord
                {
                    BodyId = bodyId,
                    BodyName = bodyName,
                    BodyType = tagged.IsSheet ? "sheet" : "solid",
                    GlbNodeName = nodeName,
                    FolderPath = folderPath,
                    ColorHex = color.Hex,
                    FaceCount = faceCount,
                    VertexCount = positions.Count / 3,
                    TriangleCount = indices.Count / 3,
                    BoundsMin = boundsMin,
                    BoundsMax = boundsMax
                });

                Console.WriteLine($"    Body '{bodyId}': {positions.Count / 3:N0} verts, {indices.Count / 3:N0} tris, folder={string.Join("/", folderPath)}");
            }

            if (meshes.Count == 0)
            {
                Console.WriteLine("    Warning: No body meshes generated");
                return null;
            }

            List<BufferViewInfo> bufferViews;
            byte[] binData = BuildBinaryBuffer(meshes, out bufferViews);
            string gltfJson = BuildGltfJson(meshes, bufferViews, binData.Length);

            string glbPath = Path.Combine(outputFolder, baseName + "_body.glb");
            WriteGlbFile(gltfJson, binData, glbPath);

            string jsonPath = Path.Combine(outputFolder, baseName + "_process_bodies.json");
            WriteProcessBodiesJson(records, modelDoc, Path.GetFileName(glbPath), jsonPath);

            long fileSizeKb = new FileInfo(glbPath).Length / 1024;
            Console.WriteLine($"    Body-level GLB: {meshes.Count} nodes, {fileSizeKb} KB");
            Console.WriteLine($"    Process bodies JSON: {jsonPath}");

            return glbPath;
        }

        private string GetBodyDisplayName(IBody2 body, int index)
        {
            try
            {
                string name = body.Name;
                if (!string.IsNullOrWhiteSpace(name))
                    return name.Trim();
            }
            catch { }
            return "Body " + index.ToString("000", CultureInfo.InvariantCulture);
        }

        private string MakeBodyId(int index, string bodyName)
        {
            string slug = Slugify(bodyName);
            if (string.IsNullOrEmpty(slug)) slug = "body";
            return "body_" + index.ToString("000", CultureInfo.InvariantCulture) + "__" + slug;
        }

        private string Slugify(string raw)
        {
            string s = (raw ?? "").Trim().ToLowerInvariant();
            s = Regex.Replace(s, @"[^a-z0-9]+", "_").Trim('_');
            if (s.Length > 80) s = s.Substring(0, 80).Trim('_');
            return s;
        }

        private Dictionary<string, List<string>> BuildBodyFolderPathMap(IModelDoc2 modelDoc)
        {
            var map = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
            if (modelDoc == null) return map;

            try
            {
                IFeature feat = (IFeature)modelDoc.FirstFeature();
                while (feat != null)
                {
                    WalkFeatureForBodyFolders(feat, new List<string>(), map);
                    feat = (IFeature)feat.GetNextFeature();
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    Warning: body folder traversal failed: {ex.Message}");
            }

            return map;
        }

        private void WalkFeatureForBodyFolders(IFeature feat, List<string> parentPath, Dictionary<string, List<string>> map)
        {
            if (feat == null) return;

            string typeName = "";
            string featureName = "";
            try { typeName = feat.GetTypeName2() ?? ""; } catch { }
            try { featureName = feat.Name ?? ""; } catch { }

            bool folderLike = typeName.IndexOf("Folder", StringComparison.OrdinalIgnoreCase) >= 0
                || string.Equals(typeName, "FtrFolder", StringComparison.OrdinalIgnoreCase);

            var path = new List<string>(parentPath);
            if (folderLike && !IsSystemBodyFolder(featureName, typeName))
            {
                string clean = CleanFolderName(featureName);
                if (!string.IsNullOrWhiteSpace(clean))
                    path.Add(clean);
            }

            if (folderLike)
                TryMapBodiesFromFolder(feat, path, map);
            else if (path.Count > 0)
                TryMapBodyFeatureName(feat, path, map);

            try
            {
                IFeature sub = (IFeature)feat.GetFirstSubFeature();
                while (sub != null)
                {
                    WalkFeatureForBodyFolders(sub, path, map);
                    sub = (IFeature)sub.GetNextSubFeature();
                }
            }
            catch { }
        }

        private bool IsSystemBodyFolder(string featureName, string typeName)
        {
            string name = (featureName ?? "").Trim().ToLowerInvariant();
            string type = (typeName ?? "").Trim().ToLowerInvariant();
            if (type == "solidbodyfolder" || type == "surfacebodyfolder" || type == "bodyfolder")
                return true;
            if (name.StartsWith("solid bodies") || name.StartsWith("surface bodies"))
                return true;
            if (name == "history" || name == "annotations" || name == "sensors")
                return true;
            return false;
        }

        private string CleanFolderName(string name)
        {
            if (string.IsNullOrWhiteSpace(name)) return "";
            return Regex.Replace(name.Trim(), @"\s+", " ");
        }

        private void TryMapBodiesFromFolder(IFeature folderFeature, List<string> folderPath, Dictionary<string, List<string>> map)
        {
            if (folderFeature == null) return;
            object specific = null;
            try { specific = folderFeature.GetSpecificFeature2(); } catch { }
            if (specific == null) return;

            object rawBodies = null;
            try
            {
                dynamic dyn = specific;
                rawBodies = dyn.GetBodies();
            }
            catch { }

            foreach (object obj in ToObjectArray(rawBodies))
            {
                IBody2 body = obj as IBody2;
                if (body == null) continue;
                string bodyName = GetBodyDisplayName(body, 0);
                if (string.IsNullOrWhiteSpace(bodyName)) continue;
                if (!map.ContainsKey(bodyName) || folderPath.Count > map[bodyName].Count)
                    map[bodyName] = new List<string>(folderPath);
            }

            // User-created SolidWorks body folders are commonly exposed as
            // FeatureFolder objects rather than BodyFolder objects. In that case
            // GetBodies() is unavailable, but GetFeatures() returns the contained
            // BaseBody features whose names match IBody2.Name.
            object rawFeatures = null;
            try
            {
                dynamic dyn = specific;
                rawFeatures = dyn.GetFeatures();
            }
            catch { }

            foreach (object obj in ToObjectArray(rawFeatures))
            {
                IFeature feature = obj as IFeature;
                TryMapBodyFeatureName(feature, folderPath, map);
            }
        }

        private void TryMapBodyFeatureName(IFeature feature, List<string> folderPath, Dictionary<string, List<string>> map)
        {
            if (feature == null || folderPath == null || folderPath.Count == 0) return;

            string typeName = "";
            string featureName = "";
            try { typeName = feature.GetTypeName2() ?? ""; } catch { }
            try { featureName = feature.Name ?? ""; } catch { }

            if (string.IsNullOrWhiteSpace(featureName)) return;
            bool isBodyFeature = string.Equals(typeName, "BaseBody", StringComparison.OrdinalIgnoreCase)
                || string.Equals(typeName, "SurfaceBody", StringComparison.OrdinalIgnoreCase);
            if (!isBodyFeature) return;

            if (!map.ContainsKey(featureName) || folderPath.Count > map[featureName].Count)
                map[featureName] = new List<string>(folderPath);
        }

        private IEnumerable<object> ToObjectArray(object value)
        {
            if (value == null) yield break;
            if (value is object[] arr)
            {
                foreach (object item in arr) yield return item;
                yield break;
            }
            if (value is Array a)
            {
                foreach (object item in a) yield return item;
            }
        }

        private void WriteProcessBodiesJson(List<BodyProcessRecord> records, IModelDoc2 modelDoc, string glbFileName, string outputPath)
        {
            var groups = new Dictionary<string, List<BodyProcessRecord>>(StringComparer.OrdinalIgnoreCase);
            foreach (var r in records)
            {
                string key = (r.FolderPath != null && r.FolderPath.Count > 0)
                    ? string.Join("/", r.FolderPath)
                    : "__ungrouped__";
                if (!groups.ContainsKey(key))
                    groups[key] = new List<BodyProcessRecord>();
                groups[key].Add(r);
            }

            var sb = new StringBuilder();
            string filePath = "";
            try { filePath = modelDoc.GetPathName() ?? ""; } catch { }
            string fileName = string.IsNullOrWhiteSpace(filePath) ? "" : Path.GetFileName(filePath);

            sb.AppendLine("{");
            sb.AppendLine("  \"schemaVersion\": \"process_bodies.v1\",");
            sb.AppendLine("  \"sourceType\": \"solidworks_multibody_part\",");
            sb.AppendFormat("  \"fileName\": \"{0}\",\n", EscapeJson(fileName));
            sb.AppendFormat("  \"filePath\": \"{0}\",\n", EscapeJson(filePath));
            sb.AppendFormat("  \"extractionTimeUtc\": \"{0}\",\n", DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture));
            sb.AppendFormat("  \"glbFile\": \"{0}\",\n", EscapeJson(glbFileName));
            sb.AppendLine("  \"summary\": {");
            sb.AppendFormat("    \"bodyCount\": {0},\n", records.Count);
            sb.AppendFormat("    \"groupCount\": {0}\n", groups.Count);
            sb.AppendLine("  },");

            sb.AppendLine("  \"bodyGroups\": [");
            int gIdx = 0;
            foreach (var kvp in groups)
            {
                bool ungrouped = kvp.Key == "__ungrouped__";
                var groupPath = ungrouped ? new List<string>() : kvp.Key.Split('/').ToList();
                string displayName = ungrouped ? "Ungrouped Bodies" : groupPath.LastOrDefault() ?? kvp.Key;
                string groupId = ungrouped ? "ungrouped_bodies" : Slugify(kvp.Key);
                sb.AppendLine("    {");
                sb.AppendFormat("      \"groupId\": \"{0}\",\n", EscapeJson(groupId));
                sb.AppendFormat("      \"displayName\": \"{0}\",\n", EscapeJson(displayName));
                sb.Append("      \"folderPath\": ");
                AppendStringArray(sb, groupPath, 6);
                sb.AppendLine(",");
                sb.AppendLine("      \"bodyIds\": [");
                for (int i = 0; i < kvp.Value.Count; i++)
                {
                    sb.AppendFormat("        \"{0}\"{1}\n", EscapeJson(kvp.Value[i].BodyId), i < kvp.Value.Count - 1 ? "," : "");
                }
                sb.AppendLine("      ],");
                sb.AppendLine("      \"processRole\": \"\",");
                sb.AppendLine("      \"sageExplanation\": \"\",");
                sb.AppendLine("      \"operatorChecks\": []");
                sb.Append("    }");
                if (gIdx < groups.Count - 1) sb.Append(",");
                sb.AppendLine();
                gIdx++;
            }
            sb.AppendLine("  ],");

            sb.AppendLine("  \"bodies\": [");
            for (int i = 0; i < records.Count; i++)
            {
                var r = records[i];
                sb.AppendLine("    {");
                sb.AppendFormat("      \"bodyId\": \"{0}\",\n", EscapeJson(r.BodyId));
                sb.AppendFormat("      \"bodyName\": \"{0}\",\n", EscapeJson(r.BodyName));
                sb.AppendFormat("      \"bodyType\": \"{0}\",\n", EscapeJson(r.BodyType));
                sb.AppendFormat("      \"glbNodeName\": \"{0}\",\n", EscapeJson(r.GlbNodeName));
                sb.Append("      \"folderPath\": ");
                AppendStringArray(sb, r.FolderPath ?? new List<string>(), 6);
                sb.AppendLine(",");
                sb.AppendFormat("      \"color\": \"{0}\",\n", EscapeJson(r.ColorHex));
                sb.AppendFormat("      \"faceCount\": {0},\n", r.FaceCount);
                sb.AppendFormat("      \"vertexCount\": {0},\n", r.VertexCount);
                sb.AppendFormat("      \"triangleCount\": {0},\n", r.TriangleCount);
                sb.Append("      \"boundingBox\": { \"min\": ");
                AppendFloatArray(sb, r.BoundsMin);
                sb.Append(", \"max\": ");
                AppendFloatArray(sb, r.BoundsMax);
                sb.AppendLine(" }");
                sb.Append("    }");
                if (i < records.Count - 1) sb.Append(",");
                sb.AppendLine();
            }
            sb.AppendLine("  ]");
            sb.AppendLine("}");

            File.WriteAllText(outputPath, sb.ToString(), Encoding.UTF8);
        }

        private void AppendStringArray(StringBuilder sb, IList<string> values, int indentSpaces)
        {
            sb.Append("[");
            for (int i = 0; i < values.Count; i++)
            {
                if (i > 0) sb.Append(", ");
                sb.Append("\"").Append(EscapeJson(values[i])).Append("\"");
            }
            sb.Append("]");
        }

        private void AppendFloatArray(StringBuilder sb, float[] values)
        {
            sb.Append("[");
            for (int i = 0; i < values.Length; i++)
            {
                if (i > 0) sb.Append(", ");
                sb.Append(values[i].ToString("G9", CultureInfo.InvariantCulture));
            }
            sb.Append("]");
        }

        /// <summary>
        /// Build the binary buffer for per-feature meshes (same layout as assembly: pos/norm/idx per mesh).
        /// </summary>
        private byte[] BuildFeatureBinaryBuffer(List<FeatureMeshData> meshes, out List<BufferViewInfo> bufferViews)
        {
            bufferViews = new List<BufferViewInfo>();

            using (var ms = new MemoryStream())
            using (var bw = new BinaryWriter(ms))
            {
                foreach (var mesh in meshes)
                {
                    float[] positions = mesh.Positions.ToArray();
                    float[] normals = mesh.Normals.ToArray();
                    uint[] indices = mesh.Indices.ToArray();

                    // --- Positions ---
                    int posOffset = (int)ms.Position;
                    for (int i = 0; i < positions.Length; i++)
                        bw.Write(positions[i]);
                    int posLength = (int)ms.Position - posOffset;
                    PadToAlignment(bw, ms, 4);
                    bufferViews.Add(new BufferViewInfo
                    {
                        ByteOffset = posOffset,
                        ByteLength = posLength,
                        Target = ARRAY_BUFFER
                    });

                    // --- Normals ---
                    int normOffset = (int)ms.Position;
                    for (int i = 0; i < normals.Length; i++)
                        bw.Write(normals[i]);
                    int normLength = (int)ms.Position - normOffset;
                    PadToAlignment(bw, ms, 4);
                    bufferViews.Add(new BufferViewInfo
                    {
                        ByteOffset = normOffset,
                        ByteLength = normLength,
                        Target = ARRAY_BUFFER
                    });

                    // --- Indices ---
                    int idxOffset = (int)ms.Position;
                    bool useUint32 = (positions.Length / 3) >= 65536;
                    for (int i = 0; i < indices.Length; i++)
                    {
                        if (useUint32)
                            bw.Write(indices[i]);
                        else
                            bw.Write((ushort)indices[i]);
                    }
                    int idxLength = (int)ms.Position - idxOffset;
                    PadToAlignment(bw, ms, 4);
                    bufferViews.Add(new BufferViewInfo
                    {
                        ByteOffset = idxOffset,
                        ByteLength = idxLength,
                        Target = ELEMENT_ARRAY_BUFFER,
                        UseUint32 = useUint32
                    });
                }

                bw.Flush();
                return ms.ToArray();
            }
        }

        /// <summary>
        /// Build the glTF JSON for per-feature colored part GLB.
        /// Each feature gets its own node (named by cad_feature_id), mesh, and material.
        /// </summary>
        private string BuildFeatureGltfJson(List<FeatureMeshData> meshes, List<BufferViewInfo> bufferViews, int totalBinarySize)
        {
            var sb = new StringBuilder();
            int N = meshes.Count;

            sb.Append("{");

            // asset
            sb.Append("\"asset\":{\"version\":\"2.0\",\"generator\":\"SolidWorksExtractor-PartFeature\"},");

            // scene + scenes
            sb.Append("\"scene\":0,\"scenes\":[{\"nodes\":[");
            for (int i = 0; i < N; i++) { if (i > 0) sb.Append(","); sb.Append(i); }
            sb.Append("]}],");

            // nodes — each named by cad_feature_id
            sb.Append("\"nodes\":[");
            for (int i = 0; i < N; i++)
            {
                if (i > 0) sb.Append(",");
                sb.Append("{\"mesh\":").Append(i);
                sb.Append(",\"name\":\"").Append(EscapeJson(meshes[i].CadFeatureId)).Append("\"}");
            }
            sb.Append("],");

            // meshes
            sb.Append("\"meshes\":[");
            for (int i = 0; i < N; i++)
            {
                if (i > 0) sb.Append(",");
                int posAccessor = i * 3;
                int normAccessor = i * 3 + 1;
                int idxAccessor = i * 3 + 2;
                sb.Append("{\"name\":\"").Append(EscapeJson(meshes[i].CadFeatureId)).Append("\",");
                sb.Append("\"primitives\":[{");
                sb.Append("\"attributes\":{\"POSITION\":").Append(posAccessor);
                sb.Append(",\"NORMAL\":").Append(normAccessor).Append("}");
                sb.Append(",\"indices\":").Append(idxAccessor);
                sb.Append(",\"material\":").Append(i);
                sb.Append("}]}");
            }
            sb.Append("],");

            // materials — PBR with per-feature color. Sheet-body-derived
            // meshes are doubleSided so thin surfaces are visible from
            // both sides in three.js (single-sided culling would hide
            // half of every surface panel).
            sb.Append("\"materials\":[");
            for (int i = 0; i < N; i++)
            {
                if (i > 0) sb.Append(",");
                string r = (meshes[i].ColorR / 255f).ToString("F4", CultureInfo.InvariantCulture);
                string g = (meshes[i].ColorG / 255f).ToString("F4", CultureInfo.InvariantCulture);
                string b = (meshes[i].ColorB / 255f).ToString("F4", CultureInfo.InvariantCulture);
                sb.Append("{\"name\":\"").Append(EscapeJson(meshes[i].CadFeatureId)).Append("\",");
                sb.Append("\"pbrMetallicRoughness\":{");
                sb.Append("\"baseColorFactor\":[").Append(r).Append(",").Append(g).Append(",").Append(b).Append(",1.0],");
                sb.Append("\"metallicFactor\":0.1,\"roughnessFactor\":0.7}");
                if (meshes[i].IsSheetBody) sb.Append(",\"doubleSided\":true");
                sb.Append("}");
            }
            sb.Append("],");

            // accessors — 3 per mesh: positions, normals, indices
            sb.Append("\"accessors\":[");
            bool firstAccessor = true;
            for (int i = 0; i < N; i++)
            {
                int bvBase = i * 3;
                int vertCount = meshes[i].Positions.Count / 3;
                int idxCount = meshes[i].Indices.Count;
                bool useUint32 = vertCount >= 65536;

                // Position accessor
                if (!firstAccessor) sb.Append(","); firstAccessor = false;
                sb.Append("{\"bufferView\":").Append(bvBase);
                sb.AppendFormat(CultureInfo.InvariantCulture,
                    ",\"componentType\":{0},\"count\":{1},\"type\":\"VEC3\"", FLOAT, vertCount);
                sb.AppendFormat(CultureInfo.InvariantCulture,
                    ",\"min\":[{0:G9},{1:G9},{2:G9}]",
                    meshes[i].BoundsMin[0], meshes[i].BoundsMin[1], meshes[i].BoundsMin[2]);
                sb.AppendFormat(CultureInfo.InvariantCulture,
                    ",\"max\":[{0:G9},{1:G9},{2:G9}]",
                    meshes[i].BoundsMax[0], meshes[i].BoundsMax[1], meshes[i].BoundsMax[2]);
                sb.Append("}");

                // Normal accessor
                sb.Append(",{\"bufferView\":").Append(bvBase + 1);
                sb.AppendFormat(CultureInfo.InvariantCulture,
                    ",\"componentType\":{0},\"count\":{1},\"type\":\"VEC3\"", FLOAT, vertCount);
                sb.Append("}");

                // Index accessor
                int compType = useUint32 ? UNSIGNED_INT : UNSIGNED_SHORT;
                sb.Append(",{\"bufferView\":").Append(bvBase + 2);
                sb.AppendFormat(CultureInfo.InvariantCulture,
                    ",\"componentType\":{0},\"count\":{1},\"type\":\"SCALAR\"", compType, idxCount);
                sb.Append("}");
            }
            sb.Append("],");

            // bufferViews
            sb.Append("\"bufferViews\":[");
            for (int i = 0; i < bufferViews.Count; i++)
            {
                if (i > 0) sb.Append(",");
                var bv = bufferViews[i];
                sb.Append("{\"buffer\":0");
                sb.AppendFormat(CultureInfo.InvariantCulture,
                    ",\"byteOffset\":{0},\"byteLength\":{1},\"target\":{2}",
                    bv.ByteOffset, bv.ByteLength, bv.Target);
                sb.Append("}");
            }
            sb.Append("],");

            // buffer
            sb.AppendFormat(CultureInfo.InvariantCulture,
                "\"buffers\":[{{\"byteLength\":{0}}}]", totalBinarySize);

            sb.Append("}");
            return sb.ToString();
        }

        /// <summary>
        /// Extract dimensional parameters from a feature definition for diff detection.
        /// Uses AccessSelections/ReleaseSelectionAccess pattern proven in FeatureExtractor.
        /// Returns empty dict for unsupported types — never crashes the export.
        /// Units: mm for lengths, degrees for angles.
        /// </summary>
        private Dictionary<string, object> ExtractFeatureParameters(IFeature feature, IModelDoc2 modelDoc, string swTypeName)
        {
            var p = new Dictionary<string, object>();
            if (feature == null || modelDoc == null) return p;

            try
            {
                object defObj = feature.GetDefinition();
                if (defObj == null) return p;

                switch (swTypeName)
                {
                    case "Extrusion":
                    case "Boss-Extrude":
                    case "Boss":
                    case "ICE":
                    case "Cut":
                    {
                        var data = defObj as IExtrudeFeatureData2;
                        if (data == null) break;
                        if (!data.AccessSelections(modelDoc, null)) break;
                        try
                        {
                            p["depth1_mm"] = Math.Round(data.GetDepth(true) * 1000.0, 4);
                            p["depth2_mm"] = Math.Round(data.GetDepth(false) * 1000.0, 4);
                            p["end_condition_1"] = ((swEndConditions_e)data.GetEndCondition(true)).ToString();
                            try { p["draft_angle_deg"] = Math.Round(data.GetDraftAngle(true) * (180.0 / Math.PI), 2); } catch { }
                        }
                        finally { data.ReleaseSelectionAccess(); }
                        break;
                    }

                    case "EdgeFlange":
                    {
                        var data = defObj as IEdgeFlangeFeatureData;
                        if (data == null) break;
                        if (!data.AccessSelections(modelDoc, null)) break;
                        try
                        {
                            try { p["offset_mm"] = Math.Round(data.OffsetDistance * 1000.0, 4); } catch { }
                            try { p["bend_angle_deg"] = Math.Round(data.BendAngle * (180.0 / Math.PI), 2); } catch { }
                            try { p["gap_mm"] = Math.Round(data.GapDistance * 1000.0, 4); } catch { }
                            try { p["bend_radius_mm"] = Math.Round(data.BendRadius * 1000.0, 4); } catch { }
                        }
                        finally { data.ReleaseSelectionAccess(); }
                        break;
                    }

                    case "Fillet":
                    {
                        var data = defObj as ISimpleFilletFeatureData2;
                        if (data == null) break;
                        if (!data.AccessSelections(modelDoc, null)) break;
                        try
                        {
                            try { p["radius_mm"] = Math.Round(data.DefaultRadius * 1000.0, 4); } catch { }
                        }
                        finally { data.ReleaseSelectionAccess(); }
                        break;
                    }

                    case "Chamfer":
                    case "ChamferFeature":
                    {
                        var data = defObj as IChamferFeatureData2;
                        if (data == null) break;
                        if (!data.AccessSelections(modelDoc, null)) break;
                        try
                        {
                            // Use dynamic for safe property access (API version variance)
                            try
                            {
                                dynamic dynData = data;
                                p["distance_mm"] = Math.Round((double)dynData.Distance1 * 1000.0, 4);
                                p["distance2_mm"] = Math.Round((double)dynData.Distance2 * 1000.0, 4);
                                p["angle_deg"] = Math.Round((double)dynData.Angle * (180.0 / Math.PI), 2);
                            }
                            catch { }
                        }
                        finally { data.ReleaseSelectionAccess(); }
                        break;
                    }

                    case "Revolution":
                    case "Revolve":
                    case "RevCut":
                    {
                        var data = defObj as IRevolveFeatureData2;
                        if (data == null) break;
                        if (!data.AccessSelections(modelDoc, null)) break;
                        try
                        {
                            try { p["angle_deg"] = Math.Round(data.GetRevolutionAngle(true) * (180.0 / Math.PI), 2); } catch { }
                        }
                        finally { data.ReleaseSelectionAccess(); }
                        break;
                    }

                    case "HoleWzd":
                    {
                        var data = defObj as IWizardHoleFeatureData2;
                        if (data == null) break;
                        if (!data.AccessSelections(modelDoc, null)) break;
                        try
                        {
                            int holeType = 0;
                            try { holeType = data.Type; p["hole_type"] = holeType.ToString(); } catch { }
                            try { p["diameter_mm"] = Math.Round(data.HoleDiameter * 1000.0, 4); } catch { }
                            try { p["depth_mm"] = Math.Round(data.HoleDepth * 1000.0, 4); } catch { }
                            try { p["is_through"] = data.EndCondition == (int)swEndConditions_e.swEndCondThroughAll; } catch { }
                            // Tapped hole fields
                            try
                            {
                                string fs = data.FastenerSize;
                                if (!string.IsNullOrEmpty(fs))
                                    p["thread_size"] = fs;
                            }
                            catch { }
                            try { p["thread_depth_mm"] = Math.Round(data.ThreadDepth * 1000.0, 4); } catch { }
                            // Counterbore fields (type 1)
                            if (holeType == 1)
                            {
                                try { p["cbore_diameter_mm"] = Math.Round(data.CounterBoreDiameter * 1000.0, 4); } catch { }
                                try { p["cbore_depth_mm"] = Math.Round(data.CounterBoreDepth * 1000.0, 4); } catch { }
                            }
                            // Countersink fields (type 2)
                            if (holeType == 2)
                            {
                                try { p["csink_diameter_mm"] = Math.Round(data.CounterSinkDiameter * 1000.0, 4); } catch { }
                                try { p["csink_angle_deg"] = Math.Round(data.CounterSinkAngle * (180.0 / Math.PI), 2); } catch { }
                            }
                        }
                        finally { data.ReleaseSelectionAccess(); }
                        // Remove zero-valued optional fields to keep JSON clean
                        var zeroKeys = new List<string>();
                        foreach (var kvp in p)
                        {
                            if (kvp.Value is double d && d == 0.0 && kvp.Key != "depth_mm")
                                zeroKeys.Add(kvp.Key);
                        }
                        foreach (var k in zeroKeys) p.Remove(k);
                        break;
                    }

                    case "SMBaseFlange":
                    {
                        var data = defObj as IBaseFlangeFeatureData;
                        if (data == null) break;
                        if (!data.AccessSelections(modelDoc, null)) break;
                        try
                        {
                            try { p["thickness_mm"] = Math.Round(data.Thickness * 1000.0, 4); } catch { }
                            try { p["bend_radius_mm"] = Math.Round(data.BendRadius * 1000.0, 4); } catch { }
                        }
                        finally { data.ReleaseSelectionAccess(); }
                        break;
                    }

                    case "OneBend":
                    case "SketchBend":
                    case "FlattenBend":
                    {
                        var data = defObj as IOneBendFeatureData;
                        if (data == null) break;
                        if (!data.AccessSelections(modelDoc, null)) break;
                        try
                        {
                            try { p["bend_radius_mm"] = Math.Round(data.BendRadius * 1000.0, 4); } catch { }
                            try { p["bend_angle_deg"] = Math.Round(data.BendAngle * (180.0 / Math.PI), 2); } catch { }
                        }
                        finally { data.ReleaseSelectionAccess(); }
                        break;
                    }

                    case "Shell":
                    {
                        var data = defObj as IShellFeatureData;
                        if (data == null) break;
                        if (!data.AccessSelections(modelDoc, null)) break;
                        try
                        {
                            try { p["thickness_mm"] = Math.Round(data.Thickness * 1000.0, 4); } catch { }
                        }
                        finally { data.ReleaseSelectionAccess(); }
                        break;
                    }

                    case "LPattern":
                    {
                        var data = defObj as ILinearPatternFeatureData;
                        if (data == null) break;
                        if (!data.AccessSelections(modelDoc, null)) break;
                        try
                        {
                            try { p["d1_count"] = data.D1TotalInstances; } catch { }
                            try { p["d1_spacing_mm"] = Math.Round(data.D1Spacing * 1000.0, 4); } catch { }
                            try { p["d2_count"] = data.D2TotalInstances; } catch { }
                            try { p["d2_spacing_mm"] = Math.Round(data.D2Spacing * 1000.0, 4); } catch { }
                        }
                        finally { data.ReleaseSelectionAccess(); }
                        break;
                    }

                    case "CirPattern":
                    {
                        var data = defObj as ICircularPatternFeatureData;
                        if (data == null) break;
                        if (!data.AccessSelections(modelDoc, null)) break;
                        try
                        {
                            try { p["instance_count"] = data.TotalInstances; } catch { }
                            try { p["spacing_deg"] = Math.Round(data.Spacing * (180.0 / Math.PI), 2); } catch { }
                        }
                        finally { data.ReleaseSelectionAccess(); }
                        break;
                    }

                    case "MiterFlange":
                    case "Hem":
                    {
                        // Sheet metal miter/hem — use dynamic for safe property access
                        // These types don't have dedicated stable interfaces
                        try
                        {
                            dynamic dynDef = defObj;
                            dynDef.AccessSelections(modelDoc, null);
                            try
                            {
                                try { p["gap_mm"] = Math.Round((double)dynDef.GapDistance * 1000.0, 4); } catch { }
                                try { p["bend_radius_mm"] = Math.Round((double)dynDef.BendRadius * 1000.0, 4); } catch { }
                            }
                            finally { dynDef.ReleaseSelectionAccess(); }
                        }
                        catch { /* Interface not available for this feature */ }
                        break;
                    }

                    // Unsupported types: return empty dict (graceful degradation)
                    default:
                        break;
                }
            }
            catch (Exception ex)
            {
                // Never crash the GLB export due to parameter extraction
                Console.WriteLine($"    Warning: Parameter extraction failed for '{feature.Name}': {ex.Message}");
            }

            return p;
        }

        /// <summary>
        /// Write the _feature_colors.json sidecar file containing the feature-to-color mapping.
        /// </summary>
        private void WriteFeatureColorsJson(List<FeatureMeshData> meshes, string partNumber, string outputPath)
        {
            var sb = new StringBuilder();
            sb.AppendLine("{");
            sb.AppendFormat("  \"partNumber\": \"{0}\",\n", EscapeJson(partNumber));
            sb.AppendLine("  \"features\": [");

            for (int i = 0; i < meshes.Count; i++)
            {
                var m = meshes[i];
                sb.AppendLine("    {");
                sb.AppendFormat("      \"cad_feature_id\": \"{0}\",\n", EscapeJson(m.CadFeatureId));
                sb.AppendFormat("      \"sw_name\": \"{0}\",\n", EscapeJson(m.SwName));
                sb.AppendFormat("      \"type\": \"{0}\",\n", EscapeJson(m.FeatureType));
                sb.AppendFormat("      \"display_label\": \"{0}\",\n", EscapeJson(m.SwName));
                sb.AppendFormat("      \"color\": \"{0}\",\n", EscapeJson(m.ColorHex));
                sb.AppendFormat("      \"color_name\": \"{0}\",\n", EscapeJson(m.ColorName));
                sb.AppendFormat("      \"face_count\": {0},\n", m.FaceCount);
                // Write parameters if any exist
                if (m.Parameters != null && m.Parameters.Count > 0)
                {
                    sb.AppendLine("      \"parameters\": {");
                    int pIdx = 0;
                    foreach (var kvp in m.Parameters)
                    {
                        string valStr;
                        if (kvp.Value is double d)
                        {
                            // F4 for lengths (mm), F2 for angles (deg)
                            string fmt = (kvp.Key.Contains("angle") || kvp.Key.Contains("deg")) ? "F2" : "F4";
                            valStr = d.ToString(fmt, CultureInfo.InvariantCulture);
                        }
                        else if (kvp.Value is int intVal)
                            valStr = intVal.ToString();
                        else if (kvp.Value is bool b)
                            valStr = b ? "true" : "false";
                        else if (kvp.Value is string s)
                            valStr = "\"" + EscapeJson(s) + "\"";
                        else
                            valStr = "\"" + kvp.Value + "\"";

                        string comma = (pIdx < m.Parameters.Count - 1) ? "," : "";
                        sb.AppendFormat("        \"{0}\": {1}{2}\n", EscapeJson(kvp.Key), valStr, comma);
                        pIdx++;
                    }
                    sb.AppendLine("      },");
                }
                sb.AppendFormat("      \"glb_node_name\": \"{0}\"\n", EscapeJson(m.CadFeatureId));
                sb.Append("    }");
                if (i < meshes.Count - 1)
                    sb.Append(",");
                sb.AppendLine();
            }

            sb.AppendLine("  ]");
            sb.Append("}");

            File.WriteAllText(outputPath, sb.ToString(), Encoding.UTF8);
        }

        /// <summary>
        /// Export the assembly as a color-coded GLB file.
        /// </summary>
        /// <param name="assyDoc">Open assembly document</param>
        /// <param name="outputFolder">Directory to write the GLB file</param>
        /// <param name="assemblyName">Base filename for the GLB</param>
        /// <returns>Full path of written GLB, or null on failure</returns>
        public string ExportGlb(IAssemblyDoc assyDoc, string outputFolder, string assemblyName)
        {
            if (assyDoc == null)
            {
                Console.WriteLine("    Warning: No assembly document for GLB export");
                return null;
            }

            if (!Directory.Exists(outputFolder))
                Directory.CreateDirectory(outputFolder);

            // Get all components (flat list)
            object[] allComponents = (object[])assyDoc.GetComponents(false);
            if (allComponents == null || allComponents.Length == 0)
            {
                Console.WriteLine("    Warning: No components found for GLB export");
                return null;
            }

            // Build sorted unique part set (identical logic to PartColorizer)
            var uniqueParts = new SortedSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (object obj in allComponents)
            {
                IComponent2 comp = (IComponent2)obj;
                if (comp == null) continue;
                if (comp.GetSuppression2() == (int)swComponentSuppressionState_e.swComponentSuppressed)
                    continue;
                string path = comp.GetPathName();
                if (string.IsNullOrEmpty(path)) continue;
                string fn = Path.GetFileName(path);
                if (!string.IsNullOrEmpty(fn) && fn.EndsWith(".SLDPRT", StringComparison.OrdinalIgnoreCase))
                    uniqueParts.Add(fn.ToLower());
            }

            // Assign palette indices (same deterministic order as PartColorizer)
            var partToColorIndex = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            int colorIdx = 0;
            foreach (string partFile in uniqueParts)
            {
                partToColorIndex[partFile] = colorIdx % Palette.Length;
                colorIdx++;
            }

            // Extract tessellation for each component. Repeated facility layouts
            // often reuse the same rack/forklift parts hundreds of times, so cache
            // local part meshes by file/config and only apply each instance transform.
            var meshes = new List<MeshData>();
            var localMeshCache = new Dictionary<string, MeshData>(StringComparer.OrdinalIgnoreCase);
            foreach (object obj in allComponents)
            {
                IComponent2 comp = (IComponent2)obj;
                if (comp == null) continue;
                if (comp.GetSuppression2() == (int)swComponentSuppressionState_e.swComponentSuppressed)
                    continue;

                string path = comp.GetPathName();
                if (string.IsNullOrEmpty(path)) continue;
                string fn = Path.GetFileName(path)?.ToLower();
                if (string.IsNullOrEmpty(fn) || !partToColorIndex.ContainsKey(fn)) continue;

                MeshData mesh = ExtractComponentMeshCached(comp, fn, partToColorIndex[fn], localMeshCache);
                if (mesh != null)
                    meshes.Add(mesh);
            }

            if (meshes.Count == 0)
            {
                Console.WriteLine("    Warning: No tessellation data extracted for GLB");
                return null;
            }

            Console.WriteLine($"    Extracted {meshes.Count} component meshes");

            // Build binary buffer
            List<BufferViewInfo> bufferViews;
            byte[] binData = BuildBinaryBuffer(meshes, out bufferViews);

            // Build glTF JSON
            string gltfJson = BuildGltfJson(meshes, bufferViews, binData.Length);

            // Write GLB file
            string outputPath = Path.Combine(outputFolder, assemblyName + "_colored.glb");
            WriteGlbFile(gltfJson, binData, outputPath);

            long fileSizeKb = new FileInfo(outputPath).Length / 1024;
            Console.WriteLine($"    GLB file size: {fileSizeKb} KB");

            return outputPath;
        }

        /// <summary>
        /// Extract tessellation data for a single component, transformed into assembly space.
        /// </summary>
        private MeshData ExtractComponentMeshCached(
            IComponent2 comp,
            string partFilename,
            int paletteIndex,
            Dictionary<string, MeshData> localMeshCache)
        {
            if (comp == null) return null;
            string path = comp.GetPathName();
            string configName = "";
            try { configName = comp.ReferencedConfiguration ?? ""; } catch { }
            string cacheKey = (path ?? partFilename) + "|" + configName;

            if (!localMeshCache.TryGetValue(cacheKey, out MeshData localMesh))
            {
                IModelDoc2 refDoc = (IModelDoc2)comp.GetModelDoc2();
                if (refDoc == null)
                {
                    Console.WriteLine($"    Warning: '{comp.Name2}' is lightweight, skipping GLB mesh");
                    return null;
                }

                if (!string.IsNullOrWhiteSpace(configName))
                {
                    try { refDoc.ShowConfiguration2(configName); }
                    catch { /* best effort: component context may already be correct */ }
                }

                IPartDoc partDoc = refDoc as IPartDoc;
                if (partDoc == null) return null;

                localMesh = ExtractLocalPartMesh(refDoc, partDoc, partFilename, configName);
                if (localMesh == null) return null;
                localMeshCache[cacheKey] = localMesh;
                Console.WriteLine($"    Cached {partFilename} [{(string.IsNullOrWhiteSpace(configName) ? "default" : configName)}]: {localMesh.Positions.Length / 3:N0} verts, {localMesh.Indices.Length / 3:N0} tris");
            }

            MeshData transformed = TransformLocalMeshForComponent(localMesh, comp, partFilename, paletteIndex);
            if (transformed != null)
                Console.WriteLine($"    {comp.Name2}: {transformed.Positions.Length / 3:N0} verts, {transformed.Indices.Length / 3:N0} tris");
            return transformed;
        }

        private MeshData ExtractLocalPartMesh(IModelDoc2 refDoc, IPartDoc partDoc, string partFilename, string configName)
        {
            // Ensure sheet metal parts are in folded state (suppress Flat Pattern if active)
            IFeature flatPatternFeature = null;
            bool needRestore = false;
            try
            {
                IFeature feat = (IFeature)refDoc.FirstFeature();
                while (feat != null)
                {
                    if (feat.GetTypeName2() == "FlatPattern")
                    {
                        if (!feat.IsSuppressed())
                        {
                            flatPatternFeature = feat;
                            feat.SetSuppression2(
                                (int)swFeatureSuppressionAction_e.swSuppressFeature,
                                (int)swInConfigurationOpts_e.swThisConfiguration, null);
                            refDoc.ForceRebuild3(false);
                            needRestore = true;
                        }
                        break;
                    }
                    feat = (IFeature)feat.GetNextFeature();
                }
            }
            catch { /* proceed without flat pattern handling */ }

            var taggedBodies = EnumerateVisibleBodies(partDoc);
            if (taggedBodies.Count == 0)
            {
                if (needRestore) RestoreFlatPattern(flatPatternFeature, refDoc);
                return null;
            }

            var allPositions = new List<float>();
            var allNormals = new List<float>();
            var allIndices = new List<uint>();
            var faces = new List<FaceRun>();
            uint indexOffset = 0;
            bool sawSolid = false;
            bool sawSheet = false;

            foreach (var tagged in taggedBodies)
            {
                IBody2 body = tagged.Body;
                if (body == null) continue;
                if (tagged.IsSheet) sawSheet = true;
                else sawSolid = true;

                IFace2 face = (IFace2)body.GetFirstFace();
                while (face != null)
                {
                    float[] triVerts = null;
                    float[] triNorms = null;
                    try
                    {
                        triVerts = ConvertToFloatArray(face.GetTessTriangles(true));
                        triNorms = ConvertToFloatArray(face.GetTessNorms());
                    }
                    catch { /* skip face */ }

                    if (triVerts == null || triVerts.Length < 9)
                    {
                        face = (IFace2)face.GetNextFace();
                        continue;
                    }

                    int vertexCount = triVerts.Length / 3;
                    if (triNorms == null || triNorms.Length != triVerts.Length)
                    {
                        triNorms = new float[triVerts.Length];
                        for (int i = 0; i < vertexCount; i++)
                        {
                            triNorms[i * 3 + 0] = 0f;
                            triNorms[i * 3 + 1] = 1f;
                            triNorms[i * 3 + 2] = 0f;
                        }
                    }

                    for (int v = 0; v < vertexCount; v++)
                    {
                        allPositions.Add(triVerts[v * 3 + 0]);
                        allPositions.Add(triVerts[v * 3 + 1]);
                        allPositions.Add(triVerts[v * 3 + 2]);

                        float nx = triNorms[v * 3 + 0];
                        float ny = triNorms[v * 3 + 1];
                        float nz = triNorms[v * 3 + 2];
                        double len = Math.Sqrt(nx * nx + ny * ny + nz * nz);
                        if (len > 1e-10)
                        {
                            allNormals.Add((float)(nx / len));
                            allNormals.Add((float)(ny / len));
                            allNormals.Add((float)(nz / len));
                        }
                        else
                        {
                            allNormals.Add(0f);
                            allNormals.Add(1f);
                            allNormals.Add(0f);
                        }
                    }

                    faces.Add(DescribeFace(face, allIndices.Count / 3, vertexCount / 3));
                    for (uint i = 0; i < (uint)vertexCount; i++)
                        allIndices.Add(indexOffset + i);
                    indexOffset += (uint)vertexCount;

                    face = (IFace2)face.GetNextFace();
                }
            }

            if (needRestore)
                RestoreFlatPattern(flatPatternFeature, refDoc);

            if (allPositions.Count == 0) return null;

            float minX = float.MaxValue, minY = float.MaxValue, minZ = float.MaxValue;
            float maxX = float.MinValue, maxY = float.MinValue, maxZ = float.MinValue;
            for (int i = 0; i < allPositions.Count; i += 3)
            {
                float x = allPositions[i], y = allPositions[i + 1], z = allPositions[i + 2];
                if (x < minX) minX = x; if (x > maxX) maxX = x;
                if (y < minY) minY = y; if (y > maxY) maxY = y;
                if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
            }

            return new MeshData
            {
                Name = string.IsNullOrWhiteSpace(configName) ? partFilename : $"{partFilename}:{configName}",
                PartFilename = partFilename,
                PaletteIndex = 0,
                Positions = allPositions.ToArray(),
                Normals = allNormals.ToArray(),
                Indices = allIndices.ToArray(),
                Faces = faces,
                BoundsMin = new float[] { minX, minY, minZ },
                BoundsMax = new float[] { maxX, maxY, maxZ },
                IsSheetBody = sawSheet && !sawSolid
            };
        }

        private MeshData TransformLocalMeshForComponent(MeshData localMesh, IComponent2 comp, string partFilename, int paletteIndex)
        {
            if (localMesh == null) return null;

            double[] xform = null;
            try
            {
                IMathTransform mathXform = comp.Transform2;
                if (mathXform != null)
                    xform = (double[])mathXform.ArrayData;
            }
            catch { /* use identity if transform unavailable */ }

            var positions = new float[localMesh.Positions.Length];
            var normals = new float[localMesh.Normals.Length];
            float minX = float.MaxValue, minY = float.MaxValue, minZ = float.MaxValue;
            float maxX = float.MinValue, maxY = float.MinValue, maxZ = float.MinValue;

            for (int i = 0; i < localMesh.Positions.Length; i += 3)
            {
                float px = localMesh.Positions[i];
                float py = localMesh.Positions[i + 1];
                float pz = localMesh.Positions[i + 2];

                float tx = px, ty = py, tz = pz;
                if (xform != null && xform.Length >= 13)
                {
                    double scale = xform[12];
                    double rx = xform[0] * px + xform[3] * py + xform[6] * pz;
                    double ry = xform[1] * px + xform[4] * py + xform[7] * pz;
                    double rz = xform[2] * px + xform[5] * py + xform[8] * pz;
                    tx = (float)(rx * scale + xform[9]);
                    ty = (float)(ry * scale + xform[10]);
                    tz = (float)(rz * scale + xform[11]);
                }
                positions[i] = tx;
                positions[i + 1] = ty;
                positions[i + 2] = tz;

                if (tx < minX) minX = tx; if (tx > maxX) maxX = tx;
                if (ty < minY) minY = ty; if (ty > maxY) maxY = ty;
                if (tz < minZ) minZ = tz; if (tz > maxZ) maxZ = tz;
            }

            for (int i = 0; i < localMesh.Normals.Length; i += 3)
            {
                float nx = localMesh.Normals[i];
                float ny = localMesh.Normals[i + 1];
                float nz = localMesh.Normals[i + 2];

                float tx = nx, ty = ny, tz = nz;
                if (xform != null && xform.Length >= 9)
                {
                    double rnx = xform[0] * nx + xform[3] * ny + xform[6] * nz;
                    double rny = xform[1] * nx + xform[4] * ny + xform[7] * nz;
                    double rnz = xform[2] * nx + xform[5] * ny + xform[8] * nz;
                    double len = Math.Sqrt(rnx * rnx + rny * rny + rnz * rnz);
                    if (len > 1e-10)
                    {
                        tx = (float)(rnx / len);
                        ty = (float)(rny / len);
                        tz = (float)(rnz / len);
                    }
                    else
                    {
                        tx = 0f; ty = 1f; tz = 0f;
                    }
                }
                normals[i] = tx;
                normals[i + 1] = ty;
                normals[i + 2] = tz;
            }

            return new MeshData
            {
                Name = comp.Name2 ?? localMesh.Name,
                PartFilename = partFilename,
                PaletteIndex = paletteIndex,
                Positions = positions,
                Normals = normals,
                Indices = localMesh.Indices,
                Faces = localMesh.Faces,
                BoundsMin = new float[] { minX, minY, minZ },
                BoundsMax = new float[] { maxX, maxY, maxZ },
                IsSheetBody = localMesh.IsSheetBody
            };
        }

        private MeshData ExtractComponentMesh(IComponent2 comp, string partFilename, int paletteIndex)
        {
            IModelDoc2 refDoc = (IModelDoc2)comp.GetModelDoc2();
            if (refDoc == null)
            {
                Console.WriteLine($"    Warning: '{comp.Name2}' is lightweight, skipping GLB mesh");
                return null;
            }

            IPartDoc partDoc = refDoc as IPartDoc;
            if (partDoc == null) return null;

            // Ensure sheet metal parts are in folded state (suppress Flat Pattern if active)
            IFeature flatPatternFeature = null;
            bool needRestore = false;
            try
            {
                IFeature feat = (IFeature)refDoc.FirstFeature();
                while (feat != null)
                {
                    if (feat.GetTypeName2() == "FlatPattern")
                    {
                        // Check if the flat pattern is unsuppressed (active)
                        if (!feat.IsSuppressed())
                        {
                            flatPatternFeature = feat;
                            feat.SetSuppression2(
                                (int)swFeatureSuppressionAction_e.swSuppressFeature,
                                (int)swInConfigurationOpts_e.swThisConfiguration, null);
                            refDoc.ForceRebuild3(false);
                            needRestore = true;
                            Console.WriteLine($"    Note: Suppressed flat pattern for '{comp.Name2}' to get folded geometry");
                        }
                        break;
                    }
                    feat = (IFeature)feat.GetNextFeature();
                }
            }
            catch { /* proceed without flat pattern handling */ }

            // Enumerate both solid and sheet bodies so surface-modeled parts
            // (e.g. fairings, panels, sheet-metal-with-surfaces) contribute
            // visible geometry to the assembly GLB. The legacy swSolidBody-
            // only call dropped every surface body silently.
            var taggedBodies = EnumerateVisibleBodies(partDoc);
            if (taggedBodies.Count == 0)
            {
                if (needRestore) RestoreFlatPattern(flatPatternFeature, refDoc);
                return null;
            }

            // Get component transform (part-local → assembly coordinates)
            double[] xform = null;
            try
            {
                IMathTransform mathXform = comp.Transform2;
                if (mathXform != null)
                    xform = (double[])mathXform.ArrayData;
            }
            catch { /* use identity if transform unavailable */ }

            var allPositions = new List<float>();
            var allNormals = new List<float>();
            var allIndices = new List<uint>();
            var faces = new List<FaceRun>();
            uint indexOffset = 0;
            bool sawSolid = false;
            bool sawSheet = false;

            foreach (var tagged in taggedBodies)
            {
                IBody2 body = tagged.Body;
                if (body == null) continue;
                if (tagged.IsSheet) sawSheet = true;
                else                sawSolid = true;

                // Get tessellation via per-face API (IFace2.GetTessTriangles)
                IFace2 face = (IFace2)body.GetFirstFace();
                while (face != null)
                {
                    float[] triVerts = null;
                    float[] triNorms = null;

                    try
                    {
                        triVerts = ConvertToFloatArray(face.GetTessTriangles(true));
                        triNorms = ConvertToFloatArray(face.GetTessNorms());
                    }
                    catch { /* skip face */ }

                    if (triVerts == null || triVerts.Length < 9)
                    {
                        face = (IFace2)face.GetNextFace();
                        continue;
                    }

                    int vertexCount = triVerts.Length / 3;

                    // Ensure normals array matches
                    if (triNorms == null || triNorms.Length != triVerts.Length)
                    {
                        triNorms = new float[triVerts.Length];
                        for (int i = 0; i < vertexCount; i++)
                        {
                            triNorms[i * 3 + 0] = 0f;
                            triNorms[i * 3 + 1] = 1f;
                            triNorms[i * 3 + 2] = 0f;
                        }
                    }

                    // Transform vertices and normals into assembly space
                    // SolidWorks uses ROW-VECTOR convention: P' = P * R * scale + T
                    // ArrayData: [a b c d e f g h i Tx Ty Tz Scale]
                    // Row-vector multiply uses COLUMNS of the stored matrix
                    for (int v = 0; v < vertexCount; v++)
                    {
                        float px = triVerts[v * 3 + 0];
                        float py = triVerts[v * 3 + 1];
                        float pz = triVerts[v * 3 + 2];

                        if (xform != null && xform.Length >= 13)
                        {
                            double scale = xform[12];
                            // P' = scale * (P * R) + T  (row-vector: use columns)
                            double rx = xform[0] * px + xform[3] * py + xform[6] * pz;
                            double ry = xform[1] * px + xform[4] * py + xform[7] * pz;
                            double rz = xform[2] * px + xform[5] * py + xform[8] * pz;
                            allPositions.Add((float)(rx * scale + xform[9]));
                            allPositions.Add((float)(ry * scale + xform[10]));
                            allPositions.Add((float)(rz * scale + xform[11]));
                        }
                        else
                        {
                            allPositions.Add(px);
                            allPositions.Add(py);
                            allPositions.Add(pz);
                        }

                        // Normals: rotation only (row-vector), then normalize
                        float nx = triNorms[v * 3 + 0];
                        float ny = triNorms[v * 3 + 1];
                        float nz = triNorms[v * 3 + 2];

                        if (xform != null && xform.Length >= 9)
                        {
                            double rnx = xform[0] * nx + xform[3] * ny + xform[6] * nz;
                            double rny = xform[1] * nx + xform[4] * ny + xform[7] * nz;
                            double rnz = xform[2] * nx + xform[5] * ny + xform[8] * nz;
                            double len = Math.Sqrt(rnx * rnx + rny * rny + rnz * rnz);
                            if (len > 1e-10)
                            {
                                allNormals.Add((float)(rnx / len));
                                allNormals.Add((float)(rny / len));
                                allNormals.Add((float)(rnz / len));
                            }
                            else
                            {
                                allNormals.Add(0f); allNormals.Add(1f); allNormals.Add(0f);
                            }
                        }
                        else
                        {
                            allNormals.Add(nx); allNormals.Add(ny); allNormals.Add(nz);
                        }
                    }

                    faces.Add(DescribeFace(face, allIndices.Count / 3, vertexCount / 3));
                    // Sequential indices for this face's triangles
                    for (uint i = 0; i < (uint)vertexCount; i++)
                        allIndices.Add(indexOffset + i);
                    indexOffset += (uint)vertexCount;

                    face = (IFace2)face.GetNextFace();
                }
            }

            // Restore flat pattern if we suppressed it
            if (needRestore)
                RestoreFlatPattern(flatPatternFeature, refDoc);

            if (allPositions.Count == 0) return null;

            // Compute bounding box
            float minX = float.MaxValue, minY = float.MaxValue, minZ = float.MaxValue;
            float maxX = float.MinValue, maxY = float.MinValue, maxZ = float.MinValue;
            for (int i = 0; i < allPositions.Count; i += 3)
            {
                float x = allPositions[i], y = allPositions[i + 1], z = allPositions[i + 2];
                if (x < minX) minX = x; if (x > maxX) maxX = x;
                if (y < minY) minY = y; if (y > maxY) maxY = y;
                if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
            }

            int verts = allPositions.Count / 3;
            int tris = allIndices.Count / 3;

            Console.WriteLine($"    {comp.Name2}: {verts:N0} verts, {tris:N0} tris");

            return new MeshData
            {
                Name = comp.Name2 ?? partFilename,
                PartFilename = partFilename,
                PaletteIndex = paletteIndex,
                Positions = allPositions.ToArray(),
                Normals = allNormals.ToArray(),
                Indices = allIndices.ToArray(),
                Faces = faces,
                BoundsMin = new float[] { minX, minY, minZ },
                BoundsMax = new float[] { maxX, maxY, maxZ },
                // Mark doubleSided only when every contributing body was a
                // sheet body. Mixed solid+sheet components stay single-sided
                // (the solid hull dominates; double-siding it darkens shading).
                IsSheetBody = sawSheet && !sawSolid
            };
        }

        /// <summary>
        /// One face's run of triangles, with the kind of surface it lies on and the feature that made it.
        /// </summary>
        private static FaceRun DescribeFace(IFace2 face, int firstTriangle, int triangleCount)
        {
            var run = new FaceRun
            {
                FirstTriangle = firstTriangle,
                TriangleCount = triangleCount,
                Kind = "other",
                Feature = ""
            };
            try
            {
                ISurface surface = (ISurface)face.GetSurface();
                if (surface != null)
                {
                    if (surface.IsPlane()) run.Kind = "plane";
                    else if (surface.IsCylinder())
                    {
                        run.Kind = "cylinder";
                        // CylinderParams: origin xyz, axis xyz, radius.
                        if (surface.CylinderParams is double[] p && p.Length >= 7) run.Radius = p[6];
                    }
                    else if (surface.IsCone()) run.Kind = "cone";
                    else if (surface.IsSphere())
                    {
                        run.Kind = "sphere";
                        // SphereParams: centre xyz, radius.
                        if (surface.SphereParams is double[] p && p.Length >= 4) run.Radius = p[3];
                    }
                    else if (surface.IsTorus()) run.Kind = "torus";
                }
            }
            catch { /* the kind stays other */ }
            try
            {
                IFeature feature = (IFeature)face.GetFeature();
                if (feature != null) run.Feature = feature.Name ?? "";
            }
            catch { /* no feature name */ }
            if (double.IsNaN(run.Radius) || double.IsInfinity(run.Radius) || run.Radius < 0) run.Radius = 0;
            return run;
        }

        /// <summary>
        /// The mesh's CAD faces as primitive extras (docs/assembly-face-selection-plan.md, F0): the kinds and
        /// features named once, then one row per face of [first triangle, triangle count, kind, feature,
        /// radius]. Each face's triangles are one unbroken run, in the order they were appended.
        /// </summary>
        private void AppendFaceExtras(StringBuilder sb, MeshData mesh)
        {
            if (mesh.Faces == null || mesh.Faces.Count == 0) return;
            var kinds = new List<string>();
            var features = new List<string>();
            var kindIndex = new Dictionary<string, int>(StringComparer.Ordinal);
            var featureIndex = new Dictionary<string, int>(StringComparer.Ordinal);
            var rows = new StringBuilder();
            foreach (var face in mesh.Faces)
            {
                string kind = face.Kind ?? "other";
                string feature = face.Feature ?? "";
                if (!kindIndex.TryGetValue(kind, out int k))
                {
                    k = kinds.Count;
                    kindIndex[kind] = k;
                    kinds.Add(kind);
                }
                if (!featureIndex.TryGetValue(feature, out int f))
                {
                    f = features.Count;
                    featureIndex[feature] = f;
                    features.Add(feature);
                }
                if (rows.Length > 0) rows.Append(",");
                rows.Append("[").Append(face.FirstTriangle).Append(",").Append(face.TriangleCount)
                    .Append(",").Append(k).Append(",").Append(f).Append(",")
                    .Append(face.Radius.ToString("G6", CultureInfo.InvariantCulture)).Append("]");
            }
            sb.Append(",\"extras\":{\"inspectorpro\":{\"faceVersion\":1,\"faceKinds\":[");
            for (int i = 0; i < kinds.Count; i++)
            {
                if (i > 0) sb.Append(",");
                sb.Append("\"").Append(EscapeJson(kinds[i])).Append("\"");
            }
            sb.Append("],\"faceFeatures\":[");
            for (int i = 0; i < features.Count; i++)
            {
                if (i > 0) sb.Append(",");
                sb.Append("\"").Append(EscapeJson(features[i])).Append("\"");
            }
            sb.Append("],\"faces\":[").Append(rows.ToString()).Append("]}}");
        }

        private float[] ConvertToFloatArray(object obj)
        {
            if (obj == null) return null;
            if (obj is double[] dArr)
            {
                float[] result = new float[dArr.Length];
                for (int i = 0; i < dArr.Length; i++)
                    result[i] = (float)dArr[i];
                return result;
            }
            if (obj is float[] fArr) return fArr;
            return null;
        }

        /// <summary>
        /// Restore a previously suppressed flat pattern feature.
        /// </summary>
        private void RestoreFlatPattern(IFeature flatPatternFeature, IModelDoc2 refDoc)
        {
            try
            {
                flatPatternFeature.SetSuppression2(
                    (int)swFeatureSuppressionAction_e.swUnSuppressFeature,
                    (int)swInConfigurationOpts_e.swThisConfiguration, null);
                refDoc.ForceRebuild3(false);
            }
            catch { /* best effort restore */ }
        }

        /// <summary>
        /// Build the binary buffer containing all mesh data (positions, normals, indices).
        /// </summary>
        private byte[] BuildBinaryBuffer(List<MeshData> meshes, out List<BufferViewInfo> bufferViews)
        {
            bufferViews = new List<BufferViewInfo>();

            using (var ms = new MemoryStream())
            using (var bw = new BinaryWriter(ms))
            {
                foreach (var mesh in meshes)
                {
                    // --- Positions (float32 triplets) ---
                    int posOffset = (int)ms.Position;
                    for (int i = 0; i < mesh.Positions.Length; i++)
                        bw.Write(mesh.Positions[i]);
                    int posLength = (int)ms.Position - posOffset;
                    PadToAlignment(bw, ms, 4);
                    bufferViews.Add(new BufferViewInfo
                    {
                        ByteOffset = posOffset,
                        ByteLength = posLength,
                        Target = ARRAY_BUFFER
                    });

                    // --- Normals (float32 triplets) ---
                    int normOffset = (int)ms.Position;
                    for (int i = 0; i < mesh.Normals.Length; i++)
                        bw.Write(mesh.Normals[i]);
                    int normLength = (int)ms.Position - normOffset;
                    PadToAlignment(bw, ms, 4);
                    bufferViews.Add(new BufferViewInfo
                    {
                        ByteOffset = normOffset,
                        ByteLength = normLength,
                        Target = ARRAY_BUFFER
                    });

                    // --- Indices ---
                    int idxOffset = (int)ms.Position;
                    bool useUint32 = (mesh.Positions.Length / 3) >= 65536;
                    for (int i = 0; i < mesh.Indices.Length; i++)
                    {
                        if (useUint32)
                            bw.Write(mesh.Indices[i]);
                        else
                            bw.Write((ushort)mesh.Indices[i]);
                    }
                    int idxLength = (int)ms.Position - idxOffset;
                    PadToAlignment(bw, ms, 4);
                    bufferViews.Add(new BufferViewInfo
                    {
                        ByteOffset = idxOffset,
                        ByteLength = idxLength,
                        Target = ELEMENT_ARRAY_BUFFER,
                        UseUint32 = useUint32
                    });
                }

                bw.Flush();
                return ms.ToArray();
            }
        }

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

        /// <summary>
        /// Build the glTF 2.0 JSON string describing all meshes, materials, and accessors.
        /// </summary>
        private string BuildGltfJson(List<MeshData> meshes, List<BufferViewInfo> bufferViews, int totalBinarySize)
        {
            var sb = new StringBuilder();
            int N = meshes.Count;

            sb.Append("{");

            // asset
            sb.Append("\"asset\":{\"version\":\"2.0\",\"generator\":\"SolidWorksExtractor\"},");

            // scene + scenes
            sb.Append("\"scene\":0,\"scenes\":[{\"nodes\":[");
            for (int i = 0; i < N; i++) { if (i > 0) sb.Append(","); sb.Append(i); }
            sb.Append("]}],");

            // nodes
            sb.Append("\"nodes\":[");
            for (int i = 0; i < N; i++)
            {
                if (i > 0) sb.Append(",");
                sb.Append("{\"mesh\":").Append(i);
                sb.Append(",\"name\":\"").Append(EscapeJson(meshes[i].Name)).Append("\"}");
            }
            sb.Append("],");

            // meshes
            sb.Append("\"meshes\":[");
            for (int i = 0; i < N; i++)
            {
                if (i > 0) sb.Append(",");
                int posAccessor = i * 3;
                int normAccessor = i * 3 + 1;
                int idxAccessor = i * 3 + 2;
                sb.Append("{\"name\":\"").Append(EscapeJson(meshes[i].PartFilename)).Append("\",");
                sb.Append("\"primitives\":[{");
                sb.Append("\"attributes\":{\"POSITION\":").Append(posAccessor);
                sb.Append(",\"NORMAL\":").Append(normAccessor).Append("}");
                sb.Append(",\"indices\":").Append(idxAccessor);
                sb.Append(",\"material\":").Append(i);
                AppendFaceExtras(sb, meshes[i]);
                sb.Append("}]}");
            }
            sb.Append("],");

            // materials — PBR with palette color. Sheet-body-only components
            // (surface-modeled parts in the assembly) are doubleSided so thin
            // surfaces are visible from both sides in three.js.
            sb.Append("\"materials\":[");
            for (int i = 0; i < N; i++)
            {
                if (i > 0) sb.Append(",");
                var c = Palette[meshes[i].PaletteIndex];
                string r = (c.R / 255f).ToString("F4", CultureInfo.InvariantCulture);
                string g = (c.G / 255f).ToString("F4", CultureInfo.InvariantCulture);
                string b = (c.B / 255f).ToString("F4", CultureInfo.InvariantCulture);
                sb.Append("{\"name\":\"").Append(EscapeJson(meshes[i].PartFilename)).Append("\",");
                sb.Append("\"pbrMetallicRoughness\":{");
                sb.Append("\"baseColorFactor\":[").Append(r).Append(",").Append(g).Append(",").Append(b).Append(",1.0],");
                sb.Append("\"metallicFactor\":0.1,\"roughnessFactor\":0.7}");
                if (meshes[i].IsSheetBody) sb.Append(",\"doubleSided\":true");
                sb.Append("}");
            }
            sb.Append("],");

            // accessors — 3 per mesh: positions, normals, indices
            sb.Append("\"accessors\":[");
            bool firstAccessor = true;
            for (int i = 0; i < N; i++)
            {
                int bvBase = i * 3;
                int vertCount = meshes[i].Positions.Length / 3;
                int idxCount = meshes[i].Indices.Length;
                bool useUint32 = vertCount >= 65536;

                // Position accessor (with min/max required by spec)
                if (!firstAccessor) sb.Append(","); firstAccessor = false;
                sb.Append("{\"bufferView\":").Append(bvBase);
                sb.AppendFormat(CultureInfo.InvariantCulture,
                    ",\"componentType\":{0},\"count\":{1},\"type\":\"VEC3\"", FLOAT, vertCount);
                sb.AppendFormat(CultureInfo.InvariantCulture,
                    ",\"min\":[{0:G9},{1:G9},{2:G9}]",
                    meshes[i].BoundsMin[0], meshes[i].BoundsMin[1], meshes[i].BoundsMin[2]);
                sb.AppendFormat(CultureInfo.InvariantCulture,
                    ",\"max\":[{0:G9},{1:G9},{2:G9}]",
                    meshes[i].BoundsMax[0], meshes[i].BoundsMax[1], meshes[i].BoundsMax[2]);
                sb.Append("}");

                // Normal accessor
                sb.Append(",{\"bufferView\":").Append(bvBase + 1);
                sb.AppendFormat(CultureInfo.InvariantCulture,
                    ",\"componentType\":{0},\"count\":{1},\"type\":\"VEC3\"", FLOAT, vertCount);
                sb.Append("}");

                // Index accessor
                int compType = useUint32 ? UNSIGNED_INT : UNSIGNED_SHORT;
                sb.Append(",{\"bufferView\":").Append(bvBase + 2);
                sb.AppendFormat(CultureInfo.InvariantCulture,
                    ",\"componentType\":{0},\"count\":{1},\"type\":\"SCALAR\"", compType, idxCount);
                sb.Append("}");
            }
            sb.Append("],");

            // bufferViews
            sb.Append("\"bufferViews\":[");
            for (int i = 0; i < bufferViews.Count; i++)
            {
                if (i > 0) sb.Append(",");
                var bv = bufferViews[i];
                sb.Append("{\"buffer\":0");
                sb.AppendFormat(CultureInfo.InvariantCulture,
                    ",\"byteOffset\":{0},\"byteLength\":{1},\"target\":{2}",
                    bv.ByteOffset, bv.ByteLength, bv.Target);
                sb.Append("}");
            }
            sb.Append("],");

            // buffers — single buffer
            sb.AppendFormat(CultureInfo.InvariantCulture,
                "\"buffers\":[{{\"byteLength\":{0}}}]", totalBinarySize);

            sb.Append("}");
            return sb.ToString();
        }

        /// <summary>
        /// Write the complete GLB binary file (header + JSON chunk + BIN chunk).
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

        private string EscapeJson(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return s.Replace("\\", "\\\\")
                    .Replace("\"", "\\\"")
                    .Replace("\n", "\\n")
                    .Replace("\r", "\\r")
                    .Replace("\t", "\\t");
        }
    }
}
