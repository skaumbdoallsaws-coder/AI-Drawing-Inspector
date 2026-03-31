# ASME Reference UI: Deterministic Section Surfacing + Popup Viewer

**Status: Plan v6 — implementation-ready**
**Date: 2026-03-28**

## Goal

Surface ASME Y14.5 section references and standard page images directly in the UI when Iris flags representation issues. The user sees:
1. Clickable ASME section references in the chat alongside findings
2. A floating popup (BOM-style) showing the relevant ASME standard page(s)
3. A post-inspection summary listing all ASME representation issues with section references

**Scope clarification:** This is deterministic section/reference surfacing — matching finding keywords to ASME feature checklists and their associated page images. It is NOT exact rule-to-page grounding (the checklists do not contain per-rule page mappings). The references point to the correct ASME topic section and its associated pages.

## Codex Round 1 Findings (All Addressed in v2)

| # | Finding | Resolution |
|---|---------|------------|
| 1 | RAG images sent to Claude without metadata — model can't reliably cite exact page/feature | **Switched to deterministic citation.** Server resolves references from findings + checklists, not from model-emitted markers. |
| 2 | rag_visual_db paths (Fundamental_Rules, etc.) have no matching popup target | **Unified serving endpoint** covers both `rag_visual_db/` and `asme_feature_references/`. Whitelist enforced. |
| 3 | Chat addMessage() is plain text, no structured metadata | **Extended message shape** to carry optional `asme_refs` array. Rendering function checks for it. |
| 4 | Post-inspection auto-summary underspecified | **Local builder** — no agent API call. Server attaches `asme_checklist_findings` to inspection response. Frontend renders directly. |

## Codex Round 4 Findings (All Addressed in v5)

| # | Finding | Resolution |
|---|---------|------------|
| 1 | `_addMessageToAgent()` doesn't clear welcome message or suggestion chips like `addMessage()` does | **Fixed.** Helper now removes `.agent-welcome` and calls `removeSuggestions()` when target agent is active (live DOM), and strips them from `agentMessagesHtml[agentKey]` when inactive (cached HTML). |
| 2 | Step 6 chat refs iterate first 10 inspection findings — too broad, attaches unrelated refs to generic follow-ups | **Fixed.** Priority order: (1) `focused_feature` from context if set, (2) user message keywords, (3) only findings with non-PRESENT status (representation gaps). Never the full features list. |

## Codex Round 3 Findings (All Addressed in v4)

| # | Finding | Resolution |
|---|---------|------------|
| 1 | Post-inspection summary assumes `renderAgentChat()` which doesn't exist; agent switching restores cached innerHTML, not a fresh render | **Fixed.** Summary uses `_addMessageToAgent('inspector', text, metadata)` — a new helper that both appends DOM to the cached `agentMessagesHtml['inspector']` string AND pushes to `agentConversations['inspector']`. If Iris is active, it also appends to live DOM. No phantom `renderAgentChat()`. |
| 2 | Step 6 chat refs only use user message keywords, never the inspection context findings | **Fixed.** Step 6 now also iterates `ctx.get("findings", [])` (the features list sent in inspection context) and collects refs from those too. User message keywords + context findings both contribute. |
| 3 | `_load_rag_images()` pair-count bug: inner `len(images) >= max_images` counts both labels and images, stopping after only 2 image pairs | **Fixed.** Inner loop uses a separate `image_count` counter that only increments on actual image appends, not label appends. |

## Codex Round 2 Findings (All Addressed in v3)

| # | Finding | Resolution |
|---|---------|------------|
| 1 | Step 3 iterates `results["findings"]` (nested dict) instead of `results["features"]` (flat list) | **Fixed.** Resolver iterates `results["features"]` — the flat list of feature dicts with `name`, `status`, `observation`, `type` fields. Engine returns `"features": findings.get("features", [])` at the top level of the inspection response. |
| 2 | Agent chat replies don't return `asme_refs` — only the inspection response does | **Fixed.** Added server step: after agent response parsing, run `_resolve_asme_refs_for_finding()` against each finding keyword in the current inspection context. Attach matching refs to the chat response as `asme_refs`. This is a lightweight lookup (no API call) using the same deterministic resolver. |
| 3 | Resolver uses "first keyword match wins" — `"hole missing position tolerance"` routes to Hole before GDT_Position | **Fixed.** Changed to multi-match: resolver collects ALL matching feature types (not first-match-wins), returns refs for each. Keyword order no longer matters. |
| 4 | Post-inspection summary posts under whichever agent is active, not necessarily Iris | **Fixed.** Summary is posted explicitly to the `inspector` conversation array, not `currentAgent`. If user is on Sage/Scout, summary still lands in Iris's history and renders when they switch to Iris. |
| 5 | Path parameter needs whitelist | **Explicit whitelist** of valid directories, checked before file access. |
| 6 | HTML injection risk from raw interpolation | **All model/JSON strings escaped** via textContent or DOM APIs, never innerHTML with raw strings. |

