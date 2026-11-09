# MI2a catalog builder report

Date: 2026-11-09. Scope: D5 install_bundle, D7 attribution, revision 3 section 9
item 7 catalogVersion, and section 10 item 4 reconciliation. No commit, branch
creation, index changes, network access, package installs, or live catalog writes.
The concurrent MI1 store/routes/API wiring, static/, server.py, and the entire
industrial_assets/model_import/ package were left untouched by this builder.
Every host.py edit read the current file immediately before applying local edits
and checked for a concurrent change before writing.

## CHANGED

- ai_inspector/facility_layout/private_catalog.py (new): private_asset_spec is
  the old per-entry binder validation extracted intact. The manifest loader
  still supplies its existing seen/reserved IDs. Optional attribution validates
  the D7 fields, string limits, URLs, control characters, licenseClass and
  statedBy; it never supplies missing credit facts.
- ai_inspector/facility_layout/host.py: calls that shared validator; binds
  attribution on the catalog record and revisioned definition. Existing records
  without attribution keep the old definition shape/revision. Adds
  bind_installed_asset(asset_id) for MI2b, factoring the live swap from
  register_authored_asset; the basic-shape install and return contract remain.
  Swaps create new dictionaries and retain old definition revisions.
  list_assets() reconciles a changed disk catalog before returning assets and
  catalogVersion; the existing GET /api/industrial-assets route uses it and
  converts reconciliation failures to structured FacilityLayoutError responses.
  The marker is nanosecond mtime plus file size; the version string also carries
  the live-swap counter. Failed reconciliation does not advance the marker.
- ai_inspector/industrial_assets/authored_library.py: adds install_bundle beside
  the unchanged install function. Validates the shared entry contract, canonical
  transform, bounded file bytes, GLB via primitives.verify, output triangle cap,
  WebP RIFF envelope, exact credit text, manifest hashes/sizes and complete D6
  identity. Under LOCK + CatalogLock, exact reuse returns added false; any
  differing existing entry/files/identity raises asset_identity_conflict. A
  staging folder is renamed into imports/<assetId>/ before catalog publication;
  exact complete orphans are reused. Catalog backups and unchanged-byte guarded
  replace_file follow the existing installer. Existing bundle files are never
  repaired or overwritten. Manifest comparison ignores JSON formatting only.
- ai_inspector/codex_runtime/authoring_reads.py: projects attribution from the
  revisioned definition in inspect_facility_asset.
- tests/test_model_import_catalog.py (new): attribution rejection/bounds, legacy
  binding and reserved/duplicate IDs, bundle add/reuse/conflict/corruption,
  orphan recovery, interrupted publication, concurrent installation, live bind,
  inspection, placement/restart/revision stability, route-level reconciliation,
  unchanged-version checks, and whole-model footprint collision/surface-fit
  cases for a tabletop, a canopy over a smaller pot, and an elevated part.
  Synthetic fixtures use model_import prepare/writer and temporary roots only.
- docs/sage-model-import-reports/MI2a.md: this report and MI2b interface handoff.

## TESTS

Attempted through the hidden runner (windowsHide on parent):

    C:/Python314/pythonw.exe tools/run_hidden.pyw C:/Python314/python.exe -B -m pytest tests/test_model_import_catalog.py -q -p no:cacheprovider --basetemp=C:/tmp/mi2a

Result: exited 1 before collection: No module named pytest. No pytest tests ran.
The available Python launcher lists only C:/Python314/python.exe. Its
importlib.util.find_spec check also reports numpy, PIL, jsonschema and fastapi
unavailable. No installs or dependency substitutes were attempted.

Passed: Python compile() syntax checks for all five changed/new Python files,
without importing the application or writing bytecode; LF checks on each file;
git diff --check. Static comparison to HEAD confirms the existing install()
function is unchanged and the legacy per-entry checks were extracted exactly
apart from the added optional attribution projection.

## NOT RUN

- tests/test_model_import_catalog.py: blocked before collection by missing pytest.
- Adjacent regression suites: tests/test_authored_assets_live.py,
  tests/test_private_asset_footprints.py, tests/test_facility_layout_host.py,
  tests/test_codex_authoring_reads.py, tests/test_sage_shape_tools.py. Same missing
  runtime dependencies; these should be run by Claude outside this sandbox.
- Live provider, browser/Electron and MI2b import-scope/receipt flows: outside
  this catalog-only phase. TestClient in the new suite is in-process and imports
  the host directly, never server.py or its dotenv loading.

## DEVIATIONS

- A small shared private_catalog.py keeps the large entry validator out of the
  concurrently edited host.py. The apparent host deletion is that extraction.
- Attribution also enters the definition (and therefore its revision when
  present), so inspection of an exact placed revision retains the correct credit.
  Missing attribution introduces no default field or legacy revision change.
- bind_installed_asset swaps one requested entry. It deliberately leaves the
  full-catalog disk marker dirty until list_assets reconciles all entries; marking
  the entire file reconciled after binding only one could hide another publisher's
  pending asset. This can cause one extra full bind after a successful install.
- The plan leaves files/bundle.json's Python/JSON shapes open; the concrete
  bounded contract below is supplied for MI2b. Empty optional URL strings are
  accepted because MI0's factual attribution uses them for missing sources.
- Thumbnail validation here is size/integrity/RIFF-envelope validation, not an
  image decode; the isolated worker produces the thumbnail. The host performs
  the required hardened GLB verification before publication.

## OPEN QUESTIONS / MI2b HANDOFF

No blocking design question. Runtime validation remains for Claude.

install_bundle(root, entry, files):

- root is the project root, with its existing private catalog, like install().
- entry contains catalog_semantics(draft), assetId from
  model_import.identity.asset_identity(draft), artifact equal to
  generated/industrial_assets/authored/imports/<assetId>/model.glb, and identity
  sourceToCanonical. Full D6 identity is validated, not just the shortened ID.
- files is a mapping of exactly four names to bytes: model.glb, thumbnail.webp,
  CREDITS.txt, bundle.json. CREDITS.txt must equal credit.credits_text(attribution)
  encoded as UTF-8. bundle.json is UTF-8 JSON:

      {"schemaVersion": 1, "assetId": "asset-import-...",
       "identity": <asset_identity(draft)["identity"]>,
       "files": {"model.glb": {"sha256": "...", "bytes": 123},
                 "thumbnail.webp": {"sha256": "...", "bytes": 456},
                 "CREDITS.txt": {"sha256": "...", "bytes": 789}}}

  The manifest excludes its own hash. Incoming manifest formatting is
  canonicalized for new publication; existing semantically identical manifest
  formatting is retained on reuse.
- Returns {assetId, added, modelWritten, backup}, as install does. Invalid new
  input raises FacilityLayoutError(asset_bundle_invalid); reuse conflicts raise
  FacilityLayoutError(asset_identity_conflict, status_code=409). Filesystem/lock
  failures may propagate as OSError/ValueError, like the existing installer, for
  MI2b to translate at its route/runtime boundary.
- After installation, call host.bind_installed_asset(assetId); it returns a copy
  of the bound catalog record including assetDefinitionRevision, attribution,
  visual/thumbnail paths and definition. MI2b must enforce layout.edit and
  import tenant/site scope before publication, then write its registration
  receipt after this method succeeds. This internal method grants no permission
  and does not itself write receipts.
- GET /api/industrial-assets returns catalogVersion as an opaque string
  "<swap counter>:<catalog st_mtime_ns>:<catalog byte size>". It stays unchanged
  across repeated reads of an unchanged catalog and changes after a live swap
  or reconciled disk update.
