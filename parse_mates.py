"""
Parse 046-935_mates.txt to extract:
1. Actual mate relationships (Part A ↔ Part B)
2. Specs from fastener names (M10x1.5, thread sizes, etc.)
3. Build a proper mating specs database

Output: sw_mate_specs.json
"""

import re
import json
from collections import defaultdict

# Load the mates file
with open('046-935_mates.txt', 'r') as f:
    content = f.read()

# =============================================================================
# STEP 1: Parse Components
# =============================================================================
components_section = re.search(r'\[COMPONENTS\]\n(.*?)\n\nTotal:', content, re.DOTALL)
components = []
if components_section:
    for line in components_section.group(1).strip().split('\n'):
        line = line.strip()
        if line:
            components.append(line)

print(f"Parsed {len(components)} components")

# =============================================================================
# STEP 2: Parse Mates
# =============================================================================
mates_section = re.search(r'\[MATES\]\n.*?-+\n(.*?)\n\nTotal Mates:', content, re.DOTALL)
mates = []
if mates_section:
    for line in mates_section.group(1).strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        # Format: MateName | Type | PartA <-> PartB
        match = re.match(r'(.+?)\s*\|\s*(\w+)\s*\|\s*(.+?)\s*<->\s*(.+)', line)
        if match:
            mate_name, mate_type, part_a, part_b = match.groups()
            mates.append({
                'name': mate_name.strip(),
                'type': mate_type.strip(),
                'part_a': part_a.strip(),
                'part_b': part_b.strip()
            })

print(f"Parsed {len(mates)} mates")

# =============================================================================
# STEP 3: Extract Specs from Fastener Names
# =============================================================================

def extract_fastener_spec(name):
    """
    Extract thread/size specs from fastener names.

    Examples:
    - "B18.3.1M - 10 x 1.5 x 30 Hex SHCS" -> M10x1.5, 30mm long
    - "B18.3.6M - M10 x 1.5 x 12 Hex Socket Cone Pt." -> M10x1.5, 12mm
    - "hex cap screw_am" -> generic, no spec
    """
    specs = {
        'type': 'unknown',
        'thread': None,
        'pitch': None,
        'length': None,
        'raw_name': name
    }

    name_upper = name.upper()

    # Detect fastener type
    if 'SHCS' in name_upper or 'HEX SHCS' in name_upper:
        specs['type'] = 'Socket Head Cap Screw'
    elif 'BTNHD' in name_upper or 'BUTTON' in name_upper:
        specs['type'] = 'Button Head Cap Screw'
    elif 'CONE PT' in name_upper or 'SET SCREW' in name_upper:
        specs['type'] = 'Set Screw'
    elif 'HEX CAP' in name_upper:
        specs['type'] = 'Hex Cap Screw'
    elif 'TAPPING' in name_upper:
        specs['type'] = 'Tapping Screw'
    elif 'NUT' in name_upper:
        specs['type'] = 'Nut'
    elif 'WASHER' in name_upper:
        specs['type'] = 'Washer'

    # Pattern 1: B18.3.1M - 10 x 1.5 x 30 (Metric: diameter x pitch x length)
    match = re.search(r'B18\.\d+\.\d+M\s*-\s*(\d+)\s*x\s*([\d.]+)\s*x\s*(\d+)', name)
    if match:
        specs['thread'] = f"M{match.group(1)}"
        specs['pitch'] = f"{match.group(2)}mm"
        specs['length'] = f"{match.group(3)}mm"
        return specs

    # Pattern 2: M10 x 1.5 x 12 (Explicit M prefix)
    match = re.search(r'M(\d+)\s*[xX]\s*([\d.]+)\s*[xX]\s*(\d+)', name)
    if match:
        specs['thread'] = f"M{match.group(1)}"
        specs['pitch'] = f"{match.group(2)}mm"
        specs['length'] = f"{match.group(3)}mm"
        return specs

    # Pattern 3: M6 X 1.0 X 12 mm (with spaces and mm suffix)
    match = re.search(r'M(\d+)\s*[xX]\s*([\d.]+)\s*[xX]\s*(\d+)\s*mm', name, re.IGNORECASE)
    if match:
        specs['thread'] = f"M{match.group(1)}"
        specs['pitch'] = f"{match.group(2)}mm"
        specs['length'] = f"{match.group(3)}mm"
        return specs

    # Pattern 4: Imperial - 3/4-10 or 1/2-13 (fraction-TPI)
    match = re.search(r'(\d+/\d+)-(\d+)', name)
    if match:
        specs['thread'] = match.group(1)
        specs['pitch'] = f"{match.group(2)} TPI"
        return specs

    # Pattern 5: Decimal imperial - .750-10 or 0.500-13
    match = re.search(r'\.?(\d*\.?\d+)-(\d+)', name)
    if match and float(match.group(1)) < 2:  # Reasonable diameter
        specs['thread'] = f"Ø{match.group(1)}"
        specs['pitch'] = f"{match.group(2)} TPI"
        return specs

    return specs


