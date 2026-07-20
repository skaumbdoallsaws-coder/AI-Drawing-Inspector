# Functional Relationship Layer

Status: implemented for assembly 100001

## Purpose

The functional relationship layer describes how an assembly works without
embedding drawing dimensions, tolerances, or measured inspection values. It is
the stable product-function context between raw CAD structure and inspection
reasoning.

The runtime keeps four evidence classes separate:

1. CAD structure and mates identify present components and geometric constraints.
2. Curated part profiles identify semantic features and reviewed part roles.
3. Validated motion packages identify observed relative motion and joint closure.
4. FAI and drawing evidence provide dimensions, limits, and measured values.

At question time, InspectorPro deterministically maps a failed characteristic to
one semantic feature and the graph interfaces that use that feature. The model
receives the separate FAI calculation plus the relevant normal function,
participants, relative motion, load path, qualitative requirements, confidence,
and missing-evidence boundary.

## Runtime Contract

The graph contains:

- Assembly identity and evidence hashes.
- Physical and organizational component instances.
- Reusable component types and stable functional feature references.
- Present and explicitly absent external entities.
- Instance-level interfaces grouped by reusable pattern IDs.
- Normal function, permitted relative motion, constrained motion, transfer modes,
  qualitative requirements, evidence classification, confidence, and review state.
- Deterministically computed physical-instance coverage.

The graph must not contain nominal values, tolerances, measured values, fit limits,
or numeric dimensions. Those remain in drawing and FAI evidence.

## Engine Assembly Coverage

Assembly 100001 contains 43 extracted nodes: 38 physical components and 5
organizational assembly nodes. The reviewed graph covers all 38 physical
instances through 40 interfaces.

Covered interface patterns include:

- Lower-block main-bearing support and crankcase clearance.
- Crank-pin split journal bearings.
- Bolted rod-cap clamp joints.
- Piston-pin and rod-pin bearings.
- Rod small-end side guidance.
- Piston-to-cylinder prismatic guidance.
- Piston-ring groove retention and cylinder sealing contact.
- Piston-skirt-to-crank dynamic clearance.
- Lower-deck structural transfer and crankshaft output coupling.

The upper cylinder block and driven system are not present in the extracted
assembly. They are represented as `absent_from_extract` external entities. This
lets Sage explain the expected piston-to-cylinder interface while preventing a
false claim that the current CAD package contains cylinder-bore evidence.

## Characteristic Join

The join is deterministic and read-only:

1. Limit candidate features to the inspected part number.
2. Prefer an explicit functional feature reference when one exists.
3. Otherwise match the characteristic description against reviewed feature
   aliases and semantic tags.
4. Require a minimum match score.
5. Select only interfaces that reference the matched feature.
6. Traverse one adjacent interface through a non-inspected physical participant
   to expose the immediate load or motion path.
7. Never authorize a viewport action or disposition from this join.

Example: a failed piston outside diameter joins to
`piston.skirt-running-surface`, then `piston-cylinder-guide`. A failed piston pin
bore joins to `piston.pin-bores`, then `piston-pin-bearing`, with the adjacent
`rod-pin-bearing` exposed through the shared pin.

## APIs

- `GET /api/functional-relationships/{assembly_number}` returns the complete
  graph and validation report.
- `GET /api/functional-relationships/{assembly_number}/part/{part_number}`
  returns compact part-specific interface patterns.
- `GET /api/assembly-context/{part_number}` includes the compact functional
  context when a reviewed graph exists.

Sage receives the compact provider only when an assembly-impact or
assembly-context skill is selected. Other compiled workflows do not receive it.
Legacy prompts render it only for a functional or assembly relationship question.

## Adding Another Assembly

1. Assemble a support packet with the assembly extract, instance hierarchy,
   part-number map, all part profiles, relevant motion summary, and orthographic
   or section views.
2. Author component functional features using stable semantic references. Do not
   copy dimensions into the graph.
3. Author instance-level interfaces. Mark every claim as CAD mate, hierarchy,
   part profile, validated motion, or reviewed engineering inference.
4. Represent expected but absent mating systems as external entities with an
   explicit presence state.
5. Run the strict validator against the current assembly extract.
6. Resolve every uncovered physical instance or document why it is outside the
   graph scope. Production activation requires full declared coverage.
7. Review every `reviewed_inference` and `needs_confirmation` interface with an
   engineer before activation.
8. Add synthetic characteristic joins for the part families in that assembly.
9. Run the prompt-compilation, read-only authorization, and live answer smokes.
10. Version the graph whenever component identity, interface semantics, or source
    evidence changes.

## Verification

`tests/test_functional_relationships.py` verifies schema behavior, source hashes,
assembly identity parity, complete coverage, dimensional-data exclusion, semantic
joins, adjacent load-path traversal, router facts, prompt selection, provenance,
and isolation from unrelated skills.

`tests/smoke_functional_relationship_reasoning.py` exercises the running API and
Sage answer with the failed piston outside diameter. It requires a grounded
cylinder-guide explanation, a clearance consequence, an explicit missing-bore
boundary, and zero viewport tool calls.
