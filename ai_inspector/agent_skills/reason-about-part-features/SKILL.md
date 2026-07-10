---
name: reason-about-part-features
description: Reason from an inspection profile and semantic feature map. Use to identify what a drawing characteristic controls, where the feature is located, or which validated feature target represents it.
---

# Reason About Part Features

Use semantic feature groups as the engineering description and CAD operations only as implementation evidence.

## Procedure

1. Match the requested characteristic to a semantic feature by description, callout, location, and function.
2. Distinguish the semantic group count from the number of SolidWorks operations used to create it.
3. Cite the expected drawing view or detail only when the profile provides it.
4. Use exact feature or region IDs from context for any requested visual target.
5. State ambiguity when several semantic features could match.

## Boundaries

- Do not present operation names such as `Cut-Extrude1` as the user-facing feature name.
- Do not invent dimensions, tolerances, feature counts, or drawing locations.
- Do not infer hidden geometry from one projection when the profile marks it uncertain.
- A feature explanation is read-only unless the user explicitly requests a viewport change.