---

## Architecture Change: Deterministic vs Model-Generated Citations

**Old approach (v1, rejected):** Ask Iris to emit `ASME_REF: Hole, P41, "rule"` markers. Unreliable because RAG images are sent without source metadata — the model would be guessing page numbers.

**New approach (v2):** Server resolves citations deterministically:

```
Inspection finding: "Blind hole missing depth symbol"
    ↓
Server: finding mentions "hole" → lookup asme_feature_references/Hole/checklist.json
    ↓
checklist.json: asme_reference = "ASME Y14.5-2018, Section 4.12-4.14"
               required[1] = "Depth symbol (↧) used for blind holes"
               reference images = ["reference_01_P41.png", "reference_02_P44.png"]
    ↓
Server attaches to finding: { asme_ref: { section: "§4.12-4.14", rule: "...", feature_type: "Hole", pages: [41, 44] } }
    ↓
Frontend renders: clickable "📖 ASME Y14.5 §4.12-4.14" link → popup shows page 41
```

**No model-generated markers. No prompt changes for citation format. Citations are grounded in the checklist data, not model imagination.**

The model's role is still what it does today: use the RAG images to reason about representation issues. The citation/linking layer is purely server-side data lookup.

---

## Existing Infrastructure

| Component | Location | Status |
|-----------|----------|--------|
| `RAG_KEYWORD_MAP` | server.py:1834-1874 | Active — 27 keywords → directories |
| `_find_relevant_rag_dirs()` | server.py:2185-2209 | Active — keyword matching |
| `_load_rag_images()` | server.py:2212-2237 | Active — base64 image loading |
| `rag_visual_db/` | Root | 294 ASME page images, 9 topic sections |
| `asme_feature_references/` | Root | 21 feature folders, each with `checklist.json` + page PNGs |
| `checklist.json` per feature | e.g. `Hole/checklist.json` | ASME section, required rules, common errors, page numbers |
| Reference PNGs | e.g. `reference_01_P41.png` | ASME standard pages, page number encoded in filename |
| Agent RAG pipeline | server.py:3054-3082 | Iris/Sage receive ASME images with API calls |

---

## Implementation Steps

### Step 1: Server — ASME Reference Image Endpoint

**File: server.py**

Serve ASME reference images from both `asme_feature_references/` and `rag_visual_db/`. Whitelist-protected.

```python
# Valid ASME reference directories (whitelist)
ASME_REF_WHITELIST = {
    # asme_feature_references/ folders
    "Hole", "Chamfer", "Counterbore", "Countersink", "TappedHole",
    "Fillet_Radius", "Slot", "Keyseat", "Knurl", "ConicalTaper",
    "Surface_Texture", "Dimension_Basics", "Line_Conventions", "Spotface",
    "GDT_Datums", "GDT_Form", "GDT_Orientation", "GDT_Position",
    "GDT_Profile", "GDT_Runout", "GDT_Symbology",
    # rag_visual_db/ sections
    "04_Fundamental_Rules", "05_Tolerancing_Defaults", "06_Symbology",
    "07_Datums", "08_Form_Tolerances", "09_Orientation_Tolerances",
    "10_Position_Tolerances", "11_Profile_Tolerances", "12_Runout_Tolerances",
}

@app.get("/api/asme-ref/{folder}/{image_name}")
async def get_asme_reference(folder: str, image_name: str):
    """Serve an ASME reference page image. Whitelist-protected."""
    if folder not in ASME_REF_WHITELIST:
        raise HTTPException(status_code=404, detail="Unknown reference folder")
    # Sanitize image_name: allow only alphanumeric, underscore, hyphen, dot
    if not re.match(r'^[\w\-]+\.png$', image_name):
        raise HTTPException(status_code=400, detail="Invalid image name")
    # Try asme_feature_references/ first, then rag_visual_db/
    for base in [Path("asme_feature_references"), Path("rag_visual_db")]:
        img_path = base / folder / image_name
        if img_path.exists() and img_path.is_file():
            return FileResponse(img_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Image not found")
```

