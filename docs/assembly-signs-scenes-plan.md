# Safety signs, logos and scenes on assemblies, placed by Sage in the Assembly tab

## Why

The user, 2026-10-25: "we need to give sage access to the scene and decal tools ... for decal so we can add specific
logos on the machine ... in the assembly 3d tab (basically all appearence tools in the facility layout tab should
also be possible in the 3d assembly tab) ... our agent can help us put some warning logo on some part of the
equipment directly like do not touch, fire hazard, pinch points and so on. that could useful for other
documentation and safety".

## What exists (read 2026-10-25)

- **Facility library** (`static/facility_library/`): 29 finishes, 7 scenes (Classic, Neutral room, Presentation
  light/dark, and three CC0 HDRIs: Soft studio, Machine shop, Warehouse), 34 ISO 7010 signs (public domain, from
  Wikimedia Commons, each with its own SVG, aspect ratio and a default width of 0.3 m). Among them: P010 Do not
  touch, W024 Crushing of hands (the pinch-point sign), W019 Crushing, W017 Hot surface, W012 Electricity, W001
  General warning, PPE mandatory signs, and fire-equipment signs. **There is no "fire hazard" sign** (ISO 7010
  W021 Flammable material) and no W018 Automatic start-up, which a robot cell needs.
- **Facility rendering** is three r184: equipment signs are `DecalGeometry` projections anchored in the
  placement's own coordinates; HDRI scenes use `HDRLoader`. Facility Sage can propose a scene; signs are UI only.
