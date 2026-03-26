# Scout Supplier API Integration Plan
**Status: Codex-approved after 5 review rounds (2026-03-24)**

## Problem
Scout currently uses Playwright-based web scraping (`ai_inspector/search/browser_engine.py`) to search supplier websites. Most supplier sites block headless browsers — McMaster blocks entirely, Bing returns 0 links, Misumi/MSC/Grainger show captchas. Phases 7-9 exist purely as time-padding. The 90-120 second search often yields fewer than 4 usable results.

## Solution
Replace unreliable web scraping with direct API calls to established mechanical engineering supplier APIs. Browser search becomes fallback only.

## Target APIs

| Supplier | API | Auth | Status |
|----------|-----|------|--------|
| McMaster-Carr | REST API (https://www.mcmaster.com/help/api/) | Client certificate (mTLS) | Access requested via eprocurement@mcmaster.com |
| TraceParts | REST API (https://developers.traceparts.com) | API key → token flow | API key requested via developer portal |
| Misumi | REST API (api.us.misumi-ec.com) | API key | Not yet requested |

## Architecture

### Module Structure
```
ai_inspector/search/
    __init__.py                     (existing — add SupplierAPIRouter export)
    browser_engine.py               (existing — unchanged, becomes fallback)
    supplier_apis/
        __init__.py                 (SupplierAPIRouter)
        base.py                     (BaseSupplierAPI abstract interface)
        traceparts.py               (TraceParts adapter)
        mcmaster.py                 (McMaster-Carr adapter)
        misumi.py                   (Misumi adapter)
```

### SupplierAPIRouter
Mirrors the existing `BrowserSearchEngine` contract exactly:
```python
class SupplierAPIRouter:
    @property
    def ready(self) -> bool: ...          # backward-compatible

    @property
    def parts_search_ready(self) -> bool: ...  # True if any API OR browser up

    @property
    def vendor_search_ready(self) -> bool: ... # True if browser up

    async def start(self): ...
    async def stop(self): ...
    async def search_parts(self, query: str, sites: list = None) -> AsyncGenerator[SearchEvent, None]: ...
    async def search_vendors(self, query: str, service_type: str = "") -> AsyncGenerator[SearchEvent, None]: ...
```

### BaseSupplierAPI
```python
class BaseSupplierAPI:
    name: str                    # "TraceParts", "McMaster-Carr"
    domain: str                  # "traceparts.com"
    keys: list[str]              # ["traceparts", "traceparts.com"] — for sites filtering

    async def search(self, query: str) -> AsyncGenerator[SearchEvent, None]:
        """Yield navigate, reading, reading_content, search_results, result events.
        Do NOT yield search_start or search_complete — the router owns those."""

    async def is_available(self) -> bool: ...
    def matches_query(self, query: str) -> float: ...  # 0.0-1.0 relevance
```

Import and reuse `SearchEvent` and `PartResult` directly from `browser_engine.py` — no parallel definitions.

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Routing | Deterministic (parallel all APIs) | 1-3s API calls make parallel cheap, no Claude round-trip needed |
| Tool schema | Keep existing two tools | No prompt/frontend changes |
| Event format | Same SearchEvent types | Zero changes to server.py SSE or frontend |
| Browser engine | Fallback only | Keeps working for vendor search + uncovered suppliers |
| Lifecycle events | Router owns search_start/search_complete | Adapters only emit mid-stream events |
| Dedup | Before yield, two-set model | Preview URLs and result keys tracked separately |

## Search Flow (search_parts)

### Router owns lifecycle:
```python
async def search_parts(self, query, sites=None):
    start_time = time.time()
    result_count = 0

    yield SearchEvent(type="search_start", data={"query": query})

    # ... queue-based streaming from parallel adapters ...
    # ... browser fallback if result_count < MIN_GOOD_RESULTS ...

    yield SearchEvent(type="search_complete", data={
        "total_results": result_count,
        "duration_ms": int((time.time() - start_time) * 1000)
    })
```

### Queue-based parallel streaming with timeout/cancellation:
```python
queue = asyncio.Queue()
tasks = []

async def _run_adapter(api):
    try:
        async with asyncio.timeout(15):  # 15s hard timeout per adapter
            async for event in api.search(query):
                await queue.put(event)
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"[Scout] Adapter {api.name} failed: {e}")
    finally:
        await queue.put(None)  # sentinel always pushed

for api in available_apis:
    tasks.append(asyncio.create_task(_run_adapter(api)))

try:
    while done_count < total:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=20)
        except asyncio.TimeoutError:
            break
        if event is None:
            done_count += 1
            continue
        # Dedupe + yield (see below)
        yield event
finally:
    for t in tasks:
        if not t.done():
            t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
```

Three layers of protection:
- Per-adapter: `asyncio.timeout(15)` kills any adapter after 15 seconds
- Queue read: `asyncio.wait_for(queue.get(), timeout=20)` breaks stream if nothing arrives
- Cleanup: `finally` block cancels all surviving tasks

### Sites filtering with adapter keys:
```python
if sites:
    sites_lower = {s.lower() for s in sites}
    available_apis = [
        api for api in available_apis
        if any(k in sites_lower or any(k in s for s in sites_lower) for k in api.keys)
    ]
```

### Deduplication before yield (two-set model):
```python
seen_preview_urls = set()   # for search_results items (cosmetic only)
seen_result_keys = set()    # for result events (actual dedup)

# search_results: dedupe previews against OTHER previews only
# result: dedupe against OTHER results only — previews don't block results
# Bundle-level: suppress navigate/reading/reading_content if result is duplicate
```

Preview URLs do NOT prevent later result events for the same URL.

### Event payload compatibility:
All adapters emit events with full payload shapes matching frontend expectations:
- `search_results`: `{"items": [{"title", "url", "favicon", "site_name", "domain"}]}`
- `navigate`: `{"url", "favicon", "site_name", "status"}`
- `reading`: `{"title"}`
- `reading_content`: `{"narration"}`
- `result`: full `PartResult.to_dict()` shape

### Vendor search stays browser-based:
```python
async def search_vendors(self, query, service_type=""):
    if self._browser_engine:
        async for event in self._browser_engine.search_vendors(query, service_type):
            yield event
```

## TraceParts Auth Flow
1. Request API key through approval process
2. Call `POST /v2/RequestToken` with API key to get session token
3. Use session token as bearer auth on search requests
4. Handle token expiration and refresh

**Validation gate:** Before implementing the adapter, verify TraceParts supports free-text product search (not just part-number lookup). If not, swap Phase 2 to Misumi.

## Server.py Changes (Minimal)

### Startup:
```python
from ai_inspector.search.supplier_apis import SupplierAPIRouter
search_engine = SupplierAPIRouter()
await search_engine.start()
```

### Tool gating:
- `web_search_parts` offered when `search_engine.parts_search_ready`
- `web_search_vendors` offered when `search_engine.vendor_search_ready`

### SSE handler: Zero changes — same event types, same pipeline.

### New env vars:
```
MCMASTER_CERT_PATH=/path/to/cert.pem
MCMASTER_KEY_PATH=/path/to/key.pem
TRACEPARTS_API_KEY=your_key_here
MISUMI_API_KEY=your_key_here
```

## Implementation Sequence

| Phase | Work | Timeline | Dependency |
|-------|------|----------|------------|
| 1. Foundation | Module structure, router, server.py wiring | 1 week | None |
| 2a. Validate TraceParts | Test if free-text search is supported | 1-2 days | API key approval |
| 2b. First adapter | TraceParts (if viable) or Misumi (if not) | 3-5 days | Phase 2a |
| 3. Second adapter | Misumi or TraceParts (whichever wasn't Phase 2b) | 3-5 days | Phase 2b |
| 4. McMaster-Carr | Highest value, longest lead time | 1-2 weeks | API approval |
| 5. Vendor DB | Load xlsx, enrich results, tag in-house | 3-5 days | Phase 1 |
| 6. Tuning | Speed, remove dead Bing phases, trim MIN_DURATION | 2-3 days | Phase 2b+ |

## No Changes Required
- Frontend (`static/index.html`) — zero changes
- Scout prompt in `server.py` — same tools, same behavior
- Server SSE handler — same event pipeline
- `BrowserSearchEngine` — stays as fallback, unchanged

## Codex Review History
- Round 1: Direction approved, 6 findings (contract mismatch, auth, gather, payloads, readiness, models)
- Round 2: 4 findings (timeout, TraceParts viability, search_results items, dedup placement)
- Round 3: 4 findings (lifecycle ownership, preview/result dedup split, sites contract, bundle dedup)
- Round 4: 2 findings (lifecycle payloads, sites alias keys)
- Round 5: No findings — implementation-ready
