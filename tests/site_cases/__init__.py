"""Reference cases for the site build (docs/facility-site-reference-cases-plan.md, approved 2026-10-25).

A case is a frozen lot, the models its build places, and a recipe: the step tools' arguments in order, as Sage
sends them. The Bayport recipe is the take's prompts (steps_take.py PROMPTS, recorded 2026-10-24) in numbers.
"""
from copy import deepcopy

from ai_inspector.facility_layout.geo import from_property

from .bayport_lot import LOT as BAYPORT_LOT, MODELS

BUILDING = {"lengthMeters": 80, "widthMeters": 45, "heightMeters": 10, "alignWith": "4th Ave N",
            "fromStreetMeters": 60, "dockWall": "west"}
PAINT = {"walls": {"color": "cyan", "bandColor": "white", "logoWalls": ["beside_docks"]}, "pavementLogo": True}


def recipe(building=BUILDING, dock_wall="west", doors=8, stalls=30, side="north", street="4th Ave N",
           car_street=None, court=40):
    return [
        ("building", "plan_warehouse_building", {**building, "dockWall": dock_wall}),
        ("zones", "plan_warehouse_zones", {"dockWall": dock_wall, "stagingDepthMeters": 15,
                                           "chargingLengthMeters": 20, "chargingDepthMeters": 4}),
        ("markings", "plan_floor_markings", {"dockWall": dock_wall, "stagingLanes": doors, "walkwayWidthMeters": 1,
                                             "aisleEdgeLines": True}),
        ("layout", "plan_storage_layout", {"dockWall": dock_wall, "rowDirection": "across", "aisleWidthMeters": 3.7}),
        ("docks", "plan_site_docks", {"dockWall": dock_wall, "doors": doors, "truckCourtDepthMeters": court,
                                      "entranceStreet": street}),
        ("parking", "plan_site_parking", {"stalls": stalls, "side": side,
                                          "entranceStreet": car_street or street}),
        ("contents", "plan_warehouse_contents", {"racks": True, "forklifts": 4, "trucks": 5, "cars": 20}),
        ("paint", "plan_design_paint", deepcopy(PAINT)),
        ("references", "suggest_site_references", {"maxPoints": 4}),
    ]


def moved(lot, dx, dz):
    """The same lot dx metres east and dz north of the site point. Roads are stored as longitude and latitude, so
    the site point moves the other way and every property-frame shape moves by (dx, dz)."""
    lot = deepcopy(lot)
    geo = lot["georeference"]
    geo["originLatitude"], geo["originLongitude"], _ = from_property(-dx, -dz, geo["originLatitude"],
                                                                     geo["originLongitude"])
    for points in (lot["property"]["boundary"], *(area["boundary"] for area in lot["areas"])):
        for point in points:
            point["x"], point["z"] = round(point["x"] + dx, 6), round(point["z"] + dz, 6)
    for road in lot["roads"]["items"]:
        road.pop("line", None)  # derived from lonLat on load
    return lot


def mill_st_lot():
    """The step tests' made-up lot: 140 x 100 m, Mill St along the south edge, State Hwy 95 east, a railway west."""
    from tests.test_facility_site_steps import lot
    return lot()["extensions"]["facilitySiteContext"]


# The biggest 45 m-deep building that fits 60 m back from 4th Ave N: a search on 2026-10-25 found 167.97 m (168.01 m
# refused). The case keeps a little inside it, and 1 m more must be refused.
BIGGEST = 167.9

CASES = {
    "bayport": {"lot": BAYPORT_LOT, "models": MODELS, "recipe": recipe()},
    "bayport-moved": {"lot": moved(BAYPORT_LOT, 0.37, 0.61), "models": MODELS, "recipe": recipe(),
                      "sameCountsAs": "bayport"},
    "bayport-east-docks": {"lot": BAYPORT_LOT, "models": MODELS, "recipe": recipe(dock_wall="east")},
    "bayport-biggest": {"lot": BAYPORT_LOT, "models": MODELS,
                        "recipe": recipe({**BUILDING, "lengthMeters": BIGGEST})[:1]},
    "bayport-too-big": {"lot": BAYPORT_LOT, "models": MODELS,
                        "recipe": recipe({**BUILDING, "lengthMeters": BIGGEST + 1})[:1], "refuses": "building"},
    "mill-st": {"lot": mill_st_lot, "models": MODELS,  # with the step tests' arguments (test_facility_site_steps.ARGS)
                "recipe": recipe({"lengthMeters": 70, "widthMeters": 40, "alignWith": "Mill St",
                                  "fromStreetMeters": 20}, dock_wall="east", doors=7, stalls=20, side="west",
                                 street="State Hwy 95", car_street="Mill St", court=30)},
}
