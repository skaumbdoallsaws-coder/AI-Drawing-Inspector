# Facility Layout P0 Baseline Report

Date: 2026-07-28

Plan reviewed: `docs/industrial-layout-platform-implementation-plan.md`, revision 2

Baseline window: 2026-07-28 19:18-19:38 UTC-05:00

Overall result: **NOT GREEN**

The Facility Layout endpoint/data bar, Facility mode contract, complete current
Process Map backend suite, Process Map Node harnesses, core schema tests, and
all parser-level syntax checks passed. The frozen snapshot still has:

- the documented Legacy Training result of 15 passed / 8 failed; and
- 14 current agent-registry test failures (60 passed / 14 failed) caused by
  stale expected skill/tool catalogs in two test modules.

No application code was edited for this verification.

## Scope and Safety Controls

- Repository used:
  `<workspace>\AI-Drawing-Inspector`.
  The workspace root itself contains a `.git` directory but was not recognized
  as a Git repository; the nested project is the active repository.
- `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` were forced to empty strings before
  every test that imported the server.
- No paid model, shadow-model, or network call was made.
- The agent streaming tests use `test-not-real`, monkeypatched provider
  functions, and synthetic 11-input/7-output-token responses. Their temporary
  telemetry therefore records four synthetic `anthropic` events and a
  calculated cost, but those records do not represent provider requests or
  incurred cost.
- `PYTHONDONTWRITEBYTECODE=1` prevented Python bytecode output.
- Pytest caching was disabled with `-p no:cacheprovider`.
- Every pytest command used `--basetemp` under the current user's system temp
  directory.
- Every telemetry database was redirected to an
  `InspectorPro-P0-*.sqlite` file under that same temp directory.
- Process Map backend tests write only to `tmp_path` fixtures. The one test that
  consumes real racing-bike data copies its three inputs to `tmp_path` first.
- The Legacy Training suite only reads real generated assets.
- Real Facility and racing-bike generated inputs were hashed before and after
  all tests. Individual and recursive tree hashes were unchanged.

## Environment

| Item | Value |
| --- | --- |
| Git branch | `ui-bridge-telemetry-unified-2026-05-18` |
| Git HEAD | `96e678d40113ccf8e0f55917879708c54aa12cee` |
| Upstream state | 40 commits ahead of `origin/ui-bridge-telemetry-unified-2026-05-18` |
| OS | Windows 11 Home 64-bit, version `10.0.26200`, build `26200` |
| CPU | 13th Gen Intel Core i7-1355U, 10 cores / 12 logical processors |
| RAM | 16,454,352 KiB visible (about 15.69 GiB) |
| Time zone | America/Chicago; Windows `Central Standard Time`; observed UTC-05:00 |
| Python | `3.14.0` |
| pytest | `9.1.1` |
| Node.js | `v24.11.1` |
| npm | `11.9.0` |
| Git | `2.51.2.windows.1` |

Repeated non-fatal environment warning:

```text
Core Pydantic V1 functionality isn't compatible with Python 3.14 or greater.
```

This comes from `langsmith.schemas`; it did not fail collection or execution.

## Dirty Worktree Snapshot

At baseline start:

- 41 tracked modified files;
- 88 top-level untracked entries reported by normal Git status;
- no staged diff; and
- multiple access warnings for pre-existing `.pt*` and `.pytest_tmp_*`
  directories plus the current user's `.config\git\ignore`.

After tests but before this report:

- the same 41 tracked modified files and the same 41 `git diff --name-only`
  paths remained;
- the untracked count was 91; and
- no new test-temp or baseline-report entry existed in Git status.

The repository was changing concurrently. Timestamp inspection showed at least
these unrelated files/families appearing while this verifier was running:

```text
static/contracts/facility-layout-authorization-v1.json
static/contracts/facility-layout-observation-contract-v1.json
tests/fixtures/facility_layout/
tools/benchmark_facility_layout_renderers.py
docs/facility-layout-p0-asset-normalization-report.md
```

Another process briefly held `.git/index.lock`. It cleared without action from
this verifier, HEAD remained unchanged, and none of the selected application or
test files appeared in the concurrent timestamp set. Nothing was cleaned,
staged, reverted, or deleted.

## Results

Counts in different rows are not additive because the focused schema bar
re-runs schema tests already included in the complete Process Map backend bar.

