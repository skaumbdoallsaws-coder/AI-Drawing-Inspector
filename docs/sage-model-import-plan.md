# Sage model import: downloaded 3D models into the facility library (plan, revision 3)

Status: revision 3 after Codex plan reviews 1 (AGREE WITH CHANGES, 2 blockers + 15 major) and 2 (AGREE WITH
CHANGES, 10 of 17 resolved, 7 major + 2 minor follow-ups); section 8 maps review 1, section 9 maps review 2. Decisions owner: Claude (the user: "you have the authority on
this implementation"). Builder: Codex, phase by phase; Claude reviews, runs the tests outside the builder's sandbox,
runs the browser checks, and commits. Base: real repo `ui-bridge-telemetry-unified-2026-05-18` at 396bc9e, worktree
branch `sage-model-import`.

## 0. Why and what

On 2026-11-08 the user's gym kitchenette was made over with Sketchfab downloads that Claude adapted by script outside
the app (docs/sage-model-import-reference/): read the GLB, rename parts, replace or fix materials (a printed slogan, a
picture label, a glow, pale alpha-blended leaves), shrink textures, scale to a real size, re-centre on the base, join
copies (three mugs, two basil pots) or join a download with our own parts (an olive tree in a terracotta pot), then a
catalog entry with support surfaces, a footprint and the CC BY credit. Sage then placed them.

The user: "this skill need to be part of sage's app arsenal ... provide sage with the tools necessary to do that also
when the user just loads a download part in the chat pan in the frontend".

User story: in a Facility Layout the user drops `fruit-bowl.glb` (or Sketchfab's `.zip`) on Sage's chat and types
"make this a fruit bowl for the island". Sage reads what the app found (parts, size, licence) and looks at the
picture, prepares a library asset (orientation, real size, part names, materials, textures, copies, simple extra
parts, surfaces, footprint), looks at the result picture and fixes its own mistakes, adds it to the library with its
credit, says what it did, and places it when asked, with the existing placement tools and review rules.

## 1. What exists (file:line at 396bc9e)

- Chat pane: no attachments. Composer and the placeholder "+" `agentCameraBtn`: static/index.html:21473-21480,
  85185-85188. `updateSendButtonState` :85021 and `handleAgentSend` :94549-94584 (payload :94670, frozen :94728)
  know text and the screenshot only. `AgentChatRequest` server.py:22525-22542; facility dispatch :41531-41540.
  A facility Codex turn sends text only (codex_runtime/pilot.py:445-455, app_server.py:379-380); pilot hashes
  message/document/effort (pilot.py:422-423); server memory identity server.py:44994-45004 via
  memory/turn_lifecycle.py:149-201. Codex cannot read files (policy.py:25,126). MCP request bodies <= 32768 bytes
  (mcp_bridge.py:125), tool results <= 64 KB (facility_tools.py:157), tool timeout 90 s (policy.py:134). Pictures
  reach Sage only as `gateway.last_image` from tools declaring `"pictures": True` (mcp_bridge.py:92-120).
- Upload precedent: floor-plan import (floor_plan_imports.py:32-75 route, layout.edit at :43-46;
  floor_plan_store.py: 25 MB streamed cap :46,:153-158, `clean_source_name` :108-114, atomic writes :117-128,
  sha256 names, per-user parse queue :174-230, stale sweep :279). Sage sees only an importId
  (floor_plan_tools.py:1-4).
- Worker precedent: packaging `glb_worker.py` + `sources.py:80-130`: `-I -S -B` interpreter, scrubbed environment
  (HOME/TMP/APPDATA... = the job folder, PATH = python dir + System32, thread counts 1), cwd = job folder, no
  stdin/stdout/stderr, CREATE_NO_WINDOW, 25 s wall clock then kill + wait, exit codes 3 (dependency missing) and 4
  (limits could not be set: never parse without limits). `limit_resources` (glb_worker.py:64-110): Windows Job Object
  (CPU time, one process, process memory, kill on close); POSIX RLIMIT_CPU and core only. The dependency root is
  host-supplied (`glb_runtime()`, sources.py:43-67), never from upload data. This is a resource boundary, NOT a
  filesystem or network sandbox.
- Image safety precedent: decal_images.py:19-50,86-105 (format allow-list, frame and pixel count checked before
  decode, decompression-bomb warning as error, re-encode strips metadata).
- Live catalog: `register_authored_asset` (host.py:1166-1207) -> `authored_library.install` (:190-225; already
  accepts any descendant folder of `generated/industrial_assets/authored` and creates it, :198-212; CatalogLock,
  10 backups, `replace_file(unchanged=...)`; an existing id is treated as success without comparing content,
  :207-215) -> `build_private_local_asset_catalog` (finds a sibling `thumbnail.webp`, host.py:703-710) -> new
  `_catalog`/`_asset_versions` dicts under `_authoring_lock`. Wired into the agent runtime as `author_shape`
  (host.py:954). Needs `INSPECTORPRO_FACILITY_PRIVATE_ASSETS`. Asset resolution and `/generated` serving are not
  site-scoped (host.py:1089-1117, server.py:47548): the private library is shared by every site of this app.
- Binding validation `_private_manifest_specs` (host.py:378-621) never reads `source` (:607-620). Revision = sha256
  of the canonical definition before visual paths are attached (host.py:148-156,671-676). `authoring_reads.
  read_authoring` projects fields without attribution (:92-100); frontend `normalizeCatalog`
  (facility_layout_workspace.js:976-1014) and `Workspace._assetCard` project fields too.
  `Workspace._refreshAssetCatalogFor` refetches only for unknown placed assets (:18449-18460).
- GLB: artifacts.py `inspect_glb` (default limit 30 MiB :35; external URIs refused :494-516; sparse :578; skins,
  animations, morph targets :751-785; index accessor metadata checked, not index values, :676-709; does not check
  `extensionsRequired`; does not validate embedded texture sizes; the 2048 px constant belongs to
  `normalize_web_image` :1307). `primitives.verify` (:292-318): whole-model bounds centred on x/z, base y = 0,
  declared size, `extras.facilityAuthoredFinish` on every material (a textured material marked so keeps its texture:
  facility_layout_three_adapter.js:7245,7370). One mirroring step exists, `model_axes.mirror_catalog_record`
  (model_axes.py:120-125): imports must not add another. MAX_TRIANGLES 250k (shape_families.py:27).
- Pictures: `shape_preview._rasterize` (:73-95) is a numpy depth-buffer rasterizer with a Python loop per triangle
  (flat colour). tools/render_industrial_asset_thumbnail.py is a headless Three.js renderer (browser process; not
  used here).
- Sage tools: read specs facility_tools.tool_specs (:32-56) + `FacilityReadGateway._read_data` (:425-564); edit tools
  `FacilityEditGateway` (assisted_tools.py:47-58, dispatch :89-130, `_shapes` :165-203), active with
  `INSPECTORPRO_CODEX_EDIT_PREVIEWS=1`; gateways get `host.agent_runtime`, not the host (pilot.py:395-397).
  `enabled_tools` must equal the MCP list (pilot.py:441, app_server.py:369-374). Playbook strings pilot.py
  `INSTRUCTIONS` :20-50, `EDIT_INSTRUCTIONS` :52-272. Progress labels progress.py `SIMPLE` and `_step`.
  Pinned tool lists: tests/test_sage_shape_tools.py, test_codex_mcp_pictures.py, test_codex_assisted_tools.py,
  test_codex_readonly_pilot.py, test_codex_floor_plan_tools.py.
- Reference implementation: docs/sage-model-import-reference/ (glbsrc.py reader/writer, geom.py builder,
  kitchen_models.py recipes, kitchen_install_part.py catalog entry). It shows intent, not code to copy: its reader
  trusts the file (review 1, finding 4).

## 2. Decisions

D1 Formats. `.glb`, or `.zip` holding exactly one model (one `.gltf` with its resources, or one `.glb`) plus optional
licence text (`license.txt`, `LICENSE*`, `README*`, `*.md`, `*.txt`; <= 64 KiB each, <= 8 files). Refused with a
helpful message: other formats (.fbx .obj .blend .usdz .stl .dae: "download the glTF or GLB version"), data: URIs (v1),
skins, morph targets, sparse accessors. Primitive modes 4 (triangles), 5 and 6 (strips and fans, converted); points
and lines dropped with a warning. The default scene (or scene 0) is used.
Extensions (exact policy):
- supported: `KHR_materials_emissive_strength` (multiplies emission), `KHR_texture_transform` on the base colour
  texture (applied to the UVs at read time), `KHR_materials_unlit` (read as a plain material),
  `KHR_materials_pbrSpecularGlossiness` (diffuse factor/texture read as the base colour; older Sketchfab exports),
  `KHR_mesh_quantization` (integer attributes converted by componentType honouring `accessor.normalized`:
  normalized ones scaled to [0,1] or [-1,1], unnormalized ones kept as their integer values, before node transforms).
- ignored with a warning when only in `extensionsUsed`: `KHR_materials_specular`, `_ior`, `_transmission`,
  `_volume`, `_clearcoat`, `_sheen`, `_iridescence`, `_anisotropy`, `_dispersion`, `KHR_lights_punctual`,
  `KHR_materials_variants`; any other unknown used-only extension is ignored with a warning too.
- refused when in `extensionsRequired` and not supported (Draco, meshopt, KTX2/basisu, WebP-only textures, any other).
A texture on a non-zero `texCoord` is dropped with a warning (the part keeps its base colour). Animations are dropped
(rest pose) with a warning.

D2 Budgets (enforced before allocation where possible, checked again after decoding):
- upload <= 128 MiB, streamed cap (real Sketchfab GLBs seen: 0.08-86 MB; the 2026-11-08 stool was 85.8 MB);
- zip: <= 512 entries, <= 512 MiB uncompressed in total, each entry's declared size checked and the real decompressed
  size capped while reading, ratio <= 200 per entry, methods stored/deflate only, encrypted entries refused;
- glTF JSON <= 16 MiB, <= 4096 nodes, node graph depth <= 64, no cycles, <= 4096 mesh primitives after instancing,
  <= 64 materials, <= 32 images;
- geometry: source <= 2,000,000 triangles and <= 3,000,000 vertices after instancing; output <= 250,000 triangles
  after copies and added parts (no decimation in v1: the error names the count and the five biggest parts so Sage can
  drop parts or tell the user);
- images: PNG/JPEG/WebP by magic bytes (not by name or mimeType), one frame only, <= 8192 px a side, <= 64 MP each,
  <= 256 MP in total; decoded one at a time and downsized at once (JPEG `draft` first) to the output size; output
  images re-encoded (PNG when the alpha is used, otherwise JPEG q85), metadata stripped, <= 2048 px (default 1024);
- output GLB <= 30 MiB (the `inspect_glb` default), preview PNG <= 1.5 MiB, thumbnail WebP <= 64 KiB;
- worker: 1.5 GiB process memory, CPU 60 s, wall clock 70 s, then killed and joined.

D3 Isolation (the real boundary, stated as it is). Untrusted bytes are parsed, decoded, transformed, rendered and
written only in a worker subprocess launched like the packaging worker: `-I -S -B`, a host-supplied dependency root
(numpy, Pillow; the same `glb_runtime()` binding), the model_import package directory appended explicitly (the
package imports nothing from the rest of ai_inspector), scrubbed environment, cwd = a fresh job folder holding only
the job's inputs, no stdio, hidden window, resource limits set before anything is read (Windows Job Object: CPU,
memory, one process, kill on close; POSIX: RLIMIT_CPU, RLIMIT_AS, RLIMIT_NOFILE, no core) and fail closed (exit 4)
when they cannot be set. It is not an OS filesystem or network sandbox: the worker code opens only the job folder
paths it is given and never opens a network connection, and tests pin that (a static test that the package imports
no socket/http/urllib modules, and a test that it reads only the job folder). The host kills and waits for the
worker on timeout or cancellation. The server process reads only the worker's JSON results (schema-validated,
size-capped) and its output files, and runs `primitives.verify` / `inspect_glb` (the existing hardened validator) on
the output GLB before registering it.

