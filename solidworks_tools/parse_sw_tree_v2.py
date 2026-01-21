"""
Parse SolidWorks Full Tree V2 - Improved Parser
Captures all components with full context.
"""

import re
import json

def parse_tree_file(filepath):
    """Parse the SolidWorks tree extraction file."""

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    components = []
    current_component = None
    current_level = 0
    hierarchy_stack = []  # Track parent assemblies

    for line in content.split('\n'):
        # Check for component header [N] name
        level_match = re.match(r'^(\s*)\[(\d+)\]\s*(.+)$', line)
        if level_match:
            # Save previous component
            if current_component:
                components.append(current_component)

            indent = len(level_match.group(1))
            level = int(level_match.group(2))
            name = level_match.group(3).strip()

            # Update hierarchy stack
            while hierarchy_stack and hierarchy_stack[-1]['level'] >= level:
                hierarchy_stack.pop()

            parent = hierarchy_stack[-1]['name'] if hierarchy_stack else "ROOT"

            current_component = {
                'name': name,
                'level': level,
                'parent': parent,
                'type': None,
                'config': None,
                'file': None,
                'id': None,
                'part_number': None,
                'description': None,
                'material': None,
                'make_buy': None,
            }
            current_level = level
            continue

        # Parse properties for current component
        if current_component:
            # Type
            type_match = re.match(r'\s+Type:\s*(\S+)', line)
            if type_match:
                current_component['type'] = type_match.group(1)
                if current_component['type'] in ['SUBASSY', 'ASSEMBLY']:
                    hierarchy_stack.append({
                        'name': current_component['name'],
                        'level': current_component['level']
                    })
                continue

            # Config
            config_match = re.match(r'\s+Config:\s*(.+)$', line)
            if config_match:
                current_component['config'] = config_match.group(1).strip()
                continue

            # File
            file_match = re.match(r'\s+File:\s*(.+)$', line)
            if file_match:
                current_component['file'] = file_match.group(1).strip()
                continue

            # ID (old PN)
            id_match = re.match(r'\s+ID:\s*(.+)$', line)
            if id_match and not current_component['id']:
                current_component['id'] = id_match.group(1).strip()
                continue

            # PART_NUMBER (new PN)
            pn_match = re.match(r'\s+PART_NUMBER:\s*(\S+)', line)
            if pn_match:
                current_component['part_number'] = pn_match.group(1).strip()
                continue

            # DESCRIPTION
            desc_match = re.match(r'\s+DESCRIPTION:\s*(.+)$', line)
            if desc_match and not current_component['description']:
                current_component['description'] = desc_match.group(1).strip()
                continue

            # MATERIAL
            mat_match = re.match(r'\s+MATERIAL:\s*(.+)$', line)
            if mat_match:
                current_component['material'] = mat_match.group(1).strip()
                continue

            # MAKE_BUY
            mb_match = re.match(r'\s+MAKE_BUY:\s*(.+)$', line)
            if mb_match:
                current_component['make_buy'] = mb_match.group(1).strip()
                continue

    # Don't forget last component
    if current_component:
        components.append(current_component)

    return components

def build_structure(components):
    """Build assembly structure with mating context."""

    # Group by parent
    structure = {}
    parts_db = {}
    assemblies_db = {}

    for comp in components:
        parent = comp['parent']

        if parent not in structure:
            structure[parent] = []

        structure[parent].append({
            'name': comp['name'],
            'type': comp['type'],
            'part_number': comp['part_number'],
            'description': comp['description'],
        })

        # Build flat databases
        key = comp['part_number'] or comp['id'] or comp['name']

        record = {
            'old_pn': comp['id'],
            'new_pn': comp['part_number'],
            'description': comp['description'],
            'type': comp['type'],
            'material': comp['material'],
            'make_buy': comp['make_buy'],
            'file': comp['file'],
            'parent_assembly': parent,
        }

        if comp['type'] == 'PART':
            if key not in parts_db:
                parts_db[key] = record
        else:
            if key not in assemblies_db:
                assemblies_db[key] = record

    return structure, parts_db, assemblies_db

def build_mating_context(structure, parts_db):
    """Build mating context - siblings in same assembly."""

    context_db = {}

    for parent, children in structure.items():
        # Get all siblings (parts in same assembly)
        siblings = [c for c in children if c['part_number'] or c['name']]

        for child in children:
            key = child['part_number'] or child['name']
            if not key:
                continue

            # Get sibling list (excluding self)
            sibling_list = []
            for s in siblings:
                s_key = s['part_number'] or s['name']
                if s_key != key:
                    sibling_list.append({
                        'pn': s_key,
                        'desc': s['description'] or '',
                        'type': s['type']
                    })

            context_db[key] = {
                'part_number': key,
                'description': child['description'],
                'type': child['type'],
                'assembly': parent,
                'siblings': sibling_list,
                'siblings_str': '; '.join([f"{s['pn']} ({s['desc']})" for s in sibling_list[:10]])
            }

    return context_db

def main():
    input_file = "046-935_full_tree_v2.txt"

    print(f"Parsing {input_file}...")
    components = parse_tree_file(input_file)

    print(f"Extracted {len(components)} components")

    # Count types
    parts = [c for c in components if c['type'] == 'PART']
    assys = [c for c in components if c['type'] in ['SUBASSY', 'ASSEMBLY']]

    print(f"  Parts: {len(parts)}")
    print(f"  Assemblies: {len(assys)}")

    # Build structure
    structure, parts_db, assemblies_db = build_structure(components)

    print(f"\nUnique parts in DB: {len(parts_db)}")
    print(f"Unique assemblies in DB: {len(assemblies_db)}")

    # Build mating context
    context_db = build_mating_context(structure, parts_db)

    # Save all databases
    with open('sw_components_all.json', 'w', encoding='utf-8') as f:
        json.dump(components, f, indent=2)
    print(f"\nSaved all components to sw_components_all.json")

    with open('sw_parts_db.json', 'w', encoding='utf-8') as f:
        json.dump(parts_db, f, indent=2)
    print(f"Saved parts database to sw_parts_db.json")

    with open('sw_assemblies_db.json', 'w', encoding='utf-8') as f:
        json.dump(assemblies_db, f, indent=2)
    print(f"Saved assemblies database to sw_assemblies_db.json")

    with open('sw_structure.json', 'w', encoding='utf-8') as f:
        json.dump(structure, f, indent=2)
    print(f"Saved structure to sw_structure.json")

    with open('sw_mating_context.json', 'w', encoding='utf-8') as f:
        json.dump(context_db, f, indent=2)
    print(f"Saved mating context to sw_mating_context.json")

    # Print sample
    print("\n" + "="*60)
    print("SAMPLE PARTS:")
    print("="*60)
    for i, (key, data) in enumerate(parts_db.items()):
        if i >= 10:
            break
        print(f"{data['old_pn']:20} -> {data['new_pn'] or 'N/A':15} | {data['description'] or 'N/A'}")

    print("\n" + "="*60)
    print("SAMPLE MATING CONTEXT:")
    print("="*60)
    for i, (key, data) in enumerate(context_db.items()):
        if i >= 5:
            break
        print(f"\n{key} ({data['description']})")
        print(f"  Assembly: {data['assembly']}")
        print(f"  Siblings: {len(data['siblings'])}")
        if data['siblings']:
            for s in data['siblings'][:3]:
                print(f"    - {s['pn']} ({s['desc']})")

if __name__ == "__main__":
    main()
