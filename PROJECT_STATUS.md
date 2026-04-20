# AI Engineering Drawing Inspector - Project Status

**Last Updated:** March 5, 2026

---

## Project Goal

Build an AI-powered platform that **unifies Engineering, Purchasing, and Manufacturing** around a single shared context — from 3D CAD model to shop floor. The system verifies engineering drawings against CAD model data, analyzes deviations with full assembly awareness, and sources replacement parts with live web search.

---

## Current Status: InspectorPro v1.1 — Three-Agent Platform (Iris + Sage + Scout)

### Latest Milestone (March 5, 2026)

**Demo-Ready Platform — Three Departments, One Tool**

The platform is now demo-ready with all three agents fully operational:

- **Agent Iris** (Drawing Inspector): Inspects engineering drawings against 3D CAD data and company standards. Flags missing dimensions, GD&T errors, representation gaps. Proposes corrective actions. Uses ASME Y14.5 RAG references.
- **Agent Sage** (Deviation Analyst): Makes accept/rework/scrap verdicts on dimensional deviations with full assembly context — mates, constraints, tolerance stacks, functional narrative. Color-coded assembly views for visual reference.
- **Agent Scout** (Procurement & Vendor Search): Searches industrial suppliers live (McMaster, Misumi, MSC, Grainger, Fastenal, etc.) and custom fabrication vendors. Assembly-aware — knows specs AND how the part fits. Amazon/eBay/Walmart/AliExpress filtered from results.
- **Voice interaction**: Full speech pipeline — mic recording → OpenAI Whisper transcription → agent response. Works with all three agents.
- **Cross-agent context sharing**: Iris ↔ Sage (bidirectional), Iris/Sage → Scout (one-way). Each agent builds on what the others know.

**Data:**
- 197 inspection profiles in 400S_Sorted_Library/
- 3 assembly profiles with 46 part-to-assembly mappings
- Full assembly JSON: components, mates, mateRelationships, assemblyFeatures, partDataCache, partColorMapping, functional narrative, color-coded view exports

**Demos recorded:**
- Demo 2: Sage deviation analysis on oversize bore (posted to LinkedIn)
- Demo 3: Scout piston ring sourcing from 1020001 Piston drawing (recorded)

**LinkedIn content pipeline:**
- Carousel 1: "3 Departments. One Platform. Zero Silos." (7 slides) — `static/carousel_slide_01..07.png`
- Carousel 2: "Every CAD company is adding AI. Here's why most of it is surface-level." (7 slides) — `static/carousel2_slide_01..07.png`
- 18 total post ideas documented in POST_IDEAS.md (2 posted, 16 draft)

**Recent code changes:**
- Removed Amazon/eBay from Scout Phase 8 direct supplier search (`browser_engine.py`)
- Added junk domain filter for consumer marketplaces in `server.py` (_junk_domains: amazon.com, ebay.com, walmart.com, aliexpress.com, alibaba.com)
- Updated app description to reflect three-department platform positioning

**Files modified:**
- `ai_inspector/search/browser_engine.py` — Removed Amazon/eBay from Phase 8 fill_suppliers
- `server.py` — Added `_junk_domains` filter in `_is_junk()` function
- `POST_IDEAS.md` — Added Posts 5-8 (Scout demo, Sage demo, Carousel 1 individual slides, Carousel 2 individual slides)

### Previous Milestone (February 28, 2026)

**Cross-Agent Context Sharing Fixes**

Reliability and efficiency improvements to the agent context sharing system, validated by two Codex review rounds:

- **Race condition fix**: The cross-agent summarize call (fired on tab switch) was async and not awaited. If the user typed fast after switching, `pendingCrossContext` could still be empty, silently skipping context injection. Fix: summarize fetch stored as a promise in `crossContextReady`; both `handleAgentSend()` and `handleScoutSearchSend()` now `await crossContextReady` before dispatching. Confirmed working on 1015003 (CAM ENCLOSURE) — Iris -> Sage context passes reliably.
- **One-directional Scout context**: Scout (parts-finder) now receives cross-agent context from Iris/Sage but does NOT contribute back. Leaving Scout skips the Haiku summarize API call entirely. Scout's supplier/pricing results are excluded from the `buildCrossContext()` combination loop. Context flow: Iris <-> Sage (bidirectional), Iris/Sage -> Scout (one-way), Scout -> Iris/Sage (blocked).
- **Stale callback guard** (Codex review): Rapid A->B->C switching could let old in-flight `.then()` callbacks overwrite `pendingCrossContext` with context intended for a previous target. Fix: monotonic `crossContextSwitchId` counter — `buildCrossContext()` checks `thisSwitchId !== crossContextSwitchId` and discards stale callbacks.
- **Summarize timeout** (Codex review): `await crossContextReady` hard-blocked sends with no timeout. If `/api/agent/summarize` hung, chat was frozen indefinitely. Fix: `Promise.race([summarizeCall, timeout])` with 5-second deadline — sends unblock after 5s without context if needed.
- **Stale context leak** (Codex review): `buildCrossContext()` did not clear `pendingCrossContext` when no summaries were available (`parts.length === 0`), allowing stale context to leak into a later send. Fix: explicit `pendingCrossContext = null` in the else branch.

**Files modified:** `static/index.html` — `crossContextReady` promise, `crossContextSwitchId` counter, `await` in both send handlers, `selectAgent()` skips summarize for Scout, `buildCrossContext()` with switchId guard + null cleanup + Scout exclusion, `Promise.race` timeout.

### Previous Milestone (February 27, 2026)

**Scout Browser Overlay — ChatGPT-Style Animated UX**

Replaced the raw Playwright screenshot overlay with a polished two-mode animated browser card for the Scout (Parts Finder) agent:

- **Mode 1 — Search Results List**: Clean vertical list of search results (favicon + green monospace domain + title) with an animated green cursor that highlights each row as the agent "clicks" on it. Fades in with `searchListFadeIn` animation.
- **Mode 2 — Reading Mode**: Shows the search query as a bold title, scrolling gray blur lines simulating page content (`blurScroll` animation), and a floating cursor with speech bubble that types out AI-generated narration character-by-character (25ms/char) describing what the agent found (product name, price, specs, stock status). Uses `cursorDrift` and `cursorPulse` animations.
- **Strict alternation**: Mode 1 highlights supplier row → Mode 2 opens reading view with streaming narration → back to Mode 1 for next item → repeat until all suppliers visited.
- **Backend**: `_visit_product()` in `browser_engine.py` converted from collect-and-return to **async generator** — events stream immediately via SSE so frontend receives `reading` instantly, then `reading_content` after parsing, with a 5-second hold after yielding to keep Mode 2 visible.
- **Navigate events**: Carry `"highlight": True` flag to distinguish supplier-list clicks (trigger Mode 1 highlighting) from internal navigation (URL bar update only).
- **9-phase search strategy** spanning Bing, Google, DuckDuckGo, and direct supplier URLs (McMaster, MSC, Grainger, Amazon, eBay, Online Metals, etc.) to fill 90-120 second search duration.
- **Junk result filtering**: Error pages ("404", "Sorry", "Something Went Wrong"), blocked pages, and generic titles filtered in both `server.py` (before Claude summary) and `index.html` (before rendering part cards in chat).

**Files modified:**
- `ai_inspector/search/browser_engine.py` — async generator `_visit_product()`, 9 search phases, `_generate_narration()`, `_extract_google_links()`, `_extract_ddg_links()`, enriched `_extract_bing_links()` with titles/domains/favicons, removed all screenshot `preview` events
- `static/index.html` — New CSS (`.scout-search-results`, `.scout-reading-mode`, `.scout-blur-lines`, `.scout-narration-bubble`, animations), new HTML inside `.scout-browser-content`, new JS (`setScoutMode()`, `renderSearchResults()`, `highlightSearchResult()`, `showReadingMode()`, `typeNarration()`), junk filtering in `formatPartCards()`
- `server.py` — `_is_junk()` filter applied to results before Claude summary

**PDF Screenshot Capture — Feature #124**

Server-side PDF rendering for agent vision analysis:
- Playwright-based headless PDF screenshot capture via `/api/screenshot-pdf` endpoint
- Enables agents to "see" uploaded PDF drawings for visual analysis

