# MB5b - reference files (backend)

## CHANGED

- Added `reference_files.py` and `reference_file_routes.py`: site-scoped `rf-` intake, streamed upload admission, content-addressed metadata-free pages, read routes, quotas, seven-day sweep, draft pins, minimal registration provenance, and a per-draft comparison-view cache. The PDF capability is off by default.
- Added `reference_worker.py` and `model_reference_runner.py`; the private model-import worker now has a contained `reference` task. Images are checked by content, reoriented, bounded and re-encoded. Opt-in PDF reading is confined to the worker and its trusted dependency root. The host checks every returned page and hash.
- Kept reference IDs outside frozen model recipes and identity. Build and revise pin them during the job, then retain up to three in a site sidecar. `get_model_recipe` and subsequent revisions overlay that sidecar. Registration writes only reference ID, kind, source SHA-256 and page to site provenance, then releases pins. Identical portable builds with different references keep one draft and asset identity, including across a host restart and repeated registration.
- Added `inspect_reference_file` and `compareWith` to Sage's host hooks and gateway; updated the numbered edit playbook and pinned tool inventories. The comparison is one 1536 x 768 PNG, outside the bundle and identity.
- Added discriminated reference-file chat attachments to `server.py`, bounded untrusted chat descriptions, and memory identity normalization for mixed and attachment-only turns. Empty attachment lists preserve the existing hash. No static files changed.
- Added reference, transport, worker, quota, scope, permission, PDF, comparison, and provenance tests. Updated the existing isolated server AST fixture and pinned tool tests.

## TESTS RUN

Each pytest file ran in its own hidden venv process through `pythonw.exe tools/run_hidden.pyw .../python.exe -m pytest <file> -q -p no:cacheprovider --basetemp=<fresh TEMP folder>`; temporary folders were removed after each run. Later broad runs used `--tb=short` and included Node on `PATH`. No tests ran concurrently.

- MB5b and direct compatibility: `test_model_builder_reference_files.py` 13 passed; `test_model_import_chat_transport.py` 67 passed, 1 skipped; `test_model_builder_registration.py` 19 passed; `test_model_builder_sage_tools.py` 10 passed; `test_codex_readonly_pilot.py` 66 passed; `test_codex_mcp_pictures.py` 3 passed; `test_sage_shape_tools.py` 26 passed; `test_model_import_registration.py` 24 passed; `test_model_import_sage_tools.py` 41 passed; `test_codex_assisted_tools.py` 13 passed; `test_facility_layout_api.py` 10 passed; `test_facility_layout_agent_runtime.py` 19 passed; `test_codex_gateway_turn.py` 36 passed; `test_codex_mcp_schema_types.py` 5 passed.
- Frozen drafts and shared worker: `test_model_builder_draft_store.py` 30 passed; `test_model_builder_draft_worker.py` 5 passed; `test_model_builder_bundle.py` 19 passed; `test_model_builder_identity.py` 10 passed; `test_model_builder_build.py` 35 passed; `test_model_builder_schema.py` 12 passed; `test_model_builder_import_compat.py` 20 passed; `test_model_builder_composition.py` 17 passed; `test_model_builder_composition_host.py` 29 passed; `test_model_builder_anchor.py` 7 passed; `test_model_import_worker.py` 27 passed, 2 skipped; `test_model_builder_worker.py` 22 passed; `test_model_builder_worker_boundary.py` 10 passed; `test_model_builder_protocol.py` 13 passed, 1 skipped; `test_model_import_reader.py` 112 passed; `test_model_import_prepare.py` 21 passed; `test_model_import_inspection.py` 14 passed; `test_model_import_sage_integration.py` 7 passed; `test_model_import_catalog.py` 43 passed; `test_model_import_recipe.py` 137 passed; `test_model_builder_cookbook_recipes.py` 30 passed.
- Other direct importers passed: `test_facility_layout_host.py` 16; `test_facility_layout_proposals.py` 17; `test_facility_operation_proposals.py` 37; `test_authored_assets_live.py` 7; `test_codex_assembly_appearance_tools.py` 11; `test_codex_authoring_reads.py` 12; `test_codex_engineering_tools.py` 72; `test_codex_documentation_tools.py` 62; `test_codex_new_placement_finishes.py` 10; `test_codex_part_tools.py` 8; `test_facility_asset_orientation.py` 25; `test_facility_ceilings.py` 37; `test_facility_emergency_maps.py` 10; `test_facility_generation_admission.py` 63; `test_facility_generation_composition.py` 27; `test_facility_gap.py` 8; `test_facility_layout_construction_service.py` 12 (after adding Node to test `PATH`); `test_facility_layout_facility_planning.py` 7; `test_facility_layout_full_factory.py` 9; `test_facility_layout_facility_program.py` 5; `test_facility_layout_generation_coordinator.py` 22; `test_facility_layout_p11_identity.py` 21; `test_facility_layout_program_execution.py` 11; `test_facility_layout_spatial_integration.py` 15; `test_facility_light_positions.py` 23; `test_facility_light_coverage.py` 22; `test_facility_light_models.py` 11; `test_facility_site_references.py` 7; `test_facility_site_reference_fit.py` 5; `test_facility_parking_review.py` 21; `test_facility_wall_attachments.py` 35; `test_facility_workstation_review.py` 16; `test_sage_shots.py` 39; `test_sage_position_tools.py` 34 passed, 2 skipped; `test_sage_pattern_tools.py` 84 passed, 22 skipped; `test_sage_views.py` 23; `test_sage_stack_tools.py` 40 passed, 2 skipped; `test_shape_families.py` 15; `test_private_asset_footprints.py` 12; `test_private_gym.py` 1 passed, 7 skipped; `test_private_gym_fitness_centre.py` 8; `test_private_gym_calisthenics.py` 5. `test_facility_generation_documents_live.py` skipped 2.
- Broad importer files with unresolved sandbox failures: `test_codex_floor_plan_tools.py` 10 failed, 2 passed (first failure: `ezdxf` unavailable); `test_memory_turn_lifecycle.py` 1 failed, 17 passed (missing fixture); `test_codex_packaging_pilot.py` 3 failed, 7 passed; `test_codex_progress_steps.py` 1 failed, 9 passed (exact `static/index.html` text assertion); `test_facility_layout_agent_integration.py` 2 failed, 200 passed (`facility_design_write_disabled` in this environment); `test_facility_layout_design_loop_contracts.py` 43 failed, 1 passed (missing frozen fixture); `test_facility_layout_navigation_nav0.py` 4 failed, 2 passed, 3 errors; `test_facility_layout_navigation_nav8.py` 2 failed, 14 passed; `test_facility_layout_reference_finished_goods.py` 3 errors; `test_facility_layout_reference_benchmark.py` 1 failed, 1 passed; `test_facility_layout_reference_receiving.py` 3 errors; `test_facility_layout_planning_generation.py` 1 failed, 2 passed; `test_facility_layout_synthetic_planning_corpus.py` 6 failed, 2 passed; `test_facility_site_steps.py` 1 failed, 20 passed; `test_facility_site_paint.py` 1 failed, 5 passed; `test_facility_site_reference_cases.py` 4 failed, 2 passed; `test_mmle_facility_planning_package.py` 3 failed; `test_assembly_dimensions.py` 1 failed, 20 passed; `test_assembly_faces.py` 1 failed, 6 passed; `test_assembly_signs_scenes.py` 2 failed, 4 passed. `test_private_gym_detail.py` could not collect because `trimesh` is unavailable. The MB5b-focused and shared import/builder files above pass; these broader failures need comparison with the user's outside-sandbox baseline.
- `git diff --check` passed. `server.py` still has its UTF-8 BOM; new files use LF. No static files changed.

