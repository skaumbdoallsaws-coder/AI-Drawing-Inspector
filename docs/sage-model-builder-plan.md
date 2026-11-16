# Sage model builder: simple equipment models from a recipe (plan, revision 5)

Status: revision 5, written by Claude on 2026-11-16 at the user's request. Revision 2 (same day, user: "yes add both
to the plan"): photos and spec sheets as input in v1 (D16, MB5b), sizes from the layout and looks from public research
(D17), a user-described tier and a photo tier in the evaluation. Revision 3: Codex review 1 (AGREE WITH CHANGES, 26
findings) answered in section 13; revision 4: Codex review 2 (10 findings) answered in section 14; revision 5:
Codex review 3 (AGREE, 6 minor) and the MB0 findings in section 15. Sections 13-15 are binding and win over earlier
text they contradict. Decisions owner:
Claude, except the decisions in section 11, which are the user's (1-5 accepted 2026-11-16, 6 open). Builder:
Codex, phase by phase; Claude reviews, runs the tests outside the builder's sandbox, runs the browser and live
checks, and commits. Base: worktree Documents/InspectorPro-FloorPlan/model-builder, branch `sage-model-builder` at
567f22a (the real repo's HEAD on 2026-11-16, without the user's uncommitted work); the port into the real repo
happens with the user.

## 0. Why and what

On 2026-11-16 the user asked Claude to "build the baler, a gaylord and a pack station with printer" for a
shipping-room proposal, and later clip-on carrier tags for the parcel carts. The library had none of them. Claude
built them as our own models in Python outside the app (docs/sage-model-builder-reference/), installed them in the
local library by script, placed them through the app's save, then gave their parts library finishes. The user then
asked how this works and said:

- "exactly! I was thinking to equip sage in the app with this ability"
- "yeah write the plan for it. you did the work and it is very important that sage can replicate that work just as
  well as you. later when you sell the product it is with sage that our customers will interact with not you"

Goal: inside the app, Sage builds simple equipment models the library lacks, at the quality Claude reached, with the
app's own checks and review rules. User story: in a Facility Layout the user types "the library has no baler: build a
42 in vertical baler and put it in the BALER box with its back to the wall". Sage picks a real size and says why,
builds a draft from a recipe, looks at the picture and fixes its own mistakes, adds it to the library, places it when
asked, looks at it in the room, and offers finishes.

Not in scope: CAD or manufacturing parts (the SolidCraft route, Part C of the basic-shapes plan, or SOLIDWORKS);
sculpted or organic shapes (people, vehicles, plants: downloads through model import do that better); free-form code
(the sandbox idea; section 12 says how a sandbox could feed this builder later).

## 1. The method Sage must reproduce (what Claude did by hand)

This section is the source for the playbook (section 6), the lints (D9) and the evaluation rubric (section 9).

1. Pin the object down: what it is, its size class, how it is used and from which side, what sits on or in it, how it
   moves. Baler: 42 in vertical class, about 1.32 x 0.95 x 2.6 m, loaded through the upper front door, bale pulled
   forward onto a pallet, 1.5 m clear in front, own 230/460 V circuit. Gaylord: 1.2 x 1.0 x 0.9 m double-wall carton
   on a pallet, moved by pallet jack. Pack station: 72 x 36 in bench at 36 in work height, riser to 1.8 m, packer
   stands at the front.
2. Fix the frame: metres, y up, base on the floor, centred on x/z, front (operator side) toward +z.
3. Block out the main volumes at real size (body and chamber; bench, riser and shelves).
4. Add the 5 to 10 features a person recognises first, biggest first. Baler: mesh loading door (a pattern of bars),
   bale door with tie slots and a handwheel latch (a ring and spokes), control box with red and green buttons,
   cylinder housing on top, power pack at the back, DANGER and CARDBOARD ONLY labels. Pack station: monitor on the
   riser, thermal label printer with a label coming out, scale with a lit display and a box on it, scanner in its
   stand, tape gun, kraft paper roll under the front, flat box stock on the bottom shelf. Gaylord: strap bands,
   flattened cartons inside at random angles (about 60 % full, fixed seed, kept inside the walls), label.
5. Name every part by what it is ("baler doors", "bench top", "scale platform") and merge pieces with the same job
   into one part. This is what later let 15 part finishes go onto one pack station.
6. Materials: plausible colour, roughness and metalness per part. Printed panels for labels, screens and tags, drawn
   at the panel's exact aspect (1080 x 600 px for 360 x 200 mm), 0.5 mm proud of the surface (no flicker), lit for
   screens. Text only, no logos.
7. Look before installing: front, side, back and three-quarter pictures; fix what looks wrong.
8. Catalog entry: name, an existing category, search tags, and a description that states the size basis, the front,
   clearances, power, and that it is our own generic model.
9. Place it with the app's checks (Claude: on a copy of the store first, 0 errors), facing the right way (pack
   stations turned so packers stand on the aisle side), save, then look at it in the room and fix.
10. Finish pass: library appearances per part (blue powder-coat frames, maple tops, rubber feet); printed parts keep
    their print.

Gotchas Claude hit, each handled below:
- (a) The 3D view mirrors model x (model_axes.mirror_catalog_record). Text written normally still reads correctly in
  the app; this was checked in screenshots and must stay checked (MB7).
- (b) The server cached the catalog until a restart. Sage's registration path already binds live (import plan, MI2).
- (c) A placed asset's file can never change: a change is a new version (D12).
- (d) The carrier tag hangs on a cart and has no floor. Claude's workaround (geometry at rail height, catalog height
  from the floor) breaks the canonical contract; the right answer is one combined asset, cart plus tag (D8, D13).
- (e) The catalog category must be one that exists ("Signage" does not; "Material Handling" does).
- (f) The tags rendered darker in the room than in the preview (UPS brown read as nearly black): check printed colours
  in the scene, not only in the preview (playbook step 9, E3).
- (g) Random scatter needs a seed for repeatable output and clamping so pieces stay inside their container.
- (h) The cart's mesh panels are real wire geometry: a decal projects only onto the wires. Prints need a solid panel.

Can Sage match it? Claude's edge was general knowledge of equipment, a kit of shapes, a picture loop, and knowing the
app's conventions. Sage's model has comparable knowledge and already sees pictures; this plan supplies the kit
(D4-D8), encodes the conventions as builder rules and lints (D3, D9), and gives worked examples (the cookbook, D15).
Sage also has inputs Claude did not use that day: the layout's own measurements, public research, and the user's
photos and spec sheets (D16, D17). Building something with no reference model is the normal case, as it was for
Claude; the cookbook is a shortcut.
The honest risks are fine proportions and small details, long recipes under the 32 KiB MCP cap, and round-trip time;
the mitigations are the cookbook, `revise_model_draft` (small edits instead of resending), the focus picture and the
evaluation loop in section 9.

## 2. What exists (file:line in the working tree on 2026-11-16)

- Model import (built and ported 2026-11-09, docs/sage-model-import-plan.md): self-contained worker package
  ai_inspector/industrial_assets/model_import/ (stdlib, numpy, Pillow only; README.md). `recipe.py` RECIPE_SCHEMA with
  up to 8 added simple parts (box, cylinder, frustum, hollow vessel; simple_parts.py:11-68). `writer.write_glb`
  (writer.py:12) textured deterministic GLB. `preview.py` 2 x 2 contact sheet (front, side, back, three-quarter;
  VIEWS :17-18) with dimensions. `footprint.py` hull/box and explicit support surfaces. `identity.py`. `prepare.py`
  `build_draft` :31 and `execute_prepare` :71 (immutable draft folder: model.glb, draft.json, preview.png,
  thumbnail.webp, parts.jsonl, CREDITS.txt, manifest). Worker limits and cancellation: runner.py,
  prepare_runner.py.
- Store: ai_inspector/facility_layout/model_import_store.py (scope per tenant + site, admission, quotas, `prepare`
  :698, drafts :633-697, receipts :790-805, previews :611). Registration: host.py `register_imported_asset` :1036 ->
  authored_library.install_bundle (authored_library.py:342) -> live binding; `catalogVersion` refresh (host.py,
  model_import_store.py, static/facility_layout_workspace.js).
- Sage tools: ai_inspector/codex_runtime/model_import_tools.py (inspect_model_import, prepare_model_asset,
  register_model_asset; 32 KiB request cap :21, 48 KiB summary :20, pictures :22). Playbook: pilot.py
  EDIT_INSTRUCTIONS :54, model-import paragraph about :244-258, basic shapes about :153-160. Progress labels:
  progress.py :56-58.
- Basic shapes (BS0-BS4, committed 2026-11-04): shape_families.py FAMILIES :343 (17 parameterised families: columns,
  beams, joists, barriers, bollards, guard rail, cable tray, pipe run, sprinkler line, high-bay lights, roof deck,
  fascia, tank, bin, pallet stack, workbench), kernel primitives.py (Mesh.box/prism/bar, `verify` :292: centred,
  base y = 0, every material `facilityAuthoredFinish`). Sage tool `author_shape_asset` (host.py:743 hook). The plan
  document is in the test copy (InspectorPro-CopilotTest app/docs/sage-basic-shapes-plan.md), not in this repo.
