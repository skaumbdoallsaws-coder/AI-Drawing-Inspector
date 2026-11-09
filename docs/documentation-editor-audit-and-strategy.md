# Documentation Editor Audit and Enhancement Strategy

Assessment date: 2026-11-09. Source checkout: `AI-Drawing-Inspector`, HEAD `1a8030a` at audit completion.

Status: research and architecture recommendation only. No application implementation, dependency installation, document migration, desktop restart, or live Sage operation was performed. Findings are from source inspection and current primary-source documentation, not a new end-to-end test. Effort estimates and compatibility judgments below are engineering estimates, not vendor guarantees.

Companion deliverable: [Detailed Word/PowerPoint capability matrix](documentation-editor-capability-matrix.md).

## 1. Decision Summary

**Recommend Strategy D: retain InspectorPro's CAD-backed publication system and introduce Tiptap's open-source rich-text layer inside appropriate editable regions.** Keep the current page canvas, CAD figures, BOM semantics, evidence, document generation, managed assets, and revision checks. Do not replace them with an office file or an HTML blob.

InspectorPro already has more than a text viewer: positioned text/image/shape objects, direct text edits, appearance controls, publication templates, CAD-linked parts lists, figure capture, command history, and several export paths. However, it is not using an established rich-text framework. Its editable text is primarily a plain string per object, block, cell, or specification slot. Whole-object styling is not equivalent to formatting selected words.

The immediate opportunity is **professional engineering authoring**, not Office parity:

1. Preserve manual work reliably across agent updates and CAD regeneration.
2. Add normal rich text, lists, headings, and editable non-BOM tables using an existing editor.
3. Make the editing surface and PDF/DOCX exports agree on the supported features.
4. Improve page/object controls incrementally; defer a full presentation editor and arbitrary Office-file round-tripping.

Tiptap can run in vanilla JavaScript and supports custom node views, which suits the existing frontend without requiring a React rewrite. Its open-source core is separate from paid pagination and conversion offerings. This recommendation does **not** depend on purchasing Tiptap's AI, collaboration, Pages, or conversion services. [Vanilla integration](https://tiptap.dev/docs/editor/getting-started/install/vanilla-javascript), [custom node views](https://tiptap.dev/docs/editor/extensions/custom-extensions/node-views/javascript), [Tiptap product/license overview](https://tiptap.dev/).

**Important boundary:** adding a rich-text editor does not automatically solve pagination, CAD refresh conflicts, DOCX fidelity, or agent authorization. InspectorPro must continue to own those contracts.

## 2. Current Editor Audit

### 2.1 Implementation map

| Layer | Actual implementation | What should be retained |
|---|---|---|
| Documentation workspace | Custom JavaScript in `static/index.html`; DOM publication pages, SVG annotations/shapes, and CAD rendering/capture integration | Workspace navigation, ribbon/sidebar design, selection, CAD figure tools |
| Text editing | Browser `contenteditable`, `Range`, and `window.getSelection`; committed strings | Existing user workflows and field semantics, not the low-level caret implementation |
| Publication composition | `DocumentationSceneRepository`, JSON scene schema version 2, normalized object frames and command replay | IDs, domain validation, history, document/source binding |
| Parts-manual content | Generated document schema version 4 from assembly catalog and approved manual plan | BOM identity, quantities, section ownership, figure revisions |
| Operations/work instructions | Generated `layoutBlocks` with typed paragraphs, tables, lists, notes, figures and captions | Structured content, evidence and release checks |
| Specification sheet | Typed slots in a separate `slots.json` store, source/evidence/acceptance fields | Editable unknowns, explicit provenance, CAD-derived values |
| Assets | Managed PNG/JPEG assets with content hashes; CAD figure captures tied to revisions | Managed asset access and invalidation |
| Exports | PyMuPDF PDF paths; `python-docx` for operations/work instructions/specification sheets; specialized fillable PDFs | Existing successful outputs, after fidelity and licensing review |
| Sage | Typed documentation gateway tools and backend handlers; some workflows queue frontend captures after the turn | Authorization, assembly binding, deterministic generation, evidence checks |

No use of Tiptap, ProseMirror, Lexical, Slate, Quill, CKEditor, or ONLYOFFICE was found in the documentation editing paths inspected. This is not a claim about every unrelated library elsewhere in the repository.

### 2.2 Source evidence index

Line references are anchors for this checkout and will move as the large frontend file changes. Function names are the more durable search keys.

| ID | Source | Relevant evidence |
|---|---|---|
| R1 | [Inline editing and object controls](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/static/index.html:39306) | `_documentationBeginInlineTextEdit`; nearby drag, resize, style, rotate, template functions |
| R2 | [Scene schema and operations](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/parts_manual/documentation.py:26) | Supported targets/operations; fonts, objects, styles, theme and page masters; `_document_style` at 417 |
| R3 | [Scene persistence](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/parts_manual/documentation.py:1407) | Read/write/rebaseline; `apply_command` at 1596; `move_history` at 1900 |
| R4 | [Parts-manual document](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/parts_manual/document.py:143) | Definition-keyed text overrides; `build_manual_document` at 371; figure revision at 50 |
| R5 | [Publication layout](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/parts_manual/layout.py:10) | Letter landscape dimensions and predefined rectangles/page types |
| R6 | [Specification slots](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/specification_sheet/slots.py:161) | SlotStore, values, row operations, evidence, units, acceptance; separate persistence |
| R7 | [Specification document](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/specification_sheet/document.py:201) | Portrait layout, slots, CAD values, release gate; build at 452 |
| R8 | [Sage documentation tools](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/codex_runtime/documentation_tools.py:583) | Tool catalog, assembly/document binding, generation and evidence tools |
| R9 | [Sage text tools](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/codex_runtime/documentation_tools.py:701) | Read/edit schemas and text target construction at 734 |
| R10 | [Sage edit execution](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/server.py:41247) | Sequential per-edit writes and partial-failure reporting |
| R11 | [Parts-manual PDF](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/parts_manual/pdf.py:80) | Font mapping; document-object drawing at 926; PDF builder at 1056 |
| R12 | [Operations exports](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/operations_manual/exports.py:638) | PDF builder; DOCX builder at 1041; master/page-number fields at 858 |
| R13 | [Specification exports](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/specification_sheet/exports.py:235) | PDF, fillable PDF, returned values; DOCX at 609; overflow checks |
| R14 | [Work-instruction exports](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/work_instructions/exports.py:148) | Review DOCX export reuses operations export machinery |
| R15 | [Frontend properties](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/static/index.html:40821) | Selection-dependent properties, format controls around 41126; specification inline editor at 42403 |
| R16 | [Specification save handler](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/server.py:18452) | Slot changes are not routed through scene command history |
| R17 | [Export dependencies](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/requirements.txt:25) | Existing PyMuPDF licensing gate comment and python-docx dependency |
| R18 | [Inspection document](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/ai_inspector/inspection_sheet/document.py:208) | Structured engineering fields, requirements and conformance, not a generic equation editor |
| R19 | [Template save](C:/Users/might/OneDrive/Desktop/InspectorPro/AI-Drawing-Inspector/server.py:17048) | Versioned theme/page-master templates; does not save the whole page composition |

