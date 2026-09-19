# Task: render generation research results as clickable source cards

Written 2026-09-19 for the next Codex session. Scope is one wiring gap, not a
new subsystem. Everything this task depends on already exists and works; do not
rebuild any of it.

## Goal

When Sage runs `search_generation_sources` or `read_generation_source` in the
Facility Layout generation workflow, the retained sources must appear in the
chat pane as source cards whose links open in the in-app research browser.

Today those citations are returned inside the tool result only. They never
reach the chat renderer, so the user cannot click them.

## What already works - do not re-implement

The click path is complete end to end. The only missing piece is that the
generation workflow never emits the block that feeds it.

1. **Renderer.** `static/chat_rich_content.js` `renderSources()` (line 566)
   builds source cards with real anchors: title link, a "View source" link and
   up to four extra links, each `target="_blank" rel="noopener noreferrer"`.
2. **Desktop interception.** `desktop/src/application-links.cjs`
   `installApplicationLinks()` catches `target="_blank"` through
   `setWindowOpenHandler`, classifies the URL, and routes an external HTTPS
   address to `'browser'`, which opens the research pane. It is wired with a
   real `openBrowser` and `isDocument` at `desktop/src/application-main.cjs:179`.
3. **PDF handling.** `desktop/src/document-preview.cjs` sniffs the `%PDF-`
   magic bytes and overrides a wrong `content-type`, serves under a locked CSP,
   and bounds the body by `MAX_BYTES`. Download, `trackDownload` and
   `cancel-downloads` all exist in `desktop/src/research-pane.cjs`.
4. **Block schema and normalizer.** `ai_inspector/chat_content.py` already
   defines the `sources` block and `_normalize_source`.
5. **Reference implementation.** The Documentation workflow already does this.
   Grep `static/index.html` for `badge.href = String(citation.url)` (line 37386
   as of 2026-09-19), which builds anchor badges from `sourceCitations`. Copy
   that pattern rather than inventing one.
6. **Response assembly.** `server.py` already attaches rich blocks and already
   handles the generation turn in the same place:
   - `server.py:40802` calls `extract_chat_presentation_blocks()` to build
     `_rich_content_blocks` from presentation tool calls.
   - `server.py:41244-41245` is `if _rich_content_blocks:` followed by
     `result["content_blocks"] = _rich_content_blocks`.
   - `server.py:41250` is the `if ctx.get("_facility_generation_binding"):`
     branch, five lines later. It reads
     `ctx["_facility_generation_outcome"]` (the `generation_turn_outcome()`
     result) and sets `result["facility_generation_planning"]`. It clears
     `result["tool_calls"]` but does **not** clear `content_blocks`, so a block
     attached above survives.
   - `normalize_chat_response_payload()` runs at `server.py:43258`, `43582`
     and `44375`.

   Line numbers are accurate as of commit `a442754` plus the UI commit that
   follows it. `static/index.html` in particular shifts often -- prefer the
   quoted code strings over the numbers when they disagree.

## The two contracts

### What research returns

`ai_inspector/research/web.py` `normalize_response()` produces, per source:

```python
{"url": address, "title": "...", "pageAge": ..., "retrieval": "search_result" | "fetched_document"}
```

and at the top level: `retrievedAt`, `citations` (each `{url, text, locator}`),
`summary`, `truncated`, `errors`, `resultRevision`, plus the fixed
`authority: "supporting"`, `reviewStatus: "pending"`,
`productionEligible: False`.

### What the chat block accepts

`normalize_chat_content_block()` (`ai_inspector/chat_content.py:316`) accepts:

```python
{"type": "sources", "title": "...", "sources": [...]}
```

`_normalize_source()` (line 141) requires only `url`; everything else is
optional with fallbacks. Bounds: 20 sources per block, 24 blocks per response,
4 links and 8 specifications per source. `sourceType` must be one of
`manufacturer`, `supplier`, `standard`, `technical-document`, `web`, and
silently falls back to `web` when unrecognized.

### Mapping

| Card field | Source | Note |
| --- | --- | --- |
| `url` | source `url` | Required. Already validated by `public_url()`. |
| `title` | source `title` | Already bounded to 240. |
| `domain` | omit | `_domain(url)` derives it. |
| `retrievedAt` | top-level `retrievedAt` | Per-result, not per-source. |
| `sourceType` | derive | `technical-document` when `retrieval == "fetched_document"`, otherwise `web`. |
| `description` | matching citation `text` | First citation whose `url` matches. |
| `id` | source index or `resultRevision` prefix | Must be stable across a turn. |
| `publisher` | **leave empty** | Not carried by `web.py`. See non-goals. |

## Work

**Derive the block from retained receipts. Do not add a presentation tool for
it.** `extract_chat_presentation_blocks()` exists so the model can author
charts and tables by calling a tool. Sources must not work that way: the URLs
and titles already exist in the retained research result, and letting the model
author the card would let it retitle a source or invent a publisher. Build the
block from the receipt, not from model output.

1. Retain the research sources on the turn context where the generation
   outcome is already retained. `server.py:41251` reads
   `ctx["_facility_generation_outcome"]`; add a sibling (for example
   `ctx["_facility_generation_sources"]`) populated wherever the generation
   tool results are collected. `generation_turn_outcome()`
   (`ai_inspector/facility_layout/generation_agent.py:40`) receives every
   `results` entry with its `tool` name and `result` payload, so both
   `search_generation_sources` and `read_generation_source` receipts are
   reachable there and it can return the collected sources alongside
   `status`/`blockers`/`response`.
