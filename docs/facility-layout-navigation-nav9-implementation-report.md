# Facility Layout NAV9 Implementation Report

Date: 2026-09-01

Status: Implementation complete; production promotion held for explicit
reference-layout review

## Scope

NAV9 closes the implementation and hardening path for deterministic Facility
Navigation. It qualifies the NAV1-NAV8 contracts, Plan authoring, immutable
navigation snapshots, pedestrian and vehicle journeys, handoffs, shared-clock
activity presentation, Sage's coordinate-free intent surface, persistence,
feature gating, performance, and browser behavior.

This report does not grant human authority. The archived manual factory remains
the evidence source and was never modified by qualification.

## Implemented Result

- Durable `extensions.facilityNavigation` intent remains in canonical layout
  bytes; snapshots, journey solutions, handoffs, and activity scenarios remain
  immutable derived artifacts.
- Plan pointer authoring owns coordinates. Sage can select semantic actors,
  stops, routes, policies, and existing constraint IDs, but cannot author path
  coordinates through chat.
- Complete authored overrides now contribute every required point to navigation
  scope selection. A path may leave a small home cell when a containing
  department or floor region supports the complete route; anchor-only automatic
  routes retain their local scope.
- Pedestrian free space is compiled from post-union, deterministically expanded
  obstacle geometry. Vehicle planning reuses directional lanes, an exact
  revision-bound profile, and sampled swept-volume validation.
- Existing actor identities and exact catalog visuals are borrowed for playback;
  source visuals are suppressed and restored without duplicates.
- Feature dependencies fail closed from contract through Sage write. The legacy
  rectangle-loop builder is inaccessible from production entry points and
  remains available only behind the explicit prototype-fixture switch.
- Navigation survives Save/reopen byte-equivalently and one Undo restores the
  exact prior draft.

## Deterministic Qualification

The NAV9 property suite proves:

- 100 of 100 randomized accepted pedestrian routes remain within canonical free
  space and do not enter obstacle interiors;
- five of five disconnected cases return the same `unreachable` result on
  repeated planning;
- feature stages cannot be enabled out of dependency order;
- production calls cannot reach the legacy rectangle-loop implementation; and
- persisted navigation reopens with identical canonical bytes.

The complete NAV9 test file passes 12 of 12 checks.

## Performance

The 20-run frozen-machine evidence in
`tests/fixtures/facility_layout/navigation/nav9-performance-v1.json` passes all
budgets:

| Measurement | p95 | Limit |
| --- | ---: | ---: |
| Cold reference snapshot compile | 4,680.9358 ms | 5,000 ms |
| Warm snapshot lookup | 1.7851 ms | 100 ms |
| Local pedestrian query | 64.0432 ms | 1,500 ms |
| Single vehicle query | 63.9429 ms | 5,000 ms |
| Complete bounded 16-actor scenario | 309.6514 ms | 60,000 ms |

The cold compiler retains all frozen NAV0 geometry and route fingerprints. Its
lineage lookup now uses a spatial index, and triangle ordering uses the same
canonical key without repeatedly invoking general polygon validation.

## Browser Evidence

`tests/fixtures/facility_layout/navigation/browser/nav9-browser-evidence-v1.json`
records one end-to-end run on a disposable clone of the manual reference:

- one Plan-authored operator loop validated and remained unsaved;
- snapshot compilation and journey planning returned `accepted`;
- the same pose was shown in Plan and 3D;
- the exact existing operator catalog visual was loaded and its stationary
  source was suppressed;
- eight nonblank screenshots cover Plan/3D, light/dark, and 1920 x 1080 /
  430 x 932 viewports;
- the compact mobile view hides the Geometry inspector while motion controls are
  active, preventing the two surfaces from overlapping;
- Edge 152 on Intel UHD D3D11 rendered 2,031 frames in 60 seconds, or 33.85 FPS;
- playback changed no layout operation or base revision;
- one Undo removed the authored navigation and restored the exact blank
  navigation state; and
- no browser error, failed request, or 5xx response occurred.

The proof images are stored beside the evidence JSON with the `nav9-` prefix.

## Reference Acceptance Boundary

`tests/fixtures/facility_layout/navigation/nav9-reference-acceptance-v1.json`
enumerates every frozen candidate without omission:

- 12 operator candidates;
- four vehicle candidates;
- seven handoff candidates; and
- zero omitted candidate cases.

All review receipt arrays remain empty. Vehicle candidates fail closed with
`facility_navigation_vehicle_profile_unavailable` until exact published profile
authority exists. The complete reference activity scenario is intentionally not
built, and production promotion remains in
`promotion_held_review_pending`. The required reviewer is Shadrack in the role
of InspectorPro product owner and reference-layout author.

## Regression Result

- Python navigation, service, API, agent-runtime, integration, and host suite:
  330 passed.
- JavaScript workspace, Three.js adapter, transport, session, navigation
  authoring, P11, and chat-stream contracts: 243 passed.
- NAV9 browser assertions: 15 passed.
- Manual reference SHA-256 before and after:
  `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`.

The only pytest warning was the existing Windows `.pytest_cache` path warning;
the isolated `--basetemp` run completed successfully.

## Claim Boundary

The implementation proves deterministic geometry, identity preservation,
revision binding, persistence, refusal behavior, and synchronized playback. It
does not prove safety, staffing adequacy, throughput, timing feasibility,
regulatory compliance, or operational optimality. Playback remains qualified
prototype presentation until the named reference review is explicitly recorded.
