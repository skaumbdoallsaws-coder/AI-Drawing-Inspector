# MI0a model intake

This directory is independent of the application. It imports only the standard
library, numpy and Pillow, plus its own modules. It does not import server,
facility_layout, codex_runtime, packaging_shipping or the industrial_assets
parent package. The isolated worker bootstraps this directory as a private
package so Python does not execute the parent's __init__.py.

## Entry points

- reader.read_model(payload, name="Imported model", *, limits=DEFAULT_LIMITS,
  texture_max_px=1024) returns a Model. Use this only inside a resource-limited
  worker or with trusted generated test fixtures.
- summary.build_summary(model, *, parts_offset=0, parts_limit=64) returns an
  inspection page without a picture. Pages include nextPartsOffset; the byte
  budget can make a page smaller than requested. materialsTotal describes the
  complete material table even when its summary is shortened to fit.
- worker_task.execute_inspect(job_dir) runs the complete task in-process for
  trusted tests. It deliberately does not set process-wide limits in the test
  runner. Production always uses worker.py through runner.
- runner.run_inspect(job_dir, dependency_root, *, cancel_event=None, timeout=70)
  returns the validated first summary page and leaves the successful cache.
  run_inspect_async has the same arguments, signals cancellation, then joins
  the runner thread before propagating CancelledError.
- cache.load_cache(job_dir) reconstructs a Model inside a worker. It verifies
  the completion manifest and uses allow_pickle=False. Do not load this cache
  in the server process.

The dependency root is a trusted absolute directory containing both numpy and
PIL. MI1 should supply glb_runtime().dependency_root from the host binding.
It is never taken from uploaded JSON. The runner does not discover packages
from environment variables or import packaging_shipping.

ModelImportError has code, message, status_code and to_dict(). The host
integration in MI1 must translate it to FacilityLayoutError. Keeping that
translation outside this package preserves the self-contained worker.

## Worker protocol

Invoke the same interpreter as the host:

    python -I -S -B worker.py <dependency_root> <job_dir> inspect

The caller owns a fresh, absolute, non-linked job directory. Inputs:

- source.bin: exact uploaded GLB or zip bytes, at most 128 MiB.
- request.json (optional, at most 4096 bytes): an object with name (display text)
  and textureMaxPx (256, 512, 1024 or 2048). Defaults are "Imported model" and
  1024. These are host options, not arbitrary filenames or module paths.

Successful outputs:

- summary.json: validated inspection page, at most 48 KiB.
- cache.json: version 1 metadata, at most 16 MiB.
- parts.npz: uncompressed numeric arrays and normalized encoded image bytes,
  at most 384 MiB.
- result.json: version 1 completion manifest written last, at most 4096 bytes.
  Its files map records bytes and sha256 for the three files above.

The runner checks fixed names, regular files, size caps, hashes and the summary
schema. It reads no array or image data into a decoder. Hashes are streamed.
It removes partial outputs on failure/cancellation; source.bin and job cleanup
remain the caller's responsibility. Existing output files are never overwritten.

Exit codes: 0 success; 1 unexpected worker failure; 2 controlled refusal in
error.json; 3 missing dependency; 4 resource limits unavailable. Refusal JSON
contains only a known code and its fixed public message. Unexpected exceptions
and source paths are never returned to the caller.

The process uses no stdin/stdout/stderr. The environment is allowlisted, home
and temporary paths point at the job, numerical thread counts are one, and
Windows launches are hidden. CPU (60 s), memory/address space (1.5 GiB), and
platform process/file limits are set before dependency imports or source reads.
POSIX also disables core dumps and caps file descriptors at 64. Windows uses a
one-process Job Object with kill-on-close. The parent checks cancellation and
wall time at intervals of at most 0.2 seconds and always kills/joins on failure.

These are resource limits, not an OS filesystem/network sandbox.

## Cache version 1

cache.json contains schemaVersion, name, format, sourceBytes, sourceSha256,
generator, materials, licence, warnings, parts and images.

Each part has key, name, node, mesh, material (an index into materials), and an
arrays map. Stable source keys count primitive instances in selected-scene
depth-first order, then primitive order. Dropping point/line primitives can
leave gaps in these keys. Cache array names use the retained part's ordinal:

- pN_positions: float32, shape (vertices, 3), world/source coordinates.
- pN_normals: optional float32, shape (vertices, 3), inverse-transpose transformed
  and normalized.
- pN_uv0: optional float32, shape (vertices, 2).
- pN_indices: uint32, shape (triangles, 3), strips/fans converted, reflected
  transforms' winding reversed.
- imageN: uint8, shape (encoded_bytes,), containing a fresh PNG (used alpha) or
  JPEG q85 (opaque). Image records supply MIME type, resized and original sizes.

