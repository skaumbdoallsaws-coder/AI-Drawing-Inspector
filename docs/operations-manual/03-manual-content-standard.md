# Operations Manual Content Standard

## 1. Document Type

Document type ID: `operations_and_maintenance_manual`  
Prototype title: `MMLE-50D Operations and Maintenance Manual`  
Primary release output: controlled PDF  
Secondary output: editable DOCX working copy

The manual is page-oriented in InspectorPro but content-driven underneath. A paragraph, warning, procedure step, specification row, figure, and citation remain semantic blocks, not unrelated canvas objects.

## 2. Information Architecture

The default section sequence is:

1. Cover
2. Document control, effectivity, approvals, and revision history
3. Table of contents
4. About this manual, audience, and conventions
5. Safety
6. Product description, intended use, and prohibited use
7. Specifications
8. Controls, indicators, and safety features
9. Receiving, setup, and pre-use inspection
10. Operating procedures
11. Moving and parking
12. Charging
13. Cleaning and storage
14. Inspection and maintenance
15. Troubleshooting
16. Service, replacement parts, and technical support
17. Inspection/maintenance records
18. Sources, standards, and document history
19. Optional parts-reference appendix

The compiler may paginate dynamically, but it may not reorder safety prerequisites behind the procedures that depend on them.

## 3. Page System

Use a 16:9 landscape page with a 960 x 540 pt logical coordinate system for the review workflow. Define reusable masters rather than fixed page screenshots:

| Master | Use | Required regions |
| --- | --- | --- |
| `operations_cover` | Cover | company/product identity, title, controlled status, product image, document metadata |
| `operations_front_matter` | Document control and TOC | header, main text/table region, footer |
| `operations_section_open` | Major section start | section number/title, purpose summary, optional full-width figure |
| `operations_procedure` | Sequential tasks | prerequisite/safety block, numbered steps, step figures, verification |
| `operations_reference` | Specs, maintenance, troubleshooting | table and supporting figure regions |
| `operations_figure` | CAD-heavy page | large figure, caption, legend/callouts, text inset |
| `operations_record` | Inspection/maintenance log | writable table, document metadata, continuation marking |

Header/footer content must include product, document number, revision, section/figure where relevant, and page X of Y. Release-state markings must be visually unavoidable.

## 4. Content Blocks

Supported semantic blocks for V1:

- `heading`
- `paragraph`
- `bullet_list`
- `safety_message`
- `procedure` containing ordered `procedure_step` records
- `figure`
- `figure_callout_legend`
- `specification_table`
- `maintenance_schedule`
- `troubleshooting_table`
- `checklist`
- `note`
- `source_note`
- `cross_reference`
- `revision_table`
- `approval_table`
- `record_table`

Every block carries stable identity, evidence links, audience/role, approval state, and local presentation overrides. Free canvas text is allowed for decorative or user-authored material, but release text must map to semantic blocks.

## 5. Writing Standard

- Use direct, task-oriented US English.
- Put one action in each numbered step.
- State prerequisites before actions.
- State the expected result or verification after safety-critical steps.
- Use the exact approved component/control display name consistently.
- Separate operator actions from qualified-maintenance actions.
- Use `must` only for an approved requirement; use `should` for recommendation; avoid vague `may` unless describing permission or possibility.
- Do not use marketing language in procedures.
- Do not turn absence of evidence into a reassuring claim.
- Keep measurements with units; retain source units and show a verified conversion when dual units are required.
- Do not direct the user to infer a location from prose when a figure can identify it.

## 6. Safety Communication System

### 6.1 Safety message anatomy

Every safety message must contain:

1. signal word;
2. hazard type/source;
3. consequence of exposure;
4. avoidance instruction;
5. role or operating state when needed;
6. one or more approved evidence claims.

The renderer must not allow color alone to communicate severity. The signal word, text, icon/symbol, border, and accessible label must remain legible in grayscale and for assistive technology.

### 6.2 Signal words

Use the final signal-word mapping only after licensed ANSI/NEMA Z535.6 review. Prototype styling may reserve:

| Type | Intended use | Prototype color role |
| --- | --- | --- |
| `DANGER` | Imminent hazard with the highest consequence level | red signal panel |
| `WARNING` | Hazard capable of death or serious injury | orange signal panel |
| `CAUTION` | Hazard capable of minor or moderate injury | yellow signal panel |
| `NOTICE` | Property, procedure, or reliability information without personal-injury hazard | blue signal panel |