### 2.3 Editing, selection and formatting

The inline editor enables `contenteditable`, selects the node's contents using a DOM Range, and commits on blur or Enter. Escape cancels. The normal documentation path commits `textContent.trim()`; specification slots use `innerText` and their own save path. Browser spellcheck is enabled. There is no persisted rich-text range/mark model in these paths. Pasted formatting is not retained as an editable structured text document. [R1, R15]

The style schema allows font family/size/weight/style, underline, text alignment, color, shape fill/outline, line width and opacity. The font list is bounded. Frontend formatting is selection-dependent, principally document objects and certain master text elements. Applying a color to a text object does not provide arbitrary mixed colors within its sentence. There is no native rich-text extension/plugin registry; additions currently require coordinated schema, rendering, controls and exporter changes. [R2, R15]

The existing template-save endpoint persists a versioned theme and page masters, not a complete snapshot of all authored page objects and content. Template improvements should extend that explicit scope rather than assume a full document-template designer is already present. [R19]

### 2.4 Document and non-text representation

Generated pages contain semantic descriptors rather than editable Office files. Composition overlays hold translations, frames, styles, added objects and text overrides. Objects can be text, managed images or a limited shape set, including arrows, revision clouds and detail boxes. Frames use normalized page coordinates; CAD transforms retain their separate model-coordinate semantics. [R2, R4, R5]

BOMs come from the assembly catalog and approved sections. Parts-manual part-number and description overrides use the part definition ID, propagate across lists, and do not change CAD quantities or item numbering. This is valuable domain behavior a generic table editor must not bypass. CAD figures retain source/render revisions and are selectively recaptured. [R4, R8]

Operations and work-instruction tables/lists are generated typed blocks. Their visible cells/items can have text overrides, but this is not a general spreadsheet or table designer. Specification sheets separately support named row/value editing, additions/removals and source acceptance. [R6-R9, R12-R14]

### 2.5 Saving and history

Scene commands validate base revision, CAD source/manual-plan binding and target membership, write atomically, and persist replayable history with a cursor. Undo/redo is real for that scene, not merely a visual browser undo. A new command removes the redo branch; history is bounded. [R3]

Specification values live in another store. Its mutation path updates that store and recompiles the sheet; no corresponding persistent slot undo/redo was found in `SlotStore` or `_specification_sheet_slot_change`. Do not advertise scene undo as covering every specification value or every generated workflow. [R6, R16]

### 2.6 Sage integration today

Sage can inspect the active documentation context/type/BOM, request generation/export workflows, supply user-stated inspection values, use specification evidence/acceptance tools, read editable page text, edit selected text fields, and move parts between approved manual sections. Some figure-generation workflows are queued and executed by the workspace after the reply; the queue receipt is not proof that export completed. [R8]

The text reader exposes IDs for headings, paragraphs, captions, cells and list items. The editor accepts up to 12 replacements per call, with individual text limits. It is not a general editor command API for arbitrary formatting, insertion, table surgery, grouping or page management. Existing lower-level scene operations could underpin those tools, but frontend availability is not proof that Sage already has a tool for them. [R2, R9]

### 2.7 Preservation and fidelity findings to resolve first

These are source-supported risks; no reproduction against a user's saved document was attempted.

| Priority | Finding | Consequence and required action |
|---|---|---|
| High | Agent text edits do not carry the revision or original-value hash observed by the agent. The host reads the latest scene immediately before writing. [R9-R10] | Backend concurrency checks protect individual writes but not the interval between the agent's earlier read and edit. Add read-bound preconditions so a manual change is not silently overwritten. |
| High | The 12-edit endpoint commits edits one at a time and explicitly reports how many succeeded before failure. [R10] | A requested multi-field change can be partially applied and require multiple undos. Add atomic document batches and a single change receipt/history group. |
| High | `rebaseline` intentionally creates a new scene, retaining theme/masters but clearing page overrides/history. It is used when a stale-binding rebaseline is requested. [R3; server builders around 16066, 16306, 16488] | Regeneration needs explicit conflict handling and preserved manual overrides, not an implicit reset. The specialized `rebind_manual_plan` path already demonstrates a narrower preservation approach. |
| High | Table/list text targets encode row/item indexes, unlike definition-keyed parts-list fields. [R9] | Reordering or inserting generated rows can redirect an old override. Introduce persistent row/column/list-item IDs and migrate with verified mappings. |
| Medium | Sage read results truncate and normalize text, while edits replace entire target strings. [R9] | A shortened excerpt is not a lossless editing source. Provide full targeted reads and hashes; label excerpts explicitly. |
| Medium | Specification-slot history and scene history are separate. [R6, R16] | Define consistent user-visible undo boundaries before introducing another editor's local history. |
| Medium | Browser styles and PDF rendering are different implementations. The parts PDF maps browser fonts to a small PDF font set; underline/image rotation/cover behavior is simplified. [R11] | Establish a supported-format contract and golden export tests. Do not promise exact visual fidelity from current controls alone. |
| Medium | Parts PDF explicitly renders `documentationObjects`; the inspected operations/specification exporters use different block/slot paths, without that same generic object pass. [R11-R13] | Test every added-object type in every document/export combination. Do not claim all UI additions already export everywhere. |
| Release gate | `requirements.txt` records PyMuPDF's AGPL/commercial-license disposition as blocked. [R17] | Verify the actual legal disposition before commercial release. A comment is evidence of an unresolved recorded gate, not proof the company lacks a license. |

