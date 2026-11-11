# Documentation Editor Capability Gap Matrix

Assessment: 2026-11-09, source checkout HEAD `1a8030a`. Companion to the [audit, technology comparison and architecture recommendation](documentation-editor-audit-and-strategy.md).

This matrix describes implementation found in the source, not newly executed UI tests. A generated layout or a library capability is not counted as a user-editable feature. Missing means not found in the documentation editing paths inspected, not proof that no unrelated workflow has similar functionality.

## Reading the Matrix

- **Implemented:** exists for the scope stated, not necessarily Office parity.
- **Partial:** limited to certain objects/document types, generated-only, or missing editing/export behavior.
- **Missing:** no usable general documentation implementation found.
- Office comparison is a reference for typical desktop Word/PowerPoint behavior, not a version-specific parity certification. Word is primarily a flowing document editor; PowerPoint is primarily a positioned slide editor. CAD-linked capabilities are specialized InspectorPro functions, not standard Office functionality.
- Improvement effort assumes the recommended shared command service and rich-text adapter exist: **S** = 1-3 engineer-days; **M** = 4-10 days; **L** = 2-4 weeks; **XL** = 5+ weeks. These are overlapping estimates with export/tests included where stated, not additive promises. Validate through the prototype.
- Source references point to the actual files. Detailed risks and architectural dependencies are in the main report.

## A. Text Editing and Typography

| Capability | Word / PowerPoint reference | InspectorPro today and implementation | Improvement and effort |
|---|---|---|---|
| Direct text editing and cursor selection | Both: rich text with caret/range editing | **Implemented for plain fields.** Browser `contenteditable`, DOM Range selection, blur/Enter commit; no persisted inline marks. Specification slots have a separate path. [R1], [R15] | Preserve current entry points; replace eligible editing internals with the chosen framework. **M** |
| Fonts and font sizes | Both: selected ranges and reusable formatting | **Partial.** Bounded font family and size fields; object/master-element styling, not arbitrary runs. [R2], [R15] | Range marks, font licensing/availability and consistent export metrics. **M** |
| Font color | Both: per-range color | **Partial.** Whole-object/element color and theme colors. [R2], [R15] | Add range-level color with approved palette and export mapping. **S-M** |
| Text highlighting | Both: highlighting, with version differences | **Missing as text-range highlighting.** Shape fill is not a highlight mark. [R2] | Rich-text highlight extension and exporter support. **S-M** |
| Bold, italic, underline | Both: per-range marks | **Partial.** Whole text-object and selected master-element B/I/U; plain-string content remains. PDF underline is simplified. [R1], [R2], [R11] | Reuse editor marks; test mixed/multiline runs in PDF/DOCX. **M** |
| Strikethrough | Both | **Missing.** Style whitelist permits underline/none, not strike. [R2] | Editor mark plus export representation. **S** |
| Superscript/subscript | Both | **Missing as formatting.** Pasted Unicode characters are not equivalent. [R2] | Editor marks and font/line-height/export tests. **S-M** |
| Paragraph alignment | Both | **Partial.** Left/center/right object style; not full paragraph-range alignment/justification. [R2] | Paragraph attributes and ribbon integration. **M** |
| Indentation | Both; Word has richer paragraph/ruler control | **Missing as a general edit command.** Generated layout offsets are not paragraph indentation. [R2], [R12] | Structured paragraph/list indentation and export. **M** |
| Line and paragraph spacing | Both | **Partial generated styles only.** Renderers consume layout styles; no comprehensive editing controls/schema. [R2], [R12], [R15] | Shared spacing attributes; overflow checks. **M** |
| Bulleted, numbered, multilevel lists | Word: rich numbering; PowerPoint: bullets/numbering and nested levels | **Partial.** Generated list blocks and editable item strings; no general list authoring/nesting model in the scene editor. [R9], [R12] | Framework list extensions; deterministic numbering and stable item IDs. **M-L** |
| Heading/reusable text styles | Word: semantic heading hierarchy; PowerPoint: theme/master text levels | **Partial.** Generated headings and title/heading/body/caption/accent style references with a document theme. [R2], [R12] | Semantic paragraph styles; named-style UI; TOC linkage. **M** |
| Find and replace | Both, with different formatting options | **Missing as a document-editing tool.** Reading page text through Sage is not a reliable replace-all engine. [R9] | Search full text by stable ID; scoped replacements with conflict checks and atomic undo. **M** |
| Spellcheck | Both: proofing tools | **Partial.** Browser `spellcheck=true`; no verified engineering dictionary, language configuration or offline proofing UX. [R1], [R15] | Verify Electron spellcheck/privacy settings; add dictionary controls only if required. **S-M** |
| Symbols/special characters | Both | **Partial.** Text can contain characters; no general engineering-symbol picker and no guaranteed PDF glyph coverage. [R11], [R18] | Approved symbol palette, Unicode font coverage, export validation. **M** |
| Equations | Both: editable equation objects | **Missing.** Tolerance parsing is not a general equation editor. [R18] | Optional math node/renderer and native DOCX equation or explicit fallback policy. **L** |

