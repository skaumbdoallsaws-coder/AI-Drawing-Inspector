CHANGED

- `ai_inspector/industrial_assets/model_builder/pictures.py`: build-only four-view contact sheets with a floor-grid FRONT arrow, a 1.75 m side-view person for models taller than 0.5 m, full-brightness lit artwork, bundled default-finish base colors, and a camera framed on selected part bounds plus 10 cm. The existing import renderer already sampled print textures; its constant emissive term washed out lit prints. The build renderer avoids that term for lit artwork.
- `ai_inspector/industrial_assets/model_import/preview_raster.py`: optional camera frame; the import call path and default computation remain unchanged.
- `ai_inspector/industrial_assets/model_builder/{job_io.py,worker_task.py}` and `ai_inspector/industrial_assets/model_builder_runner.py`: bounded preview-color input and a focus request against pinned GLB bytes in the existing contained build launch. Import tasks are unchanged.
- `ai_inspector/facility_layout/model_build_views.py`, `model_build_store.py`, `model_import_store.py`, `model_import_registration.py`, and `host.py`: scoped host focus function, per-draft view cache outside identity and bundles, at most eight cached views per draft, expired-draft cleanup, and read-only reload of the installed artifact after registration.
- `static/facility_layout_component_materials.js` and `ai_inspector/codex_runtime/component_inventory.py`: flatten validated model-default color, roughness, and metalness adjustments into the existing finish resolution; preserve part override > model default > placement > own material; protect artwork from finishes. Existing basic-shape default IDs, finish groups, and library resolution remain in use.
- `static/facility_layout_workspace.js` and `static/index.html`: built asset card line from `buildProvenance.sizeBasis.kind`, with updated script versions.
- Tests: new `tests/test_model_builder_pictures.py`, `test_model_builder_focus.py`, `test_model_builder_default_consumers.py`, `test_model_builder_default_consumers.js`, and `test_model_builder_asset_card.js`; updated the MB4a draft-worker preview expectations. Existing lint fixtures already cover all twelve codes with clean negatives and the 3,000-component performance case in `test_model_builder_build.py`, `test_model_builder_prints.py`, and `test_model_builder_composition.py`.

TESTS RUN

- `node --test tests/test_model_builder_asset_card.js`: 1 passed.
- `node --test tests/test_model_builder_default_consumers.js`: 3 passed.
- `node tests/test_facility_appearance_runtime.js`: all cases passed.
- `node --check` on the changed static JavaScript and new asset-card test: passed.
- Hidden Python stdlib `ast.parse` on changed and new Python files: passed (no imports or test execution).
- `git diff --check`: passed.

NOT RUN

- Pytest, including the new picture, focus, default-finish, worker, import-preview, and existing builder suites. The sandbox cannot import the test dependencies; the user will run these outside it. No browser tests or network operations were run.

DEVIATIONS

- None. The focus view uses an opt-in request within the existing `build` worker task so it shares the build process limits and private-package bootstrap.

OPEN QUESTIONS

- None.

CLAUDE REVIEW AND VERIFICATION

Run outside the sandbox with the test venv, one file at a time: pictures 9, focus 3, default_consumers 4 (py) and
3 (node), asset_card 1 (node), draft_worker 5, and every earlier builder file (build 35, prints 46, print_worker 8,
worker 22, worker_boundary 10, protocol 13 + 1 skipped, composition 17, composition_worker 12, composition_host 29,
bundle 19, identity 10, registration 19, draft_store 30, import_compat 20); model_import store, registration,
catalog, lifecycle_fixes, worker, launch, preview (import preview bytes unchanged), prepare, inspection, sage_tools,
routes, chat_transport; node test_facility_appearance_runtime.js and test_facility_layout_three_adapter.js
(190/190). Rendered and inspected: the pack station, baler, gaylord and tag sheets and focus views of the monitor
screen and scale display (screens readable, lit display not washed out, FRONT arrow, focus framed on the part).

Two fixes:
1. The side-view person stood with its feet at y = 0.1 m (floating above the floor line) and arms raised. It now
   stands on the floor (feet at 0) with arms down: neck 1.55, shoulders 1.42, hip 0.9, hands 0.85, head 1.55-1.75.
2. Finish precedence on printed faces (my brief's wording "prints are never finished" was wrong; I meant model
   defaults). The change made both the 3D view (component_materials.js apply) and component_inventory ignore the
   user's own part override on a printed face, which broke the existing test
   test_codex_component_inventory.py::test_shown_color_follows_the_renderer_precedence and changed shipped
   behaviour. Restored: part override > (printed artwork: no model default, no object finish) > model default >
   object finish > own material. Model defaults still skip printed faces (recordDefaults and the apply loop), as
   C6/C28 intend. The two new tests that encoded the wrong rule now test the right one
   (test_printed_artwork_takes_its_part_override_but_no_default_or_object_finish; the node test "artwork takes its
   own part finish but never a default").