# Test extraction
test_names = [
    "B18.3.1M - 10 x 1.5 x 30 Hex SHCS -- 30NHX-1",
    "B18.3.6M - M10 x 1.5 x 12 Hex Socket Cone Pt. SS --N-3",
    "B18.3.1M - 8 x 1.25 x 12 Hex SHCS -- 12NHX-2",
    "hex head tapping screw_am-1",
    "socket set screw cup point_am-1"
]

print("\n=== Fastener Spec Extraction Test ===")
for name in test_names:
    spec = extract_fastener_spec(name)
    print(f"  {name[:50]:50} -> {spec['thread']} x {spec['pitch']}")

# =============================================================================
# STEP 4: Extract Base Part Number from Component Name
# =============================================================================

def extract_base_pn(component_name):
    """
    Extract the base part number from a component instance name.

    Examples:
    - "B18.3.1M - 10 x 1.5 x 30 Hex SHCS -- 30NHX-3" -> "B18.3.1M - 10 x 1.5 x 30 Hex SHCS -- 30NHX"
    - "046-908-1" -> "046-908"
    - "022-639_1-1" -> "022-639_1"
    - "017-142_1_1-1/017-134-1" -> "017-134" (last part in path)
    """
    # Handle nested paths (take the last component)
    if '/' in component_name:
        component_name = component_name.split('/')[-1]

    # Remove instance number suffix (-1, -2, -3, etc.)
    base = re.sub(r'-\d+$', '', component_name)

    return base


# =============================================================================
# STEP 5: Build Mating Relationships Database
# =============================================================================

# Track what each part mates with
mate_relationships = defaultdict(list)

for mate in mates:
    part_a = mate['part_a']
    part_b = mate['part_b']
    mate_type = mate['type']

    # Extract base part numbers
    base_a = extract_base_pn(part_a)
    base_b = extract_base_pn(part_b)

    # Skip self-mates and assembly-level mates
    if base_a == base_b:
        continue
    if base_a == '046-935' or base_b == '046-935':
        # Top-level assembly mate - still useful
        pass

    # Extract specs if it's a fastener
    spec_a = extract_fastener_spec(base_a)
    spec_b = extract_fastener_spec(base_b)

    # Add bidirectional relationships
    mate_relationships[base_a].append({
        'mates_with': base_b,
        'mate_type': mate_type,
        'their_spec': spec_b if spec_b['thread'] else None,
        'full_path': part_b
    })

    mate_relationships[base_b].append({
        'mates_with': base_a,
        'mate_type': mate_type,
        'their_spec': spec_a if spec_a['thread'] else None,
        'full_path': part_a
    })

print(f"\nBuilt mate relationships for {len(mate_relationships)} unique parts")

# =============================================================================
# STEP 6: Build Final Specs Database
# =============================================================================

# Load existing parts database for descriptions
try:
    with open('sw_parts_db.json', 'r') as f:
        parts_db = json.load(f)
except:
    parts_db = {}

# Build reverse lookup: old_pn -> new_pn
old_to_new = {}
for new_pn, info in parts_db.items():
    old_pn = info.get('old_pn', '')
    if old_pn:
        old_to_new[old_pn] = new_pn
        # Also handle file basename
        file_base = info.get('file', '').replace('.SLDPRT', '').replace('.SLDASM', '')
        if file_base:
            old_to_new[file_base] = new_pn

def get_part_info(base_pn):
    """Look up part info from parts database."""
    # Try direct lookup
    if base_pn in parts_db:
        return parts_db[base_pn]
    # Try old_pn lookup
    if base_pn in old_to_new:
        new_pn = old_to_new[base_pn]
        return parts_db.get(new_pn, {})
    # Try without hyphens
    normalized = base_pn.replace('-', '')
    for old_pn, new_pn in old_to_new.items():
        if old_pn.replace('-', '') == normalized:
            return parts_db.get(new_pn, {})
    return {}


