# Library Intake Wizard — plan

**Status:** plan only. No source-code changes proposed by this document. Implementation requires explicit go-ahead per the project assistant rules in `CLAUDE.md`.

**Purpose:** specify a guided, safe, review-before-commit workflow that promotes SOLIDWORKS-extracted drawing and part data into the canonical InspectorPro library, replacing the implicit multi-step procedure that exists today as informal convention.

**Companion documents:**
- `docs/bridge-part-assembly-app-integration-plan.md` — Phase A/B/C bridge integration plan (the wire layer the wizard sits on top of).
- `docs/production-pilot-packaging-checklist.md` — pilot ops + non-promises (the wizard explicitly does not break any non-promise listed there).
- `docs/solidworks-bridge.md` — bridge operational notes.

**Hard boundaries (restated from user direction):**
- Planning only — no code yet.
- No bridge / add-in / installer changes.
- No FEA / motion / CAD write-back.
- No new feature promises beyond what's in §3 (MVP cut).
- No automatic generation of a **full** inspection profile. The wizard MAY write a clearly-marked incomplete **stub** profile so newly-added parts are discoverable in `/api/profiles` without claiming inspection readiness — see §5.7. The corresponding **consumer-side stub-awareness** (a "Profile incomplete" UI badge + an Inspect button that disables or fails fast with a clear message) ships in the same MVP as the wizard backend, NOT as a follow-up — see §5.7 + §9.5 + §11.

---

## 1. Current fragmented workflow

Today, getting a new part-revision into the library requires the operator to execute six implicit steps in a specific order, with no UI guiding them and no preview of what will land where. Each step is sound; the *fragmentation* is the problem.

### 1.1 The six implicit steps today