PyMuPDF's own documentation confirms AGPL/commercial dual licensing. This assessment is not legal advice; obtain the license determination for the shipped dependency set. [Official licensing](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright).

## 3. Capability Comparison

The [companion matrix](documentation-editor-capability-matrix.md) covers every requested A-G area, distinguishing implemented capabilities from limited/generated-only functionality and missing editing controls. It also distinguishes Word's flowing documents from PowerPoint's positioned objects.

The largest gaps are inline formatting, general table authoring, configurable page flow, reliable refresh/merge, cross-format fidelity, and unified agent transactions. The largest existing advantages are engineering provenance, typed CAD relationships, selective figure refresh, editable placeholders and deterministic BOM generation. Generic editors do not supply those advantages automatically.

## 4. Technology Evaluation

### 4.1 Existing editor: extend, do not rebuild rich text

**Type:** custom engineering publication editor.

**Fit:** highest preservation and UI compatibility. Existing scene operations are suitable for incremental object/layout improvements and an editor-independent document service. They are not a mature text engine. Building IME, clipboard normalization, nested lists, range formatting, table selection and undo semantics directly on `contenteditable` would duplicate mature library work.

**Use it for:** CAD semantics, document generation, object placement, validation, authorization, persistence and render coordination. Add a rich-text adapter at field/block boundaries rather than replacing the entire workspace. No new infrastructure is necessary for this approach. Maintaining the present plain-string editor alone is reasonable only for a deliberately narrow forms product.

### 4.2 Tiptap / ProseMirror

