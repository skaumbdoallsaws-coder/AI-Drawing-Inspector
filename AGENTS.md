# Agent handoff

Routing document for an agent picking up work in this repo. Last updated
2026-09-23. Details live in `docs/`; this file only points at them and lists the
constraints that are expensive to discover by accident.

## Active task

**`docs/task-generation-research-source-cards.md`** -- render the generation
workflow's research results as clickable source cards in the chat pane. Scope is
one wiring gap; the click path (chat link -> in-app browser -> PDF download) is
already built end to end. That document carries the exact contracts, the
confirmed seam in `server.py`, the field mapping and the non-goals. Read it
before touching anything in the generation path.

## Recently landed

**Facility Layout structure tree** (`docs/facility-layout-structure-tree-plan.md`,
section 7a). A SolidWorks-style pane in the left slot showing zones and their
equipment, derived geometrically - zone membership is never written into the
layout. FT0-FT4 are complete and FT5 is complete in the browser; the Electron
half is an open gap recorded in the plan.

Three things an agent touching this should know:

- `tests/verify_facility_layout_structure_tree_app.py` drives a real browser
  against a local server and is the **only** place the workspace wiring is
  exercised. Three defects reached the app while every unit test passed,
  because unit tests feed the renderer a model directly. Run it after changing
  `_structureRepresentedLayout`, `Workspace.structureSource`, or the generation
  view's `activeLayout` / `activePreviewRef`.
- `generationPlanningView.activeLayout()` returns the candidate **layout
  document**, not a wrapper, and carries no identity. `activePreviewRef()` was
  added beside it for callers that must tell one candidate from another. It is
  additive and read-only; do not fold it into `activeLayout()`.
- Two authoritative server rules constrain any layout-authoring test: a
  placement whose footprint leaves the shell floor is rejected
  (`placement_outside_floor`), and **once any zone exists every placement must
  be inside a zone** (`zone_containment_violation`). Unzoned is therefore
  authorable only before the first zone or after the last one.

## Where the larger work stopped

**`docs/sage-research-layout-implementation-report.md`** is the honest status of
Sage's facility-layout generation. Its "Remaining gates, in order" section is
the work queue. Work halted on provider credit exhaustion, not on a design
problem -- six of seven live runs failed on real defects that were then fixed,
and the last two never reached the tools.

Gate 1 needs live provider access. Do not substitute local mocks as proof of a
live research-to-preview pass.

## Constraints that are costly to violate

**Do not commit the large generated trees.** These are untracked but *not* in
`.gitignore`, so a `git add -A` pulls them straight into permanent history:

| Path | Size | Why it stays out |
| --- | --- | --- |
| `generated/industrial_assets/local_library` | 1.3 GB | Private asset library |
| `generated/engine_motion` | 135 MB | Regenerable exports |
| `output/` | 86 MB | Third-party manufacturer PDFs |
| `tests/fixtures` (bulk) | 99 MB | Only already-tracked files belong |

Adding `.gitignore` entries for these is an open decision, not yet made.

**Do not rename internal agent keys.** `inspector`, `deviation-analyst` and
`parts-finder` are persisted in the chat registry as `agentType` and key
`agentSessionId`. Renaming them breaks restore of saved conversations.
`server.py`'s `_SKILL_PUBLIC_TO_INTERNAL_AGENT` maps the public names (`iris`,
`sage`, `scout`) onto these keys and is the correct place for that translation.

**Never hardcode an agent display name.** Resolve through
`AGENTS[currentAgent].name`. A hardcoded `Message Iris...` in markup was a real
bug: it survived into restored Sage and Scout conversations and named the wrong
agent. Sage is now the default agent via the `DEFAULT_AGENT_KEY` constant.

**Keep new strings ASCII** in `server.py` and `static/index.html`. Both files
have had mojibake repaired before; non-ASCII literals are how it returns.

**Sage and the in-app browser are separate on purpose.** Sage fetches
provider-side (`ai_inspector/research/web.py`, using the provider's own
search/fetch tools); the Electron research pane is human-driven and has no
content-extraction command. That boundary keeps the pane's logged-in cookies
away from the model. Do not bridge them.

**The desktop shell is real and pinned.** Electron 44.3.0, Node >= 22.12.
`desktop/README.md` documents the isolated-snapshot launch procedure; the
rendering backend refuses to run from the live checkout.

## Repository state

- Active branch is **`ui-bridge-telemetry-unified-2026-05-18`**, not `main`.
- Commit `a442754` (2026-09-19) checkpointed ~1065 files after a **stale
  `.git/index.lock` from 2026-08-30 had silently blocked every commit for 20
  days**. If `git` reports "Another git process seems to be running", check the
  lock's age and whether a git process actually exists before waiting on it.
- `static/index.html` is ~90k lines and shifts often. Prefer grepping a quoted
  code string over trusting a line number from a document.

## Tests

**No flashing terminals on Windows.** The user is working in other apps.
Prefer in-process file reads. Launch commands directly through pythonw.exe
and tools/run_hidden.pyw (CREATE_NO_WINDOW), without an intermediate
PowerShell/cmd window. Use redirected output and windowsHide on the parent
spawn as well. Background helpers must never open visible console windows.

`desktop/` uses `npm test` (`node --test tests/*.test.cjs`). Python tests are
pytest-style with bare module-level asserts. Confirm the runner in use before
reporting counts, and report what actually ran rather than an expected total.
