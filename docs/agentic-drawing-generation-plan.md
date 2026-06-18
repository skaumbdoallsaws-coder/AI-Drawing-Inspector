# Agentic Drawing Generation Plan

Status: saved idea / future implementation track.

## Core Idea

InspectorPro + Sage-in-SolidWorks should eventually create a professional draft manufacturing drawing from a finished SolidWorks part, then critique and improve that drawing through a visual feedback loop before presenting it to the user.

This should not be framed as "an LLM magically generates a drawing." The credible workflow is a controlled engineering loop:

1. Understand the finished model.
2. Plan the drawing from semantic regions, feature intent, drawing standards, and inspection needs.
3. Execute drawing creation through the SolidWorks API.
4. Export or screenshot the result.
5. Visually critique the output.
6. Iterate until the drawing is acceptable or a max-iteration limit is reached.
7. Return a draft drawing plus a human-review checklist.

## Why This Matters

Once Sage can understand an existing part and its semantic regions, drawing generation becomes a natural next step. The drawing is a visual artifact, so the agent should not stop after API execution. It should inspect the actual result visually and correct layout or completeness problems.

The differentiator is the loop:

- SolidWorks API creates the drawing.
- InspectorPro evaluates the exported drawing.
- Sage decides what needs to improve.
- Sage-in-SolidWorks applies another drawing-layout pass.
- The loop repeats until the output is acceptable.

## Proposed Architecture

### 1. Semantic Model Understanding

Inputs:

- Part metadata.
- Semantic regions.
- Feature intent map.
- Inspection profile.
- Revision context.
- Available feature colors / CAD feature IDs.
- Optional drawing-map history from prior revisions.

The agent should know physical names like "propeller blade", "outer wing strut", "mounting face", or "bore", and map those names to the SolidWorks feature tree.

### 2. Standards-Aware Drawing Planner

The planner decides:

- Sheet size.
- Projection type.
- View set: front, top, right, isometric, section, detail.
- Scale.
- Which features need dimensions.
- Which hidden lines / centerlines / center marks are needed.
- Where section/detail views are justified.
- Which notes belong on the sheet.
- Title block fields.
- Inspection-critical or functionally important dimensions.

The planner should reference drawing standards and shop conventions, but must be honest when a decision is inferred rather than specified.

### 3. SolidWorks Drawing Executor

Sage-in-SolidWorks should execute drawing operations through the SolidWorks API:

- Create drawing from part.
- Apply sheet format.
- Insert model views.
- Insert projected views.
- Insert section/detail views.
- Add model dimensions or selected reference dimensions.
- Add center marks / centerlines.
- Add notes.
- Populate title block fields.
- Rebuild/save/export PDF.

Execution should be deterministic and audit logged. No free-form unsafe macro execution.

### 4. Visual Critique Loop

After each execution pass:

- Export drawing image/PDF or take a screenshot.
- Inspect the rendered drawing visually.
- Detect layout problems:
  - overlapping dimensions
  - crowded annotations
  - dimensions outside readable areas
  - missing center marks
  - missing section/detail views
  - bad scale
  - views too small or too large
  - hidden geometry ambiguity
  - title block missing fields
- Compare against a standards/checklist layer.
- Produce a correction plan.
- Re-run the SolidWorks drawing executor.

The loop stops when:

- the checklist passes,
- the agent reaches a max iteration count,
- or the operator stops it.

### 5. Final Validation

Before giving the drawing to the user:

- Run drawing-map extraction.
- Run inspection/profile consistency checks.
- Compare dimensions and annotations against the part metadata and feature intent map.
- Emit a human-review checklist.

The output should be labeled as a draft until reviewed.

## Demo Flow

Possible demo:

User:

> Create a manufacturing drawing for this finished part.

System flow:

1. Sage plans the drawing.
2. Sage-in-SolidWorks creates the drawing.
3. InspectorPro takes/receives the exported drawing screenshot.
4. Sage critiques the drawing visually.
5. Sage-in-SolidWorks adjusts layout.
6. InspectorPro reviews the final drawing and lists remaining review items.

Positioning:

This is not "text-to-CAD." It is an AI-assisted engineering workflow for an existing engineered part:

- understand existing geometry,
- create a standards-informed drawing,
- visually review the generated artifact,
- iterate toward a professional result.

## Safety / Honesty Constraints