**Where to insert:** After the existing `/api/assembly-model/` endpoint block, before voice endpoints.

---

### Step 2: Server — Deterministic ASME Reference Resolution

**File: server.py**

New function that maps inspection finding keywords to ASME checklist data + image paths. Called server-side, no model involvement.

```python
# Mapping from finding keywords to asme_feature_references/ folder names
FINDING_TO_ASME_FEATURE = {
    "hole": "Hole",
    "bore": "Hole",
    "thru": "Hole",
    "blind": "Hole",
    "depth": "Hole",
    "chamfer": "Chamfer",
    "bevel": "Chamfer",
    "counterbore": "Counterbore",
    "cbore": "Counterbore",
    "countersink": "Countersink",
    "csink": "Countersink",
    "thread": "TappedHole",
    "tapped": "TappedHole",
    "tap": "TappedHole",
    "fillet": "Fillet_Radius",
    "radius": "Fillet_Radius",
    "round": "Fillet_Radius",
    "slot": "Slot",
    "keyseat": "Keyseat",
    "keyway": "Keyseat",
    "knurl": "Knurl",
    "taper": "ConicalTaper",
    "surface finish": "Surface_Texture",
    "roughness": "Surface_Texture",
    "datum": "GDT_Datums",
    "position": "GDT_Position",
    "flatness": "GDT_Form",
    "perpendicularity": "GDT_Orientation",
    "parallelism": "GDT_Orientation",
    "runout": "GDT_Runout",
    "profile": "GDT_Profile",
    "tolerance": "05_Tolerancing_Defaults",
    "dimension": "Dimension_Basics",
    "gd&t": "GDT_Symbology",
    "feature control": "GDT_Symbology",
}


def _resolve_asme_refs_for_finding(finding: dict) -> List[dict]:
    """Given an inspection finding, resolve ALL matching ASME references.

    Returns a list of ref dicts (may be empty). Each has section, rules,
    feature_type, and image URLs. Multi-match: a finding like "hole missing
    position tolerance" returns refs for BOTH Hole and GDT_Position.

    Does NOT call the model — purely deterministic keyword lookup.
    """
    text = ""
    for key in ["name", "observation", "status", "feature_type"]:
        val = finding.get(key, "")
        if val:
            text += " " + str(val).lower()

    # Collect ALL matching feature types (not first-match-wins)
    matched_features = set()
    for keyword, feature_type in FINDING_TO_ASME_FEATURE.items():
        if keyword in text:
            matched_features.add(feature_type)

    if not matched_features:
        return []

    refs = []
    for matched_feature in matched_features:
        # Load checklist from asme_feature_references/
        checklist_path = Path("asme_feature_references") / matched_feature / "checklist.json"
        if checklist_path.exists():
            with open(checklist_path, "r", encoding="utf-8") as f:
                checklist = json.load(f)

            # Find matching required rules (2-word overlap with finding text)
            matched_rules = []
            for rule in checklist.get("required", []):
                finding_words = set(text.split())
                rule_words = set(rule.lower().split())
                if len(finding_words & rule_words) >= 2:
                    matched_rules.append(rule)
            if not matched_rules:
                matched_rules = checklist.get("required", [])[:2]

            # Collect reference images
            ref_dir = Path("asme_feature_references") / matched_feature
            pngs = sorted(ref_dir.glob("reference_*.png"))[:2]
            images = []
            for p in pngs:
                page_match = re.search(r'P(\d+)', p.stem)
                page_label = f"p.{page_match.group(1)}" if page_match else p.stem
                images.append({
                    "url": f"/api/asme-ref/{matched_feature}/{p.name}",
                    "page": page_label,
                })

            refs.append({
                "feature_type": matched_feature,
                "section": checklist.get("asme_reference", ""),
                "rules": matched_rules,
                "common_errors": checklist.get("common_errors", [])[:2],
                "images": images,
            })
        else:
            # Try rag_visual_db/ for topic sections (no checklist)
            rag_path = Path("rag_visual_db") / matched_feature
            if rag_path.exists():
                pngs = sorted(rag_path.glob("*.png"))[:2]
                refs.append({
                    "feature_type": matched_feature,
                    "section": f"ASME Y14.5 — {matched_feature.replace('_', ' ')}",
                    "rules": [],
                    "common_errors": [],
                    "images": [
                        {"url": f"/api/asme-ref/{matched_feature}/{p.name}", "page": p.stem}
                        for p in pngs
                    ],
                })

    return refs
```

**Where to insert:** After `_load_rag_images()`, before `_build_context_message()`.