There are no object arrays or pickles. Nodes and buffers are flattened; source
arrays are not retained. The model is not re-centred or scaled to assumed metres
in MI0a. A recipe requesting textures larger than the cached inspection size
must re-read source.bin at the requested texture_max_px; cache images cannot
restore discarded pixels. Recipes changing alpha use must also re-decode the
source images with their patched materials: inspection intentionally drops
unused alpha. The read_images helper accepts that material table. No catalog
mirroring occurs.

Base-colour KHR_texture_transform is already baked into each part's UV0.
The material retains offset/scale/rotation as source metadata: MI0b must not
apply them a second time when writing the GLB. Sampler wrapS/wrapT remain
available for the later writer/renderer. A part with no UV0 cannot display a
texture even if a shared material references one.

Only base-colour texture maps are retained. Emission factors and emissive
strength, roughness/metalness, alpha mode/cutoff and double-sided flags survive.
Normal, occlusion, emissive and metallic/roughness maps are omitted with a
warning. Specular-glossiness uses diffuse factor/texture, zero metalness and
1 - glossiness as roughness; it is labelled as an approximation. Unlit is
recorded as a flag for the later writer.

Zip resources are resolved as virtual, case-sensitive names after URI
percent-decoding and slash normalization. Case-folded entry aliases, root
escapes, links, special files and encryption are refused. Entries are never
extracted. Every non-model/non-licence file must be referenced as a buffer or
image; resource file extensions and supplied image MIME types do not determine
image format. A GLB remains self-contained even when zipped.

Licence parsing keeps facts from Sketchfab labels and glTF asset metadata.
Unknown or conflicting attribution is explicit. Full bounded provenance stays
in cache.json; summary excerpts/conflict values are shortened for tool budgets.

MI1 storage reservations must include copied source bytes plus the bounded
cache/output files above, not a fixed 64 MiB worker allowance. MI0b's prepared
GLB and MI0c's picture/thumbnail limits are separate; this phase emits none.

## Tests

All fixtures are generated in tests/model_import_test_support.py. No real
downloads, credentials, app stores or network are used.

    python -m pytest tests/test_model_import_reader.py tests/test_model_import_worker.py -q -p no:cacheprovider --basetemp=<short-temp-directory>

The tests load this package without importing the application. Most parsing
runs in-process; worker startup, actual parsing, dependency failure, timeout,
cancellation and environment isolation also have real subprocess coverage.
Windows and POSIX limit probes run only on their respective platforms.


## MI0b: recipes and frozen draft output

The public schema is recipe.RECIPE_SCHEMA (Draft 2020-12). MI3 should reuse
that exact object. normalize_recipe validates the schema's closed objects and
caps, performs semantic checks, fills defaults, cleans names and rounds numbers
to 1e-6. It needs only the standard library. The tests compare this contract
with jsonschema; the worker does not import jsonschema.

Catalog categories are open strings, matching host._private_manifest_specs;
there is no fixed category enum in that binder. Extra numerical ceilings for
fields without explicit plan limits: angles -360..360 degrees, translations
and rectangle coordinates -100..100 m, support heights 0..100 m, added sizes
0.0001..30 m and radii 0.0001..15 m. Hollow thickness must be positive and
smaller than both radii and height. The result must have finite positive
dimensions <=10,000 m and a footprint above the catalog's 1e-9 area tolerance.
These are schema/validation ceilings, not recommended object sizes.

D11 is implemented in transforms.transform_model. Selectors refer to stable
source keys and source material/mesh/node names, even after rename/material
rules. Dropped parts stop matching subsequent selectors. Only indexed vertex
rows contribute to the prepared solid; unused source vertices are discarded
before sizing, pivot calculation and copies. Copies retain the original part
name. Output keys are assigned anew as p0, p1, ... in copy/source order, then
added parts. Sizes are meters after the global size step.

Hex colours are converted from sRGB to linear RGB, matching primitives.Finish;
a colour patch replaces the complete factor with that RGB and alpha 1. Other
omitted material properties retain source values. Source UV transforms have
already been baked by MI0a and are not written a second time. Original image
bytes are decoded again after material patches, under all MI0a image budgets,
so increased texture resolution or a new alpha mask can recover information
discarded by the inspect cache. PNG is used when actual alpha is retained,
otherwise metadata-free JPEG at quality 85.

footprint.footprint uses every output part, including overhangs and elevated
parts. A hull of more than 32 points is enlarged by retaining 28 selected hull
half-planes and the four bounding-rectangle planes. It remains convex, contains
the actual hull, and stays within the exact model bounds. Explicit support
rectangles must be inside those bounds; the exported origin is their centre
with symmetric minimumX/maximumX/minimumZ/maximumZ bounds and authored evidence.