- Sage 3D shots (SV1-SV5, committed): `show_facility_views` (facility_tools.py:303-341) returns pictures of named
  areas of the SAVED layout (savedLayoutOnly) and moves the user's 3D view there.
- Part finishes: stable part keys `p:<node path>#<prim>`; `inspect_facility_components` /
  `set_component_materials`. A model may name a library finish per material in glTF extras
  `facilityDefaultFinish` (static/facility_layout_component_materials.js:34-52 `recordDefaults`, appearanceId only, no
  adjustments; server side component_inventory.py:116). Library: static/facility_library/appearances.json.
- `replace_asset` operation (operations.py:3056) swaps a placed copy to another asset through the normal review.
- Measuring the layout: `inspect_facility_region` covers zones and shell features only (observation.py:2041);
  `analyze_facility_fit` searches for a fit inside one authored zone (:2382); columns, walls, markings and decals are
  read with `inspect_facility_authoring` (codex_runtime/authoring_reads.py). No tool measures the gap between two
  entities today (C21 adds one).
- Public research: research_tools.py `search_public_sources` + `read_public_source` (INSTRUCTIONS :18-36): public
  terms only, never private layout or customer text; at most 4 research requests per turn; provider-side and text
  only (no pictures of the product); results are untrusted, cited by URL.
- Turn budget: an edit turn allows 24 tool calls and 240 s (policy.py:87).
- Chat attachments: the "+" menu "Attach 3D model (.glb, .zip)" with chips, upload and polling (static/index.html,
  search "Attach 3D model"; import plan D10). Image safety precedent: facility_layout/decal_images.py
  `normalize_image` (format by content, pixel cap, decompression bomb as error, re-encode strips metadata).