**Auto-Annotate Drawing with Inspection Findings — Feature #125**

Automatic overlay of inspection findings onto the drawing:
- After inspection completes, findings are automatically annotated on the drawing as SVG overlays
- Visual indicators for present, missing, partial, and discrepant features

### Previous Milestone (February 17, 2026)

**InspectorPro v1.0 Web Application — COMPLETE (112/112 features passing, 46 sessions)**

The full web application wrapping the spatial inspection engine is now live and verified:

- **Tech Stack:** FastAPI backend (`server.py`) + vanilla HTML/CSS/JS frontend (`static/index.html`), no framework, no database
- **Backend:** 4 REST API endpoints wrapping `ai_inspector/spatial/engine.py`:
  - `GET /api/profiles` — returns 185 inspection profiles with part number, name, feature count
  - `GET /api/detect-pn?filename=...` — auto-detects part number from uploaded filename
  - `GET /api/reference-views/{pn}` — returns base64-encoded CAD reference views (front/top/right/isometric)
  - `POST /api/inspect` — accepts multipart form (drawing file + part number), runs full spatial inspection, returns findings, report, gap summary, feature list
- **Frontend:** SolidWorks-inspired dark theme, pixel-accurate match to `ui_mockup.html`:
  - Three-column layout: left panel (280px, upload + part info + feature tree), center viewport (tabs: Split View / Drawing Only / CAD Views Only / Report), right panel (280px, loading animation + results)
  - Drag-and-drop file upload (PNG, JPEG, PDF) with auto part number detection and AUTO badge
  - Searchable dropdown with all 185 profiles for manual part selection
  - CAD reference views in 2x2 grid (flex-based 45% width in Split View), click to enlarge in lightbox
  - Chain-of-thought loading animation with 7-step progress timeline and elapsed timer
  - Completeness gauge (SVG arc), color-coded metrics (present/missing/partial/discrepant), critical issues list
  - Feature tree with color-coded status dots and smooth transitions
  - QC report rendered as formatted markdown in Report tab
  - Export dropdown: Markdown report (.md) and full results (.json)
  - Keyboard accessibility (focus-visible outlines, tab navigation, keyboard-activated controls)
  - Custom scrollbars matching dark theme, no page-level scrolling
  - Proper HTTP error codes (404/422 instead of 500) for malformed API requests
  - Responsive layout verified at 1920px, 1440px, and 1280px
- **Server:** `python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload`