D4 Import store, per tenant + site (like floor plans, hashed scope folder):
`<facility root>/model-imports/<sha256(tenant\0site)>/sources/<sha256>.<glb|zip>`,
`imports/mi-<24 hex>.json` (record: schemaVersion, id, scope hash, clean display name, sha256, bytes, format,
created, createdBy, state queued|checking|ready|refused|failed, refusal code/message, summary, licence, warnings,
drafts and registrations made from it), `drafts/md-<24 hex>/` (model.glb, preview.png, thumbnail.webp, draft.json:
normalized recipe, engine version, source sha256, output sha256s, dimensions, triangles, surfaces, footprint,
attribution, changes). Drafts are immutable once written (temp folder, then rename). Every lookup (inspect, preview,
prepare, register) takes the principal and the bound tenant/site/layout and answers an id from another scope with the
same "not found". Admission before the body is read: <= 2 active jobs per user, <= 8 per app, <= 2 GiB of sources
per site. Sweep: drafts never registered after 7 days, refused/failed imports after 1 day, never while a job holds
the import (lock file per import). Filenames, README text, licence excerpts and part names are untrusted data
everywhere (bounded, cleaned for display, passed to Sage as JSON data, never as instructions).

D5 Library assets (deliberately shared). Registering publishes the asset to this app's shared private library, like
a basic shape: every site of this app can place it (the library is not site-scoped today). Only the import and its
drafts are site-scoped. Registration requires `layout.edit` on the bound layout and a draft of that tenant/site,
checked again at the registration boundary.
Bundle: `generated/industrial_assets/authored/imports/<assetId>/` = `model.glb`, `thumbnail.webp`, `CREDITS.txt`,
`bundle.json` (identity inputs and sha256 of each file). A new installer beside `install`:
`authored_library.install_bundle(root, entry, files)`:
1. validates the complete catalog entry with the same rules the binder applies (factor the per-entry checks of
   `_private_manifest_specs` into a function both use) and `primitives.verify` on the GLB, before touching anything;
