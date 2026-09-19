# Agent handoff

Routing document for an agent picking up work in this repo. Last updated
2026-09-19. Details live in `docs/`; this file only points at them and lists the
constraints that are expensive to discover by accident.

## Active task

**`docs/task-generation-research-source-cards.md`** -- render the generation
workflow's research results as clickable source cards in the chat pane. Scope is
one wiring gap; the click path (chat link -> in-app browser -> PDF download) is
already built end to end. That document carries the exact contracts, the
confirmed seam in `server.py`, the field mapping and the non-goals. Read it
before touching anything in the generation path.

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

`desktop/` uses `npm test` (`node --test tests/*.test.cjs`). Python tests are
pytest-style with bare module-level asserts. Confirm the runner in use before
reporting counts, and report what actually ran rather than an expected total.
