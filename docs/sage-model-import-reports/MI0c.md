# MI0c implementation report

## CHANGED

Implemented MI0c on the MI0b base, including both requested fixes. No commits,
branches, index changes, network calls or package installs. Changes are confined
to model_import, its tests and this report.

- Process lifetime: new process_tree.py selects and validates the absolute base
  interpreter, creates a host Windows kill-on-close Job Object before launch,
  assigns the process immediately after Popen, and terminates the whole job
  before joining. POSIX launches a new session and kills its process group.
  runner.py uses the same launch path for inspect and prepare. Worker resource
  limits remain in place and containment failures fail closed.
- Cleanup: new cleanup.py retries transient locks five times over 0.9 seconds.
  prepare_runner.py replaces TemporaryDirectory's error-masking cleanup with
  checked, owned-directory cleanup. Inspect outputs, published drafts and locks
  also use bounded retries. Persistent cleanup failures preserve the original
  refusal and leave owned remnants for MI1's sweep.
- Repairable refusals: new diagnostics.py and changes to recipe.py, transforms.py,
  footprint.py and errors.py provide up to five field-specific {path, problem}
  records. Missing importId, nested colour/range errors, invalid surfaces and
  selector misses now identify what Sage should repair. Closest selector names
  remain available. Details survive to_dict() and worker exit mapping and stay
  inside the existing 8 KiB error envelope.
- Renderer: preview_geometry.py selects the largest 250,000 source triangles
  deterministically and builds shared geometry/shader arrays. preview_raster.py
  implements orthographic depth buffering, bilinear barycentric UV sampling,
  sRGB/linear conversion, fixed Lambert plus ambient lighting, both faces,
  per-pixel MASK, ordered BLEND, emissive and unlit materials. Small triangles
  use vectorized centroid splats, including segmented alpha composition.
- Images: preview.py produces a labelled 768 x 768 PNG containing four
  384 x 384 views, metric dimensions, the floor grid and approximation/source-cap
  labels. The fourth view produces a 256 x 256 WebP thumbnail. Encoders enforce
  1.5 MiB / 64 KiB caps. The shared decoded-texture LRU is bounded to four images.
- Worker/protocol: worker_task.py writes the source preview. prepare.py writes
  both draft images. limits.py, job_io.py, protocol.py, prepare_protocol.py,
  runner.py and prepare_runner.py validate fixed filenames, image sizes/hashes,
  dimensions and PNG/WebP structure without decoding images in the host.
  New completion manifests are version 2. Legacy version-1 inspect caches still
  prepare; newly completed inspect/prepare outputs require pictures.
- Documentation: package README describes rendering approximations, file
  versions, caps, cancellation/cleanup and the diagnostic contract.
- Tests: added test_model_import_launch.py, test_model_import_diagnostics.py and
  test_model_import_preview.py. Updated the prepare-test manifest helper to
  version 2 so existing corruption tests continue to exercise their intended
  checks.

New coverage includes interpreter selection, real descendant termination for
both tasks on timeout/cancel, fail-closed containment, cleanup errors preserving
refusal codes, precise recipe feedback and worker diagnostic round trips.
Preview coverage includes image formats/caps, texture quadrants and wrapping,
linear-light shading, mask holes, texture/factor alpha, blend ordering and shared
edges, back faces, emissive, centroid sampling, tiny/large scales, source area
selection, worker publication, old-cache compatibility, corrupted image headers
and byte-cap fallbacks. Timing tests exercise full sheets at 5,000 and 250,000
triangles with 2-second and 20-second limits; MODEL_IMPORT_SKIP_TIMING=1 skips
only those timing tests.

## TESTS

Executed here, using hidden Windows processes:

- Standard-library real-subprocess probes passed for timeout and cancellation:
  the spawned descendant stopped writing its heartbeat, the parent was joined,
  and the job directory could be renamed after the bounded cleanup retry.
- Confirmed the worker's Windows resource limits remain active inside the new
  host Job Object before third-party import: CPU 60 seconds, memory 1.5 GiB,
  active-process limit 1. Used the existing limit-test probe at the dependency
  import boundary; this did not run a numerical import.
- Injected persistent PermissionError during prepare cleanup: timeout remained
  model_timeout, cancellation remained model_cancelled, five retries occurred
  and the owned directory was left for sweeping.
- Dependency-free recipe probes passed for missing importId, nested colour,
  size range, move/moveTo conflict, reversed surface rectangle and invalid
  attribution URL. Unicode diagnostic payloads remained within the wire cap.
- A generated PNG passed the host chunk/CRC/dimension validator; truncation was
  refused.
- Syntax compilation and LF checks passed for all 43 package/model-import test
  modules present at the check. AST checks confirmed package imports remain
  relative or standard library/numpy/Pillow.
- git diff --check passed.

Attempted the combined pytest command through tools/run_hidden.pyw:

    python -B -m pytest tests/test_model_import_reader.py tests/test_model_import_worker.py tests/test_model_import_regressions.py tests/test_model_import_recipe.py tests/test_model_import_prepare.py tests/test_model_import_launch.py tests/test_model_import_diagnostics.py tests/test_model_import_preview.py -q -p no:cacheprovider --basetemp=<temporary-directory>/mi0c/pt

It exited before collection: No module named pytest. The available Python 3.14
interpreter has no numpy, Pillow, pytest or jsonschema; no worktree venv was
available. No pytest pass count is claimed.

## NOT RUN

- The full pytest suite, pixel assertions, actual PNG/WebP encoder checks,
  numerical inspect/prepare subprocess success paths and determinism checks.
- Both timing gates and the real-download preview/total-worker CPU checks.
  Performance is not established; Claude must run these in the real venv.
- POSIX process-group and resource-limit paths on a POSIX machine.
- Visual review of rendered contact sheets, since the rendering dependencies
  are unavailable here.

## DEVIATIONS

- No requested feature was intentionally deferred. Runtime validation is blocked
  by the missing sandbox dependencies, as permitted by the phase rules.
- Image-bearing completion manifests use version 2 to distinguish required
  pictures from legacy caches; draft.json schema and identity inputs are
  unchanged. Legacy source caches remain compatible.
- Preview implementation choices are documented: orthographic cameras, flat
  Lambert illumination from averaged normals, centroid ordering for transparent
  surfaces, display-clamped emissive, and a single centroid splat when both
  projected box dimensions are <= 2 pixels. Subpixel grid lines are hidden.
  High-entropy sheets may use a palette PNG to meet the hard byte cap.
- The package continues to raise its independent ModelImportError. MI1 remains
  responsible for FacilityLayoutError adaptation and sweeping owned remnants;
  MI3 must retain details.problems in tool refusals.

## OPEN QUESTIONS

No design decisions are pending. Claude's real-environment tests, timing gates
and image review remain the validation gate before committing MI0c.