2. Build one `sources` block per turn. De-duplicate by URL across all research
   calls in the turn, preserving first-seen order so cited sources stay ahead of
   unused search hits - `web.py` already orders them that way, so do not re-sort.
3. Merge it into `result["content_blocks"]` at `server.py:41244`. Note that
   line is guarded by `if _rich_content_blocks:`, so a sources block must
   either be appended to `_rich_content_blocks` before the guard or the guard
   must also account for it. A turn can legitimately carry a chart or table
   block as well; do not overwrite them.
4. Confirm the payload still passes through
   `normalize_chat_response_payload()` (`ai_inspector/chat_content.py:435`,
   called at `server.py:43258`, `43582`, `44375`). It accepts `contentBlocks`
   or `content_blocks` and emits normalized `content_blocks`.
5. Verify in the running desktop app that a card link opens the research pane
   rather than the OS browser, and that a PDF link reaches the preview and can
   be downloaded from there.

## Non-goals and constraints

- **Do not build a bridge from the browser back to Sage.** Sage fetches
  provider-side; the pane is human-side. Keeping them separate is what stops
  the pane's logged-in cookies from reaching the model. This separation is
  deliberate. Do not add a content-extraction command to the research pane.
- **Do not invent `publisher`, `manufacturer` or `partNumber`.** `web.py` does
  not carry them. Deriving a publisher from a domain is fabricated provenance.
  Leave the field empty and let the card show the domain.
- **Do not change the research authority fields.** Cards must not imply review.
  `authority: "supporting"`, `reviewStatus: "pending"` and
  `productionEligible: False` stay as they are, and the block must not present a
  source as approved evidence.
- **Do not let a source title or citation text become an instruction.** It is
  untrusted text rendered as content, exactly as `web.py`'s system prompt
  already states.
- **Do not weaken `desktop/src/research-policy.cjs`.** HTTPS-only, port 443,
  public IPv4, no credential URLs, and `x-inspectorpro-*` header stripping all
  stay.
- **Do not construct a URL that did not come from a retained result.** The
  existing `sourceIndex` design in `read_generation_source` exists precisely so
  the model cannot invent an address; the cards must honor the same rule.
- Do not change the Electron binary, the backend timeout, any security setting,
  or the manual reference layout.

## Acceptance

1. A generation turn that calls `search_generation_sources` returns a
   `content_blocks` entry of type `sources` whose every URL appears in the
   retained result for that turn.
2. A turn with no research calls returns no `sources` block, not an empty one.
   `normalize_chat_content_block` already returns `None` for an empty list;
   confirm nothing upstream emits a stub.
3. Clicking a card link in the desktop app opens the in-app research pane.
   Capture a screenshot.
4. A PDF source opens in the document preview and downloads. Capture a
   screenshot.
5. A turn that also produces a chart or table still returns those blocks
   alongside the sources block, not instead of them.
6. Python and Node suites pass. Record counts in the report.
   `tests/test_chat_content.py` is the existing block-normalization suite and
   is the right place for the mapping tests.
7. Report what was verified live versus locally. Do not claim a live
   research-to-card pass from a mocked researcher.

## UI changes landed 2026-09-19 -- read before editing the chat composer

Three changes went into `static/index.html` after the `a442754` checkpoint. None
of them touch the generation pipeline, but two of them establish rules this task
must not break.

1. **Sage is now the default agent.** A new `DEFAULT_AGENT_KEY` constant (near
   the top of the main script block, beside `PM_CARD_TOOLBAR`) holds
   `'deviation-analyst'`, and the 17 conversation-creation and restore sites
   that previously hardcoded `'inspector'` now read from it. The registry role
   also changed from `Deviation Impact` to `Manufacturing & Quality` to match
   the server's Sage skill prompt.

   **Internal agent keys were deliberately NOT renamed.** `deviation-analyst`,
   `inspector` and `parts-finder` are persisted in the chat registry as
   `agentType` and key `agentSessionId`, so renaming them breaks restore of
   saved conversations. `server.py`'s `_SKILL_PUBLIC_TO_INTERNAL_AGENT` still
   maps the public names onto these keys. Do not "tidy" this.

2. **Agent display names come from the `AGENTS` registry only.** The composer
   placeholder previously hardcoded `Message Iris...` in the markup, which went
   stale whenever a Sage or Scout conversation was restored -- the boot restore
   path set `currentAgent` but never re-synced the placeholder. That path now
   calls `_syncAgentInputPlaceholder()`, and the markup names no agent. If this
   task adds any user-visible agent name, resolve it through
   `AGENTS[currentAgent].name`; never write a name into markup or a literal.

3. **The composer has a first-focus edge animation.** `.agent-composer-shell`
   gained a `::before` conic-gradient ring driven by an `@property`-registered
   `--agent-edge-angle`, shown once per page load via an `agent-edge-sweep`
   class added on first focus and removed after 2400 ms. It is cosmetic and
   independent of this task; just be aware that `.agent-composer-shell` now has
   a `::before` and a `z-index: 1` on it, so any new overlay in the composer
   needs to account for that stacking.

## Relationship to the open gates

This does not close any gate in
`docs/sage-research-layout-implementation-report.md`. It is presentation
wiring, and it should be reported that way. It does make gate 1 easier to
observe, because a reviewer can see which sources a turn actually consulted
without reading `.runtime/` receipts.

Note separately that `source_consulted` proves consultation, not applicability.
Rendering a card does not change that, and it must not be described as if it
does.
