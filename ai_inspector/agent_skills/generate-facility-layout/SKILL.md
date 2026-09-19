---
name: generate-facility-layout
description: Generate or modify a factory from its envelope and macro departments through cells and resources using evidence-aware deterministic Facility Layout tools.
---

# Generate Facility Layout

Use only trusted Facility Layout context. The bounded
`facility_layout.digest` is mandatory. Full `facility_layout.state` and
`facility_layout.evidence` may be included when they fit the contract budget;
otherwise use the digest's stable IDs and read descriptors with the targeted
observation tools. Never treat an omitted optional provider as missing
authority or request the entire layout to replace it.

Transform the user's facility objective into coordinate-free, revision-bound
intent. Plan from the site level down to departments, flows, cells, and
resources. Do not imitate the user's manual clicks. Deterministic tools own
geometry, validation, stage receipts, and unsaved draft state.

When the user supplies a complete facility envelope and macro departments, use
`generate_facility_departments_draft`. This is Gate G1. It can create from an
empty saved layout or explicitly replace the whole current facility proposal. It
executes a bounded server-owned stage sequence so the user can see the envelope
and department partition appear in the editor. Sage calls the tool once; model
text cannot enqueue or continue stages. For resource placement or rearrangement
inside an existing facility, use `build_facility_layout_preview` instead. Never
call both generation tools in one turn.

When one request supplies the envelope and macro departments plus downstream
circulation, subdivisions, exact catalog-named assets, seed-cell intent, or
cell replication, use `generate_full_factory_draft` exactly once instead of
splitting the request across G1-G6 calls. Populate every requested stage in the
closed schema; use empty arrays or `null` only for stages the user omitted.
InspectorPro resolves exact asset IDs and revisions, owns all geometry, and
advances the same durable ten-stage run to one cumulative unsaved draft.

When the user explicitly asks for the trusted or reference-quality MMLE-50D
prototype from its Facility Planning package, call
`generate_facility_planning_prototype_draft` exactly once. Supply only the
registered package ID and `authorized_draft_run`; do not expand package content
into model-authored geometry or resources. Report the result as **Prototype /
Unsaved / Not Released** and retain its unresolved policy findings.

For a follow-up that changes one dependency-independent resource batch in that
active prototype, call `amend_facility_program_resource_batch_draft` once.
Resolve the exact stable batch ID from trusted run context, copy only the
user-requested quantity, pattern, orientation, or numeric spacing, and leave
all other optional fields null. Do not emit coordinates or reinterpret a
request as a safety, capacity, or compliance requirement. InspectorPro
recompiles only the target-area resource set, appends an immutable receipt,
preserves unrelated geometry, and keeps one cumulative Save and Undo boundary.

One narrow exception is an explicit exact translation such as "move the
selected machine 10 ft east." Resolve the current selection or exact placement
IDs, then use `preview_facility_move`. Supply only the cardinal direction,
distance, source unit, and `preserve_rotation=true`; never calculate or emit
coordinates. This creates a validated unsaved draft transaction with Undo and
does not invoke the whole-layout planner.

## Coordinate-Free Actor Navigation

When the user assigns an existing operator or vehicle to existing authored
service points, use `observe_navigation_context` to resolve the exact actor,
anchors, movement program, handoffs, and missing requirements. Never create an
actor, duplicate a placement, emit a coordinate, or infer a station location.

Use `propose_navigation_intent` for exactly one unsaved semantic program
upsert. Supply existing stable actor, anchor, route, and zone IDs only. The
proposal must remain `inferred` and `pending`; manual path constraints,
authored anchors, unrelated programs, and handoffs remain byte-identical. The
result uses the normal cumulative Save and exact Undo boundary and never grants
human authority automatically.

For an explicit prototype playback request, compile and validate existing
programs before calling `build_activity_scenario`. Plan and 3D share one
presentation clock, but independent paths do not become traffic simulation.
Never stagger actors to hide overlap or imply timing, staffing, throughput,
capacity, safety, compliance, or operational optimality.

Ask one clarification when actor identity, stop order, an anchor, or an exact
vehicle profile is missing. Refuse chat-authored coordinates, generic vehicle
assumptions, invented clearances, and unsupported engineering claims.

## Facility Layout Environment Contract

- An asset definition is a revisioned machine, rack, fixture, workstation,
  vehicle, or other resource template. A placement is one occurrence of an
  exact asset-definition revision in a Facility Layout.
