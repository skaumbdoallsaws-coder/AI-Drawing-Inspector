# Model builder (MB1a kernel, MB1b worker)

This package accepts bounded JSON data and produces an in-memory GLB. It imports
only stdlib, numpy, Pillow (through model_import), and the adjacent model_import
package. It does not import application parents, launch processes, fetch URLs,
publish drafts, or install assets. The kernel is in-memory; the worker task reads
only fixed, validated job inputs and its bundled font manifest.

`recipe.normalize_recipe(raw, allowed_categories=..., allowed_appearance_ids=...)`
is dependency-free. Hosts must pass the catalog category and bundled appearance
allowlists. Omitting categories permits syntax-only validation in fixtures;
omitting appearance IDs permits no default finishes. The closed JSON Schema is
`schema.RECIPE_SCHEMA`. Includes and prints validate now. Geometry expansion
refuses includes with `composition_unavailable` until MB3; prints currently
produce a background-colored quad with UV0, plus the closed backing plate.

`build.build_model(...)` returns a `BuildResult`: normalized input, Model, GLB
bytes, own geometry dimensions, floor-to-top catalog dimensions, normalization
shift, entry/instance-to-part-key map, lints, warnings, support surfaces,
footprint, pre-merge components, preflight budgets, and provenance. The components
are an in-process diagnostic seam, not a worker protocol payload. MB1b serializes
their bounded metadata; atomic draft publication belongs to MB4.

Use `recipe.portable_recipe(...)` before identity or publication. It separates
reference IDs and research citations from the recipe. Build provenance exposes
citations and size basis; its `sitePrivate.references` must never enter a shared
bundle. `hangHeight` belongs in provenance. `size.height` and
`BuildResult.dimensions.height` exclude hangHeight; catalog height and fit
height include it. The later host verification must use own geometry dimensions
and `base_height=hangHeight`, then register `catalog_dimensions`.

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
No images are produced yet. MB2 will extend the texture-bearing result contract.

Build refusals have an <=8 KiB canonical envelope with a known code, fixed
message, and bounded JSON path/problem. Triangle-budget refusals additionally
carry triangles and limit=60000. Only the build launch accepts these envelopes.
Infrastructure failures retain the existing model_* refusal codes.

On failure or cancellation the host joins the owned process and removes only
model.glb, result.json and error.json from its admitted job. Pre-existing output
causes refusal before ownership and is preserved. This is job cleanup, not
draft publication: MB4 must apply C41 around its later atomic publication.
