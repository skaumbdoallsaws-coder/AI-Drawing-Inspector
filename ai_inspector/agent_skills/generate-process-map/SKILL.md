---
name: generate-process-map
description: Generate one evidence-aware Semantic Process Plan and submit it for deterministic layout, routing, preview, and approval.
---

# Generate Process Map

Use only trusted `process_map.graph`, `process_map.state`, and
`process_map.evidence`.

## Runtime Environment Contract

- Product-occurrence cards represent stable assembly-tree occurrences. The same
  part number may occur more than once; use occurrence IDs, never label matching.
- Part and subassembly nodes represent physical product structure. An
  operation/stage node represents manufacturing or assembly work.
- `parallel_and`, `merge`, `split`, and `wire_branch` junctions represent flow
  topology only. Do not use a junction where parts are joined or transformed.
- Routes are directed output-to-input logical connections. Node requirements
  describe a card/stage; route requirements describe a transfer or relationship.
- Evidence states are `authored`, `derived`, `inferred`, and `unknown`.
  Authored/derived claims require provenance. Inferred operations must expose
  their evidence or assumption. Unknown values remain unresolved.
- Assembly structure proves membership. BOMs, mates, geometry, names, and spatial
  proximity may support an inference but do not prove manufacturing sequence.
- `process_map.evidence.identity` is the immutable knowledge source for this
  turn. Copy its package, source, evidence, and context fingerprints into the
  plan's `evidenceBinding`; never substitute browser data or an older identity.
- Use reviewed process candidates when available. Preserve each candidate's
  `knowledgeStatus`, `authority`, `reviewStatus`, evidence refs, assumptions,
  and unresolved questions. Confirmation is review evidence, not production
  approval.
- Honor `process_map.evidence.processCandidates.presentation`. In `high_level`
  mode, retain every leaf occurrence in `requiredOccurrences` and operation
  inputs for exact coverage, but set `scope.presentationMode` to `high_level`.
  The deterministic compiler will keep those covered inputs auditable without
  rendering hundreds of leaf cards.
- Saved geometry uses world coordinates. Never emit coordinates, ports,
  waypoints, camera transforms, screen pixels, or low-level Builder operations.
- `auto` positions may move during arrangement; `manual` positions are preserved
  by default; `locked` positions cannot move.
- One request produces one revision-bound Semantic Process Plan, deterministic
  validation/layout/routing, one complete ghost preview, one explicit approval,
  one atomic commit, and one structured receipt. A preview is not a write.
- When occurrence-level visual validation is available, the preview compiler
  compares every operation's direct inputs against fixed assembly views and
  identity masks. It may relabel an existing stage or move an existing required
  occurrence between existing stages, once, while the proposal is still
  temporary. Visual evidence never establishes sequence or authoritative
  manufacturing facts, and every correction remains inferred.

## Procedure

1. Confirm `process_map.state.identity`, saved-state currency, capabilities,
   `process_map.evidence.identity.readiness`, and that the v1 canvas is empty.
   If dirty, conflicted, stale, non-empty, not planning-ready, or semantic
   preview is unavailable, report the exact blocker.
2. Resolve exactly one requested assembly/subassembly from the full
   `product_structure.occurrences` catalog, not from placed canvas nodes.
3. Include every descendant part occurrence exactly once. Do not collapse
   repeated occurrences that share an item or part number.
4. Draft Semantic Process Plan v1 with:
   `schemaVersion`, `planId`, `evidenceBinding`, `scope` (including the trusted
   `presentationMode`),
   `requiredOccurrences`, `operations`, `intermediateResults`, optional
   `junctions`, `branches`, `evidence`, `assumptions`, `layoutHints`, and
   `unresolvedQuestions`.
5. Every operation needs inputs, one output, a branch/stage hint,
   `knowledgeStatus`, evidence, and assumption IDs where applicable. The final
   output must be the requested subassembly occurrence.
6. Never invent torque, duration, tools, machines, fasteners, dimensions,
   inspection limits, standards, or procedure IDs. Leave them unresolved unless
   trusted evidence supplies them.
7. Call `build_process_map_preview` exactly once with the trusted scope
   occurrence ID and the complete semantic plan. Do not call any other map-write
   or spatial proposal tool in the same response.
8. Report the tool summary, visual-validation status, applied inferred
   corrections, warnings, assumptions, and unresolved count. Tell the user to
   review both the ghost preview and the occurrence contact sheet. Do not claim
   it was applied until a later trusted receipt reports the committed revision
   and created IDs.

## Semantic Plan Shape

```json
{
  "schemaVersion": 1,
  "planId": "stable-plan-id",
  "evidenceBinding": {
    "packageId": "trusted-package-id",
    "packageRevision": "trusted-package-revision",
    "sourceRevision": "trusted-source-revision",
    "evidenceFingerprint": "trusted-evidence-fingerprint",
    "contextFingerprint": "trusted-context-fingerprint"
  },
  "scope": {
    "assemblyOccurrenceId": "trusted-id",
    "label": "name",
    "presentationMode": "detailed"
  },
  "requiredOccurrences": [
    {
      "occurrenceId": "trusted-leaf-id",
      "quantity": 1,
      "role": "input",
      "knowledgeStatus": "derived",
      "evidence": [
        {
          "sourceType": "assembly_structure",
          "sourceRef": "trusted-structure-revision",
          "supports": "component-membership"
        }
      ]
    }
  ],
  "operations": [
    {
      "id": "op-stable-id",
      "operationType": "operation",
      "label": "Perform supported work",
      "inputs": [{"ref": "trusted-leaf-id", "type": "occurrence"}],
      "output": {
        "ref": "state-stable-id",
        "type": "intermediateResult",
        "label": "Intermediate result"
      },
      "branchId": "branch-id",
      "stageIndex": 1,
      "knowledgeStatus": "inferred",
      "evidence": [
        {
          "sourceType": "domain_heuristic",
          "sourceRef": "named-heuristic",
          "supports": "candidate-operation"
        }
      ],
      "assumptionIds": ["assumption-id"],
      "properties": {}
    }
  ],
  "intermediateResults": [
    {
      "id": "state-stable-id",
      "label": "Intermediate result",
      "producedBy": "op-stable-id"
    }
  ],
  "junctions": [],
  "branches": [{"id": "branch-id", "label": "Branch"}],
  "evidence": [],
  "assumptions": [
    {"id": "assumption-id", "text": "Review this inferred sequence."}
  ],
  "layoutHints": [
    {"ref": "op-stable-id", "branchId": "branch-id", "stageIndex": 1}
  ],
  "unresolvedQuestions": []
}
```

## Output

Keep prose short. Distinguish supported facts, inferred steps, assumptions, and
unresolved items. The visual proposal and receipt carry the detailed result.
