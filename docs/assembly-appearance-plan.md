# Appearances on assemblies, applied by Sage before the capture

## Why

The user, 2026-10-25, during the spec-sheet build: "make the appearance tool available to Sage in the 3D assembly
and all the documentation workflow so we can have a better appearance of the machine or equipment on the
specification sheet. Sage will apply a given appearance before the capture is done."

Today a machine on a sheet is uniform neutral grey (or its source colours, which for library models are a body
identification palette: red, green, purple...). The Facility workflow already has an appearance library (29
finishes such as `paint-safety-yellow`, `steel-brushed`, glass) that Sage applies to placed equipment.

## What exists (read 2026-10-25)

- Library: `static/facility_library/appearances.json`, read by `ai_inspector/facility_layout/appearance_library.py`
  (`load_library`, `normalize_overrides`, `library_summary`). An appearance has `appearanceId`, `label`,
  `category`, `model`, `color`, `roughness`, `metalness`, `opacity` (physical rows add transmission and
  clearcoat), and an optional texture. Per-use overrides: color, roughness, metalness, opacity and texture fields.
- Facility: Sage applies them as layout edits (`set_appearance`, `set_component_materials`); the finish code
  (`facility_layout_finishes.js`) is three r184.
- Assembly viewer: three r128 with a minimal GLB loader (no UVs, no textures). Every highlight pass resets each
  mesh's material to neutral grey or its source colours (`_applyAssemblyMaterialAppearance`,
  `_applyAssemblyMeshBaseMaterial`); the capture runs that pass, then draws the live scene. No environment map.
  Nothing about appearance is stored for an assembly, and nothing makes a capture stale when colours change.
- Sage: on the ChatGPT plan, Sage runs in Facility and Documentation only; the Assembly tab answers 409 ("not
  migrated"). The Documentation gateway serves every document type.
- Captures: the Specification Sheet is shaded colour. The parts manual defaults to hidden-line line art; the
  operations manual and work instructions are line art only; the inspection sheet has no 3D capture.

## Decisions (defaults taken while the user was away; easy to change)

1. **One appearance per assembly**, stored on the server (`<root>/<assembly>.json`, root
   `INSPECTORPRO_ASSEMBLY_APPEARANCE_ROOT`, default `generated/assembly_appearances`). The same machine looks the
   same in the Assembly tab and in every document.
2. **Targets:** the whole machine, and parts by the Assembly viewer's part names (a library machine's bodies, a
   CAD assembly's part numbers). A part's finish wins over the whole machine's.
3. **Finishes from the same library as Facility**, with the same overrides (color, roughness, metalness,
   opacity). A brand colour is a library finish with a colour override. The Assembly viewer draws colour,
   roughness, metalness and transparency; a textured finish (wood, brushed metal) shows its colour and sheen
   without the texture in this first version (the viewer's loader carries no texture coordinates).
4. **The viewer:** an assigned finish replaces the neutral or source colour of the meshes it covers in both colour
   modes; selection highlights still show on top. While a finish is set, a soft room reflection is added so metal
   finishes do not render black.
5. **Capture:** the Specification Sheet's figure revision includes the appearance's revision (only when one is
   set, so existing captures stay valid). A changed appearance makes the picture stale; the export then queues
   the publish, which captures again. The page refreshes the appearance before every capture.
6. **Sage (Documentation, every document type):** `list_appearances` (read: the finishes, the assembly's part
   names, the current assignment) and `set_assembly_appearance` (applied on the server during the turn; the
   browser reloads it after the reply). Sage may choose finishes itself when asked to make a machine look better
   (painted body, steel, glass), and uses a colour the user names. Line-art figures do not show colour: Sage says
   so for the manuals and work instructions.
7. **Assembly tab:** the appearance shows there (same store). Changed 2026-10-25 at the user's word ("you can connect
   sage assembly to codex as well"): with the ChatGPT plan sign-in (where that tab answered "not migrated"), the
   Assembly tab's Sage runs on the same Codex runtime with `inspect_assembly`, the BOM and the two appearance tools
   only. Highlighting, hiding, exploding and motion stay on the old runtime and are not offered there yet.

## Phases

- **AP1 - store and routes.** `ai_inspector/assembly_knowledge/assembly_appearance.py` (validate against the
  library and the assembly's part names, revision). `GET /api/assembly-appearance/{asm}`,
  `PUT /api/assembly-appearance/{asm}` (whole document), `DELETE` (clear). Spec sheet figure revision. Tests.
- **AP2 - the viewer.** Load with the assembly; apply in `_applyAssemblyMeshBaseMaterial`; room reflection while
  set; refresh before a capture and after a Sage turn that changed it. Live check on :8491.
- **AP3 - Sage.** The two tools in the Documentation gateway, instructions, progress labels, the turn result flag.
  Tests.
- **AP4 - live test, then port.** Mori CL-200A: "make it look like a real machine: painted body, steel spindle
  cover, glass door" then export the spec sheet; a CAD assembly (MMLE-50D) by part numbers; clear. Port with the
  usual backup and byte check.

## Status

- 2026-10-25: plan written from the user's request; building in the test copy.
- 2026-10-25 AP1 (76a0e67): store, GET/PUT/DELETE routes, spec figure revision (only when a finish is set).
- 2026-10-25 AP2 (7d9ddaf): the viewer draws finishes. Live fixes: library colours are sRGB and this renderer
  writes sRGB, so they are converted to linear (black had come out mid-grey); the room reflection lit painted tops
  to pure white, so it now scales with metalness (0.15 + 0.85 x metalness).
- 2026-10-25 AP3 (240bb96, 7520ffa): the Documentation tools and the Assembly tab on Codex; Assembly turns needed
  the Codex turn identity in the page (chat_stream_runtime.js).
- 2026-10-25 AP4 live (Sage on Codex gpt-6.1-sol, :8491, 4 turns): Mori CL-200A in Documentation - Sage read the
  finishes and parts, set grey enamel / clear glass window / brushed-steel spindle cover / black controls, then
  exported; the queued publish found the workspace blank (it opens blank until Refresh) and captured nothing. Fixed
  (7d495e7): a queued publish loads the saved sheet first. The capture then came out as a flat side view: the spec
  sheet's automatic camera choice preferred any view that fills the frame more, so a boxy machine lost its
  isometric product view; the requested view is now kept whenever it fills the minimum. Then "Export the spec sheet
  PDF" published the isometric, finished picture. MMLE-50D in the Assembly tab: Sage set 40 part finishes (yellow
  frame, scissor arms and platform; black wheels on aluminium rims; steel hardware; black handle, motor and
  cylinder) after one refused write (a guessed part name), shown on all 206 meshes.
- Not done: textures (wood grain, brushed lines) in the Assembly viewer; colour in line-art documents.