Severity must come from approved risk evidence, never from an LLM's choice of adjective.

### 6.3 Symbols and colored warning panels

- Use licensed or customer-approved symbol assets tied to a symbol register.
- ISO 7010 assets must retain their registered geometry and meaning.
- Do not use image generation to create safety symbols.
- A safety panel is a structured object with `hazardId`, `signalWord`, `symbolIds`, message elements, evidence, and approval state.
- The same hazard ID may appear as an overview warning and as a contextual warning before a procedure, but wording variants remain linked.
- Printed color must pass contrast checks; grayscale output must preserve hierarchy.

### 6.4 Energy-control content

The manual may identify machine energy sources, stored-energy hazards, disconnect/isolation points, and the requirement for the employer's energy-control procedure. It must not fabricate a site-specific OSHA 1910.147 lockout/tagout program.

## 7. Figure Standard

### 7.1 Technical figure modes

- Neutral shaded view for product orientation and selected feature identification.
- Hidden Lines Removed for technical identification, exploded views, and service figures.
- Selective color overlay only for hazards, controls, movement arrows, exclusion zones, or user-approved emphasis.

The neutral-gray assembly view remains separate from stored GLB colors; rendering overrides do not alter source materials.

### 7.2 Figure requirements

Every figure contains:

- figure ID and caption;
- CAD source revision and visibility scope;
- camera/view/explosion state;
- component/group identity map;
- alt text and long description where needed;
- callout or legend mapping;
- evidence/purpose classification;
- accepted capture artifact bound to the compiled document revision.

Arrows indicating motion or action are procedure annotations. Dots indicate component identification. Hazard zones use a separate overlay style. The same line style must not ambiguously represent all three.

### 7.3 Figure quality

- 300 dpi effective resolution at placed size; minimum capture remains at least 2400 x 1800 for technical figures unless a figure-specific request requires more.
- white or transparent technical background as defined by the page master;
- no viewer chrome, ground plane, axis triad, selection outline, agent glow, or transient generation UI;
- visible geometry framed for the allocated region, not the whole assembly origin;
- no clipping, accidental occlusion, unrelated visible components, or unreadable tiny detail;
- viewport, stored capture, PDF, and DOCX must use the same accepted artifact and annotation manifest.

## 8. Tables

Tables are semantic and dynamically sized. Do not draw filler rows.

### Specifications

Columns: `Characteristic | Value | Source note` in review mode. Published output may omit source note when a source register is provided elsewhere.

### Maintenance schedule

Columns: `Interval | Task | Role | Machine state | Evidence/record`.

### Troubleshooting

Columns: `Symptom | Operator checks | Stop/use restriction | Qualified-service action | Reference`.

The operator column must never contain an action reserved for qualified maintenance.

## 9. Citations and Source Presentation

The live Sage response should link directly to approved public sources when explaining generated content. The manual itself uses controlled source notes and a Sources/Standards section rather than chat-style links on every sentence.

Each factual block retains invisible/internal provenance plus, where useful, a visible source marker. External links in PDF and DOCX must be descriptive, not bare URLs.

Do not quote more text than necessary. Manufacturer and standards content should be paraphrased unless a short exact warning phrase is approved and copyright/license permits it.

## 10. Theme and Brand

Branding is inherited in this order:

`CompanyTheme -> DocumentTemplate -> PageMaster -> Page -> Object override`

The theme defines logo, colors, heading/body fonts, safety-panel tokens, table rules, callout tokens, header/footer style, and default spacing. Local formatting never breaks semantic identity or safety severity.

The TLIFT440 reference establishes the desired balance of text, figures, and safety color, but InspectorPro should use its own brand system and customer template.

## 11. PDF Policy

The PDF is the controlled publication artifact. It must:

- compile from one immutable `documentRevision`;
- include document metadata, bookmarks, links, page labels, revision/effectivity, and release status;
- use accepted revision-bound figure artifacts;
- preserve selectable text and vector tables/annotations;
- have deterministic page count and TOC references;
- produce the tagged structure needed for the selected PDF/UA-2 target; a renderer that cannot do so is not eligible for a conformance claim;
- include a publication manifest and SHA-256 receipt.

