using System;
using System.Collections.Generic;
using System.IO;
using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorksExtractor.Services;

class GymAssemblyExporter
{
    [STAThread]
    static int Main(string[] args)
    {
        ISldWorks app = null;
        IModelDoc2 doc = null;
        try
        {
            app = (ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application.32")
                ?? Type.GetTypeFromProgID("SldWorks.Application"));
            app.Visible = false;
            app.SetCurrentWorkingDirectory(Path.GetDirectoryName(args[0]));
            int errors = 0, warnings = 0;
            bool interchange = !args[0].EndsWith(".sldasm", StringComparison.OrdinalIgnoreCase);
            if (interchange)
                doc = (IModelDoc2)app.LoadFile4(args[0], "r", app.GetImportFileData(args[0]), ref errors);
            else
                doc = (IModelDoc2)app.OpenDoc6(args[0], (int)swDocumentTypes_e.swDocASSEMBLY,
                    (int)swOpenDocOptions_e.swOpenDocOptions_Silent | (int)swOpenDocOptions_e.swOpenDocOptions_ReadOnly,
                    "", ref errors, ref warnings);
            if (doc == null) throw new Exception("Assembly open failed: " + errors);
            if (doc.GetType() == (int)swDocumentTypes_e.swDocPART)
            {
                IPartDoc part = (IPartDoc)doc;
                int bodyCount = 0, faceCount = 0;
                foreach (int kind in new[] { (int)swBodyType_e.swSolidBody, (int)swBodyType_e.swSheetBody })
                {
                    object[] bodies = part.GetBodies2(kind, true) as object[];
                    if (bodies == null) continue;
                    foreach (object body in bodies) { bodyCount++; faceCount += ((IBody2)body).GetFaceCount(); }
                }
                string bodyOutput = new GlbExporter().ExportPartBodyGlb(part, doc, args[1], "model");
                if (String.IsNullOrEmpty(bodyOutput) || !File.Exists(bodyOutput)) throw new Exception("No part GLB exported");
                File.WriteAllText(Path.Combine(args[1], "native-export.json"), new JavaScriptSerializer().Serialize(
                    new { visibleBodies = bodyCount, visibleFaces = faceCount, errors = errors, warnings = warnings,
                          sourcePath = args[0], sourceUnits = "m", interchangeImport = interchange, version = app.RevisionNumber() }));
                return 0;
            }
            IAssemblyDoc assembly = (IAssemblyDoc)doc;
            int resolveResult = assembly.ResolveAllLightWeightComponents(false);
            var parts = new List<string>();
            var missing = new List<string>();
            var suppressed = new List<string>();
            object[] components = assembly.GetComponents(false) as object[];
            if (components == null) throw new Exception("Assembly contains no components");
            foreach (object value in components)
            {
                IComponent2 component = (IComponent2)value;
                if (component.GetSuppression2() == (int)swComponentSuppressionState_e.swComponentSuppressed)
                {
                    suppressed.Add(component.Name2);
                    continue;
                }
                IModelDoc2 model = component.GetModelDoc2() as IModelDoc2;
                if (model == null) missing.Add(component.Name2);
                else if (model.GetType() == (int)swDocumentTypes_e.swDocPART) parts.Add(component.Name2);
            }
            File.WriteAllText(Path.Combine(args[1], "native-export.json"), new JavaScriptSerializer().Serialize(
                new { componentCount = components.Length, partInstances = parts, missing = missing,
                    suppressed = suppressed, errors = errors, warnings = warnings, resolveResult = resolveResult,
                    sourcePath = args[0], sourceUnits = "m", readOnly = true, version = app.RevisionNumber() }));
            if (missing.Count > 0) throw new Exception("Unresolved components: " + String.Join(", ", missing));
            string output = new GlbExporter().ExportGlb(assembly, args[1], "model");
            if (String.IsNullOrEmpty(output) || !File.Exists(output)) throw new Exception("No assembly GLB exported");
            return 0;
        }
        catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
        finally
        {
            if (app != null && doc != null) app.CloseDoc(doc.GetTitle());
            if (app != null) app.ExitApp();
        }
    }
}
