# Factory 02: Layer 3 Process Movement

Date: 2026-09-29
Sheet: `fl-independent-factory-20260928` (Factory 02 - Integrated Production).

## Scope

This is an offline-authored, proposed operator-process layer over the independently built factory. It is not a new Sage capability or an approved production Process Map. No product drawing, bill of operations, demand, task times or handling loads were supplied.

Layer 1 supplies the departments, cells, equipment and circulation. Layer 2 supplies exact operator/workstation assignments, corrected operating-side positions, staging locations and robot-cell boundaries. The movement programs reuse those identities; they do not infer assignments by nearest equipment or change placement geometry.

The illustrative process context is receive/stage components, machine them where applicable, stage robot-cell work, kit and assemble, inspect, pack, then dispatch. **Only the local operator station visits below are executable in this slice.** Interdepartment material transfers, loading/unloading, process precedence, task dwell and machine/robot operation are not implemented by these paths.

## Executable Cycles

| Area | Actors | Ordered station visits, returning home | Computed round trip |
| --- | ---: | --- | ---: |
| Machining | 12 | Reviewed machine-side home, assigned tool cabinet, home | 11.383 m |
| Robot-cell staging | 12 | External attendant home, input staging, output staging, home | 14.088 m |
| Assembly | 8 | Bench-side home, kit cart, home, test bench, output lift, home | 56.554 m |
| Inspection | 4 | Workstation-side home, sample cart, gauging table, home | 31.178 m |
| Packing | 4 | Bench-side home, shipment staging, pallet truck, home | 24.964-29.732 m |

These are computed path lengths, not optimality claims. Operators do not enter robot enclosures. Fixed machinery remains stationary. No workpiece is carried or transformed by this presentation. Clearance is planar and catalog-derived, not a clearance/ergonomic/safety approval.

Forty revision-bound movement programs and derived approach anchors are stored in `extensions.facilityNavigation`. Every process assignment remains `inferred` / `pending`. Positions come from the existing navigation compiler, not handwritten waypoint coordinates. `extensions.facilityProcessPresentation` groups the programs and records their purpose, without granting process authority.

## Application Use

On Factory 02, choose **More > Saved movement**, leave **All saved movement (40 actors)** selected, then click **Play movement**. The paths are validated and all forty operators start together automatically. No department group selection is needed. Use the existing movement panel's pause, resume, scrub, rate, Paths, actor selector and Focus controls. Plan and 3D share the same presentation. Focus is a close-up, not camera following; zoom out to inspect a complete path.

Department groups remain optional: machining (12), cell staging (12), downstream assembly/inspection/packing (16). Individual programs and a supported selected-actor set are also available. Navigation presentations now allow up to 64 actors and 512 KiB of canonical scenario metadata; the older activity preset contract remains at 24 actors and 64 KiB. An oversized or invalid group is refused as a whole, never silently truncated. The default All option is offered only when the complete set is valid and within the bound.

Closing playback restores the original static actors. Preparation and playback do not Save, mutate geometry or alter editor history. Cancellation, stale drafts and candidate previews cannot install a late result. The app must be reopened/reloaded to receive the updated frontend; an already-open draft is not forcibly reloaded.

## Corrections Found During Verification

The first complete dry run refused the four inspection cycles. A cardinal access point was checked before rounding against an obstacle boundary already canonicalized to six decimals. Outward canonical rounding and checking the exact serialized point corrected the false refusal. The requested side, obstacle buffer and actual obstruction refusal remain intact. Compiler identity advances to `facility-navigation-compiler-v1.1`.

Native testing also caught the new command missing from the workspace's exported toolbar state. The command is now registered there as well as in the external ribbon. Playback actor labels now use placement instance labels, rather than twelve indistinguishable "Operator" entries.

The all-actor follow-up caught a second command-state bug: a camera or selection update during preparation could publish a disabled Saved movement command that stayed disabled after completion. Navigation preparation now publishes both its pending and terminal states, including refusal and cancellation. Regression tests reproduce the old failure and cover all three outcomes. `native08-all` preserves the failed replay check; it did verify all forty actors moving before the command-availability failure.

The first native screenshots were inadequate despite passing state assertions: one preceded settled paint, and a moving operator left the focused close-up. A later run attempted Focus before an animation frame had installed the actor pose. The isolated harness now waits for a usable pose, disables background throttling in the test window, frames the current pose, records projected mesh bounds, and compares pixels with the selected avatar hidden/restored. A large scene-wide pixel change fails the test rather than counting as visible avatar evidence. No application camera-follow or background-animation change is claimed.

## Verification and Publication

- Engine: all **40/40** journeys accepted through public compile/plan APIs on the isolated saved copy. No trusted-draft shortcut or failed-path override.
- Regression coverage: **108 distinct focused Python tests** and **256 JavaScript checks** passed across authoring, guarded publication, precision, navigation contracts/planning, service, workspace, renderer, session and navigation authoring. Reruns are not added to these counts.
- Final native checks passed in the normal desktop application against an isolated store: `native06-focus` covers Q1 inspection and R01 staging; `native07` covers the 12-person machining group and A01 assembly. Real ribbon selection, preparation, Play/Pause, changed actor positions/gait, scrubbing, Plan/3D switching and closing playback were exercised. Native window sizes were 1440 x 900 and 900 x 700 logical pixels; Windows scale produced 1800 x 1125 and 1125 x 875 captures.
- Final avatar visibility checks measured 2,828-6,832 changed viewport pixels when hiding the selected avatar. Screenshots were visually inspected. No duplicate source actors were visible, no editor document/history edits occurred, saved bytes were unchanged, and both final native runs made **zero Save calls**. Owned backends and Electron test processes exited with cleanup confirmed.
- Live publication completed with **one revision-guarded Save**, targeting Factory 02 only. All 836 placements (including operators and walls), 58 zones, 9 routes and 90 markings remain unchanged. The original manual layout remains byte-for-byte unchanged.

