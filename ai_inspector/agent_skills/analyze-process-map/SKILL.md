---
name: analyze-process-map
description: Review a saved manufacturing process map or identify the part occurrences contained in a named product-structure scope using the trusted server-compiled graph digest.
---

# Analyze Process Map

Use only the trusted `process_map.graph` evidence supplied by the server.

## Process Map Environment Contract

- A **product-occurrence node** is one immutable assembly-tree occurrence. A
  part or subassembly card never changes the source product structure.
- An **operation/stage node** means work is performed. A **merge**, **split**,
  **parallel/AND**, or wire-branch **junction** means topology only and must not
  hide a manufacturing operation.
- A **route** is a directed output-to-input connection. Node requirements apply
  to a card or stage; route requirements apply to the transfer or relationship
  represented by one logical connection.
- Evidence states are `authored`, `derived`, `inferred`, and `unknown`.
  Assembly structure, BOM membership, mates, geometry, and proximity can support
  a proposal, but do not prove manufacturing order.
- Persisted positions are world coordinates. Camera pan, zoom, viewport size,
  and screen pixels never change saved geometry.
- `positionMode: auto` may be arranged automatically, `manual` preserves a user
  placement by default, and `locked` cannot move.
- Persistent changes use one revision-bound Builder transaction: semantic plan,
  deterministic validation/layout/routing, complete ghost preview, explicit
  approval, atomic commit, then a structured receipt. A preview is not a write.

## Procedure

1. Confirm the saved map identity and revision in the digest.
2. Check validator findings and precedence cycles before interpreting the flow.
3. Identify entry and terminal nodes, disconnected regions, and parallel branches.
4. Compare authored precedence with `suggestedBuildOrder` where both values exist.
5. Report fan-in of three or more only as a **bottleneck candidate**.
6. Cite every concrete finding with the node ID and node name.

## Spatial Layout Analysis

When the user asks about card placement, overlaps, spacing, wire crossings, or
layout quality, use only the trusted `spatial` section compiled by the server.

1. Check `spatial.status`. If it is not `computed`, say that deterministic
   layout diagnostics are unavailable for this saved revision.
2. Lead with warning-level conditions represented in `problem_ids`: card
   overlaps, wires through cards, and group-header intersections.
3. Then report informational opportunities such as wire crossings, backward
   visual flow, excessive route detours, or alignment deviation.
4. Use the node and edge IDs encoded in `problem_ids`, resolving node names from
   the trusted `nodes` list. Do not expose or invent raw coordinates.
5. Treat `open_regions` and `dense_regions` as visual-layout evidence only.
   Never infer manufacturing sequence, precedence, capacity, or process meaning
   from proximity, region occupancy, or card position.
6. Layout analysis is read-only. Do not call `ui_actions`, emit another tool
   protocol, change the map, or claim that any card or wire moved.

## Spatial Edit Proposals

Only when the current user explicitly asks to place, move, arrange, connect, or
route process-map content:

1. Use `propose_process_map_node_placement` for one requested card placement or
   move, or `propose_process_map_connection_route` for one existing connection.
2. Request the semantic outcome only. Never supply coordinates, positions,
   waypoints, route geometry, viewport transforms, or a hand-authored operation.
3. The deterministic planner owns candidate generation, obstacle avoidance, port
   layout, and route geometry. The tool creates a visual proposal only.
4. Tell the user to review the preview. Never claim that the map was changed,
   saved, approved, or executed until a later browser receipt confirms it.
5. Do not call a proposal tool for a question about layout quality or for advice
   on how the user could improve it.
6. Limit each response to one spatial proposal so one preview, one approval, one
   diff, and one receipt remain aligned.

## Canvas Focus And Dependency Trace

When the user asks where a card, part, subassembly, stage, or route is on the
Process Map, use the trusted graph IDs and call `ui_actions` in the current
response. This is a temporary explanation layer, not editable selection.

1. Resolve a placed product card from `nodes[].occurrenceId`, or a stage or
   junction from `nodes[].id`. Use occurrence IDs for physical product content;
   never choose a repeated part by label alone.
2. For "where is this part," use `direction: "target"`.
3. For a subassembly, "what builds this," "show its contributors," or "show
   everything upstream," use `direction: "upstream"` and
   `include_routes: true`. The deterministic editor traces every predecessor
   card, operation, junction, and route. Do not enumerate that traversal
   yourself.
4. For an explicitly requested downstream or bidirectional trace, use
   `direction: "downstream"` or `"both"`.
