# Safety equipment + evacuation and emergency maps (EM0-EM5)

Status: approved 2026-10-30 ("start the complete implementation"), with doors and restrooms added ("plan on
adding doors restrooms and safety equipment"). The user was away; the open decisions took the proposed defaults
(see "Decisions taken" at the end). EM0-EM3 built in the test copy.

## Goal

The user, 2026-10-30: add 3D models for the items on an emergency-map legend "across the factory at strategic
places", then "equip our agents with the ability to generate in addition to the factory 2d plan two other pdfs the
evacuation and emergency map ... for each factory an agent will now be able to generate up to 3 pdf plans."

The user's reference photo shows two posted letter sheets: an evacuation map (team areas outlined in colour, a star
at every exit door, a box per team naming its meeting point, one instruction line) and an emergency map (black floor
plan, a symbol at every safety item, a legend, the assembly areas). The photo is used for its format only; none of
its names, address, phone number or floor plan go into the app, the demo or any test fixture.

Legend items: Emergency Exit, First Aid Kit, AED, Eyewash, Severe Weather Shelter, Spill Kit, Fire Extinguishers,
Electrical Panel, Bathroom, Fire Risers, PPE Vending.

## 1. Models (EM0)

Sketchfab, CC BY 4.0 (credit line in a CREDITS.txt beside the models, as for the car pack). Sketchfab downloads need
a signed-in account, so the user downloads the GLB files; I convert and install them.

| Item | Model | Author | Triangles |
|---|---|---|---|
| Exit door + sign | Low poly metal door with exit sign (89bd4e493f4e4e1db314fb19ccd6fec1) | sauti | 104 |
| Fire extinguisher | Modern Fire Extinguisher (d5aa2d0ead914e8794a7d46acc12d2d9) | louir-muir | 2,396 |
| First aid kit | First Aid Kit (a6cc12f1d4a14a0fb3aed520cb196549) | Doctor_Fastoss87 | 3,756 |
| AED | IPAD SP1 Automated External Defibrillator (faff5cbba8734373bed35e00291bf9a1) | redonemart | 4,896 |
| Eyewash + shower | Emergency Shower with Eye Wash (61a536cf4e1f4995a8128863f8994e3e) | cesar.seidel | 15,226 |
| Electrical panel | Electrical Breaker Panel Box - LP model (4b12b4e00fc14f95beb55d7016eaf28d) | Nikoleta.Zhecheva | 4,698 |
| PPE vending | Vending Machine (d62a741a00e04d84bc45b6ccb039cf8a), recoloured blue, no brand marks | RackRibs | 1,626 |

Searched with nothing usable (non-commercial, branded, or a whole room at 1.3 M triangles), so built by us from
basic shapes like the barriers and the roof: fire riser (red pipe, valves, gauges), spill kit station (yellow bin,
green band), assembly-point sign (green sign on a post), and a wall cabinet for the AED and first aid kit.

Not models: Bathroom and Severe Weather Shelter are rooms. They become map symbols on zones the user designates.
Factory 02 has no restrooms, so that symbol does not appear unless restrooms are added.

Conversion as for the car pack: metres, upright, centred X/Z with the base at Y=0, materials marked as authored so the
3D view keeps their colours, each model under about 10 k triangles (gltfpack when needed). Each catalog entry carries
a tag that gives its map symbol: emergency-exit, fire-extinguisher, first-aid, aed, eyewash, spill-kit,
electrical-panel, fire-riser, ppe-vending, assembly-point. Wall items use the existing wall attachment
(snapRelationship family wall_attachment, support tagged wall); items at columns stand on the floor.

## 2. Placing them in Factory 02 (EM4)

Done by me in one save with a backup, like the roof (Factory 02 was built with Codex; Sage did not build it). Rules
of thumb, written on the plan and reported as numbers, not claimed as a code review:

- Exit doors: personnel doors along the outer walls, about every 50 m and at each department edge (about 20).
- Fire extinguishers: no spot on the floor more than 75 ft (23 m) of walking from one (the Class A travel distance in
  OSHA 1910.157 / NFPA 10); on the outer walls and on floor stands beside the steel columns (about 60-70).
- First aid kits: one per department plus lunchroom, gym and office (about 12).
- AEDs: lunchroom, office, gym, and on the main production aisles so one is within about a 3-minute round trip
  (about 6).
- Eyewash + shower: within 10 seconds (about 17 m) of the hazard (ANSI Z358.1): machining coolant, toolroom,
  equipment service, inspection (about 5).
- Spill kits: docks, machining, equipment service (about 6).
- Electrical panels: Equipment Service + Utilities, plus distribution panels on the outer walls by department
  (about 12).
- Fire risers: one per sprinkler system area along the outer walls (NFPA 13 caps one system at 52,000 ft2, about
  4,800 m2) (about 12).
- PPE vending: where staff enter production from the office and lunchroom (2-3).
- Assembly-point signs: one at each team's meeting point.

Every new placement sits in a zone and the save adds no error findings.

## 3. Teams and meeting points (EM1)

New layout data `extensions.facilityEmergencyPlan`:
`{teams: [{teamId, name, color, zoneIds, meetingPoint: {label, placementId | position {x, z}}}], shelterZoneIds,
restroomZoneIds, phone?}`. The phone number is stored only when the user gives it. New operation
`set_emergency_plan` (validated: zones exist, colours valid, meeting points outside the building), allowed for
Apply directly.