- **Assembly viewer** is three r128 (`three.min.js` only, no add-ons), with a minimal GLB loader. Finishes are
  drawn per mesh (`_assemblyFinishForMesh`); a hand-built room gives metal its reflections. Front = +Z, right = +X,
  top = +Y (the capture's view presets).
- **Assembly appearance store** (`assembly_appearance.py`): one JSON per assembly with the whole-machine finish and
  part finishes. Its revision is in the Specification Sheet figure revision, so a change makes the picture stale.
- **Part names Sage sees** are part numbers on a CAD assembly, but body IDs on a library machine: the ABB robot's 13
  parts are named "...IRB6650_320-125_m2000_rev2_01-12-1". Sage cannot tell the base from the wrist by name.
- **Documents:** the Specification Sheet figure is shaded colour on technical white. The parts manual, operations
  manual and work instructions use line art; the operations manual has safety sections.

## Decisions

Defaults I would take; the ones marked **(needs your answer)** change what gets built.

1. **Same store.** Signs, logos and the scene join the assembly's appearance JSON, with one revision. So the same
   machine shows the same signs in the Assembly tab and in every document, and a new sign makes the spec sheet
   picture stale.
2. **A sign is on a part.** It is stored in that part's own coordinates: point, surface normal, the sign's up
   direction, width in metres and rotation. It therefore follows the part when the view explodes or plays motion,
   for example a pinch-point sign on the robot's wrist.
3. **Sage places by part, side and spot.** Sage names a part, a side (front, back, left, right, top, bottom, in
   the viewer's axes) and optionally a spot on that side (0-1 across and up, centre by default).
   - The server finds the surface by casting a ray at the part's triangles in its GLB. It answers in the same
     turn with the point it found, or with "no surface of this part faces front there".
   - Sage can then retry, and never has to guess coordinates.
   - The sign keeps its library width unless asked, shrunk to fit the face it lands on.
4. **Sage sees where parts are.** The part list gains each part's centre and size in metres and its height in the
   machine (from the GLB bounds). From these Sage can reason "the highest, farthest part is the wrist". Sage says
   when it is inferring a part from its position.
5. **Logos.** The user imports a PNG or JPEG through the same importer as Facility wall decals (re-encoded,
   metadata removed, size caps). It is stored with the assembly's appearance. Sage places an imported logo exactly
   like a sign. A logo can also arrive as a chat attachment, if the chat's attachments reach Sage on Codex; I
   would check that in AD3.
6. **New signs (needs your answer).** Add the machine-safety signs a fire-hazard or robot request needs, checked
   for public-domain status like the first 34 and recorded in `decals.json`:
   - W021 Flammable material ("fire hazard");
   - W018 Automatic start-up;
   - W022 Sharp element;
   - W016 Toxic material;
   - W023 Corrosive substance;
   - W002 Explosive material;
   - P015 No reaching in.

   This downloads about eight small SVGs from Wikimedia Commons, so I need your OK first.
7. **Scenes.** A scene sets the Assembly view's light, reflections and background.
   - The spec sheet picture uses the scene's light and reflections, but keeps its white background.
   - The three HDRI scenes need r128's HDR loader, and the signs need its `DecalGeometry`. Both would be copied
     unmodified from the three@0.128.0 npm package (MIT), as was done for the 0.184 add-ons. That is a download
     from npm, which I would also do only after your OK.
   - Without it, the four non-HDRI scenes still work, and I would write the sign projection myself.
8. **Line-art documents.** Signs are left out of line-art figures at first: a hidden-line pass would draw only
   their outline.
   - Follow-up, if you want it: the operations manual's safety section lists the machine's signs, with the sign
     picture, its meaning, the part and where it is.
   - The sign record keeps what that needs (sign code, label, part, side), so this can be added later.
9. **Sage only, or also the panel (needs your answer).** The first build gives Sage the tools, and the user sees
   the result in the 3D view.
   - The Facility library panel in the Assembly tab (tree, thumbnails, drag a sign onto a part, Pick in 3D) is
     phase AD5, if you want it too.
   - Your words "all appearance tools ... should also be possible in the 3d assembly tab" may mean the panel as
     well.
10. **Signs are visual aids.** Sage says to check the site's rules and the current ISO 7010 edition before relying
    on them, as the Facility doc does.

## Phases

- **AD1 - store, bounds and placement.**
  - Extend `assembly_appearance.py` with `scene` and `signs`, validated against the library, the part names and
    the imported images.
  - Add part bounds from the GLB, and the ray-cast placement (numpy).
  - Routes: GET/PUT as today, plus `POST /api/assembly-appearance/{asm}/images` for logos.
  - Tests.
- **AD2 - the viewer.**
  - Scenes in the r128 viewer.
  - Signs as decals parented to their part's mesh, rasterised from the SVG (or the imported image) to a
    texture. Selection highlights never tint them.
  - Signs are hidden in line-art passes and drawn in the spec sheet capture.
  - Live check on :8491.
- **AD3 - Sage.**
  - `list_appearances` gains scenes, signs, imported images and part bounds.
  - New tools: `set_assembly_scene`, `place_assembly_signs` and `remove_assembly_signs`, in the Assembly tab and
    in Documentation.
  - Instructions (what each warning sign means, one sign per hazard, a sign faces where a person stands),
    progress labels, and the turn result flag so the page reloads.
  - Tests.
- **AD4 - live test, port, desktop.**
  - ABB IRB 6650: "put a crushing-of-hands warning on the wrist, a hot-surface sign on the axis-1 motor, Do not
    touch on the base, and use the Machine shop scene", then the spec sheet.
  - MMLE-50D: pinch-point signs on the scissor arms.
  - Port with the usual backup and byte check, restart the desktop and demo it.
- **AD5 - the Assembly tab library panel** (if chosen in decision 9).

## As built (2026-10-25)

What changed from the decisions above, and why:

- **Placement happens in the browser, not on the server (decisions 2 and 3).**
  - A sign is stored as part, side, spot (0-1 across and up), width and turn. The Assembly view finds the
    surface each time it draws, so a sign follows its part through explode and motion.
  - A sign dropped from the library pane also keeps an anchor: the mesh, point and normal in that mesh's own
    coordinates.
  - The view reports what it measured to `PUT /api/assembly-appearance/{asm}/geometry`. That is each part's
    centre and size (only when not exploded and not in motion), the bounds, and where each sign landed, with the
    width drawn.
  - Sage reads this in the same tools: `list_signs_and_scenes` "shown" and `drawnWidthMeters`. No numpy ray caster
    and no GLB parsing on the server.
- **Where a sign may go.** A spot must pass two checks:
  - **Fit.** A 5 x 5 grid of rays under the sign, then a sheared 9 x 9 grid where that passes (every ray at its own across and up position, so a thin rib cannot slip between them), lands on one smooth surface. Faces turn at most 45 degrees from
    the spot. Neighbouring rays differ by 30 degrees at most, so a chamfer or fold fails. The surface may fall
    away behind the sign's plane only as far as its tilt explains, and nothing may rise in front of it, so steps,
    rims, recesses and slots fail.
  - **Seen.** Rays from the sign's centre and corners toward the person on that side hit nothing, the part's own
    rims included.
  - The search tries rings of nearby spots; a spot that fails is moved to the middle of its surface and tried
    again (on a straight bar the middle of any chord is the centre line). The rays turn with the sign.
  - Then the sign is tried smaller, from 70% down to 3 cm. If nothing fits even then, it is not drawn and the view
    reports `no_fit` (2026-10-25: the MMLE-50D's 6.5 cm scissor arms had drawn a 15 cm sign half off a bar; now
    3.9 cm, whole). A sign dropped or picked on a spot keeps half size wrapped there when nothing fits, since the
    person chose the spot.
  - Where it fits, only faces of the measured surface take the sign: no copy on a wall seen through a slot.
- **Scenes in the r128 view.**
  - Lights map from the r184 library: ambient / pi, each directional at 0.5 x scene / 2.
  - The HDRI environment comes through r128's RGBELoader and PMREM. The background is the scene's colour, or the
    theme's.
  - No shadows in the Assembly view.
  - The spec sheet capture keeps its white background. Signs are drawn only in shaded figures, never in line art.
- **Library cache.** The facility library manifest is fetched with `?v=<library version>`, so a browser that
  cached the old manifest sees the new signs.
- **AD5 panel built** (`static/assembly_library_panel.js`):
  - The tree has "On this machine", Appearances, Scenes, Safety signs and Logos, with search and thumbnails.
  - Editors: a finish for the whole machine or the selected parts; "Use this scene" / "Back to Classic"; a sign or
    logo with part, side, width and turn; "Remove sign".
  - Import logo.
  - Drag onto the machine: a finish goes to the part under the pointer, a sign lands where it is dropped, and a
    scene applies to the whole machine.
  - "Pick on the machine" does the same with one click, or Esc to cancel. A click in the Assembly view orbits and
    never selects, and a library machine has no Parts list to tick. Parts ticked in the Parts list (SolidWorks
    assemblies) can also be chosen by name.

## Status

- 2026-10-25: plan written. Waiting for answers on decisions 6, 7 (downloads) and 9 (panel).
- 2026-10-25: the user answered "yes download both, and build the panel too".
  - Downloaded the 8 ISO 7010 signs and the r128 DecalGeometry.js + RGBELoader.js (9c172ff).
  - AD1 + AD3 committed in d9985eb.
  - AD2 + AD5 built and checked live on :8491 with the ABB IRB 6650 and the Mori lathe:
    - signs on the wrist, the axis-1 motor and the base;
    - a drag-and-drop placement;
    - the shaded Specification Sheet picture with a sign;
    - line art without signs.
  - One Sage turn on Codex in the Assembly tab (5 steps, 47 s) placed all three signs and the Machine shop scene
    directly. Sage said which parts it inferred from position.
  - Not done yet: the MMLE-50D pinch-point check, the port to the real repo and the desktop demo.