---

### Step 3: Server — Attach ASME Refs to Inspection Response

**File: server.py — in the POST /api/inspect endpoint response builder**

After inspection results are computed, resolve ASME references for each feature in the flat features list and attach them to the response.

**Important:** The inspection response shape is:
- `results["findings"]` — nested dict from the AI (contains `features` key inside)
- `results["features"]` — flat list extracted as `findings.get("features", [])`, already at the top level

The resolver MUST iterate `results["features"]` (the flat list), NOT `results["findings"]` (the nested dict).

```python
# After building the inspection response dict:
# results["features"] is the flat list: each item has name, status, observation, type
asme_findings = []
seen_features = set()  # deduplicate across findings
for feature in results.get("features", []):
    refs = _resolve_asme_refs_for_finding(feature)
    for ref in refs:
        if ref["feature_type"] not in seen_features:
            seen_features.add(ref["feature_type"])
            asme_findings.append({
                "finding_name": feature.get("name", ""),
                **ref,
            })

if asme_findings:
    response_data["asme_checklist_findings"] = asme_findings
```

This means the inspection response carries structured ASME reference data without any model call. The frontend can render it immediately. References are deduplicated by feature type — if 3 holes are flagged, only one Hole reference is included.

---

### Step 4: Server — Label RAG Images with Source Metadata

**File: server.py — in `_load_rag_images()`**

Add a text label before each image so the model knows which reference it's looking at. This improves model reasoning quality (not required for citations, but makes Iris's answers more grounded).

```python
def _load_rag_images(directories: List[str], max_images: int = 4) -> List[Dict]:
    """Load PNG images from directories as base64 for Claude Vision API.
    Each image is preceded by a text label identifying its source.
    max_images counts actual images, not label+image pairs."""
    content_blocks = []
    image_count = 0
    for dir_path in directories:
        p = Path(dir_path)
        if not p.exists():
            continue
        # Load checklist if available (for section reference)
        checklist_label = ""
        cl_path = p / "checklist.json"
        if cl_path.exists():
            try:
                with open(cl_path, "r", encoding="utf-8") as f:
                    cl = json.load(f)
                checklist_label = cl.get("asme_reference", p.name)
            except Exception:
                checklist_label = p.name
        else:
            checklist_label = p.name.replace("_", " ")

        png_files = sorted(p.glob("*.png"))[:3]
        for png_file in png_files:
            if image_count >= max_images:
                break
            try:
                # Add label before image
                page_match = re.search(r'P(\d+)', png_file.stem)
                page_label = f" (page {page_match.group(1)})" if page_match else ""
                content_blocks.append({
                    "type": "text",
                    "text": f"[Reference: {checklist_label}{page_label} — {p.name}/{png_file.name}]"
                })
                b64 = base64.standard_b64encode(png_file.read_bytes()).decode("utf-8")
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": b64,
                    }
                })
                image_count += 1
            except Exception as e:
                logger.warning(f"Failed to load RAG image {png_file}: {e}")
        if image_count >= max_images:
            break
    return content_blocks
```

**This replaces the existing `_load_rag_images()` at server.py:2212.**

---

### Step 5: Server — Add Prompt Instructions for ASME Reasoning

**File: server.py — Iris system prompt (AGENT_SYSTEM_PROMPT)**

Add after existing scope instructions. Note: Iris does NOT need to emit structured markers. She just needs to reference ASME sections naturally in her text. The structured data comes from the deterministic resolver (Step 2).

```
ASME STANDARD REFERENCES:
When you identify a representation issue, reference the specific ASME Y14.5 section in your response text.
Each reference image sent to you is labeled with its source (e.g., "[Reference: ASME Y14.5-2018, Section 4.12-4.14 (page 41)]").
Use these labels to cite accurately. Example: "The blind hole is missing the depth symbol — per ASME Y14.5 §4.12, blind holes require ↧ followed by the depth value."
Do NOT invent section numbers. Only cite sections from the reference labels provided.
```

---

### Step 6: Server — Attach ASME Refs to Agent Chat Responses

**File: server.py — in the agent response parser, after all other marker parsing**

For ordinary Iris/Sage chat replies, resolve ASME references from the inspection context findings that are already in `ctx`. This uses the same deterministic resolver — no extra API call.

