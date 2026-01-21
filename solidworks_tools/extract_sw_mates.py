"""
SolidWorks Assembly Mate Extractor
Extracts mating relationships and interface data from a SolidWorks assembly.

Requirements:
- SolidWorks installed and running with assembly open
- pywin32: pip install pywin32

Usage:
1. Open your assembly in SolidWorks
2. Run this script
"""

import win32com.client
import pythoncom
import json
import os
from datetime import datetime

def connect_to_solidworks():
    """Connect to running SolidWorks instance."""
    try:
        pythoncom.CoInitialize()

        # Get running SolidWorks instance
        sw = win32com.client.GetActiveObject("SldWorks.Application")

        print(f"Connected to SolidWorks")

        return sw
    except Exception as e:
        print(f"GetActiveObject failed: {e}")
        print("Trying Dispatch method...")
        try:
            sw = win32com.client.Dispatch("SldWorks.Application")
            sw.Visible = True
            return sw
        except Exception as e2:
            print(f"Dispatch also failed: {e2}")
            print("\nMake sure:")
            print("1. SolidWorks is running")
            print("2. An assembly is open")
            print("3. Try running this script as Administrator")
            return None

def get_mate_type_name(mate_type):
    """Convert mate type constant to readable name."""
    mate_types = {
        0: "Coincident",
        1: "Concentric",
        2: "Perpendicular",
        3: "Parallel",
        4: "Tangent",
        5: "Distance",
        6: "Angle",
        7: "Unknown",
        8: "Symmetric",
        9: "CamFollower",
        10: "Gear",
        11: "Width",
        12: "Lock",
        13: "Screw",
        14: "Linear/Linear Coupler",
        15: "Path",
        16: "Slot",
        17: "Hinge",
        18: "Rack Pinion",
        19: "Universal Joint",
    }
    return mate_types.get(mate_type, f"Unknown({mate_type})")

def extract_component_info(component):
    """Extract information from a component."""
    try:
        info = {
            "name": component.Name2 if component.Name2 else "Unknown",
            "path": component.GetPathName() if component.GetPathName() else "",
            "suppressed": component.IsSuppressed(),
        }

        # Try to get custom properties
        try:
            model_doc = component.GetModelDoc2()
            if model_doc:
                config_name = model_doc.ConfigurationManager.ActiveConfiguration.Name
                custom_prop_mgr = model_doc.Extension.CustomPropertyManager(config_name)

                # Common property names to look for
                prop_names = ["Description", "PartNumber", "Material", "Finish",
                              "Thread", "Tolerance", "Diameter", "Length"]

                properties = {}
                for prop in prop_names:
                    try:
                        result = custom_prop_mgr.Get5(prop, False, "", "", False)
                        if result and result[2]:  # Resolved value
                            properties[prop] = result[2]
                    except:
                        pass

                if properties:
                    info["properties"] = properties
        except Exception as prop_error:
            pass

        return info
    except Exception as e:
        return {"name": "Error", "error": str(e)}

def extract_mate_info(mate):
    """Extract information from a mate feature."""
    try:
        mate_info = {
            "name": mate.Name if mate.Name else "Unnamed",
            "type": get_mate_type_name(mate.Type),
            "type_id": mate.Type,
            "components": [],
        }

        # Get mate entities count
        try:
            entity_count = mate.GetMateEntityCount()
            for i in range(entity_count):
                entity = mate.MateEntity(i)
                if entity:
                    comp = entity.ReferenceComponent
                    if comp:
                        mate_info["components"].append(comp.Name2)
        except:
            pass

        # Get distance/angle value for applicable mates
        try:
            if mate.Type == 5:  # Distance
                mate_info["distance_mm"] = mate.Distance * 1000  # Convert to mm
            elif mate.Type == 6:  # Angle
                mate_info["angle_deg"] = mate.Angle * 57.2958  # Convert to degrees
        except:
            pass

        return mate_info
    except Exception as e:
        return {"name": "Error", "error": str(e)}