| Bar | Pass | Fail | Skip | Wall time | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Facility Layout TestClient endpoint/current-data probe | 22 | 0 | 0 | 9.331 s | PASS |
| Facility/Plant mode contract (`test_mode_contract.py`) | 28 | 0 | 0 | 6.260 s | PASS |
| Complete current Process Map Python suite (`test_process_map_*.py`) | 216 | 0 | 0 | 22.960 s (pytest 19.76 s) | PASS |
| Process Map editor Node harness | 83 | 0 | 0 | 1.353 s | PASS |
| Process Map spatial Node harness | 44 | 0 | 0 | 1.562 s | PASS |
| Floating-surface Node harness | 14 | 0 | 0 | 1.367 s | PASS |
| Legacy Training real-data suite | 15 | 8 | 0 | 9.106 s (pytest 7.13 s) | KNOWN FAIL |
| Core Process Map + Assembly Knowledge schema tests | 31 | 0 | 0 | 3.165 s | PASS |
| Core agent tests | 60 | 14 | 0 | 11.773 s (pytest 8.99 s) | FAIL |
| Python AST syntax (`server.py`, `ai_inspector`, `tools`, `tests`) | 242 | 0 | 0 | 2.918 s | PASS |
| JSON/YAML contract parsing | 39 | 0 | 0 | 0.358 s | PASS |
| Standalone + inline JavaScript syntax | 24 | 0 | 0 | 1.733 s | PASS |

An initial combined schema/agent run produced 91 passed / 14 failed in
15.669 seconds. The split rows above isolate the result: all 31 schema tests
pass and all 14 failures are in agent tests.

## Facility Layout Findings

The in-process FastAPI probe exercised:

```text
GET  /api/training/facility-layout/semantic
POST /api/training/facility-layout/capacity
POST /api/training/facility-layout/route
GET  /api/training/facility-layout/layout-analysis
```

Observed current data:

| Field | Value |
| --- | --- |
| Semantic schema | `facility-layout-semantic-v0.2` |
| Rack rows | 5 |
| Rack occurrences | 24 |
| Material-handling assets | 5 |
| GLB bytes | 327,184,996 |
| Coordinate correspondences | 24 |
| Maximum alignment residual | 0.06131 m |
| Upper-middle capacity sample | 392 boxes |
| All-row capacity sample | 2,618 boxes |
| `forklift 1` to `upper middle` route | 7.92 m, `~5 s`, no reported obstacle violation |
| Baseline OD total | 423.3 m over 35 OD pairs |
| East-cross-aisle what-if total | 405.1 m |
| Reported reduction | 4.3% |

The 0.06131 m residual and rough rack envelopes remain suitable only for the
current explanatory demo. They are not clearance or safety authority, exactly
as the implementation plan states.

The negative endpoint paths also passed:

- unsupported capacity unit -> HTTP 400;
- unresolved route endpoint -> HTTP 400.

## Existing Failures

### Documented Legacy Training Failures

The implementation plans already document the Legacy Training bar as
15 passed / 8 known fixture failures. This run reproduced that exact count:

1. `test_racing_bike_process_map_working_draft_shape`
   expects legacy schema string
   `racing-bike-process-map-working-draft-0.17`; the dirty real asset is schema
   v3.
2. `test_racing_bike_process_map_approved_baseline_shape`
   cannot find `racing_bike_process_map_approved_baseline.json`.
3. `test_racing_bike_subassembly_visual_manifest_and_guided_build_plan`
   expects legacy `process["nodes"]`; the current schema-v3 asset has no
   `nodes`.
4. `test_racing_bike_assembly_context_names_follow_process_map`
   cannot find `racing-bike_assembly.json` in either demo or full library.
5. `test_training_shop_floor_narration_behavior`
   invokes a Node helper that expects legacy `processMap.nodes`.
6. `test_front_wheel_brake_extract_excludes_mudguard_after_reextract`
   reads a UTF-8 BOM file with `encoding="utf-8"` and fails JSON decoding.
7. `test_training_explode_vectors_from_extract_behavior`
   feeds the same BOM-prefixed extract to Node `JSON.parse`.
8. `test_training_apply_extract_explode_steps_behavior`
   feeds the same BOM-prefixed extract to Node `JSON.parse`.

### Current Agent Baseline Failures

These 14 failures existed in the dirty snapshot before this report, but they
are not listed as the historical known-failure bar in the P0 plan:

- `test_phase3_registry_resolves_dependency_bounded_skill_compositions`
  expects 8 registered skills; the current registry has 10.
- Thirteen tests in `test_agent_skill_routing.py` build a local known-tool
  catalog containing only `ui_actions` and `highlight_features`. Current
  manifests additionally declare:
  `inspect_process_map_spatial_layout`,
  `propose_process_map_connection_route`,
  `propose_process_map_demo_metadata`,
  `propose_process_map_node_placement`, and
  `build_process_map_preview`.

The affected routing tests are:

