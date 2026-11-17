# MB5c report

## CHANGED

- Added `measure_facility_gap` as a revision-bound read tool. It measures a rectangle between typed column, wall, marking, placement, or zone edges using the saved layout and shell geometry, reports height limits and positive-area obstructions beyond a 5 mm inset, and refuses ambiguous or unsupported geometry. Wired its schema, dispatch, progress label, and pinned inventories.
- Added server-side `anchorInclude` resolution for `replace_asset` in both preview and apply. The host validates the installed built bundle and the old placement's current artifact revision and SHA-256, requires an anchorable yaw-only frame and an unscaled yaw-only placement, computes the mirrored include pose, transfers mapped part finishes, and reports lost finishes and equipment decals. The Sage proposal summary exposes that loss report before review. Registration now returns `includeFrames` for built assets.
- Added the measuring and anchored-tag guidance to the existing ten-step edit playbook. Restricted `analyze_facility_fit` guidance to zone targets.
- Added `tests/test_facility_gap.py` and `tests/test_model_builder_anchor.py`; updated read-tool inventories and one model-import privacy assertion to exclude the already volatile `turnRemaining` field.

## TESTS RUN

Each Python run used `C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/pythonw.exe tools/run_hidden.pyw C:/Users/might/Documents/InspectorPro-CopilotTest/venv/Scripts/python.exe -m pytest <one file> -q -p no:cacheprovider --basetemp=<fresh TEMP folder>`, with `PYTHONUSERBASE=C:\Users\might\AppData\Roaming\Python`. Runs were sequential; each TEMP folder was removed afterward.

- New tests: `test_facility_gap.py` 7 passed; `test_model_builder_anchor.py` 7 passed.
- Builder, import, and Sage boundaries: `test_model_builder_registration.py` 19 passed; `test_model_builder_sage_tools.py` 10 passed; `test_model_import_registration.py` 24 passed; `test_model_import_sage_tools.py` 41 passed; `test_model_import_sage_integration.py` 7 passed; `test_model_import_chat_transport.py` 62 passed, 1 skipped; `test_codex_readonly_pilot.py` 66 passed; `test_codex_assisted_tools.py` 13 passed; `test_codex_gateway_turn.py` 36 passed; `test_codex_authoring_schema.py` 14 passed; `test_codex_authoring_reads.py` 12 passed; `test_codex_mcp_schema_types.py` 5 passed; `test_codex_mcp_pictures.py` 3 passed; `test_sage_shape_tools.py` 26 passed; `test_sage_views.py` 23 passed; `test_sage_pattern_tools.py` 84 passed, 22 skipped; `test_sage_position_tools.py` 34 passed, 2 skipped; `test_sage_stack_tools.py` 40 passed, 2 skipped.
- Operations and materials: `test_facility_layout_operations.py` 30 passed; `test_facility_operation_proposals.py` 37 passed; `test_facility_replace_asset.py` 6 passed; `test_facility_component_materials.py` 8 passed; `test_codex_new_placement_finishes.py` 10 passed; `test_facility_asset_orientation.py` 25 passed; `test_facility_light_positions.py` 23 passed. `test_codex_component_proposals.py` had 15 skips.
- Other direct importers of changed modules passed: `test_codex_assembly_appearance_tools.py`, `test_codex_chat_http_boundary.py`, `test_codex_documentation_tools.py`, `test_codex_public_research.py`, `test_codex_engineering_tools.py`, `test_codex_facility_authoring.py` (5 passed, 25 skipped), `test_codex_part_tools.py`, `test_codex_site_tools.py`, `test_facility_ceilings.py`, `test_facility_columns.py`, `test_facility_emergency_maps.py`, `test_facility_decals.py`, `test_facility_appearance.py`, `test_facility_appearance_library.py`, `test_facility_floor_paths.py`, `test_facility_floor_surfaces.py`, `test_facility_ground.py`, `test_facility_interior_walls.py`, `test_facility_perimeter_walls.py`, `test_facility_layout_api.py`, `test_facility_layout_asset_placement.py`, `test_facility_layout_cell_composition.py`, `test_facility_layout_cell_replication.py`, `test_facility_layout_circulation.py`, `test_facility_layout_facility_planning.py`, `test_facility_layout_full_factory.py`, `test_facility_layout_spatial.py`, `test_facility_layout_service.py`, `test_facility_targeted_collection_operations.py`, `test_facility_place_asset_array.py`, `test_facility_site_reference_fit.py`, `test_facility_layout_navigation_nav2.py`, `test_facility_layout_subdivisions.py`, `test_facility_layout_planner.py`, `test_facility_layout_program_execution.py`, `test_facility_layout_workflow_packages.py`, `test_facility_layout_semantic_model.py`, `test_facility_generation_draft.py`, `test_facility_generation_requirements.py`, `test_facility_light_coverage.py`, `test_facility_light_models.py`, `test_facility_site_areas.py`, `test_facility_site_context.py`, `test_facility_site_plan.py`, `test_facility_site_references.py`, `test_facility_site_property.py`, `test_facility_wall_finishes.py`, `test_facility_floor_plan_conversion.py`, `test_facility_layout_generation_coordinator.py`, `test_facility_layout_g1_planner.py`, `test_factory02_open_kitchen.py`, `test_factory02_parking_office.py`, `test_factory02_lunchroom.py`, `test_factory02_kitchen_walls.py`, `test_factory02_gym.py`, `test_facility_generation_admission.py`, `test_facility_generation_composition.py`, `test_facility_layout_agent_runtime.py`, `test_facility_layout_facility_program.py`, `test_facility_layout_host.py`, `test_facility_layout_p11_identity.py`, `test_facility_layout_proposals.py`, and `test_facility_layout_spatial_integration.py`. `test_facility_generation_documents_live.py` had 2 skips.
- `test_codex_floor_plan_tools.py -k the_reads_are_published`: 1 passed, 11 deselected; the full file has the existing isolated DXF reader gap here. `git diff --check` passed. New files have LF endings.
- Other attempted files had failures outside MB5c: `test_codex_progress_steps.py` 1 failed on an unchanged `static/index.html` assertion, 9 passed; `test_facility_layout_kf0_knowledge_foundation.py` 1 failed on its old registry snapshot, 5 passed; `test_facility_layout_agent_integration.py` 2 failed on disabled facility-design writes, 200 passed; `test_facility_plan_pdf.py` 1 failed on expected PDF text, 9 passed; `test_facility_layout_navigation_nav8.py` 2 failed, 14 passed; `test_facility_layout_navigation_nav9.py` 3 failed, 9 passed; `test_facility_layout_reference_generation.py` 3 failed, 1 passed; `test_mmle_facility_planning_package.py` 3 failed. The latter navigation/reference failures report unavailable fixture files. `test_facility_floor_plan_review.py` had 13 `reader_unavailable` failures, 1 passed. `test_facility_layout_navigation_nav0.py` had 4 failed, 2 passed, 3 errors on missing files. `test_facility_layout_construction_service.py` reached a missing Node host dependency and timed out after 11 failures, 1 pass. `test_facility_layout_design_loop_contracts.py` and `test_memory_server_turns.py` timed out in this sandbox.

