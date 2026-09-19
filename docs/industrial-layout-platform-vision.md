# InspectorPro Industrial Layout Platform

Status: deferred product direction - resume after the process-map flow editor
is complete and stable.

## 1. Product thesis

InspectorPro can extend its product-structure tree, GLB pipeline, process-map
editor, and agent architecture into an industrial spatial-planning platform.
Users would build warehouse layouts, manufacturing cells, inspection areas,
assembly lines, and material-handling systems by dragging semantic industrial
assets into a dimensioned 2D/3D workspace.

The target outcome is a credible first layout in hours rather than days,
while deterministic engineering checks and human approval remain authoritative.

## 2. Initial use cases

- Warehouse storage, staging, receiving, shipping, and picking layouts.
- Rack rows, bays, slots, pallets, barriers, and charging areas.
- Forklift lanes, pickup/drop-off points, and turning envelopes.
- Machining, welding, robotic, assembly, and packaging cells.
- Inspection laboratories and quality-control stations.
- Conveyors, workbenches, fixtures, utilities, and operator stations.
- Service, maintenance, safety, and exclusion areas.

## 3. Core interaction

1. Open or import the facility shell and floor plan.
2. Draw and dimension working zones in a top-down plan view.
3. Assign each zone a type, purpose, constraints, and permitted asset classes.
4. Browse a SolidWorks-style tree of company and InspectorPro library assets.
5. Drag an asset occurrence into the layout.
6. Resolve the asset ID to an optimized GLB and semantic asset definition.
7. Project the drop location onto the floor or an eligible mounting surface.
8. Preview valid snap targets, clearances, and conflicts before placement.
9. Commit the placement and show deterministic validation findings.
10. View and edit the same layout in synchronized 2D and 3D modes.

The drag payload should contain a stable asset or occurrence ID, not the GLB
binary or a mutable object. The workspace resolves and caches the asset.

## 4. Product architecture

```text
Process map
    Operations, precedence, material inputs, and outputs

Facility model
    Floor boundary, walls, columns, doors, docks, and utilities

Zones and routes
    Work areas, storage, staging, aisles, safety areas, and travel lanes

Industrial asset library
    Machines, racks, conveyors, tooling, vehicles, fixtures, and stations

Spatial layout
    Asset occurrences, transforms, snap relationships, and validation state

Product intelligence
    Parts, assemblies, drawings, quality requirements, and production context

Agents
    Layout proposals, modifications, explanation, comparison, and analysis
```

The process map explains what must happen. The facility layout explains where
and with which resources it happens. InspectorPro should connect both rather
than maintaining unrelated diagrams.

## 5. Semantic industrial asset library

A useful industrial asset is more than a GLB mesh. Every asset definition
should be versioned and include:

- Stable asset ID, revision, owner, source, and licensing metadata.
- Display name, category, tags, and compatible workspace types.
- Optimized GLB URLs and level-of-detail variants.
- Native units, coordinate system, origin, and orientation conventions.
- Physical dimensions, footprint, height, weight, and floor loading.
- Simplified collision proxy and selection bounds.
- Placement anchors and supported mounting surfaces.
- Snap connectors for rows, bays, conveyors, utilities, and process links.
- Operating, loading, maintenance, and door-swing clearance volumes.
- Operator work zones and ergonomic access regions.
- Material input/output points and allowed flow directions.
- Electrical, air, water, exhaust, network, and foundation requirements.
- Capacity, cycle-time, utilization, and availability fields when known.
- Safety classification and applicable placement constraints.
- Preview image and fallback geometry for low-resource devices.

The platform should support two catalogs:

- InspectorPro common library: standard racks, pallets, forklifts, conveyors,
  workbenches, barriers, and representative industrial equipment.
- Private company library: actual machines, fixtures, racks, standards, and
  approved vendor assets controlled by the customer.

Large vendor CAD models must be converted into optimized GLBs with collision
proxies and multiple levels of detail before interactive placement.

## 6. Spatial data model

The layout should keep source assets separate from placed occurrences.

```json
{
  "layoutId": "plant-a-cell-04",
  "unit": "m",
  "zones": [
    {
      "zoneId": "storage-a",
      "zoneType": "storage",
      "boundary": [[0, 0], [18, 0], [18, 12], [0, 12]],
      "heightLimit": 8.0,
      "allowedAssetCategories": ["rack", "pallet"]
    }
  ],
  "placements": [
    {
      "placementId": "rack-a-04",
      "assetId": "rack-standard-01",
      "zoneId": "storage-a",
      "position": {"x": 8.0, "y": 0.0, "z": 4.5},
      "rotation": {"x": 0.0, "y": 90.0, "z": 0.0},
      "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
      "snapTarget": "rack-row-a-slot-04"
    }
  ],
  "routes": [],
  "revision": "content-hash"
}
```

Zones, placements, routes, and process relationships are different data
layers. Deleting a placement must not delete its source library asset.

## 7. Zones

V1 zone authoring should support dimensioned rectangles and polygons with
real engineering units. Initial zone types:

- Storage
- Staging
- Receiving
- Shipping
- Workcell
- Inspection
- Aisle
- Dock
- Charging
- Safety
- Exclusion
- Utility/service

Each zone can define permitted asset categories, maximum height or load,
grid spacing, preferred orientation, edge setbacks, required aisle access,
and relevant safety rules.

## 8. Placement and snapping engine

On drop, deterministic code should:

1. Convert screen coordinates to a world-space ray.
2. Intersect the ray with the floor or an eligible mounting surface.
3. Identify the containing zone.
4. Check whether the asset category is permitted in that zone.
5. Calculate candidate grid, edge, row, bay, slot, or connector snaps.
6. Show a translucent placement preview and all clearance volumes.
7. Validate collision, containment, access, and utility constraints.
8. Commit only the accepted transform and snap relationship.
9. Return an execution receipt describing what was actually placed.

