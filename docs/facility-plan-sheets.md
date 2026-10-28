# Facility plan sheets (2D layout PDF)

The **Export PDF** button on the Facility Layout ribbon opens the saved layout as plan sheets. It is
also available at `GET /api/facility-layouts/{siteId}/{layoutId}/plan.pdf`. Unsaved changes are not
in the PDF, so the button stays disabled until the layout is saved.

## The one template

Every plan uses `ai_inspector/facility_layout/plan_sheet_template.json`. A different look for all
future plans means editing that file, not the code. It holds:
- `page`: 17 x 11 in landscape, with the margin.
- `titleStrip`: the strip on the right. It holds:
  - the brand band (logo and wordmark);
  - project, sheet, key numbers, legend and notes;
  - the sheet block (date, revision, layout, sheet number, "n OF m").
- `drawing`: the drawing area and the title band under it (drawing title, scale, scale bar, north arrow).
- `brand`, `palette`, `fontSizes`.
- `scalesFeetPerInch`: the standard engineering scales. Each sheet uses the largest one at which its
  content fits.
- `notes`: the numbered notes.
- `sheets`: which sheets exist, in order, with number, title and optional extra `notes`. Kinds:
  - `site` is drawn only when the layout is placed on a site;
  - `setting-out` is drawn only for a building placed on a site;
  - `floor` is always drawn.
- `styles`: the stroke, fill, dash and legend label of every kind of object. The legend lists only the
  kinds a sheet actually shows.

Units are feet and inches first, metres in brackets, for example `305'-1" (93.0 m)`. Areas are square
feet with square metres.

## What each sheet draws

All geometry is the layout's own (metres, layout X/Z), the same data the 3D view uses:
- model footprints come from `spatial.placement_spatial_records`;
- walls and door gaps come from the compiled wall panels;
- the lot, drives, roads and routes come from the site context, turned into the layout frame by the
  building pose.

+Z (plan north) is drawn up the sheet, as in the Plan view. The north arrow points to true north from
the pose's bearing.

**Site plan (C-101):**
- public roads with their names, and the railroad;
- asphalt and concrete paving, stalls, painted lines, the crosswalk and arrows;
- trucks and cars, the building and its walls, the ground mark;
- the property line;
- the routes to the main road;
- labels for the outdoor areas and entrances;
- the building's overall dimensions.

**Setting-out plan (C-102)**, from the reference points (`docs/facility-site-reference-points-plan.md`):
- On the left: the lot, the building with its corners lettered A-D, the reference points (RP1, RP2,
  ...), and from the two nearest references to each corner a dashed tie with its length.
- On the right, the tables:
  - the corners and the centre, in site metres east/north and latitude/longitude;
  - the building lines' bearings (N 87 deg 34' 12" E) and lengths;
  - the reference points with their source and accuracy;
  - each tie's distance and bearing;
  - the fit check (`check_site_references`, computed when the PDF is made, with the stored photo).
- An extra note says to stake from a surveyor's control.

**Floor plan (A-101):**
- the slab and the zones, tinted by use and labelled with their area;
- staging lanes, lane lines, the walkway and aisle centrelines (with the aisle width);
- racks, forklifts and other equipment;
- dock doors (D1, D2 and so on, with their leveller pits) and personnel door swings;
- the overall, door-width and door-spacing dimensions.

## No PDF library

`pdf_canvas.py` writes the PDF directly: vector paths, the standard Helvetica faces (nothing
embedded), an image for the logo, and zlib-compressed streams. The app's other PDFs use PyMuPDF, which
is blocked pending its AGPL licence review. Pillow, already a facility dependency, only reads the logo.

Tests: `tests/test_facility_plan_pdf.py`.