```python
# After all marker parsing (FAI_FILL, ANIMATE_MOTION, etc.), before building result:
asme_refs = []
if request.agent_type != "parts-finder" and ctx:
    seen = set()

    # Priority 1: focused_feature (user selected a specific dimension/finding)
    focused = ctx.get("focused_feature")
    if focused and isinstance(focused, dict):
        f_refs = _resolve_asme_refs_for_finding(focused)
        for ref in f_refs:
            if ref["feature_type"] not in seen:
                seen.add(ref["feature_type"])
                asme_refs.append(ref)

    # Priority 2: user message keywords
    if len(asme_refs) < 3:
        msg_refs = _resolve_asme_refs_for_finding({"observation": request.message})
        for ref in msg_refs:
            if ref["feature_type"] not in seen:
                seen.add(ref["feature_type"])
                asme_refs.append(ref)

    # Priority 3: only findings with representation issues (non-PRESENT status)
    #    NOT the full features list — only gaps/failures
    if len(asme_refs) < 3:
        ctx_findings = ctx.get("findings", [])
        if isinstance(ctx_findings, list):
            for finding in ctx_findings:
                if len(asme_refs) >= 3:
                    break
                status = finding.get("status", "").upper() if isinstance(finding, dict) else ""
                if status in ("MISSING", "PARTIAL", "DISCREPANT"):
                    f_refs = _resolve_asme_refs_for_finding(finding)
                    for ref in f_refs:
                        if ref["feature_type"] not in seen:
                            seen.add(ref["feature_type"])
                            asme_refs.append(ref)

    asme_refs = asme_refs[:3]

if asme_refs:
    result["asme_refs"] = asme_refs
```

**Priority order:**
1. **`focused_feature`** — if the user selected a specific dimension/finding in the UI, cite that
2. **User message keywords** — "is the hole callout correct?" → matches "hole"
3. **Representation gaps only** — only findings with MISSING/PARTIAL/DISCREPANT status, never PRESENT features. A generic "is this correct?" only picks up actual issues, not the full inspection list.

**This is a lightweight keyword lookup, not a model call.** It runs in <1ms.

---

### Step 7: Frontend — Extended Chat Message Shape (renumbered from Step 6)

**File: static/index.html — `addMessage()` function and message rendering**

Extend `addMessage()` to accept optional metadata:

```javascript
// Change from:
//   addMessage(text, role)
// To:
//   addMessage(text, role, metadata)
// where metadata is optional: { asme_refs: [...] }

function addMessage(text, role, metadata) {
    const msg = { role, text };
    if (metadata) msg.metadata = metadata;
    agentConversations[currentAgent].push(msg);
    // ... existing render logic
}
```

In the agent response handler, pass `asme_refs` through:

```javascript
// After getting data from /api/agent/chat:
const msgMeta = {};
if (Array.isArray(data.asme_refs) && data.asme_refs.length > 0) {
    msgMeta.asme_refs = data.asme_refs;
}
addMessage(response, 'assistant', Object.keys(msgMeta).length ? msgMeta : undefined);
```

---

### Step 7: Frontend — Render ASME Reference Links in Chat Bubbles

**File: static/index.html — in the message bubble rendering function**

When rendering an assistant message, check for `msg.metadata?.asme_refs`:

```javascript
// Inside the chat bubble rendering loop, after setting bubble.innerHTML for the message text:
// Click handled by delegated listener on agentMessages — no direct addEventListener.
if (msg.metadata && msg.metadata.asme_refs) {
    const refsDiv = document.createElement('div');
    refsDiv.className = 'asme-refs-row';
    msg.metadata.asme_refs.forEach(ref => {
        const link = document.createElement('a');
        link.href = 'javascript:void(0)';
        link.className = 'asme-ref-link';
        link.textContent = `📖 ${ref.section || ref.feature_type} (${ref.images?.[0]?.page || ''})`;
        link.title = ref.rules?.[0] || '';
        link.dataset.asmeRef = JSON.stringify(ref);
        refsDiv.appendChild(link);
    });
    bubble.appendChild(refsDiv);
}
```

All text is set via `textContent` (not innerHTML) — addresses Codex finding #6 (injection risk).

CSS:
```css
.asme-refs-row {
    margin-top: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}
.asme-ref-link {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 8px;
    background: rgba(79, 195, 247, 0.08);
    border: 1px solid rgba(79, 195, 247, 0.2);
    border-radius: 4px;
    font-size: 11px;
    color: var(--accent) !important;
    cursor: pointer;
    transition: background 0.15s;
    text-decoration: none !important;
}
.asme-ref-link:hover {
    background: rgba(79, 195, 247, 0.15);
}
```

---

### Step 8: Frontend — ASME Popup Viewer (BOM Pattern)

**File: static/index.html**