# Build the final database
mate_specs_db = {}

for base_pn, mates_list in mate_relationships.items():
    # Get part info
    part_info = get_part_info(base_pn)

    # Extract this part's own spec (if it's a fastener)
    own_spec = extract_fastener_spec(base_pn)

    # Deduplicate mates (same part, same type)
    unique_mates = {}
    for m in mates_list:
        key = (m['mates_with'], m['mate_type'])
        if key not in unique_mates:
            unique_mates[key] = m

    # Build mating specs list
    mating_specs = []
    for (mate_pn, mate_type), m in unique_mates.items():
        mate_info = get_part_info(mate_pn)
        mate_spec = extract_fastener_spec(mate_pn)

        entry = {
            'part': mate_pn,
            'description': mate_info.get('description', ''),
            'mate_type': mate_type,
        }

        # Add spec if available
        if mate_spec['thread']:
            entry['thread'] = mate_spec['thread']
            entry['pitch'] = mate_spec['pitch']
            if mate_spec['length']:
                entry['length'] = mate_spec['length']

        mating_specs.append(entry)

    # Sort by mate type (Concentric first, then Coincident)
    type_order = {'Concentric': 0, 'Coincident': 1, 'Parallel': 2, 'Distance': 3, 'Type_21': 4}
    mating_specs.sort(key=lambda x: type_order.get(x['mate_type'], 99))

    mate_specs_db[base_pn] = {
        'part_number': base_pn,
        'description': part_info.get('description', ''),
        'own_spec': own_spec if own_spec['thread'] else None,
        'mates_with': mating_specs,
        'mate_count': len(mating_specs)
    }

# =============================================================================
# STEP 7: Save Output
# =============================================================================

with open('sw_mate_specs.json', 'w', encoding='utf-8') as f:
    json.dump(mate_specs_db, f, indent=2, ensure_ascii=False)

print(f"\n{'='*60}")
print("OUTPUT: sw_mate_specs.json")
print('='*60)
print(f"Total parts with mates: {len(mate_specs_db)}")

# Show some examples
print("\n=== Sample Entries ===")
sample_keys = list(mate_specs_db.keys())[:5]
for key in sample_keys:
    entry = mate_specs_db[key]
    print(f"\n{key} ({entry['description'] or 'No description'}):")
    if entry['own_spec']:
        print(f"  Own spec: {entry['own_spec']['thread']} x {entry['own_spec']['pitch']}")
    print(f"  Mates with {entry['mate_count']} parts:")
    for m in entry['mates_with'][:3]:
        spec_str = f" [{m.get('thread', '')}]" if m.get('thread') else ""
        print(f"    - {m['mate_type']}: {m['part']}{spec_str}")
    if entry['mate_count'] > 3:
        print(f"    ... and {entry['mate_count'] - 3} more")

# =============================================================================
# STEP 8: Create Summary for Stage 1 Inspection
# =============================================================================

# Build a simpler format for the inspector
inspector_db = {}

for base_pn, entry in mate_specs_db.items():
    # Build requirements string
    requirements = []

    for m in entry['mates_with']:
        if m.get('thread'):
            # This mate has a thread spec - the drawing should show matching feature
            if m['mate_type'] == 'Concentric':
                # Concentric with a screw = need a threaded hole
                requirements.append(f"THREAD HOLE: {m['thread']} (for {m['part']})")
            elif m['mate_type'] == 'Coincident':
                requirements.append(f"MATING SURFACE: {m['part']}")
        else:
            # No thread spec - just note the mating part
            if m['mate_type'] == 'Concentric':
                requirements.append(f"CONCENTRIC FIT: {m['part']} ({m.get('description', '')})")

    if requirements:
        inspector_db[base_pn] = {
            'part_number': base_pn,
            'description': entry['description'],
            'requirements': requirements,
            'requirements_str': "; ".join(requirements[:10])
        }

with open('sw_inspector_requirements.json', 'w', encoding='utf-8') as f:
    json.dump(inspector_db, f, indent=2, ensure_ascii=False)

print(f"\n{'='*60}")
print("OUTPUT: sw_inspector_requirements.json")
print('='*60)
print(f"Parts with specific requirements: {len(inspector_db)}")