```text
test_candidate_catalog_filters_without_loading_skill_body
test_route_validator_accepts_registered_read_only_route
test_route_validator_rejects_unknown_ids_unavailable_skills_and_extra_keys
test_route_validator_rejects_read_only_writes_and_canonicalizes_effect_categories
test_route_validator_rejects_unknown_target_and_invalid_skill_roles
test_route_validator_adds_dependencies_and_rejects_conflicts
test_route_validator_normalizes_multiple_primary_skill_roles_by_confidence
test_route_prompt_contains_metadata_not_skill_body_and_delimits_untrusted_text
test_route_prompt_omits_execution_only_context_and_redundant_catalog_fields
test_shadow_classifier_validates_caches_and_never_marks_output_executable
test_shadow_classifier_reports_failure_reasons
test_compact_v2_route_derives_server_owned_fields
test_typed_intent_deterministically_selects_primary_skill
```

The common exception is `RegistryValidationError`, reporting that Process Map
tools in `analyze-process-map@1.4.0` and `generate-process-map@1.2.0` are
unavailable in the test's stale local catalog.

## Generated-Input Integrity

All hashes are SHA-256. "Before" was captured before endpoint/test execution;
"After" was captured after every selected bar. Values are identical.

| Input | Bytes | SHA-256 before | SHA-256 after |
| --- | ---: | --- | --- |
| `facility_layout_semantic.json` | 99,910 | `269ed9e33c32f7937221b4cbf26c52ea61b529999c96c16f38b4cd5d02f6077d` | `269ed9e33c32f7937221b4cbf26c52ea61b529999c96c16f38b4cd5d02f6077d` |
| `generated/training/facility-layout/Assem3_colored.glb` | 327,184,996 | `da2be02acea430027324857e58db3ddee81713dcf9b54e38d45b830671898ce2` | `da2be02acea430027324857e58db3ddee81713dcf9b54e38d45b830671898ce2` |
| `generated/training/facility-layout/facility_layout.json` | 243,131 | `c07f8bd574ea151d1a6e2060e8716ec96db1279bf11b6e0769a03e737e0b7c0a` | `c07f8bd574ea151d1a6e2060e8716ec96db1279bf11b6e0769a03e737e0b7c0a` |
| `generated/training/facility-layout/facility_layout_attach_check.json` | 243,131 | `30dbc74ad6cb2ea721607794bae467b6c2d5a6f3fd1a5e1b9154c035a2aa2f55` | `30dbc74ad6cb2ea721607794bae467b6c2d5a6f3fd1a5e1b9154c035a2aa2f55` |
| `generated/training/facility-layout/facility_layout_check.json` | 243,131 | `9531b1d5b699fd0a81216c03c1d0835bc69dae9837005b0d58263443663458fe` | `9531b1d5b699fd0a81216c03c1d0835bc69dae9837005b0d58263443663458fe` |
| `generated/training/racing-bike/racing_bike_process_map_working_draft.json` | 1,066 | `5533e00f3801e34577fec72ffcb2aff67e90817c2efd1ce079dc38a29780f000` | `5533e00f3801e34577fec72ffcb2aff67e90817c2efd1ce079dc38a29780f000` |
| `generated/training/racing-bike/racing_bike_product_structure.json` | 39,662 | `d11870dba11af3d10183b9ecdcce7f5e4206a600d013e84359b7bfdea3490da1` | `d11870dba11af3d10183b9ecdcce7f5e4206a600d013e84359b7bfdea3490da1` |
| `generated/training/racing-bike/racing_bike_unique_items.json` | 29,781 | `a8ee41579fe4844a09b7d01caae5f556d5d494fc1b9a30a7b220a0552537bd30` | `a8ee41579fe4844a09b7d01caae5f556d5d494fc1b9a30a7b220a0552537bd30` |
| `generated/training/racing-bike/racing_bike_subassembly_visuals.json` | 11,901 | `5d8e6e27418d7639ceddadacfd54a77fe335d5db97a577a7599bdb0dc446eaee` | `5d8e6e27418d7639ceddadacfd54a77fe335d5db97a577a7599bdb0dc446eaee` |
| `generated/training/racing-bike/racing_bike_guided_build_plan.json` | 61,779 | `c94642594918462316758d01f81c6f86cb33ddc6cfe426ded351dc991c9a6bb3` | `c94642594918462316758d01f81c6f86cb33ddc6cfe426ded351dc991c9a6bb3` |
| `generated/training/racing-bike/part_colored_iso_manifest.json` | 1,430 | `a8485716c4a07dc4267ef361ade9ad2f1357f463aefb9e60b5b83290fe02a313` | `a8485716c4a07dc4267ef361ade9ad2f1357f463aefb9e60b5b83290fe02a313` |
| `generated/training/racing-bike/process_knowledge/front-wheel-process-demo.json` | 11,265 | `f7b9dbb7e58ba4e9eaf44556532c91ca726786b07ec1cb81fd77309db5d4bbbf` | `f7b9dbb7e58ba4e9eaf44556532c91ca726786b07ec1cb81fd77309db5d4bbbf` |
| `generated/training/racing-bike/subassembly_extracts/front_wheel_brake.json` | 137,223 | `77a5e9d7ee73260a994f4c60c7fbcecf01b2feac5fc10cb911deca62ee771fcf` | `77a5e9d7ee73260a994f4c60c7fbcecf01b2feac5fc10cb911deca62ee771fcf` |

