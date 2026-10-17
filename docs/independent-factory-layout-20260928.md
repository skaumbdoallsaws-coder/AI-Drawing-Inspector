# Independent Factory Layout

Created September 28, 2026 for the user's independent authoring challenge.

The first-layer result below is historical. A subsequent
[Layer 2 functional review](independent-factory-layer2-20260928.md) corrected
operator positions/headings and floor markings, with explicit unresolved
manufacturing constraints. The current sheet has 90 markings; the initial
revision and evidence below remain preserved.

## Delivered Sheet

- Name: **Factory 02 - Integrated Production**
- ID: `fl-independent-factory-20260928`
- Saved revision: `a6454eb6812b8f1798a0eab50b33bfa0313ae9a242c8ad15a8b64fa60733e250`
- Same approximately 300 x 200 m site frame as the manual reference.
- 830 placements, 36 asset definitions, 52 zones, 9 aisles, 85 floor markings.
- Twelve guarded robot cells, eight assembly cells, four inspection stations,
  four packing stations, machining, tool preparation, warehouses and service bays.
- 408 guard panels, 120 racks, 76 pallets, 40 operators, 24 machining assets,
  12 robots, plus benches, lifts, fixtures, storage and material-handling assets.
- Twelve tooling plates retain explicit support relationships to their lift tables.

The layout uses fresh coordinates, identities and arrangements. It was authored
by Codex through the existing operation kernel, not copied from the reference
layout and not generated through a Sage provider conversation. The source was
used for the site references and the expected level of detail only.

`tools/build_independent_factory.py` creates an empty document, authors bounded
operation batches, validates dependencies, geometry and aisles, then optionally
publishes the blank sheet and saves the completed new document. It refuses to
overwrite an existing sheet with the same identity. No application engine or
structure-tree code was changed.

## Verification

Actual authoritative validation reported:

- Zero placement collisions, shell-obstacle collisions or clearance conflicts.
- Zero obstructed aisles and zero spatial errors.
- All 830 placements have exact catalog definition revisions.
- No placement has a persisted `zoneId`.

The normal Electron application was launched with a separate desktop profile,
using the same live facility store. The existing user window was not closed.
The native check opened the manual sheet, opened the new sheet, displayed Plan
and 3D, inspected a robot-cell close-up, and switched between both sheets.

- Native check: passed; both saved sheets remained clean.
- 830 placement transforms audited, zero missing or mismatched transforms.
- 36 asset groups; no renderer warnings or degraded state.
- At whole-factory scale, normal level-of-detail behavior displayed 634
  overview-model placements, 40 operator avatars and 156 deferred footprints.
  This is not a claim that every heavy model was loaded at full detail.
- Screenshot checks confirmed nonempty rendering; Plan, 3D and cell-detail
  captures were also visually inspected.

Evidence is under `.runtime/independent-factory-20260928/`:
`blank.json`, `operations.json`, `layout.json`, `report.json`,
`native-check.json`, and four PNG captures.

The original saved manual layout remains byte-for-byte unchanged:
`a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`.
The site's default layout remains the original manual layout. No other saved
layout was edited. The new sheet is saved in the normal facility repository;
the review window keeps both sheets open. Ordinary startup still opens only
its configured layout, following the existing sheet behavior.

## Boundaries

This is a detailed, editable spatial concept, not a production-qualified plant.
Operating/service clearances, robot safety envelopes, vehicle turning clearance,
capacity, utilities and regulatory compliance remain unverified. The aisles are
authored circulation corridors, not a newly approved manufacturing Process Map.
No motion scenario or optimization claim was added. No provider credits were used.