## B. Page and Document Layout

| Capability | Word / PowerPoint reference | InspectorPro today and implementation | Improvement and effort |
|---|---|---|---|
| Paper sizes/orientation | Word: paper and section orientation; PowerPoint: slide size/orientation | **Partial.** Fixed generated layouts, e.g. Letter landscape manuals and portrait specification sheets; no general page setup. [R5], [R7] | Validated A4/Letter and orientation presets, reflow/fit checks across generators/exporters. **L** |
| Margins | Word: editable margins; PowerPoint: layout/guide-based positioning | **Partial.** Predefined safe areas and export margins. [R5], [R12] | Page-layout properties with safe-area validation and export agreement. **M-L** |
| Columns | Word: flowing columns; PowerPoint: text columns/independent boxes | **Partial generated composition only.** Fixed illustration/BOM or table columns are not editable narrative columns. [R5], [R12] | Defer flowing columns; bounded text-column support needs explicit layout mode. **L-XL** |
| Page breaks | Word: manual/automatic breaks; PowerPoint: separate slides | **Partial.** Generators create pages and exports insert breaks; no general manual-break editing command. [R4], [R12] | Explicit breaks within a supported flow section or explicit page insertion. **M-L** |
| Headers and footers | Word: section headers/footers; PowerPoint: masters/footer fields | **Partial.** Theme/page masters, header/footer elements and selected text overrides already exist. [R2], [R12] | Editable bounded master regions, per-section overrides and repeat behavior. **M-L** |
| Page numbering | Word: page fields; PowerPoint: slide numbers | **Implemented in generated publications.** Numbered pages and DOCX PAGE/NUMPAGES fields where supported. [R4], [R12] | Number-format/start options and regression tests after reordering. **S-M** |
| Pagination | Word: text/table flow; PowerPoint: fixed slide boundaries | **Partial.** Manual BOM/index rows split by generator; fixed-page narrative/specification layouts and fit logic. Not general live text reflow. [R4], [R5], [R13] | Prototype flow engine only when needed; retain explicit overflow for fixed pages. **XL** |
| Table of contents | Word: heading-derived fields; PowerPoint: manual/linked agenda | **Partial.** Generated contents entries/page numbers; not an arbitrary field-driven TOC editor. [R4], [R12] | Rebuild from stable section IDs after layout; export navigation/bookmarks. **M-L** |
| Sections and section breaks | Word: section formatting; PowerPoint: slide organization | **Partial.** Approved manual sections and work stages; no generic page-section break model. [R4], [R8] | Separate semantic sections from layout sections; preserve figure/part ownership. **L** |
| Templates and master layouts | Word: templates/styles; PowerPoint: slide masters/layouts | **Partial.** Save/apply versioned theme/page-master templates and predefined cover/technical/reference masters, not complete page composition. [R2], [R19] | Extend template schemas, bounded master editing, migration and preview. **L** |
| Backgrounds and borders | Both, with different page/slide behavior | **Partial.** Generated brand bands, theme fills and object outlines; no general page-border/background editor. [R2], [R5], [R12] | Page background/border attributes, printable contrast and export. **M** |
| Watermarks | Word: page watermark; PowerPoint: master object | **Missing as a managed document feature.** A manually positioned object is not a repeatable watermark policy. [R2] | Repeating non-content master layer with export and permission controls. **M** |

