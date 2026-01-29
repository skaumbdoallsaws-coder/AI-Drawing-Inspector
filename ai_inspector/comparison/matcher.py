"""
Feature Matching Module

Compares drawing callouts against SolidWorks CAD requirements.
All comparisons done in INCHES with configurable tolerance.
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


# Default tolerance for inch comparisons (~0.4mm)
DEFAULT_TOLERANCE_INCHES = 0.015

# Standard metric thread pitches (for when pitch is not specified)
STANDARD_METRIC_PITCHES = {
    6: 1.0,
    8: 1.25,
    10: 1.5,
    12: 1.75,
    14: 2.0,
    16: 2.0,
    20: 2.5,
    24: 3.0,
}


def extract_sw_requirements(sw_data: Dict, filter_sheet_metal: bool = True) -> List[Dict]:
    """
    Extract requirements from SolidWorks JSON using comparison.holeGroups.

    Returns hole diameters in INCHES for direct comparison with drawing callouts.

    Args:
        sw_data: SolidWorks part JSON data
        filter_sheet_metal: Whether to filter out sheet metal bend artifacts

    Returns:
        List of requirement dictionaries
    """
    requirements = []

    # Primary source: comparison.holeGroups (reconciled/canonical data)
    comparison = sw_data.get('comparison', {})
    hole_groups = comparison.get('holeGroups', [])

    for hg in hole_groups:
        # FILTER: Skip bogus "holes" that are actually sheet metal bend geometry
        if filter_sheet_metal:
            recon_note = hg.get('reconciliationNote', '')
            if 'Bend' in recon_note or 'bend' in recon_note.lower():
                continue  # Skip bend artifacts

            # FILTER: Skip holes with unrealistic aspect ratio (depth > 10x diameter)
            diameters = hg.get('diameters', {})
            depth_info = hg.get('depth', {})
            dia_mm = diameters.get('pilotOrTapDrillDiameterMm', 0)
            depth_mm = depth_info.get('mm', 0) if isinstance(depth_info, dict) else 0
            if dia_mm > 0 and depth_mm > 0 and depth_mm > 10 * dia_mm:
                continue  # Skip unrealistic holes (likely geometry artifacts)

        diameters = hg.get('diameters', {})
        hole_type = hg.get('holeType', '')
        canonical = hg.get('canonical', '')
        count = hg.get('count', 1)
        thread = hg.get('thread', {})

        if hole_type == 'Tapped':
            # Tapped hole - thread info stays in metric (M6x1.0)
            requirements.append({
                'type': 'TappedHole',
                'thread': {
                    'standard': thread.get('standard', 'Metric'),
                    'nominalDiameterMm': thread.get('majorDiameterMm') or diameters.get('threadNominalDiameterMm'),
                    'pitch': thread.get('pitch'),
                    'callout': thread.get('callout', canonical)
                },
                'count': count,
                'canonical': canonical,
                'source': 'sw_comparison.holeGroups'
            })
        elif hole_type == 'Through':
            # Plain through hole - use INCHES for comparison
            diameter_inches = diameters.get('pilotOrTapDrillDiameterInches')
            requirements.append({
                'type': 'Hole',
                'diameterInches': diameter_inches,
                'isThrough': True,
                'count': count,
                'canonical': canonical,
                'canonicalInches': diameters.get('nearestStandardInch', ''),
                'source': 'sw_comparison.holeGroups'
            })
        elif hole_type == 'Blind':
            # Blind hole - use INCHES
            diameter_inches = diameters.get('pilotOrTapDrillDiameterInches')
            requirements.append({
                'type': 'Hole',
                'diameterInches': diameter_inches,
                'isThrough': False,
                'count': count,
                'canonical': canonical,
                'source': 'sw_comparison.holeGroups'
            })

    # Fallback: features.holeWizardHoles if no comparison data
    if not requirements:
        features = sw_data.get('features', {})
        requirements.extend(_extract_from_features(features))

    return requirements


def _extract_from_features(features: Dict) -> List[Dict]:
    """Extract requirements from features section as fallback."""
    requirements = []

    for hole in features.get('holeWizardHoles', []):
        if hole.get('isTapped'):
            thread_size = hole.get('threadSize', '')
            m = re.match(r'M(\d+(?:\.\d+)?)[xX](\d+(?:\.\d+)?)', thread_size)
            if m:
                requirements.append({
                    'type': 'TappedHole',
                    'thread': {
                        'standard': 'Metric',
                        'nominalDiameterMm': float(m.group(1)),
                        'pitch': float(m.group(2)),
                        'callout': thread_size
                    },
                    'count': hole.get('instanceCount', 1),
                    'source': 'sw_features.holeWizardHoles'
                })
        else:
            # Convert meters to inches
            diameter_m = hole.get('diameter', 0)
            diameter_inches = diameter_m * 39.3701
            requirements.append({
                'type': 'Hole',
                'diameterInches': diameter_inches,
                'isThrough': hole.get('isThrough', False),
                'count': hole.get('instanceCount', 1),
                'source': 'sw_features.holeWizardHoles'
            })

    # Fillets - convert to inches
    for fillet in features.get('fillets', []):
        radius_mm = fillet.get('radius', 0)
        requirements.append({
            'type': 'Fillet',
            'radiusInches': radius_mm / 25.4 if radius_mm else 0,
            'source': 'sw_features'
        })

    # Chamfers - convert to inches
    for chamfer in features.get('chamfers', []):
        dist_mm = chamfer.get('distance1', 0)
        requirements.append({
            'type': 'Chamfer',
            'distance1Inches': dist_mm / 25.4 if dist_mm else 0,
            'angleDegrees': chamfer.get('angle', 45),
            'source': 'sw_features'
        })

    return requirements


def extract_mate_requirements(
    part_number: str,
    inspector_requirements: Optional[Dict] = None,
    part_context: Optional[Dict] = None
) -> List[Dict]:
    """
    Extract thread hole requirements from assembly mate data.

    These requirements come from concentric mates with fasteners and
    fill the gap where part JSONs show hasThread=false.

    Args:
        part_number: Part number to look up
        inspector_requirements: Inspector requirements database entry
        part_context: Part context database entry

    Returns:
        List of mate-derived requirements
    """
    requirements = []

    # Source 1: inspector requirements DB
    if inspector_requirements:
        # Data structure: {"requirements": ["THREAD HOLE: M8 (for fastener...)", ...]}
        for req_str in inspector_requirements.get('requirements', []):
            if not req_str.startswith('THREAD HOLE:'):
                continue
            # Parse "THREAD HOLE: M8" or "THREAD HOLE: M10 x 1.5" formats
            m = re.search(r'M(\d+(?:\.\d+)?)(?:\s*[xX]\s*(\d+(?:\.\d+)?))?', req_str)
            if m:
                nom = float(m.group(1))
                pitch = float(m.group(2)) if m.group(2) else None
                # Standard metric pitches if not specified
                if pitch is None:
                    pitch = STANDARD_METRIC_PITCHES.get(int(nom))
                requirements.append({
                    'type': 'TappedHole',
                    'thread': {
                        'standard': 'Metric',
                        'nominalDiameterMm': nom,
                        'pitch': pitch,
                        'callout': f"M{int(nom)}x{pitch}" if pitch else f"M{int(nom)}"
                    },
                    'count': 1,
                    'source': 'assembly_mate',
                    'raw_requirement': req_str
                })

    # Source 2: part context DB (mates_with entries with thread specs)
    if part_context:
        for mate in part_context.get('mating', {}).get('mates_with', []):
            thread = mate.get('thread')
            if thread:
                # Parse thread string like "M10"
                m = re.search(r'M(\d+(?:\.\d+)?)', str(thread))
                if m:
                    nom = float(m.group(1))
                    pitch_str = mate.get('pitch', '')
                    pitch_m = re.search(r'(\d+\.?\d*)', str(pitch_str))
                    pitch = float(pitch_m.group(1)) if pitch_m else None
                    # Avoid duplicates with Source 1
                    already = any(
                        r.get('thread', {}).get('nominalDiameterMm') == nom
                        for r in requirements
                    )
                    if not already:
                        requirements.append({
                            'type': 'TappedHole',
                            'thread': {
                                'standard': 'Metric',
                                'nominalDiameterMm': nom,
                                'pitch': pitch,
                                'callout': f"{thread}x{pitch_str}" if pitch_str else str(thread)
                            },
                            'count': 1,
                            'source': 'assembly_mate',
                            'mating_part': mate.get('part', ''),
                            'mate_type': mate.get('mate_type', '')
                        })

    return requirements


def compare_callout_to_requirement(
    callout: Dict,
    req: Dict,
    tolerance_inches: float = DEFAULT_TOLERANCE_INCHES
) -> bool:
    """
    Check if a drawing callout matches a SW requirement.

    Hole comparison done in INCHES with configurable tolerance.

    Args:
        callout: Drawing callout dictionary
        req: Requirement dictionary
        tolerance_inches: Tolerance for inch comparisons (default 0.015")

    Returns:
        True if callout matches requirement
    """
    ctype = callout.get('calloutType')
    rtype = req.get('type')

    if ctype != rtype:
        return False

    if ctype == 'Hole':
        # Compare in INCHES
        d1 = callout.get('diameterInches', 0)
        d2 = req.get('diameterInches', 0)
        if d1 and d2 and abs(d1 - d2) <= tolerance_inches:
            return True

    elif ctype == 'TappedHole':
        # Metric threads - compare in mm
        t1 = callout.get('thread', {})
        t2 = req.get('thread', {})
        nom1 = t1.get('nominalDiameterMm', 0)
        nom2 = t2.get('nominalDiameterMm', 0)
        if nom1 and nom2 and abs(nom1 - nom2) < 0.1:
            p1 = t1.get('pitch')
            p2 = t2.get('pitch')
            if p1 and p2:
                return abs(p1 - p2) < 0.01
            return True  # Match if pitches not specified

    elif ctype == 'Fillet':
        r1 = callout.get('radiusInches', 0)
        r2 = req.get('radiusInches', 0)
        if r1 and r2 and abs(r1 - r2) <= tolerance_inches:
            return True

    elif ctype == 'Chamfer':
        d1 = callout.get('sizeInches', callout.get('distance1Inches', 0))
        d2 = req.get('distance1Inches', 0)
        if d1 and d2 and abs(d1 - d2) <= tolerance_inches:
            return True

    return False


def generate_diff_result(
    callouts: List[Dict],
    requirements: List[Dict],
    part_number: str,
    tolerance_inches: float = DEFAULT_TOLERANCE_INCHES
) -> Dict:
    """
    Compare drawing callouts against SolidWorks requirements.

    Args:
        callouts: List of callouts from drawing
        requirements: List of requirements from SW + mates
        part_number: Part number for report
        tolerance_inches: Tolerance for comparisons

    Returns:
        DiffResult dictionary with summary and details
    """
    found = []
    missing = []
    matched_callouts = set()
    matched_requirements = set()

    # Check each requirement against callouts
    for ri, req in enumerate(requirements):
        match_found = False
        for ci, callout in enumerate(callouts):
            if ci not in matched_callouts and compare_callout_to_requirement(callout, req, tolerance_inches):
                found.append({
                    'status': 'FOUND',
                    'requirement': req,
                    'evidence': callout,
                    'note': f"Matched: {req.get('canonical', req.get('type'))}"
                })
                matched_callouts.add(ci)
                matched_requirements.add(ri)
                match_found = True
                break

        if not match_found:
            missing.append({
                'status': 'MISSING',
                'requirement': req,
                'evidence': None,
                'note': f"Not found in drawing: {req.get('canonical', req.get('type'))}"
            })

    # Extra callouts not matched to any requirement
    extra = []
    for ci, callout in enumerate(callouts):
        if ci not in matched_callouts:
            extra.append({
                'status': 'EXTRA',
                'requirement': None,
                'evidence': callout,
                'note': f"In drawing but not in SW: {callout.get('raw', callout.get('calloutType'))}"
            })

    # Calculate match rate
    total_reqs = len(requirements)
    match_rate = f"{len(found)/total_reqs*100:.1f}%" if total_reqs > 0 else "N/A"

    diff_result = {
        'partNumber': part_number,
        'generatedAt': datetime.now().isoformat() + 'Z',
        'units': 'inches',
        'toleranceInches': tolerance_inches,
        'summary': {
            'totalRequirements': total_reqs,
            'found': len(found),
            'missing': len(missing),
            'extra': len(extra),
            'matchRate': match_rate,
            'mateRequirements': len([r for r in requirements if r.get('source') == 'assembly_mate']),
        },
        'details': {
            'found': found,
            'missing': missing,
            'extra': extra
        }
    }

    return diff_result


def create_stub_diff_result(part_number: str, reason: str = "No SolidWorks data") -> Dict:
    """
    Create a stub DiffResult when no SW data is available.

    Args:
        part_number: Part number for report
        reason: Reason for stub (for note field)

    Returns:
        Stub DiffResult dictionary
    """
    return {
        'partNumber': part_number,
        'generatedAt': datetime.now().isoformat() + 'Z',
        'units': 'inches',
        'comparisonAvailable': False,
        'summary': {
            'totalRequirements': 0,
            'found': 0,
            'missing': 0,
            'extra': 0,
            'matchRate': 'N/A (no CAD data)'
        },
        'details': {
            'found': [],
            'missing': [],
            'extra': []
        },
        'note': f'{reason}. Report based on drawing analysis only.',
        'suggestions': [
            'Add this part to sw_json_library for future comparisons',
            'Verify part number matches SolidWorks filename',
            'Check if this is an assembly (assemblies may not have individual JSON)'
        ]
    }
