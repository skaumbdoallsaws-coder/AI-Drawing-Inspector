# MB6 - Cookbook v1 and frozen evaluation items (Claude)

Written by Claude on 2026-11-17 while Codex built MB5a (plan section 7, C26, C42-C44). Codex did not write or edit
any of these files.

## CHANGED

- `ai_inspector/industrial_assets/model_builder/cookbook/index.json` (schemaVersion 1): id, name, size and a
  "teaches" line (<= 120 characters) per recipe, read by `get_model_recipe {}` (MB5a).
- Eleven recipes in the same folder:
  1. `baler-vertical-42` - copied from the MB0 reference recipe (Material Handling, unchanged).
  2. `gaylord-on-pallet` - copied from the reference. Its pallet stays a group of boards and blocks, not an include,
     so it builds on any site; item 6 (roll-cage-tag) is the include lesson.
  3. `pack-station-printer` - copied from the reference.
  4. `floor-sign-receiving` (new) - a double-sided panel sign with two panels, +z and -z, 2 mm off the board; the
     front list names only the +z face.
  5. `roll-cage-plain` (from the reference) - the base for roll-cage-tag. This is an eleventh entry beyond the
     plan's ten, because C43 has item 5 include the builder's own plain cage, and that cage must be buildable from
     the cookbook first.
  6. `roll-cage-tag` - the MB3 template with the real include values. Registering the cookbook's plain cage is
     deterministic: the same assetId, revision and artifactSha256 came out in two fresh temporary hosts:
     - asset-built-mesh-roll-cage-plain-6301e5fb6af6ad0ee2589744
     - revision 6d8c7683...
     - sha 8dda66bf...
     - top rail p:cage%20top%20rail#0

     So Sage can build and register roll-cage-plain, then build this recipe unchanged.
  7. `workbench-pegboard-vise` (new) - grid legs, pegboard holes as a dots print, and an extruded vise body. The
     vise overhangs the front by 15 cm, so the whole model sits in one group shifted 7.7 cm back to keep it centred.
     Mirrors work about the origin, so a recipe must be authored centred.
  8. `flammable-cabinet-45gal` (new) - two doors with a seam, a tube pull handle, mirrored hinges and a two-line
     label across both doors.
  9. `drums-spill-pallet` (new) - lathe drums, torus rolling hoops, two bungs placed with `around` (180 degrees),
     the drum group copied by a 2 x 1 grid, and repeat bars for the grating.
  10. `eyewash-station` (new) - a lathe bowl drawn as an open dish profile, a tube arm to a printed PUSH flag, and an
      EMERGENCY EYEWASH sign on the pedestal.
  11. `dock-bumper` (new) - extruded L-profile steel angles and 12 rubber pads repeated with 2 mm gaps. With 18 pads
      the 0.75 mm gaps aliased into a few uneven seams in the preview. Hex bolts are 6-sided cylinders.
- `docs/sage-model-builder-eval/items.json`, frozen before any live run (C26). It holds:
  - the rubric and pass rule, the bar, the holdout rule and the workflow gates;
  - the rater procedure: two raters, blind, R1 rated first from the contact sheet alone;
  - E1 items with their tolerances (gaylord body +-35 %, pallet scored against its own spec, C42);
  - 18 E2 items with size ranges, features, accepted part names and front criteria (24 initial runs; tier 1 x 3);
  - two E3 runs.

  The tier-5 items stay open by design. The user supplies two photos, and the spec-sheet page needs the user's OK
  to download. Each of these is frozen when supplied, before its run.
- `.gitignore`: a narrow exception `!docs/sage-model-builder-eval/**/*.json`, like the other C42 exceptions.
- `tests/test_model_builder_cookbook_recipes.py` (new). It checks:
  - the index matches the files (names, sizes, teaches length);
  - every file is ASCII, LF and <= 24 KiB;
  - every standalone recipe normalises and builds with no lints at its stated size, under 20,000 triangles;
  - E1 parity for the baler and pack station (bounds within 1 cm, the same part names, triangles within 25 %);
  - the gaylord body and pallet names;
  - registering the plain cage in a temporary host gives exactly roll-cage-tag's include values and top-rail key,
    and the tag recipe then builds with no lints;
  - items.json has 18 items, 24 runs, the tier counts, and no cookbook word in tier 2.

## Built results (in-process, as the worker builds)

| recipe | W x D x H (m) | triangles | lints |
| --- | --- | --- | --- |
| baler-vertical-42 | 1.32 x 0.99 x 2.60 | 1144 (ref 1084) | none |
| gaylord-on-pallet | 1.208 x 1.008 x 1.032 | 686 (ref 558, body rule +-35 %) | none |
| pack-station-printer | 1.83 x 0.91 x 1.87 | 1064 (ref 976) | none |
| floor-sign-receiving | 0.62 x 0.40 x 1.80 | 328 | none |
| roll-cage-plain | 1.10 x 0.65 x 1.00 | - | none |
| roll-cage-tag | 1.10 x 0.662 x 1.00 | - | none |
| workbench-pegboard-vise | 1.83 x 0.914 x 1.83 | 1798 | none |
| flammable-cabinet-45gal | 1.092 x 0.503 x 1.651 | 374 | none |
| drums-spill-pallet | 1.30 x 0.66 x 1.142 | 3216 | none |
| eyewash-station | 0.355 x 0.29 x 1.00 | 828 | none |
| dock-bumper | 0.254 x 0.114 x 0.508 | 544 | none |

I looked at every contact sheet. Each item is recognisable, the prints read the right way round, and the FRONT arrow
and the person are where they should be.

## TESTS RUN

- `tests/test_model_builder_cookbook_recipes.py`: 28 passed (test venv, outside the sandbox).

## NOT RUN / OPEN

- "Each checked in the app": the plan wants each recipe seen in the app. The desktop app stays untouched tonight,
  so this moves to MB7's isolated server, or the morning.
- If a later builder version changes the plain cage's output bytes, its asset id changes too. The cookbook test
  then fails and names the new values. That is intended.

## E1 side-by-side check (2026-11-17, MB8 preparation)

The hand-built library originals (read-only from the user's library) and the cookbook builds were rendered with the
same renderer (model-builder-night/e1_sheets.py; pictures in model-builder-night/out/e1, not in the repo).
- Baler and pack station: they look the same, view for view.
- Gaylord: the pallet differs, as C42 expects (the original's pallet is a user CAD-library model). The flattened
  cartons sat lower than in the original, which stacks them to about 0.8 m with some reaching the rim. The scatter
  window's top went from 0.75 m to 0.95 m, still under the 1.032 m rim. Bounds, part names and triangles are
  unchanged, and the test still passes. The MB0 reference recipe stays as it was recorded.
- Cage + tag against the hand-placed pair (cart_tags.py: the placard's top sits 15 mm below the rail top). The
  cookbook tag (from the MB3 template) hung 65 mm below. It is raised 5 cm (centre y 0.885), and the clips now run
  up to the rail top (0.95-1.00). It still builds with no lints and reads forward. Size and centring were already
  equal. New test: test_e1_cage_tag_matches_the_hand_placed_pair_in_size_height_and_centring.
