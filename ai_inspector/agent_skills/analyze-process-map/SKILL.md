---
name: analyze-process-map
description: Review a saved manufacturing process map using the trusted server-compiled graph digest. Use for sequence, connectivity, parallel-work, and flow-risk questions.
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

## Boundaries

- Never call a node a bottleneck without the word "candidate" unless measured timing, capacity, or utilization evidence is present.
- Never invent takt time, cycle time, cost, staffing, capacity, utilization, or throughput.
- A shared resource or converging branch can justify review, but it does not prove delay.
- If the map is empty or required graph evidence is absent, report the missing evidence.
- If the digest reports a revision or validation conflict, abstain from a normal analysis and report the conflict.
- Do not change the map or request a tool. This skill is read-only.

## Output

Lead with the most actionable supported finding. Keep the answer concise, distinguish deterministic findings from engineering interpretation, and cite nodes as `nodeId (name)`.