## C. Tables

| Capability | Word / PowerPoint reference | InspectorPro today and implementation | Improvement and effort |
|---|---|---|---|
| Insert/delete arbitrary tables | Both | **Partial generated-only.** BOM/specification/operations tables exist; generic document objects do not include a table type. [R2], [R4], [R7], [R12] | Framework table nodes for user tables; dedicated constrained CAD table type. **M-L** |
| Add/remove rows | Both | **Partial.** Specification row controls exist; no uniform row editing for every table. [R6], [R16] | General typed row operations with persistent IDs and undo. **M** |
| Add/remove columns | Both | **Missing as a generic edit operation.** Generated columns are schema-owned. [R2], [R12] | Table schema/controls; protect required BOM columns. **M** |
| Merge/split cells | Both | **Missing.** No validated cell-span editing model found. [R2], [R12] | Reuse table extension commands plus server-side span validation. **M-L** |
| Cell formatting/alignment | Both | **Partial.** Generated headers/body styling and editable cell strings; no full per-cell formatting UI. [R9], [R12] | Rich cell content, alignment, fills/borders, validation and export. **M** |
| Table styles | Both | **Partial.** Theme table colors and fixed exporter styles; no general style gallery. [R2], [R12] | Small named style set shared across screen/export. **M** |
| Column widths | Both | **Partial generated-only.** Fixed/table layout calculations rather than interactive widths. [R5], [R13] | Column resizing with minimum widths and page overflow checks. **M-L** |
| Row heights | Both | **Partial generated-only.** Content fit and table height calculations; no general height editing. [R13] | Auto/minimum/exact height policy; reject clipped content. **M-L** |
| Whole-table resizing | Both | **Missing as a consistent user operation.** Moving page regions is not a generic table resize. [R2], [R15] | Table frame constraints and logical column scaling. **M** |
| Automatic BOM generation | Not standard CAD-backed Office behavior | **Implemented.** Catalog/section-derived rows, quantities and part identifiers. [R4] | Preserve; broaden engineering acceptance tests rather than replace with a generic table. **S-M** |
| Dynamic CAD metadata links | Requires specialized Office integrations | **Partial but substantial.** Definition IDs, source revisions, shared description overrides and figure invalidation; no complete regeneration merge. [R3], [R4] | Stable row/column identity and three-way refresh preserving manual notes. **L** |

## D. Images, Drawings and Graphics

Object rows updated for P4a-1 (2026-11-11); implementation is awaiting the supervisor runtime gate. PDFs preserve page stacking. DOCX places authored objects in top/left/ID reading order, without overlap or stacking; images remain native pictures and each shape is its own transparent 4 px/pt picture.