Missing both before and after:

```text
generated/training/racing-bike/racing_bike_process_map_approved_baseline.json
demo_library/assemblies/racing-bike_assembly.json
400S_Sorted_Library/assemblies/racing-bike_assembly.json
```

Recursive tree manifests protect assets checked only for existence by the
Legacy Training suite. The digest input for each sorted file is:

```text
relative POSIX path + NUL + decimal byte size + NUL + raw 32-byte file digest + LF
```

| Tree | Files | Bytes | SHA-256 before | SHA-256 after |
| --- | ---: | ---: | --- | --- |
| `generated/training/facility-layout` | 4 | 327,914,389 | `9fda3c22fd8ab67a462071e0b820fdd80e35be6c9f45ca5f8e817f28d0132e12` | `9fda3c22fd8ab67a462071e0b820fdd80e35be6c9f45ca5f8e817f28d0132e12` |
| `generated/training/racing-bike` | 257 | 45,139,815 | `6e22bbc11575d875b555439bec332c0da51631d9d13208202faac7b6c265e0a3` | `6e22bbc11575d875b555439bec332c0da51631d9d13208202faac7b6c265e0a3` |

## P0 final integration addendum

Final verification window: 2026-07-28 20:56-21:11 UTC-05:00

P0 result: **EXIT GATE MET**

The repository-wide baseline remains intentionally classified as not globally
green because the same 14 stale agent-registry assertions and eight legacy
training fixture failures reproduced. Neither failure set intersects a P0
file, and the counts and failure names are byte-for-byte consistent with the
initial baseline recorded above.

### P0-specific gates

| Gate | Result |
| --- | --- |
| Contract, authority, migration, asset, and geometry tests | 17/17 pass |
| Renderer, dependency, benchmark, and instance tests | 6/6 pass |
| Combined P0 suite | 23/23 pass |
| Local Three r184 offline smoke | 12/12 pass |
| Real rack instancing browser smoke | 16/16 pass |
| P0 JSON parse | 33/33 pass |
| Python compilation | Pass |
| JavaScript syntax | Pass |
| Scoped `git diff --check` | Pass |

### Integrated frozen bars

| Bar | Final result | Baseline comparison |
| --- | --- | --- |
| Facility endpoint/current-data probe | 22/22 pass | Unchanged |
| Facility/Plant mode contract | 28/28 pass | Unchanged |
| Complete current Process Map Python suite | 216/216 pass | Unchanged |
| Process Map editor Node harness | 83/83 pass | Unchanged |
| Process Map spatial Node harness | 44/44 pass | Unchanged |
| Floating-surface Node harness | 14/14 pass | Unchanged |
| Core Process Map + Assembly Knowledge schemas | 31/31 pass | Unchanged |
| Core agent tests | 60 pass / 14 fail | Same pre-existing stale-catalog failures |
| Legacy Training real-data suite | 15 pass / 8 fail | Same pre-existing fixture failures |

Provider keys were blank for every server/agent test. Test telemetry and temp
output were isolated under the system temp directory. No paid model call was
made.

### Source integrity after final verification

| Artifact | Bytes | Final SHA-256 |
| --- | ---: | --- |
| `facility_layout_semantic.json` | 99,910 | `269ed9e33c32f7937221b4cbf26c52ea61b529999c96c16f38b4cd5d02f6077d` |
| `generated/training/facility-layout/Assem3_colored.glb` | 327,184,996 | `da2be02acea430027324857e58db3ddee81713dcf9b54e38d45b830671898ce2` |
| `generated/training/facility-layout/facility_layout.json` | 243,131 | `c07f8bd574ea151d1a6e2060e8716ec96db1279bf11b6e0769a03e737e0b7c0a` |
| `generated/training/facility-layout/facility_layout_attach_check.json` | 243,131 | `30dbc74ad6cb2ea721607794bae467b6c2d5a6f3fd1a5e1b9154c035a2aa2f55` |
| `generated/training/facility-layout/facility_layout_check.json` | 243,131 | `9531b1d5b699fd0a81216c03c1d0835bc69dae9837005b0d58263443663458fe` |

All match their initial baseline hashes.

### Closed technical choices

- Canonical layout coordinates are finite right-handed meters with `+Y` up
  and X/Z as the floor plane. Camera transforms are never persisted geometry.
- WebGL/Three.js is the primary renderer; virtualized SVG is the degraded
  fallback; measured full-redraw Canvas 2D is rejected as primary.
