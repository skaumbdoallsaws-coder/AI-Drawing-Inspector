using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorksExtractor.Models;

namespace SolidWorksExtractor.Services
{
    /// <summary>
    /// Extracts custom properties, material, and physical properties from parts
    /// </summary>
    public class PropertyExtractor
    {
        /// <summary>
        /// Extract all identity and physical properties from a part
        /// </summary>
        public PartIdentity ExtractIdentity(IModelDoc2 doc)
        {
            var identity = new PartIdentity();

            if (doc == null)
                return identity;

            // Get custom property manager for file-level properties
            ICustomPropertyManager filePropMgr = doc.Extension.CustomPropertyManager[""];

            // Extract standard properties (try multiple common property name variations)
            identity.PartNumber = GetPropertyValue(filePropMgr, "PartNumber", "Part Number", "PART_NUMBER", "Part_Number", "Number", "PN", "P/N", "ItemNumber", "Item Number");
            identity.Description = GetPropertyValue(filePropMgr, "Description", "Desc", "Title", "DESCRIPTION");
            identity.Revision = GetPropertyValue(filePropMgr, "Revision", "Rev", "Revision Level");
            identity.Author = GetPropertyValue(filePropMgr, "Author", "DrawnBy", "Drawn By", "Designer");
            identity.Material = GetPropertyValue(filePropMgr, "Material", "MaterialName");
            identity.Finish = GetPropertyValue(filePropMgr, "Finish", "Surface Finish", "SurfaceFinish");

            // Get all custom properties
            identity.CustomProperties = GetAllProperties(filePropMgr);

            // Get configuration-specific properties if applicable
            IConfiguration activeConfig = (IConfiguration)doc.GetActiveConfiguration();
            if (activeConfig != null)
            {
                ICustomPropertyManager configPropMgr = activeConfig.CustomPropertyManager;
                identity.ConfigProperties = GetAllProperties(configPropMgr);

                // Config properties can override file properties
                if (string.IsNullOrEmpty(identity.PartNumber))
                    identity.PartNumber = GetPropertyValue(configPropMgr, "PartNumber", "Part Number", "PART_NUMBER", "Number");
                if (string.IsNullOrEmpty(identity.Description))
                    identity.Description = GetPropertyValue(configPropMgr, "Description", "Desc", "DESCRIPTION");
            }

            // Final fallback: search CustomProperties dictionary for part number variations
            if (string.IsNullOrEmpty(identity.PartNumber) && identity.CustomProperties != null)
            {
                // Try exact matches first, then case-insensitive
                string[] partNumberKeys = { "PART_NUMBER", "PartNumber", "Part Number", "Number", "PN", "P/N", "ItemNumber" };
                foreach (var key in partNumberKeys)
                {
                    if (identity.CustomProperties.TryGetValue(key, out string val) && !string.IsNullOrEmpty(val))
                    {
                        identity.PartNumber = val;
                        break;
                    }
                }

                // If still null, try case-insensitive search for any key containing "part" and "number"
                if (string.IsNullOrEmpty(identity.PartNumber))
                {
                    var match = identity.CustomProperties.FirstOrDefault(kvp =>
                        kvp.Key.ToUpperInvariant().Contains("PART") &&
                        kvp.Key.ToUpperInvariant().Contains("NUMBER") &&
                        !string.IsNullOrEmpty(kvp.Value));
                    if (!string.IsNullOrEmpty(match.Value))
                        identity.PartNumber = match.Value;
                }
            }

            return identity;
        }

