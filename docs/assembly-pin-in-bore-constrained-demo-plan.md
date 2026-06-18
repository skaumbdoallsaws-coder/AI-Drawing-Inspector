# Constrained Assembly New-Part Demo Plan: Pin Into Piston Bore

Saved: 2026-05-28

## Goal

Build a constrained demo where Sage designs a simple cylindrical pin that fits into a specific bore in an existing SolidWorks assembly.

Example operator request:

```text
Design a pin that fits into this piston bore with 0.10 mm clearance.
```

The demo should show Sage coordinating across InspectorPro and SolidWorks:

1. InspectorPro understands the assembly context.
2. Sage prepares a structured new-part-design handoff.
3. SolidWorks Sage previews the target bore and proposed pin.
4. The operator approves.
5. SolidWorks creates the pin part, inserts it into the assembly, mates it to the bore, rebuilds, and saves.
6. InspectorPro refreshes the assembly and compares before/after.

This is a controlled engineering workflow, not unconstrained text-to-CAD.

## MVP Positioning

This first version should solve one narrow case:

```text
Create a straight cylindrical pin for a selected cylindrical bore.
```

It should not attempt arbitrary part design.

The demo is credible if it can:

- identify or confirm the bore,
- read the bore diameter and axis from SolidWorks,
- calculate a pin diameter using clearance,
- choose a pin length from bore depth or an operator-provided length,
- preview the target and proposed dimensions,
- create the pin only after approval,
- insert and mate the pin into the assembly,
- refresh back into InspectorPro as a new revision.

## Hard Safety Rule

Sage must not create geometry from a vague phrase alone.

For MVP, SolidWorks must confirm the target bore using one of these:

1. operator-selected cylindrical face in SolidWorks, or
2. one unambiguous region/face resolved from InspectorPro and verified in SolidWorks preview.

If the bore cannot be confirmed, the workflow stops at preview.

## Current Foundation Already Available

InspectorPro already has:

- part/assembly library revisions,
- GLB visual extraction,
- semantic regions for selected parts,
- feature intent and dimension intent work,
- edit session logs,
- SolidWorks handoff pipeline,
- SolidWorks Sage task pane,
- gated preview/apply execution,
- rebuild/save,
- re-extract/refresh,
- revision compare.

The missing layer is a new handoff type and SolidWorks-side geometry reader for assembly fit targets.

## New Concept: Fit Target

Introduce a read-only target description for assembly fit design.

```json
{
  "targetType": "cylindrical_bore",
  "selectionRequired": true,
  "selectedEntityType": "face",
  "geometry": {
    "diameterMm": 12.0,
    "radiusMm": 6.0,
    "axisOriginMm": [0, 0, 0],
    "axisDirection": [0, 0, 1],
    "depthMm": 25.0,
    "isThrough": false
  },
  "assemblyContext": {
    "assemblyPath": "C:/.../engine.SLDASM",
    "componentName": "Piston",
    "owningPartPath": "C:/.../piston.SLDPRT"
  }
}
```

For MVP, this data comes from SolidWorks after preview/selection, not from mesh guessing.

## Handoff Contract

Add a new handoff type:

```text
new_part_design_handoff
```

Request shape from InspectorPro to SolidWorks:

```json
{
  "handoffType": "new_part_design",
  "handoffVersion": "new-part-design-handoff-0.1",
  "sessionId": "01...",
  "partNumber": "engine_assembly_or_library_id",
  "sourceRevision": "revA",
  "userInstruction": "Design a pin that fits into this piston bore with 0.10 mm clearance.",
  "designIntent": {
    "partKind": "cylindrical_pin",
    "fitTarget": "cylindrical_bore",
    "clearanceMm": 0.10,
    "lengthPolicy": "use_bore_depth",
    "endTreatment": "flat",
    "material": null
  },
  "target": {
    "semanticPhrase": "piston bore",
    "requiresSolidWorksSelection": true,
    "resolvedRegions": [],
    "candidateComponents": []
  },
  "operationPolicy": {
    "canCreate": false,
    "requiresHumanReview": true,
    "blockedReason": "Bore face must be confirmed in SolidWorks preview before creating the pin."
  }
}
```

`canCreate` stays false until SolidWorks preview confirms a valid cylindrical face and computes a proposal.

## SolidWorks Preview Flow

The SolidWorks Sage pane should show:

```text
Incoming New Part Design Handoff
Request: Design a pin for piston bore
Status: Needs target bore selection

[Use Current Selection As Bore]
[Preview Pin Proposal]
[Reject]
[Create Pin Part] disabled
```

### Preview Steps

1. Operator selects a cylindrical bore face in SolidWorks.
2. Clicks `Use Current Selection As Bore`.
3. Add-in validates:
   - active document is an assembly,
   - selected entity is a face,
   - face surface is cylindrical,
   - radius is finite and positive,
   - axis is available,
   - owning component can be identified.