| Capability | Word / PowerPoint reference | InspectorPro today and implementation | Improvement and effort |
|---|---|---|---|
| Image insertion | Both | Managed PNG/JPEG objects now draw in parts, operations, work-instruction and specification PDFs (including fillable), and the three existing DOCX formats. [R20] | No parts DOCX or inspection-sheet objects. Runtime matrix pending. |
| Image resizing | Both | Complete frame and aspect-lock model; Sage partial-frame edits preserve the ratio for a lone width/height. Legacy resize also enforces the lock. [R20] | Workspace aspect-lock and new handles are P4a-2. |
| Image cropping | Both | Fractional source crop, contain and centred cover share the page/PDF/DOCX placement rule. Sage can set or clear crop. [R20] | Workspace crop mode is P4a-2. |
| Image rotation | Both | Clockwise frame-centred quarter turns; old free-angle images remain readable but refuse export by object ID. [R20] | Free-angle images remain outside scope. |
| Text wrapping | Word: anchored wrap modes; PowerPoint: mainly independent boxes | **Missing.** Absolute image frames do not cause narrative text to flow around them. [R2], [R5] | Defer Word-style float layout unless required; block/inline images first. **L-XL** |
| Image alignment/anchoring | Both, different models | Page-relative frames and server alignment/distribution include rotated objects. CAD anchors are unchanged. [R20] | No paragraph anchoring or text wrap. Workspace controls are P4a-2. |
| Shapes, arrows, lines and callouts | Both | Rectangle, ellipse, arrow, revision cloud and detail box share the canvas paths in all PDFs; DOCX uses one transparent picture per shape. Opacity applies to all authored object types. CAD callouts are unchanged. [R20] | Runtime pixels and Word render pending. |
| Text boxes | Both | P3 rich text and authored tables remain supported. P4a adds aspect lock, frame/order operations and opacity in the object flow. [R20] | PDF/DOCX rich-text rotation refusals remain; DOCX text flows in a native table. |
| Grouping and layering | Both; stronger slide/object workflow in PowerPoint | Persisted bottom-to-top order and undo, with Sage bring/send operations. No general object grouping. [R20] | Workspace layer controls are P4a-2; groups remain later. |
| Object alignment/distribution | Both | Eight server-computed arrangements use rotated page boxes, equal gaps and atomic undo. Sage exposes them with object hashes. [R20] | Workspace controls and multi-selection are P4a-2. |
| Captions/figure numbering | Word: caption/reference fields; PowerPoint: largely manual | **Partial.** Generated figure captions and numbers; editable caption text, no arbitrary cross-reference fields. [R4], [R9], [R12] | Stable figure IDs and automatic reference resolution. **M-L** |
| CAD-generated/exploded illustrations | Requires CAD tooling outside standard Office | **Implemented.** CAD visualization, explosion/callout commands, revision-bound captures and selective refresh. [R2], [R4], [R8] | Retain; validate links after edits and preserve unaffected captures. **M** |

## E. PowerPoint-Style Editing

| Capability | Word / PowerPoint reference | InspectorPro today and implementation | Improvement and effort |
|---|---|---|---|
| Slide/canvas editing | Word: page/flow; PowerPoint: full slide canvas | **Partial.** Positioned publication pages and objects, not a separate slide document model. [R2], [R5] | Distinct presentation layout mode if justified; reuse page object IDs/commands. **L-XL** |
| Drag/drop object positioning | Word: anchored objects; PowerPoint: free placement | **Implemented for supported document objects/CAD controls.** Not evidence that every generated block is freely draggable. [R1], [R2] | Consistent frame/property controls and keyboard nudging. **M** |
| Independent text/graphics | Both | Text, image and shape objects share the ordered page/PDF walk. DOCX keeps editable text, native images and individual shape pictures in reading order. [R20] | DOCX overlap and stacking are intentionally not reproduced. |
| Shapes and diagrams | Both; PowerPoint has richer diagram workflows | **Partial.** Basic shapes and engineering callouts, no general connector/diagram editing system. [R2] | Scoped connectors/diagram library only on actual demand. **L** |
| Alignment guides/snapping | Word: object guides; PowerPoint: slide alignment guides | **Partial.** Existing snap-guide and arrangement helpers primarily serve documentation/CAD selections. [R15] | Uniform object edges/centers and explicit page units; no CAD-coordinate leakage. **M-L** |
| Layer ordering | Both | Schema-7 objectOrder drives the canvas and every PDF, and restores deleted objects at their old depth. DOCX retains flow order. [R20] | Workspace bring/send controls are P4a-2. |
| Group/ungroup | Both | **Missing for arbitrary page objects.** Manual CAD section/group ownership is a different concept. [R2] | Group identity, nested transforms, undo and export support. **L** |
| Slide templates/master layouts | Word: templates; PowerPoint: slide masters/layouts | **Partial.** Publication templates/masters, not presentation slide masters. [R2], [R1] | Extend only for a presentation document type; avoid redefining manuals as slides. **L** |
| Presentation export | PowerPoint: PPTX/PDF; Word: DOCX/PDF | **Missing PPTX export in the inspected documentation paths.** | Add one native PPTX generator with a declared editable-object subset; do not rasterize whole slides by default. **L** |

## F. Professional Documentation