**Type:** headless rich-text framework over a schema/transaction editor engine. Tables include row/column operations, merge/split and optional resizing; custom nodes and commands support application-defined elements. [Table extension](https://tiptap.dev/docs/editor/extensions/nodes/table), [commands](https://tiptap.dev/docs/editor/api/commands), [ProseMirror project](https://github.com/ProseMirror/prosemirror-state).

**Fit:** strongest default for this vanilla-JS application. InspectorPro's ribbon can invoke commands without adopting a vendor toolbar. Persist a validated, versioned rich-text payload within InspectorPro blocks. Use custom nodes for immutable CAD references only where necessary; keep BOM calculations outside the editor. Migration of plain text to a paragraph is simple, but multiline whitespace, existing styles, selection, history and export conversion require tests.

**Licensing/limits:** MIT core is distinct from paid offerings. Pages is a paid, beta pagination product; conversion is also a separately entitled service/product. Neither is required for bounded text blocks. Open-source Tiptap by itself is not Word, does not give verified DOCX/PPTX round-tripping, and does not solve engineering validation. Evaluate exact extension packages/licenses before pinning. [Pages](https://tiptap.dev/docs/pages/getting-started/overview), [conversion](https://tiptap.dev/docs/conversion/getting-started/overview).

**Effort/risk:** medium for a bounded rich-text integration, high for replacing all page composition. Prototype export consistency and mounted-editor count before adoption. Prefer existing extensions over new bespoke ones.

### 4.3 Lexical

**Type:** extensible text editor framework with immutable editor state, commands, transforms and custom nodes; core is MIT. Editor state can serialize to JSON, but runtime node keys and selection are not durable document IDs. [Architecture/state](https://lexicaljs.org/docs/concepts/editor-state), [project/license](https://github.com/meta/lexical).

**Fit:** viable second choice. Custom nodes could represent CAD references and structured engineering fields. The core is not tied to React, although many ready-made integrations/examples use it. InspectorPro would still build its schema bridges, toolbar integration, tables, history boundary and exports. Its lower-level flexibility is not a reason to discard working page composition.

**Effort/risk:** medium-high. No automatic paginated engineering-document or Office export solution. Compare with Tiptap only through the same bounded prototype; do not select it based on generic performance claims. Persistent IDs must be explicit custom data, not node keys.

### 4.4 Slate

**Type:** flexible JSON-tree rich-text framework with normalization, transforms and custom elements. MIT; its repository still identifies the project as beta. [Repository](https://github.com/ianstormtaylor/slate), [normalization](https://docs.slatejs.org/concepts/11-normalizing).

**Fit:** possible for custom engineering blocks, but more assembly of editing behavior and a React-oriented UI integration than InspectorPro needs. Complex tables, clipboard behavior and schema normalization would remain significant product work. Plate reduces some of that work but adds its own integration choices.

**Effort/risk:** high relative to the immediate need. Not a pagination, Office import/export, or CAD engine. Do not choose solely because its schema is flexible; InspectorPro already has a useful domain schema.

### 4.5 CKEditor 5

**Type:** mature rich-text editor/framework with its own editing model, commands and conversion layers. Broad text, image and table features; custom widgets are possible. Its decoupled UI can be integrated into a host application. Pagination is a dedicated feature, not evidence of arbitrary Office fidelity. [Editing engine](https://ckeditor.com/docs/ckeditor5/latest/framework/architecture/editing-engine.html), [pagination](https://ckeditor.com/docs/ckeditor5/latest/features/pagination/pagination.html).

**Licensing:** GPL 2+ or commercial; premium functionality and conversion entitlements require separate attention. A free CDN offering is not automatically a suitable self-hosted, closed-source Electron distribution license. [Official license](https://ckeditor.com/docs/ckeditor5/latest/getting-started/licensing/license-and-legal.html), [activation/deployment](https://ckeditor.com/docs/ckeditor5/latest/getting-started/licensing/license-key-and-activation.html).

**Fit:** credible commercial alternative if support, advanced editing, track changes and conversion justify vendor cost. CAD nodes still need InspectorPro adapters; replacing the model does not eliminate provenance/merge work. Obtain written desktop/offline/SaaS/export terms and test whether conversions keep data on the customer's machine or send it to a service.

**Effort/risk:** medium-high; less commodity editing work, more licensing and model-conversion dependency. Not the default while a smaller permissive integration meets the target.

### 4.6 ONLYOFFICE Docs

**Type:** complete office editor suite, including document and presentation editing, normally embedded through the Docs API. Its document server performs editing/conversion; the host supplies document storage and save callbacks. This is not simply an npm editing engine that replaces a `contenteditable` node. [Architecture](https://api.onlyoffice.com/docs/docs-api/get-started/how-it-works).

**Agent integration:** plugins, Office APIs and Document Builder can create or manipulate document content. External custom-UI control through the Automation API is specifically a Docs Developer premium feature at extra cost. CAD images/tables could be inserted, but persistent semantic identity across saves must be proven using supported content controls/bookmarks/metadata rather than paragraph indexes. [Automation API](https://api.onlyoffice.com/docs/docs-api/usage-api/automation-api), [plugins](https://api.onlyoffice.com/docs/plugins/get-started/overview).

**Licensing/deployment:** Community is AGPLv3; Enterprise and Developer are commercial, with Developer intended for embedding under an application's brand. Commercial use is not inherently forbidden by AGPL, but proprietary distribution/SaaS obligations need review; do not assume an iframe removes them. [Edition comparison](https://www.onlyoffice.com/compare-editions).

**Fit:** best candidate if editable DOCX/PPTX import and Office-class authoring become contractual requirements. InspectorPro can retain primary storage, but the server receives and processes working document copies. Offline desktop use would require a supported local service deployment and lifecycle strategy; cloud hosting changes the IP/data boundary. Integration must handle credentials/JWT, document keys, callbacks, save versions, failure recovery and patching.

**Effort/risk:** high. Its own toolbar/canvas can live within InspectorPro, but exact ribbon integration and removal/replacement of internal controls depend on supported APIs and license. Full editing engine extraction or silently replacing its UI is not a validated plan. Benchmark startup/RAM, 100-page documents, large figures, round-trip metadata and disconnect recovery before choosing it.

### 4.7 Word and PowerPoint MCP research

**An MCP server exposes operations. It is not, by itself, a document editing or rendering engine.** Two distinct implementations matter:

| Implementation | Operations and schemas inspected | Engine / Office dependency | Assessment |
|---|---|---|---|
| GongRzhe Office-Word-MCP-Server | Typed FastMCP functions for document reads/creation, paragraphs, search, styles, tables, images and formatting. Inputs include filenames, paragraph indexes and character offsets. Some results are strings, including JSON encoded inside strings. | Primarily `python-docx` file manipulation; basic operations do not require Word. Optional converters need separate review. | MIT source, but repository archived March 3, 2026. Useful catalog reference, not a production foundation without ownership. |
| GongRzhe Office-PowerPoint-MCP-Server | Presentation IDs; slide/layout indexes; content, images, tables, charts/connectors. `add_slide` returns slide index/layout or an error object; read tools return dictionaries. | `python-pptx`, not PowerPoint's running editing engine. | MIT source, also archived March 3, 2026. Native file generation is not an embedded interactive editor. |
| kennypeh85 Word Live MCP | Read selection/paragraph/table, replace text, styles, highlighting, insert table, update TOC, export PDF. Optional document name; 1-based indexes. | Windows `win32com` talking to installed/running Word. | MIT community implementation; automation is delegated to Office. Cannot make InspectorPro independent of Office. |
| kennypeh85 PowerPoint Live MCP | Read slides/shapes/selection, add text box, replace text, format, duplicate/delete slide, capture previews. | Windows COM and installed PowerPoint. | Optional external-Office connector, not a native editor solution. Review exact selected code/license before reuse. |

Sources: [Word repository](https://github.com/GongRzhe/Office-Word-MCP-Server), [Word tool registration](https://raw.githubusercontent.com/GongRzhe/Office-Word-MCP-Server/main/word_document_server/main.py), [Word implementation](https://raw.githubusercontent.com/GongRzhe/Office-Word-MCP-Server/main/word_document_server/tools/document_tools.py), [PowerPoint repository](https://github.com/GongRzhe/Office-PowerPoint-MCP-Server), [PowerPoint content tools](https://raw.githubusercontent.com/GongRzhe/Office-PowerPoint-MCP-Server/main/tools/content_tools.py), [Word Live](https://github.com/kennypeh85/word-mcp), [PowerPoint Live](https://github.com/kennypeh85/powerpoint-mcp).

One concrete caution: the Word MCP's `format_text` implementation clears existing paragraph runs and reconstructs before/selected/after runs. That is not a safe general rich-format-preserving edit. Borrowing a tool name does not mean borrowing correct preservation semantics. [Formatting source](https://raw.githubusercontent.com/GongRzhe/Office-Word-MCP-Server/main/word_document_server/tools/format_tools.py).

Useful ideas to borrow: separate inspect/edit/export tools, typed targets, explicit table operations, style commands and read-only annotations. Do **not** borrow unrestricted filename access, implicit active-document targeting, positional IDs, unversioned writes or arbitrary script execution. InspectorPro's document-scoped service should remain the authority.

Representative contracts inspected, summarized rather than adopted:

| Tool | Input shape | Result shape | InspectorPro adaptation |
|---|---|---|---|
| Word MCP `format_text` | File path, integer paragraph/start/end indexes, optional font/style attributes | Human-readable success/error string | Document/element ID, observed revision/hash, structured change receipt; preserve existing runs |
| Word MCP `get_document_info` | File path | Serialized document information or error text | Authorized document ID, typed data, no arbitrary filesystem discovery |
| PowerPoint MCP `add_slide` | Optional presentation ID, integer layout index, title/background options | Dictionary with new slide index/layout or error | Stable slide ID, explicit document revision, atomic operation |
| PowerPoint MCP `get_slide_info` | Integer slide index and optional presentation ID | Slide-information dictionary or error | Persistent element IDs and capability metadata |

FastMCP derives input schemas from typed function signatures in these implementations. That does not guarantee a consistent output schema, transaction boundary or preservation policy. No community server was installed or executed for this audit. [Word registration](https://raw.githubusercontent.com/GongRzhe/Office-Word-MCP-Server/main/word_document_server/main.py), [PowerPoint implementation](https://raw.githubusercontent.com/GongRzhe/Office-PowerPoint-MCP-Server/main/tools/content_tools.py).

#### Microsoft APIs are different options

| Technology | What it supplies | Boundary for InspectorPro |
|---|---|---|
| Office.js | JavaScript APIs inside Office add-in hosts; Word ranges/content controls and PowerPoint slides/shapes, subject to host requirement sets | InspectorPro integration *into Office*, not Office embedded into InspectorPro. Useful optional customer connector. [Overview](https://learn.microsoft.com/en-us/office/dev/add-ins/overview/office-add-ins), [PowerPoint APIs](https://learn.microsoft.com/en-us/office/dev/add-ins/powerpoint/powerpoint-add-ins) |
| Open XML SDK | MIT .NET APIs for DOCX/PPTX package structures | No interactive editor or Word pagination engine; adds .NET integration if selected. Existing Python exports reduce the immediate need. [SDK](https://github.com/dotnet/Open-XML-SDK), [Microsoft overview](https://learn.microsoft.com/en-us/office/open-xml/about-the-open-xml-sdk) |
| Microsoft Graph | Microsoft 365 storage/file operations and supported format conversion with permissions and service limits | The DriveItem API inspected is not a general native Word range-editing engine. Requires Microsoft service access; do not assume CAD stays local. Other Microsoft agent products would need their own assessment. [File conversion API](https://learn.microsoft.com/en-us/graph/api/driveitem-get-content-format?view=graph-rest-1.0) |
| Windows Office COM | Live application object model and native Office rendering/export | Requires licensed installed Office and process/session handling. Not the default for a cross-deployment embedded editor. |

### 4.8 Other requested technologies

These are not interchangeable. Licensing summaries apply to the named core project, not every plugin, font, template or hosted service.

| Technology | Category and license | Useful capability | Fit, limits and adoption effort |
|---|---|---|---|
| [Quill](https://quilljs.com/docs/api), [Delta](https://quilljs.com/docs/delta), [license](https://github.com/slab/quill/blob/main/LICENSE) | Rich-text editor; BSD-3-Clause | Formatting/selection APIs, Delta changes, custom embeds | Low-medium for simple fields; complex engineering tables, page flow and exports still require additional work. Less compelling than Tiptap for the target schema. |
| [BlockNote](https://www.blocknotejs.org/docs), [licensing](https://www.blocknotejs.org/pricing) | Block editor built on Tiptap/ProseMirror; MPL2 core; XL GPL3/commercial | Ready block UI, menus and drag/drop | Medium-high. React-first integration and its block UX overlap existing UI. XL exporters/multi-column features are not freely usable in a closed-source app without meeting license terms. Useful if a Notion-like authoring mode is desired. |
| [Milkdown](https://github.com/Milkdown/milkdown) | ProseMirror/remark Markdown editor framework; MIT | Plugin-driven Markdown authoring | Medium. Good for narrative notes; Markdown-first structure is a poor canonical format for engineering page frames, CAD links and advanced tables. |
| [Plate](https://platejs.org/docs), [core license](https://raw.githubusercontent.com/udecode/plate/main/LICENSE), [Pro offering](https://pro.platejs.org/pricing) | Slate-based React toolkit/components; MIT default with package exceptions; commercial Pro offering | Rich-text/table plugins and ready UI components | Medium-high. Reduces Slate work but adds React/UI integration. Its development-oriented MCP does not automatically supply Sage runtime editing. Check chosen packages separately. |
| [Editor.js](https://github.com/codex-team/editor.js) | Block editor with JSON output; Apache2 | Plugin blocks, easy structured prose | Medium. Good notes/manual sections, but not a paginated engineering publication engine. Table sophistication depends on plugins. |
| [Paged.js](https://github.com/pagedjs/pagedjs) | CSS paged-media layout/print library; MIT | Browser pagination, running page elements, print preparation | Medium-high as an optional flowing-document output layer. Not caret/selection editing, DOCX export or a complete editor. Avoid continuously repaginating every keystroke without measurement. |
| [Fabric.js](https://www.fabricjs.com), [license](https://github.com/fabricjs/fabric.js/blob/master/LICENSE) | Object-based 2D canvas engine; MIT | Transforms, interactive text, grouping, SVG/JSON, image manipulation | Medium-high. Candidate for a future presentation/diagram canvas, not needed to replace working DOM/SVG page objects now. Semantic export and accessible editing remain application work. |
| [Konva](https://konvajs.org/docs/), [text-editing boundary](https://konvajs.org/docs/sandbox/Editable_Text.html), [license](https://github.com/konvajs/konva/blob/master/LICENSE) | 2D scene/canvas engine; MIT | Layers, groups, dragging, transforms and hit testing | Medium-high. Text editing generally uses a DOM overlay. Does not supply Word layout, tables or Office export. Choose Fabric *or* Konva only after a canvas need is demonstrated. |
| [PptxGenJS](https://github.com/gitbrent/PptxGenJS) | PPTX generator; MIT | Editable slides, text, shapes, tables, pictures and masters | Medium for bounded presentation export; not an editor, PPTX renderer or arbitrary PPTX importer. CAD becomes an image plus reference metadata, not an editable CAD assembly. |
| [docx.js](https://github.com/dolanmiu/docx) | JS/TS DOCX generation/modification library; MIT | Paragraphs, runs, sections, tables, images | Medium. Not a visual editor/rendering engine. InspectorPro already uses python-docx; do not maintain two exporters for the same schema without a concrete benefit. |
| [LibreOffice headless](https://help.libreoffice.org/latest/en-GB/text/shared/guide/start_parameters.html?DbPAR=BASIC&System=WIN), [licenses](https://www.libreoffice.org/licenses/) | Full installed office engine usable for headless conversion/UNO automation; MPL2 and bundled-component terms | Conversion/rendering of Office/ODF files without Microsoft Office | Medium-high operations cost: executable deployment, private worker profiles, timeouts, fonts, crash containment and conversion fidelity tests. Not a lightweight web editor. |
| [Apache POI](https://poi.apache.org/) | Java Office-file libraries, including XWPF/XSLF; Apache2 | File-level DOCX/PPTX manipulation | High incremental cost for this Python/JS app, little immediate advantage. Not a Word layout engine or interactive editor. |
| [python-docx](https://python-docx.readthedocs.io/en/latest/) | Existing Python DOCX generator/editor | Reuse document/table/run generation | Best initial DOCX path. Native runs/tables are editable, but generation alone does not guarantee matching Word pagination or round-trip preservation. |

Additional complete-office products such as Collabora Online belong in the same architectural category as ONLYOFFICE, not in the lightweight rich-text category. They would require a separate service/licensing/integration proof; no unverified claim of a drop-in engine is used in this recommendation.

## 5. Compatibility and Strategy Assessment

### 5.1 Practical shortlist

| Criterion | Keep current only | Tiptap hybrid | Lexical hybrid | CKEditor hybrid | ONLYOFFICE |
|---|---|---|---|---|---|
| Current JS/Python fit | Native | Good; vanilla JS adapter | Good core; more integration | Good JS; own model | Separate editor/server integration |
| Preserve existing code | Highest | High | High | Medium-high | Domain services retained; UI/export replacement risk |
| Out-of-box editing | Limited | Strong rich text/tables | Strong primitives, more UI work | Broad editor features | Broad office authoring |
| Sage commands | Existing service extensions | Map typed edits to schema | Map typed edits to commands | Map via model API | Plugins/automation adapter and callback coordination |
| CAD/BOM/evidence | Existing | Retained outside text layer | Retained outside text layer | Custom widgets and external semantics | Explicit content-control/metadata mapping required |
| Ribbon/sidebar match | Exact | Headless, strong fit | Host-controlled, strong fit | Customizable/decoupled | Embedded UI; exact match constrained |
| Large documents | Current behavior; benchmark needed | Lazy mount text editors; benchmark | Benchmark equivalent workload | Benchmark custom widgets/conversion | Server resources plus client cost; benchmark |
| New runtime services | None | None for OSS core | None for core | None for core; chosen premium services may add | Document server required |
| Closed-source distribution | Current dependency review | MIT core; review extensions | MIT core | Commercial agreement likely needed | Developer terms or AGPL compliance review |
| PDF/DOCX/PPTX | Existing subset/no PPTX | Existing exports extended; PPTX separate | Same export work | Conversion entitlements; PPTX separate | Native office formats; still test round trip |
| Data locality | Existing boundaries | Core can stay local | Core can stay local | Depends on selected services | Server sees working copies |
| Maintenance | Own text-engine burden grows | Own domain adapters, upstream editor | More custom editor integration | Vendor dependency/support | Service patching, deployment, adapters, contracts |

Maturity is not inferred from GitHub stars. Tiptap/ProseMirror, Lexical, CKEditor and the office suites have substantial documented APIs; Slate's beta status and the archived MCP repositories are explicit risks. Pin exact releases, review recent security/release history and supported Electron versions at the implementation gate. No comparative performance measurement was performed here.

### 5.2 Four architectural strategies

Estimates below are **engineer-weeks**, assuming an experienced JS/TypeScript engineer with Python support, a bounded feature set, representative documents and review access. They include integration/testing, not procurement delays. They are alternative planning ranges, not additive and not promises of Office parity.

| Strategy | Initial useful release | Maintenance / complexity | Decision |
|---|---|---|---|
| A. Enhance current editor only | 4-8 weeks for safety, object controls and modest formatting; full rich text substantially beyond that | Lowest migration initially, highest risk of owning commodity editing internals | Keep for domain/layout, reject as the sole rich-text strategy |
| B. Replace editing layer broadly with a framework | 10-18 weeks | Schema migration, history/export adapters and broad regression work; costs vary by license | Possible later if flowing documents dominate; unnecessary initial displacement |
| C. Embed complete office editor | 12-24 weeks for a production integration, not a demo iframe | Highest service/licensing/security/save-sync complexity; strongest Office authoring coverage | Reserve for proven Office round-trip requirements |
| D. Hybrid bounded rich text + retained CAD publisher | 8-14 weeks for the prioritized release below | Moderate adapters; preserves strongest domain components; local OSS core possible | Recommended |

The largest uncertainty is export fidelity and existing regeneration behavior, not adding toolbar buttons. A 1-2 week proof should revise these estimates before committing to a schedule.

## 6. Recommended Sage Editing Interface

### 6.1 Authority and adapters

```text
InspectorPro ribbon / properties / rich-text editor / Sage tools
                           |
             Document command service (authoritative)
       permissions + schema + revision + identity + provenance
                           |
       semantic document + composition + managed assets + history
                    /                        \
         browser editor adapters       PDF/DOCX/PPTX adapters
```

Use the same backend service for manual and agent changes. MCP is an optional transport over that service, not a second implementation and not a reason to add another agent loop. Do not let Sage execute arbitrary JavaScript in Tiptap, Office, or the application process.

Retain assembly and document-type bindings, but add explicit persistent `documentId` and document revision to the tool contract. Switching the active UI document must not retarget an in-flight request. Resolve the authorized document on the backend, not by whatever tab happens to be selected when a queued action runs.

### 6.2 Document model evolution

Extend the existing schema incrementally, with explicit migration/versioning:

- Keep semantic CAD sources, approved plans and calculated BOM values separate from presentation content.
- Give every section, block, custom object, table row/column/cell and list item a stable ID. Page number and array index are presentation, not identity.
- Add a versioned `richText` payload to eligible text blocks. A restricted ProseMirror/Tiptap JSON schema can be the first supported encoding; adapters expose semantic commands rather than raw ProseMirror steps to Sage.
- Keep simple text slots available. A mass, tolerance, certification value or source citation should not become unrestricted prose merely because a rich editor exists.
- Record `sourceRef`, source revision, last generated baseline, manual override state, evidence and locks at the smallest meaningful field/block boundary.
- Keep frames/page masters outside rich-text content. Initially preserve fixed-page templates; introduce flow sections later as an explicit layout mode.
- Persist media as managed asset IDs, not arbitrary HTML, local paths or network URLs. Validate paste/uploads and sanitize permitted content.
- Store the document schema as authoritative; neither editor DOM nor transient editor selection is authoritative. Avoid dual canonical copies that drift.

This is an adapter contract, not a proposal to invent a new text engine. Reuse the selected editor's text schema, normalization and transactions internally.

### 6.3 Tool families

Names are proposed, not implemented. Expose only operations that the selected document type actually supports, through capability discovery.

| Family | Proposed operations | Target and result |
|---|---|---|
| Discover/read | `inspect_document`, `read_elements`, `find_document_text` | Document ID, revision, IDs, kinds, capabilities; full selected text and content hashes; excerpts clearly labeled |
| Lifecycle | `create_document`, `clone_document`, `export_document` | Approved template/source references; job IDs for async work; artifact and validation receipt on completion |
| Text | `insert_text`, `replace_text`, `format_text`, `apply_paragraph_style`, `insert_heading` | Block ID plus validated range/expected text/hash; permitted marks/styles only |
| Tables | `create_table`, `modify_table` | Row/column/cell IDs; explicit add/remove/merge/split/resize operations; reject invalid spans |
| Engineering | `insert_cad_view`, `refresh_cad_view`, `insert_bom`, `refresh_bom`, `add_callout` | Authorized assembly/section/source revision and occurrence/definition IDs; no invented quantities |
| Graphics | `insert_image`, `resize_image`, `move_element`, `arrange_elements`, `group_elements` | Managed asset ID, element IDs, page-relative frames, supported transforms; grouping only once implemented |
| Structure/layout | `create_page`, `set_page_layout`, `move_section`, `update_document_section` | Explicit page/section IDs and layout mode; refuse unsupported geometry/overflow |
| History/review | `apply_document_edits`, `inspect_change`, `undo_document_change`, `approve_document_change` | Atomic batch, actor, expected revision, audit receipt; consequential actions require appropriate review |

Do not expose dozens of overlapping low-level mouse actions. A small set of typed batch operations plus read/validate/export tools can implement this catalog without giving the agent arbitrary process access.

### 6.4 Transaction contract

Illustrative request, not a committed API:

```json
{
  "documentId": "doc-example",
  "expectedRevision": "rev-42",
  "requestId": "client-generated-unique-id",
  "operations": [
    {
      "operation": "replace_text",
      "elementId": "block-maintenance-note",
      "expectedContentHash": "sha256-of-observed-content",
      "text": "User-requested replacement text."
    }
  ]
}
```

Backend behavior:

1. Authenticate principal, document binding and permitted operations. Actor identity comes from the session, not a model-supplied string.
2. Resolve IDs; validate document/source revisions and observed-content preconditions.
3. Apply the whole batch in a transaction to a candidate state; validate schema, links, typed fields and layout constraints.
4. Commit once or change nothing. Store one undo group, before/after revisions and a durable request receipt.
5. On retry, return the prior receipt for the same request and payload; reject reuse with a different payload.
6. Return changed IDs, new revision, validation findings, undoability and any asynchronous job IDs. Return structured failures such as `stale_revision`, `manual_edit_conflict`, `read_only_derived_field`, `unsupported_export_feature` or `layout_overflow`.

Text ranges need a documented indexing convention. Do not mix Python code-point indexes with browser UTF-16 offsets. Prefer exact-text plus context/hash targeting, or validated node/range IDs; reject ambiguous matches. Test emoji, combining characters, symbols and IME composition.

### 6.5 Preserving manual edits

Use a three-way refresh policy: prior generated baseline, current edited document, newly generated content.

| Situation | Refresh behavior |
|---|---|
| Generated value changed; user did not edit it | Update only that value and dependent figures/references |
| User changed text; generated source unchanged | Preserve user text exactly |
| Both changed the same field | Keep current text, create a conflict with old/new evidence, request a decision |
| Generated row reordered | Follow stable row/definition identity, not index |
| CAD part deleted or identity changed | Mark the link stale/orphaned; do not silently delete manual commentary or guess a new match |
| User inserted unrelated text/image/table | Leave it alone |
| User explicitly requests a complete rebuild/reset | Show affected manual content, retain recoverable prior version, require the appropriate approval |

For a BOM refresh, quantities remain deterministic CAD data. Manual descriptions and narrative notes stay separate. Existing definition-keyed overrides are the starting point, not a feature to discard.

No CRDT or real-time collaboration server is required for the initial single-user desktop case. Optimistic concurrency plus atomic transactions is sufficient. Add collaborative merging only when multi-user editing is a validated requirement.

### 6.6 Undo, approval and safety

- Use editor-local undo while actively typing; commit a coherent document transaction at defined boundaries. The document undo stack must include both manual and agent operations without silently skipping specification slots.
- Do not implement agent undo by blindly moving a shared cursor past later human edits. Revert a named transaction only when its affected fields still match, otherwise report a conflict.
- Routine authorized formatting/text edits may execute directly with undo. Do not restore mandatory preview for every small edit.
- Destructive regeneration, changing verified engineering data, replacing accepted evidence, release/signature actions and overwriting external files require explicit authority and appropriate review.
- A screenshot is presentation evidence, not proof of correct quantities, tolerances or citations. Validate those deterministically.
- The rich-text core can remain local, but any content sent to Sage's model follows the existing AI data boundary. Local editing does not imply local AI inference. Hosted conversion/research requires separate disclosure and permission.

## 7. Implementation Roadmap

No phase below has been implemented by this assessment. Use an isolated branch/test store; do not port to the desktop until the acceptance gates pass and the user approves deployment.

### Phase 0: Baseline and release boundaries (about 1 week)

Inventory representative parts manuals, operations manuals, work instructions and specification sheets, including manual edits and missing evidence. Capture existing screenshots, exported files and semantic JSON. Record the current export/undo matrix instead of assuming parity.

Resolve the recorded PyMuPDF licensing gate; inventory editor/export/font licenses and offline requirements. Establish the bounded first-release feature list: inline typography, lists/headings, non-BOM tables, safe refresh, consistent PDF/DOCX and basic object controls.

**Gate:** existing documents reopen unchanged; source data untouched; current export differences documented; dependency/license decisions recorded.

### Phase 1: Safe document command contract (about 2-3 weeks)

Add full targeted reads, read-bound revisions/hashes, stable table/list IDs, atomic batches, idempotent receipts and change-level undo. Bridge specification-slot transactions rather than pretending scene history covers them. Replace destructive stale refresh with explicit preservation/conflicts; retain the narrow parts-section rebind behavior.

**Gate:** agent-read/manual-edit/agent-write race refuses stale change; invalid second edit commits nothing; duplicate retry does not apply twice; BOM reorder preserves descriptions; source changes do not erase unrelated notes; undo does not erase intervening human work.

### Phase 2: One-region rich-text proof (about 1-2 weeks)

Prototype Tiptap OSS in one manually authored text block, behind a development flag. Preserve selection when the ribbon is clicked. Support a small schema: paragraphs, bold/italic/underline, basic color, links, headings and lists. Round-trip old plain strings without reformatting unaffected documents. Test editor focus against page drag/resize and CAD keyboard shortcuts.

Export the same block to existing PDF and DOCX paths. Pin packages and create a local bundle; do not depend on runtime CDN access or vendor AI services.

**Gate:** clipboard, Unicode/IME, keyboard selection, local/document undo, reload, Sage edit and export all agree. No lost whitespace or manual content. If export or integration fails, retain the existing editor and compare a CKEditor or Lexical proof before expanding.

### Phase 3: Professional text and table editing (about 2-3 weeks)

Extend to approved narrative blocks with fonts/sizes, highlight, strike, superscript/subscript, alignment, spacing, headings, nested lists and find/replace. Use supported extensions where available. Add general user tables with row/column editing, merge/split, widths and styles; keep CAD BOMs a constrained semantic table type. Add reusable named styles and a local engineering-symbol picker where useful.

**Gate:** matrix A/C target rows pass; formulas/measurements remain typed and validated; table edits preserve row IDs, merge constraints and exports. Engineering equations can be deferred unless real customer documents require them.

### Phase 4: Composition and export consistency (about 2-3 weeks)

Improve image aspect locks/crop, selection handles, alignment, z-order and supported page settings without changing the whole page renderer. Define A4/Letter and orientation/margin behavior per document type. Handle long text with explicit overflow or a supported flow mode, not silent clipping or unlimited shrinking.

Use shared style tokens and approved fonts across browser/PDF/DOCX. Map rich-text runs and tables to native DOCX elements. Keep CAD views as revision-linked images with captions. Test every added object/export combination; do not silently drop unsupported objects.

**Gate:** published output matches the declared feature subset; correct numbering/references; readable tables and labels; no clipped text; missing/stale CAD captures block the relevant export. Exact Word pagination is not promised without testing Word itself.

### Phase 5: Scale, recovery and release (about 1-2 weeks)

Benchmark small, 50-page and 100-page documents with realistic CAD figures and BOM sizes. Lazy-mount editors only where needed; dispose renderers/listeners correctly. Test save failure, interrupted generation, restart recovery, schema upgrade/rollback and restricted permissions. Test at normal/high DPI with keyboard-only access.

**Gate:** define and meet measured latency/memory budgets on the user's machine and a clean Windows installation; no data loss; migration backup/rollback verified; automated domain, UI and export regression suites pass. Report live Sage verification separately from mocks.

Phases overlap, so the initial planning range is 8-14 engineer-weeks, not the sum of every maximum. Re-estimate after Phase 2.

### Later options, only when justified

- Flowing long manuals: compare Paged.js print composition, Tiptap Pages and CKEditor pagination using the same difficult tables/figures. Do not assume print pagination solves live caret pagination.
- Presentation documents: add a distinct slide layout mode and PptxGenJS (or one approved backend equivalent) for editable PPTX export. Prototype Fabric.js only if current object controls become a measurable bottleneck.
- Office-file round trip: run an ONLYOFFICE Developer proof with real customer files and preserved CAD identity. Obtain OEM/SaaS/offline and Automation API terms first.
- Comments/review/collaboration: add if customer workflow requires them; do not introduce a collaboration backend preemptively.

## 8. Prototype and Procurement Questions

| Uncertainty | Exact verification needed |
|---|---|
| Rich-text engine fit | Same one-block clipboard/IME/history/export benchmark in InspectorPro; no standalone demo as proof |
| Manual-edit preservation | CAD revision, row insertion/removal, duplicate descriptions, renamed sections and changed definition IDs against saved real copies |
| Export fidelity | Browser/PDF/DOCX comparisons for all supported marks, fonts, tables, crops, rotations and special symbols; open DOCX in Word and LibreOffice |
| Large-document performance | Measure load, typing, pagination, memory and export with realistic images; no library marketing benchmarks substituted |
| Existing added objects | Verify PDF/DOCX outputs per document type; inspect all export paths before claiming support |
| Tiptap paid features | Exact pinned package license and offline rights; Pages/conversion beta behavior and data destination if chosen |
| CKEditor commercial fit | Written self-hosted Electron/SaaS, premium conversion, offline activation and document-data terms |
| ONLYOFFICE fit | Supported local/server deployment, save callbacks, CAD content-control identity, runtime footprint, branding/custom UI and automation license |
| Community MCP reuse | Pinned source/security review, dependency licenses, maintained ownership, restricted file access; archived source is not vendor support |
| PyMuPDF | Written resolution of the already-recorded AGPL/commercial gate for actual distribution |

## 9. Final Recommendation

Keep InspectorPro's engineering document system. Improve its transaction and preservation guarantees first, then embed **Tiptap OSS for rich text** and retain the current page/CAD composition controls. Extend existing PDF/DOCX generation to a deliberately supported rich-text subset; do not add redundant exporters without need.

This delivers the professional editing engineers are asking for while preserving the product's differentiator: editable, traceable documentation linked to real CAD data. It avoids both extremes: rebuilding Word on raw `contenteditable`, and replacing a functioning CAD publisher with a heavy office server before Office compatibility is actually required.

The decision to approve next is the bounded Phase 0-2 proof, not an irreversible editor migration.