2. under `LOCK` + `CatalogLock`: if the id is in the catalog, compares `bundle.json` and the files' sha256 with the
   new bundle: identical -> `added: false`; different -> `asset_identity_conflict` (never overwritten);
3. otherwise writes the bundle folder (temp folder + rename; an existing folder with the same bundle.json is reused,
   a different one is an error), then appends the catalog entry (backup + `replace_file`, as `install` does);
4. a failure after the folder is written leaves an orphan folder that the next attempt reuses; a catalog entry never
   points at a missing folder.
`install` and the basic shapes keep their behaviour. `LocalFacilityLayoutHost.register_imported_asset(principal,
site_id, layout_id, draft_id)` loads the frozen draft (never rebuilds it), builds the entry, calls `install_bundle`,
binds through `build_private_local_asset_catalog`, swaps the live dicts as `register_authored_asset` does, and records
the registration in the import record. Exposed to Sage as a new agent-runtime hook `register_model_import` next to
`author_shape` (host.py:954), with matching hooks for the store reads and prepare.

D6 Identity. `assetId = "asset-import-" + slug(name)[:40] + "-" + sha256(identity)[:24]`; identity = canonical JSON
(sorted keys, no whitespace) of {engine: MODEL_IMPORT_ENGINE_VERSION, source: source sha256, recipe: the normalized
recipe (defaults filled, numbers rounded to 1e-6, names cleaned), model: output GLB sha256, entry: the catalog
semantics without assetId and artifact (displayName, category, description, tags, dimensions, supportSurfaces,
footprintPolygons, attribution)}. Same draft -> same id; any change of recipe, engine, output bytes or semantics ->
a new id (a recipe change with identical output still gets a new id: simple and safe, the old asset stays). On reuse
the full bundle.json identity is compared, not only the id. The binder computes `assetDefinitionRevision` as today; a
registered asset's files and entry are never rewritten, so a placed revision and its bytes never change.