- Zones are named operating, storage, staging, aisle, dock, safety, utility,
  service, or operator regions. Zone membership is computed from authoritative
  world geometry and is not a label Sage may invent.
- A production cell is represented semantically by a `workcell` zone, its
  member asset items, and supported placement relationships. It is not proof
  that the resources can perform a process unless trusted capability evidence
  supports that claim.
- Connectors are occurrence-qualified interfaces on a placement, shell, or zone
  anchor. A connector ID without its owner is ambiguous.
- Material, operator, forklift, and conveyor routes are distinct from utility
  networks. Electrical, air, water, exhaust, network, gas, and drain topology
  belongs in utility networks.
- Clearances, floor capacity, utility compatibility, and safety verdicts require
  current authoritative evidence. Missing evidence is `unverified`; it is never
  proof that a layout is safe.
- Saved transforms use right-handed Facility Layout world coordinates with +Y
  up and X/Z on the floor. Sage never emits coordinates, transforms,
  quaternions, matrices, ports, route points, screen pixels, or camera values.
- `auto` placements may be moved by deterministic arrangement. `manual`
  placements are preserved by default. `locked` placements never move.
- Process Map bindings connect process nodes or routes to facility resources.
  Process meaning and spatial quality remain separate. Proximity, mates,
  geometry, or adjacency do not prove manufacturing order.
- Evidence states are exactly `authored`, `derived`, `inferred`, and `unknown`.
  Sage cannot promote evidence. Inferred facts may support a proposal but cannot
  satisfy hard process, utility, loading, clearance, or safety requirements.
- Floor markings communicate routes, boundaries, warnings, or labels. A painted
  line, arrow, or zone never proves aisle clearance, accessibility, separation,
  or safety compliance. Semantic Plan v1 does not author arbitrary marking
  geometry; retain unsupported marking intent as an unresolved item.
- Semantic Plan v1 can create or size zones, place trusted asset revisions,
  express supported relationships, and propose supported routes. It does not
  author utility-network topology, stack or named support surface attachments,
  or arbitrary floor-marking geometry. Persistent manufacturing-cell groups
  are available only through the bounded G5 cell-composition gate described
  below. Never claim deferred intents were applied.
- A semantic plan creates one temporary 2D/3D ghost preview. Preview is not a
  saved layout. One later explicit approval binds the exact diff and every
  dependency; one atomic commit returns a canonical receipt.
- Never say that a layout was applied, saved, validated, safe, or approved
  without the matching trusted receipt or deterministic evidence.
- A G1 generated draft is also unsaved. Each stage has an immutable receipt,
  but only the final cumulative proposal can become Save-eligible. Save is an
  explicit user command bound to the exact cumulative diff and full valid
  receipt chain. Undo restores the immutable saved base and supersedes the
  draft receipts without rewriting them.

## Observation

1. Start from the bounded digest. Confirm the active site, layout, revision,
   shell and policy revisions, saved-state currency, capabilities, stale
   dependencies, active proposal, findings, and unresolved authority gaps.
2. Use the read-only tools for exact details. Search assets by capability or
   category, and inspect only stable entity, zone, finding, or process IDs.
3. Never ask observation tools to inspect model-authored coordinates or screen
   rectangles. Use opaque pagination cursors unchanged.
4. Do not infer authoritative geometry, policy, evidence, revisions, approval,
   or receipts from the browser or visible canvas.

Use the tools by purpose:

- `search_industrial_assets`: find planning-ready resources by capability,
  category, or role. Copy exact asset IDs and definition revisions.
- `inspect_facility_entities`: inspect exact placements, zones, routes,
  markings, and other stable entities already in the layout.
- `inspect_facility_region`: inspect a bounded area before assigning resources
  to an existing department or workcell.
- `inspect_facility_findings`: resolve current collisions, containment,
  clearance, routing, or authority findings that affect the requested scope.
- `inspect_process_bindings`: read revision-bound process-to-resource intent;
  do not derive process order from the current spatial arrangement.
- `inspect_facility_semantics`: read exact derived area and hierarchy, asset
  operational roles, Facility command meaning, and the structured cell-layout
  strategy registry. Inferred manufacturing priors guide alternatives but
  never satisfy hard safety, clearance, utility, or policy requirements.
- `inspect_pattern_provenance`: read authored pattern seeds, parameters,
  membership, and manual drift without creating a new pattern.
- `inspect_cell_layout_provenance`: read an authored cell strategy and current
  conformance without arranging or previewing the cell.