| # | Step | Where it happens today | Outcome on disk |
|---|---|---|---|
| 1 | Drawing extraction via bridge | `POST /api/request-extraction` → `_drive_extraction` (server.py:678ff) | `400S_Sorted_Library\{pn}_drawing_map.json` + `{pn}_drawing.pdf` at library ROOT |
| 2 | Part extraction via bridge | `POST /api/request-part-extraction` → `_drive_part_extraction` | `400S_Sorted_Library\_bridge_imports\part\{pn}\{packageId}\` sidecar |
| 3 | Assembly extraction via bridge | `POST /api/request-assembly-extraction` → `_drive_assembly_extraction` | `400S_Sorted_Library\_bridge_imports\assembly\{id}\{packageId}\` sidecar |
| 4 | Per-revision file curation | **Manual** — operator drops files into `parts\{pn}\rev{X}\` | Per-revision files: `{pn}.json`, `{pn}_inspection_profile.json`, `{pn}.STL`, `{pn}_colored.glb`, view PNGs, `{pn}_feature_colors.json`, `{pn}_dimension_descriptions.json`, `{pn}_highlight_boxes.json`, optionally `{pn}_drawing_map.json` |
| 5 | Root-level profile registration | **Manual** — operator drops `{pn}_inspection_profile.json` at library root | Visible to `/api/profiles` after a server restart |
| 6 | Profile / search index refresh | **Server restart** — `_build_profile_index()` runs once at startup (engine.py:294) | `list_profiles()` returns the new entry |

### 1.2 Why this is fragmented in practice

- **Two storage shapes coexist.** Drawing extraction lands at library root (`{pn}_drawing_map.json`). Part/assembly extractions land under `_bridge_imports/{kind}/{pn}/{packageId}/`. Manual curation lands under `parts/{pn}/rev{X}/`. Nothing ties these three locations together for a given (part, revision) tuple.
- **The 8-step manual workflow isn't written down.** Memory and prior comments reference a `LIBRARY_ENTRY_GUIDE.md`; that file **does not exist in the repo today** (verified). The implicit workflow lives in operator muscle memory + the structure of populated parts like `parts\1020001\revA\`.
- **No preview.** The operator finds out what went wrong after copying files and restarting the server — at which point partial state is already on disk.
- **No revision atomicity.** Drawing extraction overwrites `{pn}_drawing_map.json` at root with `.bak` rollback (server.py:835–911), but the per-revision files in `parts\{pn}\rev{X}\` are copied by hand with no atomic guarantees.
- **No visibility into bridge sidecars.** A part extracted via the bridge sits in `_bridge_imports/part/{pn}/{packageId}/` as raw JSON. Nothing surfaces it as "ready to promote".
- **Profile/search visibility lags.** A newly-added profile requires a server restart to appear in `/api/profiles` because `_build_profile_index()` only runs at init (engine.py:294–319; cached in `self._profiles_cache`).

### 1.3 Concrete evidence the fragmentation costs us

- **Mixed per-revision shapes today.** `parts\1015003\revA\` has only `{pn}_colored.glb` + `{pn}_feature_colors.json`. `parts\1020001\revA\` has the full set including `{pn}_inspection_profile.json` and view PNGs. `parts\1030001\revA\` is geometry-only. Same `parts/{pn}/rev{X}/` shape, wildly different completeness — because each was curated by hand, in different sessions, without a single source of truth for "what does a complete revision look like".
- **Debug artifacts leaking into revisions.** `parts\1020001\revB\` contains `{pn}_drawing_map_before_stage8.json`, `{pn}_drawing_map_candidate.json`, `{pn}_drawing_map_extracted_raw_incomplete.json` — intermediate extraction artifacts that should have stayed in staging.
- **`_batch_index.json` is dead** at library root (the original 2026-02-12 batch ingestion catalog) — proof that we tried a manifest once, then stopped maintaining it because nothing read it.

---

## 2. Wizard goal

Turn extracted bridge data into a **canonical library entry** for a single (part, revision) tuple, in a guided UI that lets the operator preview every file that will be created before any disk write happens.

**Specifically:**
- The operator never types a copy command, never opens File Explorer to move files, never restarts the server.
- The operator can abort at any step before the "promote" click; nothing under `parts/{pn}/rev{X}/` is touched until that click.
- After promote, the new revision is visible to the rest of the app within the same session (no restart).
- Failure during promote leaves the library in the same state it was before the wizard started.

**Non-goals for the wizard itself:**
- It does not invent missing files. If the bridge cannot produce a part package because no part is open in SOLIDWORKS, the wizard says so and stops — it does not synthesize a placeholder.
- It does not modify SOLIDWORKS data. Strictly read-only, same as the existing extraction path.
- It does not "fix" pre-existing curated revisions. Migration of historical `parts/{pn}/rev{X}/` directories to the canonical wizard shape is explicitly out of scope (see §10).

---

## 3. MVP cut

**Scope locked for v1:** part + drawing intake for a **single** (part, revision) tuple, with the operator providing both the SOLIDWORKS active doc (drawing first, then part) and the metadata (partNumber, revision, new-vs-existing).

### 3.1 In scope

- Drawing extraction via the existing `/api/request-extraction` endpoint.
- Part extraction via the existing `/api/request-part-extraction` endpoint.
- Sidecar promotion from `_bridge_imports/part/{pn}/{packageId}/` into `parts/{pn}/rev{X}/`.
- Drawing-map promotion from the existing root-level `{pn}_drawing_map.json` into `parts/{pn}/rev{X}/`, with the root-level copy preserved for backward compat (see §10).
- `intake_manifest.json` per revision recording what was promoted, when, and from which `packageId`.
- Refresh hook so the new revision is visible to `/api/profiles` and `/api/profile-details/{pn}` within the same session.

### 3.2 Out of scope for MVP

- Assembly intake. Assemblies have a separate top-level (`assemblies/{id}/`), separate metadata schema (`{id}_assembly.json`), separate BOM file (`{id}_bom_row_highlights.json`), and are loaded into separate globals (`assembly_part_lookup`, `assembly_profiles` — server.py:181–246). Treating them in the same wizard would conflate two unlike workflows. Plan for a v2 (see §12).
- Batch intake. The operator drives one (part, revision) tuple at a time. The same single-flight `_request_extraction_lock` (server.py:498) that gates bridge calls applies.
- CAD write-back. Bridge is read-only by design.
- FEA / motion / kinematics import. Out of bounds.
- **Real (full) inspection-profile generation.** Inspection profiles encode *which* features are critical, *which* dimensions to inspect, what tolerance bands matter — domain expertise. The shipped code does not generate these from extracted geometry; the wizard must NOT pretend to either. **What the wizard DOES do (Option A — see §5.7):** if no `{pn}_inspection_profile.json` exists at library root, the wizard writes a clearly-marked **intake stub profile** (`source: "library_intake_stub"`, `status: "incomplete"`, `inspectionReady: false`) so the newly-added part is discoverable in `/api/profiles` without claiming to have inspection criteria. The matching consumer-side stub-awareness (UI badge + Inspect-gating fail-fast) is also part of the MVP (§5.7 + §9.5 + §11) — the wizard does not ship without it. Authoring a real (non-stub) profile remains a separate manual step (or a future Profile Builder tool).

### 3.3 What the MVP wizard explicitly does NOT promise

- It does not generate STL / GLB / view PNGs. The extraction pipeline today does not produce these for parts; future work could add them but the wizard ships without that capability.
- It does not validate that the part is "complete enough" for inspection. The minimum-viable revision is whatever the extraction produces; downstream completeness checks belong elsewhere.
- It does not auto-detect when a part has been revised in SOLIDWORKS. The operator drives the wizard; the wizard does not poll.

### 3.4 What the MVP wizard tolerates

- A part that has no real `{pn}_inspection_profile.json` yet. The wizard promotes what came out of extraction AND writes an intake stub profile (§5.7) so the part is discoverable. The stub is clearly marked `status: "incomplete"`; downstream UI is responsible for surfacing that to the user (see §10.7).
- A revision that exists but is incomplete (e.g. geometry-only, like `parts\1015003\revA\`). The wizard treats this as "old revision exists; new revision being added"; promotion targets a fresh subdir.
- A part that has never had a profile registered at library root. The wizard's promote step creates the intake stub at root (and per-revision archive copy) so `/api/profiles` picks it up automatically — see §5.7.

### 3.5 What the MVP wizard rejects outright

- Promotion to an existing `parts/{pn}/rev{X}/` directory unless the operator explicitly confirms overwrite intent (§6.1).
- Promotion when validation fails (§7) — fail closed.
- Promotion when the extraction's `packageId` cannot be located in `_bridge_imports/` (suggests the sidecar was deleted or never landed).

---

## 4. User flow

Eleven discrete steps, each owning one decision or one observable side effect. Numbered for ease of reference in §8 (UI) and §11 (acceptance).

1. **Open wizard.** Operator clicks "Add to Library" (or equivalent — see §8.1) in the AI-tool app. Wizard panel appears.
2. **Enter or pick part number.** Free-text input with type-ahead against existing `/api/profiles`. Validated against `sanitize_part_number()` (`ai_inspector/utils/drawing_map.py:15`). Visible state: "1020001 (existing — revA, revB present)" OR "1099999 (new — no existing entry)".
3. **Enter revision.** Free-text. Validated against the project convention (e.g. `revA`, `revB`, `revC`...). Wizard surfaces existing revisions for the part and refuses to silently overwrite (§6.1).
4. **Choose intake mode.** Two radio options: "Add a new revision of an existing part" / "Add a brand-new part". Selection drives §10 backward-compat behaviour (whether a root-level `{pn}_inspection_profile.json` symlink/copy is offered after promote).
5. **Verify active SOLIDWORKS drawing.** Wizard reads `/api/bridge/status`. Pill must read `Bridge: drawing active` AND the bridge's `activeDoc.title` must look plausibly like the part number (e.g. starts with `{pn}` or contains it). Wizard flags the mismatch but lets the operator override.
6. **Request drawing extraction.** Wizard POSTs to `/api/request-extraction` with `partNumber=<pn>` and `expectedDocPath=<the active doc path from /status>`. Approval modal appears in SW. Operator approves. Wizard polls until done.
7. **Verify active SOLIDWORKS part.** Operator switches SW to the matching `.SLDPRT`. Wizard re-polls `/api/bridge/status` until pill reads `Bridge: part active`. Same plausibility check on `activeDoc.title`.
8. **Request part extraction.** Wizard POSTs to `/api/request-part-extraction` with `partNumber=<pn>`. Approval modal. Operator approves. Wizard polls until done.
9. **Validate packages.** Wizard runs the validation matrix in §7 against the just-extracted drawing root file + part sidecar. Any failure aborts here — no promotion.
10. **Preview the promotion plan.** Wizard renders a preview table (§8.5): every file path that will be created, every file that will be moved, every file that will be backed up. Operator reviews. Operator clicks "Promote" or "Cancel".
11. **Promote.** Wizard executes the §5 install plan, writes `intake_manifest.json`, refreshes the profile index, returns a success state with a clickable link to the new revision's path.

If anything fails between steps 6 and 11, the wizard captures the state and offers two options: "Retry from this step" or "Cancel intake (no library changes)".

---

## 5. Canonical storage design

### 5.1 Per-revision target shape

Every successful wizard promotion creates this layout under `400S_Sorted_Library/parts/{partNumber}/rev{revision}/`:

```
parts/{partNumber}/rev{revision}/
├── intake_manifest.json                       ← NEW. Authored by the wizard. See §5.4.
├── {partNumber}_drawing_map.json              ← Promoted from staging compat-export output.
├── {partNumber}_drawing.pdf                   ← Promoted if compat-export produced one (optional today).
├── {partNumber}.json                          ← Promoted from {bridge_imports}/part/{pn}/{packageId}/part/part.json. The "part definition" file matching the existing convention seen in parts\1020001\revA\1020001.json.
├── {partNumber}_inspection_profile.json       ← Archive copy of the intake stub (§5.7), IF a real profile did not already exist. Skipped when a real profile is in place.
└── (optional curated files — NOT touched by the wizard:)
    ├── {partNumber}.STL
    ├── {partNumber}_colored.glb
    ├── {partNumber}_feature_colors.json
    ├── {partNumber}_dimension_descriptions.json
    ├── {partNumber}_highlight_boxes.json
    └── {partNumber}_view_{front,right,top,isometric}.png