D7 Credit. New optional catalog field `attribution` = {title, author, authorUrl, sourceUrl, license, licenseUrl,
licenseClass (cc0|cc-by|cc-by-sa|cc-by-nc|cc-by-nd|cc-by-nc-sa|cc-by-nc-nd|other|unknown), changes, statedBy
(file|user)}: strings <= 300 chars (changes <= 600), URLs https only, no control characters. Validated in the shared
entry check, bound into the asset record by `build_private_local_asset_catalog`, projected by
`authoring_reads.read_authoring` (so `inspect_facility_asset` shows it), `normalizeCatalog` and `_assetCard` (a
"Credit" line), and written to the bundle's CREDITS.txt. Facts come from Sketchfab `license.txt`, glTF `asset.extras`
{title, author, license, source} and `asset.copyright`; never invented. The raw excerpt (<= 2 KiB) stays in the
import record as provenance. Conflicting sources -> licenseClass `unknown` with both shown. Correction path:
`prepare_model_asset` takes `attribution` fields only when the user stated them in this conversation
(`statedBy: "user"`); Sage must not fill them from guesses. `changes` is derived deterministically from the recipe
("scaled to 0.095 m tall; 3 copies; plain material instead of the texture on mug") plus an optional note from Sage.
Policy for Sage (playbook): CC0, CC BY, CC BY-SA: go ahead and keep the credit (SA: mention share-alike). Any NC:
say "non-commercial use only" before preparing. Any ND: say adapting it may not be allowed and ask before preparing.
unknown/other: say the licence could not be read and ask the user to check it before registering.

D8 Pictures. A worker-side preview renderer built on the `shape_preview` depth-buffer idea (helpers may be copied
into the self-contained package): per-pixel barycentric UV sampling of the base colour texture (sRGB decoded to
linear for shading, back to sRGB), Lambert + ambient, both faces drawn, alpha MASK per pixel, BLEND drawn after opaque
at its alpha, emissive added. Speed: triangles whose screen box is <= 2 px are splatted vectorized (depth-sorted, one
sample at the centroid); larger ones go through the per-triangle loop. Output: one contact sheet PNG (2 x 2 views:
front, side, back, three-quarter from above; each 384 x 384), a floor grid (0.1 m or 0.5 m by size), and the width,
depth and height in metres printed on it, labelled "preview (approximate)". Gates: 250k triangles in <= 20 s, 5k
triangles in <= 2 s on this computer; the source preview at upload draws at most the 250k largest-area triangles
(labelled so). `thumbnail.webp` 256 px from the three-quarter view.

D9 Review. Inspecting and preparing change nothing in layouts or the library. Registering adds a library asset (no
layout change), directly, like `author_shape`, logged in the import record. Placing uses the existing operations and
review policy unchanged.

D10 Chat attachments (frontend + transport).
- Only in a Facility Layout Sage chat with a bound layout and `layout.edit`; elsewhere the "+" menu item is hidden
  and the server refuses attachments with `attachments_unsupported`.
- The "+" button gets a small menu "Attach 3D model (.glb, .zip)"; dropping a file on the chat pane does the same,
  with a visible drop target while dragging. Each file uploads at once (`POST .../model-imports`), then its chip polls
  the record (`GET .../model-imports/{id}`) until ready/refused/failed.