## NOT RUN

- Browser harnesses and the whole suite, per the brief. No live provider or network checks.

## DEVIATIONS

- The named `briefs/mb5b-references.md` is absent from this worktree; I followed the complete eight-item MB5b brief in the conversation.
- PDF enablement remains an injectable backend capability only, defaulting off. No production setting exposes it pending the PyMuPDF licence decision. Opt-in PDF behavior was exercised in the test venv.

## OPEN QUESTIONS

- The PyMuPDF licence decision remains open. Until settled, PDF uploads return the requested screenshot guidance.

## CLAUDE REVIEW AND VERIFICATION (2026-11-17)

The first run was stopped from outside at about 02:50 (the host was low on memory). On the user's request it was
resumed in the same Codex session, from the partial work left in the worktree.

Reviewed: the store, routes, worker, runner, builder/host wiring, chat attachments, memory identity and the
playbook. Sound:
- Reference ids stay out of the frozen recipe, identity and bundle (recipe.json is the portable recipe, and the
  site sidecar holds the ids).
- Scope checks go through the model-import authorization; a foreign or expired id gives 404.
- The format is sniffed from content in the host, and the worker checks it again. Animated images, GIF and over 40
  MP are refused before decoding, EXIF orientation is applied, and re-encoding drops all metadata.
- Pins are released on registration and on supersession.
- Upload abort is shielded, and a refusal discards the record.
- The discriminated chat union, and the unchanged request hash when there are no attachments.

Fixes (mine):
1. Phone photos were refused, and Sage could not see larger pictures.
   - The worker stored every image as an RGBA PNG at up to 2048 px, but the page limit is 4 MB. A synthetic
     phone-style photo (4032 x 3024 JPEG, 1.7-3.6 MB) came out at 4.9-6.0 MB, so every such photo was refused
     at intake.
   - Separately, inspect_reference_file returned the stored page as the tool picture. Any tool picture over
     model_import_tools.PICTURE_BYTES (1.5 MB) fails, so even a stored 1080p photo (2.4-3.8 MB) could not be shown
     to Sage.
   - Now the worker drops alpha when nothing is transparent and shrinks the long side 15 % a step until the PNG
     fits 4 MB. A 4032 x 3024 photo is stored at 1741 x 1306, and 1080p stays full size.
   - ReferenceStore.sage_page fits Sage's copy under 1.5 MB (RGB, at most 1600 px, smaller if needed) and reports
     shownWidth/shownHeight. The stored page and the browser route keep full size.
   - New test: test_a_phone_sized_photo_is_stored_within_its_page_limit_and_sage_can_see_it. Its photo made a
     5.8 MB page before the fix; Sage now gets 983 x 737 at 1.15 MB from a noisy worst case.
2. The sweep now also drops the per-draft page-choice files (draft-pages) of drafts that no longer exist. New test.

Tests I re-ran outside the sandbox, one file at a time:
- references 15; chat_transport 67 + 1 skipped; builder registration 19; sage_tools 10;
- readonly_pilot 66; mcp_pictures 3; sage_shape_tools 26; floor_plan_tools 12 (all pass outside the sandbox);
- model_import registration 24, sage_tools 41, sage_integration 7; facility_layout_api 10; gateway_turn 36;
- draft_store 30, draft_worker 5; import worker 27 + 2 skipped; builder worker 22, worker_boundary 10;
- cookbook 30.

test_codex_progress_steps (baseline) and test_memory_turn_lifecycle (missing fixture file; it fails the same way at
e949f41 without MB5b) are not caused by MB5b.

Codex's DEVIATIONS note about a missing brief file: the brief lives in the runner folder, outside the worktree.
Nothing was missed. The PyMuPDF licence question stays open for the user; PDF reading is off by default.