Floating, draggable, minimizable, closable — identical behavior to BOM overlay.

```javascript
function _showAsmeRefPopup(ref) {
    // Remove existing popup
    const existing = document.getElementById('asmeRefOverlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id = 'asmeRefOverlay';
    overlay.className = 'asme-ref-overlay';

    // Title bar (draggable)
    const titlebar = document.createElement('div');
    titlebar.className = 'asme-ref-titlebar';

    const title = document.createElement('span');
    title.className = 'asme-ref-title';
    title.textContent = ref.section || `ASME Y14.5 — ${ref.feature_type}`;
    titlebar.appendChild(title);

    const btns = document.createElement('div');
    btns.className = 'asme-ref-titlebar-btns';

    const minBtn = document.createElement('button');
    minBtn.textContent = '—';
    minBtn.title = 'Minimize';
    btns.appendChild(minBtn);

    const closeBtn = document.createElement('button');
    closeBtn.textContent = '×';
    closeBtn.title = 'Close';
    btns.appendChild(closeBtn);

    titlebar.appendChild(btns);
    overlay.appendChild(titlebar);

    // Body
    const body = document.createElement('div');
    body.className = 'asme-ref-body';

    // Rule callout
    if (ref.rules && ref.rules.length > 0) {
        const ruleDiv = document.createElement('div');
        ruleDiv.className = 'asme-ref-rule';
        ruleDiv.textContent = ref.rules[0];
        body.appendChild(ruleDiv);
    }

    // Common errors
    if (ref.common_errors && ref.common_errors.length > 0) {
        const errDiv = document.createElement('div');
        errDiv.className = 'asme-ref-errors';
        ref.common_errors.forEach(err => {
            const p = document.createElement('div');
            p.textContent = `✗ ${err}`;
            errDiv.appendChild(p);
        });
        body.appendChild(errDiv);
    }

    // Reference images (page thumbnails → click to enlarge)
    if (ref.images && ref.images.length > 0) {
        ref.images.forEach(img => {
            const imgEl = document.createElement('img');
            imgEl.src = img.url;
            imgEl.alt = `ASME reference ${img.page}`;
            imgEl.style.cssText = 'width:100%;border-radius:4px;margin-top:8px;cursor:pointer;';
            imgEl.addEventListener('click', () => {
                // Open full-size in new tab or lightbox
                window.open(img.url, '_blank');
            });
            body.appendChild(imgEl);
        });
    }

    overlay.appendChild(body);

    // Position
    overlay.style.top = '60px';
    overlay.style.right = '60px';

    const viewport = document.querySelector('.viewport-content') || document.body;
    viewport.appendChild(overlay);

    // Close
    closeBtn.addEventListener('click', () => overlay.remove());

    // Minimize
    minBtn.addEventListener('click', () => {
        body.style.display = body.style.display === 'none' ? 'block' : 'none';
    });

    // Drag (BOM pattern)
    let dragX, dragY;
    titlebar.addEventListener('mousedown', (e) => {
        if (e.target.tagName === 'BUTTON') return;
        dragX = e.clientX - overlay.offsetLeft;
        dragY = e.clientY - overlay.offsetTop;
        const onMove = (ev) => {
            overlay.style.left = (ev.clientX - dragX) + 'px';
            overlay.style.top = (ev.clientY - dragY) + 'px';
            overlay.style.right = 'auto';
        };
        const onUp = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    });
}
```

CSS (uses existing tonal system variables):
```css
.asme-ref-overlay {
    position: absolute;
    top: 60px;
    right: 60px;
    width: 420px;
    max-height: 500px;
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: 6px;
    box-shadow: 0 12px 40px rgba(0,0,0,0.5);
    z-index: 100;
    overflow: hidden;
}
.asme-ref-titlebar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 10px;
    background: var(--bg-tab);
    cursor: grab;
    user-select: none;
    border-bottom: 1px solid var(--border);
}
.asme-ref-titlebar:active { cursor: grabbing; }
.asme-ref-title {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-primary);
}
.asme-ref-titlebar-btns { display: flex; gap: 6px; }
.asme-ref-titlebar-btns button {
    background: none;
    border: none;
    color: var(--text-secondary);
    cursor: pointer;
    font-size: 14px;
    padding: 0 4px;
}
.asme-ref-titlebar-btns button:hover { color: var(--text-primary); }
.asme-ref-body {
    padding: 10px;
    overflow-y: auto;
    max-height: 440px;
}
.asme-ref-rule {
    font-size: 12px;
    color: var(--accent);
    padding: 6px 10px;
    background: rgba(79, 195, 247, 0.06);
    border-left: 3px solid var(--accent);
    border-radius: 0 4px 4px 0;
    margin-bottom: 8px;
    line-height: 1.5;
}
.asme-ref-errors {
    font-size: 11px;
    color: var(--missing);
    padding: 4px 0 8px;
    line-height: 1.6;
}
```