        /// <summary>
        /// Extract physical properties (mass, volume, bounding box)
        /// </summary>
        public PhysicalProperties ExtractPhysicalProperties(IModelDoc2 doc)
        {
            var props = new PhysicalProperties();

            if (doc == null)
                return props;

            // Get document unit system
            int lengthUnit = doc.Extension.GetUserPreferenceInteger(
                (int)swUserPreferenceIntegerValue_e.swUnitsLinear,
                (int)swUserPreferenceOption_e.swDetailingNoOptionSpecified);

            int massUnit = doc.Extension.GetUserPreferenceInteger(
                (int)swUserPreferenceIntegerValue_e.swUnitsMassPropMass,
                (int)swUserPreferenceOption_e.swDetailingNoOptionSpecified);

            int angleUnit = doc.Extension.GetUserPreferenceInteger(
                (int)swUserPreferenceIntegerValue_e.swUnitsAngular,
                (int)swUserPreferenceOption_e.swDetailingNoOptionSpecified);

            props.LengthUnit = GetLengthUnitString(lengthUnit);
            props.MassUnit = GetMassUnitString(massUnit);
            props.AngleUnit = GetAngleUnitString(angleUnit);
            props.DocUnitSystem = DetermineUnitSystem(lengthUnit, massUnit);

            // Get mass properties
            try
            {
                IPartDoc partDoc = doc as IPartDoc;
                if (partDoc != null)
                {
                    object[] bodies = (object[])partDoc.GetBodies2((int)swBodyType_e.swSolidBody, true);
                    if (bodies != null && bodies.Length > 0)
                    {
                        // Get mass properties from extension
                        int status = 0;
                        double[] massProps = (double[])doc.Extension.GetMassProperties(1, ref status);

                        if (massProps != null && status == 0)
                        {
                            // massProps array:
                            // [0-2] Center of mass X, Y, Z
                            // [3] Volume
                            // [4] Surface area
                            // [5] Mass
                            // [6-8] Principal moments of inertia
                            // [9-11] Principal axes of inertia

                            props.CenterOfMass = new double[] { massProps[0], massProps[1], massProps[2] };
                            props.Volume = massProps[3];
                            props.SurfaceArea = massProps[4];
                            props.Mass = massProps[5];
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: Could not get mass properties: {ex.Message}");
            }

            // Get bounding box
            props.BoundingBox = ExtractBoundingBox(doc);

            // Get assigned material
            try
            {
                IPartDoc partDoc = doc as IPartDoc;
                if (partDoc != null)
                {
                    string matName = partDoc.MaterialIdName;
                    if (!string.IsNullOrEmpty(matName))
                    {
                        // Format is "database|material_name"
                        string[] parts = matName.Split('|');
                        if (parts.Length >= 2)
                        {
                            props.MaterialDatabase = parts[0];
                            props.AssignedMaterial = parts[1];
                        }
                        else
                        {
                            props.AssignedMaterial = matName;
                        }
                    }
                }
            }
            catch { }

            return props;
        }

        /// <summary>
        /// Extract bounding box dimensions
        /// </summary>
        public BoundingBox ExtractBoundingBox(IModelDoc2 doc)
        {
            var bbox = new BoundingBox();

            try
            {
                IPartDoc partDoc = doc as IPartDoc;
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
                            bbox.MinX = minX;
                            bbox.MinY = minY;
                            bbox.MinZ = minZ;
                            bbox.MaxX = maxX;
                            bbox.MaxY = maxY;
                            bbox.MaxZ = maxZ;
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: Could not get bounding box: {ex.Message}");
            }

            return bbox;
        }

        /// <summary>
        /// Extract all configurations from a part
        /// </summary>
        public List<ConfigurationData> ExtractConfigurations(IModelDoc2 doc)
        {
            var configs = new List<ConfigurationData>();

            if (doc == null)
                return configs;

            try
            {
                string[] configNames = (string[])doc.GetConfigurationNames();
                string activeConfigName = ((IConfiguration)doc.GetActiveConfiguration())?.Name ?? "";

                if (configNames != null)
                {
                    foreach (string configName in configNames)
                    {
                        IConfiguration config = (IConfiguration)doc.GetConfigurationByName(configName);
                        if (config != null)
                        {
                            var configData = new ConfigurationData
                            {
                                Name = configName,
                                IsActive = configName == activeConfigName,
                                Description = config.Description
                            };

                            // Get config-specific properties
                            ICustomPropertyManager propMgr = config.CustomPropertyManager;
                            configData.Properties = GetAllProperties(propMgr);

                            // Get parameters/dimensions if available
                            // This would require iterating through equations or dimension values

                            configs.Add(configData);
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: Could not extract configurations: {ex.Message}");
            }

            return configs;
        }

        /// <summary>
        /// Get property value trying multiple possible names
        /// </summary>
        private string GetPropertyValue(ICustomPropertyManager propMgr, params string[] names)
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

        /// <summary>
        /// Get all custom properties as dictionary
        /// </summary>
        private Dictionary<string, string> GetAllProperties(ICustomPropertyManager propMgr)
        {
            var props = new Dictionary<string, string>();

            if (propMgr == null)
                return props;

            // Method 1: Try GetNames + Get6 (more reliable across versions)
            try
            {
                object namesObj = propMgr.GetNames();
                if (namesObj is string[] propNames && propNames.Length > 0)
                {
                    foreach (string name in propNames)
                    {
                        if (string.IsNullOrEmpty(name))
                            continue;

                        string valOut, resolvedValOut;
                        bool wasResolved, linkToProperty;

                        int result = propMgr.Get6(name, false, out valOut, out resolvedValOut, out wasResolved, out linkToProperty);

                        if (result == (int)swCustomInfoGetResult_e.swCustomInfoGetResult_ResolvedValue ||
                            result == (int)swCustomInfoGetResult_e.swCustomInfoGetResult_CachedValue ||
                            result == 0)  // Success
                        {
                            string value = !string.IsNullOrEmpty(resolvedValOut) ? resolvedValOut : valOut;
                            props[name] = value ?? "";
                        }
                    }
                    return props;
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: GetNames failed: {ex.Message}");
            }

            // Method 2: Fallback to GetAll3
            try
            {
                object propNamesObj = null, propTypesObj = null, propValuesObj = null;
                object resolvedValuesObj = null, propLinkedObj = null;

                int count = propMgr.GetAll3(ref propNamesObj, ref propTypesObj, ref propValuesObj,
                                            ref resolvedValuesObj, ref propLinkedObj);

                if (count > 0 && propNamesObj != null)
                {
                    string[] propNames = (string[])propNamesObj;
                    string[] resolvedValues = resolvedValuesObj as string[];
                    string[] propValues = propValuesObj as string[];

                    for (int i = 0; i < count; i++)
                    {
                        string value = (resolvedValues != null && !string.IsNullOrEmpty(resolvedValues[i]))
                            ? resolvedValues[i]
                            : (propValues != null ? propValues[i] : "");
                        if (!string.IsNullOrEmpty(propNames[i]))
                        {
                            props[propNames[i]] = value ?? "";
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: GetAll3 failed: {ex.Message}");
            }

            return props;
        }

        /// <summary>
        /// Convert length unit enum to string
        /// </summary>
        private string GetLengthUnitString(int unit)
        {
            switch ((swLengthUnit_e)unit)
            {
                case swLengthUnit_e.swMM: return "mm";
                case swLengthUnit_e.swCM: return "cm";
                case swLengthUnit_e.swMETER: return "m";
                case swLengthUnit_e.swINCHES: return "in";
                case swLengthUnit_e.swFEET: return "ft";
                case swLengthUnit_e.swMICRON: return "um";
                default: return "unknown";
            }
        }

        /// <summary>
        /// Convert mass unit enum to string
        /// </summary>
        private string GetMassUnitString(int unit)
        {
            // swUnitsMassPropMass values
            switch (unit)
            {
                case 0: return "kg";
                case 1: return "g";
                case 2: return "mg";
                case 3: return "lb";
                case 4: return "oz";
                default: return "unknown";
            }
        }

        /// <summary>
        /// Convert angle unit enum to string
        /// </summary>
        private string GetAngleUnitString(int unit)
        {
            // swAngleUnit_e
            switch (unit)
            {
                case 0: return "deg";
                case 1: return "rad";
                default: return "deg";
            }
        }

        /// <summary>
        /// Determine the overall unit system from length and mass units
        /// </summary>
        private string DetermineUnitSystem(int lengthUnit, int massUnit)
        {
            // Common SolidWorks unit systems:
            // IPS = Inch-Pound-Second (in, lb)
            // MMGS = Millimeter-Gram-Second (mm, g)
            // CGS = Centimeter-Gram-Second (cm, g)
            // MKS = Meter-Kilogram-Second (m, kg)

            string length = GetLengthUnitString(lengthUnit);
            string mass = GetMassUnitString(massUnit);

            if (length == "in" && (mass == "lb" || mass == "oz"))
                return "IPS";
            if (length == "mm" && (mass == "g" || mass == "mg"))
                return "MMGS";
            if (length == "cm" && mass == "g")
                return "CGS";
            if (length == "m" && mass == "kg")
                return "MKS";
            if (length == "ft" && mass == "lb")
                return "FPS";

            // Custom or mixed
            return $"Custom ({length}, {mass})";
        }
    }
}