```

The wizard owns the first four lines unconditionally, plus the intake-stub copy when applicable (§5.7). The optional curated files remain the operator's responsibility — same as today.

It also touches two locations at library root, per §5.2:

```
400S_Sorted_Library/
├── {partNumber}_drawing_map.json    ← Current app-visible drawing (mirror of latest promote).
├── {partNumber}_drawing.pdf         ← Same, if PDF is present.
└── {partNumber}_inspection_profile.json   ← Intake stub (§5.7) — ONLY when no real profile is already there.
```

### 5.2 Where `{pn}_drawing_map.json` should live

**Both locations, by deliberate design.** The two copies have different roles:

| Location | Role | Mutability |
|---|---|---|
| `400S_Sorted_Library/{pn}_drawing_map.json` (root) | **Current app-visible drawing.** What the rest of the app reads when no specific revision is named. | Mutable — overwritten by every promote of this part (with `.bak` rollback). |
| `parts/{partNumber}/rev{revision}/{pn}_drawing_map.json` (per-revision) | **Revision archive.** Immutable historical record of what was promoted under this revision name. | Effectively immutable — written once at promote, never updated except via §6.1 overwrite-confirmation. |

The wizard's promote step:

1. Writes the **revision archive** copy to `parts/{partNumber}/rev{revision}/{pn}_drawing_map.json` (atomic via `.partial` + rename — see §6.2).
2. Updates the **current app-visible** copy at root with the same content (atomic via `.tmp` + `os.replace`, `.bak` of previous).

**Why both:** the codebase already has the dual-location convention. `find_drawing_map_revision_path()` (`ai_inspector/utils/drawing_map.py:56-84`) checks the per-revision location first, then falls back to the root location. Five consumer call sites read drawing maps today (`server.py:474, 1215, 1411`; `server.py:3074-3075`); switching them en-masse to per-revision lookup is a separate refactor that does NOT belong in the wizard MVP (see §12.6 / §10.6).

**Migration path:** future commit (NOT bundled with the wizard) can move all consumers to `load_drawing_map_revision()`, deprecate the root-level copy, and migrate existing root files into a `revUnknown/` archive folder. The wizard's behaviour does not need to change at that point — it already writes the per-revision copy.

### 5.3 Where `{pn}_drawing.pdf` should live

Same dual-location convention as the drawing map. Per-revision copy at `parts/{partNumber}/rev{revision}/{pn}_drawing.pdf`; root-level copy at `400S_Sorted_Library/{pn}_drawing.pdf`. The PDF is optional in `compat-export` output; if absent, neither location is written.

### 5.4 `intake_manifest.json` shape

New file per revision. Authored by the wizard, never read by the engine. Purpose: audit trail + future-tool consumable. Proposed shape:

```json
{
  "schemaVersion": "1.0.0",
  "partNumber": "1020001",
  "revision": "revC",
  "promotedAtUtc": "2026-05-16T18:32:14.123Z",
  "promotedBy": "skaumb@<machine>",
  "intakeMode": "new-revision-of-existing-part",
  "sourceDrawing": {
    "packageId": "12546e8b7c96e432b14a2c272aff04252320dfd7981020059290bc677aa6190a",
    "sourceDocPath": "C:\\path\\to\\Drawing.SLDDRW",
    "sheetCount": 1,
    "viewCount": 4
  },
  "sourcePart": {
    "packageId": "4c9d1c4b...",
    "sourceDocPath": "C:\\path\\to\\Part.SLDPRT",
    "featureCount": 46,
    "activeConfiguration": "Default"
  },
  "files": [
    { "path": "1020001_drawing_map.json",  "bytes": 45112 },
    { "path": "1020001_drawing.pdf",       "bytes": 218456 },
    { "path": "1020001.json",              "bytes": 21100 }
  ],
  "bridgeBaseline": {
    "addinCommit": "c043fbe",
    "appCommit":   "c2de55d"
  }
}
```

`bridgeBaseline` references the milestone commits from §2.3 of the bridge integration plan — gives a downstream consumer enough to know which extraction-engine version produced the bytes in this revision.

### 5.5 Current revision pointer

**Recommendation: no separate pointer file in the MVP.** Revision discovery via filesystem scan (`Get-ChildItem parts/{pn}/rev*/`) is the existing convention; introducing a `_latest_revision.txt` would create a new failure mode (pointer drifting from filesystem reality).

If a future workflow demands a "current production revision" concept (e.g. for FAI reports that should always pin to the released rev, not the latest extraction), introduce `parts/{pn}/_released.txt` containing the revision name. Out of scope for the wizard MVP.

### 5.6 Relationship to existing root-level `{pn}_drawing_map.json` files

| Scenario | Wizard behaviour |
|---|---|
| Library has `1020001_drawing_map.json` at root, no `parts/1020001/revC/` | Wizard creates `parts/1020001/revC/` and updates the root file with the new content. Old root file is backed up to `.bak` (mirrors today's drawing-extraction install behaviour at `server.py:903-907`). |
| Library has `1020001_drawing_map.json` at root AND `parts/1020001/revB/1020001_drawing_map.json` from a prior wizard run | Wizard creates `parts/1020001/revC/`, leaves `revB/` untouched, updates the root copy to the `revC` content. The `revB` per-revision copy is the canonical reference for that revision; the root is a moving pointer. |
| Library has no `{pn}_drawing_map.json` anywhere yet | First wizard run for this part: creates both `parts/{pn}/rev{X}/{pn}_drawing_map.json` and the root copy. |

The principle: **the root-level file always reflects the most-recently-promoted revision's drawing map.** The per-revision file is the canonical historical record.

### 5.7 Intake stub profile (Option A)

**The problem this solves:** `_build_profile_index()` (`ai_inspector/spatial/engine.py:294-319`) globs for `*_inspection_profile.json` files at library root ONLY. A brand-new part promoted by the wizard would NOT appear in `/api/profiles` until someone authors a real inspection profile by hand, which is engineering work that can take days. That makes the wizard feel broken from the operator's point of view ("I just added this part, where is it?").

**The decision:** the wizard writes a clearly-marked **intake stub** profile so the part is discoverable, but never claims inspection readiness. Real (full) inspection-profile authoring remains a separate flow (§3.5).

**File location (dual, mirroring §5.2):**
- Root: `400S_Sorted_Library/{partNumber}_inspection_profile.json` — what `_build_profile_index()` discovers.
- Per-revision archive: `parts/{partNumber}/rev{revision}/{partNumber}_inspection_profile.json` — historical record bound to the revision.

**When the wizard writes the stub:**

| State at promote time | Wizard behaviour |
|---|---|
| No `{pn}_inspection_profile.json` at root | Write the stub at both locations (root + per-rev archive). |
| Root file exists AND `source == "library_intake_stub"` (stub from prior promote) | Overwrite root with the new revision's stub. Write the new revision's stub to the per-rev archive. |
| Root file exists AND `source != "library_intake_stub"` (real profile in place) | DO NOT touch the root file. DO NOT write a stub to the per-rev archive either — a real profile exists and is authoritative; the wizard does not shadow it. |

The detection rule lives in one place — the wizard's pre-promote check — and is governed by the `source` field. No other consumer needs to change.

**Stub schema (proposed `1.0.0-stub`):**

```json
{
  "$schemaVersion":  "intake-stub-1.0.0",
  "source":          "library_intake_stub",
  "status":          "incomplete",
  "inspectionReady": false,
  "part_number":     "1099999",
  "revision":        "revA",
  "name":            "<from extracted part.json `name`/`title` field if present>",
  "description":     "<from extracted part.json `description` field if present>",
  "createdAtUtc":    "2026-05-16T18:32:14.123Z",
  "createdBy":       "library-intake-wizard@1.0.0",
  "links": {
    "intakeManifest":  "parts/1099999/revA/intake_manifest.json",
    "drawingMap":      "1099999_drawing_map.json",
    "partMetadata":    "parts/1099999/revA/1099999.json"
  },
  "notes": "Stub profile created automatically by the Library Intake Wizard. The wizard produced the underlying drawing-map and part-metadata files but cannot infer inspection criteria (which features matter, which dimensions to inspect, what tolerance bands trigger findings). Author a real {pn}_inspection_profile.json (or use a future Profile Builder tool) before relying on this part's inspection workflow."
}
```

**Required fields (downstream consumers can rely on these):**
- `$schemaVersion` — versions the stub format so a future schema change is safe.
- `source: "library_intake_stub"` — the canonical marker. **Any consumer that wants to behave differently for stubs vs. real profiles checks this field.**
- `status: "incomplete"` — human-readable status.
- `inspectionReady: false` — boolean gate for UI / API: if false, inspection actions surface a "Profile incomplete" affordance instead of running.
- `part_number`, `revision` — identity.
- `links.intakeManifest`, `links.drawingMap`, `links.partMetadata` — pointers to the actual artifacts the stub describes.

**Optional fields:**
- `name`, `description` — pulled from the extracted part metadata if available; surfaced in the picker so the operator sees something more useful than just the number.

**Consumer-side stub-awareness (MVP — ships with the wizard, not as a follow-up):**

The wizard's backend writes a stub; the matching consumer surface MUST be in place at the same time so the user never sees an incomplete-profile part presented as inspection-ready. These five requirements are all in MVP scope — the wizard does not ship without them:

1. **`/api/profiles` includes the stub entry.** Discoverability: the new part appears in the picker without further user action. (Achieved automatically because the stub lives at the path `_build_profile_index()` already scans — no consumer code change needed for this requirement; listed for completeness.)
2. **`/api/profile-details/{pn}` exposes `inspectionReady`, `status`, and `source` verbatim** to the frontend. The current endpoint response shape (server.py:1608-1646) gets these three fields added when the underlying file is a stub. See §9.5 for the exact response-shape change.
3. **Frontend renders a visible "Profile incomplete" badge** on stub entries in the picker AND a "Intake pending inspection profile" warning banner on the selected-part panel. Plain text, not an emoji-only signal — must be readable by a screen reader. See §8.7 for the UI specifics.
4. **The Inspect action is disabled OR fails fast with a clear message.** Recommendation: visibly disabled (greyed-out button with tooltip) is preferable to "you can click it but it fails" — the former prevents the dead-end click entirely. If the existing UI cannot disable cleanly, fall back to fail-fast: `POST /api/inspect` returns HTTP 422 with the body `{ "error": "profile_incomplete", "message": "This part has been added to the library, but no inspection profile has been authored yet." }`. See §9.6 for the backend gate and §11.7c for the acceptance check.
5. **Both backend and frontend pieces of the stub-awareness ship in the same MVP commit-set as the wizard backend.** No "ship the wizard, the badge follows next sprint" gap — that creates the exact bad-UX window this plan exists to prevent (see §10.7 reasoning).

Without all five, the wizard creates a class of parts that look inspection-ready but aren't. The operator clicks Inspect, gets garbage back, doesn't know why. That's worse than the wizard not shipping. Treat these as gate requirements, not nice-to-haves.

---

## 6. Safety rules

These are non-negotiable. Each rule names the failure mode it prevents.

### 6.1 Never overwrite an existing revision without explicit confirmation

**When this rule fires.** Retype-to-confirm friction applies in TWO cases only — both involve overwriting bytes the operator has not explicitly opted into losing:

1. **Existing revision directory.** If `parts/{partNumber}/rev{revision}/` already exists at step 3 (revision entry), the wizard surfaces the existing revision's `intake_manifest.json` content (when present) and offers three options: "Cancel" (default) / "Promote into a different revision name" / "Overwrite this revision (requires typing the revision name to confirm)". The third option requires the operator to retype the exact revision string (`revC`) — mirrors the `git push --force-with-lease` pattern: possible by intent, impossible by accident.
2. **Existing root-level `{pn}_drawing_map.json`** that belongs to a DIFFERENT promoted revision (per the `intake_manifest.json` cross-check in §7.6). This is the rarer case: root file was last updated by a promote of revA's content, operator is now promoting revC. The wizard updates the root copy as part of normal promote — but if the operator's new revision string MATCHES an already-promoted revision name (revA), the §6.1.1 rule fires.

**When this rule does NOT fire.** Normal new-revision intake — operator types `revC` for a part that has `revA` and `revB` already, or `revA` for a brand-new part — proceeds through preview to promote with no extra retype friction. The `.bak` rollback on the root-level drawing-map update is the safety net for that path (mirrors today's drawing-extraction install behaviour at `server.py:903-907`).

**Implementation note:** the wizard's §10 preview computes the warning state and surfaces it in the §8.5 preview table as `OVERWRITE (confirmation required)` rather than the bare `CREATE` / `UPDATE` rows. The Promote button is disabled until the retype input matches.

### 6.2 Write to `.partial` first, then atomic rename

Mirrors the pattern already in `_install_sidecar()` (server.py — Phase B `_install_sidecar` helper). For the wizard:
1. Create `parts/{partNumber}/rev{revision}.partial/`
2. Copy all promoted files into it
3. Validate (re-read each file from the partial dir; confirm sizes match plan)
4. `os.rename(partial, target)` — atomic on Windows for non-existent target
5. On any failure between 1 and 4: `shutil.rmtree(partial, ignore_errors=True)`. No `.bak` of partial state.

### 6.3 Keep previous revision intact

The wizard never reads, modifies, or copies files out of any existing `parts/{pn}/rev*/` directory other than the one being created. This is structurally guaranteed because every wizard target path is templated as `parts/{pn}/rev{revision}/...` where `{revision}` is the operator's chosen new value.

### 6.4 Keep manual library files safe

Files under `parts/{pn}/rev{X}/` that the wizard does NOT manage (per §5.1's "optional curated files" list) are never touched:
- The wizard writes a fresh `rev{X}/` directory; pre-existing files are only present if the operator chose §6.1 overwrite mode, in which case the warning explicitly listed what would be lost.
- The wizard never writes to `parts/{pn}/` outside of its specific revision target.
- The wizard never writes to the `assemblies/` tree.
- The wizard never writes to any path under `_bridge_imports/` (read-only consumer of those sidecars).

### 6.5 Fail closed on validation error

Any §7 validation failure → no promotion happens. The error panel surfaces:
- Which check failed (machine-readable code + human message).
- What the wizard can do to recover (usually "retry extraction" or "operator needs to fix SW state and start over").
- A copy-to-clipboard button for the full failure detail (so the operator can paste into the diagnostics bundle or chat).

### 6.6 Preserve `_bridge_imports/` as staging until promotion succeeds

The wizard reads from but does not modify `_bridge_imports/{kind}/{pn}/{packageId}/`. Specifically:
- The wizard does NOT delete the sidecar after promotion. The `_latest.txt` pointer continues to name the latest extraction; the sidecar stays on disk as the source-of-truth for what came out of the bridge.
- A future cleanup tool can prune `_bridge_imports/` entries older than N days — explicitly out of wizard scope (see pilot checklist §4.6).

---

## 7. Validation

Run after step 8 (part extraction complete) and before step 10 (preview). All checks must pass or the wizard refuses to enter the preview state.

| # | Check | How | On failure |
|---|---|---|---|
| 7.1 | `inspectorpkg validate-package <drawing zip>` returns 0 | Reuse `_run_subprocess([cli, "validate-package", str(zip_path)])` (server.py:943ff) — already invoked by the existing drawing flow at `server.py:843-847` | Hard fail — the bridge already validated; if it fails on re-validate something corrupted the staging zip. Suggest "retry from extraction". |
| 7.2 | `inspectorpkg validate-package <part zip>` returns 0 | Same helper for the part package | Same |
| 7.3 | Drawing map loads via `load_drawing_map(pn, library_root_for_test_dir)` | Drop the drawing map into a temporary directory and call the existing loader; this is the same probe used by `server.py:944-949` after install | Hard fail — drawing map is corrupt; suggest retry. |
| 7.4 | Part JSON parses against the part schema | Read `parts/part.json` from the unzipped sidecar; validate against `schemas/v1/part.schema.json` from the bridge repo (via `inspectorpkg validate-package` which already does this, but also as a defensive re-check after copy) | Hard fail with schema-error message |
| 7.5 | Required files exist | `manifest.json`, `part/part.json` exist in the unzipped sidecar. `{pn}_drawing_map.json` exists in compat-export staging. | Hard fail; report which file is missing |
| 7.6 | Source doc path consistency | `intake_manifest.sourceDrawing.sourceDocPath` and `sourcePart.sourceDocPath` both start with paths that mention the part number (case-insensitive substring) OR the operator overrode the warning in step 5/7 | Warning, not fail. Wizard surfaces the mismatch in preview; operator decides. |
| 7.7 | Revision consistency (if available) | If the part package's `manifest.json` carries a revision field, it should match the operator's chosen revision. If the bridge does not yet expose revision in the part schema, this check is no-op for MVP. | Warning, not fail |

The validation step gates promotion. The preview (step 10) is shown only after validation passes.

---

## 8. UI design

The wizard lives in the AI-tool web frontend (`static/index.html`). Visual conventions match the existing left-panel + center-viewport layout.

### 8.1 Entry point

A new button in the left panel near the existing Part Information section:

```
[ + Add to Library ]
```

The button is visible whenever the bridge status pill is in any of: `available`, `drawing active`, `part active`, `assembly active`. Disabled when bridge is `unavailable` or `auth missing` (the wizard cannot do its job without bridge).

Clicking opens the wizard as a right-side panel overlay (similar to the existing Scout overlay), not a modal — the operator can still see the left-panel state + main viewport.

### 8.2 Step-by-step panel layout

Each of the 11 user-flow steps (§4) renders as a single panel state. Only one step is active at a time; previous steps render as a collapsed summary at the top (a vertical breadcrumb). Like a wizard, not a dashboard.

| Step | Panel content |
|---|---|
| 1 (open) | The wizard itself opening counts as step 1 |
| 2 (part number) | Type-ahead input + "Existing/New" status badge |
| 3 (revision) | Text input + list of existing revisions for context |
| 4 (intake mode) | Two radio options |
| 5 (verify drawing) | Live bridge status pill snapshot + active doc title + path. Auto-advances when pill flips to `Bridge: drawing active` |
| 6 (extract drawing) | "Extracting drawing — approve in SOLIDWORKS" with a spinner. Same wording as the existing Re-extract button's busy state |
| 7 (verify part) | Mirrors step 5 |
| 8 (extract part) | Mirrors step 6 |
| 9 (validate) | Inline checklist: 7 lines, each transitioning from grey → green / red as checks complete. Hard-fails surface a "Recover" button |
| 10 (preview) | The preview table (§8.5) plus a single "Promote" button (red-ish primary) and a "Cancel intake" button |
| 11 (success) | Green check + summary + path to the new revision + button to "Open in File Explorer" + button to "View part in app" (uses `/api/profile-details/{pn}` to verify the refresh worked) |

### 8.3 Status messages

Plain language. No jargon. Examples:

- **Step 5, mismatch detected:** "The active SOLIDWORKS drawing is `Bracket-Rev3.SLDDRW`. The part number you entered is `1020001`. These do not appear to match. You can override if you know this is correct."
- **Step 7, no part open:** "Open the matching part (`.SLDPRT`) in SOLIDWORKS, then click Continue."
- **Step 9, validation fail:** "Validation failed: `part.json` does not match the schema. The bridge produced a package the schema validator rejected. Click Retry to re-extract, or Cancel to abort."

### 8.4 Error states

| State | Visual treatment | Recovery surface |
|---|---|---|
| Bridge unavailable mid-wizard | Yellow banner across the wizard top | "Restart SOLIDWORKS, then click Resume" |
| Extraction failed (HTTP 500) | Red panel replacing the active step | "Retry extraction" / "Cancel intake" |
| Validation failed | Red checklist line + inline detail | "Retry from extraction" / "Cancel intake" |
| Promotion failed mid-write | Red panel + the `.partial` directory left on disk for inspection | "Rollback partial (deletes the .partial directory)" / "Leave for inspection" |
| Operator cancels at preview | Confirmation dialog | "Cancel intake (no library changes)" — confirms zero side effects |

### 8.5 Preview table

The preview table is the wizard's most important screen. It must be unambiguous about what will happen.

| Action | Path | Size | Notes |
|---|---|---|---|
| CREATE | `parts/1020001/revC/1020001_drawing_map.json` | 45.1 KB | from staging compat-export |
| CREATE | `parts/1020001/revC/1020001_drawing.pdf` | 218.4 KB | from staging compat-export |
| CREATE | `parts/1020001/revC/1020001.json` | 21.0 KB | from `_bridge_imports/part/1020001/4c9d1c4b…/part/part.json` |
| CREATE | `parts/1020001/revC/intake_manifest.json` | (small) | authored by wizard |
| UPDATE | `400S_Sorted_Library/1020001_drawing_map.json` | 45.1 KB | overwrites; `.bak` of previous |
| UPDATE | `400S_Sorted_Library/1020001_drawing.pdf` | 218.4 KB | overwrites; `.bak` of previous |
| REFRESH | `/api/profiles` cache | — | in-process; no restart |

Header: "Review the changes before promoting. **Nothing has been written yet.**" Footer: `[ Cancel intake ]` `[ Promote (writes 4 files, updates 2) ]`.

### 8.6 Final success state

```
✅ Promoted 1020001 revC successfully.