**Annotation Features — COMPLETE (features #82-98)**

Drawing markup/annotation capabilities on the Drawing Only tab:
- **Annotation toolbar** with shape categories: Lines, Rectangles, Basic Shapes, Block Arrows, Callouts
- **SVG overlay layer** on top of the drawing for shape rendering
- **Shape tools:** straight lines, single/double arrows, rectangles, rounded rectangles, circles, triangles, diamonds, block arrows (right/left/up/down), callouts (speech bubble, line callout, cloud)
- **Interaction:** select/move/resize shapes with handles, Delete key to remove
- **Styling:** color swatches (red/yellow/green/blue/white/black), stroke width (thin/medium/thick), fill mode (none/semi-transparent/solid)
- **Undo/Clear All** with confirmation dialog
- **Export annotated drawing as PNG** (composites drawing + annotations)
- PDF viewer coexistence, annotation persistence across tab switches, toolbar restricted to Drawing Only tab

**ASME Representation Analysis — COMPLETE (features #99-111)**

ASME Y14.5 compliance analysis integrated into the inspection pipeline:
- ASME feature type mapper and checklist loader (features #99-100)
- Representation fields, summary aggregation, and compliance badges (features #102-104)
- Representation gap details in feature detail panel (feature #105)
- ASME representation analysis included in QC report (feature #106)
- ASME compliance score badge in status bar (feature #107)
- Caution icons for representation gaps in feature detail panel (feature #108)
- Sharpened ASME prompt with reduced noise and reordered content (feature #109)
- Profile type cross-check instruction in INSPECTION_PROMPT (feature #110)
- Profile validation script for feature type consistency (feature #111)

**UI Layout Redesign — COMPLETE (feature #112)**

- Split View redesigned: drawing now takes full viewport width, CAD reference views moved to a horizontal thumbnail strip at the bottom
- Improves readability for landscape-format engineering drawings — callouts and dimensions visible without zooming
- CAD views in bottom strip remain clickable for lightbox enlargement

**112 automated test features** covering: backend engine initialization, API endpoints, file upload, part detection, CAD views, viewport tabs, inspection flow, results display, export, accessibility, error handling, responsive layout, annotations, ASME compliance analysis, and UI layout

### Previous Milestone (February 14, 2026)

**Backend Engine + UI Design for Web App (Autoforge):**
- Extracted all spatial inspection logic from `spatial_inspection.ipynb` into `ai_inspector/spatial/engine.py`
- `SpatialInspector` class with 4 public methods: `list_profiles()`, `detect_part_number(filename)`, `get_reference_views(part_number)`, `inspect(drawing_bytes, filename, ...)`
- Bytes-based input (accepts uploaded file content, not file paths) — ready for web framework integration
- Returns a single dict with findings, report markdown, gap summary, features list, tokens, and elapsed time
- Smoke tested: matches notebook results exactly (1008176: 4/7 present, 57% completeness)
- Created `AUTOFORGE_BRIEF.md` — full spec for Autoforge: SolidWorks-inspired 3-column dark theme layout, 4 API endpoints, chain-of-thought loading UX, color palette, InspectorPro branding
- Created `ui_mockup.html` — pixel-accurate interactive prototype with loading and results states
- New files: `ai_inspector/spatial/__init__.py`, `ai_inspector/spatial/engine.py`, `AUTOFORGE_BRIEF.md`, `ui_mockup.html`

**Spatial Inspection Notebook — Reference CAD Views + Auto Part Detection + Multi-Page Drawing Support:**
- **Reference CAD view injection**: `SEND_REFERENCE_VIEWS = True` sends the 4 rendered CAD model views (front, top, right, isometric) alongside the engineering drawing in the Claude Vision API call. Views are loaded from `400S_Sorted_Library/{PN}_view_{viewname}.png`, encoded as JPEG, and sent as labeled `[CAD FRONT VIEW]` etc. image blocks before the drawing pages. The inspection prompt is augmented with instructions to cross-reference 3D geometry against the 2D drawing.
- **Comparison results (with vs without reference views)**:
  - **1008176 (RACK VISE)**: Without views: 3/7 present, 2 partial, 2 missing, 60%. With views: **4/7 present, 1 partial, 2 missing, 57%** — "Large through holes" improved PARTIAL→PRESENT (both holes found with threading spec). Token cost increased from ~3K to ~9.4K input tokens (4 extra images).
  - **1008175 (PLATE WEAR)**: Without views: 2/2 present, 85%. With views: **2/2 present, 100%** — completeness improved 85%→100%.
  - **178683 (CLEVIS)**: Without views: 2/2 present, 100%. With views: **2/2 present, 100%** — maintained perfect score, richer observations (identified section cut, isometric pictorial).
- **Audit trail**: `reference_views_sent` field added to `_full_context.json` recording which views were sent.

**Spatial Inspection Notebook — Auto Part Detection + Multi-Page Drawing Support (earlier today):**
- Reviewed and validated `spatial_inspection.ipynb` end-to-end
- **Auto part number detection**: `PART_NUMBER = "auto"` extracts candidates from drawing filenames and matches against the 185-profile inspection library. Reuses candidate extraction logic from `ai_inspector/extractors/identity.py` — handles revision suffixes, letter suffixes, hyphenated PNs, merged digits with progressive peeling, Paint suffixes. Profile index supports both exact and normalized matching (strips dashes/spaces/underscores). Falls back to manual config if no match found.
- **Multi-page drawing support implemented**: `DRAWING_PATH` now accepts three input formats:
  - Single file path (backward compatible): `"drawing.png"` or `"drawing.pdf"`
  - List of paths: `["sheet1.png", "sheet2.png"]`
  - Glob pattern: `"drawing_samples_batch/*_1008176_*.png"`
  - PDFs automatically extract all pages (previously only rendered page 1)
- **Page-labeled API calls**: Each page sent as `[PAGE X of Y]` labeled image blocks in a single Claude Vision request
- **Cross-page inspection**: Prompt updated to instruct Claude to check ALL sheets before marking a feature MISSING
- **`found_on_page` tracking**: Findings JSON now records which page(s) each feature was found on; display table includes Page column
- Tested on 3 parts:
  - **178683 (CLEVIS)**: 2/2 features present, 100% completeness (prior run, single page)
  - **1008175 (PLATE WEAR)**: 2/2 features present, 85% completeness (single page, dinged for missing views)
  - **1008176 (RACK VISE)**: 4/7 features present, 57% completeness — tested both single-page and multi-page (machining + casting sheets); multi-page correctly identified "Two-page drawing set" and reported features found across both pages

**Spatial Inspection Pipeline Summary (not new, but now documented):**
- Pre-built spatial profiles exist for 100+ parts in `400S_Sorted_Library` (generated once via `generate_inspection_profiles.py`)
- Profile generation: 4 rendered CAD views + SW JSON → Claude Vision → spatial feature descriptions (no dimensions, spatial understanding only)
- Inspection: Profile primes Claude Vision with what to look for → drawing image(s) sent → structured findings JSON → GPT-4o-mini QC report
- No GPU required — runs entirely on API calls (Claude + OpenAI)

**Files Changed:**
- `spatial_inspection.ipynb` — Cells 2 (config docs + auto default + SEND_REFERENCE_VIEWS), 3 (profile index + candidate extraction + auto-resolve + load logic + ref view loading), 4 (ref views + drawing pages in API call + ref_instruction), 5 (page column in display), 7 (reference_views_sent in audit context)

### Previous Milestone (February 11, 2026)

**Assembly Context + Improved Reporting:**
- **Mating context** wired: `sw_mating_context.json` (62 parts) provides parent assembly + sibling components
- **Mate specifications** wired: `sw_mate_specs.json` (40 parts, 100 mate relationships) provides Concentric/Coincident mates + thread specs (M10x1.5, M8x1.25)
- **Old↔new part number bridging**: `sw_part_context_complete.json` (597 entries) maps between old-style (046, 017-134) and new-style (314884, 199680) part numbers — enables cross-reference when mate_specs uses old keys
- **Sibling cross-reference**: When a part isn't directly in mate_specs, the pipeline looks up its siblings from mating_context, resolves their old PNs via part_context, and collects their mate specs — e.g., 314884 (PAWL) → sibling 199680 → old PN "B18.3.1M - 10 x 1.5 x 30 Hex SHCS" → Concentric mate found
- **GPT-4o report upgraded**: Pre-computed severity summaries (critical vs minor missing, detection coverage assessment, assembly-driven findings, extra↔missing correlations) replace raw JSON dumps — report now has severity tiers, detection caveats, and prioritized next steps
- **Part 314884 (PAWL) end-to-end**: 4 detections, 1 matched (R0.030" fillet), 12 missing (1 critical TappedHole + 11 minor fillets), 3 extra — mating context found (assembly 047-263, 5 siblings), mate specs found via sibling cross-reference (M10x1.5 Concentric mate)
- **Pipeline runtime**: ~380s with VLM enabled (RTX 4000 Ada, 12.9 GB VRAM)

### OCR Quick Wins Implemented (February 11, 2026 - PM)

**Implemented and verified in full pipeline path (not a side notebook):**
- **Canonicalization improvements** in `ai_inspector/extractors/canonicalize.py`:
  - Added stronger diameter-symbol normalization (phi/theta/mojibake variants)
  - Added LaTeX cleanup (`\phi`, `\frac{33}{64}`, etc.) and decimal-repair handling
- **Regex parse improvements** in `ai_inspector/extractors/patterns.py`:
  - Added drill parsing without explicit diameter symbol (e.g., `33/64 DRILL`)
  - Added `THRU ALL` handling and more tolerant tapped-hole parsing for noisy OCR separators
- **OCR robustness in crop reading** in `ai_inspector/extractors/crop_reader.py`:
  - Added hallucinated-tail stripping to remove explanatory prose appended after valid callout text
- **OCR retry behavior** in `ai_inspector/extractors/ocr_adapter.py`:
  - Added confidence-gated second OCR pass with larger crop/token budget and best-pass selection
- **Comparison resilience** in `ai_inspector/comparison/matcher.py`:
  - Added hole↔tapped-hole equivalence matching by diameter (for tap-drill style callouts)
  - Added fallback thread matching from top-level `threadSize`/`pitch` when nested `thread` is absent
  - Added guard to ignore clearly implausible OCR pitch values (prevents false thread mismatches)
- **YOLO post-filtering** in `ai_inspector/pipeline/yolo_pipeline.py`:
  - Added class-specific confidence thresholds to reduce low-confidence false positives

**Validation result (local full notebook run):**
- `tests/notebooks/test_full_pipeline.ipynb` executed successfully to `tests/notebooks/test_full_pipeline_executed_local.ipynb`
- Latest summary for part **314884**: `matched=1, missing=12, extra=1` with `detection_count=2`
- The matched feature is now an **equivalent Hole↔TappedHole** correlation on the `⌀.52 / 33/64 DRILL` style case

### Previous Milestone (February 9, 2026)

**Full 4-Model Pipeline Running Locally:**
- Sequential model loading: YOLO detect → unload → OCR read → unload → VLM page understanding → unload → match → score → GPT-4o report
- Qwen2.5-VL-7B wired for holistic page understanding (title block, tolerances, notes, drawing type, surface finish)
- GPT-4o wired for assembly-aware QC report generation via OpenAI API
- All stages execute without errors on RTX 4000 Ada (12.9 GB VRAM), Python 3.14, Windows 11
- Drawing 176759: 2/2 holes matched (100% instance match rate)
- Drawing 314884 (PAWL): Full pipeline with VLM + mating context + GPT-4o report

### Previous Milestone (February 5, 2026)

**YOLO-OBB Finetuning Complete:**
- Trained YOLO11s-OBB on 224 annotated drawings (550 annotations)
- 4 callout classes: Hole, TappedHole, Fillet, Chamfer
- **mAP50 = 0.729** (target was 0.5) — all classes above 0.70
- Model uploaded to HuggingFace: `hf://shadrack20s/ai-inspector-callout-detection/callout_v2_yolo11s-obb_best.pt`

### What's New in v4.0

v4 introduces a **modular Python package architecture** with **drawing type classification**. Different drawing types (machined parts, weldments, sheet metal, etc.) have different inspection requirements and are handled by specialized analyzers.

**Key Changes from v3:**
- **Modular package structure** (`ai_inspector/`) instead of monolithic notebook
- **Drawing type classifier** determines how to process each drawing
- **Type-specific analyzers** with appropriate feature extraction
- **Conditional OCR** based on drawing type (weldments skip OCR)
- **Slim notebook** (~80 lines) as orchestrator only

### v4 vs v3 Comparison

| Aspect | v3 (Current) | v4 (New) |
|--------|--------------|----------|
| Code structure | Single 300KB notebook | Python package + slim notebook |
| Drawing classification | Page type only (PART_DETAIL/ASSEMBLY) | Full type (7 categories) |
| OCR decision | Based on page type | Based on drawing type |
| Feature extraction | Same for all drawings | Type-specific |
| Testability | Manual notebook runs | Unit tests + integration tests |
| Maintainability | Difficult | Modular, easy to extend |

### Architecture (v4.0) — Model Roles

**Four models, four distinct roles — no overlap. Three GPU models load/unload sequentially (peak ~5.5 GB VRAM):**

| Model | Role | Input | Output | VRAM |
|-------|------|-------|--------|------|
| **YOLO11s-OBB** | Locate + classify callouts | Full page image | Bounding boxes + class labels | ~0.04 GB |
| **LightOnOCR-2-1B** | Read text in each crop | Cropped callout image | Raw text + confidence | ~2.02 GB |
| **Qwen2.5-VL-7B** | Holistic page understanding | Full page image | Title block, notes, context | ~4.5 GB |
| **GPT-4o (API)** | Write QC report | Pre-computed summaries JSON | Severity-tiered pass/fail report | — |

**Assembly context databases (CPU-only, loaded alongside comparison):**

| Database | Entries | Provides |
|----------|---------|----------|
| `sw_mating_context.json` | 62 | Parent assembly, sibling components |
| `sw_mate_specs.json` | 40 | Concentric/Coincident mates, thread specs |
| `sw_part_context_complete.json` | 597 | Old↔new part number mapping for cross-reference |

```
┌─────────────────┐
│  PDF Drawing    │
└────────┬────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────────┐
│  ai_inspector package                                               │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  STAGE 1: Drawing Type Classification                         │  │
│  │  classifier/drawing_classifier.py                             │  │
│  │  → MACHINED_PART | SHEET_METAL | WELDMENT | ASSEMBLY          │  │
│  │  → CASTING | PURCHASED_PART | GEAR                            │  │
│  │  → Returns: type, confidence, use_ocr, use_qwen               │  │
│  └──────────────────────────┬───────────────────────────────────┘  │
│                             │                                       │
│  ┌──────────────────────────▼───────────────────────────────────┐  │
│  │  STAGE 2: Type-Specific Analyzer                              │  │
│  │  analyzers/{type}.py                                          │  │
│  │  ┌─────────────────┐  ┌─────────────────┐                     │  │
│  │  │ BaseAnalyzer    │  │ Type-Specific   │                     │  │
│  │  │ - title_block   │  │ - OCR (if used) │                     │  │
│  │  │ - quality_audit │  │ - Qwen prompts  │                     │  │
│  │  │ - best_practices│  │ - feature focus │                     │  │
│  │  └─────────────────┘  └─────────────────┘                     │  │
│  └──────────────────────────┬───────────────────────────────────┘  │
│                             │                                       │
│  ┌──────────────────────────▼───────────────────────────────────┐  │
│  │  STAGE 3: Comparison                                          │  │
│  │  comparison/matcher.py + diff_result.py                       │  │
│  │  → Type-aware matching rules                                  │  │
│  │  → Mate-derived requirements (from assembly context)          │  │
│  └──────────────────────────┬───────────────────────────────────┘  │
│                             │                                       │
│  ┌──────────────────────────▼───────────────────────────────────┐  │
│  │  STAGE 4: Report Generation                                   │  │
│  │  report/qc_report.py                                          │  │
│  │  → Type-aware emphasis (weld symbols for weldments, etc.)     │  │
│  │  → Assembly context integration                               │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐
│  QC Report      │
│  PASS / FAIL    │
│  + details      │
└─────────────────┘
```

---

## Drawing Types Supported (v4.0)

| Type | % of Library | Use OCR? | Key Features | Critical Checks |
|------|--------------|----------|--------------|-----------------|
| **MACHINED_PART** | 71% | ✓ Yes | holes, threads, GD&T, tolerances | Thread callouts, hole dims |
| **SHEET_METAL** | 10% | ✓ Yes | bends, flat pattern, slots | Bend callouts, (F) dims |
| **ASSEMBLY** | 11% | ✗ No | BOM, balloons, assembly notes | BOM complete, balloons match |
| **WELDMENT** | 4% | ✗ No | weld symbols, BOM, weld callouts | Weld symbols present |
| **CASTING** | 2% | ✓ Yes | critical dims, reference dims | Critical features only |
| **PURCHASED_PART** | 2% | ✗ No | manufacturer table | Cross-reference present |
| **GEAR** | <1% | ✓ Yes | gear data table | Teeth, pitch, pressure angle |

---

## Package Structure (v4.0)

```
AI-tool/
├── ai_inspector/                    # Python package
│   ├── __init__.py                  # Package root, exports main functions
│   │
│   ├── classifier/
│   │   ├── __init__.py
│   │   └── drawing_classifier.py    # Type classification logic ✓ IMPLEMENTED
│   │
│   ├── analyzers/
│   │   ├── __init__.py
│   │   ├── base.py                  # Shared logic (title block, quality)
│   │   ├── machined_part.py         # OCR + Qwen, threads, GD&T
│   │   ├── sheet_metal.py           # Bends, flat pattern
│   │   ├── weldment.py              # Weld symbols, BOM
│   │   ├── assembly.py              # BOM, balloons
│   │   ├── casting.py               # Reference dims
│   │   └── purchased_part.py        # Manufacturer table
│   │
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── ocr.py                   # LightOn OCR wrapper
│   │   ├── vlm.py                   # Qwen VLM wrapper
│   │   └── title_block.py           # Title block parsing
│   │
│   ├── comparison/
│   │   ├── __init__.py
│   │   ├── matcher.py               # Feature matching
│   │   └── diff_result.py           # DiffResult generation
│   │
│   ├── report/
│   │   ├── __init__.py
│   │   └── qc_report.py             # GPT-4o-mini report
│   │
│   └── utils/
│       ├── __init__.py
│       ├── pdf_render.py            # PDF → image
│       ├── sw_library.py            # SolidWorks JSON library
│       └── schemas.py               # Type definitions
│
├── notebooks/
│   └── ai_inspector_v4.ipynb        # Slim orchestrator (~80 lines)
│
├── tests/
│   ├── test_classifier.py
│   ├── test_analyzers.py
│   └── golden_set/                  # Reference drawings + expected outputs
│
├── setup.py                         # ✓ IMPLEMENTED
├── pyproject.toml                   # ✓ IMPLEMENTED
└── PROJECT_STATUS.md                # This file
```

---

## v4.0 Implementation Progress

### Core Infrastructure
| Phase | Module | Status | Notes |
|-------|--------|--------|-------|
| 1 | `classifier/drawing_classifier.py` | ✅ DONE | Classification logic from 258 drawing analysis |
| 2 | `setup.py` + `pyproject.toml` | ✅ DONE | Editable install support |
| 3 | Package skeleton (`__init__.py` files) | ✅ DONE | All directories created |
| 4 | `utils/pdf_render.py` | ✅ DONE | PDF rendering with PyMuPDF |
| 5 | `utils/sw_library.py` | ✅ DONE | SolidWorks JSON library manager |
| 6 | `extractors/ocr.py` | ✅ DONE | LightOnOCR-2 wrapper + callout parsing |
| 7 | `extractors/vlm.py` | ✅ DONE | Qwen2.5-VL wrapper + all prompts |
| 8 | `config.py` | ✅ DONE | Central configuration dataclass |

### YOLO-OBB Detection Pipeline (M0-M12)
| Module | Component | Status | Notes |
|--------|-----------|--------|-------|
| M1 | `detection/yolo_detector.py` | ✅ DONE | YOLO11-OBB inference wrapper |
| M2 | `extractors/cropper.py` | ✅ DONE | OBB crop extraction with padding |
| M3 | `extractors/rotation.py` | ✅ DONE | 4-rotation OCR quality selector |
| M4 | `extractors/ocr_adapter.py` | ✅ DONE | LightOnOCR-2 with confidence |
| M5 | `extractors/crop_reader.py` | ✅ DONE | OCR → parse → VLM fallback |
| M6 | `schemas/callout_packet.py` | ✅ DONE | Provenance tracking dataclass |
| M7 | `extractors/unit_normalizer.py` | ✅ DONE | Inch/mm detection + conversion |
| M8 | `extractors/validator.py` | ✅ DONE | Schema validation + repair |
| M9 | `comparison/quantity_expander.py` | ✅ DONE | 4X → 4 instances expansion |
| M10 | `comparison/matcher.py` | ✅ DONE | Type-aware feature matching |
| M11 | `pipeline/yolo_pipeline.py` | ✅ DONE | Full pipeline orchestrator |
| M12 | `fine_tuning/evaluate.py` | ✅ DONE | Evaluation harness |

### YOLO Finetuning
| Step | Status | Notes |
|------|--------|-------|
| Image selection | ✅ DONE | 224 images from PDF VAULT + machined parts |
| Roboflow annotation | ✅ DONE | 550 annotations across 4 classes |
| Training notebook | ✅ DONE | `notebooks/train_yolo_obb.ipynb` with TensorBoard |
| Model training | ✅ DONE | yolo11s-obb, mAP50=0.729, early stop at epoch 81 |
| HuggingFace upload | ✅ DONE | `shadrack20s/ai-inspector-callout-detection` |
| Config update | ✅ DONE | Default model points to HuggingFace |

### Test Notebooks
| Notebook | Tests | Status |
|----------|-------|--------|
| `test_detection.ipynb` | M1 + M2 (YOLO + Cropping) | ✅ Created, ⏳ Not validated |
| `test_ocr_pipeline.ipynb` | M3 + M4 + M5 (Rotation + OCR + Parse) | ⚠️ Deprecated for primary validation (full pipeline is source of truth) |
| `test_normalize_validate.ipynb` | M7 + M8 (Units + Validation) | ✅ Created, ⏳ Not validated |
| `test_matching.ipynb` | M9 + M10 (Expansion + Matching) | ✅ Created, ⏳ Not validated |
| `test_full_pipeline.ipynb` | Full end-to-end | ✅ Created, ✅ Validated locally (Feb 11 PM run) |

### VLM + Assembly Context + Reporting (Feb 9-11)
| Module | Component | Status | Notes |
|--------|-----------|--------|-------|
| M13 | `extractors/vlm.py` wired into pipeline | ✅ DONE | Sequential load/unload, Qwen2.5-VL-7B |
| M14 | `extractors/prompts.py` PAGE_UNDERSTANDING | ✅ DONE | Title block, tolerances, notes, drawing type |
| M15 | `utils/context_db.py` mating context | ✅ DONE | load_mating_context(), get_mating_context() |
| M16 | `utils/context_db.py` mate specs | ✅ DONE | load_mate_specs(), get_mate_specs(), sibling cross-ref |
| M17 | `utils/context_db.py` part context bridging | ✅ DONE | load_part_context(), old↔new PN mapping |
| M18 | Pipeline assembly context wiring | ✅ DONE | mating_context_path, mate_specs_path, part_context_path |
| M19 | GPT-4o report with pre-computed summaries | ✅ DONE | Severity tiers, detection caveat, assembly findings |

### Remaining Work
| Phase | Module | Status | Notes |
|-------|--------|--------|-------|
| 9 | OCR post-processing quick wins | ⚙️ IN PROGRESS | Implemented core quick wins in canonicalize/parse/matcher; next is broader symbol coverage and regression hardening |
| 10 | OCR fine-tuning on drawing crops | ⏳ PENDING | 200-500 labeled crops needed |
| 11 | More YOLO classes (GD&T, Datum, Weld, etc.) | ⏳ PENDING | Annotate + retrain (14-class taxonomy ready) |
| 12 | 3D spatial context — Phase 1: multi-view renders | ✅ DONE | Reference CAD views sent alongside drawing in spatial inspection notebook |
| 13 | 3D spatial context — Phase 2: assembly renders | ⏳ PLANNED | Exploded view + highlighted part → GPT-4o |
| 14 | 3D spatial context — Phase 3: VLM-guided discovery | ⏳ PLANNED | 3D-highlighted feature → find on 2D drawing |
| 15 | Other analyzers (sheet metal, weldment, etc.) | ⏳ PENDING | One at a time |
| 16 | Datum inference from assembly context | ⏳ PLANNED | Infer datum A/B/C from assembly mates (coincident→primary, concentric→secondary); extract datum refs from GD&T callouts; add to schema + matcher |

---

## Known Limitations

### OCR Quality (Primary Bottleneck)

LightOnOCR-2-1B is a general-purpose document OCR model. It was **not trained on engineering drawings**, which causes:

| Issue | Example | Impact |
|-------|---------|--------|
| **LaTeX / symbol output** | `$\phi$ 1.28`, `\frac{33}{64}` | Quick-win canonicalization now converts common forms, but not all symbol families |
| **Hallucination** | Generates paragraphs about "project planning" after reading a hole callout | Garbage text after first line; regex grabs first valid match |
| **Non-deterministic** | Same image produces different text on different runs | Inconsistent parse results |
| **Symbol blindness** | Cannot reliably read GD&T symbols, weld symbols, datum references | These are graphical symbols not in its training data |
| **Low recall interaction** | OCR improvements applied, but only 2 detections on latest 314884 run | OCR can only improve what YOLO crops; low detection coverage still dominates misses |

**Root cause:** Same as YOLO before fine-tuning — the model has never seen domain-specific data.

### YOLO Detection Coverage

Currently trained on **4 classes only**: Hole, TappedHole, Fillet, Chamfer. Missing:
- GD&T feature control frames
- Datum references
- Weld symbols
- Surface finish callouts
- Bend callouts (sheet metal)
- General dimensions and tolerances
- Notes and special instructions

### Pipeline Gaps

- ~~**Qwen VLM not wired in**~~ ✅ Wired (Feb 9) — sequential load/unload in pipeline
- ~~**GPT-4o report not connected**~~ ✅ Wired (Feb 9) — pre-computed summaries + severity-tiered prompt
- ~~**Assembly context missing**~~ ✅ Wired (Feb 11) — mating context + mate specs + old/new PN bridging
- **OCR accuracy on domain symbols** — improved via quick wins (LaTeX/fraction normalization, hallucination trimming, tolerant parsing), but still weak on GD&T and noisy thread formats; fine-tuning remains necessary
- **YOLO detection coverage** — still the dominant bottleneck; latest full run on 314884 had detection_count=2, which constrains end-to-end match rate
- **SW extractor** only reads from `comparison.holeGroups` fallback — doesn't handle all C# extractor sections (slots, chamfers, fillets in comparison)
- ~~**No 3D spatial context**~~ ✅ Phase 1 implemented (Feb 14) — reference CAD views (front/top/right/isometric) sent alongside drawing in spatial inspection notebook; Phase 2 (assembly renders) and Phase 3 (VLM-guided discovery) still pending

---

## Next Steps (Priority Order)

### 1. OCR Improvement (Foundation — Fixes Match Rate)

OCR is the weakest link. A misread decimal (⌀.52 → ⌀52) makes the comparison engine unable to match valid features. Two tracks:

**Track A: Quick Wins (implemented; continue hardening)**
- ✅ **Implemented:** canonicalization/post-processing rules in `canonicalize.py` (LaTeX cleanup, symbol normalization, decimal repair)
- ✅ **Implemented:** parser hardening in `patterns.py` (`33/64 DRILL`, `THRU ALL`, noisy tapped-hole separators)
- ✅ **Implemented:** OCR hallucination tail stripping in `crop_reader.py`
- ✅ **Implemented:** OCR retry path in `ocr_adapter.py` and matcher resilience updates in `comparison/matcher.py`
- **Immediate next hardening:** build/expand locked regression cases for symbol-heavy and noisy-thread callouts, then tune thresholds using measurable pass/fail benchmarks

**Track B: Fine-Tuning LightOnOCR (medium-term)**
- **Dataset source:** YOLO crops saved to `debug/*/crops/` — these are the input images
- **Labels needed:** Manually transcribe each crop with correct text (e.g., `⌀.750 THRU`, `M6x1.0-6H`)
- **Dataset size:** Target 200-500 labeled crops for initial fine-tune, 2,000-5,000 for production
- **Note:** This is different data from YOLO training — YOLO annotations are bounding boxes on full pages; OCR annotations are text transcriptions of individual crops
- **Goal:** Eliminate hallucination, output clean single-line engineering text, recognize ⌀/±/GD&T symbols natively

### 2. Expand YOLO to More Classes

Currently trained on **4 classes only** (Hole, TappedHole, Fillet, Chamfer). Detects ~4 callouts on drawings that have 15-30+. Need to annotate and retrain with:
- GD&T feature control frames
- Datum references
- Weld symbols
- Surface finish callouts
- Bend callouts (sheet metal)
- General dimensions and tolerances
- Notes and special instructions

Full 14-class taxonomy already defined in `ai_inspector/detection/classes.py`.

### 3. 3D Spatial Context for VLM (New Direction)

**Problem:** The VLM only sees a flat 2D drawing. It has no spatial understanding of the 3D part geometry. This limits its ability to:
- Identify which drawing view corresponds to which part orientation
- Understand why certain features are critical (assembly interfaces)
- Locate specific dimensions on the actual geometry
- Make sense of the mating relationships it receives as JSON

**Solution: Feed rendered 3D views alongside the 2D drawing as multi-image input to GPT-4o/Claude.**

#### Phase 1: Multi-View Part Renders (low effort, high value)
Add to `SolidWorksExtractor/`:
- Render 6 standard views (front, top, right, back, bottom, isometric) as PNGs via SolidWorks API
- Save alongside the SW JSON
- Feed to GPT-4o as additional images in the report prompt
- Prompt: "Here is the 2D drawing and the 3D CAD model from multiple angles. Identify which drawing views correspond to which 3D orientations. Flag features visible in 3D but missing from the drawing."
- **No model training required** — pure prompt engineering with multi-image input

#### Phase 2: Assembly Context Renders (medium effort, high value)
- Render the assembly with the inspected part highlighted in color
- Render an exploded view showing mating interfaces
- Feed to GPT-4o alongside mating context JSON
- Prompt: "The highlighted part mates with the cap screw via the hole shown. Verify the drawing includes callouts for all interface features."
- **Visually grounds the mating relationships** — the model can see where the M10 screw goes through the part instead of just reading it from JSON

#### Phase 3: VLM-Guided Feature Discovery (higher effort, experimental)
- Use 3D renders to help the VLM find features that YOLO missed
- Show side-by-side: 3D render with feature highlighted → corresponding area on 2D drawing
- "The 3D model shows an M10 tapped hole at this location. Find the corresponding callout on the drawing."
- Could significantly improve recall beyond what YOLO training alone can achieve

**Architecture with 3D context:**
```
                    ┌─────────────┐
                    │ SolidWorks  │
                    │   Model     │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        SW JSON       3D Renders    Assembly
        (precise      (6 views +    Renders
        dimensions)    iso PNG)     (exploded)
              │            │            │
              │            ▼            │
              │     ┌─────────────┐    │
              │     │   GPT-4o    │◄───┘
              │     │ (qualitative│
              │     │  reasoning) │◄─── 2D Drawing
              │     └──────┬──────┘
              │            │
              ▼            ▼
        ┌─────────────────────────────┐
        │   Comparison Engine         │
        │  structured + VLM insights  │
        └─────────────────────────────┘
```

**Key principle:** VLM for qualitative understanding (what am I looking at, which features are at interfaces) + SW JSON for quantitative comparison (dimensions, tolerances). Don't ask the VLM to measure — it can't do precise measurements from rendered images.

### 5. Datum Inference from Assembly Context (New Research Direction)

**Problem:** Datums (A, B, C reference frames on engineering drawings) are critical for manufacturing — they dictate fixturing, measurement reference, and machining sequence. Currently, our system does NOT extract, store, or compare datum information. The VLM prompt collects `datumReferences` but the field is never parsed or used downstream. GD&T regex patterns drop datum letters after the tolerance value.

**Insight:** ~70-80% of datum assignments follow directly from how a part fits into its assembly. The primary datum (A) is almost always the primary mating/locating surface. This means assembly mate data — which we already partially have in `sw_mate_specs.json` — can be used to **infer likely datums** without the designer explicitly specifying them.

**Reference Drawing:** 1008175 (PLATE WEAR C916) — Datum A is the mounting face, parallelism 0.003 to A, flatness inspected in restrained state using fixture #28544. The datum choice maps directly to the coincident mate in the assembly.

#### Tier 1: Extract Datums from Drawings (low effort)
- Parse datum reference letters from GD&T feature control frames (update `patterns.py` regex to capture trailing datum letters A, B, C after tolerance value)
- Add `datumReferences` field to GDT callout type in `callout_schema.py`
- Display datum info in inspection results and QC report

#### Tier 2: Infer Datums from SolidWorks Part Model (medium effort)
- Identify faces used as sketch planes for critical features
- Identify faces with the most constraints/references in the feature tree
- Flag likely datum candidates and rank by confidence

#### Tier 3: Infer Datums from Assembly Mates (high value, medium-high effort)
- Analyze assembly mates to identify primary/secondary/tertiary locating surfaces:
  - Coincident (planar face) → Primary datum (A) — locating surface
  - Concentric (cylindrical) → Secondary datum (B) — centering feature
  - Distance/Angle constraint → Tertiary datum (C) — rotational lock
- Cross-reference inferred datums against drawing's GD&T to validate datum assignments
- Requires assembly-level mate traversal in `SolidWorksExtractor/` (C# layer) — currently `AssemblyExtractor.cs` references `swSelDATUMPLANES`/`swSelDATUMAXES`/`swSelDATUMPOINTS` but only for mate entity classification, not for datum inference
- Output: per-part JSON with `inferredDatums: [{letter: "A", face: "Face<1>", mateType: "Coincident", confidence: 0.9}]`

#### Why This Matters for Manufacturing
- **Fixturing:** Datum A tells the machinist which surface to clamp against. Wrong datum = wrong fixture = every dimension is off.
- **Measurement reference:** All GD&T is meaningless without the datum reference frame.
- **Process order:** Datums often dictate machining sequence (machine datum A first, reference everything else from it).
- **Tolerance accumulation:** Wrong datum frame can make in-tolerance parts measure out-of-tolerance.

**Dependencies:** Tier 3 depends on expanding the C# SolidWorks extractor to traverse assembly mates per-face (not just per-component). Tier 1 can proceed immediately. Tier 2 requires SolidWorks API access to feature tree sketch plane references.

### 4. Batch Evaluation on Full Drawing Library
Run pipeline on all 258 drawings with matched SW JSONs to measure:
- Detection recall and precision per class
- OCR accuracy (CER/WER) before and after improvements
- End-to-end match rate against SW data
- Report quality assessment

---

## Drawing Analysis Summary (Basis for v4 Classification)

**Source:** 258 unique drawings from 400S_Sorted_Library (band saw machine)

**Analysis Method:**
1. Rendered all 526 PDFs (258 unique after deduplication)
2. Extracted text via PyMuPDF
3. Classified based on text patterns
4. Spot-checked with visual inspection

**Key Patterns Identified:**

| Pattern | Detection Method | Drawing Type |
|---------|------------------|--------------|
| "WELDT" in title | Text search | WELDMENT |
| BOM table (ITEM NO + QTY) | Column detection | ASSEMBLY |
| Manufacturer table (NSK/SKF) | Multiple supplier names | PURCHASED_PART |
| Gear data (TEETH, PITCH) | Keyword count ≥2 | GEAR |
| "DUCTILE IRON" / "MFG ITEM #" | Material callout | CASTING |
| "FLAT PATTERN" / bend callouts | View label + bend spec | SHEET_METAL |
| Default | No specific signals | MACHINED_PART |

**Reference Drawings Organized:**
```
Drawing_Analysis_By_Type/
├── 01_Machined_Parts/     (184 files)
├── 02_Sheet_Metal/        (26 files)
├── 03_Castings/           (4 files)
├── 04_Assemblies/         (29 files)
├── 05_Weldments/          (11 files)
├── 06_Purchased_Parts/    (4 files)
└── README.md
```

---

## v3.0 Features (Preserved in v4)

All v3 functionality is preserved and will be refactored into modules:

### Core Pipeline (from v3)
- ✓ Page classification (PART_DETAIL/ASSEMBLY_BOM/MIXED)
- ✓ Conditional OCR based on page type
- ✓ Multi-page PDF support
- ✓ LightOnOCR-2 text extraction with markdown cleanup
- ✓ Qwen2.5-VL-7B feature extraction (enhanced prompt)
- ✓ Evidence merge with deduplication
- ✓ SW JSON comparison with tolerance matching
- ✓ GPT-4o-mini report generation
- ✓ Graceful degradation when no CAD data

### Recent Enhancements (from v3)
- ✓ Mate-derived requirements (M8 thread from assembly context)
- ✓ Sheet metal bend hole filtering (skip geometry artifacts)
- ✓ Inspector requirements database integration
- ✓ Dimension suffix recognition ((F), STK., REF., TYP.)
- ✓ Enhanced thread format parsing (Metric, Unified, ACME)
- ✓ GD&T extraction
- ✓ Surface finish callouts
- ✓ Coating/heat treatment specs

---

## Testing Strategy (v4)

### Unit Tests (Fast)
- Classifier logic: text → type mapping
- Title block extraction
- Feature parsing/normalization
- Matching rules

### Integration "Golden Set" (20-30 drawings)
- Representative drawings covering all types
- Expected outputs (or key assertions)
- Run on every commit to prevent regressions

### Full Batch Run (258 drawings)
- Periodic regression/evaluation
- Track metrics:
  - Type classification accuracy
  - OCR extraction rate
  - Match rate distribution
  - Top failure modes

---

## Colab Usage (v4)

```python
# 1. Clone repo and install
!git clone https://github.com/user/AI-tool.git
%cd AI-tool
!pip install -e .

# 2. Import and run
from ai_inspector import pipeline

result = pipeline.run(
    pdf_path="drawing.pdf",
    sw_library_path="sw_json_library.zip"
)

# 3. Display results
result.display()
```

---

## API Keys Required (Colab Secrets)
- `HF_TOKEN` - Hugging Face (for model downloads)
- `OPENAI_API_KEY` - OpenAI (for GPT-4o-mini reports)

---

## Change Log

### February 17, 2026 - InspectorPro v1.0 Feature Complete (111/111)

**All 111 features passing across 45 Autoforge sessions:**
- Features #82-98: Annotation toolbar, shapes, interaction, styling, export, PDF coexistence, tab persistence
- Features #99-111: ASME Y14.5 representation analysis, compliance badges, gap details, prompt sharpening, profile validation

### February 16, 2026 - InspectorPro v1.0 Web App Complete

**Full web application built and verified via Autoforge autonomous coding (33 sessions, 81/81 features passing):**
- FastAPI backend (`server.py`) wrapping `ai_inspector/spatial/engine.py` with 4 API endpoints
- Vanilla HTML/CSS/JS frontend (`static/index.html`) matching `ui_mockup.html` pixel-for-pixel
- SolidWorks-inspired dark theme, three-column layout, 4 viewport tabs
- Drag-and-drop upload, auto part number detection, searchable profile dropdown
- CAD reference views in 2x2 grid with lightbox enlargement
- Chain-of-thought loading animation, completeness gauge, color-coded results
- Feature tree with status transitions, QC report rendering, export (Markdown + JSON)
- Keyboard accessibility, custom scrollbars, responsive layout (1920/1440/1280px)
- Proper HTTP error handling (404/422)
- Zero console errors across all features

**Annotation features added (Drawing Only tab):**
- Shape toolbar: lines, arrows, rectangles, circles, triangles, diamonds, block arrows, callouts
- SVG overlay for shape rendering on top of drawings
- Select/move/resize with handles, color/stroke/fill controls, undo, clear all
- Export annotated drawing as PNG
- Bug fixes in progress: PDF viewer tool coexistence, tab-switch shape persistence

**New files:** `server.py`, `static/index.html`, `init.sh`

### February 14, 2026 - Autoforge Brief Updated with Final UI Design

- Updated `AUTOFORGE_BRIEF.md` with SolidWorks-inspired 3-column dark theme layout (left feature tree, center viewport, right analysis sidebar)
- Added chain-of-thought loading state spec: spinning logo + 7-step progress timeline
- Added complete color palette table with high-contrast colors (`#00E676` green, `#FF1744` red, `#FFD600` yellow, `#FFB300` amber)
- Added InspectorPro branding with crosshair SVG logo, "no AI model branding" design note
- Reference HTML mockup at `ui_mockup.html` included as pixel-accurate interactive prototype

### February 14, 2026 - Backend Engine Extracted for Autoforge Web UI

- Extracted spatial inspection pipeline from notebook into `ai_inspector/spatial/engine.py` (`SpatialInspector` class)
- 3 public methods: `list_profiles()`, `detect_part_number()`, `inspect()` — bytes-based input, single dict output
- Created `AUTOFORGE_BRIEF.md` with full web UI spec (layout, 3 API endpoints, response schemas, design notes)
- Smoke tested: `inspect()` produces identical results to notebook (1008176: 4/7 present, 57%)

### February 14, 2026 - Spatial Inspection: Reference CAD Views + Auto Part Detection + Multi-Page Drawings

- Reviewed `spatial_inspection.ipynb` pipeline and validated on multiple parts
- **Auto part number detection**: `PART_NUMBER = "auto"` extracts candidates from drawing filenames using logic adapted from `ai_inspector/extractors/identity.py` (revision peeling, letter suffix removal, hyphen normalization, progressive digit peeling) and matches against a profile index built from `400S_Sorted_Library` (185 profiles, exact + normalized matching)
- **Reference CAD view injection**: Added `SEND_REFERENCE_VIEWS = True` config toggle. Loads 4 rendered CAD views (front/top/right/isometric) from library, encodes as JPEG, sends as labeled image blocks before drawing pages. Prompt augmented with cross-reference instructions. Results: improved feature detection on 1008176 (PARTIAL→PRESENT for large through holes), improved completeness on 1008175 (85%→100%). Token cost ~3x higher due to 4 extra images.
- Implemented multi-page drawing input: single path, list of paths, glob pattern, and multi-page PDF extraction
- Updated Claude Vision API call to send all pages as labeled `[PAGE X of Y]` image blocks
- Updated inspection prompt to require cross-page checking before marking features MISSING
- Added `found_on_page` field to findings JSON schema and Page column to display output
- Tested backward compatibility (single image) and multi-page mode (2-page list for part 1008176)
- Tested auto-detection: `59_BASE ASSEMBLY_1008176_01.png` → auto-resolved to profile `1008176` (exact match)
- Updated config cell docs with multi-page and auto-detect usage examples
- Updated `PROJECT_STATUS.md` to reflect dual-approach architecture (YOLO+OCR pipeline + spatial vision inspection)

### February 11, 2026 - OCR Quick Wins Integrated into Full Pipeline

- Implemented OCR quick wins directly in pipeline code path (`canonicalize.py`, `patterns.py`, `crop_reader.py`, `ocr_adapter.py`, `matcher.py`, `yolo_pipeline.py`)
- Ran `tests/notebooks/test_full_pipeline.ipynb` locally end-to-end; artifacts written to `tests/notebooks/test_full_pipeline_executed_local.ipynb`
- Confirmed improved robustness on fraction/drill-style parsing and hole↔tapped-hole equivalence matching
- Confirmed remaining limitation: low YOLO recall is currently the strongest constraint on end-to-end match rate

### February 11, 2026 - Assembly Context + Severity-Tiered Reports

**Assembly Context Wired End-to-End:**
- `sw_mating_context.json` (62 entries): parent assembly + sibling components for each part
- `sw_mate_specs.json` (40 entries, 100 mates): Concentric/Coincident mates with thread specs (M10x1.5, M8x1.25)
- Old↔new part number bridging via `sw_part_context_complete.json` (597 entries) — enables cross-reference when databases use different numbering schemes
- Sibling cross-reference: when a part isn't directly in mate_specs, looks up its siblings' specs to infer required features (e.g., 314884 PAWL → sibling 199680 SCR CAP HEX → M10 Concentric mate found)

**GPT-4o Report Upgraded with Pre-Computed Summaries:**
- Severity-grouped missing features: critical (TappedHole, Hole) vs minor (Fillet, Chamfer)
- Detection coverage assessment: flags LOW when YOLO detects fewer callouts than typical for the drawing type
- Assembly-driven findings: extracts Concentric mates that imply required tapped holes / bored holes
- Extra↔missing correlation: flags drawing callouts that may be mismatched versions of missing SW features
- Feature breakdown by type and status
- Prompt restructured: VERDICT → CRITICAL → MINOR → CAVEAT → NEXT STEPS

**Files Changed:**
- `ai_inspector/utils/context_db.py` — Added load_part_context(), load_mate_specs(), get_mate_specs(), get_mate_specs_for_siblings(), old_pn bridging in get_mate_specs()
- `ai_inspector/pipeline/yolo_pipeline.py` — Added mate_specs_path, part_context_path params; mate_specs in PipelineResult; sibling cross-reference logic; mate_specs.json debug output; CLI flags
- `tests/notebooks/test_full_pipeline.ipynb` — Added Cell 8 (mate specs display), updated Cell 13 (pre-computed summaries + severity-tiered prompt), added MATE_SPECS_PATH and PART_CONTEXT_PATH config

**Test Results (Part 314884 PAWL):**
- 4 detections, 1 matched (R0.030" fillet), 12 missing (1 critical TappedHole + 11 fillets), 3 extra
- Mating context: assembly 047-263, siblings: PIN LOWER SPRING, SCR CAP HEX M10X1.5X30, T-NUT
- Mate specs: found via sibling cross-reference (M10x1.5 Concentric mate with part 046)
- Report correctly highlights: "Missing Tapped Hole: 33/64" diameter, critical for assembly with M10X1.5X30 cap screw"

### February 9, 2026 - VLM + GPT-4o Report Wired into Pipeline

**Qwen2.5-VL-7B Wired for Page Understanding:**
- Sequential model loading: YOLO → unload → OCR → unload → VLM → unload (peak ~5.5 GB VRAM)
- Full page understanding: title block, tolerances, notes, drawing type, surface finish, views, datums
- `extractors/vlm.py` + `extractors/prompts.py` integrated into pipeline Phase 3

**GPT-4o Report Generation:**
- All pipeline context assembled as JSON and sent to GPT-4o API
- Mating context included when available
- Report saved as `qc_report.md` in debug output

**Mating Context Wired:**
- `utils/context_db.py` extended with load_mating_context() and get_mating_context()
- Pipeline resolves part number from SW JSON (priority) or VLM title block (fallback)
- Assembly context saved as `assembly_context.json` in debug output

**Files Changed:**
- `ai_inspector/pipeline/yolo_pipeline.py` — VLM Phase 3, mating_context_path, PipelineResult.page_understanding + mating_context
- `ai_inspector/utils/context_db.py` — mating_context support
- `tests/notebooks/test_full_pipeline.ipynb` — 15 cells, full end-to-end with VLM + mating context + GPT-4o report

### February 9, 2026 - Full Pipeline Validated End-to-End

**Pipeline Bugs Fixed (5):**
- `config.py`: Reduced `ocr_max_tokens` 2048 → 128 (prevented runaway OCR generation)
- `extractors/ocr.py`: Added `repetition_penalty=1.2`, image resize to 384px max, per-call `max_tokens` override
- `extractors/ocr_adapter.py`: Passes resize + `max_tokens=64` for crop-level OCR
- `pipeline/yolo_pipeline.py`: Added `encoding="utf-8"` to JSON file writes (Windows cp1252 Unicode crash)
- `extractors/canonicalize.py`: Added LaTeX-to-Unicode conversion (13 patterns: `\phi`→⌀, `\varphi`→⌀, subscript extraction, garbage removal)
- `comparison/sw_extractor.py`: Added fallback extraction from `comparison.holeGroups` (C# extractor format)

**Performance Improvement:**
- Pipeline runtime reduced from **49 minutes** to **16-126 seconds** (depending on detection count)
- Root cause: OCR model was generating thousands of repeated tokens per crop with no size limit or repetition penalty

**Test Results:**
- Drawing 176759 + SolidWorks JSON: 2/2 holes matched (⌀1.28" delta=+0.0005", ⌀.75" delta=+0.0020")
- Drawing 1008193 (complex, 12 callouts): All 12 detected, validated, parsed by regex
- Multiple test images from PDF VAULT ran without errors

**Key Decision: Model Roles Clarified:**
- **YOLO**: Locate and classify callouts (crop extraction)
- **LightOnOCR**: Read text inside each crop (needs fine-tuning)
- **Qwen VLM**: Full-page understanding (title block, notes, context) — NOT used as crop fallback
- **GPT-4o**: Final QC report generation from all combined data

### February 5, 2026 - YOLO-OBB Finetuning Complete

### February 6, 2026 - Detection Threshold Calibration Note

**Test Result Recorded:**
- Ran `test_detection.ipynb` on `00595601_04.png` with finetuned HF model.
- Detections: 5 total (`Fillet` 1, `Hole` 3, `Chamfer` 1, `TappedHole` 0).
- Observed likely false-positive `Fillet` on this page; no `TappedHole` expected from visible callouts.

**Calibration Decision (to revisit):**
- Add class-specific confidence gating for post-processing, with stricter threshold on `Fillet`.
- Proposed starting thresholds for next tuning pass:
  - `Hole`: 0.40
  - `Chamfer`: 0.35
  - `TappedHole`: 0.40
  - `Fillet`: 0.88

**Status:** Deferred for dedicated threshold tuning pass after OCR pipeline validation.

**Model Training:**
- Collected 224 training images from PDF VAULT and machined parts folders
- Annotated 550 callouts in Roboflow (Hole, TappedHole, Fillet, Chamfer)
- Trained yolo11s-obb with drawing-safe augmentation (no flip, no color shift)
- Achieved **mAP50 = 0.729** (per-class: Hole 0.78, TappedHole 0.72, Fillet 0.70, Chamfer 0.71)
- Early stopping triggered at epoch 111 (best at epoch 81)

**Infrastructure Updates:**
- Training notebook updated to use TensorBoard instead of W&B
- Model saved to HuggingFace Hub: `shadrack20s/ai-inspector-callout-detection`
- `config.py` updated to default to HuggingFace model path
- Test notebooks updated to load model from HuggingFace

**Files Changed:**
- `notebooks/train_yolo_obb.ipynb` — v2 with TensorBoard + HuggingFace
- `ai_inspector/config.py` — Default yolo_model_path to HF
- `tests/notebooks/test_detection.ipynb` — Use HF model
- `tests/notebooks/test_full_pipeline.ipynb` — Use HF model

### January 29, 2026 - v4.0 Development Started (Modular Architecture)

**New Package Structure:**
- Created `ai_inspector/` Python package with proper module organization
- Added `setup.py` and `pyproject.toml` for editable install
- Created `classifier/drawing_classifier.py` with full classification logic

**Drawing Type Classification:**
- 7 drawing types: MACHINED_PART, SHEET_METAL, WELDMENT, ASSEMBLY, CASTING, PURCHASED_PART, GEAR
- Type-specific configurations (use_ocr, features_to_extract, critical_checks)
- Based on analysis of 258 unique drawings from 400S library

**Drawing Analysis:**
- Processed all 526 PDFs (258 unique after deduplication)
- Organized into categorized folders by type
- Created classification log and README documentation

**v3 Qwen Prompt Enhancements (merged into v4):**
- Dimension suffixes: (F), STK., REF., TYP., MAX., MIN.
- Thread formats: Metric M##X#.#-6H, Unified UNC/UNF, ACME
- Sheet metal: FLAT PATTERN, bend callouts, gauge materials
- Special types: Casting signals, Purchased parts, Gears
- GD&T: Position, perpendicularity, runout, concentricity
- Surface finish: Ra microinch callouts
- Coating/heat treat: Paint, powder coat, hardness specs
- Weldment signals: WELDT keyword + BOM table

### January 28, 2026 - v3.0 Development (Smart Classification Pipeline)
- Page classification system (PART_DETAIL/ASSEMBLY_BOM/MIXED)
- Conditional OCR based on page type
- Multi-page PDF support
- OCR markdown preprocessing
- Enhanced Qwen feature prompts
- No-SW-JSON graceful degradation
- Mate-derived requirements integration
- Sheet metal hole filtering

### January 27, 2025 - v2.0 Complete
- BOM extraction
- Manufacturing notes
- GPT-4o-mini report integration
- Dual AI pipeline (LightOnOCR + Qwen)

---

## Technical Notes

- **Assembly:** 400S (band saw machine)
- **SolidWorks version:** 2023
- **Local dev environment:** Windows 11, RTX 4000 Ada 12GB, Python 3.14, CUDA 12.8
- **Colab GPU:** T4 or better for inference
- **Peak GPU memory:** ~5.5 GB (models load/unload sequentially: YOLO ~0.04GB → OCR ~2.02GB → VLM ~4.5GB)
- **GPT-4o cost:** ~$0.01-0.05 per report (~2,000-3,500 tokens)
- **Pipeline runtime:** ~330-380s with VLM, ~16-126s without VLM
- **Unique drawings in library:** 258
- **Drawing types:** 7 (machined parts most common at 71%)
- **SW JSON library:** 383 extracted JSON files (C# SolidWorks Extractor)
- **Assembly context:** 62 parts in mating context, 40 parts in mate specs, 597 parts in part context
- **Matched drawing+JSON pairs identified:** 6+ (176759, 314884, 1008176, 1013072, 226121, 231977, 231979)
