"""Plain-language progress for the chat pane while Sage works on a saved Facility Layout.

Each tool call becomes one step that names what it looks at (a zone, an item, a number
of changes) in words a plant engineer reads, never internal IDs. Text Sage writes
between tool calls is a remark: it joins the step list instead of the final answer.
Display only: nothing here reaches the model or changes a tool result.
"""
from __future__ import annotations

import asyncio
import re

READ = ("Reading", "Read", "read")
CHECK = ("Checking", "Checked", "check")
LOOK_UP = ("Looking up", "Looked up", "look up")
SEARCH = ("Searching", "Searched", "search")
STAGE = ("Staging", "Staged", "stage")
REVIEW = ("Reviewing", "Reviewed", "review")
MEASURE = ("Measuring", "Measured", "measure")
FIND = ("Finding", "Found", "find")
COMPARE = ("Comparing", "Compared", "compare")
PREPARE = ("Preparing", "Prepared", "prepare")
RUN = ("Running", "Ran", "run")

SIMPLE = {
    "inspect_facility_context": (READ, "the layout overview"),
    "inspect_facility_findings": (READ, "layout findings"),
    "inspect_pattern_provenance": (READ, "how equipment patterns were made"),
    "inspect_cell_layout_provenance": (READ, "how work cells were set up"),
    "observe_navigation_context": (READ, "how people and vehicles move"),
    "inspect_saved_process_bindings": (READ, "the process map links"),
    "read_public_source": (READ, "a public source"),
    "inspect_facility_operation_contracts": (READ, "the rules for these edits"),
    "prepare_facility_lettering": (PREPARE, "floor lettering"),
    "preview_facility_undo": (PREPARE, "an undo"),
}
AUTHORING_VIEWS = {
    "placements": "placed equipment", "zones": "zones", "routes": "aisles and routes",
    "utilities": "utility networks", "floor_markings": "floor markings", "interior_walls": "interior walls",
    "floor_surfaces": "floor finishes", "decals": "floor graphics", "plan": "plan settings",
    "ground": "ground levels", "perimeter_walls": "outside walls", "navigation": "navigation settings",
    "wall_artworks": "wall artwork", "overview": "the layout contents",
}
SEMANTIC_VIEWS = {
    "overview": "the layout summary", "departments": "departments", "department_metrics": "department sizes",
    "zones": "zone details", "assets": "equipment roles", "placements": "equipment details",
    "routes": "aisle details", "route_crossings": "aisle crossings", "floor_markings": "floor markings",
    "process_bindings": "process links", "layout_patterns": "equipment patterns",
    "commands": "layout commands", "cell_layout_strategies": "cell layout strategies",
    "derived_metrics": "layout measurements",
}
ENTITY_KINDS = {"placement": "items", "zone": "zones", "floor_marking": "floor markings",
                "route": "aisles", "utility_network": "utility networks"}
ANALYSES = {
    "clearances": (CHECK, "clearances"),
    "protected_intrusions": (CHECK, "walkways for blockages"),
    "route_crossings": (CHECK, "where aisles cross"),
    "free_space": (MEASURE, "free floor space"),
    "layout_provenance": (READ, "how the layout was built"),
    "route_access": (CHECK, "aisle access"),
    "route_widths": (MEASURE, "aisle widths"),
    "cell_alternatives": (COMPARE, "cell arrangements"),
    "module_fit": (CHECK, "how the modules fit"),
    "operator_travel": (MEASURE, "operator walking distances"),
    "asset_access": (CHECK, "access around equipment"),
    "cell_access": (CHECK, "access to work cells"),
    "drone_clearance": (CHECK, "drone clearance"),
    "render_consistency": (CHECK, "that the 3D view matches the plan"),
}
CHANGES = {
    "place_asset": ("new item", "new items"), "duplicate_placement": ("copied item", "copied items"),
    "move_placement": ("move", "moves"), "rotate_placement": ("turn", "turns"),
    "delete_placement": ("removal", "removals"), "replace_asset": ("swap", "swaps"),
    "add_zone": ("new zone", "new zones"), "edit_zone": ("zone change", "zone changes"),
    "add_aisle": ("new aisle", "new aisles"), "edit_aisle": ("aisle change", "aisle changes"),
}
REASONS = {
    "codex_result_too_large": "result too large to read",
    "codex_tool_arguments_invalid": "malformed request",
    "facility_agent_revision_invalid": "malformed request",
    "spatial_validation_failed": "spatial checks failed",
    "codex_tool_budget_exhausted": "step limit reached",
    "codex_tool_denied": "not allowed",
    "codex_document_unavailable": "the layout changed",
}