- Exact Three r184 files are locally pinned with package provenance, hashes,
  and retained MIT license. No decoder dependency is adopted in P0.
- The official local GLTFLoader works with browser networking denied and
  rejects corrupt GLB input.
- Two private assets are visual-ready and placement-ready from reviewed
  standalone SolidWorks extraction, while planning and public readiness remain
  independently blocked.
- One real 8x16 rack prototype renders six stable occurrences through 10
  instance groups instead of 60 independent mesh draws. Instance-aware
  raycasting resolves back to stable placement identity.
- Semantic v0.2 migration preserves its complete parsed source tree.
  Unsupported newer schemas are read-only and byte-preserving.

P0 adds no visible editor behavior and no production write path. P1 may begin
only under its transaction-kernel scope; later phases still own production
renderer migration, catalog publication, safety authority, complete warehouse
benchmarks, and minimum-hardware release gates.

## Exact Commands

All commands ran from:

```powershell
Set-Location '<workspace>\AI-Drawing-Inspector'
```

Common controls applied to Python test/probe commands:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:ANTHROPIC_API_KEY=''
$env:OPENAI_API_KEY=''
```

### Facility endpoint/current-data probe

The final accepted 22-check command was:

```powershell
$env:INSPECTORPRO_METRICS_DB="$env:TEMP\InspectorPro-P0-facility-final.sqlite"
$sw=[Diagnostics.Stopwatch]::StartNew()
@'
import hashlib, json
from pathlib import Path
from fastapi.testclient import TestClient
import server
c=TestClient(server.app)
sr=c.get('/api/training/facility-layout/semantic'); sp=sr.json(); s=sp.get('semantic',{})
rows=s.get('rackRows',[]); assets=s.get('materialHandlingAssets',[])
cf=s.get('layoutMap',{}).get('coordinateFrame',{}); val=cf.get('validation',{}); gc=cf.get('glbAsset',{}); gp=Path(gc.get('path','__missing__'))
h=hashlib.sha256()
if gp.is_file():
    with gp.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