PyMuPDF 1.27.2.3 is already installed and used by InspectorPro. Its published license is `AGPL-3.0-or-later OR Artifex commercial license`; this is a Phase 0 entry blocker, not a future deployment note. Before any pilot or commercial PDF work, InspectorPro must either obtain and record an Artifex commercial-license receipt, document an approved AGPL compliance disposition, or migrate to an approved renderer. The selected renderer/version must be pinned and recorded in the source register.

## 12. DOCX Policy

The DOCX is an editable working copy generated from the same compiled document as the PDF.

Recommended implementation: `python-docx` 1.2.0 (MIT) over ECMA-376/ISO 29500-compatible OOXML, subject to dependency review.

Requirements:

- named Word styles for headings, body, warnings, captions, tables, and lists;
- page/section breaks and headers/footers derived from the same page-master intent;
- figures inserted from the same accepted capture artifacts;
- alt text and descriptive captions where the library/OOXML implementation supports them;
- no floating-layout dependence for core reading order; prefer inline figures and stable tables;
- document properties include product, document number, revision, compiled revision, and export status;
- visible banner: `EDITABLE WORKING COPY - NOT CONTROLLED AFTER EXTERNAL EDIT`;
- a source/provenance appendix or custom data part when support is robust;
- Word and LibreOffice open/save smoke tests, plus XML/package validation.

External edits do not update InspectorPro's manual plan and cannot return to controlled status in V1. Reimport, semantic diff, and round-trip reapproval are future work and must not be shown or described as available.

## 13. Accessibility and Localization Readiness

Selected V1 targets:

- Documentation Workspace: WCAG 2.2 Level AA for the complete authoring workflow, including keyboard alternatives for drag interactions.
- Controlled PDF: PDF/UA-2 (`ISO 14289-2:2024`) plus format-independent content checks. No conformance claim is allowed until a named reviewer approves the target and an independent validator passes the exact artifact.
- DOCX working copy: structured headings, tables, lists, language, alt text, and Microsoft Word Accessibility Checker review. DOCX is not represented as PDF/UA-conformant.

- Define reading order independently of visual z-order.
- Require alt text for informative figures and mark decorative elements appropriately.
- Use actual table headers, lists, and headings, not painted text.
- Do not encode instructions only through position, color, or animation.
- Keep source values and units structured so localization and unit conversion do not rewrite prose manually.
- Keep text expansion tolerance in page templates.
- Animation obeys `prefers-reduced-motion` and never affects captured content.

## 14. Font Licensing and Embedding

V1 must not depend on whatever fonts happen to be installed on the server or viewer machine.

1. Select a primary sans-serif and technical monospace family with an explicit redistribution/embedding license. Noto Sans and Noto Sans Mono under OFL-1.1 are candidates, not approved assets until their exact files, versions, hashes, and license text are registered.
2. PDF export subsets and embeds every used font, including required symbols and non-ASCII glyphs. Missing glyphs are a hard export failure.
3. DOCX defines named theme fonts. Font embedding is enabled only when the recorded license permits it; otherwise the uncontrolled-copy notice identifies the required fonts and approved fallbacks.
4. A font manifest records family, style, source, version, asset hash, license, permitted outputs, subset status, and glyph coverage.
5. Acceptance uses text extraction, font-embedding inspection, and a fixed multilingual/glyph fixture. Substitution that changes pagination or warning meaning fails.

## 15. Quotation and Source-Similarity Policy

Generated prose is a sourced paraphrase, not a collage of OEM or standards text.

- Exact standards clauses, safety-symbol artwork, and copyrighted tables are never reproduced without a recorded license and approved purpose.
- An automated similarity check flags any run of 12 or more normalized consecutive source words or 80 or more substantially matching characters.
- A single external source contributes at most 25 verbatim words to an artifact unless a rights/quotation approval receipt explicitly permits more.
- Approved quotations are short, attributed, linked to source identity/location, and excluded from LLM rewriting.
- A flag blocks release pending technical-publications/license review; it is not automatically waived because the text is factually correct.

## 16. Quality Principle

The generated manual may be visually impressive during streaming, but publication quality is decided by evidence, semantic validation, accepted captures, and approval receipts. The reveal animation is a view of progress, not proof of completion.