Proposed for Factory 02 (the user decides):
- Red Team - Production (machining, toolroom, robotics, assembly, inspection, equipment service): meeting point
  Employee Parking South.
- Blue Team - Warehouse (receiving, raw and finished racks, dispatch, docks): meeting point Employee Parking North.
- Green Team - Office (office, lunchroom, conference rooms, gym): meeting point the office parking lot.

## 4. The two new PDFs (EM2)

One renderer per kind beside today's plan sheets, from the same saved layout: `layout` (today's C-101/C-102/A-101),
`evacuation`, `emergency`. Each is its own PDF file and chat file card; the existing route takes
`?kind=evacuation|emergency`.

- Evacuation map: title "<layout name> Evacuation Map"; floor plan in light grey; each team's zones outlined and
  lightly tinted in its colour; a star at every exit door; a box per team ("Red Team - Production / Meeting point -
  Employee Parking South") placed in the margin near its area; a meeting-point star outside; the line "Proceed to
  any exit door and continue to your meeting point for evacuation roll call."; legend.
- Emergency map: title "<layout name> Emergency Map", with the site address when the layout has one and the phone
  number when stored; black floor plan; a symbol at every safety item and EXIT at every exit; a legend listing only
  the symbols present; the assembly areas with their coloured stars; revision and date.
- Both: 11 x 17 in landscape like the layout plan (prints fine shrunk to letter), poster layout like the example
  (title on top, legend box below), small InspectorPro footer, and the note "Generated from the saved layout. Check
  exits, routes and equipment on site; the facility's emergency action plan governs."
- Symbols in the US style of the example (red EXIT box); the ISO 7010 pictograms already in the app
  (static/facility_library/decals: E003 first aid, E011 eyewash, F001 extinguisher, E007 assembly point) drawn as
  PDF vectors; simple drawn symbols for AED, electrical panel, fire riser, PPE vending, spill kit, shelter, restroom.
- The result tells Sage the item counts, the teams, and the longest straight-line distance from any floor point to
  its nearest exit (a number to discuss, not a code check).

## 5. Sage (EM3)

- `prepare_layout_pdf` gains `kind`: layout | evacuation | emergency. Up to 3 PDFs per factory, each a file card.
- `suggest_emergency_teams` (read-only): teams from the zone types and names, meeting points from parking or open
  ground outside; Sage stages `set_emergency_plan` with the user's changes.
- Safety items are placed with the existing placement tools from the library.
- With no teams set, the evacuation map is not built; Sage says so and offers to set them.

## Steps

EM0 models (after the downloads) + our own builds -> EM1 data + operation + tests -> EM2 the two renderers + tests ->
EM3 Sage tools + tests -> EM4 Factory 02 placements and teams -> EM5 port, desktop restart, 2-3 live Sage turns on
Codex (one per PDF), screenshots of the three PDFs.

## Decisions for the user

1. Download the 7 Sketchfab models above as GLB into Downloads\safety_models (or: I build all of them from basic
   shapes - plainer, no credit line).
2. Teams and meeting points as proposed in section 3?
3. Which rooms are severe-weather shelters? Left off Factory 02 until the user picks (a structural call). Add
   restrooms to Factory 02 so the map can show them?
4. Paper: 11 x 17 poster layout (proposed) or letter like the example?

## Decisions taken (user away, 2026-10-30)

1. Models: the user downloaded the door, extinguisher, first aid kit, AED (a UK AED cabinet instead of the IPAD SP1),
   eyewash shower and electrical panel. Built by us: exit sign post, extinguisher / first aid / AED floor stands
   with signs, fire riser, spill kit, PPE vending machine (no download), assembly-point sign, restroom walls,
   toilet stall and vanity. All stand on the floor (wall attachment only works on a support's +-Z faces).
2. Teams as proposed: Red = production -> Employee Parking South, Blue = warehouse -> Employee Parking North,
   Green = office, lunchroom, conference rooms, gym -> the office parking lot. suggest_emergency_teams gives the
   same split from the zone names.
3. Shelters: the four restroom blocks (the user, 2026-10-30: "use the restroom blocks as the shelters"); whether
   they can shelter people in severe weather is still for a structural engineer to confirm on site. Restrooms: four 10 x 7 m blocks (two rooms, two stalls and a vanity
   each) on free floor beside the walkways; the robot and inspection side has no free floor big enough.
4. Paper: 11 x 17 in poster, landscape. The map scale is the smallest whole 10 ft per inch that fills the page.

## Built

- emergency_plan.py: extensions.facilityEmergencyPlan (normalize, plan_from_layout), safety items by catalog
  tag, team suggestion, farthest floor point from an exit (straight line, 3 m grid over the indoor zones).
- set_emergency_plan operation: validated, in the Sage schema, allowed for Apply directly (it moves nothing).
- emergency_pdf.py: the two poster maps; plan.pdf?kind=evacuation|emergency (409 when the evacuation map has no
  teams, 400 for an unknown kind).
- Sage: prepare_layout_pdf(kind), suggest_emergency_teams; each PDF a file card under the reply (up to three).
- Tests: tests/test_facility_emergency_maps.py.