Useful snap modes include:

- Dimensioned floor grid
- Zone boundary and setback
- Rack row and bay
- Conveyor or utility connector
- Machine foundation anchor
- Alignment and equal-spacing guides
- Material input/output port

Snapping should be assistive. Users must be able to override non-safety
alignment suggestions while hard constraints remain explicit.

## 9. Synchronized 2D and 3D authoring

Top-down 2D is the primary precision surface for zone boundaries, dimensions,
alignment, aisle spacing, and routes. The synchronized 3D view confirms
height, visibility, access, clearances, equipment orientation, and visual fit.

Both views edit the same layout state. A change in either view must update the
other without duplicating assets or losing transforms.

## 10. Mobile resources and material flow

A parked forklift can be represented as a placed GLB, but an operating
forklift is a mobile resource with additional semantics:

- Compatible travel-lane network
- Vehicle dimensions and turning radius
- Pickup/drop-off points
- Load limits and lift height
- Charging or fueling stations
- Route, speed, and operating constraints

Material-flow edges should connect asset input/output ports and process-map
steps. They should not be inferred from visual proximity alone.

## 11. Agent role and deterministic authority

The LLM should understand goals, compose workflows, select assets, propose
alternatives, and explain tradeoffs. It must not be the authority for geometry
or safety.

Agent responsibilities:

- Translate natural-language goals into a structured layout proposal.
- Select compatible library assets using semantic metadata.
- Request zone creation, placement, alignment, routing, and comparison tools.
- Explain validation findings and unresolved assumptions.
- Generate multiple alternatives and summarize tradeoffs.

Deterministic responsibilities:

- Coordinate conversion and transforms
- Collision and containment checks
- Clearance and aisle validation
- Snap eligibility
- Unit conversion
- Route connectivity and turning geometry
- Revision and workspace-state validation
- Idempotency, duplicate suppression, and execution receipts

Human responsibilities:

- Confirm requirements and assumptions
- Review safety, regulatory, and site-specific constraints
- Approve the selected layout

Example future request:

> Build a four-station piston machining and inspection cell using available
> equipment. Preserve forklift access, maintain every machine's service
> clearance, and place rejected-part staging near inspection.

## 12. Delivery phases

### Phase 0 - prerequisites

- Complete and stabilize process-map source-tree authoring.
- Reuse the product/asset tree, revision-safe persistence, and undo/redo model.
- Define industrial asset and facility-layout schemas.
- Establish the CAD-to-optimized-GLB conversion pipeline.

### Phase 1 - spatial editor foundation

- Facility shell and dimensioned floor plane.
- 2D/3D synchronized cameras and selection.
- Zone creation, resize, type, and dimensions.
- Asset tree and GLB drag/drop.
- Move, rotate, delete, duplicate, and revision-safe save/reload.

### Phase 2 - snapping and constraints

- Floor grid, zone, row, bay, and connector snapping.
- Collision proxies and clearance volumes.
- Zone eligibility and containment validation.
- Visual findings and execution receipts.

### Phase 3 - warehouse workflows

- Rack rows, bays, slots, pallets, and staging.
- Aisles, docks, forklifts, charging areas, and travel lanes.
- Storage capacity and travel-distance calculations.

### Phase 4 - manufacturing cells

- Machines, fixtures, workstations, conveyors, and operator zones.
- Utilities and maintenance access.
- Link process-map operations to physical stations and resources.
- Cell templates and reusable sublayouts.

### Phase 5 - agent-assisted layout

- Hybrid intent classification and layout skills.
- Validated tools for zones, placements, routing, and comparisons.
- Natural-language modification and alternative generation.
- Receipt-grounded responses describing actual execution.

### Phase 6 - analysis and optimization

- Capacity and utilization analysis.
- Material-flow distance and handling analysis.
- Forklift route and congestion analysis.
- Scenario comparison and constraint-aware optimization.
- Simulation only where validated domain engines are available.

## 13. First-version acceptance criteria

- Users can create and dimension facility zones in real units.
- A source asset remains in the library after placement or deletion.
- GLBs can be dragged into valid zones and appear at the drop location.
- Placement remains correct after camera pan, orbit, and zoom.
- Assets snap to grids, boundaries, rows, and compatible connectors.
- Collision and clearance volumes are visible and validated.
- Invalid hard-constraint placements are rejected with a clear reason.
- 2D and 3D views remain synchronized.
- Saved layouts restore zones, placements, transforms, and relationships.
- Repeated asset occurrences remain independently addressable.
- Agent actions pass the same deterministic validation as manual actions.
- Execution receipts report what was placed, rejected, or changed.

## 14. Product value

InspectorPro would collapse repeated search, import, positioning, clearance,
and redraw work. The realistic product claim is not that an agent replaces
facility engineering. It is that an engineer can obtain and iterate on a
credible, constraint-checked first layout in hours, then retain human control
over assumptions, safety, and approval.

The largest gain is iteration speed. Requests such as adding a machine,
increasing staging capacity, preserving forklift access, or comparing two cell
arrangements could produce validated alternatives in minutes instead of
requiring a substantial manual redraw.

## 15. Resume point

Do not begin this work until the process-map flow editor is complete and its
source-tree, canvas-state, persistence, and validation contracts are stable.
When resumed, begin with Phase 0 schema decisions and a narrow Phase 1 proof:
one dimensioned zone, one rack asset, one machine asset, GLB drag/drop, and
synchronized 2D/3D persistence.