cap_body={'row':'upper middle','length':24,'depth':18,'height':12,'clearance':1,'unit':'in'}
cr=c.post('/api/training/facility-layout/capacity',json=cap_body); cap=cr.json().get('result',{})
car=c.post('/api/training/facility-layout/capacity',json={**cap_body,'row':None}); capa=car.json().get('result',{})
ciu=c.post('/api/training/facility-layout/capacity',json={**cap_body,'unit':'yard'})
rr=c.post('/api/training/facility-layout/route',json={'start':'forklift 1','end':'upper middle'}); route=rr.json().get('result',{})
riu=c.post('/api/training/facility-layout/route',json={'start':'missing endpoint','end':'upper middle'})
ar=c.get('/api/training/facility-layout/layout-analysis'); analysis=ar.json().get('result',{})
checks={'semantic_http_200':sr.status_code==200,'semantic_success':sp.get('success') is True,'semantic_schema_v0_2':s.get('schemaVersion')=='facility-layout-semantic-v0.2','semantic_five_rows':len(rows)==5,'semantic_twenty_four_racks':sum(int(x.get('rackCount',0)) for x in rows)==24,'semantic_five_material_assets':len(assets)==5,'semantic_glb_exists':gp.is_file(),'semantic_glb_size_matches':gp.is_file() and gp.stat().st_size==gc.get('byteLength'),'semantic_glb_hash_matches':gp.is_file() and h.hexdigest()==gc.get('sha256'),'semantic_alignment_24_points':val.get('rackCorrespondences')==24,'semantic_alignment_residual_demo_only':val.get('maxResidualMeters')==0.06131,'capacity_http_200':cr.status_code==200,'capacity_upper_middle_392':cap.get('estimatedTotalBoxes')==392,'capacity_all_http_200':car.status_code==200,'capacity_all_rows_2618':capa.get('estimatedTotalBoxes')==2618,'capacity_invalid_unit_400':ciu.status_code==400,'route_http_200':rr.status_code==200,'route_positive_obstacle_free':route.get('ok') is True and route.get('distanceMeters',0)>0 and not route.get('obstacleViolations'),'route_unknown_endpoint_400':riu.status_code==400,'layout_analysis_http_200':ar.status_code==200,'layout_analysis_ok':analysis.get('ok') is True,'layout_analysis_reduces_distance':analysis.get('baselineTotalMeters',0)>analysis.get('withEastCrossAisleTotalMeters',0) and analysis.get('reductionPercent',0)>0}
for name,ok in checks.items(): print(('PASS' if ok else 'FAIL')+'\t'+name)
print('FACILITY_SUMMARY='+json.dumps({'passed':sum(checks.values()),'failed':len(checks)-sum(checks.values()),'routeDistanceMeters':route.get('distanceMeters'),'routeEtaText':route.get('etaText'),'baselineTotalMeters':analysis.get('baselineTotalMeters'),'withEastCrossAisleTotalMeters':analysis.get('withEastCrossAisleTotalMeters'),'reductionPercent':analysis.get('reductionPercent')},sort_keys=True))
raise SystemExit(0 if all(checks.values()) else 1)
'@ | python -u -
$code=$LASTEXITCODE
$sw.Stop()
"ELAPSED_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds,3))"
exit $code
```

### Pytest bars

```powershell
$env:INSPECTORPRO_METRICS_DB="$env:TEMP\InspectorPro-P0-process-map-metrics.sqlite"
$sw=[Diagnostics.Stopwatch]::StartNew()
python -m pytest -q -ra -p no:cacheprovider --basetemp "$env:TEMP\InspectorPro-P0-process-map-backend" tests/test_process_map_analysis.py tests/test_process_map_assembly_catalog.py tests/test_process_map_builder.py tests/test_process_map_demo_metadata.py tests/test_process_map_endpoints.py tests/test_process_map_identity.py tests/test_process_map_schema_v3.py tests/test_process_map_semantic_plan.py tests/test_process_map_spatial.py tests/test_process_map_suggestions.py tests/test_process_map_templates.py tests/test_process_map_validate.py tests/test_process_map_visual_validation.py
$code=$LASTEXITCODE; $sw.Stop(); "ELAPSED_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds,3))"; exit $code
```

```powershell
$env:INSPECTORPRO_METRICS_DB="$env:TEMP\InspectorPro-P0-training-metrics.sqlite"
$sw=[Diagnostics.Stopwatch]::StartNew()
python -m pytest -q -ra -p no:cacheprovider --basetemp "$env:TEMP\InspectorPro-P0-training-data" tests/test_training_process_map.py
$code=$LASTEXITCODE; $sw.Stop(); "ELAPSED_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds,3))"; exit $code
```

```powershell
$env:INSPECTORPRO_METRICS_DB="$env:TEMP\InspectorPro-P0-schema-metrics.sqlite"
$sw=[Diagnostics.Stopwatch]::StartNew()
python -m pytest -q -ra -p no:cacheprovider --basetemp "$env:TEMP\InspectorPro-P0-core-schema-only" tests/test_process_map_schema_v3.py tests/test_assembly_knowledge_schema.py
$code=$LASTEXITCODE; $sw.Stop(); "ELAPSED_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds,3))"; exit $code
```

```powershell
$env:INSPECTORPRO_METRICS_DB="$env:TEMP\InspectorPro-P0-agent-only-metrics.sqlite"
$sw=[Diagnostics.Stopwatch]::StartNew()
python -m pytest -q -ra --tb=no -p no:cacheprovider --basetemp "$env:TEMP\InspectorPro-P0-core-agent-only" tests/test_agent_chat_streaming_backend.py tests/test_agent_response_encoding.py tests/test_agent_skill_phase3.py tests/test_agent_skill_routing.py tests/test_agent_skill_runtime.py tests/test_agent_tool_policy.py tests/test_agent_workflow_state.py
$code=$LASTEXITCODE; $sw.Stop(); "ELAPSED_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds,3))"; exit $code
```

```powershell
$env:INSPECTORPRO_METRICS_DB="$env:TEMP\InspectorPro-P0-mode-metrics.sqlite"
$sw=[Diagnostics.Stopwatch]::StartNew()
python -m pytest -q -ra -p no:cacheprovider --basetemp "$env:TEMP\InspectorPro-P0-mode-contract" tests/test_mode_contract.py
$code=$LASTEXITCODE; $sw.Stop(); "ELAPSED_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds,3))"; exit $code
```

The initial combined schema/agent diagnostic was:

```powershell
$env:INSPECTORPRO_METRICS_DB="$env:TEMP\InspectorPro-P0-agent-metrics.sqlite"
$sw=[Diagnostics.Stopwatch]::StartNew()
python -m pytest -q -ra -p no:cacheprovider --basetemp "$env:TEMP\InspectorPro-P0-core-schema-agent" tests/test_process_map_schema_v3.py tests/test_assembly_knowledge_schema.py tests/test_agent_chat_streaming_backend.py tests/test_agent_response_encoding.py tests/test_agent_skill_phase3.py tests/test_agent_skill_routing.py tests/test_agent_skill_runtime.py tests/test_agent_tool_policy.py tests/test_agent_workflow_state.py
$code=$LASTEXITCODE; $sw.Stop(); "ELAPSED_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds,3))"; exit $code
```

### Node functional bars

```powershell
$sw=[Diagnostics.Stopwatch]::StartNew(); node tests/test_process_map_editor.js; $code=$LASTEXITCODE; $sw.Stop(); "ELAPSED_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds,3))"; exit $code
```

```powershell
$sw=[Diagnostics.Stopwatch]::StartNew(); node tests/test_process_map_spatial.js; $code=$LASTEXITCODE; $sw.Stop(); "ELAPSED_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds,3))"; exit $code
```

```powershell
$sw=[Diagnostics.Stopwatch]::StartNew(); node tests/test_floating_surface.js; $code=$LASTEXITCODE; $sw.Stop(); "ELAPSED_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds,3))"; exit $code
```

### Python syntax

```powershell
$sw=[Diagnostics.Stopwatch]::StartNew()
@'
import ast
import tokenize
from pathlib import Path
roots = [Path('ai_inspector'), Path('tools'), Path('tests')]
paths = [Path('server.py')]
for root in roots:
    paths.extend(root.rglob('*.py'))