## NOT RUN

- Browser tests and the whole suite, per request. I did not run every remaining broad host importer (including the private gym and authored asset suites); several require generated private fixtures or external capabilities. The user runs the wider suite outside this sandbox.

## DEVIATIONS

- `fitsWithin` was already normalized and linted in MB1/MB2. It is part of `portable_recipe`, so it remains in build identity. The caller deducts clearances once from measured width/depth and records them; the existing `fit_exceeded` lint compares against the resulting `fitsWithin` dimensions.
- The anchor authority lives in a host resolver called from the service before the pure operation, and it is called again on apply. This keeps the catalog and installed bundle checks out of the pure operation handler.

## OPEN QUESTIONS

- None for MB5c.

## CLAUDE REVIEW AND VERIFICATION (2026-11-17)

I re-ran these outside the sandbox, one file at a time:
- gap 8 (with my addition) and anchor 7;
- builder registration 19, sage_tools 10 and cookbook 29;
- model_import sage_integration 7, chat_transport 62 + 1 skipped and sage_tools 41;
- readonly_pilot 66, assisted_tools 13, floor_plan_tools in full 12, gateway_turn 36;
- sage_shape_tools 26 and sage_views 23;
- layout_operations 30, operation_proposals 37, replace_asset 6 and component_materials 8.

test_codex_progress_steps fails once, and that failure is in the MB0 baseline.

Independent pose check, not using the resolver's own formula (model-builder-night/anchor_check.py, temporary
roots):
- An L-shaped host is included with rotateY 40 and an offset, next to a tag far to one side, so the builder's
  centring shift is not zero.
- It is placed at (4, 0, 4), turned 35 degrees, and replaced with anchorInclude.
- Every host vertex is mapped into the plan the way the app maps it: mirror x once (model_axes), then
  spatial.py's own placement transform.
- Before and after coincide exactly (largest mismatch 0 m), and the y range is unchanged.

The tests in test_model_builder_anchor.py restate the resolver's formula and use an unrotated include, so this
check is the one that proves the sign conventions.

Fixes (mine):
1. measure_facility_gap turned rotated floor markings the wrong way. It built marking rectangles with its own
   formula, x = cx + lx c + lz s, z = cz - lx s + lz c. The app's markings (circulation.py, fit_analysis.py) turn
   the other way. At any angle other than multiples of 90 degrees, a marking was measured mirrored about its own
   centre, so a real obstruction could be missed or a phantom one reported. The tool now uses the app's own
   _floor_marking_polygon, so there is no second geometry source (as the brief required); unusable markings are
   skipped. The unused _box helper is gone. New test: test_a_rotated_marking_turns_the_way_the_app_draws_it.
   It fails with the old formula: an intrusion of 0.0 m2 against the app's 0.0095 m2.
2. Playbook clearance line reworded. It read "Deduct sides twice and front/back once from its width/depth" and now
   reads "width = gap width minus a side clearance at each end, depth = gap depth minus the front and back
   clearances".

No objection to the deviations. fitsWithin stays in the portable recipe (identity), as it was since MB1. The anchor
resolver runs in the service before the pure operation, on preview and again on apply. A caller cannot supply
_anchorResolved; that is refused, and the test covers it.