- `analyze_facility_spatial`: resolve human entity names and current selection;
  measure free space, clearances, route crossings and widths; retrieve pattern
  or cell provenance; compare bounded cell alternatives; test complete cell
  modules; and audit 2D/3D transforms. Choose the focused analysis named in the
  tool description. It is read-only and never creates a preview.
- `analyze_facility_fit`: test whether one exact revisioned asset has a bounded
  validated candidate inside one authored zone before proposing it. Resolve a
  current placement, current selection, or human asset name internally; never
  expose revision hashes to the user. This does not prove maximum quantity or
  production throughput.

For a large facility, inspect by region and stable ID with bounded pagination.
Do not pull the entire asset catalog or layout when a digest and targeted reads
answer the planning question.

The orchestration runtime classifies the operation before exposing tools.
Only `simulate` or `modify` may see the whole-layout preview tool, and only an
`exact_transform` may see the bounded move tool. An inspect, measure, compare,
recommend, render, or provenance request remains read-only even when it names
the Facility Layout or discusses a possible improvement.

## Gate G1: Facility Envelope And Macro Departments

Use this gate when the request explicitly defines or redefines the complete
outer facility plus 1-50 labeled macro departments. The saved layout may be
empty or populated. A complete redefinition is an explicit replacement draft;
it does not mutate the saved layout until Save.

1. Preserve the user's width, depth, source unit, facility name, department
   count, labels, proportions, arrangement, orientation, authored row count,
   row membership, row order, and row shares exactly. Rows are ordered north
   to south; labels inside a row are ordered west to east.
2. Use `null` when grid size, labels, or proportions were not supplied. Generic
   department labels may then be produced by the deterministic contract; Sage
   must not invent manufacturing functions.
3. Call `generate_facility_departments_draft` exactly once. Use
   `authorized_draft_run` unless the user explicitly asks for preview only.
4. Never provide coordinates, polygon points, boundaries, transforms, routes,
   placements, utilities, corridors, safety separations, expansion reserves,
   process order, or approval. The G1 solver owns every coordinate.
5. The tool advances ten bounded stages, but only the envelope and macro
   department stages add geometry. Out-of-scope stages close with explicit
   cancelled receipts; they do not fabricate content.
6. Report the exact envelope, authored department labels, stage and receipt
   counts, deterministic validation status, and that the layout remains
   unsaved. Direct the user to Save or Undo.
7. Do not infer replacement from a scoped edit. Use replacement semantics only
   when the user explicitly requests a complete facility envelope and macro
   department set. Preserve the saved base until the cumulative draft is saved.
8. A follow-up may reshape the current server-owned G1 department program
   without repeating its envelope or labels. Reuse only the trusted saved
   program or revision-bound generation run, supersede the active unsaved
   draft, and preserve stable zone identity for unchanged labels.
9. `row_stack` supports any valid number of non-empty rows. With equal
   department areas, derive each row depth from the number of departments it
   contains. With complete department or row proportions, honor those shares
   exactly. Reject partial membership, incomplete shares, duplicate labels,
   or conflicting row and department areas; ask for the missing intent instead
   of guessing.

## Gate G5: Manufacturing-Cell Feasibility And Composition

Use this gate only after G4 has placed at least two exact-revision resources in
one uniquely named department or child area.

1. Use `generate_facility_cell_draft` to compare or apply only registered
   strategies: straight line, L, U or inverted U, grid, parallel, serpentine,
   loop, spine, herringbone, and cluster.
2. A comparison question is read-only. A build, arrange, convert, or reflow
   request may create an unsaved G5 draft. Never convert a recommendation into
   a write without an explicit action verb.
3. Preserve every department ID and boundary, route, floor marking, asset ID,
   asset-definition revision, and asset rotation. G5 may change only the
   target resources' deterministic positions and the target zone's cell-group
   metadata.
4. Accept spacing only when the user supplies an exact value. Without one,
   validate physical non-overlap only and report access or clearance as
   unverified. Never supply a generic machine, OSHA, fire-code, ergonomic, or
   service clearance.
5. Preserve `manual` and `locked` placements. If they prevent a bounded reflow,
   ask the user to resolve them; never move them silently.
6. Treat shortest travel, smallest envelope, minimum movement, and maximum
   expansion reserve as geometric comparison objectives only. They do not
   establish throughput, takt, staffing, safety, accessibility, ergonomics,
   utilities, maintenance access, or operational optimality.
7. Process sequence is authoritative only when supplied by revision-bound
   process evidence or explicit placement IDs. The current spatial order is
   not manufacturing intent.
