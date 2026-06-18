# Drawing Revision Handoff Plan

Status: implementation plan for Sage + SolidWorks drawing revision workflow.

## Goal

Given an existing drawing revision in InspectorPro, Sage should prepare a controlled handoff to the SolidWorks Sage add-in so the operator can create or update a new drawing revision in SolidWorks. After SolidWorks saves the drawing, InspectorPro should refresh the drawing package, promote it as the next drawing revision, and open drawing compare against the source revision.

This is not free-form "AI draws anything." The workflow must stay constrained, reviewable, and reversible:

1. InspectorPro identifies the source drawing revision and desired target revision.
2. Sage creates a structured drawing-revision handoff.
3. SolidWorks Sage previews the drawing plan.
4. The operator approves the drawing operation.
5. The add-in creates/updates the drawing revision through the SolidWorks API.
6. InspectorPro extracts the updated drawing.
7. InspectorPro promotes it under the target revision.
8. InspectorPro opens Drawing Compare and Sage explains what changed.

## Existing Assets To Reuse

- Main app drawing extraction pipeline:
  - `/api/request-extraction` / drawing kind
  - root `{pn}_drawing_map.json`
  - root `{pn}_drawing.pdf`
  - per-revision archive `parts/{pn}/revX/{pn}_drawing_map.json`
  - per-revision archive `parts/{pn}/revX/{pn}_drawing.pdf`

- Drawing compare:
  - `GET /api/drawing-revisions/{part_number}`
  - `GET /api/drawing-diff/{part_number}?revA=A&revB=B`
  - Drawing Compare UI state in `static/index.html`

- Existing model edit-session pattern:
  - edit session JSON log
  - handoff to SolidWorks Sage pane
  - one-at-a-time queue
  - preview before apply
  - refresh-from-SolidWorks orchestration

- SolidWorks add-in:
  - `/sage/handoff` bridge endpoint
  - Sage task pane queue
  - preview/apply safety pattern
  - existing drawing extraction job runner

## New Contract: Drawing Revision Session

Do not overload CAD edit sessions. Drawing revision work has different gates and outputs.

Store one JSON file per session:

`400S_Sorted_Library/_drawing_sessions/{sessionId}.json`

Minimum schema:

```json
{
  "sessionId": "01...",
  "schemaVersion": "drawing-revision-session-0.1",
  "status": "prepared",
  "createdAtUtc": "...",
  "updatedAtUtc": "...",
  "partNumber": "1030035",
  "sourceRevision": "revA",
  "targetRevision": "revB",
  "requestedInstruction": "make a new drawing revision following the standard",
  "drawingStandard": {
    "name": "InspectorPro default mechanical drawing checklist",
    "source": "default"
  },
  "handoffPayload": {},
  "solidWorks": {
    "appliedAtUtc": null,
    "appliedByUser": null,
    "sourceDrawingPath": null,
    "targetDrawingPath": null
  },
  "extraction": {
    "drawingPackageId": null,
    "extractedAtUtc": null
  },
  "promotion": {
    "promotedRevision": null,
    "promotedManifestPath": null,
    "promotedAtUtc": null
  },
  "comparison": {
    "revA": null,
    "revB": null,
    "comparedAtUtc": null
  },
  "notes": []
}
```

Status enum:

- `prepared`
- `sent_to_solidworks`
- `previewed_in_solidworks`
- `applied_in_solidworks`
- `extracted`
- `promoted`
- `compared`
- `abandoned`
- `failed`

Terminal statuses:

- `compared`
- `abandoned`
- `failed`

## New InspectorPro Endpoints

### 1. Create drawing revision session

`POST /api/drawing-revision-sessions`

Request:

```json
{
  "partNumber": "1030035",
  "sourceRevision": "A",
  "targetRevision": "B",
  "instruction": "make a new drawing revision following the standard"
}
```

Validation:

- `partNumber` exists.
- `sourceRevision` has a drawing map in per-revision archive.
- `targetRevision` does not already contain a drawing map unless `overwriteConfirmed` is explicitly supplied later.
- Root/per-rev drawing map can be loaded and normalized.

Response:

```json
{
  "ok": true,
  "session": {},
  "sendToSolidWorks": {
    "url": "/api/drawing-revision-sessions/{sessionId}/send-to-solidworks"
  }
}
```

### 2. Send drawing handoff to SolidWorks

`POST /api/drawing-revision-sessions/{sessionId}/send-to-solidworks`

Builds a narrow wire payload and posts it to the SolidWorks bridge. This must be separate from CAD edit handoffs.

Wire payload:

```json
{
  "drawingSessionId": "01...",
  "kind": "drawing_revision",
  "partNumber": "1030035",
  "sourceRevision": "revA",
  "targetRevision": "revB",
  "requestedInstruction": "make a new drawing revision following the standard",
  "sourceDrawing": {
    "drawingMapPath": "parts/1030035/revA/1030035_drawing_map.json",
    "drawingPdfPath": "parts/1030035/revA/1030035_drawing.pdf"
  },
  "plan": {
    "actions": [
      "copy_or_save_as_new_revision",
      "verify_title_block",
      "verify_standard_views",
      "verify_dimensions_and_annotations",
      "save_and_rebuild"
    ],
    "requiresHumanApproval": true
  }
}
```

### 3. Refresh drawing from SolidWorks

`POST /api/drawing-revision-sessions/{sessionId}/refresh-from-solidworks`

Behavior:

