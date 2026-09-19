# YC Product Demo Script

Target length: 2:10-2:30. Keep InspectorPro visible from the first frame; do not begin on a blank screen.

## 0:00-0:12 | Problem and Founder

**Screen:** InspectorPro is open on the Drawing tab. Your camera is prominent.

**Say:**

> Manufacturers lose time and money because product knowledge is scattered across drawings, CAD files, inspection reports, and people's heads. I'm Shadrack, a mechanical engineer and founder of InspectorPro.

## 0:12-0:30 | Upload and Product Context

**Action:** Upload the piston drawing. Let InspectorPro load the part number and associated assets.

**Say:**

> I'll upload this customer's piston drawing. InspectorPro identifies the part and links it to its CAD model, inspection requirements, and parent engine assembly.

## 0:30-0:38 | Show the Connected Model

**Action:** Open the 3D Model tab and rotate the piston briefly.

**Say:**

> This is the exact CAD model linked to the drawing.

Stay here for only two or three seconds. The later workflow proves the rest of the connected context.

## 0:38-1:03 | First Article Inspection

**Action:** Open the FAI table, set the tolerances, and auto-fill nominal measurements. Enter the failed pin-bore measurement.

**Say:**

> The supplier has finished the part and is running first article inspection. InspectorPro fills the nominal dimensions from the drawing. Everything passes except the wrist-pin bore.

Pause briefly so the failed row is visible.

## 1:03-1:28 | Explain Assembly Impact

**Action:** Open the Assembly tab and ask Sage:

> What is the impact of the failed pin-bore dimension on the assembly?

**While Sage responds, say:**

> Sage combines the FAI result with the piston's functional relationships in the engine.

Allow the important part of Sage's answer to remain readable.

## 1:28-1:53 | Visualize the Motion

**Action:** Ask Sage:

> Show the affected components in motion.

Let the affected components highlight and the motion begin.

**Say:**

> InspectorPro highlights the affected components and plays the relevant motion, showing where the failed bore affects the assembly.

## 1:53-2:10 | Disposition and Next Action

**Action:** Return to the FAI table and ask Sage:

> What is the recommended disposition and next action?

**Say:**

> This case is covered by an engineer-approved rule, so Sage gives the final disposition immediately: scrap and replace the piston.

## 2:10-2:25 | Value and Closing

**Screen:** Keep the final disposition and InspectorPro branding visible. Keep your camera on screen.

**Say:**

> What normally takes days of email between suppliers, quality, sourcing, and engineering now takes minutes. InspectorPro is the product intelligence layer for manufacturers that build physical products from CAD.

End with the final disposition, your camera, and InspectorPro branding visible.

## Recording Checklist

- Open InspectorPro before recording and leave it on the Drawing tab.
- Position the cursor near the upload control before speaking.
- Keep the camera overlay away from the drawing upload panel and Sage chat.
- Remove long model-response waits in the edit, but preserve enough streaming to show that Sage is responding live.
- Pause narration briefly when an important Sage answer needs to be read.
- Run the complete workflow once immediately before recording.
- Use the exact three Sage questions shown above.