8. InspectorPro selects coordinates and validates fit. Sage supplies no world
   points, transforms, angles, or candidate geometry.
9. Report the selected strategy, rejected strategies and reasons, geometric
   metrics, spacing authority, evidence gaps, and that the result is unsaved.
10. A follow-up may convert the active cell to another registered strategy in
    the same durable run. Supersede only `seed_cells` and downstream receipts;
    retain upstream G1-G4 receipts and one cumulative Save/Undo boundary.

If no candidate fits, report the deterministic rejection reasons and stop. Do
not omit resources, shrink footprints, relax authored spacing, or move
unrelated geometry to make a strategy appear feasible.

## Gate G6: Reusable Cell Modules And Exact Replication

Use this gate only after G5 has produced a qualified manufacturing cell with
revision-bound asset definitions, authored relative geometry, and cell-group
provenance.

1. Use `generate_facility_cell_replication_draft` only when the user names one
   qualified source cell and one or more uniquely named empty target areas.
2. Replicate exact asset-definition revisions, relative transforms,
   orientations, and internal snap relationships. InspectorPro creates new
   stable placement and cell-group identities for every target.
3. Preserve the source cell, every department and child boundary, routes,
   markings, unrelated placements, and manual or locked work byte for byte.
4. Never accept chat-authored coordinates, translations, rotations, offsets,
   scale factors, or polygon geometry. The deterministic compiler translates
   the source module from source-zone centroid to target-zone centroid and
   validates containment and spatial conflicts.
5. A target must be empty and large enough for the unchanged source geometry.
   Do not shrink, rotate, reflow, omit, or substitute assets to force a fit.
6. If the source has diverged from its authored G5 snapshot, stop unless the
   user explicitly says to copy the current edited state. Record that choice as
   explicit authority; never silently promote manual edits into the module.
7. Refuse claims that replicas are safe, compliant, capacity-equivalent,
   throughput-equivalent, ergonomic, or operationally optimal. G6 proves only
   exact revision, relative-geometry, relationship, and provenance conformance.
8. A conformance or drift question is read-only. Report modified, missing, or
   extra members without overwriting either the source or any replica.
9. Report source and target names, replica and copied-placement counts,
   preserved state, validation status, and that the result is unsaved.
10. Supersede only `repeated_modules` and downstream receipts. Retain G1-G5
    receipts and keep one cumulative Save and Undo boundary for the full run.

If a target is occupied, a source relationship depends on an entity outside
the source cell, or exact translated geometry does not fit, name the blocking
condition and stop. Do not make a plausible substitute arrangement.

## FLI-026: Full-Factory Generation

Use this orchestration gate only when a single user request completely defines
the facility envelope, macro departments, and at least one downstream G2-G6
stage.

1. Call `generate_full_factory_draft` once. Do not issue separate department,
   circulation, subdivision, asset, cell, or replication calls in that turn.
2. Preserve every authored label, quantity, route width, source unit,
   subdivision membership, strategy candidate, gap, and replication target.
3. Reference routes by unique authored labels for crossing intent. The
   deterministic circulation stage resolves generated route IDs and the exact
   centerline intersection.
4. Reference assets by exact catalog display name. Sage never emits or invents
   asset IDs, revisions, footprints, coordinates, or transforms; the server
   resolves and binds the exact revision before the run starts.
5. Omitted stages are explicit empty arrays or `null`. Never invent corridors,
   support areas, resources, cell strategies, spacing, safety clearances,
   vehicle profiles, policy, or approval to make the factory look complete.
6. The server executes at most ten bounded stages with immutable receipts and
   restart-safe checkpoints. A blocked stage stops the run and names the
   deterministic finding; model text cannot continue or repair it on its own.
7. The result is one cumulative unsaved draft. Save requires a later explicit
   command bound to the exact diff and receipt chain. One Undo restores the
   immutable saved base and supersedes the complete draft chain.

## Hierarchical Factory Procedure

### 1. Establish The Design Basis

1. Classify the request as greenfield, brownfield, or a scoped modification.
2. Resolve the requested output, process or material sequence, resource counts,
   receiving and shipping needs, people and vehicle flows, utilities, fixed
   building constraints, and requested expansion allowance.
3. Separate hard constraints from preferences. Treat user instructions as
   authored intent, not as verified safety or engineering policy.
4. Record missing throughput, dimensions, capacities, clearances, utilities,
   access rules, or process evidence as assumptions or unresolved items. Do not
   fill gaps with generic factory values.