| Capability | Word / PowerPoint reference | InspectorPro today and implementation | Improvement and effort |
|---|---|---|---|
| Document templates | Both | **Partial.** Generated workflow templates and saved theme/page-master templates; not arbitrary authored-document templates. [R2], [R7], [R19] | Extend existing template versioning with content schemas and compatibility checks. **M-L** |
| Automatic numbering | Word: headings/lists/captions; PowerPoint: slides/lists | **Partial.** Generated page, part item and figure numbering; no universal editable numbering fields. [R4], [R12] | Typed numbering scopes tied to stable IDs. **M-L** |
| Cross-references | Word: fields; PowerPoint: links/manual labels | **Partial.** Generated contents/figure relationships; no arbitrary authorable cross-reference field system. [R4], [R12] | Resolved reference nodes with missing-target validation. **M-L** |
| Revision tables | Usually authored as tables/templates in Office | **Partial.** Generated document-control/revision information, not a complete revision approval workflow. [R11], [R12] | Tie revision records to actual publication transactions; no invented approvals. **M-L** |
| Approval/signature blocks | Word supports form/signature workflows; PowerPoint mainly authored objects | **Partial.** Inspection fields/sign-off and document release/acceptance gates; not general verified e-signatures. [R7], [R8], [R18] | Keep human-controlled sign-off; design identity/audit workflow separately from drawing a signature image. **L-XL** |
| Engineering symbols | Both support characters/equation objects; not CAD semantics by default | **Partial.** Engineering text/tolerance handling in domain workflows; no shared picker/coverage policy. [R11], [R18] | Curated symbols plus approved fonts and export checks. **M** |
| Units and tolerances | Office generally stores authored text | **Implemented in specific domain fields**, including specification units/CAD values and inspection tolerance logic, not every free text box. [R6], [R7], [R18] | Retain typed values and formatting units separately; expand only to verified fields. **M-L** |
| Parts lists/BOMs | Requires data integration | **Implemented.** Automatic catalog/section lists with shared editable descriptions. [R4] | Safe refresh and optional user-note columns; protect calculated quantities. **L** |
| Document metadata | Both | **Implemented for workflow-specific metadata** and source/manual/document revisions; not every Office property. [R3], [R4], [R7] | Unified metadata editor with permissions and export mapping. **M** |
| Print preview | Both | **Partial.** Publication page display and exported PDF, not guaranteed print-identical preview for all features. [R5], [R11], [R12], [R13], [R14] | Preview from the actual export/layout result and disclose unsupported items. **M-L** |
| PDF export | Both | **Implemented for supported document workflows**, including specialized fillable PDFs; fidelity/licensing gates remain. [R11], [R12], [R13], [R14], [R17] | Rich text, object coverage, font consistency, overflow and license resolution. **L** |
| DOCX export | Word: native; PowerPoint: not equivalent editable slide export | **Partial.** Implemented for operations manuals, work instructions and specification sheets; no general parts-manual DOCX path found. No arbitrary DOCX round trip. [R12], [R13], [R14] | Extend existing python-docx mappings; declare supported edits and layouts. **L** |
| PPTX export | PowerPoint: native; Word: not normal document output | **Missing.** | Same future presentation exporter described in E; do not double-count effort. **L** |

## G. Agent-Driven Editing

