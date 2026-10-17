# Factory 02 Dispatch Office

## Saved Change

Added an open-plan two-person office inside `06 Finished Goods + Dispatch` on
`fl-independent-factory-20260928` (Factory 02 - Integrated Production).

- Office zone: `zn-independent-dispatch-office`, X 55-63 m, Z 7-15 m.
- Two existing 1400 mm desks, two chairs, two monitors, two keyboards, two mice,
  two desktop computer cases and two telephones: 14 new placements, 850 total.
- Eight desktop items attach to the desks' explicit `worktop` support surfaces.
- Chairs face the screens; mice are on the seated user's right. Facing was
  checked against the actual GLBs and the Electron close-up, not asset labels.
- A 1.5 m pedestrian connector at X 62 runs from the office to the existing
  South Pedestrian Promenade. Existing racks, pallet staging and aisles stay put.
- No laptop model exists in the published local catalog; desktop models were used.
- This is an open office area, not an enclosed office or certified access design.

Base revision: `4fafb486dcb067fb4067771a9d34cf9b58f2f5125baf5733be182c373d3830d6`.
Saved revision: `e8433641ed1c870b23aed9bd71c87c762a919f877c8d423aa25a27e3f7ceb9eb`.

All 836 previous placements, existing zones/routes/markings, perimeter walls,
process bindings and the complete navigation/presentation extensions are unchanged.
The 40 movement-program definitions remain intact; full movement compilation and
simultaneous playback were not rerun for this furniture-only addition.
The original manual reference remains byte-identical (SHA-256
`a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`).

## Verification

- Real kernel: zero placement collisions, shell collisions, obstructed aisles or
  spatial errors. Existing unverified-clearance findings remain unverified.
- Independently checked worktop containment/elevation, zone containment,
  preservation, empty office floor, unobstructed pedestrian corridor and its
  connection to the existing promenade.
- 37 focused Python tests passed (office, perimeter and CNC-side checks).
  All 13 office tests were rerun and passed after the final mouse/phone adjustment.
- Normal Electron application on an isolated store: final candidate matched the
  saved document, all seven furniture asset types rendered actual meshes, zero
  transform-audit mismatches, screenshots at 1440x900 and 900x700 logical pixels.
  Canvas-pixel diversity checks passed; overview/detail/narrow images were inspected.
- Native test processes exited and managed backend cleanup was confirmed.
- Live publication used the existing revision-checked Save service. The resulting
  document was compared with the reviewed candidate, allowing only Save's timestamp.

Evidence is under `.runtime/factory02-office-20260930/`:

- `dry03/before.json`: exact backup before publication.
- `dry03/operations.json`, `candidate.json`, `validation.json`, `report.json`,
  `saved.json`: final operations, validation and guarded publication.
- `native02/report.json` and screenshots: final native verification.
- `native02/runtime/last-application-run.json`: confirmed cleanup receipt.

`dry02` encountered an existing spatial-worker timeout during isolated Save.
The subsequent `dry03` retry passed with the same checks and timeout; no timeout
fix is claimed. Earlier `native01` verified the initial arrangement, but its first
overview was taken after an asynchronous auto-fit. `native02` frames the office
after initial loading and verifies the final arrangement.

## Ownership And Limits

The change reuses existing asset definitions, geometry validators, attachments,
zones, aisle operations and Save. No renderer, catalog definition, structure-tree
code or Sage capability was changed. No provider request was sent.

`tools/add_factory02_dispatch_office.py` defaults to isolated validation. Its
publication mode rejects a changed base, changed candidate or repeat publication.
This is a one-layout authoring utility, not a general office-layout planner.

There is no electrical, acoustic, ergonomic, accessibility, fire, traffic-safety
or regulatory qualification. The open office is visible after reopening Factory
02; an already-loaded window is not forcibly reloaded or closed by this task.

## Office Fans Added 2026-10-01

Added two catalog floor fans (`asset-floor-fan-white`) at X 58.8 m,
Z 7.8 and 14.2 m, aimed toward the corresponding workstations. Factory 02 now
contains 852 placements. All 850 previous placements and every other layout
field remain unchanged except the Save timestamp; the manual reference hash
above is unchanged.

Saved revision: `247b9723ef009d5788ce6717e7d5df635fd70b899b477f8ccf564e5ccacf3f7c`.

- Minimum footprint separation from existing equipment: 1.006 m; minimum gap
  from route corridors: 1.996 m. Both fans are inside the office without
  intersecting markings. Kernel checks found no placement/shell collision,
  obstructed aisle or spatial error. These are geometric checks, not certification.
- 17 office/fan Python tests and all 96 Three.js adapter checks passed.
- First native inspection found deferred footprint boxes instead of fan meshes.
  Camera-view changes and toolbar zoom now trigger the existing bounded visible
  mesh loader, just as mouse navigation already did; loading budgets are unchanged.
  Two regression tests cover these paths without requiring asset selection.
- Final isolated Electron inspection verified actual fan meshes at wide and
  narrow sizes, five canvas-pixel checks, zero placement-transform mismatches,
  and confirmed backend cleanup. Overview and narrow screenshots were inspected.
- Publication used the existing revision-checked Save service. The live result
  matches the reviewed candidate except its Save timestamp. No provider calls
  were made; the user's running app was not forcibly closed or reloaded.

Evidence: `.runtime/factory02-office-fans-20261001/dry01/` and `native02/`.
The earlier `native01/` capture is retained as failed visual evidence, despite
its weaker automated check having passed. The native verifier now requires
actual overview/detail representations, not merely a non-proxy representation.
`tools/add_factory02_office_fans.py` is a guarded one-layout authoring utility,
not a general planning capability. Restart InspectorPro and reopen Factory 02
to load both the saved additions and the renderer update.
