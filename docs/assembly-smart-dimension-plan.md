# Smart Dimension in the Assembly view (F6 of the face plan)

## Why

The user, 2026-10-26: "I wanted edge so we could measure the model in the viewport with smartdimensions ... our
smart dimension will work exactly as solidworks in the viewport". Then chose F6 (edges + smart dimensions) as the
next step after F0-F5 of `docs/assembly-face-selection-plan.md`.

Today the view's Measure button joins two clicked surface points and shows the distance in a toast. Nothing knows
an edge, a circle or a vertex.

## What exists (read 2026-10-26)

- **The edges are already in the GLB.** A CAD edge is where one face's run of triangles meets another's. Measured
  with a read-only prototype on the four re-exported models (`C:\t\f6\edge_chains.py`):

  | Model | Edges | Lines | Circles + arcs | Curves | One-sided |
  | --- | --- | --- | --- | --- | --- |
  | MMLE-50D | 7,050 | 3,526 | 2,549 | 975 | 97 |
  | ABB IRB 6650 | 6,214 | 5,272 | 614 | 328 | 4 |
  | Red forklift | 1,669 | 950 | 382 | 337 | 1 |
  | FANUC 14tes2 | 4,999 | 3,656 | 617 | 726 | 200 |

  - Lines are straight to within 2e-5 of the part's size.
  - Chains of three or four points always fit some circle, so a free fit invents arcs. The neighbouring faces
    settle it: a circle on a cylinder has the cylinder's radius (the exporter wrote it). 94-98 % of the fitted
    circles match their cylinder; the rest are ellipses where a plane cuts a cylinder at an angle, which stay
    curves.
  - One-sided edges border a sheet body or a gap in an imported model; they still bound their face.
  - MMLE-50D's largest part has 20,874 triangles, so a part's edges take milliseconds in the browser.
- **So no re-export and no SOLIDWORKS run is needed.** The GLBs stay byte for byte as ported in port 24.
- **The face table** (`_assemblyFaceTable` in `index.html`) gives each triangle's face, its kind and radius, and
  smooth patches on models without CAD faces.
- **The view** is in metres at true size (the model root has no scale). The orbit controls, the CSS2D label
  renderer and the per-frame `_assemblySignsSync` are where the dimensions hook in.
- **The appearance store's revision** covers finishes, scene, signs and face finishes only, so dimensions can be
  kept there without making the Specification Sheet picture stale.
- **Sage's sign tools** write to the store and the view draws after the reply. A measurement must answer inside
  the turn, so Sage measures from the face report on the server.

## Decisions (defaults taken; say if any should change)

1. **Edges come from the face runs, worked out in the browser.** Each edge is a chain of triangle sides between
   two faces (or one face and nothing), cut at vertices where three faces meet.
   - Kinds: line, circle (closed), arc, curve. Plane with plane is always a line. A circle or arc must match an
     adjacent cylinder's radius and lie square to its axis, or be a clean fit over five or more points.
     Anything else is a curve, measured by its length.
   - Vertices are the chain ends.
   - On a model without CAD faces, the edges are the smooth patches' borders, marked approximate.
2. **The tool works like SOLIDWORKS Smart Dimension.**
   - The Assembly view's Measure button becomes Smart Dimension (same place, same icon). The 3D Model tab keeps
     its Measure.
   - Hover picks a vertex within 8 px first, then an edge within 6 px, then the face. The hover and selected
     colours are the face-picking ones.
   - One entity with a size of its own shows it at once: a line its length, a circle its diameter, an arc its
     radius, a cylinder face its diameter, a curve its length.
   - Clicking a second entity dimensions the pair (table below). The dimension follows the pointer; a click on
     empty space places it. Esc drops the picks; Esc again ends the tool.
   - A placed dimension can be dragged by its text, and deleted with Delete once clicked.
   - The tool stays on for the next dimension, as SOLIDWORKS does.
3. **What a pair gives**, the SOLIDWORKS defaults:

   | Picked | Dimension |
   | --- | --- |
   | vertex + vertex | distance |
   | vertex + line, plane or cylinder axis | perpendicular distance |
   | circle or arc + vertex, line, plane, circle | from its centre |
   | two lines, two planes, line + plane, two cylinders, cylinder + plane or line | parallel: distance; else angle |
   | a curve or another surface with anything | minimum distance |

   An angle takes the quadrant the pointer is in. Parallel means within 0.05 degrees.
4. **Values as SOLIDWORKS shows them:** 2 decimals, no unit after the number, Ø for a diameter, R for a radius, °
   for an angle. Units are mm or in per machine, mm by default. The prompt line names the units and has the
   switch.
5. **Drawing.** An overlay over the canvas, redrawn each frame from the dimension's points. Thin lines, filled
   arrowheads, extension lines with a small gap, and text with a light halo so it reads on any background.
   Dimensions draw on top, as in SOLIDWORKS. Captures (the Specification Sheet picture) never show them.
6. **Kept with the machine.** The appearance store gains `dimensions` (at most 100), each with:
   - one or two entities: a face as today (number + fingerprint), an edge as its two faces plus a point near
     it, or a vertex as its point;
   - where its text sits, in the first part's coordinates, so it moves with the part.

   On load each entity is found again as faces are. One not found makes the dimension `dimension_missing`,
   never a neighbour. A dimension is on one copy of a part, so it stays on the copy it was placed on.