def extract_assembly_data(sw):
    """Extract all mating data from the active assembly."""

    model = sw.ActiveDoc

    if not model:
        print("No document open!")
        print("\nTrying to get first open document...")

        # Try getting documents differently
        try:
            doc = sw.GetFirstDocument()
            while doc:
                print(f"  Found: {doc.GetTitle()} (Type: {doc.GetType()})")
                if doc.GetType() == 2:  # Assembly
                    model = doc
                    break
                doc = doc.GetNext()
        except Exception as e:
            print(f"  Error iterating docs: {e}")

    if not model:
        print("\nNo assembly found. Please make sure:")
        print("1. SolidWorks has an assembly (.SLDASM) open")
        print("2. The assembly window is active/focused")
        return None

    doc_type = model.GetType()
    print(f"Document: {model.GetTitle()} (Type: {doc_type})")

    if doc_type != 2:  # 2 = Assembly
        print(f"Document is not an assembly (type={doc_type})")
        print("Type 1 = Part, Type 2 = Assembly, Type 3 = Drawing")
        return None

    print(f"Processing assembly: {model.GetTitle()}")

    assembly_data = {
        "assembly_name": model.GetTitle(),
        "file_path": model.GetPathName(),
        "extracted_date": datetime.now().isoformat(),
        "components": [],
        "mates": [],
        "mating_relationships": []
    }

    # Get root component
    try:
        config = model.GetActiveConfiguration()
        root_component = config.GetRootComponent3(True)
    except Exception as e:
        print(f"Error getting root component: {e}")
        return assembly_data

    # Extract components
    print("\nExtracting components...")
    try:
        components = root_component.GetChildren()
        if components:
            for comp in components:
                comp_info = extract_component_info(comp)
                assembly_data["components"].append(comp_info)
                print(f"  - {comp_info['name']}")
    except Exception as e:
        print(f"Error extracting components: {e}")

    print(f"Found {len(assembly_data['components'])} components")

    # Extract mates
    print("\nExtracting mates...")
    try:
        feature = model.FirstFeature()
        while feature:
            feat_type = feature.GetTypeName2()

            if feat_type == "MateGroup":
                sub_feature = feature.GetFirstSubFeature()
                while sub_feature:
                    sub_type = sub_feature.GetTypeName2()

                    if "Mate" in sub_type:
                        try:
                            mate = sub_feature.GetSpecificFeature2()
                            if mate:
                                mate_info = extract_mate_info(mate)
                                assembly_data["mates"].append(mate_info)

                                # Build relationship
                                comps = mate_info.get("components", [])
                                if len(comps) >= 2:
                                    rel = {
                                        "part_a": comps[0],
                                        "part_b": comps[1],
                                        "relationship": mate_info["type"],
                                    }
                                    if "distance_mm" in mate_info:
                                        rel["distance_mm"] = mate_info["distance_mm"]
                                    if "angle_deg" in mate_info:
                                        rel["angle_deg"] = mate_info["angle_deg"]
                                    assembly_data["mating_relationships"].append(rel)

                                print(f"  - {mate_info['name']}: {mate_info['type']} {comps}")
                        except Exception as me:
                            print(f"  - Error reading mate: {me}")

                    sub_feature = sub_feature.GetNextSubFeature()

            feature = feature.GetNextFeature()

    except Exception as e:
        print(f"Error extracting mates: {e}")

    print(f"Found {len(assembly_data['mates'])} mates")

    return assembly_data

def main():
    print("=" * 60)
    print("SolidWorks Assembly Mate Extractor")
    print("=" * 60)

    sw = connect_to_solidworks()
    if not sw:
        return

    data = extract_assembly_data(sw)
    if not data:
        return

    # Save to JSON
    output_file = f"{data['assembly_name'].replace('.SLDASM', '').replace(' ', '_')}_mates.json"
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_file)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"Saved to: {output_path}")
    print(f"{'=' * 60}")

    print(f"\nSummary:")
    print(f"  Components: {len(data['components'])}")
    print(f"  Mates: {len(data['mates'])}")
    print(f"  Relationships: {len(data['mating_relationships'])}")

    if data['mating_relationships']:
        print(f"\nSample relationships:")
        for rel in data['mating_relationships'][:10]:
            extra = ""
            if 'distance_mm' in rel:
                extra = f" ({rel['distance_mm']:.2f}mm)"
            elif 'angle_deg' in rel:
                extra = f" ({rel['angle_deg']:.1f}°)"
            print(f"  {rel['part_a']} <--{rel['relationship']}{extra}--> {rel['part_b']}")

if __name__ == "__main__":
    main()
