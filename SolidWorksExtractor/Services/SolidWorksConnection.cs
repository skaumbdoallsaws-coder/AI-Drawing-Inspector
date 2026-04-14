using System;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace SolidWorksExtractor.Services
{
    /// <summary>
    /// Handles connection to SolidWorks application and document operations
    /// </summary>
    public class SolidWorksConnection : IDisposable
    {
        private ISldWorks _swApp;
        private bool _createdNewInstance;

        public ISldWorks Application => _swApp;
        public bool IsConnected => _swApp != null;

        /// <summary>
        /// Connect to running SolidWorks instance or start new one
        /// </summary>
        /// <param name="startIfNotRunning">Start SolidWorks if not running</param>
        /// <returns>True if connected successfully</returns>
        public bool Connect(bool startIfNotRunning = false)
        {
            try
            {
                // Try to connect to running instance first
                _swApp = (ISldWorks)Marshal.GetActiveObject("SldWorks.Application");
                _createdNewInstance = false;
                Console.WriteLine("Connected to running SolidWorks instance");
                return true;
            }
            catch (COMException)
            {
                if (startIfNotRunning)
                {
                    try
                    {
                        // Start new instance
                        Type swType = Type.GetTypeFromProgID("SldWorks.Application");
                        _swApp = (ISldWorks)Activator.CreateInstance(swType);
                        _swApp.Visible = true;
                        _createdNewInstance = true;
                        Console.WriteLine("Started new SolidWorks instance");
                        return true;
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine($"Failed to start SolidWorks: {ex.Message}");
                        return false;
                    }
                }
                else
                {
                    Console.WriteLine("SolidWorks is not running. Start SolidWorks first or use --start flag.");
                    return false;
                }
            }
        }

        /// <summary>
        /// Get the currently active document
        /// </summary>
        public IModelDoc2 GetActiveDocument()
        {
            if (_swApp == null)
                return null;

            return (IModelDoc2)_swApp.ActiveDoc;
        }

        /// <summary>
        /// Open a document by path
        /// </summary>
        /// <param name="filePath">Full path to the document</param>
        /// <param name="readOnly">Open in read-only mode</param>
        /// <param name="silent">Suppress dialogs</param>
        /// <returns>Opened document or null on failure</returns>
        public IModelDoc2 OpenDocument(string filePath, bool readOnly = true, bool silent = true)
        {
            if (_swApp == null)
                return null;

            int docType = GetDocumentType(filePath);
            if (docType == (int)swDocumentTypes_e.swDocNONE)
            {
                Console.WriteLine($"Unknown file type: {filePath}");
                return null;
            }

            int errors = 0;
            int warnings = 0;

            int options = 0;
            if (silent)
                options |= (int)swOpenDocOptions_e.swOpenDocOptions_Silent;
            if (readOnly)
                options |= (int)swOpenDocOptions_e.swOpenDocOptions_ReadOnly;

            IModelDoc2 doc = (IModelDoc2)_swApp.OpenDoc6(
                filePath,
                docType,
                options,
                "",  // Configuration name (empty = default)
                ref errors,
                ref warnings
            );

            if (doc == null)
            {
                Console.WriteLine($"Failed to open {filePath}. Error: {errors}, Warning: {warnings}");
            }
            else
            {
                Console.WriteLine($"Opened: {System.IO.Path.GetFileName(filePath)}");
            }

            return doc;
        }

        /// <summary>
        /// Resolve lightweight components in an assembly
        /// </summary>
        /// <param name="assemblyDoc">Assembly document</param>
        /// <returns>Number of components resolved</returns>
        public int ResolveLightweightComponents(IAssemblyDoc assemblyDoc)
        {
            if (assemblyDoc == null)
                return 0;

            int resolved = 0;
            object[] components = (object[])assemblyDoc.GetComponents(false);

            if (components == null)
                return 0;

            foreach (object obj in components)
            {
                IComponent2 comp = (IComponent2)obj;
                int state = comp.GetSuppression2();

                if (state == (int)swComponentSuppressionState_e.swComponentLightweight)
                {
                    // Try to resolve
                    int result = comp.SetSuppression2((int)swComponentSuppressionState_e.swComponentFullyResolved);
                    if (result == (int)swSuppressionError_e.swSuppressionChangeOk)
                    {
                        resolved++;
                    }
                }
            }

            if (resolved > 0)
            {
                Console.WriteLine($"Resolved {resolved} lightweight components");
            }

            return resolved;
        }

        /// <summary>
        /// Get document type from file extension
        /// </summary>
        private int GetDocumentType(string filePath)
        {
            string ext = System.IO.Path.GetExtension(filePath).ToLower();
            switch (ext)
            {
                case ".sldprt":
                    return (int)swDocumentTypes_e.swDocPART;
                case ".sldasm":
                    return (int)swDocumentTypes_e.swDocASSEMBLY;
                case ".slddrw":
                    return (int)swDocumentTypes_e.swDocDRAWING;
                default:
                    return (int)swDocumentTypes_e.swDocNONE;
            }
        }

        /// <summary>
        /// Get SolidWorks version string
        /// </summary>
        public string GetVersionString()
        {
            if (_swApp == null)
                return "Unknown";

            string revision = "";
            string version = _swApp.RevisionNumber();

            // Parse version number (e.g., "31.0.0" for SW2023)
            if (!string.IsNullOrEmpty(version))
            {
                string[] parts = version.Split('.');
                if (parts.Length > 0 && int.TryParse(parts[0], out int major))
                {
                    int year = 1992 + major;  // SW version numbering
                    revision = $"SolidWorks {year} (v{version})";
                }
            }

            return string.IsNullOrEmpty(revision) ? version : revision;
        }

        /// <summary>
        /// Enable command-in-progress mode for better performance
        /// </summary>
        public void EnableBatchMode(bool enable)
        {
            if (_swApp != null)
            {
                try
                {
                    _swApp.CommandInProgress = enable;
                }
                catch (COMException ex)
                {
                    Console.WriteLine($"  Warning: Could not set CommandInProgress={enable}: {ex.Message}");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"  Warning: Could not set CommandInProgress={enable}: {ex.Message}");
                }
            }
        }

        /// <summary>
        /// Force rebuild on a document to ensure geometry is up to date
        /// </summary>
        /// <param name="doc">Document to rebuild</param>
        /// <returns>True if rebuild succeeded</returns>
        public bool ForceRebuild(IModelDoc2 doc)
        {
            if (doc == null)
                return false;

            try
            {
                // Force rebuild all configurations
                bool result = doc.ForceRebuild3(false);  // false = don't rebuild only active config
                return result;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"  Warning: Rebuild failed: {ex.Message}");
                return false;
            }
        }

        /// <summary>
        /// Close a document without saving
        /// </summary>
        /// <param name="doc">Document to close</param>
        public void CloseDocument(IModelDoc2 doc)
        {
            if (_swApp == null || doc == null)
                return;

            try
            {
                string pathName = doc.GetPathName();
                _swApp.CloseDoc(pathName);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"  Warning: Error closing document: {ex.Message}");
            }
        }

        /// <summary>
        /// Open a document silently for batch processing
        /// </summary>
        /// <param name="filePath">Full path to the document</param>
        /// <returns>Tuple of (document, errorCode) - document is null on failure</returns>
        public (IModelDoc2 doc, int errors, int warnings) OpenDocumentSilent(string filePath)
        {
            if (_swApp == null)
                return (null, -1, 0);

            int docType = GetDocumentType(filePath);
            if (docType == (int)swDocumentTypes_e.swDocNONE)
            {
                return (null, -2, 0);
            }

            int errors = 0;
            int warnings = 0;

            // Silent + ReadOnly for batch processing
            int options = (int)swOpenDocOptions_e.swOpenDocOptions_Silent |
                          (int)swOpenDocOptions_e.swOpenDocOptions_ReadOnly;

            IModelDoc2 doc = (IModelDoc2)_swApp.OpenDoc6(
                filePath,
                docType,
                options,
                "",  // Configuration name (empty = default)
                ref errors,
                ref warnings
            );

            return (doc, errors, warnings);
        }

        public void Dispose()
        {
            if (_swApp != null)
            {
                // Only close if we started it
                if (_createdNewInstance)
                {
                    try
                    {
                        _swApp.ExitApp();
                    }
                    catch { }
                }

                Marshal.ReleaseComObject(_swApp);
                _swApp = null;
            }
        }
    }
}