5. Call exactly one action:
   `{"workspace":"process_map","actions":[{"type":"set_process_map_focus","target_occurrence_id":"<trusted occurrence id>","label":"<trusted name>","direction":"upstream","include_routes":true,"fit_view":true,"dim_others":true}]}`.
   For a stage or junction, use `target_node_id` instead.
   When the user explicitly names multiple scopes, use one action with up to
   eight `target_node_ids` and/or `target_occurrence_ids`, plus `labels` in the
   same node-then-occurrence order. The editor unions the requested topology;
   do not emit one action per scope.
6. If a subassembly card is absent, the editor may show only its placed catalog
   members and will say so explicitly. Never claim a complete upstream trace in
   that fallback state.
7. The glow must not create, select, move, delete, save, or dirty map content.
   Report the focused card and route counts only from the execution receipt.

For an explicit request to clear the canvas glow, call:
`{"workspace":"process_map","actions":[{"type":"clear_process_map_focus"}]}`.

## Required-Part Selection

When the user asks which parts or components are needed for a named assembly or
manufacturing scope:

**Critical source distinction:** `product_structure.occurrences` is the complete
product catalog and is authoritative for this lookup. `nodes` contains only cards
already placed on the process-map canvas. Canvas placement is irrelevant: the
requested scope and every one of its descendants may be absent from `nodes` and
still be valid. Never say that a scope is missing or unavailable when its trusted
occurrence exists in `product_structure.occurrences`.

1. Resolve exactly one assembly, subassembly, or part from
   `product_structure.occurrences` by its trusted name and ID. Do not search
   `nodes` to establish whether the scope exists.
2. Use its `descendantPartCount`; do not invent, expand, or manually enumerate a
   different part list.
3. Call `ui_actions` with exactly this non-persistent result action:
   `{"workspace":"process_map","actions":[{"type":"set_process_map_part_scope","scope_occurrence_id":"<trusted id>","label":"<trusted name>"}]}`.
   This call is mandatory when the user explicitly asks to highlight or show the
   parts. Execute it in the current response; do not merely describe the parts or
   offer to highlight them later.
4. Tell the user how many part occurrences were identified and that they are
   highlighted in the structure tree for individual drag-and-drop placement.
5. Never create cards, edges, or groups automatically for this question.
6. Once one trusted scope is resolved, do not ask whether the user wants an
   assembly sequence or wants to place nodes first. Complete the requested
   highlight action and stop after the concise confirmation.

For an explicit request to clear this result, call `ui_actions` with
`{"workspace":"process_map","actions":[{"type":"clear_process_map_part_scope"}]}`.
This selection is temporary presentation state only; it does not edit or dirty
the saved process map.

## Boundaries

- Never call a node a bottleneck without the word "candidate" unless measured timing, capacity, or utilization evidence is present.
- Never invent takt time, cycle time, cost, staffing, capacity, utilization, or throughput.
- A shared resource or converging branch can justify review, but it does not prove delay.
- Semantic process confidence and spatial-layout confidence are separate. A
  clean layout does not validate the process, and a messy layout does not make
  the process sequence wrong.
- If the map is empty or required graph evidence is absent, report the missing evidence.
- If the digest reports a revision or validation conflict, abstain from a normal analysis and report the conflict.
- Do not change the saved map directly. The temporary required-part selection
  and canvas focus, plus the review-only demo metadata proposal, are the only
  non-spatial tool-backed result presentations allowed by this skill.

## Demo Requirement Population

Only when the user explicitly asks to fill or populate card requirements,
route names, or routing requirements for the Front Wheel & Brake demo:

1. Resolve the requested assembly from the trusted
   `product_structure.occurrences` catalog. Canvas placement does not establish
   whether the assembly exists.
2. Call `propose_process_map_demo_metadata` exactly once with the native
   `scope_occurrence_id` and `fill_mode: "fill_missing"`.
3. Do not send requirement prose, tools, standards, route names, coordinates,
   or map operations. The server loads and validates the app-owned plan.
4. State that the result is illustrative demo data and requires one browser
   approval. Never claim that it has been applied before a receipt confirms it.
5. If cards, stages, or routes are missing or ambiguous, report the unresolved
   count from the tool result. Do not guess or create missing targets.
6. Existing authored values are preserved by default. Do not instruct the user
   to open and fill each form manually.

## Output

Lead with the most actionable supported finding. Keep the answer concise, distinguish deterministic findings from engineering interpretation, and cite nodes as `nodeId (name)`.
