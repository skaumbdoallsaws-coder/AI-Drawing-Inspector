"""
Parse SolidWorks Full Tree V2 output into structured JSON.
Creates:
1. Part mapping (old PN -> new PN -> description)
2. Assembly hierarchy
3. Mating context for inspector
"""

import re
import json
from collections import defaultdict

def parse_tree_file(filepath):
    """Parse the SolidWorks tree extraction file."""

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split into component blocks
    # Each block starts with [N] or [ROOT]
    blocks = re.split(r'\n(?=\s*\[\d+\]|\[ROOT\])', content)

    parts = {}
    assemblies = {}
    hierarchy = {"root": None, "children": defaultdict(list)}

    current_path = []

    for block in blocks:
        if not block.strip():
            continue

        # Parse level and name
        level_match = re.search(r'\[(\d+|ROOT)\]\s*(.+?)(?:\n|$)', block)
        if not level_match:
            continue

        level = level_match.group(1)
        name = level_match.group(2).strip()

        # Parse properties
        props = {}
        for line in block.split('\n'):
            # Match property lines like "DESCRIPTION: PIN LOWER SPRING"
            prop_match = re.match(r'\s+([A-Z_]+(?:\s*\d*)?)\s*:\s*(.+)$', line)
            if prop_match:
                key = prop_match.group(1).strip()
                value = prop_match.group(2).strip()
                if value:  # Only store non-empty values
                    props[key] = value

        # Determine type
        type_match = re.search(r'Type:\s*(PART|SUBASSY|ASSEMBLY)', block)
        comp_type = type_match.group(1) if type_match else "UNKNOWN"

        # Extract key fields
        old_pn = props.get('ID', props.get('Id.', name))
        new_pn = props.get('PART_NUMBER', '')
        description = props.get('DESCRIPTION', props.get('Descr.', ''))
        material = props.get('MATERIAL', props.get('Mat.', ''))
        make_buy = props.get('MAKE_BUY', '')

        # Clean up old_pn (remove instance numbers)
        old_pn_clean = re.sub(r'-\d+$', '', old_pn)

        # Build component record
        component = {
            "old_pn": old_pn_clean,
            "new_pn": new_pn,
            "description": description,
            "type": comp_type,
            "material": material,
            "make_buy": make_buy,
        }

        # Store in appropriate dict
        if comp_type == "PART":
            if old_pn_clean not in parts:
                parts[old_pn_clean] = component
        else:  # ASSEMBLY or SUBASSY
            if old_pn_clean not in assemblies:
                assemblies[old_pn_clean] = component
                assemblies[old_pn_clean]["children"] = []

    return parts, assemblies

def build_mapping_table(parts, assemblies):
    """Build a simple old -> new PN mapping table."""
    mapping = {}

    for old_pn, data in parts.items():
        if data["new_pn"]:
            mapping[old_pn] = {
                "new_pn": data["new_pn"],
                "description": data["description"],
                "type": "PART"
            }

    for old_pn, data in assemblies.items():
        if data["new_pn"]:
            mapping[old_pn] = {
                "new_pn": data["new_pn"],
                "description": data["description"],
                "type": data["type"]
            }

    return mapping

def main():
    input_file = "046-935_full_tree_v2.txt"

    print(f"Parsing {input_file}...")
    parts, assemblies = parse_tree_file(input_file)

    print(f"Found {len(parts)} unique parts")
    print(f"Found {len(assemblies)} unique assemblies")

    # Build mapping table
    mapping = build_mapping_table(parts, assemblies)

    # Save parts database
    with open("sw_parts_database.json", 'w', encoding='utf-8') as f:
        json.dump(parts, f, indent=2, ensure_ascii=False)
    print(f"Saved parts database to sw_parts_database.json")

    # Save assemblies database
    with open("sw_assemblies_database.json", 'w', encoding='utf-8') as f:
        json.dump(assemblies, f, indent=2, ensure_ascii=False)
    print(f"Saved assemblies database to sw_assemblies_database.json")

    # Save mapping table
    with open("sw_pn_mapping.json", 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)
    print(f"Saved PN mapping to sw_pn_mapping.json")

    # Print sample
    print("\n" + "="*60)
    print("SAMPLE MAPPINGS:")
    print("="*60)
    count = 0
    for old_pn, data in mapping.items():
        if count >= 15:
            break
        print(f"{old_pn:40} -> {data['new_pn']:15} ({data['description'][:30]})")
        count += 1

    print(f"\n... and {len(mapping) - 15} more entries")

if __name__ == "__main__":
    main()