4. Add-in computes:
   - bore diameter,
   - pin diameter = bore diameter - clearance,
   - pin length = bore depth if available, otherwise operator must enter length,
   - insertion axis,
   - insertion origin.
5. Add-in displays preview:

```text
Target bore:
- Component: Piston
- Bore diameter: 12.00 mm
- Bore depth: 25.00 mm

Proposed pin:
- Diameter: 11.90 mm
- Length: 25.00 mm
- Clearance: 0.10 mm
- End treatment: flat

This will create a new cylindrical pin part and insert it into the assembly.
```

6. `Create Pin Part` becomes enabled only after preview passes all gates.

## Create Pin Execution

On approval, SolidWorks add-in should:

1. create a new part document from a configured part template,
2. create a sketch on the appropriate plane,
3. draw a circle using the proposed pin diameter,
4. extrude to proposed pin length,
5. save the new part under a generated path,
6. insert the part into the active assembly,
7. add mates:
   - concentric mate to the bore axis,
   - coincident or distance mate to locate the pin axially,
8. rebuild,
9. save assembly,
10. report result back to the task pane.

No multi-body or complex features in MVP.

## File Naming

Use deterministic names so the demo is repeatable:

```text
{assemblyBaseName}_Sage_Pin_{sessionShortId}.SLDPRT
```

Example:

```text
EngineBlockAssembly_Sage_Pin_01KSKH.SLDPRT
```

Store the new part next to the assembly or inside a configured `SageGeneratedParts` folder.

The result should include:

```json
{
  "createdPartPath": "C:/.../SageGeneratedParts/Engine_Sage_Pin_01KSKH.SLDPRT",
  "insertedComponentName": "Engine_Sage_Pin_01KSKH-1",
  "matesCreated": ["concentric", "coincident"],
  "rebuildOk": true,
  "saveOk": true
}
```

## InspectorPro Session Log

Add a new session type or extend edit sessions carefully.

Recommended: new session category:

```text
design_session
```

Reason: creating a new part is materially different from editing an existing feature.

Session lifecycle:

```text
prepared
sent_to_solidworks
target_confirmed
proposal_previewed
created_in_solidworks
extracted
promoted
compared
abandoned
failed
```

MVP can store this under:

```text
400S_Sorted_Library/_design_sessions/{sessionId}.json
```

## InspectorPro Refresh Flow

After SolidWorks creates and saves the pin:

1. User clicks `Refresh From SolidWorks` in InspectorPro.
2. InspectorPro asks the bridge to extract the active assembly.
3. Extraction creates a new package.
4. InspectorPro promotes it as the next revision.
5. InspectorPro drafts semantic/feature summaries if available.
6. InspectorPro opens assembly compare.
7. Sage answers:

```text
Rev B adds a new cylindrical pin inserted into the piston bore.
The pin diameter is 11.90 mm, giving 0.10 mm clearance against the 12.00 mm bore.
The pin was inserted concentrically with the bore axis.
```

## RAG / Reference Layer

For this constrained demo, references should be used as a checklist, not as an autonomous design authority.

Possible reference categories:

- internal design-practice checklist,
- fit/clearance table if available,
- company standard for generated part names,
- assembly mating best practices,
- drawing/checking checklist for generated components.

Final summary should include:

```json
{
  "referencesUsed": [
    {
      "title": "Internal fit-design checklist",
      "sourceType": "internal_checklist",
      "reasonUsed": "Used to require explicit clearance and bore confirmation before creating pin geometry.",
      "confidence": "medium"
    }
  ]
}
```

Do not invent standards or claim ASME/ISO compliance unless a specific retrieved reference was actually used.

## MVP Implementation Tracks

### Track A: InspectorPro Handoff Contract

Main app.

Add:

- `new_part_design_handoff` payload builder,
- deterministic parser for pin/bore requests,
- design session JSON log,
- send-to-SolidWorks route using existing bridge auth/port mechanism,
- tests for parser, payload shape, session creation, and send route.

Example operator prompts:

```text
Prepare a SolidWorks handoff to design a pin for the piston bore with 0.10 mm clearance.
Design a cylindrical pin that fits into the piston bore.
Create a pin for this bore using 0.1 mm clearance.
```

Parser should extract:

- `partKind = cylindrical_pin`
- `fitTarget = cylindrical_bore`
- `clearanceMm`, default only if explicitly configured
- optional length if stated

No hidden defaults for demo-critical dimensions unless shown to the user.

### Track B: SolidWorks Read-Only Fit Preview

Add-in.

Add:

- new DTO for `new_part_design`,
- queue card type for new-part handoff,
- `Use Current Selection As Bore`,
- cylindrical face validation,
- bore geometry extraction,
- pin proposal calculation,
- preview UI.