1. Check active SolidWorks document is a drawing.
2. Verify active drawing title/path appears to belong to the session part number or source/target drawing.
3. Run existing drawing extraction through bridge.
4. Promote extracted root drawing map/PDF into `parts/{pn}/{targetRevision}/`.
5. Update session status to `promoted`.
6. Return drawing compare URL/context.

Response:

```json
{
  "ok": true,
  "partNumber": "1030035",
  "sourceRevision": "revA",
  "promotedRevision": "revB",
  "drawingPackageId": "...",
  "nextCompare": {
    "revA": "A",
    "revB": "B",
    "url": "/api/drawing-diff/1030035?revA=A&revB=B"
  }
}
```

## SolidWorks Add-In Changes

Add a separate drawing handoff sink or extend the existing sink with a `kind` discriminator.

Recommended DTO:

```csharp
internal sealed class SageDrawingHandoff
{
    public string? DrawingSessionId { get; set; }
    public string? Kind { get; set; } // "drawing_revision"
    public string? PartNumber { get; set; }
    public string? SourceRevision { get; set; }
    public string? TargetRevision { get; set; }
    public string? RequestedInstruction { get; set; }
    public SageDrawingSource? SourceDrawing { get; set; }
    public SageDrawingPlan? Plan { get; set; }
}
```

UI behavior:

- Queue drawing revision handoffs separately from model edit handoffs or show a clear "Drawing Revision" badge.
- Buttons:
  - `Preview Drawing Plan`
  - `Create Drawing Revision`
  - `Reject`
- Do not show internal architecture details in public demo mode.

Preview gates:

- Active document is a SolidWorks drawing.
- Active drawing references the expected part, when this can be verified.
- Source revision exists in the handoff.
- Target revision is present and different from source.
- Plan is limited to approved drawing actions.

Apply gates:

- Confirmation dialog with Cancel as default.
- Save/rebuild only after preview passes.
- Never overwrite an existing drawing without explicit confirmation.
- Log every action to `addin.log`.

MVP apply action:

For the first pass, do not attempt full autonomous standards-compliant drafting. The MVP should:

1. Save/copy the active drawing as the target revision file.
2. Update revision/title-block fields only if the fields are discoverable safely.
3. Rebuild and save.
4. Leave all layout/dimension edits to later phases.
5. Return a checklist saying what was verified and what still requires human review.

Later phases can add deterministic drawing layout operations:

- insert/update standard views
- add model dimensions
- add center marks
- add notes
- add section/detail views
- run screenshot critique loop

## Sage Prompt Behavior

Add deterministic fast path for requests like:

- "Prepare a drawing revision handoff for 1030035 Rev A to create Rev B following the standard."
- "Tell SolidWorks Sage to make a new drawing rev from this drawing."
- "Create the next drawing revision and then compare it."

Default response:

```text
Prepared the drawing revision handoff for 1030035 Rev A -> Rev B.

SolidWorks will preview the drawing plan before anything is changed. After approval, refresh the drawing back into InspectorPro and compare Rev A vs Rev B.
```

Do not claim the drawing is ASME-compliant unless validation checks prove it. Use "standard checklist" or "review checklist" language.

## UI Additions

Sessions tab should either:

- add a `Drawing Sessions` filter, or
- add a separate top-level `Drawing Sessions` tab later.

MVP buttons:

- `Send to SolidWorks`
- `Refresh Drawing from SolidWorks`
- `Open Drawing Compare`
- `Mark Abandoned`

After refresh succeeds:

- auto-open Drawing Compare for `sourceRevision` vs `targetRevision`
- cache compare context so Sage can answer "what changed in the drawing?"

## Tests To Add

Main app:

1. Create drawing session requires existing source drawing map.
2. Create drawing session rejects target rev that already has drawing map.
3. Send-to-SolidWorks builds correct `kind: drawing_revision` payload.
4. Refresh-from-SolidWorks rejects when bridge active doc is not drawing.
5. Refresh-from-SolidWorks extracts and promotes target rev drawing map/PDF.
6. Refresh response includes `/api/drawing-diff/{pn}?revA=X&revB=Y`.
7. Sage fast path creates/sends drawing handoff without model call.
8. Missing source drawing map returns clear 404.

SolidWorks add-in:

1. Drawing handoff validates required fields.
2. Drawing handoff renders as drawing revision, not CAD edit.
3. Preview disabled when active doc is not drawing.
4. Apply disabled until preview succeeds.
5. Confirmation dialog exists with Cancel default.
6. Apply refuses overwrite without explicit target confirmation.
7. Public demo mode hides internal fields.

## MVP Demo Script

1. Load part drawing Rev A in InspectorPro.
2. Ask Sage:

   `Prepare a drawing revision handoff for 1030035 Rev A to create Rev B following the standard.`

3. SolidWorks Sage receives "Drawing Revision" handoff.
4. Click `Preview Drawing Plan`.
5. Click `Create Drawing Revision`.
6. In InspectorPro Sessions, click `Refresh Drawing from SolidWorks`.
7. InspectorPro extracts the drawing, promotes Rev B, and opens Drawing Compare.
8. Ask Sage:

   `What changed between drawing Rev A and Rev B?`

## Non-Goals For MVP

- No free-form macro execution.
- No automatic GD&T invention.
- No tolerance invention.
- No claim of ASME compliance.
- No autonomous drawing-layout iteration yet.
- No overwrite of existing drawing revisions without explicit confirmation.

