# Reference points, fit check and setting-out sheet (plan, 2026-10-23)

The user asked how a builder will know where the layout goes on the real ground, which way it faces,
and where its centre and long side are. They also suggested adding reference points to the original
photo after the design, dropping the plan onto them, and seeing how well it fits.

## Where we stand

The design is already tied to the ground. The site has a WGS84 origin point; the building pose
places the plan's corner in metres from it and gives the compass bearing of plan north. For
Bayport warehouse 5:
- the centre is at 45.020656 N, 92.775530 W;
- the long side runs N 87 deg 34' 12" E;
- the corners are 15.8 m to 35.9 m from the county parcel's lines.

What is missing is what a builder sets out from:
- points they can find on site;
- the building corners' distances and bearings from those points;
- a statement of how far each number can be trusted.

The sources do not agree to the centimetre:
- **The USGS NAIP photo:** about +/-6 m to true ground, at 95% of points. Between features in one
  photo, distances are much better, about 1 m.
- **The county parcel:** drawn from recorded plats; not survey-grade.
- **Census TIGER roads:** centreline positions good to several metres.
- **A surveyor:** survey-grade GPS (about 2 cm), and the property pins in the ground. Staking always
  rests on the survey; our numbers get the builder and the surveyor started and catch gross errors.

## What to build

**R1 - Reference points in the site context.** `facilitySiteContext.references` holds:
- an id (RP1, RP2, ...) and a label;
- a kind: property corner, pavement or curb corner, pole, road intersection, rail crossing, or other;
- a source: county parcel, site photo, road map or survey;
- a position in the property frame (metres east and north of the site origin);
- its accuracy in metres;
- optionally, a surveyed position entered later.

Edits go through review, like outdoor areas. The Site tab shows each point as a labelled triangle.

**R2 - Sage adds them.** A read tool, `suggest_site_references`, proposes well-spread candidates from
data the site already has, each with its source and accuracy:
- the parcel corners;
- the corners of the traced existing pavement;
- road intersections and the rail crossing.

Sage picks three to six, names them in plain words ("north-west curb corner of the old lot"), and
stages them as one review. The user can also add or drag them in the Site tab.

**R3 - Fit check: drop the plan onto the references.**
- The server fits one set of positions to another for the same points: a best move and turn, never a
  stretch.
- It reports each point's residual, the average and the worst, and how far that moves the building
  corners.
- **Before a survey,** it compares independent sources at points both show, such as a road
  intersection in the road map and on the photo. That tells how far the photo the design was traced
  on is from the map data, for example "photo and road map agree within 2.4 m, worst 4.1 m at RP3".
  It also tells how much the setbacks to the parcel line can be trusted.
- **After a survey,** the surveyed positions replace the photo and map ones. The same fit gives the
  building corners in survey coordinates, to the centimetre, and reports any reference that disagrees
  (a moved pin, a mistaken feature).
- Sage explains the result in plain words. The plan is re-posed only through a reviewed edit.

**R4 - Setting-out sheet (C-102)** in the same sheet template, after the site plan. It shows:
- the lot, the building outline and the reference points;
- from the two nearest references to each building corner, a tie line with its distance and bearing;
- tables:
  - building corners A-D and the centre (site metres east/north, latitude/longitude);
  - the bearing of each building line;
  - offsets to the property lines;
  - the references with their source and accuracy;
  - the latest fit result.
- the accuracy note: photo and map positions are for planning; stake from the surveyor's control.

**R5 - Showing it.** The reference points appear in the Site tab and on sheet C-102. For the video, the
3D view can show them and animate the plan settling onto them; that is offered, not built by default.

## Steps

R1 then R2 then R3 then R4, each shown live in the browser, with tests. A free gateway dry run comes
before any Sage run.

## Built (2026-10-23)

- **R1, b224430:**
  - `facilitySiteContext.references`, with `upsert_site_reference` and `delete_site_reference` through
    review;
  - kept when a whole-site edit omits them;
  - drawn as pink triangles in the Site tab.
- **R2, 92755fa:** `suggest_site_references` (`site_references.py`).
  - Property corners first, then traced pavement corners; road crossings are kept for checks only.
  - Live on "Bayport paint test": Sage staged RP1-RP4, the four property corners, each about 3 m,
    and said they are not survey control. Approved.
  - The turn took 233 s, close to the 240 s editing budget.
- **R3, e41aef4:** `check_site_references` (`site_reference_fit.py`).
  - **Road map against the photo:** the photo's road centres come from the raw pavement mask.
    - A cross-section counts only where the mapped line lies in the paved strip, and the centres must
      line up within 1.5 m.
    - The first try read the rail ballast beside Maine St as the road; it is left out now, never
      guessed.
    - At Bayport 2 of 5 crossings show: the map is 2.3 m and 3.3 m from the photo, 2.8 m on average.
  - **Survey:** a move-and-turn fit of the measured points, with residuals and the corners' new
    coordinates.
- **R4:** the setting-out sheet C-102 in the PDF (see `docs/facility-plan-sheets.md`).

## Decisions (user, 2026-10-23; plan approved)

1. **References:** the property corners and the curb or pavement corners Sage finds on the photo.
   Road intersections and the rail crossing serve only to check the photo against the map data.
2. **Coordinates** on the setting-out sheet: latitude/longitude and site metres east/north. A
   surveyor converts to their own grid.
3. **Display:** the Site tab and the PDF only. Nothing new in 3D.
