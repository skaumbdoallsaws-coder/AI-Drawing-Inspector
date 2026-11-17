# Model builder (MB1a kernel, MB1b worker, MB2 prints)

This package accepts bounded JSON data and produces an in-memory GLB. It imports
only stdlib, numpy, Pillow, and the adjacent model_import
package. It does not import application parents, launch processes, fetch URLs,
publish drafts, or install assets. Geometry is built in memory; print rendering
reads the pinned font. The worker task reads fixed, validated job inputs and its
bundled font manifest.

`recipe.normalize_recipe(raw, allowed_categories=..., allowed_appearance_ids=...)`
is dependency-free. Hosts must pass the catalog category and bundled appearance
allowlists. Omitting categories permits syntax-only validation in fixtures;
omitting appearance IDs permits no default finishes. The closed JSON Schema is
`schema.RECIPE_SCHEMA`. Includes and prints validate now. Geometry expansion
refuses includes with `composition_unavailable` until MB3. Panels have an RGB PNG
on their UV0 print quad, plus the closed backing plate.

`build.build_model(...)` returns a `BuildResult`: normalized input, Model, GLB
bytes, own geometry dimensions, floor-to-top catalog dimensions, normalization
shift, entry/instance-to-part-key map, lints, warnings, support surfaces,
footprint, pre-merge components, preflight budgets, provenance, and per-entry print
PNGs/text metrics. Components and render metrics are in-process diagnostic seams;
the worker serializes bounded metadata and embeds images only in the GLB. Atomic
draft publication belongs to MB4.

Use `recipe.portable_recipe(...)` before identity or publication. It separates
reference IDs and research citations from the recipe. Build provenance exposes
citations and size basis; its `sitePrivate.references` must never enter a shared
bundle. `hangHeight` belongs in provenance. `size.height` and
`BuildResult.dimensions.height` exclude hangHeight; catalog height and fit
height include it. Host verification uses own geometry dimensions
and `base_height=hangHeight`; registration will use `catalog_dimensions`.

Transforms follow C10: shape rotations use their unrotated bounding-box center;
groups use their own origin; R = Rz * Ry * Rx; patterns apply in the parent frame
after the entry transform. Pattern-copy paths are stable, such as
`frame[1]/rail[0]`; both group prefixes and leaf instances map to output keys.
One name becomes one node, with a primitive per named material. Faces use flat
normals. Welded indexed geometry, rather than split GLB normal vertices, defines
the edge-manifold checks.

Scatter uses a versioned SHA-256 counter stream. It scales the current entry
bounds by per-axis jitter, applies the sampled rotation, then samples a
translation from the interval that keeps every vertex inside `within`. An
oversized copy refuses; it is never squeezed or clipped. Closed tube joints are
plain miters; near-reversing joints refuse. Lathes close their radial profile,
with two points describing a capped solid; partial turns are refused.

Geometry budgets are checked before expansion, and output counts are checked
again before return. The contact lint uses a deterministic sweep capped at
100,000 candidate pairs and 20 findings per code. If that pair cap is reached,
it reports incomplete contact analysis and suppresses floating-part findings.
Coplanar checks cover box and panel faces with different materials, same-facing
normals, plane distance <= 0.3 mm, and overlap area > 1 cm2.

`imports.module(...)` uses `_model_import_worker` and bootstraps that adjacent
private package only when it is absent. The import worker preloads both private
packages for the build task only. Inspect and prepare retain their original
bootstrap and error decoding.

The shared reader/writer extensions are opt-in. Builder texture reading refuses
missing UV0, nonzero UV channels, and differing base/emissive UV transforms
because Part has one UV array. Matching transforms are baked into that array.
Default import behavior and output are pinned against the original writer in
`tests/fixtures/model_builder/import_writer_567f22a.py`.

## Worker and host boundary

The host entry lives outside this private package:
`ai_inspector.industrial_assets.model_builder_runner`.
`write_job_inputs(job, recipe, categories=..., appearance_ids=...)` fills a fresh,
empty, host-owned directory. `run_build(job, dependency_root, ...)` and its async
counterpart use the existing process launcher, limits and containment. They
validate the result and GLB hash, call application `primitives.verify` with the
recipe's hangHeight, and bind the part/material metadata to the GLB before
returning the result dictionary. GLB bytes remain in the job.

Input files are exactly recipe.json, allowed.json, fonts/ and includes/.
allowed.json contains categories and appearanceIds lists, limited to 512 and
1024 entries respectively and 256 KiB together. Fonts contains fonts.json and the
regular font named by it. The worker compares that manifest with the installed
package manifest, then checks the copied font's exact size and SHA-256. Replacing
both copies inside the job cannot replace the trust anchor. Includes is empty
until MB3, and a recipe containing an include returns composition_unavailable.
Files, directories, parents and font basenames are checked against links,
reparse points and path escapes. A build job has no source.bin.