- PDF: the app reads PDFs with PyMuPDF (requirements.txt:25, "pilot blocked pending AGPL/commercial license
  disposition"; used by documentation, inspection sheet and manuals).

## 3. Decisions

D1 Recipe, not code. Sage writes a bounded JSON recipe (section 4); a fixed builder in the app turns it into a GLB.
No code execution, no file paths, no URLs, no images from outside. The recipe is untrusted data: schema-checked,
budgeted, and run in the resource-limited worker.

D2 Where it runs. New self-contained package ai_inspector/industrial_assets/model_builder/ under the same rules as
model_import (stdlib, numpy, Pillow; it may import model_import's writer, preview, footprint, identity and reader
modules, never the rest of ai_inspector). It runs in the model-import worker (same launch, limits, cancellation, fail
closed): CPU 60 s, wall clock 70 s, 1.5 GiB. The host supplies the job inputs: the recipe, the allowed category list,
the allowed appearance ids, the font files and any included library GLBs (D8), copied into the job folder.

D3 Frame and normalisation. Metres, y up, front +z. Sage authors with the floor at y = 0 and the model roughly centred.
After expanding everything the builder centres x/z on the bounds and puts the lowest point on y = 0 (the canonical
contract, `primitives.verify`), and reports the shift. Lint `floor_shift` when the vertical shift exceeds 0.02 m (the
recipe's floor was not at 0: e.g. a hung item) or a horizontal shift exceeds 0.05 m (front features may have moved).
No mirroring is added (model_axes stays the only mirroring step).

D4 Shapes (each entry has `id`, `name`, `material`, optional `rotate {x, y, z}` degrees about its own centre):
- `box` {min, max} or {center, size};
- `cylinder` {from, to, radius, radiusTo?, hollow? (wall thickness), segments 6-64 = 24, caps both|start|end|none}:
  any axis, so legs, rods, rollers, pipes, cones and frustums;
- `tube` {path <= 64 points, radius, sides 6-24 = 12, bendRadius?, closed?}: handles, rails, hooks, hoses;
- `lathe` {profile <= 64 [r, y] points, center, axis x|y|z = y, segments 8-64 = 32, degrees <= 360}: rolls, drums,
  buckets, knobs, bowls;
- `torus` {center, axis, radius, tubeRadius, segments}: handwheels, hoops, reels;
- `sphere` {center, radii [rx, ry, rz], part whole|upper|lower}: knobs, domes, lamps;
- `extrude` {profile <= 64 [u, v] points (simple polygon), plane xy|zy|xz, at, depth}: brackets, ramps, chutes, lips;
- `panel` {center, size [w, h], facing +z|-z|+x|-x|+y, print (D7), back color?}: labels, screens, tags, signs.
Normals face outward (tests check signed volume); every closed shape is closed.

D5 Groups and patterns. `group` {entries, position, rotate} nests up to 3 levels (sub-assemblies such as the printer
or the scale, moved as one). Any entry or group may carry one pattern:
- `repeat` {count 2-200, step [dx, dy, dz]};
- `grid` {count [n1, n2], step1, step2} (<= 400 copies);
- `around` {count 2-120, axis, center, degrees = 360};
- `mirror` {plane x|z} (adds a mirrored copy across the parent's x = 0 or z = 0 plane; the builder fixes winding;
  a mirrored panel moves and flips its facing but its print is never mirrored, so text stays readable);
- `scatter` {count 1-60, seed, within {min, max}, turnY [lo, hi], tiltX [lo, hi], tiltZ [lo, hi]}: each copy is kept
  inside `within` by its bounds (gotcha g).
Entries with the same `name` merge into one node, so a name is one finishable part.

D6 Materials and library finishes. A `materials` table (<= 32) of {color, roughness, metalness, opacity 0.2-1,
lit 0-1 (emission, for screens and lamps), finish?}. `finish` = {appearanceId, color?, roughness?, metalness?}
writes `extras.facilityDefaultFinish` and new `extras.facilityDefaultFinishAdjustments`, so a built model comes with
the same library look Claude gave the parts afterwards (blue powder-coat frame in #174a7e, maple top). Small app
change in MB7: `recordDefaults` and component_inventory carry the adjustments; precedence is unchanged (a placement's
part override beats the model's default, which beats the placement's finish). The appearanceId must be in the
library (host-supplied list), else the recipe is refused. Every material gets `facilityAuthoredFinish` as the
canonical contract asks.

D7 Printed faces. `print` {background, items <= 24} on a panel. Each item's first key names its kind:
{text: "<= 60 chars, up to 3 lines with \n", box [u0, v0, u1, v1], color, weight regular|bold, align},
{rect: [u0, v0, u1, v1], fill?, stroke?, lineMm?, radiusMm?}, {line: [u0, v0, u1, v1], color, lineMm},
{circle: [u, v, r], fill?, stroke?}, {barcode: [u0, v0, u1, v1], seed} (decorative, not scannable),
{stripes: [u0, v0, u1, v1], colors [a, b], angleDegrees, widthMm} (hazard stripes). u and v are fractions of the
panel (r of its width), v from the top. Pixels: 2.5 px per mm, long side 64-1024 px, exact panel aspect (never
stretched). Text auto-fits its box. Font: one bundled open-licence sans family (regular and bold, OFL; licence file
beside it; sha256 pinned in MB0); never system fonts (identity must not depend on the machine). <= 8 printed panels,
<= 4 megapixels in total. The panel sits 0.5 mm off the surface it is placed on. Content policy: generic labels by
default ("CARDBOARD ONLY", "DANGER KEEP HANDS OUT"); a brand, carrier or company name only when the user asked for
it in this conversation (the carrier tags); never a logo or a copy of trade dress beyond a colour; no names or
pictures of people; safety signs are generic text, not certified ISO 7010 artwork (the library's sign decals cover
that).

D8 Composition. An entry {include: assetId, name, position, rotateY, recolor?}: a library model becomes a group in
the recipe (the gaylord's pallet; a roll cage with a carrier tag). The host resolves the asset in the catalog, checks
its revision, copies its GLB into the job folder and passes its attribution; the worker reads it with model_import's
reader (same checks). Its parts keep their materials and are renamed "<name>: <part name>". `recolor` (<= 16) =
[{select, material}] with the import recipe's selectors (part key, mesh, material, node), so the cage's top rail can
come brown in the model itself. At real size only (no scale).
<= 3 includes; their triangles count toward the budget. Licence: own, authored or CC0 models freely; exactly one CC BY
or CC BY-SA include, whose credit is carried into the new asset's `attribution` and CREDITS.txt; NC, ND, unknown or
other licences are refused with a message.

D9 Lints. Every draft returns deterministic warnings with part ids; Sage fixes them or tells the user why not:
`size_mismatch` (built size vs the recipe's stated `size`, beyond max(1 cm, 2 %)); `floor_shift` (D3);
`floating_part` (a part not within 3 mm of another part or the floor; bounding-box test, approximate); `front_check`
(a part listed in `front` whose centre is not on the +z side); `coplanar_overlap` (two parts of different materials
sharing a face plane within 0.3 mm over more than 1 cm2: flicker; boxes and panels only); `print_small_text` (text
cap height under 6 mm at real size); `print_clipped`; `generic_name` (part, box, cylinder, mesh, object, with or
without digits); `heavy` (over 20,000 triangles); `tiny_part` (under 2 mm in every direction); `fit_exceeded` (the
built size is larger than the recipe's `fitsWithin` in any direction).

D10 Pictures. Reuse the model-import contact sheet (four views, dimensions, floor grid) and add: a FRONT arrow on the
floor grid, a 1.75 m person outline beside the model in the side view (scale at a glance, for items over 0.5 m), and
`focus` (a part id or name): the four views cropped to that part plus a 10 cm margin (small details such as a printer
or a display). Printed panels render with their textures.

D11 Drafts, identity, registration. Same store and scope rules as model import, with a new record kind "build" (no
source upload; admission, quotas, cancellation, sweep and receipts as in the import plan's D4 and review 2/3).
Engine version "model-builder-1". `assetId = "asset-built-" + slug(name)[:40] + "-" + sha256(identity)[:24]`;
identity = canonical JSON of {engine, normalised recipe, included assetIds + revisions, output GLB sha256, catalog
semantics}. Draft ids stay `md-<24 hex>`. Registration uses `install_bundle` with the bundle folder
`generated/industrial_assets/authored/built/<assetId>/` = model.glb, thumbnail.webp, recipe.json, bundle.json and
CREDITS.txt when an include carries credit. Catalog entry: name, category (existing list), description (Sage's text
plus a builder sentence: "Generic illustrative model built by Sage; size: <basis>"), tags, dimensions, surfaces,
footprint, `source` {kind "authored-recipe", generator "model-builder-1", sizeBasis, triangles, recipeSha256,
derivedFrom?}, `attribution` only from an include. Live binding and the `catalogVersion` refresh as for imports.

D12 Editing and versions. `revise_model_draft` applies <= 40 small edits to a draft's recipe and builds a new draft:
{op "update", id, set {...}} | {op "add", entry, into? groupId, after? id} | {op "remove", id} | {op "top", set
{...}}. A registered asset never changes: editing it means `get_model_recipe {assetId}`, revise, register a new asset
(`derivedFrom` = the old id). Placed copies move to the new version only when the user asks, through `replace_asset`
and the normal review.

D13 Mounting in v1. Floor-standing items, and items on another item's support surface (existing surfaces and
attachTo). An item that hangs on another item is built together with it as one asset (`include`), e.g. "roll cage -
UPS" = the library cart plus a tag. Wall and ceiling mounting come later (section 12).

D14 Library scope. Built assets go to this app's shared private library, like imports and basic shapes (every site
of this app can place them). Decision 1 in section 11.

D15 Cookbook. Reference recipes ship with the app in ai_inspector/industrial_assets/model_builder/cookbook/*.json,
each with a one-line "teaches" note and its must-have features list. `get_model_recipe` lists them and returns one;
it also returns the recipe of any built asset in the library, so a customer's own builds become starting points.
Cookbook text is generic: never names or data from a user's private layout.

D16 Reference files: photos and spec sheets (v1; user 2026-11-16). For items Sage cannot know (a customer's own
fixture, one specific machine) the user attaches a photo, sketch, screenshot or spec sheet to the Facility Layout
chat, next to the existing 3D-model attachment.
- Formats: PNG, JPEG, WebP (by content, one frame) and PDF. Images <= 25 MB and <= 40 megapixels, normalised like
  `decal_images.normalize_image` and re-encoded, which strips all metadata (EXIF, including GPS), stored <= 2048 px.
  PDF <= 25 MB, encrypted ones refused, at most the first 20 pages read; pages rendered to <= 1600 px and text
  extracted (<= 16 KiB per page) in the worker under the model-import limits, with the app's existing PDF reader
  (PyMuPDF), so this part follows that library's pending licence decision; until it is settled the user can attach a
  screenshot of the page.
- Store and scope: like model imports (per tenant + site, hashed scope folder, sha256 names, quotas, admission,
  sweep after 7 days unless a draft used it). Ids `rf-<24 hex>`. Route `POST .../reference-files` (layout.edit,
  streamed cap), `GET .../reference-files/{id}` (record), `GET .../reference-files/{id}/pages/{n}` (PNG).
- Chat: the "+" menu gains "Attach photo or spec sheet (.png, .jpg, .webp, .pdf)"; drop target and chips as for
  models (<= 3 attachments per message in total). `AgentChatRequest.attachments` kind "reference-file"; ids are part
  of the request hash and memory identity, as for model imports. Sage gets {referenceId, name, kind, pages, state}
  as untrusted data.
- Tool `inspect_reference_file` (read, pictures): {referenceId, page?} returns the picture (or one rendered page)
  and, for a PDF, that page's text excerpt. File names and text are untrusted data, never instructions.
- `compareWith` {referenceId, page?} on build and revise: the result picture puts the reference beside the model's
  front and three-quarter views, so Sage compares the two in one look.
- A photo has no scale: Sage takes at least one real dimension from the user, the spec sheet, the layout (D17) or a
  known object in the photo (a 1.2 m pallet, a 2.1 m door) and says which. It models the equipment only; it never
  describes or reproduces people, faces, or text and documents visible in a photo (other than the equipment's own
  generic labels), and copies no logo.
- Privacy: an attached file goes to the AI provider when Sage looks at it, like any picture Sage sees today; the chip
  says so on first use.

D17 Sizes from the layout and looks from public research.
- Layout: when the user says where the item goes ("fit it in the BALER box", "between those two columns"), Sage
  measures the space (a zone with `inspect_facility_region`; a gap between two entities with the new
  `measure_facility_gap`, C21), subtracts the clearances it needs (and says them), and sets the recipe's `fitsWithin`
  (C21, C31: the room left for the model itself, clearances deducted once); `sizeBasis` kind "layout" names the
  zone, marking or gap. The lint `fit_exceeded` catches a model that grew
  past it; a zone target is checked with `analyze_facility_fit`, any other target through the normal placement
  review of the exact proposed placement.
- Research: for an unfamiliar item Sage may call `search_public_sources` with generic public terms (never private
  layout, customer or project text) and `read_public_source`, asking the reader for overall dimensions and the
  visible features (doors, controls, where the operator stands, how it is loaded). Research is text only: Sage
  builds a generic model from the described features, not a copy of a product's styling, and keeps a brand name off
  the model unless the user asked for it. `sizeBasis` kind "research" cites the URLs in its note (<= 160 chars) and
  the description says "size from public sources, unverified".
- Turn budget: research (<= 4), measuring, build, two revisions, registration and a placement proposal fit in the
  24 calls of one edit turn; the 240 s are the tighter limit. Builder tools report the time left and refuse to start
  a build without enough of it (C22); the draft is kept and the work continues next turn. E2 measures this.

## 4. The recipe (outline)

Top level: `name` (<= 80), `category` (existing catalog category), `description` (<= 300), `tags` (<= 8), `size`
{width, depth, height} (what Sage intends; checked by `size_mismatch`), `sizeBasis` {kind
user|layout|document|photo|research|typical, note <= 160}, `fitsWithin` {width, depth, height?, note} (optional,
D17), `references` (referenceIds used, <= 3, kept in the draft only), `front` (part names that must face +z,
optional), `materials`, `entries` (shapes, groups, includes; <= 160 top level, <= 400 in total), `surfaces` (as the
import recipe, <= 6), `footprint` hull|box (default hull).

Budgets: recipe JSON <= 24 KiB (the MCP request cap is 32 KiB); <= 3,000 primitives after patterns; <= 60,000
triangles (lint above 20,000); coordinates within +-15 m; no length under 0.5 mm; group depth 3.

Example (corrected in MB0, C43-C45): a roll cage with a tag, composed from the builder's own plain roll cage
(recipes/roll-cage-tag.template.json; MB3 fills in the include's id, revision, artifactSha256 and the top-rail key
from inspect_model_include). The library TR1631 cart cannot be included (454,586 triangles, C43); for it Sage builds
a standalone hung tag (recipes/carrier-tag-ups.json, C44).

```json
{"name": "Parcel roll cage - OUTBOUND tag", "category": "Material Handling",
 "description": "Mesh roll cage with a clip-on OUTBOUND placard on its front top rail, top rail to match.",
 "tags": ["roll cage", "parcel cart", "tag", "outbound"], "size": {"width": 1.10, "depth": 0.662, "height": 1.00},
 "sizeBasis": {"kind": "typical", "note": "the builder's plain roll cage plus a 360 x 200 mm tag"},
 "front": ["carrier tag"],
 "materials": {"tag": {"color": "#1f5f3a", "roughness": 0.45}, "clips": {"color": "#1c1e21", "roughness": 0.5}},
 "entries": [
  {"include": "$CAGE_ASSET_ID", "id": "cage", "name": "cage", "revision": "$CAGE_REVISION",
   "artifactSha256": "$CAGE_ARTIFACT_SHA256", "position": [0, 0, 0], "rotateY": 0,
   "recolor": [{"select": "$CAGE_TOP_RAIL_KEY", "material": "tag"}]},
  {"id": "tag", "name": "carrier tag", "shape": "panel", "material": "tag",
   "center": [0, 0.835, 0.3275], "size": [0.36, 0.20], "facing": "+z", "back": "#1f5f3a",
   "print": {"background": "#1f5f3a", "items": [
     {"rect": [0.024, 0.043, 0.976, 0.957], "stroke": "#ffffff", "lineMm": 4, "radiusMm": 9},
     {"text": "OUTBOUND", "box": [0.08, 0.20, 0.92, 0.80], "color": "#ffffff", "weight": "bold"}]}},
  {"id": "clips", "name": "tag clips", "shape": "box", "material": "clips",
   "center": [-0.12, 0.955, 0.331], "size": [0.032, 0.05, 0.012], "repeat": {"count": 2, "step": [0.24, 0, 0]}}],
 "footprint": "box"}
```

The `$...` values are placeholders the MB3 fixture generator fills in; a real recipe carries the values
inspect_model_include returned.

## 5. Sage tools

- `build_model_draft` (edit gateway, pictures; writes a draft only, changes neither the layout nor the library). In:
  a recipe, optional `compareWith` (D16). Out (<= 48 KiB): draftId, dimensions, triangles, shift, parts (id, name,
  triangles; first 64), materials, surfaces, footprint, lints, warnings, and the contact sheet.
- `revise_model_draft` (edit gateway, pictures). In: draftId, edits (D12), optional `focus`, optional `compareWith`.
  Out: as build, for the new draft.
- `inspect_reference_file` (read, pictures; D16). In: referenceId (none: this site's 20 newest), page. Out: name,
  kind, pages, the picture, and a PDF page's text excerpt.
- `get_model_recipe` (read). In: nothing (lists the cookbook: id, name, size, teaches; plus the 20 newest built
  assets), or cookbookId | assetId | draftId (returns that recipe, <= 24 KiB).
- `inspect_model_import` accepts builder draftIds and `focus` (paging parts, a second look) - no new inspect tool.
- `register_model_asset` accepts builder drafts (same output: assetId, revision, name, dimensions, credit, added).
- After registration, the existing tools: placement operations and review, `inspect_facility_components`,
  `set_component_materials`, `show_facility_views`.
Progress labels for the new tools; every pinned tool list updated (the import plan's MI3 list plus the basic-shapes
tests).

## 6. Playbook (EDIT_INSTRUCTIONS paragraph; keep it this short)

When the library lacks an item (search_industrial_assets first) and no basic-shape family fits, build it:
1. Pin it down: what it is, its size class, how it is used and from which side, what sits on or in it, how it moves.
   Size, best first: the user's numbers, an attached spec sheet, the space it must fit in the layout (measure it,
   minus clearances: fitsWithin), public research, a typical size for its class; say which (sizeBasis). Look at
   attached photos or spec sheets with inspect_reference_file; a photo needs one real dimension for scale. For an
   unfamiliar item, research public sources with generic terms only (never the user's layout or company text) and
   ask for overall size and visible features. Ask the user only when the kind of item itself is unclear.
2. Call get_model_recipe; when a cookbook or library recipe is close, adapt it. Otherwise build from scratch with
   steps 3-5: the cookbook is a shortcut, not a requirement.
3. Metres, y up, floor at y = 0, centred, front (operator side) +z. State size and the front parts.
4. Block out the main volumes at real size, then add the 5-10 features a person recognises first, biggest first.
   Groups for sub-assemblies; patterns for bars, slats, shelves, holes; scatter with a seed for loose contents.
5. Name every part by what it is; the same name makes one finishable part. Never part1 or box2.
6. Plausible materials; library finishes for wood, steel, paint, rubber, cardboard. Printed panels for labels and
   screens: text only; brand or company names only when the user asked; never logos.
7. build_model_draft (compareWith the photo when there is one), then look: recognisable? like the photo? right size
   next to the person? front toward the arrow? nothing floating, flickering or clipped? Read every lint. Fix with
   revise_model_draft (focus on small parts) in at most two more rounds; then say what is still rough. If a tool
   says the turn is running out (turn_budget_low), stop, say the draft is ready, and continue next turn.
8. register_model_asset. Tell the user the name, size and its basis, the main features, and that it is a generic
   illustrative model. Something that hangs on another item is built together with it (include).
9. Place only when asked, with the normal placement tools and review (a zone target: analyze_facility_fit first).
   Placements save only after the user applies them, so look in the room in the NEXT turn with show_facility_views
   and fix your own mistakes (orientation, clashes, colours that read wrong in the room); a shot taken before the
   placement was saved proves nothing.
10. To change a registered model, revise its recipe into a new version; replace placed copies only when asked.

## 7. Cookbook v1 (written by Claude in MB6; must-have features in brackets)

1. Vertical baler 42 in [tall body, mesh loading door, bale door with handwheel, controls with two buttons, warning
   label] - bars pattern, torus, printed labels.
2. Gaylord on a pallet [double-wall box, pallet, straps, loose cartons inside, label] - include, scatter.
3. Pack station with label printer, scale, scanner, monitor [bench, riser, monitor screen, printer with label, scale
   with display, scanner, boxes] - groups, lit screen print.
4. Floor sign on a post ("RECEIVING") [base plate, post, double-sided sign] - panel prints, cylinder.
5. Roll cage with carrier tag [cage, tag, clips] - include, the D13 answer to gotcha d.
6. Workbench with pegboard and vise [top, frame, pegboard with hole pattern, vise] - grid pattern, extrude.
7. Flammable storage cabinet 45 gal [yellow body, two doors, handle, FLAMMABLE label, legs] - prints, tube handle.
8. Two drums on a spill pallet [pallet tray, grating, drums with rolling hoops, bungs] - lathe, grid, around.
9. Eyewash station [pedestal, bowl, push flag, sign] - lathe, tube, print.
10. Dock bumper [rubber block, steel frame, bolts] - extrude, repeat.
Items 1-3 are converted from the reference scripts (bounds within 1 cm, same part names); 4-10 are new. The
evaluation's tier-2 items (section 9) are deliberately not in the cookbook.

## 8. Phases (each ends with a commit by Claude after review; the builder never commits)

MB0 (Claude) Codex plan review rounds until AGREE; refresh section 2 on the current HEAD; baseline test run; choose
the font (OFL, regular + bold, licence file, sha256); write the four reference recipes (cookbook 1-3, 5) against
this schema as acceptance fixtures; the reference scripts are already in docs/sage-model-builder-reference/.

MB1 Kernel: schema and normaliser (dependency-free like recipe.py), shapes (D4), groups and patterns (D5), materials
table without prints (D6), merge by name, normalisation and shift (D3), budgets, output through model_import's
writer, `primitives.verify` on every output. Tests: per shape bounds, outward normals (signed volume), closed meshes,
triangle counts, determinism (same recipe -> same bytes, twice and across processes), every budget and every schema
refusal, mirror winding, scatter clamping and seed stability.

MB2 Prints (D7): Pillow renderer with the bundled font, item types, auto-fit, exact aspect, lit panels, 0.5 mm
offset, mirror rule. Tests on pixel properties (text present in its box, colours, size, aspect), not golden hashes.

MB3 Composition (D8): host side (catalog lookup, revision, copy into the job, attribution) and worker side (reader,
rename, budget), licence rules. Tests: pallet include, CC BY credit carried, NC/ND/unknown refused, revision mismatch
refused, budget counted.

MB4 Drafts, pictures, lints, registration: store record kind "build" (admission, quotas, cancellation, sweep,
receipts), preview additions (D10), lints (D9) each with a positive and a negative fixture, identity (D11), bundle
with recipe.json, `register_model_asset` path, live binding and `catalogVersion`. Tests as the import plan's MI2:
live binding without restart and after a restart, same draft -> same id and added false, identity conflict refused,
scope and permission at every boundary, cancellation leaves no draft.

MB5 Sage tools and playbook (sections 5 and 6), progress labels, pinned lists, real-host tests: build -> revise ->
register -> placement proposal through the existing operation -> restart; get_model_recipe on cookbook, asset and
draft; request and result byte limits; pictures.

MB5b Reference files (D16) and layout fit (D17), backend: reference-file store, routes, image normaliser, PDF page
rendering and text in the worker, `inspect_reference_file`, `compareWith` pictures, `fitsWithin` and `fit_exceeded`,
attachment kind "reference-file" in `AgentChatRequest` (scope validation, request hash, memory identity, pilot message
data), playbook lines. Tests: formats by content (a PNG named .jpg, a GIF refused), metadata stripped (an EXIF GPS
fixture), pixel and page caps, an encrypted PDF refused, a hostile PDF times out in the worker and fails closed,
scope and permission, sweep, compareWith picture size cap, fit lint positive and negative, attachments change the
request hash.

MB6 (Claude) Cookbook: the ten recipes, each checked in the app (picture and placed in a scratch layout).

MB7 Frontend: default-finish adjustments (D6) in recordDefaults and component_inventory, the asset card line "Built
by Sage - <size basis>", the "+" menu item "Attach photo or spec sheet" with drop target, chips, upload, polling and
the first-use provider note (D16), `?v=` bumps, ASCII only in static/index.html, LF. Node tests for the pure helpers
(chip state machine with mixed model and reference files). Claude's browser check on an isolated server (the import
plan's D12 harness): build -> register -> place -> part finishes -> printed text reads correctly in 3D (gotcha a) ->
show_facility_views; attach a photo -> build with compareWith.

Phase changes from review 1 (section 13): MB1 also builds the worker task, adapter and writer `generator` argument
(C1) and the frame contract fixtures (C10); MB3 includes the pinning, recolor keys and aggregate limits (C7-C9); MB4
uses the build record, identity and bundle kind (C2-C4), and takes over the default-finish consumers from MB7 (C5)
plus buildProvenance on the asset card; MB5 adds measure_facility_gap, turnRemaining and the gateway list (C21, C22,
C24) and replace_asset anchorInclude (C15); MB5b ships image intake with PDF behind the referencePdf capability (C18,
C19, C20); MB6 freezes the evaluation items (C26).

MB8 Verification and evaluation: the facility, codex and asset suites against the MB0 baseline; E1-E3 (section 9);
up to two playbook or cookbook fix rounds; then, with the user's OK, the port to the real repo (backup branch,
desktop restart) and a live run with the user.

## 9. Evaluation: how we know Sage matches Claude

E1 Parity (no Sage, deterministic): cookbook 1-3 rebuilt by the builder. Bounds within 1 cm of the hand-built
originals (baler 1.32 x 0.99 x 2.60 m, gaylord 1.208 x 1.008 x 1.032 m, pack station 1.83 x 0.91 x 1.87 m), the same
functional part names, triangles within 25 %, and Claude compares the contact sheets side by side with the library
originals. Cookbook 5 (cage + tag) is compared with the hand-placed cart and tag pair: tag size, height and centring
on the cage within 1 cm, text reading correctly in the 3D view. This proves the vocabulary covers what Claude did.

E2 Blind builds (live Sage, paid, decision 3): 18 items, each in a fresh conversation in a scratch layout (never a
user's private layout). Research is allowed in every tier; record each research call and its sources.
- Tier 1, adapt the cookbook: "a 60 in vertical baler"; "a pack station with two label printers and no monitor"; "a
  gaylord full of flattened cartons". Each run 3 times (consistency: at least 2 of 3 pass).
- Tier 2, new items not in the cookbook: a turntable pallet stretch wrapper; an 80 gal horizontal air compressor; a
  4 x 4 ft floor scale with its indicator on a post; a rolling warehouse ladder with 6 steps; a tote rack with blue
  bins.
- Tier 3, composition and the room: "put a UPS tag on that roll cage" (combined asset + replace on request); "add
  STATION 3 on the riser of that pack station" (revise + print + new version); "build two dock bumpers and place them
  either side of the dock door" (build + place + show_facility_views); "build a parts cabinet that fits the gap
  between those two columns" (size measured from the layout, fitsWithin, fit check before placing).
- Tier 4, described only in the user's words (things no public source knows): "our weld fixture: a 1.2 x 0.8 m steel
  table at 0.9 m, two toggle clamps on the top, a locating pin near one corner, a drawer on the right"; "the label
  applicator on our line: a grey box 0.6 x 0.4 x 0.5 m on a post, a label roll on the left side, a small touch screen
  on the front"; "our kitting cart: 1.2 m long, three sloped shelves with blue bins, a push handle on one end, four
  casters". R2 here = within 2 % of the stated sizes; R3 = every feature the user named.
- Tier 5, from an attached photo or spec sheet: the user supplies two photos of equipment in their own shop (one with
  a known object for scale, one with a dimension given in the chat) and Claude supplies one public spec-sheet page
  (screenshot or PDF). R1 here = recognisably the pictured item when the result is shown beside the photo.
Rubric per item (pass/fail): R1 recognisable (Claude and the user, separately, name the object from the contact
sheet alone); R2 size within the class range written down beforehand; R3 every must-have feature present; R4 front
correct; R5 no open lint without a reason; R6 parts named by function; R7 plausible materials (nothing glowing,
washed out or see-through by mistake); R8 <= 20,000 triangles and <= 3 build/revise rounds. An item passes with R1-R4
all true and at least three of R5-R8. Bar: at least 15 of 18 items pass, every tier-1 item passes, and at least 2 of
3 in tier 4 and in tier 5. Record per run: rounds, tool calls used of the 24, wall time against the 240 s, research
calls and sources, tokens or cost where recorded, pictures, and the final recipe.

E3 In the room: two runs where Sage builds, places, finishes and checks with show_facility_views in a scratch copy
of a test layout; Claude checks printed colours and text in the scene (gotchas a and f).

Failures go into the playbook, the cookbook or the lints (not into one-off prompt hints), then E2 is re-run for the
failed items.

## 10. Rules for the builder (Codex)

- Work only in this worktree and in temp folders. Never read `.env*`, `ui-data/`, `.runtime/`, or any auth, token,
  cookie or session file. No network, no installs (Claude supplies the font in MB0). Do not commit; Claude reviews
  and commits each phase. Leave a report per phase in docs/sage-model-builder-reports/<phase>.md (changed, tests
  run, not run, deviations, open questions).
- Never put names or data from the user's layouts into code, tests, fixtures or the cookbook; generic texts only.
- LF line endings; ASCII only in server.py and static/index.html (server.py keeps its BOM).
- Keep changes to the phase. Existing behaviour changes only where this plan says (record kind "build", builder
  drafts accepted by inspect and register, default-finish adjustments, asset card line).

## 11. Decisions for the user (all five ACCEPTED as recommended on 2026-11-16: "it's yes to everything")

1. Library scope: built models go to the shared private library like imports and basic shapes. Recommended: yes.
2. Text on prints: generic by default; brand, carrier or company names only when the user asks; never logos.
   Recommended: yes.
3. Paid live evaluation: about 20-25 Sage turns for E2 and E3 (12 prompts, tier 1 three times, up to 3 rounds each).
   Recommended: approve when MB7 passes. Update 2026-11-16: with the user-described and photo tiers and the
   layout-fit item the user added the same day, E2 has 18 items and needs about 30-40 Sage turns.
4. Order: build this before the Documentation sandbox pilot. Recommended: yes (smaller, no sandbox, reuses the
   import path, demonstrable).
5. A customer's built models become recipes Sage can start from (D15). Recommended: yes.
6. (OPEN, added in revision 3) PDF spec sheets need PyMuPDF, whose licence question (AGPL or a commercial licence;
   requirements.txt:25) is not settled. Until the user settles it, PDF intake stays off and photos and screenshots
   of spec sheets work (C18). Nothing to decide before MB5b.

## 12. Later (not v1)

- Sandbox: when it exists, a sandboxed script may produce a recipe (procedural shapes, data-driven layouts); the
  builder stays the only writer of models, so the same checks apply.
- Wall and ceiling mounting for built items; include-level part finishes; logos from user uploads with stated
  rights; clearance zones in the catalog (the baler's 1.5 m) feeding the spatial checker; levels of detail for big
  scenes; `compareWith` several photos at once; pictures from public research (it is text only today);
  precise parts through the SolidCraft route.

## 13. Codex review 1 (2026-11-16): findings -> binding changes

Codex reviewed revision 2 read-only (verdict AGREE WITH CHANGES, 26 findings, 2 blockers); Claude checked the claims
in the code (worker.py:76, prepare.py:34, identity.py:21, authored_library.py:258, observation.py:2041/:2382,
facility_tools.py:306/:338, three_adapter.js:7240, workspace.js:934, authoring_reads.py) and they hold. This section
is binding: where it contradicts an earlier section, this section wins. Numbers are Codex's finding numbers.

C1 Worker (1). model_import/worker.py gets a third task "build". The worker bootstraps model_import as the private
package `_model_import_worker` (as today) and model_builder as `_model_builder_worker` the same way; neither imports an
application parent. model_builder reaches model_import through the private package only. An adapter
(model_builder/adapt.py) builds model_import's Model, Part and ModelImage. `write_glb` gains a `generator` argument
(default = today's string; import output stays byte-identical, pinned by a test). Launch, limits, cancellation and
process containment reuse runner._launch. `primitives.verify` stays host-side (it imports the application): the
worker runs an equivalent canonical check of its own, and the host runs `primitives.verify` before installing.

C2 Store (2). Builds do not use prepare.build_draft / execute_prepare. A build job's input contract: recipe.json
(normalised), includes/<n>.glb (each with its pinned sha256), fonts/, allowed.json (categories, appearance ids), no
source file. Draft records gain `kind` "import" | "build"; lookup, leases, recovery, compaction and sweep are
kind-aware; build drafts are keyed by draftId alone (`md-<24 hex>`, no importId). `get_model_recipe {}` also lists
this site's unregistered build drafts (draftId, name, created, expires), so an interrupted turn can resume.

C3 Identity and install (3). New model_builder/identity.py: engine "model-builder-1"; identity = {engine, recipe
sha256 (portable recipe, C19), includes [{assetId, revision, representation, visualSha256}], output GLB sha256,
catalog semantics}; `assetId = asset-built-<slug>-<24 hex>`. install_bundle dispatches on bundle kind: "import"
(today's validator, unchanged) | "build" (asset-built id; folder generated/industrial_assets/authored/built/<id>/;
files model.glb, thumbnail.webp, recipe.json, bundle.json, plus CREDITS.txt exactly when attribution exists; builder
provenance in bundle.json). register_model_asset dispatches on the draft kind; receipts accept asset-built ids.
Import identities, folders and validators do not change.

C4 Catalog field (4). The builder's provenance goes in a new field `buildProvenance` {generator, sizeBasis {kind,
note}, sources [<= 3 {url, title}], triangles, recipeSha256, derivedFrom?}, not in `source` (the workspace already
reads record.source as the original record). It is validated and carried through private_catalog's projection and
host binding, shown on the asset card, used by get_model_recipe, and is part of identity. "Existing category only" is
a builder rule (the host passes the categories currently in the catalog); private_asset_spec stays as it is. Tests:
live binding, reload, spatial consumers unaffected.

C5 Default finishes (5). The intermediate Material gains an optional validated `defaultFinish` {appearanceId, color?,
roughness?, metalness?}; bundled appearance ids only (static/facility_library/appearances.json), never layout-local
custom finishes. The writer emits extras.facilityDefaultFinish plus facilityDefaultFinishAdjustments; the reader keeps
both (materials.py) so includes keep them. recordDefaults and component_inventory flatten the adjustments into the
existing finish resolver inputs. Precedence stays: part override > model default > placement finish > own material.
Tests: precedence, reset, finish groups, invalid values, included defaults. This frontend/consumer work moves from MB7
into MB4, before the cookbook is judged.

C6 Prints (6). Print materials carry extras.facilityArtwork = true (whole-object finishes then leave labels and
screens alone, three_adapter.js:7240), a neutral white base colour factor (the texture carries the colour, so a brown
tag is not darkened twice), and lit panels use the print as emissiveTexture with emissiveFactor = lit (writer
extension). The reader keeps an emissive texture for includes. Previews show lit prints at full brightness (unlit),
a stated approximation. Test: a whole-object placement finish leaves prints unchanged.

C7 Includes (7). An include names {include, id, assetId, revision, position, rotateY, recolor?}; v1 uses the catalog
record's `artifact` GLB (representation "artifact"). The host pins revision and the visual sha256 when copying and the
worker checks the copied bytes. Transform order: the catalog `sourceToCanonical` first, then the recipe's rotateY and
position; no layout mirroring is applied to authored geometry. Included support surfaces are not inherited in v1:
the recipe declares its own `surfaces`; lint `include_surfaces_dropped` says so.

C8 Recolor selectors (8). `recolor` accepts the stable component keys `p:<node path>#<prim>` exactly as
inspect_facility_components reports them for that asset (same path encoding, resolved against the pinned include
GLB), and the import selectors. Selectors match before renaming; rules apply in order, the last match wins; a recolor
replaces the part's material and drops its default finish; recoloring a printed or textured part is refused. Tests:
duplicate node names (~ordinals), a key that does not resolve, overlapping rules.

C9 Aggregate limits and provenance (9). Checked before geometry is expanded (pattern copies x entry estimates):
includes <= 3, <= 8 MiB each and <= 16 MiB together; output <= 400 primitives, <= 64 materials, <= 60,000 triangles,
decoded textures <= 16 megapixels in total (prints <= 4). Trusted evidence of "own" is host-side catalog data only:
`buildProvenance`, or source.kind authored-primitive / basic shape, and no attribution. Attribution and licence
restrictions travel transitively: a built asset that includes a CC BY model carries that credit; NC, ND or unknown
anywhere in the chain is refused; at most one attributed include in the whole chain in v1.

C10 Frame contract (10). Entry `rotate {x, y, z}`: R = Rz * Ry * Rx (x first), about the shape's own bounding-box
centre before rotation. Group: child coordinates are in the group frame; world = T(position) * R(rotate) * child.
Patterns act in the parent frame after the entry's own transform; copy i = pattern_i * entry. Mirror reflects
positions and normals and fixes winding; a panel's facing changes only when its facing axis is the mirror axis
(a +z panel mirrored across x stays +z, on the other side); prints are never mirrored (UVs corrected). Normalisation
shifts support surfaces and lint locations by the same amount. v1 defers `bendRadius` (tube joints are plain mitres)
and partial lathes (360 only). Scatter whose copy cannot fit inside `within` is refused (scatter_bounds_too_small).
Fixtures: nested transforms, asymmetric text under mirror and rotation.

C11 Parts (11). One `name` = one glTF node. Same-named entries with the same material merge into one primitive;
different materials under one name are separate primitives of that node (each its own finishable key, labelled
"<name> (<material>)"). The draft keeps a map from entry ids and pattern copies to output part keys, so revisions,
focus and lints name what Sage wrote. Includes keep their own node names under the "<include name>: " prefix.

C12 Approximations (12). Straps: thin boxes. Carton sizes: scatter gains `sizeJitter` (0-0.3 per axis, seeded).
Pegboard holes and similar perforations are a print item `dots` {area, pitchMm, radiusMm, color}: visual only, no
real holes (v1 decision). The reference monitor screen is simplified to the 24-item limit. MB0 measures the four
reference recipes in the real serialised MCP request envelope before the limits are frozen.

C13 Schema (13). Every entry, group and include has an `id` ([a-z0-9-]{1,40}, unique). Material defaults: roughness
0.6, metalness 0, opacity 1, lit 0; color required. A print item is identified by exactly one discriminator key of
{text, rect, line, circle, barcode, stripes, dots}; zero or two is a refusal (canonical JSON sorts keys). A panel is
a 2 mm plate whose front face sits 0.5 mm behind `center`; the print quad is at `center`, facing out; the back face
takes `back` or the material colour. Research citations are metadata (`sizeBasis.sources`, https only, never
fetched by the builder), moved into buildProvenance by the normaliser; D1's "no URLs" means no fetch instructions.
The section 4 example is corrected in MB0 (ids, revision on the include) and validated in MB1.

C14 Editing (14). `revise_model_draft` starts from exactly one of {draftId} or {assetId, revision} (built assets
only; the host clones the installed recipe.json into a new draft input and sets derivedFrom). Edit ops: update
(shallow merge into one entry), unset [fields], add (into/after), remove, material {name, set|unset|remove}, top
{set|unset}. Unknown ids refuse the whole revision; the result is validated as a whole. Tests: edit after a restart,
after the draft expired (start from the asset).

C15 Replacement (15). Registration returns `includeFrames` (each include's pose in the new asset's canonical frame).
`replace_asset` gains an optional `anchorInclude` (include id): the server computes the new placement so the included
host stays exactly where the old placement was. Hosts with dependencies are refused (today's rule, kept in v1). Part
finishes of the old placement are carried over when their keys map into the include's prefixed keys (server-side,
reported); equipment decals are not carried, so Sage asks before proposing a replacement that would drop them. "Put a
tag on that cart" is a proposal through the normal review, never an unconditional swap.

C16 Lints (16). front_check tests facing only: panels in `front` must face +z after all transforms; other parts are
not location-tested. coplanar_overlap counts only same-direction faces (contact faces with opposite normals are
fine). floating_part runs on pre-merge components (entries and pattern copies), with a sweep so 3,000 components stay
fast, and reports at most 20 findings. Closed shapes are tested for edge-manifoldness and local winding as well as
signed volume. Every lint has a positive and a normal-model negative fixture and a performance test.

C17 Pictures (17). `focus` re-renders with a camera framed on the part (bounds + 10 cm), not a crop. Focus and
comparison pictures live in a per-draft view cache, outside identity and the bundle. After registration (when the
draft's model.glb is removed) focus renders reload the installed model read-only. compareWith: one 1536 x 768 image,
reference left (aspect kept, letterboxed), the model's front and three-quarter views right, <= 1.5 MB. Tool text says
previews approximate materials (no roughness or metalness).

C18 Reference intake (18). Image decoding and PDF parsing run in limited workers. Images: <= 25 MB, <= 40 MP, one
frame (animated GIF/WebP/PNG refused), EXIF orientation applied, then every metadata block dropped by re-encoding;
stored <= 2048 px. PDF: a capability `referencePdf` that is OFF until the user settles the PyMuPDF licence question
(decision 6); when on, PyMuPDF is found through the same trusted dependency root as numpy/Pillow, records the total
page count, reads at most the first 20 pages, renders <= 1600 px and <= 4 MB per page, text <= 16 KiB per page, job
output <= 40 MB. Tests: animated, malformed and truncated files, a missing dependency (clear "not available"), real
cancellation and containment.

C19 Retention and publication (19). The portable recipe (recipe.json, identity, bundle.json) never holds reference
ids, file names, extracted text or comparison images: the normaliser moves `references` into the draft's site-scoped
provenance record. A draft pins its references until it is registered, superseded, failed or expired; registration
writes a minimal site-scoped provenance entry (referenceId, kind, sha256, page) outside the shared library and
releases the pin; an unpinned reference follows the 7-day sweep. Site quota: <= 100 reference files and <= 200 MB
including normalised pages, temporary copies and comparison outputs; admission before upload and race-safe sweep as
for model imports.

C20 Attachments (20). server.py: a discriminated union `ModelImportChatAttachment | ReferenceFileChatAttachment` on
`kind`; chat_attachments.py resolves by kind; memory/policy.py normalises both shapes; the pilot message data names
both; static/facility_layout_chat_attachments.js emits both kinds and binds the second "+" menu item. Request hashes
are unchanged when there are no attachments (pinned test). Tests: mixed attachments, attachment-only turns, replay
conflicts, foreign and expired ids, streamed and non-streamed routes, retries, switching conversation or layout,
stale upload responses.

C21 Measuring (21). Zones and shell features: inspect_facility_region. Columns, walls, markings, decals, placements:
inspect_facility_authoring (authoring_reads.py). New read tool `measure_facility_gap` {from, to} (two named entities
of those kinds, or a zone edge): deterministic clear rectangle between them (width along the gap, depth across it,
orientation in the layout frame, height limit if any, the entities used). `fitsWithin` = {width, depth, height?,
orientation, clearances {front, back, sides}, basis measured | user | research}. analyze_facility_fit is used only
when the target is a zone; otherwise the exact proposed placement is validated through the normal placement review.
Research dimensions and clearance assumptions stay separate from measured geometry.

C22 Turn budget (22). Builder tools return `turnRemaining` {seconds, calls}. A build or revision is refused with
`turn_budget_low` (keeping the last draft) when fewer than the build timeout plus 30 s remain; Sage then tells the
user the draft is ready and continues next turn (drafts are listed by get_model_recipe). Registration is never
rushed. Tests: cancellation near publication; a registration that completed before a turn failed is reported next
turn.

C23 Room check in the next turn (23). Placement previews never save and commits land after the turn, so the in-room
look happens in the next turn: build -> register -> propose placement (review) -> the user applies -> next turn
show_facility_views. The playbook says so, and a shot of the earlier layout never counts as verification. E3
exercises the transition.

C24 Gateway integration (24). Host -> agent_runtime hooks for build, revise, get_model_recipe, inspect_reference_file,
measure_facility_gap; read dispatch (facility_tools READ_NAMES gets get_model_recipe, inspect_reference_file,
measure_facility_gap) and edit dispatch (assisted_tools: build, revise); cancellation membership with
model_import_tools.NAMES (facility_tools.py:123); bounded error details; picture flags (mcp_bridge.py:96/:115);
stale-binding checks. Pinned inventories updated: test_codex_readonly_pilot.py, test_codex_assisted_tools.py,
test_codex_floor_plan_tools.py, test_codex_mcp_pictures.py, test_sage_shape_tools.py, plus schema, transport and
real-host tests.

C25 MB0 inputs and gates (25). MB0 supplies: the reference GLBs' statistics (bounds, part names, triangles) from the
library copies; generic own include fixtures built by the builder itself (a plain pallet and a plain roll cage, so no
private library asset is needed in the worktree), plus a synthetic CC BY test GLB; a font available without a
download (MB0 looks for an OFL or CC0 font in the repo or the pinned dependencies, e.g. Pillow's bundled font; a
download needs the user's OK). Order: worker contract (MB1) before composition (MB3); finish consumers in MB4. Gates
per phase: import regression (byte-identical import output), crash recovery, quota and concurrency, malformed worker
output, nested budgets, transformed surfaces, and the browser/Electron check in MB7. Each phase report lists the
tests that ran and every skip; Claude runs the file-writing suites outside Codex's sandbox.

C26 Evaluation (26). Before any live run, MB6 freezes docs/sage-model-builder-eval/items.json: per item the size
range, the feature checklist, accepted part names, front criterion and the rater procedure (two raters, blind to the
run order). E1 maps part names with include prefixes. E2 = 18 items, 24 initial runs (tier 1 x 3, an item passes
with 2 of 3). Timeouts and refusals count as failures. Workflow gates (scope, immutability, correct replacement,
post-save verification) are mandatory and scored apart from model quality. Tier 2 is a holdout: never used to tune
the playbook or cookbook; after a fix round, 3 fresh holdout items are added.

Codex's questions, answered: (1) visual pegboard holes and a simplified screen are fine for v1 (C12); (2) part
finishes carry over where keys map, decals do not and Sage asks first, hosts with dependencies are refused (C15);
(3) references are kept only while pinned plus 7 days, a registered build keeps a minimal site-scoped provenance
entry, not the file (C19); (4) the PyMuPDF question is the user's (decision 6); until then PDF intake is off and
images and screenshots ship (C18).

## 14. Codex review 2 (2026-11-16): findings -> binding changes

Codex reviewed revision 3 (AGREE WITH CHANGES: 5 major, 5 minor; no blocker; the PDF-off decision clear; C4, C9-C10,
C12-C14, C16-C20, C24 and C26 accepted). This section is binding like section 13 and wins over earlier text.

C27 Builder-only modes in the shared reader and writer (R2-1). `write_glb(model, *, generator=..., grouped=False,
extended_materials=False)` and the reader's `extended_materials=False`: the defaults keep today's import behaviour and
bytes. Only the builder (and includes read for a build) turns them on: `grouped` writes one node per part name with
one primitive per material (C11); `extended_materials` keeps facilityDefaultFinish (+ adjustments), facilityArtwork,
facilityFinishGroup and emissive textures. Tests: full inspect/prepare round trips of an import with duplicate names,
default finishes and an emissive texture give byte-identical output to today; a builder round trip keeps every field;
the emitted material count is checked against C9's 64.

C28 Artwork and finish groups through includes (R2-2). Validated facilityArtwork and facilityFinishGroup survive
reader -> intermediate model -> writer in extended mode. An include's finish groups are namespaced
"<include id>:<group>" so two included groups stay independent. A print (front) material never carries a default
finish (the builder refuses `finish` on it); its backing plate may. Tests: a nested include then a placement finish
(prints unchanged); two included finish groups switched independently.

C29 Include entries and selector discovery (R2-3). An include entry is {include: <assetId>, id, name, revision,
artifactSha256, position, rotateY, recolor?} (`include` is the discriminator and the asset id; `name` is the part
prefix; no separate assetId field). New read tool `inspect_model_include {assetId}` reads the exact catalog
`artifact` bytes that composition will copy (not the overview GLB that inspect_facility_components defaults to) and
returns revision, artifactSha256, attribution, size and the part keys (p:<path>#<prim>, name, material, triangles).
recolor selectors come from this tool only; the host refuses a build whose artifactSha256 or revision no longer
match. Test: an asset whose overview and artifact hierarchies differ.

C30 anchorInclude authority (R2-4). The installed bundle.json persists `includes` [{includeId, assetId, revision,
artifactSha256, frame (yaw + translation of the include's canonical frame inside the built asset's canonical frame),
partMap {includeKey: outputKey}}], validated by the install_bundle "build" validator. replace_asset with
`anchorInclude` resolves this server-side from the installed, catalog-bound bundle during preview and apply (so it
works after a restart). It requires: the replaced placement's assetId, revision and current visual identity equal
the include's; the include is a single instance (includes carry no pattern or mirror in v1); no scale. Pose: both
assets go through the same canonical -> layout mapping (model_axes mirror of x, then the placement's yaw), so the new
placement pose = old pose * Mx * F^-1 * Mx, where F is the include frame; F is yaw-only, so the result stays yaw-only.
Part finishes move through partMap; unmapped keys are dropped and reported; two old keys onto one output key with
different finishes is a refusal. Tests: an asymmetric host, a rotated placement, a normalisation shift, a restart,
and a stale visual identity (refused).

C31 measure_facility_gap contract (R2-5). Input: from and to as typed references {kind column|interior_wall|
perimeter_wall|marking|placement|zone, id, edge? (+x|-x|+z|-z, required for walls and zones)}, plus either `depth`
(metres) or `region` (a zone id) when the two references do not bound the second direction. Output only what is
established: the clear width between the facing edges, the depth (from the overlap of the two references, the given
depth or the region), the rectangle's four corners in layout coordinates when fully determined, the layout revision
and the references used. Anything whose footprint intersects the rectangle (column, wall, placement, marking) is
listed and the gap is reported "not clear" (never silently shrunk). Unsupported kinds or a gap that is not a
rectangle are refused. fitsWithin is expressed in the gap frame (width along the measured separation, depth across)
and is the room left for the model itself: Sage deducts its clearances exactly once, and `clearances` records what
was deducted (D17's "subtracts the clearances" means exactly this).

C32 Legacy dispatch and pending builds (R2-6). Draft records and bundle manifests without `kind` are legacy imports
and are never rewritten; builds always write kind "build". A pending build gets a reservation/job id (`mbj-<24 hex>`)
before its content-derived draftId exists; publishing an identical draftId twice is idempotent, and cancelling one
job removes only its own job folder, never a published draft. Tests: existing drafts and bundles after the upgrade;
two simultaneous identical builds, one cancelled.

C33 Worker refusals (R2-7). A bounded builder error class with its own codes (schema_invalid, budget_exceeded,
include_mismatch, scatter_bounds_too_small, print_invalid, font_missing, ...) decoded by the host runner for the
"build" task only; the complexity diagnostic for builds uses the builder's 60,000-triangle limit. model_builder is
bootstrapped only for the build task. Isolated-process tests: a schema refusal, a 60,001-triangle refusal, and no
application-parent module in sys.modules.

C34 turnRemaining and recovery (R2-8). The gateway (deadline and call count, facility_tools.py:82/:122) appends
turnRemaining to every builder response, success or refusal, outside summaries and identities. get_model_recipe {}
lists the site's unregistered build drafts and the builds registered in the last 24 hours (from durable receipts, so
also after a restart); the pilot's failure path reports registrations that completed before the failure, as the
success path does. A budget refusal before the first build says that no draft was built; "draft ready" only with a
retained draftId.

C35 Room check exception (R2-9). pilot.py's show_facility_views rule (only when asked, never unasked; :111/:117) gets
one exception: in the turn after the user applied (review mode) or after the turn that saved (direct mode) a
placement of a model Sage built in this conversation, Sage may call show_facility_views once, unasked, to check that
placement. Tests for both modes.

C36 MB0 hand-off (R2-10). MB0 supplies: the four reference recipes, the reference statistics
(docs/sage-model-builder-reference/baseline-stats.json, from the library copies), the font file with licence and
sha256, and the baseline test report. MB1 generates the kernel fixtures; MB3 generates the composition fixtures (a
plain pallet and a plain roll cage built by the builder, and the synthetic CC BY GLB). Synthetic composition tests are
kept apart from E1, which compares against the real reference assets' statistics and pictures.

MB0 facts (Claude, 2026-11-16): the font is Aileron Regular, bundled in Pillow (ImageFont.load_default), CC0 1.0 per
Font Squirrel and Fontsource; MB0 extracts the bytes to model_builder/fonts/ with a licence note and sha256 so identity
does not depend on the Pillow version. Bold is the same font with a stroke (stroke_width = round(0.04 x size)), a v1
approximation. Reference statistics are in baseline-stats.json (baler 1.32 x 2.60 x 0.99 m, 1,084 triangles, 12
parts; gaylord 1.208 x 1.032 x 1.008 m, 558; pack station 1.83 x 1.87 x 0.91 m, 976, 15 parts; carrier tag 0.36 x
0.215 x 0.01 m, 38). The gaylord's pallet in the library is a user CAD-library model, so cookbook 2 includes the
builder's own plain pallet instead.

## 15. Codex review 3 and MB0 (2026-11-16): binding changes

Codex reviewed revision 4 (verdict AGREE: six minor findings, no further design round needed before MB1). C37-C42
fold those in; C43-C46 are MB0 findings by Claude from writing the reference recipes. Binding like sections 13-14.

C37 inspect_model_include paging (R3-1). Input {assetId, offset = 0, limit = 100 (<= 200), revision?,
artifactSha256?}; output adds total and nextOffset and stays under the 48 KiB summary cap. A page request that names
a revision or sha256 no longer current is refused (pages never mix two artifacts). The tool joins C24's gateway list
and pinned tool tests.

C38 Anchorable includes (R3-2). An include is anchorable only when its whole ancestor chain gives one unscaled,
unmirrored, yaw-only instance: an include inside a patterned group, or under any x or z rotation, still builds but
its includeFrames entry says `anchorable: false` and anchorInclude refuses it. Anchored replacement of a placement
with a non-yaw rotation (spatial.py:583) is refused. Tests: include in a repeated group; include in a tilted group.

C39 Which identity (R3-3). C30's "current visual identity" is the current catalog `artifact` sha256 compared with the
include's artifactSha256, never the displayed overview's hash. Old part-finish keys are resolved against the
representation they were recorded on (component_inventory's selected representation) before partMap; keys recorded
on an overview whose hierarchy differs from the artifact are dropped and reported. Test: overview and artifact
hashes differ.

C40 Gap obstruction (R3-4). Obstruction = positive-area intrusion into the rectangle's interior beyond 5 mm; contact
with the rectangle's boundary, including by the two defining references, is allowed. A supplied `depth` is centred
on the middle of the overlap of the two references along the second direction; when they do not overlap, `region`
is required (refused otherwise). Tests: a clear gap, boundary contact only, an intervening obstacle.

C41 Cancellation (R3-5; replaces MB4's "cancellation leaves no draft"). A build cancelled before publication leaves
no draft; after the atomic publication the complete draft remains and get_model_recipe {} lists it. Import
cancellation keeps today's behaviour (model_import_store.py:781). Tests: cancel on each side of publication; two
identical builds, one cancelled.

C42 Gaylord parity and tracked fixtures (R3-6). E1 scores the gaylord body (gaylord carton, inside, edge, flattened
cartons, label) against the reference body; the pallet is scored against its own frozen spec instead (1.2 x 1.0 x
0.132 m; 3 runners, 9 blocks, 3 stringer boards, 8 deck boards; part-name map: the reference's "User
Library-pallet ..." parts -> "pallet boards" / "pallet blocks"). The gaylord body's triangle allowance is +-35%, not
25%: the builder's straps and lips are closed boxes (D4) where the reference's were open-faced (MB1a: 410 vs 318).
JSON fixtures are tracked through narrow .gitignore exceptions (the repo ignores
*.json): `!ai_inspector/industrial_assets/model_builder/**/*.json`, `!docs/sage-model-builder-reference/**/*.json`,
`!tests/fixtures/model_builder/**/*.json`. MB0 is complete only with the recipes and the baseline report committed.

C43 Heavy library models cannot be included (MB0). The TR1631 cart in the library is a CAD export of 454,586
triangles and 37 MB (artifact sha256 b90ed94d...), far over C9 (<= 8 MiB, <= 60,000 triangles), and has no
attribution. So section 4's example is corrected to compose the builder's own plain roll cage
(recipes/roll-cage-tag.template.json; MB3 fills in the include's id, revision, artifactSha256 and the top-rail key
from inspect_model_include), and cookbook item 5 uses that cage. For a heavy library cart Sage does what Claude did by
hand: it builds a standalone hung tag (C44) and proposes it in front of the cart; anchorInclude is for light
includes only. The refusal message for an over-limit include says this.

C44 Hung models (MB0; amends D3 and D13). Top-level `hangHeight` (0-3 m, optional, default 0): the builder puts the
model's lowest point at y = hangHeight instead of 0 (x/z centring unchanged), `floor_shift` is measured against it,
`size.height` is the model's own height, the catalog height runs from the floor (hangHeight + height) and the clash
volume is the floor-to-top column in front of the host, exactly as the hand-built carrier tags (cart_tags.py: placard
0.635-0.85 m, catalog height 0.85). primitives.verify gains `base_height` (default 0, today's behaviour); the host
passes the recipe's hangHeight for builds. buildProvenance records hangHeight. Tests: verify with base_height, a
hung tag registered and placed (catalog height from the floor), a hung model with hangHeight 0 equals today.

C45 Schema details fixed by the reference recipes (MB0).
- Entry kinds are told apart by exactly one key: `shape` | `group` | `include`. A group is {id, group: [child
  entries], position = [0, 0, 0], rotate?, one pattern?}; its value is the child list.
- `around` {count, axis, center, degrees = 360}: degrees = 360 spaces copies by 360 / count; less than 360 spaces
  them by degrees / (count - 1) (both ends included). Copy 0 is the entry itself.
- `scatter.sizeJitter` [jx, jy, jz] (0-0.3 each) sits inside scatter; each copy's size is size * (1 + u * j) with u
  uniform in [-1, 1] from the seed.
- `surfaces` use the import recipe's form {id, label, height, rect [x0, z0, x1, z1]} in the recipe frame and move
  with the normalisation shift (C10).
- Panels: C13 governs (plate 2 mm, front 0.5 mm behind `center`), so a panel's centre goes 2.5 mm in front of the
  face it sits on (D7's "0.5 mm off the surface" is superseded). A standalone panel (the tag) needs no backing face.
- `coplanar_overlap` counts only faces that face the same way (a plate back-to-back on a wall does not flicker).
- Text items take `align` left|center|right (default center).

C46 MB0 measurements (2026-11-16). Reference recipes in docs/sage-model-builder-reference/recipes/: baler, gaylord on
pallet, pack station, carrier tag (UPS, hung) = the four E1 references; pallet-plain and roll-cage-plain = MB3
composition inputs; roll-cage-tag.template = the composed example. Sizes in the real MCP tools/call envelope
(recipes-envelope.json): largest 10,461 bytes (pack station: 43 entries, 15 materials, 25 print items on 2 panels),
then baler 5,903; all far under the 24 KiB recipe cap and mcp_bridge's 32,768-byte request cap, so section 4's
limits stand. Font: model_builder/fonts/Aileron-Regular-subset.ttf, 12,676 bytes, sha256 69853909b9400235...
(fonts.json holds the full hash). It covers printable ASCII, curly quotes and a few signs (degree, plus-minus,
copyright) but no accented letters, en or em dashes or the euro sign, so v1 refuses print text outside the
covered set (print_invalid names the characters). A fuller font (the full CC0 Aileron) needs a download: an
open point for the user, not needed for MB1-MB5. Baseline test report:
docs/sage-model-builder-reference/baseline-tests.txt.