def _short(value, limit=40):
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    # Zone labels carry notes such as "Receiving (2 truck doors, west wall)".
    text = re.sub(r"\s*\([^()]*\)$", "", text).strip() or text
    text = text.replace('"', "'")
    return (text if len(text) <= limit else text[:limit - 3].rstrip() + "...") or None


def _quoted(value):
    text = _short(value)
    return f'"{text}"' if text else None


def _ids(value):
    return [item for item in value if isinstance(item, str)][:50] if isinstance(value, list) else []


def _index(rows, key, label):
    found = {}
    for row in rows if isinstance(rows, (list, tuple)) else []:
        if isinstance(row, dict) and isinstance(row.get(key), str):
            text = _short(label(row))
            if text:
                found[row[key]] = text
    return found


class LayoutNames:
    """Display names for one saved layout revision and its asset catalog."""

    def __init__(self, layout=None, catalog=()):
        layout = layout if isinstance(layout, dict) else {}
        self.assets = _index(catalog, "assetId", lambda row: row.get("displayName"))
        self.zones = _index(layout.get("zones"), "zoneId", lambda row: row.get("label"))
        self.routes = _index(layout.get("routes"), "routeId", lambda row: row.get("label"))
        self.markings = _index(layout.get("floorMarkings"), "markingId", lambda row: row.get("label"))
        self.placements = _index(layout.get("placements"), "placementId", lambda row: (
            (row.get("metadata") or {}).get("instanceLabel") if isinstance(row.get("metadata"), dict) else None)
            or self.assets.get(row.get("assetId")))

    def zone(self, value):
        return self.zones.get(value) if isinstance(value, str) else None

    def asset(self, value):
        return self.assets.get(value) if isinstance(value, str) else None

    def placement(self, value):
        return self.placements.get(value) if isinstance(value, str) else None

    def any(self, value):
        if not isinstance(value, str):
            return None
        return (self.zones.get(value) or self.placements.get(value) or self.routes.get(value)
                or self.markings.get(value) or self.assets.get(value))


def _named(ids, names):
    """'Offices' or 'Offices and Break Room' when every ID has a name, else None."""
    labels = [names.any(item) for item in ids]
    return " and ".join(labels) if ids and len(ids) <= 2 and all(labels) else None


def _scope(ids, names):
    ids = _ids(ids)
    if not ids:
        return ""
    named = _named(ids, names)
    if named:
        return (" in " if all(names.zone(item) for item in ids) else " around ") + named
    return f" for {len(ids)} selected"


def _listing(noun, args, names, paged=False):
    ids = _ids(args.get("ids"))
    if ids:
        named = _named(ids, names)
        subject = f"{noun}: {named}" if named else f"{noun} ({len(ids)} selected)"
    else:
        query = _quoted(args.get("query"))
        subject = f"{noun} matching {query}" if query else noun
    offset, size = args.get("offset"), args.get("pageSize")
    if paged and type(offset) is int and offset > 0:
        subject += f", items {offset + 1}-{offset + (size if type(size) is int and size > 0 else 10)}"
    elif args.get("cursor"):
        subject += ", more results"
    return subject


