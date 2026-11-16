# Sage model builder: reference scripts (intent, not code to copy)

Claude's hand-built models of 2026-11-16, kept as the reference for docs/sage-model-builder-plan.md. They ran outside
the app with system Python (numpy, Pillow) and were installed into the local library by script.

- pack_models.py: a 42 in vertical cardboard baler, a gaylord on a pallet (the pallet is a library model; flattened
  cartons scattered with a fixed seed) and a pack station (72 x 36 in bench with riser, monitor with a printed screen,
  4 x 6 in label printer with a label coming out, parcel scale with a lit display, scanner in a stand, tape gun, kraft
  paper roll, boxes). Text on the monitor screen is generic here; the installed copy is private.
- cart_tags.py: clip-on carrier tags (printed placards) for a parcel roll cage. Note the workaround in its docstring
  (geometry at rail height, catalog height from the floor): primitives.verify rejects it today; the plan adds
  `hangHeight` (C44) so the builder can make the same thing, because the library cart is far too heavy to include
  (C43).
- glbsrc.py: the GLB writer they used (textured quads, materials, extras). geom.py (the shape kit: box, quad, lathe,
  tube, cylinder, disc, ellipsoid, centring) is the same file as docs/sage-model-import-reference/geom.py.

pack_models.py imports warehouse_models.py (folder name, credit text, `compact`), which is not copied: it adapts
Sketchfab downloads and belongs to the model-import side.

## MB0 hand-off (plan C36, C42-C46)

- baseline-stats.json: bounds, triangles, materials, images and part triangle counts of the four reference GLBs
  (read from the library copies; the gaylord's pallet there is a user CAD-library model, see C42).
- recipes/: the four E1 references written against the plan's schema (baler-vertical-42, gaylord-on-pallet,
  pack-station-printer, carrier-tag-ups), plus pallet-plain and roll-cage-plain (MB3 builds these to make the
  composition fixtures) and roll-cage-tag.template (the composed example; MB3 fills in the `$...` values).
  The gaylord carries its pallet as an inline group so MB1 can build it before composition exists.
- recipes-envelope.json: each recipe's size in a real MCP tools/call envelope (C46).
- baseline-tests.txt: the test baseline on the worktree before MB1.
- The font is in ai_inspector/industrial_assets/model_builder/fonts/ (fonts.json, LICENSE-Aileron.txt).
