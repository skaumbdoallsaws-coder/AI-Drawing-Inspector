# Step-by-step warehouse build (plan, 2026-10-24)

## Why

The first desktop take (2026-10-23, "Bayport warehouse") built the whole site from one long prompt. The user's review:

- One vague prompt did everything, and the results changed between runs: 6 trucks, 288 rack bays and 22 cars in
  the rehearsal against 5, 252 and 20 on the desktop. Sage chose the building's size and position itself.
- The car park landed in the trucks' path, between the truck entrance and the court, and it touched the truck
  court near the docks. The planner only kept it 2 m from the court.
- The walls arrived already finished: cyan panels, a white band and the logo.
- While the layout was being built, the review stayed in the Site tab. The 2D layout never showed it.

The user's direction: build it step by step with specific prompts, and choose the warehouse size once the lot has
been measured. The video can speed through some prompts; consistent results come first.

## What changes

1. **One layer per prompt, with your numbers.** Each prompt is one review: you see it, approve it, then send the
   next one. A step adds only its own layer to what is already saved and never re-plans earlier steps.
2. **You choose the building size.** The building step places exactly the size and position the prompt gives.
   If that does not fit inside the lot and its setbacks, it says so and by how much. It never shrinks or moves the
   building on its own.
3. **Walls arrive plain grey.** The colours, the white band and the logo come only with the paint step, in that
   step's review.
4. **Car park rules:**
   - it has its own entrance from the street, at least 40 m from the truck entrance;
   - it never lies between the truck entrance and the court;
   - it stays at least 10 m from the truck court and the truck drive;
   - it never shares a drive with the trucks.
   If the place you ask for breaks a rule, the tool says which rule. It does not move the car park somewhere else.
5. **Each review opens in the view that shows it:**
   - the 2D Plan for anything inside the building;
   - the Site view for the docks' drive, the car park and the routes, which sit on the photo;
   - 3D for the models and the paint.
6. **The one-shot tool is retired.** "Design the whole site" (plan_warehouse_on_outline) leaves Sage's tool list.
   Its geometry code is reused by the step tools.

## The build steps

The prompts are examples; the numbers are the user's choice.

| # | Step | Example prompt | Adds | View |
|---|------|----------------|------|------|
| 0 | Place | *(globe flight and county parcel, in the Site tab)* | site, photo, roads, parcel | Site |
| 1 | Measure | "Find the parking lot on the photo, outline it and tell me its size." | traced outline, dimensions | Site |
| 2 | Building | "Build a 100 x 50 m warehouse, 10 m high, long side along 4th Ave N, 30 m back from the street, dock wall facing west." | slab, plain walls | Plan |
| 3 | Zones | "Add receiving and shipping 15 m deep along the dock wall, side by side, storage behind them, and a 6 m forklift charging bay along the back wall." | zones | Plan |
| 4 | Markings | "Mark the floor: yellow staging lanes in receiving and shipping, and a 1.5 m walkway along the storage." | floor markings | Plan |
| 5 | Layout | "Lay out pallet-rack rows parallel to the dock wall with 3.7 m aisles and a cross aisle in the middle." | rack-row outlines and aisles (no models yet) | Plan |
| 6 | Docks | "Put 9 dock doors on the west wall, a 40 m truck court and a truck entrance from 4th Ave N, and show the route to Highway 95." | door openings, court, truck drive, entrance, route | Site |
| 7 | Parking | "Add a car park for 30 cars east of the building with its own entrance from 4th Ave N and a walkway to an employee door." | car park, stalls, car drive, entrance, door, walk | Site |
| 8 | Populate | "Fill the rows with pallet racks, put 4 forklifts in the charging bay, park trucks at 5 doors and 20 cars in the car park." | models, unpainted | 3D |
| 9 | Paint | "Paint it in our colours: cyan walls with a white band and our logo, blue truck cabs, deep-blue racks with orange beams, everyday car colours." | colours, band, logo | 3D |

Afterwards come the before-and-after reveal and the flyby, recorded frame by frame, and the PDF if wanted.

Docks come before parking so that trucks get the lot first and the car park is placed around their entrance and
court. The user's list had parking before docks (open question 1).

## Tools for Sage

- One tool per step:
  - `plan_warehouse_building` (2)
  - `plan_warehouse_zones` (3)
  - `plan_floor_markings` (4)
  - `plan_storage_layout` (5)
  - `plan_site_docks` (6)
  - `plan_site_parking` (7)
  - `plan_warehouse_contents` (8)
  - `plan_design_paint` (9), extended to the walls, band and logo.
- Each tool takes explicit numbers and stages one review through `preview_planned_design`. It reports what it
  did, and anything it could not do with the reason.
- When a number is missing, the tool uses a stated default, and Sage names it in the reply. Examples: wall height
  10 m, staging depth 15 m, aisle 3.7 m, truck court 40 m.
- Sage's guidance: one step per prompt, use the numbers given, never redo an earlier step unless asked.

## App

- A staged review switches to the view that shows it (rule above).
- The review card says the step in plain words, for example "Walls 100 x 50 m, no doors yet".

## Testing

- Unit tests for each tool:
  - fit and refusal rules;
  - the car park rules;
  - plain walls until paint;
  - paint covering the walls, band and logo;
  - each step leaving earlier steps untouched.
- A free replay of the whole sequence without Sage, checking each step's result and view.
- One live rehearsal in the test copy with Sage on Codex: 9 turns on the ChatGPT plan, no money.
- Then a port to the desktop app with the verified procedure (backups, tests before and after), and the recording.

## Where

The work is built and rehearsed in the test copy (its own sign-in and layouts), then ported to the desktop app.

## Decisions (user, 2026-10-24)

1. Order: docks, then parking. Trucks get the lot first, and the car park is placed around them.
2. The layout step draws the rack rows and aisles in 2D. The populate step fills them with rack models, forklifts,
   trucks and cars.
3. Approved: build it in the test copy, rehearse it there, then port it to the desktop app.

Still open: the building size for the Bayport lot (about 210 x 125 m, irregular). About 100 x 50 m leaves room for
the court and the car park. The user chooses it in the building prompt.
