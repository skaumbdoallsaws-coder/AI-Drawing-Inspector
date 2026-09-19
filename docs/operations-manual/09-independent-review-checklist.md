# Independent Review Checklist

## Review Objective

Determine whether this pre-coding package is sufficient to begin implementation of a reusable, evidence-bound operations-manual workflow without introducing unsafe claims, product-specific architecture, or test-only production dependencies.

Review the package and the current codebase. Do not judge only the prose; verify claimed reuse boundaries against actual modules.

## 1. Scope and Authority

- [ ] Product, configuration, jurisdiction, audience, and outputs are explicit.
- [ ] Prototype and production-release states cannot be confused.
- [ ] Approval roles are appropriate and Sage is not treated as an engineering authority.
- [ ] Non-goals prevent unsupported certification, service, and LOTO content.

## 2. Sources and Evidence

- [ ] Registered local hashes match actual files.
- [ ] URLs, editions/dates, access dates, and authority classifications are accurate.
- [ ] Copyright/licensing restrictions are recorded and respected.
- [ ] Current OEM, legacy OEM, CAD, standard, regulatory, derived, and inferred evidence stay distinct.
- [ ] Battery/charger, brake, revision/effectivity, CE, part-number, dimension, and maintenance conflicts are complete and correctly resolved.
- [ ] Advertised maintenance safety bars, isolator, and emergency relief valve are reconciled against exact CAD occurrences; unmapped features remain blocked.
- [ ] Every repository-local source has a non-null verified SHA-256, including the internal assembly registry.
- [ ] No product fact from the TLIFT440 reference enters the MMLE plan.
- [ ] Every proposed factual section can be traced to claims or remains blocked.

## 3. Standards Strategy

- [ ] ANSI MH29.1 and ANSI/NEMA Z535.6 are correctly prioritized for the US baseline.
- [ ] OSHA 1910.145/147/212 are not misrepresented as a substitute for product engineering/manual standards.
- [ ] ISO/IEC/EN sources are treated as applicability-dependent, licensed standards.
- [ ] No compliance claim is inferred from listing a standard.
- [ ] Safety symbol and signal-word assets require controlled/licensed sources.
- [ ] Each standards record has a named edition-currency review before acquisition/use.

## 4. Manual Architecture

- [ ] Information architecture covers operator, owner/supervisor, and qualified-maintenance needs without mixing roles.
- [ ] Section recipes define required evidence, allowed blocks, prohibited inference, and hard gates.
- [ ] Safety blocks require hazard, consequence where applicable, avoidance, source, severity approval, and symbol identity.
- [ ] Tables, figures, procedures, records, and citations are semantic objects.
- [ ] PDF is controlled and DOCX is explicitly an editable working copy.
- [ ] Accessibility/localization requirements are realistic and testable.
- [ ] WCAG 2.2 AA and PDF/UA-2 targets, font embedding, and quotation thresholds have measurable audits.
- [ ] External DOCX edits cannot be represented as returning to controlled status in V1.

## 5. CAD and Figure Plan

- [ ] Existing MMLE semantic groups/components support the ready figure requests.
- [ ] CAD is not used as evidence for ratings, operating limits, or procedures.
- [ ] Hazard overlays, action arrows, and identification callouts are separate layers.
- [ ] Blocked figures truly require missing evidence and are not quietly approximated.
- [ ] `isolate_scope`/`context_scope` cannot be empty, and every named feature maps to verified target occurrences.
- [ ] Viewport/capture/PDF/DOCX parity is based on one accepted artifact/manifest.

## 6. System Contract

- [ ] One shared Documentation Workspace plus document-type definitions is the correct boundary.
- [ ] Reuse recommendations match the actual current code and avoid a risky rewrite.
- [ ] Source, evidence, plan, scene, document, and artifact revisions are complete and non-overlapping.
- [ ] LLM responsibilities stop at evidence-bound structured content, not page coordinates or severity.
- [ ] Intent/tool allowlists prevent read-only, generation, approval, and publication capabilities from bleeding together.
- [ ] The end-to-end tool is only orchestration over public production APIs.
- [ ] Progressive generation reflects real work and cannot contaminate captures.
- [ ] Memory-bounded capture and restart/resume behavior address the observed browser pressure.
- [ ] A real flowing-text engine, not fixed rectangles or font shrinking, is part of slice 1 and passes the 60-page fixture.

## 7. Export and Runtime Boundaries

- [ ] PDF and DOCX consume the same compiled semantic document and accepted figures.
- [ ] DOCX pagination differences do not break semantic cross-references.
- [ ] PyMuPDF has an approved license disposition before implementation; `python-docx` is pinned/hash-locked before its track begins.
- [ ] Internal asset revisions cannot populate OEM/controlled document revision fields.
- [ ] Runtime gates live in production code, while `.runtime`, smoke, benchmark, and proof scripts only verify them.
- [ ] No test swaps the production plan/source store or injects better evidence than the customer workflow has.

## 8. Acceptance Criteria

- [ ] Hard publication failures cover unsupported claims, stale state, partial rendering, role violations, and output mismatch.
- [ ] Tests cover evidence, content, safety, CAD, UI, PDF, DOCX, memory, orchestration, and live production.
- [ ] P0/P1 definitions are appropriate for a customer pilot.
- [ ] The proof bundle is sufficient to reproduce and independently inspect a live publication.
- [ ] Named reviewers and revision-bound approval receipts validate against the approval schema.
- [ ] Pilot machine/browser profile and numeric memory budgets are recorded.
- [ ] Superseded/withdrawn publication handling is explicit and preserves immutable artifacts.

## 9. Required Review Output

Return:

1. findings first, ordered P0/P1/P2, with file/section references;
2. any incorrect or missing source/conflict decision;
3. any architecture that is too product-specific or duplicates current code;
4. any requirement that is not objectively testable;
5. any safety/compliance claim that exceeds its evidence;
6. recommended corrections;
7. final verdict: `NOT READY`, `READY WITH CONDITIONS`, or `READY FOR IMPLEMENTATION`.

Do not implement feature code during this review. Correct documentation or registers only when explicitly authorized after reporting findings.
