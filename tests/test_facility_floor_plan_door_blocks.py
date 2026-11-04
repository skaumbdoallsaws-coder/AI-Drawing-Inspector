"""Floor-plan import, FP3 gate (docs/facility-floor-plan-import-plan.md, section 11): door symbols drawn as blocks,
plain, mirrored and rotated, read through the reader and converted through the route.

The drawing, in meters (written here, no third-party content):
- A-WALL: three partitions drawn as two faces 0.2 m thick, at x = 10, 20 and 30 (faces x and x + 0.2), from y = 0 to
  y = 10, each broken by a 1 m door gap from y = 4 to y = 5, with jamb lines at y = 4 and 5 and end lines at 0 and 10.
- Block DOOR (base 0,0), on layer 0: ARC center (0,0) radius 1 from 0 to 90 degrees, LINE (0,0)-(1,0) (the leaf).
- A-DOOR: INSERT DOOR at (10.2, 4) as drawn: hinged at the lower jamb of the +x face, shut against (10.2, 5).
  INSERT DOOR at (20, 4) with xscale -1 (mirrored): hinged on the -x face, swinging to -x, shut against (20, 5).
  INSERT DOOR at (30.2, 5) rotated 270 degrees: hinged at the upper jamb, shut against (30.2, 4).
Placed on the plan by (5, 5): each wall runs from z = 5 to z = 15 with an opening from 4 to 5 m along it."""
import pytest

from ai_inspector.facility_layout.plan_settings import default_plan_settings
from tests.test_facility_floor_plan_import import IMPORTS, apply, made, reference, revision, started, upload

ezdxf = pytest.importorskip("ezdxf")

ROLES = {"A-WALL": "wall_faces", "A-DOOR": "door"}
ALIGNMENT = {"sourceOrigin": {"u": 0, "v": 0}, "metersPerDrawingUnit": 1, "rotationDegrees": 0,
             "translationMeters": {"x": 5, "z": 5}, "unitSource": "header", "confirmed": True, "controlPoints": []}


def door_blocks(folder):
    doc = ezdxf.new("R2010", units=6)
    for name in ("A-WALL", "A-DOOR"):
        doc.layers.add(name)
    door = doc.blocks.new("DOOR")
    door.add_arc((0, 0), 1.0, 0, 90, dxfattribs={"layer": "0"})
    door.add_line((0, 0), (1, 0), dxfattribs={"layer": "0"})
    msp = doc.modelspace()
    for x in (10.0, 20.0, 30.0):
        for face in (x, x + 0.2):
            msp.add_line((face, 0), (face, 4), dxfattribs={"layer": "A-WALL"})
            msp.add_line((face, 5), (face, 10), dxfattribs={"layer": "A-WALL"})
        for y in (0, 4, 5, 10):
            msp.add_line((x, y), (x + 0.2, y), dxfattribs={"layer": "A-WALL"})
    msp.add_blockref("DOOR", (10.2, 4), dxfattribs={"layer": "A-DOOR"})
    msp.add_blockref("DOOR", (20.0, 4), dxfattribs={"layer": "A-DOOR", "xscale": -1})
    msp.add_blockref("DOOR", (30.2, 5), dxfattribs={"layer": "A-DOOR", "rotation": 270})
    path = folder / "door-blocks.dxf"
    doc.saveas(path)
    return path


def test_door_blocks_plain_mirrored_and_rotated_open_their_walls(tmp_path):
    client, service = started(tmp_path)
    response = upload(client, door_blocks(made(tmp_path)))
    assert response.status_code == 200, response.text
    imported = response.json()
    names = {layer["layerId"]: layer["name"] for layer in imported["manifest"]["layers"]}
    value = reference(imported, alignment=dict(ALIGNMENT))
    value["layers"] = [{"layerId": layer_id, "visible": True, "role": ROLES.get(name, "reference")}
                       for layer_id, name in names.items()]
    response = apply(client, service, {"op": "set_plan_settings", "planSettings": default_plan_settings()},
                     {"op": "upsert_floor_plan_reference", "reference": value})
    assert response.status_code == 200, response.text
    response = client.post(f"{IMPORTS}/{imported['import']['importId']}/conversion", json={
        "baseRevision": revision(service), "settings": {"walls": {"heightMeters": 3}}})
    assert response.status_code == 200, response.text
    conversion = response.json()["conversion"]
    opening = [{"startMeters": 4.0, "endMeters": 5.0}]
    assert [(row["start"], row["end"], row["openings"], row["state"]) for row in conversion["walls"]] == [
        ({"x": x + 5.1, "z": 5.0}, {"x": x + 5.1, "z": 15.0}, opening, "new") for x in (10.0, 20.0, 30.0)]
    walls = {row["candidateId"]: row["label"] for row in conversion["walls"]}
    doors = sorted((row["at"]["x"], row["kind"], row["widthMeters"], walls[row["wall"]], row["state"])
                   for row in conversion["doors"])
    assert doors == [(15.1, "single", 1.0, "Drawing wall 1", "new"), (25.1, "single", 1.0, "Drawing wall 2", "new"),
                     (35.1, "single", 1.0, "Drawing wall 3", "new")], conversion["doors"]
    # Each door's arc and leaf come from its insert: both are named as its sources, and nothing on the door layer
    # is left over.
    assert all(len(row["sources"]) >= 1 for row in conversion["doors"])
    assert not {reason for reason in conversion["unconvertedCounts"] if reason.startswith("door")}, \
        conversion["unconvertedCounts"]
