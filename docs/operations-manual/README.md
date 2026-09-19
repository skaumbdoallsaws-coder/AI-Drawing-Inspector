# MMLE-50D Operations Manual: Pre-Coding Package

Status: **Draft Documentation workspace implemented; controlled publication gates remain open**  
Prepared: 2026-08-20  
Target product: MMLE-50D Electric Mobile Lift  
Target workflow: InspectorPro Documentation

## Decision Summary

This package defines the work that must precede implementation of an AI-generated operations and maintenance manual.

The main decisions are:

1. InspectorPro keeps one shared **Documentation Workspace**. Parts manuals, operations manuals, work instructions, and inspection sheets are document types within that workspace, not separate editors.
2. Each document type owns a separate content schema, section recipes, templates, validation rules, and export policy.
3. The controlled PDF is the release artifact. A DOCX may be exported as an editable working copy, but any external edit permanently leaves InspectorPro's controlled chain in V1. DOCX reimport and round-trip revalidation are explicitly out of scope.
4. CAD proves identity, membership, geometry, and figure scope. CAD does not prove capacity, hazards, maintenance intervals, regulatory compliance, or operating procedure.
5. Sage may draft only from registered evidence. Every factual block must retain source provenance. Missing or conflicting facts remain unresolved; Sage must not synthesize a convenient answer.
6. The current Lift Products web page defines the current commercial baseline. The 2012 service manual is useful legacy evidence, but its battery, charging, brake, and service instructions require configuration review before use.
7. ANSI MH29.1 is the primary US product-category standard to obtain under license. ANSI/NEMA Z535.6 governs product-safety information in manuals. OSHA rules inform workplace obligations but do not replace product-specific engineering review.
8. The supplied TLIFT440 manual is a presentation and information-architecture reference only. Its product facts must never enter the MMLE-50D manual.
9. The prototype must be marked DRAFT until a responsible manufacturer or engineering authority approves product configuration, effectivity, warnings, operating limits, maintenance intervals, and service data.

## Package Contents

| File | Purpose |
| --- | --- |
| [01-scope-and-governance.md](01-scope-and-governance.md) | Product boundary, audiences, evidence classes, approvals, and release states |
| [02-source-and-evidence-register.md](02-source-and-evidence-register.md) | Human-readable source hierarchy, fact matrix, conflict register, and standards plan |
| [source-register.json](source-register.json) | Machine-readable source inventory with hashes, authority, access, and licensing |
| [source-register.schema.json](source-register.schema.json) | Validation contract for source registers |
| [evidence-register.json](evidence-register.json) | Machine-readable claims, applicability, conflicts, and approval state |
| [evidence-register.schema.json](evidence-register.schema.json) | Validation contract for evidence and conflict registers |
| [approval-receipt.schema.json](approval-receipt.schema.json) | Signed, revision-bound approval contract for engineering, safety, publication, product, legal, and accessibility review |
| [safety-symbol-register.json](safety-symbol-register.json) | Deliberately empty/blocking MMLE symbol inventory pending licensed assets and approval |
| [safety-symbol-register.schema.json](safety-symbol-register.schema.json) | Validation contract for licensed safety-symbol identity and usage |
| [operations-manual-plan.schema.json](operations-manual-plan.schema.json) | Validation contract for the approved section/block/figure plan |
| [mmle-50d-prototype-plan.example.json](mmle-50d-prototype-plan.example.json) | Three-section first-slice example conforming to the plan contract |
| [03-manual-content-standard.md](03-manual-content-standard.md) | Document architecture, safety communication, visual system, citations, PDF, and DOCX policy |
| [04-section-recipes.md](04-section-recipes.md) | Per-section evidence requirements, allowed content, figures, and hard gates |
| [05-storyboard-and-figure-inventory.md](05-storyboard-and-figure-inventory.md) | Prototype page sequence and CAD-grounded figure requests |
| [06-system-contract.md](06-system-contract.md) | Domain model, revisions, tools, orchestration, progressive generation, and runtime boundaries |
| [07-acceptance-and-release-gates.md](07-acceptance-and-release-gates.md) | Deterministic acceptance criteria and proof artifacts |
| [08-implementation-plan.md](08-implementation-plan.md) | Dependency-ordered implementation plan and parallel work tracks |
| [09-independent-review-checklist.md](09-independent-review-checklist.md) | Checklist for the independent agent reviewing this package |
| [10-review-disposition-2026-08-20.md](10-review-disposition-2026-08-20.md) | Disposition of the independent findings and the remaining external entry blockers |
| [11-workspace-implementation-2026-08-20.md](11-workspace-implementation-2026-08-20.md) | Implemented draft-workspace boundary, APIs, evidence compiler, browser proof, and remaining controlled-release work |

## Prototype Scope

The first implementation should generate an **MMLE-50D Operations and Maintenance Manual** in US English for trained operators, supervisors/owners, and qualified maintenance personnel. It should include:

- controlled cover, revision/effectivity, and table of contents;
- safety conventions and residual-hazard information;
- intended use, prohibited use, specifications, controls, and features;
- receiving/setup checks and pre-use inspection;
- operating, moving, charging, cleaning, and storage procedures;
- inspection and maintenance schedules with role boundaries;
- troubleshooting restricted to approved operator and service actions;
- service contact, records, source notes, and a parts-reference appendix;
- CAD-grounded figures and tables;
- controlled PDF plus an editable DOCX working copy.

The prototype does not authorize field use. It demonstrates the generation, review, editing, evidence, rendering, and publication pipeline.

## Go/No-Go State

**Go for a draft-only foundation:** the shared workspace, evidence repository, deterministic compiler, 16:9 landscape flow engine, revision-bound draft captures, progressive generation, and Sage draft tool are implemented. They remain explicitly unable to publish controlled PDF or DOCX output.

**No-go for controlled exporters or released content:** PyMuPDF licensing, named reviewer assignments, standards/symbol review, configuration effectivity, and safety-feature CAD mappings remain unresolved. The application enforces this state through the operations-manual release gate.

**No-go for production release:** the following remain unresolved:

- exact serial-number/configuration effectivity;
- manufacturer approval of current electrical and battery configuration;
- licensed clause-level review of ANSI MH29.1 and ANSI/NEMA Z535.6;
- verified load center and permitted load distribution;
- hydraulic oil grade, fill quantity, pressure settings, torque values, and approved lubricants;
- exact maintenance-isolator engagement procedure;
- current electrical and hydraulic schematics for the modeled configuration;
- approved replacement-part numbers and service contacts;
- confirmation that the CE claim applies to this exact modeled configuration;
- engineering, technical-writing, and safety approval receipts.
- traceable CAD mappings for advertised maintenance safety bars, maintenance isolator, and emergency relief valve;
- an approved PyMuPDF license disposition or renderer migration;
- remediation of the unqualified internal revision `A` in existing parts-manual output;
- named approvers, approved safety-symbol assets, font-license records, and accessibility audit tooling.

## Review Rule

An evaluator should reject this package if it finds any path that allows:

- an unsupported claim to become publication text;
- legacy and current configuration evidence to be silently blended;
- CAD filenames or InspectorPro library IDs to be represented as OEM part numbers;
- generation animation to masquerade as completed work;
- partial page state to enter PDF or DOCX output;
- test-only scripts to provide a production capability that the live application lacks;
- PDF and DOCX to be compiled from different semantic content.
- an advertised feature with no verified CAD occurrence to enter a figure caption or callout;
- an internal asset revision to be published as an OEM/controlled document revision;
- an unresolved renderer license or unapproved safety-symbol asset to pass a pilot publication gate.
