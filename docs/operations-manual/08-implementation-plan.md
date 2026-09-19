# Dependency-Ordered Implementation Plan

This is an implementation roadmap, not authorization to start coding. Contract changes should be reviewed first.

## 1. Critical Path

```text
configuration + source policy
  -> evidence schemas/repository
  -> section recipes + plan schema
  -> deterministic semantic compiler
  -> shared Documentation type registry
  -> operations page renderer
  -> CAD figure requests/capture
  -> PDF + DOCX exporters
  -> Sage orchestration
  -> live production proof
```

The standards/license acquisition and engineering evidence work can proceed in parallel, but controlled publication cannot pass until it joins the critical path at approval/validation.

## 2. Phase 0: Contract Freeze and Acquisition

### Entry blockers

No feature implementation starts until all of these are dispositioned:

- approve the corrected source/evidence/plan schemas and independent-review disposition;
- choose PyMuPDF licensing (Artifex commercial, documented AGPL compliance, or renderer migration), record a legal receipt, and pin the approved renderer/version;
- remediate the parts-manual path so internal registry revision `A` cannot appear as an unqualified product/document revision;
- hash and verify every repository source, including the Documentation Assembly Registry;
- record `CONFLICT-008` for advertised safety features without verified CAD mappings and enforce the feature-target figure gate;
- assign named engineering, safety/EHS, technical-publications, product, legal/licensing, and accessibility reviewers;
- approve WCAG 2.2 AA/PDF/UA-2 as the pilot accessibility targets or record a signed replacement decision.

Deliverables:

- independent review of this package;
- decision on prototype-only versus pilot-release scope;
- approved `DocumentTypeDefinition` boundary;
- acquire licensed ANSI MH29.1 and ANSI/NEMA Z535.6;
- legal/license review for standards ingestion and `python-docx` (PyMuPDF/renderer is an entry blocker above);
- responsible reviewers and approval-receipt format;
- MMLE configuration/effectivity request sent to product authority.

Exit gate: every entry blocker has a revision-bound receipt; known product-content blockers remain explicitly tracked and still prevent controlled release.

## 3. Phase 1: Shared Documentation Foundation

Work:

- introduce neutral `ai_inspector/documentation` contracts/adapters;
- add `DocumentTypeRegistry` and register existing parts manual unchanged;
- preserve current Documentation scene, commands, revision hashes, and undo/redo behavior;
- add semantic content-block identity and reading order;
- add operations page-master definitions;
- implement the minimum deterministic 16:9 landscape flow engine: line breaking, paragraph reflow, widow/orphan control, keep-with-next/together, table continuation headers, row splitting, figure/caption anchoring, overflow findings, and destination resolution;
- pass a synthetic 60-page text/table pagination test before using MMLE prose as vertical-slice evidence;
- keep parts-manual tests green.

Exit gate: parts manuals compile/render identically through the adapter; an empty operations document opens with correct blank state; the 60-page flow fixture completes deterministically without clipping, page-size collapse, or memory-budget breach.

## 4. Phase 2: Source and Evidence Foundation

Work:

- JSON schemas and repositories for sources, claims, conflicts, configuration, and approvals;
- immutable source hashing and access/license metadata;
- evidence policy evaluator and conflict audit;
- import the reviewed MMLE prototype registers;
- UI panels for sources, claims, blockers, and approval state.

Exit gate: unsupported/current-vs-legacy claims cannot satisfy a recipe; every fact is traceable in the app.

## 5. Phase 3: Operations Plan and Semantic Compiler

Work:

- operations section recipes and plan repository;
- read-only planner with coverage/conflict report;
- atomic approval transition;
- structured writer constrained to claim IDs;
- semantic compiler and deterministic pagination inputs;
- blocked-section rendering.

Exit gate: the same approved inputs produce byte-identical semantic documents, with no canvas coordinates from the LLM.

## 6. Phase 4: Authoring and Progressive Generation

Work:

- operations-manual ribbon/contextual controls;
- 16:9 landscape page presentation using the already-gated flow/pagination service;
- sequential page creation and actual thumbnail updates;
- phrase-level temporary text reveal, bounded row reveal, real figure-wait phase;
- cancellation, reduced motion, no-replay, and settled-capture guards;
- context-aware inspector for evidence/approval/block properties.

Exit gate: the blank-to-complete workflow is deterministic, accessible, capture-safe, and visually credible.

## 7. Phase 5: CAD Figure Pipeline

