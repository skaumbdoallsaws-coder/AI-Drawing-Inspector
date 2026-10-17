"""Reusable build guidance, not a layout recipe or an execution permission.

The read-only context surface exposes these stages on demand. Current tool
limits remain authoritative; a described later stage is not an enabled tool.
"""
from copy import deepcopy


_STAGES = (
    {
        'stageId': 'ground-brief', 'title': 'Ground the brief and resources',
        'availability': 'available',
        'method': [
            'Resolve the selected floor, catalog revisions, product/process and user constraints before planning.',
            'Separate operations from repeated physical resources. Consider available equipment before choosing a process route.',
            'Read registered equipment summaries, then relevant manual pages, then permitted primary web sources for remaining gaps.',
            'Ask only consequential missing questions. Provisional quantities or geometric gaps need disclosed assumptions, not fabricated capacity.',
        ],
        'tools': ['inspect_generation_planning_context', 'search_generation_equipment',
                  'read_generation_equipment_document', 'search_generation_sources',
                  'read_generation_source', 'propose_generation_context'],
        'completionEvidence': ['Exact source/catalog references', 'Process/resource assignments',
                               'All consequential clauses represented or explicitly unresolved'],
    },
    {
        'stageId': 'spatial-structure', 'title': 'Allocate departments and circulation',
        'availability': 'available_with_current_limits',
        'method': [
            'Choose department shares, rows, resource quantities and semantic patterns from the brief, not a reference screenshot.',
            'Let deterministic compilers calculate coordinates, fit and routes. Do not issue hundreds of individual model-authored coordinates.',
            'Use patterns for repeated identical resources within the current budget. Do not split an oversized request into independent previews and claim one cumulative factory.',
            'Use interdepartment routes only between distinct areas. Same-department operations do not need a self-route.',
            'For an exact equipment-only scope, combine resource_set with resource_quantity for each batch. Use route_count=0 when no routes are requested.',
        ],
        'tools': ['record_generation_requirements', 'plan_generation_turn',
                  'preview_generation_package', 'revise_generation_package', 'inspect_generation_candidate'],
        'completionEvidence': ['Validated candidate counts and geometry', 'Requirement checks', 'No Save'],
    },
    {
        'stageId': 'cell-detail', 'title': 'Design one cell before repeating it',
        'availability': 'available_with_current_limits',
        'method': [
            'A reusable cell needs equipment roles, operator positions, input/output staging, support attachments and an explicit access side.',
            'Validate a representative cell before repetition; retain generated IDs and remap attachments for each copy.',
            'Use areaGroups, cellRecipes and moduleFamilies through the generation package. Batches count seed resources; resource_total counts seeds plus every copy. Include matching structure predicates in the retained ledger.',
            'Translated copies preserve the seed and target empty sibling areas. Arbitrary manual construction and attachments are not integrated into this package path.',
            'Use named child areas and explicit cell recipes for multi-asset cells; resource patterns alone do not create grouped cells. Guards, attachments and floor markings remain outside this adapter.',
        ],
        'tools': ['plan_generation_turn', 'preview_generation_package', 'revise_generation_package', 'inspect_generation_candidate'],
        'completionEvidence': ['Representative cell and repeated-cell receipts', 'Expanded resource inventory checks'],
    },
    {
        'stageId': 'functional-review', 'title': 'Check function as well as fit',
        'availability': 'partial_inspection_only',
        'method': [
            'Inspect the active candidate, not the saved layout, using exact entity IDs and revisions.',
            'For every equipment/operator pair, distinguish center-facing from a documented control/loading side. Unknown operating sides remain unknown.',
            'Keep staged materials outside keep-clear areas, check support relationships and pedestrian access, and label inferred choices.',
            'Office, cafeteria, kitchen and walls are optional requirements, not automatic decorations. Their detailed composition is not enabled in this generation tool set.',
        ],
        'tools': ['inspect_generation_candidate', 'inspect_generation_planning_context'],
        'completionEvidence': ['Candidate inspection receipts', 'Named evidence gaps',
                               'Pending integration: executable functional checks and local repair'],
    },
    {
        'stageId': 'movement', 'title': 'Derive movement from reviewed assignments',
        'availability': 'not_integrated_in_generation_chat',
        'method': [
            'Movement must reference reviewed actor/station assignments and exact candidate identities, not nearest-looking equipment.',
            'Use the navigation compiler for paths; validate obstacles and endpoints before playback.',
            'A walking animation is not a production Process Map, material transfer, robot cycle or throughput simulation.',
            'Do not promise authored movement from the current generation preview tools.',
        ],
        'tools': [],
        'completionEvidence': ['Pending integration: revision-bound navigation receipts and playback checks'],
    },
    {
        'stageId': 'review-and-adopt', 'title': 'Explain, correct and adopt the result',
        'availability': 'available_with_current_limits',
        'method': [
            'Report only counts, checks and completion supported by receipts. Missing hard checks are not passes.',
            'On correction, inspect the retained proposal and preserve unchanged requirements and package fields.',
            'Repair only the failed stage within budget. A depleted search budget is not proof of infeasibility.',
            'Present an unsaved preview. Apply and Undo use application authorization; Save requires explicit user action.',
        ],
        'tools': ['inspect_generation_planning_context', 'revise_generation_package', 'inspect_generation_candidate'],
        'completionEvidence': ['Receipt-derived explanation', 'Exact selected candidate',
                               'Application Apply/Undo evidence, separate from tool completion'],
    },
)


def build_method_summary():
    from .generation_admission import MAX_PREVIEW_PLACEMENTS
    return {
        'version': 'facility-build-method-v1', 'detailSection': 'buildMethod',
        'qualification': 'Planning guidance only; it does not enable additional actions.',
        'currentLimits': {'placements': MAX_PREVIEW_PLACEMENTS, 'departments': 8, 'resourceBatches': 24,
                          'base': 'clean_empty_layout', 'cellRecipes': True, 'moduleFamilies': True,
                          'floorMarkings': False, 'walls': False, 'movement': False},
        'instruction': 'For a detailed multistage factory request, inspect buildMethod before promising completion. '
                       'Use applicable stages; name unsupported work rather than omitting it. '
                       'Simple quantity corrections do not need another method read.',
    }


def build_method_stages():
    return deepcopy(list(_STAGES))
