# Facility Planning Synthetic Corpus v1

## Purpose

This corpus broadens InspectorPro's Facility Planning evaluation coverage beyond the MMLE-50D reference layout. It contains coordinate-free planning packages and the deterministic layouts produced by the real Facility Planning compiler and operation kernel.

The corpus is an evaluation and development asset. It is not controlled product knowledge, a factory design standard, or evidence that any generated layout is safe, compliant, capable, or production-ready.

## Contents

The generated corpus lives at:

`generated/facility_planning/synthetic-corpus/v1/`

It contains:

- 12 factory archetypes
- 4 scale variants per archetype
- 48 planning packages
- 48 compiled, unsaved prototype layouts
- 144 intent-routing cases
- 12 negative cases that must fail closed
- a revisioned manifest and evaluation report

The archetypes are:

1. Linear discrete assembly
2. High-mix job shop
3. Distribution center
4. Robotic fabrication
5. Electronics assembly
6. Fabrication, weld, and paint
7. Remanufacturing depot
8. Mixed-model cellular production
9. Warehouse and production hybrid
10. Laboratory pilot plant
11. Heavy-equipment assembly
12. Compact urban factory

Each archetype has `pilot`, `balanced`, `expanded`, and `high-throughput` variants. The variants change envelope size, equipment quantity, and authored packing dimensions without introducing model-authored coordinates.

## Split Policy

The split is archetype-aware:

| Split | Packages | Policy |
| --- | ---: | --- |
| Development | 24 | Variants 1-3 of the first eight archetypes |
| Evaluation | 8 | High-throughput variant of the same eight archetypes |
| Held-out | 16 | All variants of four archetypes absent from development |

This supports two different tests:

- Evaluation measures scale generalization within a known archetype.
- Held-out measures transfer to unseen facility structures, labels, resource mixes, and route patterns.

Held-out packages must not be copied into prompts or implementation rules before their score is frozen.

## Authority Boundary

Every package is fixed to:

```json
{
  "knowledgeStatus": "inferred",
  "authority": "illustrative",
  "reviewStatus": "pending",
  "productionEligible": false,
  "planningClaim": "illustrative_prototype",
  "reviewReceiptId": null
}
```

Synthetic evidence is always `illustrative`, `pending`, and `synthetic: true`. The referenced local asset catalog is supporting evidence for exact identities and physical footprints only.

The corpus must never be used to assert:

- production demand or capacity
- regulatory or code compliance
- safety clearances
- vehicle suitability
- process capability
- controlled release status
- human approval

The compiler rejects synthetic evidence promoted to controlled authority and illustrative packages promoted to production eligibility.

## Generation Pipeline

The implementation is in:

- `ai_inspector/facility_layout/synthetic_planning_corpus.py`
- `tools/build_facility_planning_synthetic_corpus.py`

For every positive case, the generator:

1. Builds a semantic Facility Planning package with no authored geometry coordinates.
2. Resolves exact catalog asset IDs and revisions.
3. Canonicalizes and validates the package.
4. Compiles the package to a `FacilityProgram`.
5. Compiles a revision-bound operation plan.
6. Executes the real deterministic kernel against a blank layout.
7. Verifies the result is unsaved and production-ineligible.
8. Records package, program, plan, and layout revisions.

Output is written to a temporary sibling directory and swapped into place only after the complete evaluation succeeds. The tool rejects output paths outside `generated/facility_planning/`.

Generate or refresh the corpus:

```powershell
python tools\build_facility_planning_synthetic_corpus.py --summary
```

Expected v1 summary:

```text
12 archetypes
4 variants
48 packages passed
48 layouts produced
144 intent cases
12 of 12 negative cases refused as expected
```

## Negative Coverage

The refusal set verifies:

- synthetic evidence cannot become controlled evidence
- illustrative packages cannot become production-eligible
- department shares must close correctly
- process predecessors must exist
- equipment and routes must target known areas
- equipment quantities and route widths cannot be omitted
- asset revisions must exist in the current catalog
- placement patterns must be supported
- infeasible resource density fails without mutating the base layout

## Intended Sage Use

The first use is evaluation, not fact injection or fine-tuning. The corpus can test whether Sage:

- selects the Facility Planning workflow from varied user language
- binds a request to the correct revisioned package
- preserves the unsaved-draft and human-Save boundary
- explains assumptions and unresolved evidence honestly
- handles unfamiliar facility structures without copying MMLE-specific labels
- asks or refuses when a request crosses an authority boundary

Later, reviewed development examples may support retrieval of compact structural exemplars. Retrieval must return only the package pattern and claim boundary; it must never treat synthetic dimensions, quantities, or process choices as facts about the user's facility.

Do not fine-tune these synthetic facts into model weights. A behavior or response-format fine-tune remains a separate decision and must use held-out evaluation.

## Verification

Focused tests:

```powershell
python -m pytest tests\test_facility_layout_synthetic_planning_corpus.py -q
```

The test contract checks corpus cardinality, split isolation, fixed authority, deterministic recompilation across all split types, all 12 refusals, intent-case coverage, generated-manifest integrity, and output-path safety.

Representative browser evidence is stored under:

`tests/fixtures/facility_layout/synthetic_corpus/`

The capture run loads six compiled layouts into the real Facility workspace without calling Save. It verifies the browser counts against the manifest, captures all six Plan views, checks a representative Three.js canvas at the pixel level, records browser errors, and proves the saved default layout is unchanged.

Refresh that evidence against a running local app:

```powershell
python tools\capture_facility_planning_synthetic_corpus.py --url http://127.0.0.1:8141/
```

## Adding v2 Scenarios

Add new archetypes only when they introduce a meaningful structural dimension, such as a different route topology, cell family, guarding pattern, resource density, process flow, or subdivision hierarchy. Renaming the same geometry does not add useful coverage.

Before publishing a new corpus revision:

1. Freeze the archetype and variant definitions.
2. Freeze development, evaluation, and held-out membership.
3. Compile every package with the current catalog revision.
4. Run all negative cases.
5. Record the corpus revision and exact compiler revisions.
6. Inspect representative 2D and 3D layouts.
7. Keep every result illustrative and unsaved.