- Chip: clean name, size, progress, state (uploading / checking / ready / refused + reason), remove (x). <= 3 per
  message. Chips belong to the conversation and the bound site/layout: switching conversation, site or layout clears
  them (an upload in flight finishes into the site's import list; nothing is lost on the server). A failed send keeps
  them; a successful send clears them. Send waits while a chip is uploading or checking (the button says
  "Uploading..."); ready and refused chips are sent (Sage is told the state).
- `AgentChatRequest.attachments: list[{kind: "model-import", importId}]`, <= 3, ids `^mi-[0-9a-f]{24}$`, validated
  against the bound scope before the turn starts. The attachment ids are part of the pilot request hash, the server
  memory identity and persisted retry state, so a different attachment never replays a cached answer.
- The pilot adds the attachments in every message-construction branch as structured untrusted data:
  `attachedModels: [{importId, name, format, megabytes, state, refusal}]` (name cleaned, <= 80 chars), never
  interpolated into instruction text.
- After a turn whose tool calls registered assets, the turn result carries `registeredAssets: [assetId]` (from the
  host's record of the registration, not from model text) and the workspace calls an explicit
  `refreshAssetCatalog()` so the library shows the asset at once, placed or not.

D11 Size, units, pivot, origin. glTF is metres by spec, but downloads are often centimetres or arbitrary. The app
reports the raw size and what each unit guess would make it (m, cm, mm, in). Sage picks the real size from what the
object is or the user's words, states it, and asks when it cannot tell.
Working frame: x/z origin at the pivot, y = 0 at the source's lowest point; units: source units until step 2, metres
after it. Pivot: "base" (default: centre of the source's bounds on x/z) or {parts: [selectors]} (x/z centre of those
parts' vertices in their lowest 10 % of height, e.g. a trunk).
Order: (1) `rotate` the whole source about the pivot (x, then y, then z; degrees), then re-take y = 0 at the lowest
point; (2) `size` (uniform scale about the pivot); (3) per-part rules in order: rename, drop, material patch, then
transforms about the part's own base centre (x/z centre of its bounds, its lowest y): `scale`, `turnDegrees` (about
vertical), then `move` [dx, dy, dz] metres or `moveTo` [x, y, z] (where its base centre goes, in the working frame);
(4) `copies` (each copy of the whole result so far: scaled and turned about the pivot, then moved by x/z); (5) `add`
simple parts in the working frame (metres); (6) final normalization: the whole result centred on x/z with its base at
y = 0 (the canonical contract; `primitives.verify`). Explicit surfaces and footprints are given in the final frame.
No mirroring is added (`model_axes.mirror_catalog_record` stays the only mirroring step).

## 3. Sage tools

Common: every string capped (names <= 80, description <= 300), arrays capped, numbers range-checked; the section-6
recipes must each stay under 8 KiB (the MCP request cap is 32 KiB). Parts are addressed by stable keys `p<n>` (one per
primitive instance in reading order: depth-first node order, then primitive index) and are named after their material
by default (mesh name when the material has none). A selector is `{"part": "p12"}` | `{"mesh": "<exact>"}` |
`{"material": "<exact>"}` | `{"node": "<exact>"}` | `{"all": true}`; a selector that matches nothing is an error that
names the closest keys and names; mesh, material, node and all may match several parts on purpose.

`inspect_model_import` (read, pictures). In: `importId`, optional `partsOffset` (default 0), `partsLimit` (<= 64,
default 64). With no `importId`: the imports of this site (newest 20: id, name, state, created). Out (<= 48 KiB):
name, format, state, refusal, triangles, raw size, unit guesses, up-axis hint (bounds and generator), licence {class,
title, author, urls, excerpt <= 600 chars}, partsTotal and the page of parts (key, names, triangles, bounds, base
colour, texture size, alpha mode, emissive, double sided), materials summary, flat-top hints (height and rectangle of
upward flat areas, hints only), warnings, and the source preview picture.

`prepare_model_asset` (edit gateway, pictures; changes nothing in layouts or the library). In, a recipe:
- `importId`, `name`, `category` (catalog categories), `description`, `tags` (<= 8);
- `rotate` {x, y, z} degrees; `pivot` "base" | {parts: [selectors]};
- `size` {dimension: height|width|depth|largest, meters 0.01-30} | {scale 1e-4-1e4};
- `parts` <= 64 rules in order: {select, name?, drop?, material?: {color "#rrggbb", roughness 0-1, metalness 0-1,
  texture keep|drop, emissive keep|off, alpha opaque|mask|blend, alphaCutoff 0.05-0.95, doubleSided} (omitted fields
  keep the source's value; `color` replaces the base colour factor), scale? 0.05-20, turnDegrees?, move?, moveTo?};
- `textureMaxPx` 256|512|1024|2048 (default 1024);
- `copies` <= 12 of {x, z, turnDegrees, scale 0.5-2}; default one at the pivot;
- `add` <= 8 simple parts: {shape box|cylinder|frustum, size [w, h, d] | radius | radiusTop + radiusBottom, height,
  hollow? wall thickness (cylinder and frustum: an open vessel with a floor, e.g. a pot), position [x, y, z] of its base
  centre, turnDegrees, name, color, roughness, metalness};
- `surfaces` <= 6 explicit rectangles {id, label, height, rect [x0, z0, x1, z1]} in the final frame (default none);
  each written with its frame origin at the rectangle centre and symmetric bounds (attachTo puts items at the origin);
- `footprint` "hull" (default: convex hull of the WHOLE model projected on x/z, simplified outward to <= 32 points
  so it never shrinks: collision and fit checks use it, spatial.py:676,1390, placement_intents.py:164) | "box"
  (the bounding rectangle);
- `attribution` user-stated fields (D7), `changesNote` <= 200 chars.
Out (<= 48 KiB, like inspect): draftId, dimensions, triangles, partsTotal and the first 64 parts after the recipe
(key, name, triangles), materials (<= 64), surfaces, footprint, warnings (<= 20), attribution and changes, and the
result picture. `inspect_model_import` also takes `draftId` (+ partsOffset/partsLimit) to page a draft's parts.

`register_model_asset` (edit gateway). In: `draftId`. Out: assetId, revision, display name, dimensions, credit,
`added`. The asset is in the library now; placing is a separate request with the existing tools.

Deferred (not v1): joining two different imports into one asset, automatic support surfaces, decimation, data: URIs,
texture painting or text removal.

Playbook (EDIT_INSTRUCTIONS, short): inspect first and look at the picture; state the licence as D7 says; choose a
real size and say it; prepare; look at the result picture and fix your own mistakes (orientation, floating parts,
wrong part names, washed-out, glowing or see-through materials) in at most 2 more prepare rounds; point out slogans,
brand marks or pictures of people you see and offer a plain material instead; register; tell the user the name,
size, credit and what changed; place only when asked. Never strip or alter the credit.

## 4. Phases (each ends with a commit by Claude after review; the builder never commits)

MI0a Reader + worker isolation (package `ai_inspector/industrial_assets/model_import/`, self-contained): safe GLB and
zip/glTF reader with every D1/D2 check (entry map, URI percent-decoding, `\` -> `/`, resolution relative to the
.gltf folder, `..` escapes refused, case-folded duplicates refused, never extracted to disk), accessor validation
(type, component type, normalized, bounds, alignment, stride, matching attribute counts, finite values, index values
< vertex count), node graph (cycles, depth, singular matrices refused, mirrored transforms flip winding, normals by
the inverse transpose), instancing budgets, materials and images per D1/D2, licence text parser, the summary JSON
(parts, unit guesses, flat-top hints, warnings), worker entry point with limits (D3) and its host-side runner.
Tests build their own fixtures in code (textured box GLB, glTF zip with license.txt + bin + PNG, a centimetre model,
Z-up, two materials, nested nodes with a mirrored scale, KHR_texture_transform, specular-glossiness) and the hostile
cases (zip slip, absolute path, backslash escape, case duplicate, zip bomb by ratio and by size, encrypted entry,
external and data URIs, Draco required, skin, morph target, sparse, index out of range, accessor past its buffer, NaN
position, node cycle, too many triangles after instancing, image bomb by size and by pixels, animated image, wrong
magic, truncated chunk), plus the worker: limits fail closed, timeout kills and joins, crash -> failed, no network
modules imported by the package (static test), scrubbed environment.

MI0b Recipe + writer: recipe JSON Schema (Draft 2020-12; the same object the MCP tool uses) and normalizer, transform
engine (D11), material rules, texture downsizing, copies, added simple parts (box, cylinder, frustum, hollow vessel),
footprint hull, explicit surfaces, the textured GLB writer (every material `facilityAuthoredFinish`, PNG/JPEG
textures, passes `primitives.verify` and `inspect_glb`), immutable draft folder, identity hash (D6), CREDITS text,
`changes` text. Tests: each recipe field; the six section-6 recipes against synthetic look-alike fixtures; output
passes verify; identity stable across runs and different for each changed input.

MI0c Preview: the D8 renderer, contact sheet, thumbnail, timing gates as tests (skippable on a slow machine with an
env var), alpha mask, textured face, emissive, double-sided.

MI1 Import store + routes: `model_import_store.py` (D4), routes `POST /api/facility-layouts/{site}/{layout}/
model-imports` (raw body, `X-Model-Name`, layout.edit, admission before reading the body, streamed cap),
`GET .../model-imports` (list), `GET .../model-imports/{importId}` (record), `GET .../model-imports/{importId}/
preview` and `GET .../model-drafts/{draftId}/preview` (PNG), the worker queue (D4 admission), atomic state
transitions, sweep safe against active jobs. Tests: permission (viewer refused), scope (another site's or tenant's id
answers not found), caps (body, admission), duplicate upload (same sha -> one source, new record), refused and failed
imports keep their record and reason, worker timeout and crash, concurrent uploads, sweep vs an active job.

MI2 Library registration: `attribution` field (shared entry check, binder, `read_authoring`), `install_bundle`,
`register_imported_asset` + runtime hooks, CREDITS.txt, catalog backup. Tests: live binding without restart and
again after a restart (fresh host on the same roots), same draft -> same id and `added: false`, identity conflict
refused, placed revision and bytes unchanged after another registration, interrupted publication (folder written,
catalog write fails) recovers, concurrent registration of the same draft, attribution validation (bad URL, too long,
control characters), a catalog without the field still binds, scope and permission at the boundary.

MI3 Sage tools: the three tools (inspect in facility_tools read specs and both gateways' `_read_data`; prepare and
register in `FacilityEditGateway`), progress labels (`progress._step`), the playbook, MCP limits (pictures via
`last_image`), every pinned tool list updated, `AgentChatRequest.attachments` + scope validation + hashes + memory
identity + pilot message construction, `registeredAssets` in the turn result. Tests: real-host tests (temp roots) for
upload -> inspect -> prepare -> register -> inspect_facility_asset -> placement proposal through the existing
operation -> restart; viewer denial; stale binding; cross-tenant and cross-site ids; picture results; failure
clearing; request and result byte limits; attachments change the request hash; a non-facility turn with attachments
is refused.

MI4 Frontend: chat attachments per D10 (+ menu, drop target, chips, upload, polling, remove, send, clear rules,
session switch), transport calls in facility_layout_transport.js, `refreshAssetCatalog()` on `registeredAssets`, the
Credit line in `_assetCard`, `normalizeCatalog` keeps `attribution`. ASCII only in static/index.html, LF endings,
`?v=` bump for every changed static file. Tests: node tests for pure helpers (chip state machine, payload builder);
Claude runs a Playwright check on an isolated server (D12).

MI5 Verification: the facility + codex + asset suites (same failures as the baseline), and an acceptance script
`tools/model_import_acceptance.py <downloads folder>` that runs the six section-6 recipes on the real downloads
through the worker and writes a report (dimensions, triangles, timings, previews) for Claude to compare with the
2026-11-08 assets. Claude runs it (the downloads stay outside the repo).

MI6 (morning, with the user): port to the real repo, restart the desktop app, a live Sage run with a real download.

D12 Test harness for Claude's browser checks (not shipped): a script that sets the desktop's feature flags, points
every store (facility root, generated assets, catalog, model imports) at a temp folder, makes `dotenv.load_dotenv` a
no-op before `import server` (server.py:50-52 loads two .env files on import), and serves on a free loopback port
(never 8181, 8480, 8491).

## 5. Rules for the builder (Codex)

- Work only in this worktree and in temp folders. Never read `.env*`, `ui-data/`, `.runtime/`, or any auth, token,
  cookie or session file. No network, no installs. Do not commit; Claude reviews and commits each phase. Leave a
  report per phase in `docs/sage-model-import-reports/<phase>.md` (changed, tests run, not run, deviations, open
  questions).
- LF line endings in every file you touch. ASCII only in server.py and static/index.html (server.py keeps its BOM).
- Keep changes to the phase. Existing behaviour changes only where the plan says (shared entry check, attribution,
  install_bundle beside install, chat "+" menu, attachments field).

## 6. Example recipes (acceptance; real downloads in Claude's folder, synthetic look-alikes in the tests)

1. Fruit bowl (vertexgrocer, 22 MB GLB; parts named after their materials, "bowl" among them): one rule
   `{select: {all: true}, material: {emissive: "off"}}`; no size change; expected 0.3-0.4 m long.
2. Serving board (itsjustcavan): rules by material: Material.002/.003 -> name "wine bottle"; red_wine -> "wine";
   glass -> "glasses"; bread -> "bread"; baked_FLAT -> "board"; Material.004 -> name "wine label", material {color
   "#e8dcc4", roughness 0.8, texture "drop"}; all: emissive off; `size {scale: 0.85}`; expected board 0.41 m long,
   bottle 0.32 m tall.
3. Mugs (The Lister, one part): material {color "#22272e", roughness 0.35, texture "drop"}; name "mugs";
   `size {dimension: "height", meters: 0.095}`; `pivot {parts: [{all: true}]}`; `copies [{x: -0.02, z: -0.11,
   turnDegrees: 20}, {x: 0.015, z: 0, turnDegrees: -15}, {x: -0.01, z: 0.11, turnDegrees: 35}]`; acceptance checks
   that no copy overlaps another.
4. Olive tree in a pot (massive-graphisme, 36 MB): `pivot {parts: [{material: "olive-tree-bark"}]}`; `size
   {dimension: "height", meters: 0.965}` (calibrated: the reference scaled the radial reach about the trunk to 0.7 m,
   which made the whole potted tree about 1.35 m tall; 0.965 m tree + 0.385 m lift = 1.35 m); rules: olive-leaves -> name "olive leaves", material {alpha "mask",
   alphaCutoff 0.5, emissive "off"}; olive-tree-bark -> name "olive trunk", emissive off; all -> move [0, 0.385, 0]
   (into the pot, 3 cm under the soil); `textureMaxPx 1024`; `add [{shape: "frustum", radiusBottom: 0.18, radiusTop:
   0.25, height: 0.45, hollow: 0.012, position: [0, 0, 0], name: "terracotta pot", color: "#b4643e", roughness:
   0.85}, {shape: "cylinder", radius: 0.234, height: 0.01, position: [0, 0.405, 0], name: "soil", color: "#3a2a1e",
   roughness: 0.95}]`; expected 1.35 m +- 0.03 m tall, trunk centred in the pot within 2 cm (MI5 measures both,
   and checks the lowest-10 % pivot against the reference's trunk-foot centre on the real olive and mug).
5. Basil pair (ellievaskali, one part): name "basil"; emissive off; `size {dimension: "height", meters: 0.3}`;
   `textureMaxPx 1024`; `copies [{x: 0, z: -0.105}, {x: 0.01, z: 0.105, turnDegrees: 70, scale: 0.92}]`.
6. Five vases as one shelf set (SusanKing; parts by material vase1..vase5): `size {scale: 0.005}`; rules with
   `moveTo`: vase1 [-0.34, 0, 0], vase4 [0.05, 0, 0], vase3 [0.38, 0, 0], vase5 [-0.22, 0.35, 0], vase2 [0.30, 0.35,
   0]; names "vase 1".."vase 5"; all: emissive off; `textureMaxPx 512` (the reference set them on two shelves of the
   run; here they are one decor set).

## 7. Open questions answered (Codex review 1)

1. Registered imports are deliberately shared in this app's private library (D5); imports and drafts are
   site-scoped.
2. v1 reproduces the six results within the bounded controls (per-part scale/turn/move/moveTo, pivot, copies,
   frustum and hollow vessel). Joining two different imports and automatic surfaces are deferred.
3. The downloads stay outside the repo; Claude runs the MI5 acceptance on them. Tests use synthetic fixtures built in
   code.
4. Build phases run with workspace-write in this worktree and temp folders, no network. Loopback browser checks are
   run by Claude.

## 8. Review 1 findings -> changes

1 D3 rewritten (resource boundary stated as it is, fail closed, kill+join, tests). 2 D4/D5 (scope on every lookup;
shared library by decision; checks at the registration boundary). 3 D1/D2 + MI0a (entry map, URI rules, data URIs
refused, methods, encryption, decompressed caps). 4 D1 + MI0a (accessor/index/graph validation, modes, winding,
normals, exact extension policy, texCoord). 5 D2 (aggregate and per-step budgets, sequential decode, 30 MiB output;
section 1 corrected). 6 D5 (`install_bundle`, validate before publish, files before catalog, recovery). 7 D6
(identity inputs, 24 hex, full compare on reuse, frozen drafts). 8 D11 (pivot vs final origin, order, units, no
extra mirroring). 9 section 3 per-part transforms, pivot, frustum/hollow; section 6 recipes. 10 section 3 (keys,
selectors, paging, caps; cross-import deferred). 11 D8 (per-pixel UV and alpha, splat + loop, gates, "approximate").
12 surfaces explicit only, flat-top hints; footprint defined. 13 D7 (fields, projections named, conflicts, user
correction, provenance, changes). 14 D10 (typed attachments, hashes, memory identity, structured data, refusal).
15 D10 (chip lifecycle, `registeredAssets`, explicit refresh; registration goes through the MCP tool, tested in MI3
with a real host). 16 MI3 real-host tests and wiring named. 17 baseline taken before MI0 (2026-11-09); MI0 split
a/b/c; MI1 immutable drafts, admission, quotas, safe sweep; D12 harness.

## 9. Review 2 findings -> changes (revision 3; these override anything above that disagrees)

1 Cancellation. The worker runner takes a cancellation `threading.Event`; it waits on the process in 0.2 s steps and
kills + waits when the event is set. `FacilityReadGateway.call` / the edit gateway dispatch (facility_tools.py:135-152
runs dispatch in a shielded thread) set that event when the turn is cancelled, for the model-import tools. A prepare
renames its draft into place only if the worker succeeded and the event is not set. Tests through the real gateway:
cancelling mid-prepare ends the worker, releases the admission slot and the import lock, and leaves no draft.
2 Footprint default = convex hull of the whole model (section 3 changed). Tests: an overhanging tabletop, a plant
canopy wider than its pot, an elevated part; checked through the existing spatial collision and placement-fit code.
3 Prepare output bounded and paged (section 3 changed). Test: a valid model of 3000 tiny primitives x 12 copies
prepares, returns its draftId and picture under the 64 KiB result cap.
4 Quantization honours `accessor.normalized` (D1 changed). Fixtures: normalized signed/unsigned byte/short UVs and
normals, unnormalized short positions under a node scale.
5 Storage. One per-site budget of 4 GiB covers sources, drafts, previews and job folders, taken by atomic
reservations before writing (an upload reserves min(Content-Length, 128 MiB); a prepare 64 MiB; a worker job 64 MiB;
each reservation is settled to the real size or released). Sources are reference-counted by import records: a source
file is deleted only when no record refers to it. At most 20 unregistered drafts per import (the oldest unregistered
one is deleted first). Registered drafts keep draft.json only (the bundle holds the files). Tests: repeated prepares
from one small source, concurrent reservations, duplicate-source cleanup.
6 Restart. The store reconciles on open and before each sweep: lock files hold {pid, process start time, created};
a lock whose process is gone (or older than the wall-clock limit x 3) is stale. Records in queued/checking with no
live lock become `failed` with code `interrupted` ("The check was interrupted. Retry or upload it again."); partial
uploads and job folders without a live lock are removed. `POST .../model-imports/{importId}/retry` re-queues a
failed import whose source is still there. Tests: restart during upload, during the worker, during result
publication; a polling client always reaches a terminal state.
7 Registration receipts and refresh. `register_imported_asset` writes a receipt `registrations/<draftId>.json`
{assetId, revision, at} atomically right after the live swap; registration is idempotent (`install_bundle` gives
`added: false` for the same bundle), so a retry after any failure re-creates a missing receipt; the import record's
registrations are read from receipts, not written separately. The library refresh does not depend on the turn
result: `GET /api/industrial-assets` gets a cheap `catalogVersion` (a counter bumped on each live swap, plus the
catalog file's mtime/size), and the workspace re-checks it after every facility Sage turn ends (success, failure,
interruption) and on reconnect, refetching the catalog when it changed. `registeredAssets` stays in successful turn
results as information only. Tests: failure right after publication and later in the same turn; the asset shows in
the library either way.
8 Olive recipe calibrated (section 6 changed); MI5 measures bounds and trunk/pot alignment with tolerances.
9 Chips. At most 2 uploads in flight per conversation; further files wait locally ("waiting"). An admission refusal
(HTTP 429) is retried automatically 3 times (2 s, 4 s, 8 s), then the chip shows "busy - retry". States and send:
waiting / uploading / checking block sending ("Uploading..."); ready and refused are sent (Sage is told the state);
failed is not sent and shows "retry" (calls the retry route) and remove. Tests (node, pure state machine): three files
at once, admission refusal, worker failure, conversation switch during polling.

## 10. Review 3 (VERDICT: AGREE) minor points, handled in the build

1 Reservations cover real peak storage: a worker job reserves its copied input plus bounded outputs; an upload
without Content-Length reserves the 128 MiB maximum; capacity is acquired before a reservation would be exceeded.
Tests: a large input and a header-less upload near the quota. (MI1)
2 A lock is stale only when its PID + process start time no longer match a live process; an expired but live
operation is cancelled and joined before its files are reclaimed. Test: an old lock whose operation still runs. (MI1)
3 After registration a draft keeps draft.json, its paged part metadata and preview.png; a repeated registration is
answered from the receipt and the verified bundle without the deleted draft files. Tests: repeat registration,
inspection and preview after cleanup and a restart. (MI1/MI2)
4 `GET /api/industrial-assets` reconciles the disk catalog into the live dictionaries when the catalog file changed
since the last swap (publication succeeded, live binding failed) before answering with the catalog and its version.
Test: a failure injected between catalog publication and the live swap; the asset appears without another
registration or a restart. (MI2)