Work:

- operations `FigureRequest` compiler;
- reuse isolation, HLR, neutral-gray style, camera fitting, and high-resolution capture;
- hazard/motion/identification annotation layers;
- page-region quality requests and figure-specific occupancy paths;
- one-at-a-time memory-bounded capture queue;
- accepted artifact manifests and viewport/output parity tests.

Exit gate: the ready figures in the inventory pass identity, render, and memory tests; blocked figures stay blocked.

## 8. Phase 6: PDF and DOCX

### PDF track

- common document envelope and 16:9 landscape operations renderer;
- dynamic text/table pagination, bookmarks, links, metadata, headers/footers;
- safety panels and figure/caption layouts;
- accessibility support and publication manifest.

### DOCX track

- approved dependency/license receipt plus pinned and hash-locked `python-docx` 1.2.0 (or an approved replacement);
- styles, sections, headings, tables, captions, figures, properties, and uncontrolled-copy banner;
- same semantic block census and accepted artifacts as PDF;
- Word/LibreOffice compatibility and package validation.

Exit gate: both outputs share document revision/content and pass their format-specific gates.

## 9. Phase 7: Sage Workflow

Work:

- operations-manual skill, tool policy, contracts, and workflow manifest;
- context inspection, plan proposal/approval, draft generation, editing, validation, capture, and publication tools;
- end-to-end orchestrator over the same public APIs;
- pending-operation persistence, conflict/retry behavior, and automatic read-only narrowing;
- in-chat source links and exact state/artifact reporting.

Exit gate: Sage can complete the live draft workflow without private scripts and cannot overclaim approval/publication.

## 10. Phase 8: Hardening and Pilot Proof

Work:

- all gates in `07-acceptance-and-release-gates.md`;
- source mutation, conflict, stale capture, policy bypass, partial reveal, and output mismatch adversarial tests;
- 30-figure and synthetic 60-page memory/performance runs;
- production app end-to-end proof without store swapping;
- independent content/safety/engineering/UX review;
- close or disposition every finding.

Exit gate: no P0/P1, all required approvals, artifact receipts, and a reproducible live result.

## 11. Parallel Work Tracks

After Phase 0 contract freeze:

| Track | Can start | Depends on | Merge gate |
| --- | --- | --- | --- |
| A: standards/configuration evidence | Immediately | reviewer access and source licenses | evidence schema stable |
| B: shared Documentation foundation | Immediately | type-registry contract | parts-manual regression pass |
| C: evidence repository/policy | Immediately | evidence schema | contract tests |
| D: operations recipes/planner | After C schema | evidence API | plan audit pass |
| E: landscape page UI/progressive reveal | After B block identity | page masters and event contract | settled-capture tests |
| F: CAD figure requests | After B figure contract | existing CAD/capture APIs | figure QA/memory tests |
| G: PDF renderer | After semantic block contract | compiler and masters | PDF audit |
| H: DOCX renderer | After semantic block contract | compiler and approved dependency | DOCX parity audit |
| I: Sage tools | After C/D API contracts | policy and revisions | orchestration tests |
| J: pilot proof | After all tracks | approved evidence and live build | release gates |

No track should invent its own block IDs, revisions, figure identity, or source model.

## 12. First Implementation Slice

The safest first vertical slice is:

1. satisfy the Phase 0 entry blockers above;
2. register `operations_and_maintenance_manual`;
3. open a blank operations document;
4. implement and pass the synthetic 60-page flow/pagination fixture;
5. load and validate the source/evidence/symbol/approval registers;
6. propose and explicitly approve three non-safety sections: cover, product overview, specifications;
7. generate structured semantic blocks through the flow engine;
8. generate one neutral CAD figure whose caption mentions only verified modeled features, with the feature-target validator active;
9. show sequential settled pages and real thumbnails;
10. export matching draft PDF and DOCX only through approved, pinned dependencies;
11. return hashes, revisions, semantic-block parity, and visible blockers.

This proves the architecture before safety procedures or maintenance are added, while confronting long-form pagination at the beginning instead of deferring it behind a misleading fixed-rectangle demo.

## 13. Deferred Until Evidence Exists

- approved charging procedure;
- maintenance-isolator engagement procedure;
- hydraulic/electrical service procedures and schematics;
- exact maintenance fluids, quantities, torques, pressure settings, and intervals;
- released CE/compliance content;
- OEM parts mapping;
- external DOCX reimport/round-trip editing.
