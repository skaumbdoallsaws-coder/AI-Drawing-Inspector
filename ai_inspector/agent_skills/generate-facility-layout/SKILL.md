---
name: generate-facility-layout
description: Generate one evidence-aware Semantic Facility Layout Plan and submit it for deterministic placement, routing, validation, preview, and approval.
---

# Generate Facility Layout

Use only trusted `facility_layout.digest`, `facility_layout.state`, and
`facility_layout.evidence`.

## Facility Layout Environment Contract

- An asset definition is a revisioned machine, rack, fixture, workstation,
  vehicle, or other resource template. A placement is one occurrence of an
  exact asset-definition revision in a Facility Layout.
- Zones are named operating, storage, staging, aisle, dock, safety, utility,
  service, or operator regions. Zone membership is computed from authoritative
  world geometry and is not a label Sage may invent.
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
- A semantic plan creates one temporary 2D/3D ghost preview. Preview is not a
  saved layout. One later explicit approval binds the exact diff and every
  dependency; one atomic commit returns a canonical receipt.
- Never say that a layout was applied, saved, validated, safe, or approved
  without the matching trusted receipt or deterministic evidence.

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

## Preview

1. Call `build_facility_layout_preview` exactly once with the complete semantic
   plan. Do not call low-level Facility Layout operations or simulate ribbon
   clicks and property-form typing.
2. The tool validates semantics, resolves exact revisions, compiles a P8
   declarative request, places and routes deterministically, runs diagnostics,
   and stores one authorized temporary ghost artifact.
3. Report the proposal ID, counts, alternatives, assumptions, unresolved items,
   and finding summary. Tell the user the preview is not saved.
4. Wait for explicit approval. Do not claim success until a later trusted
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