writer.write_glb emits deterministic GLB bytes, at most 30 MiB and 250,000
triangles. It preserves each output part as a node, shares identical accessor
and mesh data, embeds only used base-colour PNG/JPEG images, and marks every
material with facilityAuthoredFinish and facilityMaterialRole. The material
role equals the part name. Emission above 1 uses KHR_materials_emissive_strength;
unlit materials retain KHR_materials_unlit. Source limits of 4096 parts/64
materials do not apply to *output*: copies may produce 49,160 parts, and
differently named authored finishes may need more materials. Public summaries
contain at most 64 material records, with materialsTotal giving the full count.

Worker CLI:

    python -I -S -B worker.py <dependency_root> <job_dir> prepare

Inputs are source.bin, recipe.json (<=32 KiB), and optionally the complete,
unchanged MI0a cache files (summary.json, cache.json, parts.npz, result.json).
Without that cache, inspect runs first within the same limited worker. Cache
source SHA must match source.bin. Output is a new job_dir/output folder:

- model.glb: <=30 MiB, deterministic bytes.
- draft.json: <=128 KiB, normalized recipe, engine/source/output identities and
  bounded public fields. The full recipe is metadata, not returned to Sage.
- parts.jsonl: <=32 MiB, every output part in order, one bounded JSON record
  {key, name, triangles} per line. This is the future draft paging source.
- CREDITS.txt: <=16 KiB UTF-8 with LF, factual attribution and changes.
- manifest.json: written last; fixed filenames, byte sizes and SHA-256 hashes.

prepare.build_draft(source_model, recipe, original_bytes) returns
(draft_metadata, glb_bytes, prepared_model) for generated-fixture tests and the
MI0c renderer hook. No numerical output cache is required: MI0c can render the
returned model in the same worker before publication. Output model.glb can
exceed the MI0a source scene/JSON budgets, so do not feed a many-part prepared
GLB back through the source reader with its default limits.

prepare.prepare_summary returns <=48 KiB: draftId, dimensions, triangles,
partsTotal, a prefix of at most 64 part records, nextPartsOffset, materialsTotal,
up to 64 materials, surfaces, footprint, up to 20 warnings, attribution, changes.
Normal inputs include all first 64 parts/materials. Very long escaped Unicode
metadata can shorten the prefix/material list/warnings to meet the byte cap.
The complete part ledger is retained. Full draft metadata is bounded separately
so a near-32-KiB normalized recipe does not consume the public result budget.

Host API (available from runner and prepare_runner):

    prepare_draft(source_path, recipe, out_dir, cancel=None,
                  dependency_root=None, cache_dir=None, timeout=70)
    await prepare_draft_async(source_path, recipe, out_dir, cancel=None, ...)

Paths must be absolute, local, and without symlink/junction ancestors.
dependency_root and cache_dir are trusted host configuration, never recipe
fields. With no dependency root, the current interpreter's installed numpy
package location is used without importing it. The host makes a fresh temporary
job under out_dir's existing parent, copies bounded inputs, runs the isolated
worker, checks every output hash/size and the draft/part-ledger schema, then
renames the output into the absent destination. It returns the public summary.
It never replaces a pre-existing destination. A short-lived exclusive sibling
.prepare-lock serializes cooperating attempts at that destination; MI1 owns
crash recovery, scope, quotas and admission. A host-process crash can leave a
job/lock for MI1 reconciliation. Successful and failed regular calls remove
their temporary job/lock. Account for source plus the MI0a cache, draft output
and metadata when reserving job capacity; do not reserve only the public JSON.

Both tasks wait in 0.2-second process steps, kill and join on cancellation or
timeout, and map stable worker exits. Async cancellation waits for the owning
thread and removes even a completed output whose delivery lost the race.
Pre-existing files and destinations are preserved. Resource limits still
precede all third-party imports. The host imports no numerical/image modules;
MI1 translates ModelImportError to FacilityLayoutError.

identity.asset_identity(draft, optional_catalog_entry) returns assetId, the
full identity SHA and the complete D6 identity object for MI2 conflict checks.
Artifact paths and assetId are excluded from catalog semantics. Draft IDs are
deterministic md-<24 hex> prefixes of the same complete identity digest.
credits_text and changes_text are deterministic; the bounded changes string
reserves space for changesNote. Attribution overrides require statedBy=user;
whether the user actually stated them is the MI3 conversation policy.

No preview, import store, catalog registration, Sage tool or frontend behavior
is introduced by MI0b. primitives.verify and artifacts.inspect_glb are used by
host-side tests; MI2 must call them before library registration.
