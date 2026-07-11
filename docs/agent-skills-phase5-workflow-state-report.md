# Agent Skills Phase 5 Workflow State Report

Date: 2026-07-10

## Scope

Phase 5 adds bounded multi-turn continuity to the first Sage workflow. It persists semantic workflow progress while keeping the live browser viewport authoritative. It does not replay highlights, visibility, rotation, or motion after a refresh.

## State Contract

`workflow-state.schema.json` defines the versioned browser/server mirror. Each state contains:

- workflow ID, version, status, stage, and objective
- resolved part, characteristic, feature, assembly, and motion-group entities
- evidence references and recent semantic referents
- completion milestones and bounded execution receipts
- asset fingerprint, revision, timestamps, and expiry

`WorkflowStateStore` is a thread-safe TTL/LRU store keyed by the stable browser chat-session ID. The default inactivity TTL is 30 minutes and the default bound is 512 sessions. Both limits are configurable. Expiry, abandonment, and asset invalidation remove semantic state without touching the viewport.

Production and shadow routing use separate stores. Shadow continuity cannot leak into a later production route or a browser session.

## Asset Reconciliation

The asset fingerprint is derived from part and assembly identity, revisions and configuration, the FAI drawing-map revision, motion-package IDs, and the pinned motion asset. It deliberately excludes the active tab and all live viewport state.

On every production Sage turn:

1. the server validates the browser mirror against the registered workflow and current asset fingerprint
2. pending browser receipts reconcile into the server state
3. a matching server state resumes, or a valid mirror restores after a server restart
4. an asset mismatch invalidates all old referents
5. the selected semantic route advances the workflow

The browser persists the chat-session ID and semantic mirror through the existing chat registry. A new or cleared chat rotates the ID and starts with no workflow state.

## Continuation Resolution

The semantic router receives recent turns plus the compact active workflow state. Deterministic code then resolves omitted continuation targets only against current live target IDs. It never adds an unauthorized effect.

Implemented follow-up behavior includes:

- a motion explanation records a unique motion group only when live package metadata marks exactly one group as FAI/affected
- `Show it` can continue that validated motion referent across a tab change
- `Bring that back` resolves the last named part and clears only its display override
- `Also add the crankshaft` resolves the current named part and uses additive highlight semantics
- stale or ambiguous IDs are not carried into a new asset or workflow

The raw-message action gate remains permanent. A resolved skill action still requires an explicit command in the current message, and the browser repeats the authorization check before execution. A read-only question cannot inherit a prior turn's side effect.

## Registered Executors

Phase 5 extends the fixed executor catalog with generic, data-resolved recipes for:

- hiding resolved parts
- revealing resolved parts
- restoring all display overrides and highlights
- clearing highlights

Executor ownership now strips conflicting model actions across the entire highlight, display, motion, or rotation domain. Hide, reveal, and additive highlight preserve active package motion.

## Receipt and Completion Rules

A requested visualization succeeds only when every required effect has a successful browser receipt. A highlight receipt alone cannot complete a highlight-plus-motion request. Receipt reconciliation is idempotent.

The workflow completes only when a failed characteristic is identified, a disposition is grounded, any requested visualization has succeeded, and no clarification is pending. Explicit cancel, abandon, end-workflow, forget, and start-over phrases remove the active state through a narrow deterministic rule.

## Live Defects Found

The live continuity smoke exposed four integration defects that isolated tests did not reveal:

1. An older part-feature fast path intercepted `Show it` and highlighted the crown dome. Selected workflow turns now bypass that legacy fast path.
2. The permanent action gate did not recognize a resolved pronoun command or additive `add/include` wording. Shared server/browser authorization vectors now cover both.
3. The server generated the correct highlight-plus-motion executor, but the browser's legacy motion strip removed `play_motion` because the raw phrase contained no motion noun. The browser now accepts a validated skill motion effect only when the raw message independently passes its explicit-action gate.
4. `Add [named part]` was interpreted as visibility restoration instead of additive selection. A generic route-semantics normalizer now separates selection from display restoration.

## Verification

- Frozen and Phase 5 Python checks: 164/164
- Browser authorization and intent mapping: 119/119
- Browser receipt runtime: 8/8
- Browser workflow persistence contract: 8/8
- Embedded application scripts: 7/7 syntax checks
- Full synthetic semantic-route evaluation: 27/27 valid routes
- Workflow, viewport-effect, asset-effect, skill, and continuation accuracy: 100%
- Speech-act accuracy: 96.3% (threshold passed; the one mismatch remained read-only)
- Live Phase 5 Playwright continuity workflow: 22/22

The live workflow verified read-only behavior, tab-independent `Show it` continuation, affected-group playback at 30 RPM, motion-preserving hide/reveal/add commands, receipt reconciliation, semantic-only refresh restoration, post-refresh continuation, and stale-state invalidation after a part change.

## Operational State

Phase 5 is production-capable behind `INSPECTORPRO_SKILLS_ENABLED`. The normal safe posture remains `INSPECTORPRO_SKILLS_ENABLED=0` and `INSPECTORPRO_SKILLS_SHADOW=1` until serial router latency is optimized and remeasured.

Phase 5 exit gate is met: follow-up behavior remains correct across tab changes, chat-session turns, page refresh, and asset changes without replaying stale viewport effects.