def _spatial(args, names):
    analysis = args.get("analysis")
    if analysis == "resolve_entities":
        query = _quoted(args.get("query"))
        if query:
            return FIND, f"{query} in the layout"
        return FIND, "the selected items" if args.get("useCurrentSelection") else "the items you named"
    verbs, subject = ANALYSES.get(analysis, (CHECK, "the layout"))
    sources, targets = _named(_ids(args.get("sourceZoneIds")), names), _named(_ids(args.get("targetZoneIds")), names)
    if sources and targets:
        return verbs, f"{subject} between {sources} and {targets}"
    scope = _scope(args.get("scopeIds"), names)
    if not scope and _quoted(args.get("query")):
        scope = f" for {_quoted(args.get('query'))}"
    return verbs, subject + scope


def _changes(operations):
    rows = [item for item in operations if isinstance(item, dict)] if isinstance(operations, list) else []
    if not rows:
        return "changes"
    counts = {}
    for row in rows:
        noun = CHANGES.get(row.get("op"))
        counts[noun] = counts.get(noun, 0) + 1
    if None not in counts and len(counts) <= 2:
        return " and ".join(f"{count} {noun[0] if count == 1 else noun[1]}" for noun, count in counts.items())
    return f"{len(rows)} change" + ("" if len(rows) == 1 else "s")


def _step(name, args, names, edit_mode):
    if name in SIMPLE:
        return SIMPLE[name]
    if name == "inspect_facility_authoring":
        return READ, _listing(AUTHORING_VIEWS.get(args.get("view"), "layout records"), args, names, paged=True)
    if name == "inspect_facility_semantics":
        return READ, _listing(SEMANTIC_VIEWS.get(args.get("view"), "layout details"), args, names)
    if name == "inspect_facility_entities":
        plural = ENTITY_KINDS.get(args.get("entityKind"), "records")
        ids = _ids(args.get("ids"))
        return READ, _named(ids, names) or (f"{len(ids)} {plural}" if ids else plural)
    if name == "inspect_facility_region":
        if args.get("regionKind") == "zone":
            zone = names.zone(args.get("regionId"))
            return READ, f"the {zone} zone" if zone else "a zone"
        return READ, "a building feature"
    if name == "analyze_facility_spatial":
        return _spatial(args, names)
    if name == "analyze_facility_fit":
        item = (names.asset(args.get("assetId")) or _quoted(args.get("assetQuery"))
                or names.placement(args.get("sourcePlacementId"))
                or ("the selected item" if args.get("useSelectedPlacement") else "an item"))
        zone = names.zone(args.get("zoneId")) or _quoted(args.get("zoneQuery"))
        return CHECK, f"where {item} fits" + (f" in {zone}" if zone else "")
    if name == "inspect_facility_asset":
        return LOOK_UP, names.asset(args.get("assetId")) or "a library item"
    if name == "inspect_facility_components":
        item = names.placement(args.get("placementId"))
        return READ, f"the parts of {item}" if item else "an item's parts"
    if name == "review_facility_parking":
        return REVIEW, "parking" + _scope(args.get("zoneIds"), names)
    if name == "review_facility_workstations":
        return REVIEW, "workstations" + _scope(args.get("zoneIds") or args.get("processZoneIds"), names)
    if name == "search_industrial_assets":
        category = _short(args.get("category"))
        target = _quoted(args.get("query")) or (f"{category} items" if category else None)
        subject = f"the library for {target}" if target else "the equipment library"
        return SEARCH, subject + (", more results" if args.get("cursor") else "")
    if name == "search_public_sources":
        query = _quoted(args.get("query"))
        return SEARCH, f"public sources for {query}" if query else "public sources"
    if name == "preview_facility_operations":
        return STAGE, _changes(args.get("operations")) + (" for your review" if edit_mode == "preview" else "")
    return RUN, "a layout check"