paths = sorted({path for path in paths if path.is_file()}, key=lambda p: p.as_posix())
failures = []
for path in paths:
    try:
        with tokenize.open(path) as handle:
            source = handle.read()
        ast.parse(source, filename=str(path))
    except Exception as exc:
        failures.append((path.as_posix(), f'{type(exc).__name__}: {exc}'))
for path, error in failures:
    print(f'FAIL\t{path}\t{error}')
print(f'PYTHON_AST_SUMMARY\tfiles={len(paths)}\tpassed={len(paths)-len(failures)}\tfailed={len(failures)}')
raise SystemExit(1 if failures else 0)
'@ | python -u -
$code=$LASTEXITCODE; $sw.Stop(); "ELAPSED_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds,3))"; exit $code
```

### JSON and YAML syntax

```powershell
$sw=[Diagnostics.Stopwatch]::StartNew()
@'
import json
from pathlib import Path
import yaml
json_paths = sorted(list(Path('static/contracts').glob('*.json')) + list(Path('ai_inspector/agent_skills/schemas').glob('*.json')) + list(Path('ai_inspector/agent_workflows/schemas').glob('*.json')), key=lambda p: p.as_posix())
yaml_paths = sorted(list(Path('ai_inspector/agent_skills').glob('*/manifest.yaml')) + list(Path('ai_inspector/agent_skills').glob('*/contract.yaml')) + list(Path('ai_inspector/agent_workflows').glob('*/manifest.yaml')), key=lambda p: p.as_posix())
failures = []
for path in json_paths:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('top level is not an object')
    except Exception as exc:
        failures.append((path.as_posix(), f'{type(exc).__name__}: {exc}'))
for path in yaml_paths:
    try:
        value = yaml.safe_load(path.read_text(encoding='ascii'))
        if not isinstance(value, dict):
            raise ValueError('top level is not a mapping')
    except Exception as exc:
        failures.append((path.as_posix(), f'{type(exc).__name__}: {exc}'))
for path, error in failures:
    print(f'FAIL\t{path}\t{error}')
print(f'CONTRACT_SYNTAX_SUMMARY\tjson_documents={len(json_paths)}\tyaml_documents={len(yaml_paths)}\tpassed={len(json_paths)+len(yaml_paths)-len(failures)}\tfailed={len(failures)}')
raise SystemExit(1 if failures else 0)
'@ | python -u -
$code=$LASTEXITCODE; $sw.Stop(); "ELAPSED_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds,3))"; exit $code
```

### JavaScript syntax

```powershell
$sw=[Diagnostics.Stopwatch]::StartNew()
@'
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const standalone = [];
for (const dir of ['static', 'tests']) {
  for (const name of fs.readdirSync(dir).sort()) {
    const full = path.join(dir, name);
    if (fs.statSync(full).isFile() && name.endsWith('.js')) standalone.push(full);
  }
}
const failures = [];
for (const file of standalone) {
  try {
    new vm.Script(fs.readFileSync(file, 'utf8'), { filename: file });
  } catch (error) {
    failures.push([file, String(error && error.message || error)]);
  }
}
const html = fs.readFileSync(path.join('static', 'index.html'), 'utf8');
const inline = [];
const pattern = /<script([^>]*)>([\s\S]*?)<\/script>/gi;
let match;
while ((match = pattern.exec(html)) !== null) {
  if (!/\bsrc\s*=/.test(match[1]) && match[2].trim()) inline.push(match[2]);
}
inline.forEach((source, index) => {
  try {
    new vm.Script(source, { filename: `static/index.html#inline-${index + 1}` });
  } catch (error) {
    failures.push([`static/index.html#inline-${index + 1}`, String(error && error.message || error)]);
  }
});
for (const [file, error] of failures) console.log(`FAIL\t${file}\t${error}`);
console.log(`JAVASCRIPT_SYNTAX_SUMMARY\tstandalone=${standalone.length}\tinline=${inline.length}\tpassed=${standalone.length + inline.length - failures.length}\tfailed=${failures.length}`);
process.exitCode = failures.length ? 1 : 0;
'@ | node -
$code=$LASTEXITCODE; $sw.Stop(); "ELAPSED_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds,3))"; exit $code
```

### Hash inventory

The before and after commands used the same Python body and differed only in
the printed `HASH_PHASE` label:

```powershell
@'
from hashlib import sha256
from pathlib import Path
DIRECT = [
    Path('facility_layout_semantic.json'),
    Path('generated/training/facility-layout/Assem3_colored.glb'),
    Path('generated/training/facility-layout/facility_layout.json'),
    Path('generated/training/facility-layout/facility_layout_attach_check.json'),
    Path('generated/training/facility-layout/facility_layout_check.json'),
    Path('generated/training/racing-bike/racing_bike_process_map_working_draft.json'),
    Path('generated/training/racing-bike/racing_bike_process_map_approved_baseline.json'),
    Path('generated/training/racing-bike/racing_bike_product_structure.json'),
    Path('generated/training/racing-bike/racing_bike_unique_items.json'),
    Path('generated/training/racing-bike/racing_bike_subassembly_visuals.json'),
    Path('generated/training/racing-bike/racing_bike_guided_build_plan.json'),
    Path('generated/training/racing-bike/part_colored_iso_manifest.json'),
    Path('generated/training/racing-bike/process_knowledge/front-wheel-process-demo.json'),
    Path('generated/training/racing-bike/subassembly_extracts/front_wheel_brake.json'),
]
def file_hash(path):
    digest = sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()