7. **Sage measures and places dimensions on faces.**
   - The face report gains each listed face's exact plane (point, normal) or axis (point, direction, radius).
   - `measure_assembly` (read) measures one or two faces from that report and gives the value. The view, drawing
     the same dimension, gets the same value.
   - `place_assembly_dimensions` places them and `remove_assembly_dimensions` removes them.
   - Dimensions the user placed reach Sage with their values in the geometry report.
   - Edges and vertices stay with the user's pointer. Sage names faces, and a face pair covers most "how wide,
     how far, what diameter" questions.
8. **Out of scope:** the 3D Model tab, Facility, dimensions in the Specification Sheet picture, editing a value
   to drive the model (these dimensions are reference ones).

## Phases

- **D0 - edges.** `static/assembly_smart_dimension.js`: edges, vertices and their kinds from a face table; the
  exact plane, cylinder axis and circle of each. Node tests on built shapes and on the robot and forklift GLBs
  (each circle's radius equals its cylinder's).
- **D1 - the tool.** Hover and pick (vertex, edge, face), the pair rules, the preview, placing, dragging,
  deleting, units, the overlay. Node tests for the rules and the layout; one browser run on MMLE-50D.
- **D2 - kept with the machine.** Store, route, finding entities again, `dimension_missing`, the report to Sage.
  Python tests.
- **D3 - Sage.** The face geometry in the report, the three tools, instructions, labels. One fixture shared by the
  JavaScript and Python tests, so both give the same numbers.
- **D4 - live test, port, desktop.** MMLE-50D in the test copy: the user's dimensions by hand (deck length, a
  wheel's diameter, an arm angle), then Sage: "dimension the platform's length and width and the diameter of a
  wheel". Port 25 with the usual backup and byte check, then restart the desktop app and run the Sage turn there.

## Status

- 2026-10-26: plan written; the user chose F6 to be planned and built. Building D0-D4.
- 2026-10-26: D0-D3 built and tested in the test copy; the D4 live run there passed (by hand, then Sage on
  Codex).
- 2026-10-26: port 25 (test copy cfd2e26..698dc47, 14 files, real repo uncommitted; backup
  `Documents\InspectorPro-Backups\2026-10-26-before-smart-dimension-port`); real-repo tests pass. In the desktop
  app, Sage dimensioned MMLE-50D the same way: 1010.00, 518.00 and Ø152.40, quoted as written, in 5 steps
  (1 min 55 s).

## As built (2026-10-26)

- **D0.** `static/assembly_smart_dimension.js` (UMD, no three.js): `buildEdges`, `faceGeometry`, `fitCircle`, the
  entities, `measure`, `formatValue`, `layout`, `textOnRay`, `defaultSide`/`defaultText`. On the GLBs: robot 5,274
  lines, 16 circles, 234 arcs, 692 curves (102 circles on cylinders, ~0.3 s); forklift 949 / 139 / 296 / 284
  (419 on cylinders).
- **D1.** The Assembly toolbar's Measure is Smart Dimension (the 3D Model tab keeps Measure). An SVG overlay over
  the canvas, redrawn when the camera, the view size, the dimensions, motion or explode change. The prompt line
  holds the units switch. Picking faces in the library pane stops the tool, and the tool stops face picking.
- **D2.** The appearance document keeps `dimensions` (at most 100) and `dimensionUnits`, outside `revision()`, with
  `dimensionsRevision` of their own. `PUT /api/assembly-appearance/{n}/dimensions` saves them. The geometry
  report gives each dimension's status, kind, value and text. Each face in the face report and the selection
  carries its exact `geometry`: a plane, a cylinder or a sphere at 1e-6 m.
- **D3.** `ai_inspector/assembly_knowledge/assembly_dimensions.py` measures faces as the module does.
  `measure_assembly`, `place_assembly_dimensions` and `remove_assembly_dimensions` are in the Assembly tab only,
  not in Documentation. The Assembly instructions and the progress labels are updated.
  `tests/fixtures/smart_dimension_cases.json` (13 cases) is checked by both
  `tests/test_assembly_smart_dimension.js` (15 tests) and `tests/test_assembly_dimensions.py` (21 tests).
  Both repos' ignore rules match that path, so it is force-added.
- **Changed after the first live run:** a dimension placed without a text point (Sage's) used to sit beside
  itself, away from the machine's centre. A platform's length and width both went above the deck, on top of
  each other. Now a distance goes out past its parts on one side, as on a drawing:
  - a dimension running across sits in front (+Z);
  - one running front to back sits on the right (+X);
  - later dimensions on the same side stack further out.
- **D4 in the test copy, MMLE-50D:**
  - **By hand:**
    - the deck's back edge measured 998.34;
    - a hole measured Ø32.00;
    - two arm edges gave 81.96° or 98.04°, by the quadrant the text was dropped in;
    - the deck top to the base plate measured 1368.69;
    - they follow the camera;
    - dragging a text, clicking a dimension and pressing Delete both worked;
    - they came back after a reload;
    - inches showed 39.30 / 53.89.
  - **Sage** (gpt-6.1-sol, 6 steps, 48 s; one malformed BOM call, retried) was asked to "Dimension the
    platform's length and width and the diameter of a wheel". It placed:
    - 1010.00 between the deck's end faces (1030071 faces 25 and 34);
    - 518.00 between its side faces (faces 7 and 16);
    - Ø152.40 on a wheel's tread (1030111 face 2).

    The view drew the same values. Sage's reply rounded 1010.00 to "1010 mm". The instruction now says to quote
    the tool's text; that change has not been run live yet.
- **Limits:**
  - Curves (B-spline faces, cone and plane cuts) are dimensioned by their length only.
  - Sage measures flat, cylindrical and spherical faces. Cones, tori and free-form faces are dimensioned with
    the pointer.
  - A dimension stays on the copy of the part it was placed on.