- Always label the result as a draft drawing until reviewed.
- Do not claim ASME/GD&T compliance unless validated by explicit checks.
- Do not invent tolerances or material notes.
- Separate inferred layout decisions from drawing requirements.
- Keep a revisioned audit log of drawing-generation passes.
- Keep the SolidWorks execution contract narrow and inspectable.

## Future Implementation Tracks

1. Drawing planning schema.
2. SolidWorks drawing executor shell.
3. Drawing screenshot/export capture.
4. Visual critique checklist.
5. Iterative correction loop.
6. Drawing-map extraction and validation.
7. UI for "Create Draft Drawing" and review checklist.

---

# Related Track: Assembly-Aware New Part Generation

Status: saved idea / future implementation track.

## Core Idea

Once Sage can safely modify sketches and features, the same controlled execution architecture can create new parts that fit into an existing assembly.

Example:

> Design a pin that fits into the piston bore in this engine block.

The important distinction is that Sage should not invent an isolated shape. It should design from assembly context:

- where the part needs to go,
- what geometry it must fit,
- how long it should be,
- what diameter / clearance it should use,
- what mates or constraints it needs,
- and whether it collides with nearby components.

## Required Context

For a simple pin-in-bore demo, Sage needs:

- selected or resolved semantic region: piston bore / bore axis / mounting hole,
- cylindrical face diameter,
- bore axis and coordinate frame,
- insertion depth or available span,
- clearance rule or user-specified fit,
- neighboring components and collision envelope,
- assembly transform for the target part,
- material / naming / part-number convention,
- revision and library-intake destination.

Some of this can come from InspectorPro semantic regions and GLB/feature metadata. The precise geometry should come from Sage-in-SolidWorks querying the active assembly and selected faces/features through the SolidWorks API.

## Proposed Flow

1. User asks for a fitted component.
2. Sage resolves the assembly region or asks the user to select the target face/feature in SolidWorks.
3. Sage-in-SolidWorks measures the target geometry:
   - bore diameter,
   - bore axis,
   - available length,
   - nearby interference envelope.
4. Sage proposes a design intent:
   - "Create a cylindrical pin, diameter = bore diameter minus clearance, length = available span minus end clearance."
5. User approves.
6. Sage-in-SolidWorks creates a new SLDPRT:
   - sketch circle,
   - extrude/revolve pin body,
   - add chamfers/fillets,
   - assign material if specified,
   - save with generated part number.
7. Sage inserts the part into the assembly:
   - concentric mate to bore axis,
   - coincident/distance mate for axial position.
8. Sage runs rebuild/interference checks.
9. Sage exports screenshots or viewport captures.
10. InspectorPro/Sage visually critiques the result.
11. Sage iterates until the part fits or max iterations are reached.
12. The new part is pushed through library intake.

## Safety / Honesty Constraints

- Do not claim the design is production-ready.
- Ask for missing engineering requirements:
  - clearance,
  - fit class,
  - material,
  - retention method,
  - load case,
  - tolerance,
  - finish.
- Keep the first demo to simple axisymmetric parts.
- Use deterministic SolidWorks API operations, not arbitrary macro generation.
- Keep a generated-part audit log:
  - source assembly,
  - selected region,
  - measurements used,
  - parameters chosen,
  - operations created,
  - screenshots/reviews,
  - final part number and revision.

## Visual Feedback Loop

The loop is similar to drawing generation:

- create or update the part,
- rebuild assembly,
- capture viewport / section screenshots,
- run interference and clearance checks,
- critique visual fit,
- adjust dimensions or placement,
- repeat.

This is especially important for more complex fitted parts where numeric measurements alone are not enough. Sage may need both geometry queries and visual context before deciding whether the part looks correctly positioned and proportioned.

## MVP Demo Candidate

Pin for a bore:

- simple cylindrical geometry,
- measurable target diameter and axis,
- easy visual validation,
- easy interference/clearance validation,
- creates a new part rather than editing an existing one,
- shows the system can go from assembly context to new manufacturable component draft.

## Missing Platform Layers

1. SolidWorks face/feature measurement endpoint.
2. Assembly region/selection handoff from InspectorPro to Sage-in-SolidWorks.
3. Sketch creation executor.
4. Feature creation executor.
5. New part-number generation from SolidWorks-side workflow.
6. Assembly insertion and mate executor.
7. Interference/clearance check endpoint.
8. Screenshot capture + visual critique loop.
9. Library intake shortcut for generated parts.