### 2. Build The Macro Zone Hierarchy

1. Derive zones from the actual process and support functions. Common zone
   families include receiving and raw material, production, automation,
   assembly and kitting, inspection, packaging, finished goods, shipping,
   material handling, maintenance, utilities, safety, and expansion. Include
   only the families supported by the request and trusted evidence.
2. Reuse an existing stable zone when it has the correct purpose and evidence.
   Otherwise request a new semantic zone with an explicit member set.
3. Keep high-risk, incompatible, or restricted activities separate when trusted
   policy requires separation. Never invent a separation distance.
4. In brownfield layouts, scope changes to the requested zones. Preserve
   unrelated placements and every manual or locked position.

### 3. Establish Flow And Access

1. Establish primary material flow before filling departments. Connect
   receiving, storage, processing, inspection, packaging, and shipping only
   where trusted process evidence supports that sequence.
2. Model forklift, material, operator, conveyor, and utility flow as distinct
   intents. Give every supported flow occurrence-qualified endpoints.
3. Prefer simple, legible flow with fewer crossings and reversals as a soft
   objective. Vehicle profiles and current policy remain authoritative for
   route feasibility, width, and turning behavior.
4. Treat pedestrian paths, crossings, keep-clear regions, arrows, and labels as
   communication intent until an available semantic action and deterministic
   validator bind them. Never substitute visual paint for a route or clearance.

### 4. Populate Departments And Cells

1. Place the primary process resources first, then add the required operator
   stations, tooling, fixtures, local storage, WIP staging, inspection,
   material-handling, and safety resources supported by trusted evidence.
2. Represent a cell as one `workcell` zone with explicit member item IDs.
   Use `grouped_with`, `adjacent_to`, `aligned_with`, `face_toward`,
   `separate_from`, `near`, or `upstream_of` only when their meaning is
   supported. These relationships remain semantic preferences.
3. Use exact quantities for repeated racks, machines, benches, cells, or
   handling equipment. A repeated asset definition still produces distinct
   placement occurrences.
4. Select a cell form from process intent, access, loading, zone geometry,
   operator count, production volume/variety, maintenance needs, expansion,
   and flow evidence. Inspect the structured cell strategy registry and rank
   relevant candidates. Straight, L, U/inverted-U, grid, parallel, serpentine,
   loop, spine, herringbone, and cluster arrangements are alternatives, not
   defaults. Do not choose a form because it looks familiar.
5. Record orientation only as supported semantic relationships. Do not infer a
   machine's front, load face, output face, service side, or operator side from
   a thumbnail.
6. If equipment must be stacked or attached to a named support surface, retain
   the requested parent, children, and intent as unresolved unless the active
   semantic capabilities explicitly support that operation.

For cell layout selection, separate recommendation from execution:

1. rank strategies against the authored manufacturing situation;
2. explain the decisive fit and material tradeoff;
3. request deterministic geometry for the preferred strategy;
4. validate the result; and
5. fall back to the next ranked strategy only when structured validation shows
   why the preferred strategy is infeasible.

Never infer a machine's operator, load, output, or service side from its name,
category, thumbnail, or generic semantic role. Use only authored connectors or
interface evidence for side-specific orientation.

Never attach an estimated improvement percentage to a proposed arrangement.
Area recovery, travel reduction, additional fit count, and minimum clearance
must come from the deterministic before/after result. A complete robot-cell
question requires the complete authored module and `module_fit`; fitting a bare
robot or dividing free area by one footprint is not an acceptable substitute.

### 5. Choose Deterministic Layout Alternatives

1. Use `flow_lanes` when trusted sequence and movement dominate the layout.
2. Use `compact_rows` for repeated storage or machine rows where compactness is
   an allowed objective.
3. Use `balanced_grid` for mixed-resource areas or when no stronger flow
   preference is supported.
4. Provide only relevant alternatives. Density is a preference, never a way to
   override clearance or policy.
5. Use `stage` to carry supported operational ordering. Do not use it as a
   coordinate, visual row number, or substitute for a Process Map revision.

### 6. Check Completeness Before Preview

Verify that the plan:

- binds the exact site, layout, shell, policy, asset, vehicle, and Process Map
  revisions it depends on;
- covers every requested capability and every requested asset occurrence;
- assigns each planned resource to the intended zone or records why it cannot;
- preserves authored values plus manual and locked placements;
- distinguishes routes, utility networks, zones, and floor-marking intent;
- exposes inferred relationships, assumptions, deferred work, and unresolved
  authority gaps; and
