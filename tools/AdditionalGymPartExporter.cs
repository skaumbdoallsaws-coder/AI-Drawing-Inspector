using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorksExtractor.Services;

class AdditionalGymPartExporter
{
    [STAThread]
    static int Main(string[] args)
    {
        ISldWorks app = null;
        IModelDoc2 doc = null;
        bool owned = false;
        try
        {
            foreach (string id in new[] { "SldWorks.Application.32", "SldWorks.Application" })
            {
                try { app = (ISldWorks)Marshal.GetActiveObject(id); break; }
                catch (COMException) { }
            }
            if (app == null)
            {
                app = (ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application.32")
                    ?? Type.GetTypeFromProgID("SldWorks.Application"));
                owned = true;
                app.Visible = false;
            }
            int errors = 0, warnings = 0;
            doc = (IModelDoc2)app.OpenDoc6(args[0], (int)swDocumentTypes_e.swDocPART,
                (int)swOpenDocOptions_e.swOpenDocOptions_Silent | (int)swOpenDocOptions_e.swOpenDocOptions_ReadOnly,
                "", ref errors, ref warnings);
            if (doc == null) throw new Exception("Open failed: " + errors);
            IPartDoc part = (IPartDoc)doc;
            int bodies = 0, faces = 0;
            foreach (int kind in new[] { (int)swBodyType_e.swSolidBody, (int)swBodyType_e.swSheetBody })
            {
                object[] visible = part.GetBodies2(kind, true) as object[];
                if (visible == null) continue;
                foreach (object value in visible)
                {
                    bodies++;
                    faces += ((IBody2)value).GetFaceCount();
                }
            }
            var exporter = new GlbExporter();
            string output = exporter.ExportPartBodyGlb(part, doc, args[1], "model");
            if (String.IsNullOrEmpty(output) || !File.Exists(output)) throw new Exception("No GLB exported");
            File.WriteAllText(Path.Combine(args[1], "native-export.json"), new JavaScriptSerializer().Serialize(
                new { visibleBodies = bodies, visibleFaces = faces, errors = errors, warnings = warnings,
                      sourcePath = args[0], sourceUnits = "m", readOnly = true, version = app.RevisionNumber() }));
            return 0;
        }
        catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
        finally
        {
            if (app != null && doc != null) app.CloseDoc(doc.GetTitle());
            if (owned && app != null) app.ExitApp();
        }
    }
}