Output files are model.glb (<=30 MiB) and result.json (<=16 MiB), written
exclusively with result.json last. The result retains the full entry/copy map;
its limit accommodates 3000 expanded components and up to four instance
prefixes per component. It is an internal worker record, not the later 48 KiB
MCP response. recipeSha256 binds the full normalized job input, including
site-private metadata; it is not the later portable-recipe asset identity.
The result includes image dimensions, byte counts, entry IDs and SHA-256 hashes.
The host binds each base/emissive texture to its embedded image and validates the
metadata-free RGB PNG's chunks, CRCs and bounded decompressed scanlines before
application geometry verification. No preview files are produced until MB4.

Build refusals have an <=8 KiB canonical envelope with a known code, fixed
message, and bounded JSON path/problem. Triangle-budget refusals additionally
carry triangles and limit=60000. Only the build launch accepts these envelopes.
Infrastructure failures retain the existing model_* refusal codes.

On failure or cancellation the host joins the owned process and removes only
model.glb, result.json and error.json from its admitted job. Pre-existing output
causes refusal before ownership and is preserved. This is job cleanup, not
draft publication: MB4 must apply C41 around its later atomic publication.

## Printed faces

`prints.render_panel(normalized_entry)` renders text, rectangles, lines, circles,
decorative barcodes, stripes and dots. A build renders each entry once and shares
that image across its pattern copies. Preflight still charges every expanded copy
against the eight-panel, four-megapixel print and sixteen-megapixel total texture
budgets. Textures use clamp-to-edge sampling. Pixel dimensions use the existing
common scale (2.5 px/mm, long side 64-1024), rounded to integer pixels. Ratios
that cannot be represented exactly have at most half a pixel of rounding per
axis; there is no intermediate square image or resizing pass.

Font bytes come from the package fonts/ in-process, or the host's copied fonts/
in a worker (`build_model(..., font_directory=...)`, a trusted caller option).
Both paths check the pinned manifest, size and SHA-256. Pillow uses the BASIC
layout engine, so optional system shaping libraries cannot change the layout.
Unsupported glyphs refuse as print_invalid with their characters. Bold is regular
plus stroke_width=round(0.04*font_size). Text uses explicit newlines (at most three
lines), ink bounds centered vertically and placed by left/center/right alignment
(the real ink, not Pillow's advance box). Auto-fit chooses an integer font size
from 4 through 4096: the box height sets the size through a fixed reference line
(LINE_REFERENCE, the tallest and deepest ASCII glyphs) for that many lines, so rows
of equal height get equal type whatever their letters; only a line too wide for its
box shrinks further. The minimum is clipped to its box if it still cannot fit.
Font objects have a bounded 16-entry cache.

Drawing fractions normally lie in 0..1, with v increasing down the image. Modest
overflow (-1..2) is accepted so print_clipped can report it; larger coordinates
refuse. Circle radii remain positive fractions of panel width, at most 1.
Rect/circle outlines go inward (circle outline defaults to 1 mm); line strokes
are centered. Rect radius and stroke sizes, circle radius, stripe widths and dot
pitch/radius use physical panel dimensions. Stripes alternate their two colors;
angleDegrees rotates the band normal clockwise from +u (0 = vertical bands).
Dots start half a pitch from their area's top/left and clip to that area. Dot and
stripe work is bounded by output pixels, independent of the number of physical
repetitions. Barcodes are decorative black/white bars with quiet margins from an
independent `model-builder-1:barcode` SHA-256 stream, not scannable identifiers.

Every print material carries facilityArtwork, white RGB base factors and its PNG
base texture. Lit prints share that image as emissiveTexture with [lit,lit,lit].
Backing plates retain their own color and are not emissive. A material used for
a printed front cannot specify finish. The GLB stays physically lit;
`prints.preview_model(result.model)` is the MB4 preview seam that makes lit print
materials unlit at full brightness without changing the GLB or legacy shaders.

The existing mesh transform corrects U and triangle winding after reflections.
Text follows the transformed panel's up direction; proper rotations rotate the
panel and its artwork together. Pixel tests sample the texture through geometric
front-view rays for all five facings, mirrors, rotations, nested groups and
around patterns. The canonical-to-layout mirror remains an MB7 visual gate.

print_small_text measures H cap height at the physical size of each transformed
copy (including scatter jitter), below 6 mm. print_clipped reports an item whose
extent crosses the panel boundary or text that fails at the minimum font size.
Both include entry/copy IDs and the print item index and cap at 20 findings per
code. Minimum-size text never draws outside its box.
