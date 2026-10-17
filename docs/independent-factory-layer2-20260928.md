# Factory 02: Layer 2 Functional Review

September 28, 2026. This is a review and correction of the independently
authored factory sheet, not qualification of a new Sage planning capability.

**Subsequent correction:** the user identified six CNC operators on the wrong
machine side. The center-facing test below did not detect it. A four-sided CAD
review confirmed the controls/loading opening on local -Z; the six CNC machines
were rotated 180 degrees. See [CNC-side follow-up](independent-factory-cnc-side-20260928.md).
The historical Layer 2 evidence below remains unchanged; its final revision was
superseded by `4d3d7213064ee5a999e3b14e8771aff648e7dddf2b1d80515a33bb80cddabc7c`.

## Result

The review found and corrected demonstrable heading, workstation-position and
floor-communication problems. It did **not** establish that the factory can run
a manufacturing process safely or that its robot tasks are reachable.

- Layout: `fl-independent-factory-20260928`, Factory 02 - Integrated Production.
- Before: `a6454eb6812b8f1798a0eab50b33bfa0313ae9a242c8ad15a8b64fa60733e250`.
- After: `5d6e4bbf96076a6752abfab93d7d763c3a9e0be6962c9bbafac6f17082239517`.
- 830 placements, 52 zones, 9 aisles, now 90 floor markings (previously 85).
- All placement IDs, all 790 non-operator placements, all zones and all aisles
  remain unchanged. No catalog definitions were changed.

## Corrections

| Finding | Change | Verified boundary |
| --- | --- | --- |
| Twelve machining operators faced away from their assigned machines. | Turned them 180 degrees. | Canonical standing-avatar forward is +Z; each now faces its machine origin. The actual machine operating side remains unknown. |
| Twelve robot attendants faced along the outside fence rather than toward the loading gate. | Moved them to the outside south approach, beside the staging boxes, and turned them toward the gate. | Full footprints remain in their cells and outside every keep-clear marking. This is an observer position, not an approved robot operator station. |
| Sixteen assembly, inspection and packing operators stood well back from the workbench. | Moved them to a 0.4 m footprint gap. | The standoff is an explicit illustrative design assumption, not an ergonomic or reach standard. |
| Native close-up review then showed four inspectors behind the laboratory workstations. | Moved those four to the visible +Z drawer/workbench side and turned them toward the work surface. | Side selection is CAD-inferred, not an authoritative manufacturer interface. This finding was not detected by the geometric heading test. |
| All 60 equipment boxes rendered the default PARKING text, including WIP and process staging. | Applied INPUT, OUTPUT, WIP, KIT CART, FORKLIFT, CRANE, LIFT, CART, TOOLS or WORK AREA as appropriate; corrected parking/staging roles. | Each box fully contains exactly one identified equipment footprint. |
| Three crosswalks were centered on vehicle junctions rather than the pedestrian paths. | Replaced them with eight crosswalks derived from the actual perpendicular pedestrian/vehicle intersections. | Width follows the pedestrian corridor; length spans the vehicle corridor plus an authored 1 m overrun at each end. These are not compliance dimensions. |

The two passes comprise 32 translation operations, 28 rotations, 60 marking
edits, three marking removals and eight additions. Twenty-eight distinct
operators changed position; four were refined twice after visual inspection.
Equipment quantities were not inflated.

## Coverage

Every placement and zone was included in the structured audit. Hierarchical
zone counts overlap; the eight top-level department totals sum to 830.

| Area | Placements | Checked | Still unresolved |
| --- | ---: | --- | --- |
| Receiving and raw stock | 100 | Six rack rows, containment, parking occupants, static aisle obstruction | Rack loading faces, pallet/load requirements, forklift turning and dock interfaces |
| Machining and fabrication | 56 | All four machine rows, twelve operator headings, eight WIP boxes | Authored loading/control sides, door swings, stock feed, service clearances and actual operations |
| Toolroom | 12 | Shelf/bench containment and static separation | Tool inventory, usable support capacity and retrieval workflow |
| Robotic production | 504 | All twelve 42-placement cells, gate keep-clear occupancy, attendant headings, staging identities, twelve fixture-support relationships | Robot reach, base/TCP frames, payload, task poses, guarding/interlocks and task-specific access |
| Assembly and kitting | 48 | All eight cells, bench standoff, kit-cart boxes, containment | Product, operations, tooling, ergonomic reach and lift capacity |
| Inspection and packing | 32 | All four inspection and four packing stations, operator positions and output boxes | Inspection instruments/tolerances, packing process and handling requirements |
| Finished goods and dispatch | 66 | Six rack rows, containment, forklift parking and static obstruction | Loading access, truck paths, dock identity and handling capacities |
| Equipment service | 12 | All twelve bay occupants and correct purpose labels | Crane envelopes, setup/stabilization, service access and utilities |

