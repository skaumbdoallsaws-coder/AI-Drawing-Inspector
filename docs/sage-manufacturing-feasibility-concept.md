# Sage Manufacturing Feasibility: Concept Note

Date: 2026-09-11
Status: Recorded idea for later review. Not an implementation plan or a claim of shipped capability.

## Objective

A user uploads or updates a part and asks: "Can we make this part with our equipment?"

Sage should understand the requirements, search manufacturing routes supported by available resources, and return a defensible route with an actionable blocker list. The product is not merely a feasibility label.

## Core Decision: Feasibility Is a Search

Do not finalize operations before considering equipment. Process choices, tooling, fixtures, machine configuration, inspection, and setup order constrain each other.

Use this conceptual loop:

```text
Part requirements and job objective
    -> candidate processes
    -> available machines, tooling, fixtures, and inspection resources
    -> candidate setups and operation sequences
    -> deterministic checks and evidence review
    -> revise the route when a constraint eliminates an option
    -> supported alternatives and ranked blockers
```

Distinguish a proven incompatibility from missing evidence. A bounded search that finds no route must not claim that no route exists unless the supported search space was exhausted.

## 1. Establish Installed Resources

Create revision-bound installed-configuration records linked to existing asset and placement identities. A catalog model is not proof of an installed option or available accessory.

Records should cover:

- Machine model, variant, installed options, and relevant documented limits.
- Chuck, jaws, turret, attachments, and supporting equipment.
- Searchable tooling and fixture inventory, including compatibility and applicable limits.
- Inspection equipment and evidence supporting the measurements it can perform.
- Evidence source, review state, and unresolved configuration details.

This is primarily a data-authoring and verification task, not an inference task. Missing installed data must remain missing rather than being filled from a sibling model or an optional brochure configuration.

## 2. Understand the Job

Extract or retrieve geometry, dimensions, material and condition, tolerances, datums, surface finish, threads, stock assumptions, quantity, and delivery requirements.

Keep documented requirements separate from calculated geometry and proposed assumptions. Geometry alone does not establish material or tolerance requirements.

Ask targeted questions only when missing information materially affects the next decision. Sage can retrieve evidence and eliminate clearly unsuitable options without refusing all preliminary analysis.

Separate these questions:

- Can a supported route physically produce the requested features?
- Can the available inspection resources verify the specified requirements?
- Can that route meet the requested quantity, delivery, and economic objectives?

Volume alone does not establish production suitability; cycle time, setup time, available capacity, and other relevant evidence are also needed.

## 3. Retrieve Capability Evidence

Use the shared evidence ladder discussed for Sage and Scout:

```text
Read the equipment document summary
    -> if insufficient, search and read the relevant manual pages
    -> if still insufficient, search authoritative web sources
    -> extract readable content and verify exact model and edition
    -> answer supported questions and retain unresolved gaps
```

The five-question equipment summaries are the first entry point: operation, fit and weight, required tooling/support, applicable limits, and missing information.

The proposed web reader should preserve table headings, units, footnotes, source links, and model boundaries. Keep originals available for page-image inspection when text extraction loses structure. Web content is evidence, not agent instructions.

A vector database is not a prerequisite for an initial document cache and searchable extracted-text implementation. Provider selection for web search and extraction remains open.

## 4. Search and Validate Complete Routes

Sage proposes and explains candidate processes and routes. Deterministic tools perform supported calculations and validate applicable constraints, including envelope, mass, travel, and documented speed or thread-pitch limits.

Evaluate the complete setup: part, stock, fixture, workholding, tools, attachments, and installed machine configuration. Passing a finished-part envelope check is not sufficient.

Every required operation must map to a supported resource and setup. Backtrack when a proposed operation lacks suitable equipment or tooling. External processing can be an explicitly identified alternative, not an assumed in-house capability.

Treat setup changes as potential tolerance events. Requirements spanning setups need explicit datum, workholding, and verification consideration. Individual machine capability does not prove the complete route can meet those requirements.

Inspection is a confirmation gate. Inability to verify a requirement blocks confirmed conformance, although it does not by itself prove physical fabrication impossible.

Do not infer achievable part tolerance from machine repeatability, or an executable robot operation from nominal payload and reach alone.

## 5. Deliver Actionable Results

Present:

- A supported candidate route and useful alternatives within the explored scope.
- Required machines, configurations, tooling, fixtures, setups, and inspections.
- Passed checks with evidence references.
- Ranked blockers identifying affected requirements, missing evidence or incompatibility, and the next action that could resolve each one.
- Explicit unknowns in capacity, cost, timing, or conformance.

Rank blockers by decision impact, then resolution effort when that effort is known. Do not call an option "best" without the user's objective and sufficient comparison evidence.

Retain useful verdict labels such as feasible on available evidence, conditionally feasible, unsupported by available equipment, or insufficient information, but make the route and next actions the primary output.

Reuse the existing evidence vocabulary: authored, derived, inferred, and unknown. Review and production approval are separate from those evidence states.

## 6. Capture Manufacturing Outcomes

When a part is actually manufactured, record the actual route, equipment configuration, tooling, fixtures, inspections, and deviations. Bind the result to the part, requirement, and resource revisions.

Compare the prediction with what happened: which blockers were real, how they were resolved, and whether the specified requirements were verified. A successful job is evidence for its recorded conditions, not blanket approval for future parts or revised setups.

## First Demonstration

A stepped shaft with a threaded end is a narrow candidate example, not a pre-approved manufacturing route. Final process and setup selection must follow the actual drawing and installed resources.

Use three independently established controls:

1. Positive: a previously manufactured part with documented requirements, actual setup, and inspection results. Obtain this evidence; do not assume it already exists in the project.
2. Negative: a part or setup incompatible for a documented, independently checked reason. State whether rejection applies to one machine or to the complete available route set.
3. Conditional: a job with a deliberate information gap, followed by the configuration or evidence that resolves it and appropriately changes the conclusion.

Success means Sage finds a defensible route, rejects an unsupported route with a specific reason, and updates its assessment correctly when evidence changes. Test requirement preservation after a part revision or conversational correction as well.

## Boundaries and Next Decision

This note does not authorize inferred machine ratings, fabricated setup details, automatic production approval, CAM generation, machine execution, or unsupported cost and throughput promises.

The next planning step is to select the positive-control part and installed resources, audit their available evidence, and define the bounded process and validator scope. Do not begin with an unrestricted manufacturing planner.

Related starting documents:

- [Equipment capability assessment](facility-equipment-documented-capability-answers-2026-09-09.md)
- [Manufacturer specification research](facility-asset-manufacturer-specification-research-2026-09-09.md)

This note records the discussion only; it does not independently re-verify those documents or the implementation.
