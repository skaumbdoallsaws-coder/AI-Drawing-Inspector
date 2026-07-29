# Facility Layout P10 Workflow Packages

## Scope

P10 adds two deterministic workflow packages over the existing P8 planner and
P9 Semantic Facility Layout Plan:

- `warehouse_lane`
- `manufacturing_cell`

The packages do not write layouts, invent coordinates, route in browser space,
or approve their own output. Each compiler returns:

1. a coordinate-free P8 planner request for manual authoring;
2. a Semantic Facility Layout Plan v1 for Sage;
3. a domain model and deterministic estimates;
4. explicit deferred work, evidence references, assumptions, and source
   revisions.

Both paths reach the same P8 intent. P8 remains responsible for world
coordinates, collision checks, route geometry, ghost alternatives, approval,
and atomic application.

## Warehouse Package

`compile_warehouse_lane_package` expands a rack specification into stable:

- rack-row IDs;
- bay IDs;
- level and slot IDs;
- pallet-position counts;
- pallet-to-slot assignments;
- staging, dock, and charging asset intents;
- storage and support zone intents;
- revision-bound forklift route intents.

Capacity is a planning estimate:

```text
nominal positions
  = rows * bays * levels * slots * positions per slot

usable positions
  = floor(nominal positions * planning utilization)
```

The estimate includes its evidence and assumption IDs plus every source
revision. Forklift distance and travel time are deliberately not guessed.
Those values remain pending until P8's deterministic router creates the ghost
route against the current shell, obstacles, policy, and vehicle revision.

## Manufacturing-Cell Package

`compile_manufacturing_cell_package` instantiates a reusable role-based
template. Supported roles include:

- machine;
- robot;
- fixture;
- guard;
- workstation;
- conveyor;
- tooling and inspection;
- material input and output.

Templates carry no site, layout, asset, or product fixture identity. An
instantiation binds each role to one revisioned industrial asset and may add:

- workcell membership;
- operator, maintenance, and safety overlay intent;
- utility requirements;
- material, conveyor, operator, and forklift flow intent;
- revision-bound process operation assignments.

The template revision is the SHA-256 of normalized template content.
Changing any role, zone, relationship, flow, or capability requirement
requires a new revision.

## Operational Overlay Zones

P8 zone sizing is a containment operation. Operator, maintenance, safety, and
utility zones are operational overlays, not containers for production
equipment. Treating them as ordinary P8 containment zones creates incorrect
hard findings.

P10 therefore:

- sends workcell, staging, and inspection containment zones to P8;
- preserves operational overlays in `workflowIntent` and `domainModel`;
- marks each overlay as unresolved until a domain-specific envelope is
  computed;
- never substitutes an arbitrary rectangle or silently calls an overlay
  production-approved.

This is intentional fail-closed behavior. The user can review the full intent
without a false safety or service-space claim.

## Provenance Rules

Every package requires exact revisions for:

- active layout;
- facility shell;
- policy set;
- industrial asset catalog.

Process maps and vehicle profiles add their own revisions where referenced.
Every authored or derived item cites trusted evidence. Every inferred item
cites evidence or an explicit assumption. Unknown utility or capacity facts
remain unresolved.

The compilers reject:

- coordinates, transforms, camera state, waypoints, and screen pixels;
- stale or malformed source revisions;
- missing role assignments;
- duplicate stable IDs;
- unknown evidence or assumption references;
- pallet slot overfill;
- asset targets that point into operational overlay zones;
- a changed cell template with an unchanged template revision.

## Verification

Focused test:

```powershell
python -m pytest tests/test_facility_layout_workflow_packages.py -q
```

Deterministic report:

```powershell
python tools/verify_facility_layout_p10.py
```

The tests prove:

- warehouse hierarchy and capacity arithmetic;
- CNC cell role, zone, utility, flow, and process-assignment coverage;
- manual and Sage compilation produce the same P8 intent;
- both paths generate complete P8 ghost alternatives;
- exact operation replay reproduces the preview diff;
- templates are reusable across layout identities;
- raw geometry and stale template revisions fail closed;
- no workflow package depends on Assem3, Tricycle, or Process Map demo IDs.

## Residual Work

P10 deliberately leaves these items to their existing or future deterministic
engines:

- forklift distance and travel time: P8 router at preview time;
- material, conveyor, and operator route persistence: applicable domain
  routers;
- utility network topology and capacity: utility engineering;
- operator, maintenance, safety, and utility overlay envelopes:
  domain-specific envelope generation;
- process binding persistence: after preview creates stable placement IDs.

These gaps are surfaced in `deferredItems` and Sage `unresolvedItems`; none are
silently treated as complete.