### All-Movement Follow-Up

- **93 focused Python tests** and **222 JavaScript checks** passed for the revised navigation limits, canonical byte budget, sampler parity, transport, workspace and renderer. These are follow-up suite totals, not additions to the historical totals above. The JavaScript suites comprise 99 workspace, 30 transport and 93 renderer checks.
- `native08-all` validated and auto-started all 40 through the actual Saved movement control. Between 0.4488 and 1.2643 display seconds, **40/40 actors moved**, with minimum displacement 0.8155 m. No duplicate source operators were visible. The run then failed reopening the command; the stale disabled-state defect was fixed and regression-tested.
- `native09-all` loaded all 40 on the fixed application and confirmed the command was enabled. The selected avatar contributed 6,096 visible pixels. Auto-play had advanced to 2.7994 seconds before the harness paused it; the old absolute `elapsed > 1` wait therefore resumed and paused immediately, failing its movement assertion. The harness now waits for an additional 0.75 display seconds relative to the actual start, and records per-run movement count and minimum displacement. This failed run is not reported as a complete passing test.
- `native10-replay` passed the complete corrected replay check: prepare/auto-play R01, pause/resume and verify displacement, switch Plan/3D, close, reopen Saved movement, prepare/auto-play A01, scrub, focus, and capture at 1440 x 900 and 900 x 700 logical pixels. Preparation took 24.945 and 24.231 seconds respectively. Avatar pixel checks ranged from 2,945 to 6,832 pixels; the wide and narrow captures were visually inspected. The editor stayed clean, before/after saved hashes matched, zero Save calls occurred, and owned backend/Electron shutdown was confirmed. This narrower replay run complements the earlier all-40 movement evidence; it does not relabel either failed all-actor run as a full pass.
- The all-movement follow-up changes playback code and limits only. It makes no Save call or live layout publication; the published Factory 02 and original manual hashes remain those listed below.

Publication receipt: `dry06/publication.json`.

| Binding | Revision / SHA-256 |
| --- | --- |
| Factory 02 before Layer 3 | `a217107d22b3d78b6fa186d532138d8d8a169280c47a1a39d4a568eb2dcac3a0` |
| Isolated validated candidate | `6d5e1c37c3828917909d390c17f3189adc7ac9c4d3664f1fe00a533385f57691` |
| Published Factory 02 | `4fafb486dcb067fb4067771a9d34cf9b58f2f5125baf5733be182c373d3830d6` |
| Unchanged original manual | `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088` |

The published revision differs from the isolated candidate because Save updates its timestamp. The document content was checked against the authored candidate before publication. Playback recompiles against the active saved/draft revision; old validation receipts are not installed as current runtime paths.

Evidence: `.runtime/factory02-layer3-20260929/`. `dry05` preserves the refused inspection journeys. `dry06` contains the accepted forty-program sweep, original document backup, candidate, semantic operations, per-program receipts and dependency report. Native runs retain their reports, screenshots and managed-backend cleanup receipts.

Authoring tool: `tools/build_independent_factory_layer3.py`. Default is isolated validation; `--apply` validates before guarded Save. `--publish-validated` checks the unchanged source hash, exact candidate intent and every accepted revision-bound journey before publishing an already-validated copy. Live publication targets Factory 02 only; no sheet is created and the original manual layout is not edited.

## Performance and Remaining Work

Cold path preparation is still slow: the isolated forty-actor sweep took 859.032 seconds in aggregate, with individual requests taking 12.009-54.670 seconds. The final native run prepared twelve machining actors in 116.197 seconds and then A01 in 7.718 seconds. Earlier twelve-person runs took 163.723 and 331.007 seconds; the separate focused run took 61.648 seconds for Q1 and 39.221 seconds for R01. These are observations under varying local load, not a benchmark or p95 claim; do not describe this as instant/demo-ready preparation. Cancelling preparation discards late results but does not terminate a backend computation already in flight.

The all-actor follow-up reuses each actor's sampled pose across pairwise proximity diagnostics, preserving sample times, pairs, minimum-distance values and tie ordering. At 40 actors and 101 samples this reduces pose-sampler calls from 157,560 to 4,040. This is an ephemeral calculation optimization, not an authority cache or reduced route validation. It does not remove the sequential path compilation/planning cost. `native08-all` took 207.208 seconds and `native09-all` took 852.556 seconds to validate and auto-start all forty operators. Their subsequent failures are retained separately above. This large observed variation is an unresolved preparation-performance limitation, not a bounded latency guarantee.

The next process layer needs an agreed product/route, explicit interdepartment transfer demand, transport assignments and applicable vehicle/load evidence. Material handoffs and traffic coordination must be validated separately. Playback's common clock and synthetic walking speed do not establish throughput, staffing, production timing, collision avoidance between actors or regulatory compliance.