- requests no coordinate, transform, port, waypoint, camera, or low-level
  Builder value from the model.

## Planning

1. Resolve the user's objective, required process capabilities, quantities,
   resource roles, applicable zones, flows, and exact Process Map revisions.
2. Select only trusted planning-ready asset definitions and copy each exact
   `assetId` and `assetDefinitionRevision`.
3. Cover every requested capability and quantity. Repeated resources remain
   quantities or distinct planned occurrences; do not silently omit them.
4. Draft Semantic Facility Layout Plan v1 with:
   `schemaVersion`, `planId`, `scope`, `objective`, `sourceRevisions`,
   `requiredCapabilities`, `selectedAssets`, `requiredZones`,
   `placementRelationships`, `processBindings`, `flows`, `evidence`,
   `assumptions`, `unresolvedItems`, `alternatives`, and `layoutHints`.
5. Use relationships such as `adjacent_to`, `grouped_with`, `face_toward`, or
   `separate_from`. They are semantic preferences, never coordinates.
6. Utility flows remain explicit. Do not disguise a utility network as a
   material route.
7. Mark unsupported or missing claims unresolved. Do not invent capacities,
   clearances, utilities, dimensions, safety rules, travel envelopes, machine
   settings, or process sequence.
8. Preserve manual and locked positions. Request deterministic alternatives
   such as `compact_rows`, `balanced_grid`, or `flow_lanes`; do not arrange
   objects yourself.

## Bounded Verification And Correction

1. Complete the semantic plan before the write-capable preview call. Do not use
   repeated partial previews as a substitute for planning.
2. `build_facility_layout_preview` owns the operational loop: observe trusted
   state, compile, simulate, validate, and produce one complete ghost preview.
3. Deterministic validation checks current revisions, requested asset coverage,
   placement feasibility, and new hard findings. Treat its structured result as
   authoritative over visual appearance or prior prose.
4. The verified workflow may add an unused approved deterministic strategy only
   when no layout alternative exists. It may attempt at most two repairs and
   never weaken hard constraints, change source revisions, add resources,
   overwrite authored values, or move manual or locked placements.
5. Stop when validation reports a terminal issue, requires a human decision, or
   exhausts its budget. Report the exact blocker; do not silently relax a rule
   or start an unbounded retry loop.
6. Use 2D and 3D review as presentation and human verification of the same
   saved world state. A visually plausible scene cannot overrule deterministic
   findings.

## Preview

1. Call `build_facility_layout_preview` exactly once with the complete semantic
   plan. Do not call low-level Facility Layout operations or simulate ribbon
   clicks and property-form typing.
2. The tool validates semantics, resolves exact revisions, compiles a P8
   declarative request, places and routes deterministically, runs diagnostics,
   and stores one authorized temporary ghost artifact.
3. The tool returns a `workflowRun` operational trace. It may try at most two
   bounded deterministic repairs by adding an approved layout strategy. A
   repair never changes hard constraints, source revisions, requested assets,
   authored values, or manual and locked position rules.
4. Report the proposal ID, counts, alternatives, assumptions, unresolved items,
   finding summary, and any applied correction. If the run is blocked or its
   budget is exhausted, report the structured issue and ask for the required
   human decision. Do not expose or invent hidden reasoning.
5. Tell the user the preview is not saved, then wait for explicit approval. Do
   not claim success until a later trusted
   receipt names the new revision and affected stable IDs.

## Minimal Plan Shape

```json
{
  "schemaVersion": 1,
  "planId": "stable-plan-id",
  "scope": {
    "siteId": "trusted-site-id",
    "layoutId": "trusted-layout-id",
    "label": "Requested layout"
  },
  "objective": "place_and_cleanup",
  "sourceRevisions": {
    "layout": "trusted-layout-revision",
    "shell": "trusted-shell-revision",
    "policy": "trusted-policy-revision"
  },
  "requiredCapabilities": [],
  "selectedAssets": [],
  "requiredZones": [],
  "placementRelationships": [],
  "processBindings": [],
  "flows": [],
  "evidence": [],
  "assumptions": [],
  "unresolvedItems": [],
  "alternatives": [
    {
      "alternativeId": "balanced",
      "strategy": "balanced_grid",
      "label": "Balanced"
    }
  ],
  "layoutHints": {
    "density": "balanced",
    "preserveManual": true,
    "preserveLocked": true
  }
}
```

Keep prose concise. The preview artifact, deterministic findings, and canonical
receipt carry the detailed result.
