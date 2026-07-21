---
name: analyze-process-map
description: Review a saved manufacturing process map or identify the part occurrences contained in a named product-structure scope using the trusted server-compiled graph digest.
---

# Analyze Process Map

Use only the trusted `process_map.graph` evidence supplied by the server.

## Procedure

1. Confirm the saved map identity and revision in the digest.
2. Check validator findings and precedence cycles before interpreting the flow.
3. Identify entry and terminal nodes, disconnected regions, and parallel branches.
4. Compare authored precedence with `suggestedBuildOrder` where both values exist.
5. Report fan-in of three or more only as a **bottleneck candidate**.
6. Cite every concrete finding with the node ID and node name.

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
- If the map is empty or required graph evidence is absent, report the missing evidence.
- If the digest reports a revision or validation conflict, abstain from a normal analysis and report the conflict.
- Do not change the saved map. The temporary required-part selection above is
  the only tool-backed result presentation allowed by this skill.

## Output

Lead with the most actionable supported finding. Keep the answer concise, distinguish deterministic findings from engineering interpretation, and cite nodes as `nodeId (name)`.
