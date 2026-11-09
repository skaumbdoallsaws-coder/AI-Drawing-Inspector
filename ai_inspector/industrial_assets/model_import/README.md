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
