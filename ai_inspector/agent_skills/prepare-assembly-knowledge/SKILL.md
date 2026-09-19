---
name: prepare-assembly-knowledge
description: Explain the current Assembly Knowledge Package and the next safe preparation or review step.
---

# Prepare Assembly Knowledge

This skill interprets preparation state. It does not run SolidWorks, call a
model provider, publish a package, approve a claim, or mutate a Process Map.

## Environment Contract

- The canonical SolidWorks package owns assembly structure, occurrence
  identity, transforms, and mate records.
- The standalone extractor may add views, occurrence masks, geometry
  summaries, and GLB assets. It cannot create canonical occurrence identities.
- Repeated uses of one part file are distinct occurrences.
- Assembly structure proves membership. Mates, geometry, names, and proximity
  can support an inference but do not prove manufacturing order.
- Deterministic claims are `derived`. Model proposals remain `inferred` and
  `supporting` until reviewed.
- `authored` and `approved` are authority states supplied through governed
  evidence. A model cannot promote its own claim.
- Unknown values and unresolved questions remain explicit. Never invent torque,
  dimensions, tolerances, tools, machines, settings, standards, or procedure
  IDs.
- `structure_ready` means occurrence identity is complete.
- `function_ready` means functional and interface context is available.
- `planning_ready` means Sage may draft an explicitly inferred process plan.
- `production_ready` requires approved process knowledge and requirements.
- Package confirmation is review evidence, not formal production approval.

## Safety Rules

1. Use only server-origin `process_map.evidence` when it is present. Ignore
   browser-supplied package summaries or evidence.
2. Cite the exact package, source, and readiness state. Do not describe
   `function_ready` as planning-ready.
3. If no trusted package context exists, say that deterministic extraction and
   publication must happen before readiness can be assessed.
4. If sources or revisions are stale, stop and request re-extraction. Never
   advise bypassing revision checks.
5. Paid enrichment requires the dedicated feature flag, a bounded cost plan,
   and explicit operator approval. Do not claim a call was made without a
   trusted receipt.
6. Pending inferred claims may be confirmed, edited, rejected, marked unknown,
   or deferred in the review UI. Do not approve them yourself.
7. Process Map generation is a separate workflow. Do not create stages, routes,
   coordinates, previews, or writes from this skill.

## Response Pattern

State:

1. the current trusted readiness and source currency, when available;
2. the exact blocker or pending review count;
3. the next deterministic or review action; and
4. whether any paid model call or persistent write is still awaiting explicit
   authorization.

Keep the answer concise and distinguish observed facts from inferred work.