| Capability | Office automation comparison | InspectorPro today and implementation | Improvement and effort |
|---|---|---|---|
| Programmatic text insertion | Office object models can insert ranges/text boxes | **Partial.** Generation inserts content; current generic Sage text tool replaces existing targets, not arbitrary new paragraphs. [R8], [R9] | Typed insert operations at stable block boundaries. **M** |
| Programmatic text replacement | Office range/object operations | **Implemented for authorized existing text targets**, but read/write race and truncation risks remain. [R9], [R10] | Full targeted read, observed hash/revision and atomic batch. **M-L** |
| Programmatic formatting | Office style/range APIs | **Partial below Sage.** Scene `update_style` exists, but the generic text tool exposes no format operation. [R2], [R9] | Expose allowlisted semantic styles/marks through the shared service, not raw script. **M** |
| Table generation/modification | Office table APIs | **Partial.** Deterministic BOM and generated tables; specialized specification tools, not generic cell/row/column editing tools. [R4], [R6], [R8] | Table operations with stable IDs; distinguish authored and derived tables. **M-L** |
| Image/CAD-view placement | Office image/shape APIs; CAD requires integration | read_document_objects plus frame, crop, order and arrangement operations use managed asset IDs and pre-image hashes. One page, at most twelve object operations per atomic batch. [R20] | Sage cannot add/delete objects. CAD transforms/captures are unchanged. |
| Document reorganization | Office sections/slides/paragraph moves | **Partial.** Parts-section moves have dedicated validation; no general block/page reorganization tool. [R8] | Reuse section logic; add stable block/page moves only where supported. **M-L** |
| Targeted section updates | Office ranges/content controls; identity policy is application work | **Partial.** Page/target IDs and definition-keyed part text, but table/list targets are positional. [R4], [R9] | Stable element IDs and three-way generated/manual merge. **L** |
| Agent-change undo/redo | Depends on API/host transaction behavior | **Partial.** Scene history covers committed scene commands; generic agent text batches are multiple commits, slots separate. [R3], [R6], [R10], [R16] | One atomic change group and conflict-aware targeted undo. **L** |
| User approval | Not automatic from an Office API | **Partial and workflow-specific.** Approved structures/evidence and release gates; ordinary text edits execute directly when requested. [R8], [R9] | Preserve low-latency direct edits with undo; require explicit authority for destructive/verified/release changes. **M** |
| Preservation of manual edits | Not guaranteed merely by selecting an editor | **Partial.** Overlay strings and narrow rebind behavior preserve many edits; stale rebaseline can clear them. [R3], [R4] | Three-way merge, manual locks, conflict reporting, orphan handling and recoverable versions. **L-XL** |
| Reliable selection/targeting | Office ranges or shape IDs; durability varies | **Partial.** Existing target validation and source binding, but range targeting and durable cell/list identity missing. [R2], [R9] | IDs + content hashes + explicit Unicode range convention; no screen coordinates. **M-L** |
| Atomicity, retries and completion | Host APIs vary; integration must provide guarantees | **Partial.** Atomic single-command writes; sequential text batches; some workflows only queued after reply. [R3], [R8], [R10] | Idempotent atomic batches, job states, cancellation boundaries and final validation receipts. **L** |

## Prioritized Scope

### First release

Manual-edit preservation, stable targets, atomic Sage changes, trustworthy undo; rich text, headings/lists, find/replace, general authored tables; consistent image/object behavior and supported PDF/DOCX output. Keep the ribbon/sidebar conventions and the CAD-specific tools already implemented.

### Later, after evidence of demand

Word-style wrapping/columns, arbitrary long-document flow, full master designer, equation authoring, collaboration/track changes, verified digital signatures, independent presentation editing and arbitrary DOCX/PPTX import/export round trips. These are separate scopes, not capabilities obtained automatically by installing a rich-text package.

### Do not weaken

CAD-derived quantities and geometry, evidence/acceptance state, verified engineering fields, source-revision validation, managed asset boundaries, human approvals and manual-edit provenance. A formatting upgrade must not turn these into unvalidated strings.

## Sources

The [main report's source index](documentation-editor-audit-and-strategy.md#22-source-evidence-index) provides function-level explanations. These links open the reviewed files:

[R1]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/static/index.html:39306
[R2]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/parts_manual/documentation.py:26
[R3]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/parts_manual/documentation.py:1407
[R4]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/parts_manual/document.py:143
[R5]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/parts_manual/layout.py:10
[R6]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/specification_sheet/slots.py:161
[R7]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/specification_sheet/document.py:201
[R8]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/codex_runtime/documentation_tools.py:583
[R9]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/codex_runtime/documentation_tools.py:701
[R10]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/server.py:41247
[R11]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/parts_manual/pdf.py:80
[R12]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/operations_manual/exports.py:638
[R13]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/specification_sheet/exports.py:235
[R14]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/work_instructions/exports.py:148
[R15]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/static/index.html:40821
[R16]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/server.py:18452
[R17]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/requirements.txt:25
[R18]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/inspection_sheet/document.py:208
[R19]: C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/server.py:17048
[R20]: ../ai_inspector/documentation/objects.py