---

### Step 10: Frontend — Post-Inspection ASME Summary (Local Builder)

**File: static/index.html — after inspection results are stored**

No agent API call. The server already attached `asme_checklist_findings` to the inspection response (Step 3). The frontend renders it into Iris's chat — regardless of which agent tab is currently active.

**Architecture constraint:** The chat system caches per-agent HTML in `agentMessagesHtml[agent]` and restores it on agent switch. There is no `renderAgentChat()`. Messages are built incrementally via `addMessage()` which both appends DOM and pushes to `agentConversations[currentAgent]`.

**Solution:** New helper `_addMessageToAgent(agentKey, text, metadata)` that works whether or not the target agent is currently active:

```javascript
function _addMessageToAgent(agentKey, text, metadata) {
    // Push to conversation array
    const msg = { role: 'assistant', text };
    if (metadata) msg.metadata = metadata;
    agentConversations[agentKey].push(msg);

    // Clear welcome message and suggestion chips (same as addMessage)
    if (agentKey === currentAgent) {
        // Active agent — clear from live DOM
        const welcome = agentMessages.querySelector('.agent-welcome');
        if (welcome) welcome.remove();
        removeSuggestions();
    } else {
        // Inactive agent — strip from cached HTML string
        agentMessagesHtml[agentKey] = (agentMessagesHtml[agentKey] || '')
            .replace(/<div class="agent-welcome">[\s\S]*?<\/div>/, '')
            .replace(/<div[^>]*id="agentSuggestionChips"[^>]*>[\s\S]*?<\/div>/, '')
            .replace(/<div[^>]*id="agentSuggestionsLoading"[^>]*>[\s\S]*?<\/div>/, '');
    }

    // Build the DOM element (same structure as addMessage)
    const agent = AGENTS[agentKey];
    const row = document.createElement('div');
    row.className = 'agent-msg-row assistant';

    const avatar = document.createElement('div');
    avatar.className = 'agent-msg-avatar bot-avatar';
    avatar.innerHTML = agent.avatar;
    avatar.style.background = 'transparent';
    avatar.style.border = '2px solid ' + agent.color;

    const content = document.createElement('div');
    content.className = 'agent-msg-content';

    const name = document.createElement('div');
    name.className = 'agent-msg-name';
    name.textContent = agent.name;

    const msgEl = document.createElement('div');
    msgEl.className = 'agent-msg assistant';
    msgEl.innerHTML = formatMessageText(text);

    // Append ASME ref links if present (click handled by delegation, not per-link)
    if (metadata && metadata.asme_refs) {
        const refsDiv = document.createElement('div');
        refsDiv.className = 'asme-refs-row';
        metadata.asme_refs.forEach(ref => {
            const link = document.createElement('a');
            link.href = 'javascript:void(0)';
            link.className = 'asme-ref-link';
            link.textContent = '\uD83D\uDCD6 ' + (ref.section || ref.feature_type) +
                               ' (' + (ref.images?.[0]?.page || '') + ')';
            link.title = ref.rules?.[0] || '';
            link.dataset.asmeRef = JSON.stringify(ref);
            // No direct addEventListener — handled by delegated listener on agentMessages
            refsDiv.appendChild(link);
        });
        msgEl.appendChild(refsDiv);
    }

    content.appendChild(name);
    content.appendChild(msgEl);
    row.appendChild(avatar);
    row.appendChild(content);

    if (agentKey === currentAgent) {
        // Target agent is active — append to live DOM
        agentMessages.appendChild(row);
        agentMessages.scrollTop = agentMessages.scrollHeight;
    } else {
        // Target agent is NOT active — append to cached HTML string.
        // When user switches to this agent, selectAgent() restores
        // agentMessagesHtml[agentKey] into agentMessages.innerHTML.
        agentMessagesHtml[agentKey] += row.outerHTML;
    }
}
```

Usage after inspection:
```javascript
if (state.results.asme_checklist_findings && state.results.asme_checklist_findings.length > 0) {
    const refs = state.results.asme_checklist_findings;
    const summaryText = `Inspection found ${refs.length} ASME representation issue(s). Click any reference to view the standard.`;
    _addMessageToAgent('inspector', summaryText, { asme_refs: refs });
}
```

