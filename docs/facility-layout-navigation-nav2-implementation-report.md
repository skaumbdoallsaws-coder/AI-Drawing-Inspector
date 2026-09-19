# Facility Layout NAV2 Implementation Report

Date: 2026-09-01

Status: Implemented and verified in explicit prototype mode. No human
authority, production eligibility, safety approval, or regulatory claim was
granted.

## Scope

NAV2 adds manual Plan-authored movement paths without making the model the
owner of geometry.

Implemented:

- one `Motion Path` Plan tool for existing operator and vehicle placements;
- UI-authored waypoints, semantic anchors, loop mode, direction, locked
  segments, insertion, deletion, reversal, and exact Undo;
- authoritative server validation before one unsaved navigation gesture;
- pedestrian footprint containment and obstacle intersection checks;
- vehicle validation against one exact published revision, or an explicitly
  enabled non-production prototype revision;
- red invalid segments that remain visible but cannot be accepted as validated;
- one shared Plan/3D preview pose and independently hideable path overlays;
- exact borrowing of the selected placement's catalog GLB with the stationary
  source visual suppressed; and
- gold-case export for later NAV4/NAV5 review fixtures.

## Authority Boundary

Only pointer input in Plan writes path coordinates. Chat and deterministic
generators cannot call that coordinate-authoring path. Applied navigation
intent remains pending review and unsaved until the user invokes Save.

The prototype vehicle path used by browser acceptance is guarded by all of the
following: server prototype mode, request `prototypeMode: true`, an exact
revision, `prototypeMode: true` on the authority document, and
`productionEligible: false`. Its qualification states that the operating
limits are synthetic.

## Browser Evidence

The acceptance run cloned the archived 45-zone, 8-route, 827-placement,
50-marking reference into a temporary scratch layout. The scratch was archived
after the run; the reference was never written.

All fourteen checks passed:

- invalid path visible and not authored;
- operator complete override validated;
- vehicle complete override validated;
- exact operator and vehicle catalog visuals used;
- source placement suppressed with zero duplicate actor visuals;
- Plan and 3D actor poses agree;
- paired-lane return mode preserved;
- path visibility toggles independently;
- Undo removes only the latest vehicle gesture;
- Save/reopen is byte-equivalent;
- zero page or console errors;
- zero failed HTTP responses; and
- reference archive unchanged.

Evidence:

- `tests/fixtures/facility_layout/navigation/browser/nav2-browser-evidence-v1.json`
- `tests/fixtures/facility_layout/navigation/browser/05-nav2-invalid-operator-segment.png`
- `tests/fixtures/facility_layout/navigation/browser/06-nav2-operator-loop-plan.png`
- `tests/fixtures/facility_layout/navigation/browser/07-nav2-operator-loop-3d.png`
- `tests/fixtures/facility_layout/navigation/browser/08-nav2-paired-lane-vehicle-plan.png`
- `tests/fixtures/facility_layout/navigation/browser/09-nav2-paired-lane-vehicle-3d.png`

The receipt stores bounded identities, outcomes, fingerprints, counts, and
qualifications rather than duplicating the full layout and swept-volume sample
arrays.

## Verification

- NAV0/NAV1/NAV2, navigation validation, service, and API: 61 passed;
- Three.js adapter: 64/64 passed;
- Facility workspace: 72/72 passed;
- Facility transport: 13/13 passed;
- navigation authoring: 6/6 passed; and
- Playwright browser acceptance: 14/14 passed.

The archived reference SHA-256 remained:

`a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`

## Remaining Boundary

NAV2 validates paths the user draws. It does not yet derive traversable graphs
or choose routes. NAV3 owns the immutable navigation snapshot compiler; NAV4
and NAV5 own deterministic pedestrian and vehicle route selection.