Files written: 4
Files updated: 2
Bridge package IDs:
  drawing  12546e8b7c96e432b14a2c272aff04252320dfd7981020059290bc677aa6190a
  part     4c9d1c4b...

[ Open revision folder ] [ View part in app ] [ Start another intake ] [ Close ]
```

### 8.7 Stub-profile surface (MVP requirement, NOT a follow-up)

The wizard's backend writes an intake stub (§5.7) when no real profile exists. The frontend surface for that state must ship in the same MVP. Three UI affordances:

**A. Picker badge.** In the left-panel part list, any entry whose `/api/profile-details/{pn}` returns `source == "library_intake_stub"` renders with a small text badge next to the part number — e.g. `1099999  [INTAKE]`. The badge color is muted (greyish), not alarming red — this is "incomplete", not "broken".

**B. Selected-part warning banner.** When the operator selects a stub-only part, the main viewport renders a single-line banner above the normal content:

```
⚠ Profile incomplete — this part was added via the Library Intake Wizard, but no
inspection profile has been authored yet. Inspection will be unavailable until
a profile is added.
```

Plain text. Screen-reader-friendly. No emoji-only signal — the word "Profile incomplete" must be present in the DOM text content for accessibility.

**C. Inspect button disabled with tooltip.** The Inspect / Re-extract Drawing button on a stub-only part is rendered disabled. The button's tooltip reads:

```
This part has been added to the library, but no inspection profile has been
authored yet. Add a real {pn}_inspection_profile.json (replacing the stub at
library root) to enable inspection.
```

If the existing button rendering cannot cleanly express "disabled with explanatory tooltip", the fallback is fail-fast on click: post → 422 → toast with the same wording. §9.6 covers the backend's fail-fast contract regardless of which UI path the frontend takes.

**Stub-awareness must be testable without running the wizard.** A QA engineer can hand-craft a stub at `400S_Sorted_Library/1099999_inspection_profile.json` matching the §5.7 schema, refresh `/api/profiles`, and observe the badge + banner + disabled button. The full wizard run is not required to validate the consumer surface.

---

## 9. Backend / API design

The wizard frontend does not invent new write paths. All writes go through new server endpoints that own the §6 safety rules. The bridge endpoints remain untouched (reused as-is for extraction).

### 9.1 Reused (no changes)

| Endpoint | Used by wizard step |
|---|---|
| `GET /api/bridge/status` | Steps 5, 7 (poll for active doc kind + path) |
| `GET /api/profiles` | Step 2 (type-ahead) |
| `GET /api/profile-details/{pn}` | Steps 2, 11 (existing-part check, post-promote verification) |
| `POST /api/request-extraction` | Step 6 (drawing extraction) |
| `POST /api/request-part-extraction` | Step 8 (part extraction) |

### 9.2 New endpoints (proposed)

#### `GET /api/library/revisions/{partNumber}`

Returns the list of existing revisions for a part. Powers step 2's "existing" badge and step 3's existing-revisions list.

Response:
```json
{
  "partNumber": "1020001",
  "revisions": [
    { "name": "revA", "path": "parts/1020001/revA",
      "intakeManifest": null,
      "fileCount": 9 },
    { "name": "revB", "path": "parts/1020001/revB",
      "intakeManifest": { "promotedAtUtc": "...", "sourceDrawing": {...} },
      "fileCount": 11 }
  ]
}
```

Discovery is filesystem-scan based (`Path.glob('parts/{pn}/rev*')`); the existing convention. Returns 404 if `parts/{pn}/` does not exist.

#### `POST /api/library/intake/preview`

Dry-run. Computes the §8.5 preview table without writing anything.

Request:
```json
{
  "partNumber": "1020001",
  "revision": "revC",
  "intakeMode": "new-revision-of-existing-part",
  "drawingPackageId": "12546e8b...",
  "partPackageId": "4c9d1c4b..."
}
```

Response (200):
```json
{
  "planValid": true,
  "actions": [
    { "kind": "CREATE", "path": "parts/1020001/revC/1020001_drawing_map.json", "bytes": 45112, "source": "staging compat-export" },
    { "kind": "CREATE", "path": "parts/1020001/revC/1020001.json", "bytes": 21100, "source": "_bridge_imports/part/1020001/4c9d1c4b.../part/part.json" },
    { "kind": "UPDATE", "path": "1020001_drawing_map.json", "bytes": 45112, "source": "staging compat-export", "backup": "1020001_drawing_map.json.bak" }
  ],
  "warnings": [],
  "errors": []
}
```

Response (409 — revision exists, overwrite not confirmed):
```json
{
  "planValid": false,
  "errors": [
    { "code": "revision_exists",
      "message": "parts/1020001/revC already exists. Confirm overwrite by re-posting with `overwriteConfirmed: \"revC\"`." }
  ]
}
```

#### `POST /api/library/intake/promote`

The commit. Same body shape as preview plus `overwriteConfirmed` when the revision exists.

Performs the §6 install. Returns the same actions list with each entry annotated `committed: true | false` + a final `success: true` flag. On any per-file failure during the partial-rename sequence: rolls back the partial directory, returns 500 with the file that failed.

#### Internal: profile-index refresh

**Not a public endpoint in MVP.** Profile-index refresh is an internal step of `/api/library/intake/promote` — the promote handler invokes the index rebuild inline after a successful write so the new entry appears in `/api/profiles` within the same session. The operator never calls a refresh endpoint directly; it is implementation detail.

If a debug surface is genuinely needed later (e.g. a developer manipulates files outside the wizard and wants the in-memory cache to catch up), expose it as a clearly-labelled internal endpoint under `/api/_debug/library/index/refresh` and gate behind a non-default env flag — NOT in the public `/api/library/...` namespace. That decision belongs to a separate debug-tooling plan, not this wizard.

### 9.3 What the wizard does NOT POST

- The wizard never POSTs directly to `_install_sidecar` or its analog. Bridge sidecar install (Phase B) and library promotion (this wizard) are deliberately separate code paths so a failure in one cannot corrupt the other.
- The wizard never POSTs to the bridge directly with an alternate body shape. It uses the existing `/api/request-extraction` and `/api/request-part-extraction` endpoints as-is.

### 9.4 Single-flight gate

Reuse `_request_extraction_lock` for the bridge calls (steps 6 + 8). The promotion steps (preview + promote) do not need the same lock because they don't touch SOLIDWORKS — but they should have their own `_library_intake_lock` to prevent two concurrent promotions racing on the same revision target.

### 9.5 Stub-aware `/api/profile-details/{pn}` (MVP requirement)

The existing `get_profile_details()` handler (`server.py:1608-1646`) reads root-level `{pn}_inspection_profile.json` and falls back to `{pn}.json`. When the file IS an intake stub (§5.7), the response shape must additively expose three fields so the frontend can gate behavior:

```json
{
  "part_number":      "1099999",
  "part_name":        "...",
  "part_description": "...",
  "features":         [],

  "source":           "library_intake_stub",
  "status":           "incomplete",
  "inspectionReady":  false,

  "links": {
    "intakeManifest":  "parts/1099999/revA/intake_manifest.json",
    "drawingMap":      "1099999_drawing_map.json",
    "partMetadata":    "parts/1099999/revA/1099999.json"
  }
}
```

**Backward compat for real profiles:** when the file is a real (non-stub) profile, the handler does NOT add `source` / `status` / `inspectionReady` if they are not already present. Existing consumers that don't know about these fields keep working unchanged. Existing consumers that DO read them get sensible defaults: absence of `inspectionReady` is treated as `true` (assume ready) by frontend code that checks the field.

**Implementation note:** the cleanest way is for `get_profile_details()` to pass through the underlying file's fields when `source == "library_intake_stub"`, and to fall back to today's bespoke composition otherwise. One conditional branch; no schema migration needed for the existing real-profile fleet.

### 9.6 Stub-aware `/api/inspect` (MVP requirement — fail-fast gate)

The existing `/api/inspect` endpoint runs an inspection against the uploaded drawing using the named part's profile. When the named part's profile is an intake stub:

- **Refuse the request with HTTP 422.**
- Response body:

```json
{
  "error":   "profile_incomplete",
  "message": "This part has been added to the library, but no inspection profile has been authored yet.",
  "part_number": "1099999"
}
```

The gate runs early — before any uploaded bytes are processed, before any LLM call is made, before any temp file is written. The check is a single read of the same `{pn}_inspection_profile.json` that `get_profile_details()` would read, with the same `source == "library_intake_stub"` predicate from §9.5.

The frontend reads the 422 response and surfaces the `message` field verbatim as a toast — operator sees the same wording the §8.7 disabled-button tooltip used, so the experience is consistent whether the click was prevented or fell through.

**Why fail-fast and not "degraded inspection":** running an LLM inspection against a stub-only part wastes the API call AND returns confusing output (low-quality findings because the profile has no inspection criteria). Fail-fast is cheaper and clearer.

---

## 10. Migration / backward compatibility

The wizard must coexist with everything in the library today. Concrete cases:

### 10.1 Existing root-level `{pn}_drawing_map.json` files

Today's drawing extraction installs to root with `.bak` rollback (server.py:835ff). The wizard's promote step also writes to root (per §5.2). Both flows must coexist:

- The wizard's promote step writes the root file with the same atomic `.tmp + os.replace` + `.bak` pattern.
- If a user runs the existing Re-extract Drawing button on a part that has revisions, the root file gets overwritten — same as today; the per-revision files are NOT touched. The wizard's per-revision content is the canonical record; the root copy is a moving pointer.
- This is acceptable for MVP because the existing button's user is consciously running the existing flow. A future "deprecate the Re-extract button in favour of the wizard" decision is a separate UX call.

### 10.2 Existing part profiles

Existing `parts/{pn}/rev{X}/` directories (whether complete like `1020001/revA` or geometry-only like `1015003/revA`) are NEVER touched by the wizard. They remain readable and discoverable by all current code paths.

The wizard's `intake_manifest.json` is a new file under a new revision — no schema conflict with anything that exists today.

### 10.3 Existing assembly library

`assemblies/{id}/` is completely outside the wizard's scope for MVP — assemblies remain a v2 item (§12.4) and the MVP does NOT expand scope to include them. The assembly globals (`assembly_part_lookup`, `assembly_profiles` — server.py:181–246) are not affected by anything the wizard does.

Out-of-scope is enforced structurally on two layers:
1. The wizard's frontend never offers an "assembly" path — only the part-extraction button feeds into intake.
2. The new backend endpoints under `/api/library/...` only accept part identifiers and only ever read/write under `parts/`. An attempt to POST an assembly-shaped body would be rejected at the request-validation layer.

The wizard never reads or modifies anything under `assemblies/`. Assembly extraction continues to work via the existing `/api/request-assembly-extraction` flow (sidecar-only, no library promotion) — unchanged by this wizard.

### 10.4 The `_batch_index.json` legacy

The library has an `_batch_index.json` at the root from the 2026-02-12 batch ingestion. Nothing reads it today. The wizard does NOT update it (would imply a maintenance contract we don't have). A future "library audit" tool can either revive `_batch_index.json` or replace it; the wizard does not depend on its existence.

### 10.5 The non-existent `LIBRARY_ENTRY_GUIDE.md`

My memory referenced this file; it is not in the repo. The wizard plan does not depend on it. A separate small doc commit can create `docs/library-entry-conventions.md` describing the per-revision file shape as observed in `parts/1020001/revA/`, useful for operators doing manual intake before the wizard ships. Out of scope for this plan.

### 10.6 What the wizard explicitly does NOT break

- `GET /api/profiles` continues to scan root-level `*_inspection_profile.json` files. The wizard does not change that scan logic. The intake stub profile (§5.7) lands at exactly the path this scan expects, so newly-promoted parts appear in the list automatically.
- `GET /api/drawing-map/{pn}` continues to read via `find_drawing_map_path()` which checks root first. Wizard writes preserve the root copy.
- `GET /api/compare-drawings/{pn}/{revA}/{revB}` continues to read via `find_drawing_map_revision_path()` (drawing_map.py:56-84). Wizard writes populate exactly the path this function expects.
- `POST /api/inspect` continues to call `load_drawing_map(pn)` against the library root. Wizard writes ensure this returns the latest-promoted revision's map.
- The existing Re-extract from SOLIDWORKS button continues to work for direct drawing extraction without going through the wizard.

### 10.7 How intake stubs interact with downstream consumers

The wizard writes intake stubs that masquerade as profiles for discoverability, AND the matching consumer-side stub-awareness ships in the same MVP. Both halves are in scope; there is no "risk window" between them.

| Consumer | MVP behaviour against a stub (`source == "library_intake_stub"`) | Reference |
|---|---|---|
| `GET /api/profiles` | Returns the stub entry alongside real profiles. No frontend change required — the underlying scan is already correct. | §5.7 req 1 |
| `GET /api/profile-details/{pn}` | Returns the stub content with `source`, `status`, `inspectionReady` exposed verbatim alongside the existing fields. | §9.5 |
| `POST /api/inspect` | Refuses with HTTP 422 + body `{ "error": "profile_incomplete", "message": "This part has been added to the library, but no inspection profile has been authored yet." }`. Fail-fast — no LLM call, no temp file write. | §9.6 |
| Frontend picker | Renders `[INTAKE]` text badge next to the part number for stub-only parts. | §8.7 (A) |
| Frontend selected-part panel | Renders a "Profile incomplete — Inspection will be unavailable until a profile is added." banner. | §8.7 (B) |
| Frontend Inspect button | Disabled with explanatory tooltip; fail-fast fallback if disabled cannot be expressed cleanly. | §8.7 (C) |

Real (non-stub) profiles are unaffected: `source` / `status` / `inspectionReady` are only added to the response when the underlying file is a stub (§9.5 backward-compat rule). Existing consumers continue to see exactly the response shape they see today against the existing fleet of hand-authored profiles.

**Why this is in MVP scope and not a follow-up:** without all the rows in the table above, a brand-new wizard-promoted part LOOKS inspection-ready in the picker, the user clicks Inspect, and gets either an empty findings table or an LLM-generated guess against no real inspection criteria. Both outcomes erode trust in the tool faster than not shipping the wizard at all. The whole point of the stub design is to be honest about state; honesty is incomplete if the honest signal exists only in a JSON file the user never opens.

---

## 11. Acceptance criteria

The wizard ships when all of these can be demonstrated end-to-end on a known-good machine.

| # | Criterion | How to verify |
|---|---|---|
| 11.1 | Add a brand-new part revision | Choose `1099999` (not in `/api/profiles`). Pick revision `revA`. Walk the wizard. Confirm `parts/1099999/revA/` is created with the four expected files (§5.1) plus `intake_manifest.json` plus the per-revision archive copy of the stub profile. Confirm root-level `1099999_drawing_map.json` AND root-level `1099999_inspection_profile.json` (the intake stub, §5.7) are both created. |
| 11.2 | Add a second revision of the same part | After 11.1 succeeds, run the wizard again with `1099999` and `revB`. Confirm `parts/1099999/revB/` is created. Confirm `parts/1099999/revA/` is unchanged (mtime check). Confirm root-level `1099999_drawing_map.json` now points to revB content. Confirm root-level `1099999_inspection_profile.json` was overwritten with the revB stub (because the existing root file had `source == "library_intake_stub"` — §5.7 row 2). |
| 11.3 | Reject wrong active document | Open a drawing in SW; start wizard; at step 7, leave the drawing open instead of switching to a part. Verify wizard waits at step 7 and shows "Open the matching part (`.SLDPRT`)" message. Confirm clicking through anyway is impossible — the wizard does not advance. |
| 11.4 | Reject duplicate revision unless confirmed | After 11.1 succeeds, start wizard again with `1099999` revA. Verify step 3 surfaces the "revision exists" warning with the three options from §6.1. Verify Cancel takes the user back; verify "Overwrite" requires typing `revA` to confirm; verify simple click-through is impossible. |
| 11.5 | Recover from failed extraction | Disable the bridge mid-wizard (close SW with the wizard at step 6). Verify the wizard surfaces the error and offers "Retry extraction" / "Cancel intake". Restart SW, click Retry, verify the wizard recovers from the same step (no need to re-enter part number / revision / mode). |
| 11.6 | No manual files overwritten | Run 11.2 with `1020001` (which has populated `revA` already) using a new revision `revC`. Note the mtimes of every file under `parts/1020001/revA/` before. After promotion, confirm none of them changed. Confirm `parts/1020001/revB/` debug files are also untouched. |
| 11.7 | App can find the newly added entry | After 11.1, hit `GET /api/library/revisions/1099999` and confirm the response lists `revA`. After 11.2, confirm both `revA` and `revB` appear. Confirm `1099999` now appears in `/api/profiles` (because the intake stub at root is discovered by `_build_profile_index()`). Confirm `/api/profile-details/1099999` returns the stub content with `source == "library_intake_stub"`, `status == "incomplete"`, `inspectionReady == false`. |
| 11.7b | Real profile is NOT shadowed by a stub | On a part that has a hand-authored `{pn}_inspection_profile.json` at root with `source != "library_intake_stub"` (or no `source` field at all), run the wizard. Confirm the root profile is left untouched and no stub is written to the per-rev archive. The real profile remains the only one. Confirm `/api/profile-details/{pn}` returns the existing real-profile shape WITHOUT the added stub fields (`source`/`status`/`inspectionReady`) — §9.5 backward-compat rule. |
| 11.7c | Inspect fail-fast on stub-only part | After 11.1, upload any drawing and `POST /api/inspect` with `part_number=1099999`. Confirm HTTP 422, body `{ "error": "profile_incomplete", "message": "This part has been added to the library, but no inspection profile has been authored yet.", "part_number": "1099999" }`. Confirm NO LLM API call was made (verify via API-key dashboard or by stubbing/observing). |
| 11.7d | Frontend stub badge + banner + disabled Inspect | Refresh the AI-tool app after 11.1. In the part picker, confirm `1099999` is listed with the `[INTAKE]` badge text. Select it. Confirm the main viewport shows the "Profile incomplete" banner with the exact wording from §8.7 (B). Confirm the Inspect button is rendered disabled with the tooltip from §8.7 (C). Confirm the text "Profile incomplete" is present in the DOM (screen-reader accessibility — `document.body.innerText.includes("Profile incomplete")`). |
| 11.7e | Stub upgraded to real profile flips all gates | Manually replace the root `1099999_inspection_profile.json` with a hand-authored real profile (no `source` field, or `source != "library_intake_stub"`). Wait for the in-process cache to refresh (or restart server). Confirm: `/api/profile-details/1099999` no longer carries `inspectionReady: false`. Frontend picker no longer renders the `[INTAKE]` badge. Selected-part banner gone. Inspect button enabled. `POST /api/inspect` returns a real inspection response (not 422). |
| 11.8 | Existing drawing flow unchanged | Click the existing Re-extract Drawing button for any part. Confirm the root-level drawing map updates as before; no per-revision files are created (because the existing button is not the wizard). |
| 11.9 | Bridge regression suite still passes | Run the bridge-side and app-side smokes from `production-pilot-packaging-checklist.md §7`. All green. |
| 11.10 | Preview is non-destructive | Walk the wizard to step 10 (preview). Click Cancel intake. Confirm zero files on disk changed (no `parts/{pn}/rev{X}/`, no root file update, no `.bak` files created). |

---

## 12. Open questions

These need product / ops decisions before implementation, not technical answers from the planner.

### 12.1 Revision source of truth

**Question:** is the revision string (`revA`, `revB`, ...) operator-typed, derived from SOLIDWORKS document properties, or derived from a PLM lookup?

**Options:**
- **Operator-typed (MVP recommendation).** Simplest; matches today's manual convention. Risk: typos produce `revC` and `RevC` and `Rev_C` as three distinct revisions.
- **Derived from SW.** Pull the Custom Property `Revision` (or `RevisionNumber`) from the active doc's properties at extraction time. Eliminates typos but requires the customer to actually populate that property — many don't.
- **PLM lookup.** Out of scope for this product right now.

**Recommendation:** MVP uses operator-typed with a regex validator (`^rev[A-Z][0-9]*$`); v1.1 adds an "auto-detect from SW Custom Properties" toggle.

### 12.2 Automatic inspection-profile generation — DECIDED (closed)

**Question:** can the wizard generate `{pn}_inspection_profile.json` from the extracted part data?

**Decision (closed, in MVP scope):**

- **Full inspection profile: NO.** Inspection profiles encode which features matter for QC, which dimensions to inspect, and what tolerance bands trigger findings. This is engineering domain knowledge; the wizard cannot infer it from geometry alone, and an auto-generated "full" profile would be a lie that downstream code would treat as truth.
- **Intake stub: YES.** A clearly-marked stub (`source: "library_intake_stub"`, `status: "incomplete"`, `inspectionReady: false`) is written at promote time IF no real profile already exists. See §5.7 for the schema.
- **Stub-aware consumers: YES, in MVP.** `/api/profile-details/{pn}` exposes the stub fields (§9.5). `/api/inspect` fail-fasts on stub-only parts with HTTP 422 (§9.6). Frontend renders a `[INTAKE]` badge + "Profile incomplete" banner + disabled Inspect button (§8.7). All five MVP requirements gate the wizard ship (§5.7 list).

**Why this is closed and not deferred:** without the consumer-side stub-awareness, the wizard creates a class of parts that look inspection-ready but produce garbage findings. Splitting the wizard backend from its consumer surface would create a known bad-UX window between the two ships — the entire reason the stub exists is to be honest about state, and that honesty is incomplete if the user can't see it.

**Future:** a separate "Profile Builder" tool that prompts the operator through critical-feature selection and writes a real (non-stub) profile. The Profile Builder REPLACES the stub at root + per-revision archive when run; the wizard's `source` field is the marker that tells it the stub is safe to overwrite. The Profile Builder is its own product plan, not bundled with the wizard.

### 12.3 Whether root-level drawing maps remain canonical

**Question:** five consumer call sites read root-level `{pn}_drawing_map.json` today. Do we plan to deprecate the root location in favour of per-revision storage?

**Decision for this plan: defer. Root-level migration is a separate future refactor and is explicitly NOT bundled with the intake wizard.**

The wizard MVP ships with the §5.2 dual-location pattern (root = current app-visible, per-revision = revision archive). Wizard correctness does not depend on whether the migration eventually lands.

When/if that migration is undertaken, it is a standalone work item with these steps:
1. Update all five consumer call sites (`server.py:474, 1215, 1411, 3074, 3075`) to use `load_drawing_map_revision(pn, revision)` with an explicit revision arg (or "latest" sentinel).
2. Stop the wizard from writing the root copy (one-line change in the promote step).
3. Optionally archive existing root-level `{pn}_drawing_map.json` files into `parts/{pn}/revUnknown/` for cleanliness.
4. Run the full regression smoke from `production-pilot-packaging-checklist.md §7`.

Bundling that into the wizard MVP would multiply risk surface for no shipped capability benefit; the wizard is fully useful without it.

### 12.4 Whether to support assemblies in v2

**Yes, planned but separate.** The assembly intake wizard has a different shape:
- Assembly has its own metadata schema (`{id}_assembly.json` vs `{pn}.json`).
- Assembly has BOM data (`{id}_bom_row_highlights.json`) that has no part counterpart.
- Assembly globals live separately (server.py:181–246).
- Assembly identifiers can be path-inferred (Phase C fix); part numbers are operator-typed.

v2 spec will mirror this doc's structure but with the assembly-specific deltas called out. The shared abstraction is the preview-then-commit pattern + the `.partial`-then-rename safety design.

### 12.5 How to generate missing STL / GLB / views

**Not in MVP.** The shipped extraction pipeline does not produce these files for parts. Future work could:
- Use the SOLIDWORKS COM API to export STL during extraction (read-only — file system write but no SW model modification).
- Render view PNGs via a SW headless API call.
- Use a CAD-to-GLB tool (third-party) to produce the colored GLB.

These belong in a separate "extraction enhancements" plan, not the wizard's MVP.

### 12.6 How to handle customer library paths outside the repo root

**Open question that gates customer pilot.** The wizard, like the rest of the app, currently assumes `400S_Sorted_Library/` is at the repo root. For a customer pilot:
- Option A: customer runs the app from a folder that contains `400S_Sorted_Library/` (per the current convention).
- Option B: add a `LIBRARY_DIR` env var supported across the app and the wizard.
- Option C: per-wizard config that lets the operator point at a different library directory at intake time.

**Recommendation:** Option B — single env var honored by the entire app. Captured as a §12 next-action in `docs/production-pilot-packaging-checklist.md` (already listed). The wizard inherits whatever the rest of the app uses; no wizard-specific change needed.

---

## 13. Provenance

- Library file-shape conventions verified by inspection of `400S_Sorted_Library/parts/1020001/revA,revB/`, `parts/1015003/revA,revB/`, `parts/1030001/revA/`, `parts/1030010/revA,revB/`.
- Multi-revision parts confirmed: `1015003`, `1020001`, `1030010`, `1030011`, `1030014`, `1030016`, `1030017`, `1030100` (sample of those found).
- `/api/profiles` scan + cache behaviour verified from `ai_inspector/spatial/engine.py:294-319` (`_build_profile_index` / `list_profiles`) and `server.py:402-426` route.
- `/api/profile-details/{pn}` behaviour from `server.py:1608-1646` (`get_profile_details`).
- Drawing-map dual-location pattern from `ai_inspector/utils/drawing_map.py:20-84` (`find_drawing_map_path` + `find_drawing_map_revision_path`).
- Drawing-map readers across the app: `server.py:474, 1215, 1411, 3074-3075`.
- Assembly separation from part profiles confirmed via `server.py:181-246` (`_ensure_assembly_files`, `_load_assembly_profiles`).
- Bridge baseline + integration commits from `docs/bridge-part-assembly-app-integration-plan.md` §2 (app side `c2de55d`) + `InspectorPro.SolidWorks/docs/bridge-part-assembly-plan.md` §2.1 (bridge side `c043fbe`).
- `LIBRARY_ENTRY_GUIDE.md` verified ABSENT — memory was wrong; the implicit workflow is documented only as code conventions and the file-shape evidence in `parts/1020001/revA/`.
- `_batch_index.json` at library root verified (2026-02-12 batch ingestion catalog, 190 records, no current readers).