**Why this works:**
- If user is on Iris: message appears immediately in live DOM
- If user is on Sage/Scout: message is appended to `agentMessagesHtml['inspector']` (the cached HTML string). When user switches to Iris, `selectAgent()` restores this HTML and the message is visible.
- Conversation array always updated regardless of active agent.

**Click handling:** All ASME ref links use `dataset.asmeRef` (no direct `addEventListener`). A single delegated listener on the `agentMessages` container handles all clicks — this works for both live DOM and links restored from cached `agentMessagesHtml` innerHTML:

```javascript
// Once, during setup:
agentMessages.addEventListener('click', (e) => {
    const link = e.target.closest('.asme-ref-link');
    if (link) {
        // Reconstruct ref from data attributes
        const ref = JSON.parse(link.dataset.asmeRef || '{}');
        if (ref.feature_type) _showAsmeRefPopup(ref);
    }
});
```

And when building links, store the ref as a data attribute:
```javascript
link.dataset.asmeRef = JSON.stringify(ref);
```

This way, links work whether they're in live DOM or restored from cached HTML.

---

## File Change Summary

| File | Changes | Lines |
|------|---------|-------|
| server.py | `/api/asme-ref/` endpoint with whitelist | ~25 |
| server.py | `ASME_REF_WHITELIST` constant | ~10 |
| server.py | `FINDING_TO_ASME_FEATURE` mapping | ~35 |
| server.py | `_resolve_asme_refs_for_finding()` function (multi-match, returns list) | ~70 |
| server.py | Attach `asme_checklist_findings` to inspection response (iterates `results["features"]`) | ~15 |
| server.py | Attach `asme_refs` to agent chat responses (keyword lookup on user message) | ~15 |
| server.py | Label RAG images with source metadata (update `_load_rag_images`) | ~15 |
| server.py | Iris prompt: ASME citation instructions | ~5 |
| static/index.html | Extended `addMessage()` with metadata | ~5 |
| static/index.html | ASME ref link rendering in chat bubbles (textContent, no innerHTML) | ~20 |
| static/index.html | `_showAsmeRefPopup()` function (BOM pattern, DOM APIs only) | ~70 |
| static/index.html | Post-inspection ASME summary (posts to Iris convo specifically) | ~10 |
| static/index.html | CSS for refs + popup (uses tonal system variables) | ~50 |
| **Total** | | **~345 lines** |

**No new files. No new dependencies. No new model calls for citations.**

---

## Verification

1. **Load 1020001 (Piston), run inspection**
2. **Check inspection response** — `asme_checklist_findings` array present with matched features
3. **Chat auto-summary** — "Inspection found N ASME representation issues" with clickable links
4. **Click a reference** — popup opens showing ASME standard page image
5. **Popup behavior** — drag, minimize, close all work (same as BOM)
6. **Ask Iris a question** — "is the hole callout correct?" → Iris references ASME section in text
7. **No injection** — test with special characters in finding names
8. **Whitelist** — `/api/asme-ref/../../etc/passwd/foo.png` returns 404

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Finding keywords don't match any ASME feature type | `_resolve_asme_refs_for_finding()` returns None — no reference shown, graceful degradation |
| Checklist rules don't match the specific finding | Fallback: show first 2 required rules from the matched feature type |
| Too many ASME references clutter the chat | Cap at top 5 findings with references. Group by feature type. |
| Popup obscures drawing | Draggable + minimizable, same as BOM |
| RAG images still sent without labels (model can't cite sections) | Step 4 adds text labels before each image. Model can now reference section numbers from labels. |
| Path traversal in `/api/asme-ref/` endpoint | Whitelist check + regex validation on image name |
| `rag_visual_db/` sections have no checklist.json | `_resolve_asme_refs_for_finding()` handles this: returns folder name as section, images without rules |

---

## What Changed from v1

| v1 (rejected) | v2 (this plan) |
|---|---|
| Model emits `ASME_REF:` markers | Server resolves deterministically from findings + checklists |
| Requires prompt to produce exact page numbers | No structured markers needed from model |
| Only `asme_feature_references/` covered | Both `asme_feature_references/` and `rag_visual_db/` covered |
| Chat messages plain text | Chat messages carry optional `metadata.asme_refs` |
| Post-inspection summary via agent API call | Local builder from server-attached data |
| Raw innerHTML interpolation | DOM APIs with textContent, no injection risk |
| No path validation | Whitelist + regex on all path parameters |
