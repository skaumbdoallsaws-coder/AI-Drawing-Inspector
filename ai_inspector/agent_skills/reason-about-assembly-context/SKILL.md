---
name: reason-about-assembly-context
description: Explain a part's role, neighbors, and constraints in its parent assembly. Use for assembly impact, mating relationships, repeated instances, or current assembly-state questions.
---

# Reason About Assembly Context

Ground assembly reasoning in the available part legend, instances, mates, and live viewport state.

## Procedure

1. Identify the inspected part number and the specific affected instance when available.
2. Name only neighboring or mating parts supported by the assembly context.
3. Explain what each cited mate constrains, such as shared axis or face contact.
4. Separate structural relationships from inferred function.
5. Distinguish the current inspected instance from repeated unaffected instances.

## Boundaries

- A concentric mate proves a shared axis, not load, clearance, fit class, or failure severity.
- A coincident mate proves geometric contact or alignment, not force transfer by itself.
- Do not generalize one failed supplier part to every repeated assembly instance.
- Do not claim a component is hidden, highlighted, or moving unless live viewport state says so.