def tree_hash(root):
    files = sorted((p for p in root.rglob('*') if p.is_file()), key=lambda p: p.relative_to(root).as_posix())
    digest = sha256()
    total = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        total += size
        item_hash = file_hash(path)
        digest.update(relative.encode('utf-8'))
        digest.update(b'\0')
        digest.update(str(size).encode('ascii'))
        digest.update(b'\0')
        digest.update(bytes.fromhex(item_hash))
        digest.update(b'\n')
    return len(files), total, digest.hexdigest()
print('HASH_PHASE=before')  # changed to "after" for the post-test run
for path in DIRECT:
    if path.is_file():
        print(f'FILE\t{path.as_posix()}\t{path.stat().st_size}\t{file_hash(path)}')
    else:
        print(f'MISSING\t{path.as_posix()}')
for root in (Path('generated/training/facility-layout'), Path('generated/training/racing-bike')):
    count, total, digest = tree_hash(root)
    print(f'TREE\t{root.as_posix()}\t{count}\t{total}\t{digest}')
'@ | python -
```

## Tests and Checks Not Run

- No paid Sage, Anthropic, OpenAI, shadow-routing, or model-quality evaluation.
- No live Uvicorn server, external HTTP client, or network probe. Facility
  routes were exercised in-process with FastAPI `TestClient`.
- No Process Map Playwright smoke (`tests/smoke_process_flow_editor.py`).
  It is a live browser/write workflow and was excluded to avoid touching a
  real generated Process Map asset.
- No full browser screenshot, canvas-pixel, WebGL, Three.js loading, GPU,
  accessibility, lifecycle, or visual matrix.
- The 327 MB Facility GLB was streamed only for SHA-256. It was not decoded or
  rendered.
- No Process Map or Facility performance benchmark.
- No newly appearing Facility renderer benchmark or fixture-driven spike.
- No full Assembly Knowledge suite; only its core schema tests were selected.
- No complete repository-wide pytest run.
- No SolidWorks process, extractor execution, C# build, machine-library
  normalization, or CAD mutation.
- No generated-asset writer, bootstrapper, capture tool, or preparation tool.
- No npm install, package download, or other dependency change.
- Draft 2020-12 JSON Schema metaschema validation was attempted but not run:
  importing `jsonschema.validators` failed with
  `ModuleNotFoundError: No module named 'jsonschema'`. JSON parsing and the
  existing executable schema tests did run and pass.

## Harness Setup Notes

- The first hash script assumed the approved racing-bike baseline existed and
  exited on `FileNotFoundError`. The accepted before/after script records
  absent files as `MISSING`.
- The first Facility probe attempt reached a 120-second outer timeout before
  buffered output returned. A diagnostic rerun showed server import itself
  completed in 3.568 seconds.
- A subsequent Facility diagnostic used the wrong semantic nesting path and
  wrong layout-analysis shape for five harness assertions. Those were harness
  defects, not endpoint defects. The corrected, final 22-check probe above is
  the recorded Facility bar.
- The `jsonschema` metaschema attempt stopped at import and is listed as not
  run rather than as a contract failure.