The report records each zone's stable ID and direct members, every operator's
target, every box's occupant, each crossing's two route IDs, every attachment,
and exact-revision readiness projections for all 36 asset types. No placement
`zoneId` was added.

## Verification

- 51 focused Python checks passed: 21 new audit tests and 30 operation tests.
- Authoritative service: zero placement collisions, shell-obstacle collisions,
  obstructed aisles or spatial errors after correction.
- All 40 operator heading checks pass; all 16 bench standoffs match the stated
  assumption; no operator intersects a keep-clear marking.
- All 60 equipment boxes and eight crossings pass their stated checks.
- All ten lane arrows remain inside the main aisle and match their labels.
- All twelve tooling plates remain supported geometrically at their support
  heights. Their mounting/load capacity is not approved by this check.
- All 40 operator centers connect geometrically to the pedestrian network in a
  static free-space probe using a 0.35 m radius. The probe allows unmarked floor
  travel and does not prove an approved walking route, traffic separation,
  headroom or egress.
- Final native Electron check passed against the saved revision: 830 matching
  placement transforms, 7,420 instance matrices, no missing placements,
  renderer warnings or degraded state. Float32 storage comparisons match;
  ordinary double-to-Float32 quantization is recorded separately.
- 62 native captures include all 52 zones and six oblique detail views. Sixty
  visible 3D captures passed canvas-only pixel-diversity checks. Zone contact
  sheets were visually reviewed, and the inspection close-up was rechecked
  after the CAD-inferred correction. Captures do not establish machine limits;
  existing level-of-detail proxies remain in some views.
- Original and corrected saved-layout hashes were unchanged throughout native
  review. Switching between the manual sheet and Factory 02 passed. The final
  review window remains open on the corrected Factory 02 sheet.

The existing validator still reports **3,343 unverified findings**, including
unverified clearance evidence for all nine aisles. Zero collisions is not an
operational approval. None of the 36 asset definitions has complete controlled
planning readiness in this snapshot.

## Highest-Priority Remaining Work

1. Resolve all twelve robot cells before claiming a working robotic process.
   Robot and fixture placement origins are approximately 4.742 m apart. That is
   a warning requiring examination, not a valid reach calculation: placement
   origins are not necessarily robot-base/TCP/task points. The actual variant,
   base frame, tool, target poses and joint limits are still needed. No fixture
   was moved speculatively to produce a visually reassuring result.
2. Author exact-revision operating/loading faces and relevant clearances for
   the machining equipment. Facing a machine's center does not prove access to
   its controls or loading door.
3. Supply the actual product/process, handling profiles and resource demands.
   The nine circulation aisles have zero Process Map bindings and no vehicle
   profile bindings. This layout cannot yet demonstrate production flow or
   throughput merely by animating those aisles.

## Reproducibility And Preservation

`tools/audit_independent_factory_layer2.py` performs the audit and constructs
ordinary kernel operations. It defaults to dry-run. `--apply` is guarded by the
exact original Factory 02 revision and uses the existing service's expected
revision Save. Repeating it after the edit refuses to overwrite the newer
revision. `--visual-followup --apply` is separately bound to the first-pass
revision and only adjusts the four inspection operators. It is intentionally a
one-layout authoring tool, not a generic manufacturing validator.

Evidence: `.runtime/independent-factory-layer2-20260928/` contains `before.json`,
`after.json`, `saved.json`, `operations.json`, `visual-review.json`, `report.json`,
and native evidence. `after.json` is the evaluated candidate;
`saved.json` includes the repository-owned Save timestamp and final revision.
Native comparison checks the exact saved document, and separately verifies
that only `updatedAt` differs from the evaluated candidate. Initial native
assertion failure and first-pass evidence are retained separately.
The final `native-check.json`, `verification.json`, `canvas-pixel-checks.json`,
PNG captures and thirteen contact sheets are in the same evidence directory.
`before.json` preserves the prior Factory 02 document for deliberate restoration;
this offline Save does not create a new editor-session Undo entry.

The original manual layout remains byte-for-byte unchanged, SHA-256
`a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`.
The original remains the default sheet. No provider requests or credits were used.