No writes yet.

Tests:

- payload deserialization,
- clearance math,
- invalid target rejection,
- finite positive dimension gates,
- create button disabled until preview passes.

### Track C: Gated Pin Creation

Add-in.

Add:

- `Create Pin Part` button,
- confirmation dialog with Cancel default,
- part creation helper,
- sketch circle + extrude,
- save generated part,
- insert component,
- create mates,
- rebuild/save gates,
- result logging.

Safety gates:

- active doc still same assembly,
- target face still valid or target geometry re-confirmed,
- pin diameter finite and positive,
- pin length finite and positive,
- generated path does not overwrite existing file,
- confirmation dialog accepted,
- rebuild succeeds before save is reported successful.

### Track D: InspectorPro Refresh + Compare

Main app.

Reuse the refresh-from-SolidWorks pattern:

- active-doc gate,
- auto-extract assembly,
- promote next revision,
- compare before/after,
- cache comparison context for Sage.

Sage answer should be user-level by default:

```text
A new pin was added to the piston bore. It was sized for 0.10 mm clearance and inserted concentrically with the bore.
```

Technical details only when asked:

```text
Show the SolidWorks operations and mates used.
```

## Demo Script

1. Open engine assembly in SolidWorks.
2. Open matching assembly revision in InspectorPro.
3. Ask Sage:

```text
Prepare a SolidWorks handoff to design a cylindrical pin for the piston bore with 0.10 mm clearance.
```

4. SolidWorks Sage receives handoff.
5. Select bore face.
6. Click `Use Current Selection As Bore`.
7. Preview shows bore diameter, pin diameter, clearance, length, and insertion axis.
8. Click `Create Pin Part`.
9. SolidWorks creates/inserts/mates pin.
10. InspectorPro `Refresh From SolidWorks`.
11. InspectorPro opens compare.
12. Ask:

```text
What changed after the pin design handoff?
```

Expected answer:

```text
A new cylindrical pin was added to the piston bore. It was sized with 0.10 mm clearance from the bore and inserted concentrically along the bore axis.
```

## Key Risks

### Bore Depth

Reading bore depth robustly may be difficult from a single cylindrical face.

MVP fallback:

- if depth is not reliable, require operator-entered length,
- show `lengthSource = operator_input`.

### Assembly Mates

Mate creation can fail depending on component state, face ownership, lightweight components, or rebuild errors.

MVP fallback:

- create and insert the pin,
- if mates fail, report partial success and keep document dirty state honest.

### Face Identity Drift

Selected face references may become invalid after rebuild.

MVP mitigation:

- capture geometry for preview,
- re-check active assembly and selection before execution,
- avoid using stale COM references when possible.

### Clearance Defaults

Do not silently pick clearance in the demo.

If user does not provide clearance, ask for it or use an explicit visible default:

```text
No clearance was specified. Use 0.10 mm clearance?
```

### Generalization

This demo does not solve arbitrary part design.

It proves a controlled pattern:

```text
assembly context + fit target + constrained part template + human approval + refresh/compare
```

## Acceptance Criteria

The demo is ready when:

- Sage can prepare the pin-in-bore handoff from natural language.
- SolidWorks Sage receives the handoff.
- Operator can select a bore face.
- Preview extracts bore diameter and computes pin diameter.
- Create button stays disabled until preview is valid.
- Approval creates a simple pin part.
- Pin is inserted into the assembly.
- At least one mate is created or a clear partial-success reason is shown.
- Rebuild/save status is accurate.
- InspectorPro refresh creates a new revision.
- Compare shows the new pin.
- Sage can explain the before/after change in user-friendly language.

## Claude Review Prompt

Use this prompt to have Claude review the plan before implementation:

```text
Review this constrained demo plan for designing a cylindrical pin that fits into a piston bore in an existing SolidWorks assembly.

Focus on implementation risks, missing safety gates, SolidWorks API feasibility, and whether the scope is tight enough for a reliable demo.

Do not propose general text-to-CAD. Keep the MVP constrained to:
- operator-confirmed cylindrical bore face,
- read-only bore geometry preview,
- calculated cylindrical pin,
- human-approved part creation,
- assembly insert/mate,
- rebuild/save,
- re-extract and compare in InspectorPro.

Please identify:
1. blocking technical risks,
2. incorrect assumptions,
3. missing data fields in the handoff,
4. tests that must be added,
5. what should be deferred.
```

## Recommended Next Step

Do Track B first as a read-only SolidWorks preview.

Reason: the hardest unknown is not creating a cylinder. The hardest unknown is reliably selecting, validating, and extracting the bore face geometry from the assembly. Once that works, the rest of the demo becomes a controlled execution problem.