def describe(name, arguments, names=None, edit_mode=None):
    """Running, done and failed wording for one tool call."""
    try:
        verbs, subject = _step(name, arguments if isinstance(arguments, dict) else {},
                               names or LayoutNames(), edit_mode)
    except Exception:  # noqa: BLE001 -- unexpected argument shapes fall back to generic wording
        verbs, subject = RUN, "a layout check"
    running, done, base = verbs
    return {"running": f"{running} {subject}", "done": f"{done} {subject}", "failed": f"Couldn't {base} {subject}"}


def failure_reason(code):
    return REASONS.get(code)


def _remark(text, limit=300):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


class TurnProgress:
    """One turn's steps for the chat pane.

    The runtime reports each tool start in order with its streamed text, so text that
    arrived before a start is a remark, not part of the answer. The tool gateway hears
    of the same call over a separate channel, so it waits briefly for the runtime's
    report before showing the step; a remark then precedes the step it led to.
    """

    RUNTIME_WAIT_SECONDS = 0.25

    def __init__(self, step_sink, *, text_sink=None, status_sink=None, names=None, edit_mode=None):
        self.step_sink, self.text_sink, self.status_sink = step_sink, text_sink, status_sink
        self.load_names, self.edit_mode, self.names = names, edit_mode, None
        self.last_id = 0
        self.pending, self.segments, self.remarks = [], [], []
        self.runtime_starts = self.gateway_starts = 0
        self.started = asyncio.Event()

    async def text(self, delta):
        """Text sink for the runtime: streams on and remembers the current segment."""
        self.pending.append(delta)
        if self.text_sink:
            await self.text_sink(delta)

    async def status(self, phase):
        """Status sink for the runtime: a tool start ends the current text segment."""
        if phase in ("codex_inspecting", "codex_researching"):
            segment = "".join(self.pending)
            self.pending = []
            self.segments.append(segment)
            if segment.strip():
                self.remarks.append(_remark(segment))
            self.runtime_starts += 1
            self.started.set()
        if self.status_sink:
            await self.status_sink(phase)

    async def tool_started(self, name, arguments):
        self.gateway_starts += 1
        await self._runtime_caught_up(self.gateway_starts)
        await self._show_remarks()
        if self.names is None:
            self.names = await self._load_names()
        labels = describe(name, arguments, self.names, self.edit_mode)
        step = self._next_id()
        await self.step_sink({"id": step, "kind": "tool", "state": "running", "label": labels["running"]})
        return step, labels

    async def tool_finished(self, started, result):
        step, labels = started
        if result.get("ok"):
            await self.step_sink({"id": step, "kind": "tool", "state": "done", "label": labels["done"]})
            return
        reason = failure_reason((result.get("error") or {}).get("code"))
        await self.step_sink({"id": step, "kind": "tool", "state": "failed",
                              "label": labels["failed"] + (f" ({reason})" if reason else "")})

    async def finish(self, answer):
        """Show any remaining remarks and return the answer without them."""
        await self._show_remarks()
        if not any(segment.strip() for segment in self.segments):
            return answer
        tail = "".join(self.pending).strip()
        return tail or "\n\n".join(segment.strip() for segment in self.segments if segment.strip())

    def _next_id(self):
        self.last_id += 1
        return self.last_id

    async def _runtime_caught_up(self, count):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.RUNTIME_WAIT_SECONDS
        while self.runtime_starts < count:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            self.started.clear()
            try:
                await asyncio.wait_for(self.started.wait(), remaining)
            except TimeoutError:
                return

    async def _show_remarks(self):
        while self.remarks:
            await self.step_sink({"id": self._next_id(), "kind": "remark", "state": "done",
                                  "label": self.remarks.pop(0)})

    async def _load_names(self):
        if not self.load_names:
            return LayoutNames()
        try:
            return await asyncio.to_thread(self.load_names)
        except Exception:  # noqa: BLE001 -- names only improve the wording
            return LayoutNames()
