"""MB2 pixel/geometry properties; no golden image or PNG hashes."""
from copy import deepcopy
from io import BytesIO

import numpy as np
from PIL import Image
import pytest

from tests.model_builder_test_support import gltf, module, recipe, reference, shape

printing, build = module("prints"), module("build")
normalize = module("recipe").normalize_recipe
Error = module("errors").ModelBuildError


def panel(items, *, size=(.2, .1), background="#ffffff", **fields):
    raw = shape("panel", size=list(size), print={"background": background, "items": items}, **fields)
    return normalize(recipe(raw))["entries"][0]


def pixels(artwork):
    with Image.open(BytesIO(artwork.data)) as image:
        image.load()
        assert image.mode == "RGB" and image.size == (artwork.width, artwork.height)
        assert image.info == {}
        return np.asarray(image).copy()


def ink_bounds(array, background=(255, 255, 255)):
    y, x = np.where(np.any(array != background, axis=2))
    assert len(x)
    return int(x.min()), int(y.min()), int(x.max())+1, int(y.max())+1


@pytest.mark.parametrize("align", ["left", "center", "right"])
def test_text_fits_and_aligns_inside_its_box(align):
    entry = panel([{"text": "F2\nLINE", "box": [.1, .2, .9, .8], "color": "#000000", "align": align}])
    artwork = printing.render_panel(entry)
    array = pixels(artwork)
    left, top, right, bottom = ink_bounds(array)
    x0, y0, x1, y1 = printing._pixel_box(entry["print"]["items"][0]["box"], artwork.width, artwork.height)
    assert x0 <= left < right <= x1 and y0 <= top < bottom <= y1
    if align == "left":
        assert abs(left-x0) <= 2
    elif align == "right":
        assert abs(right-x1) <= 2
    else:
        assert abs(left+right-x0-x1) <= 3
    assert artwork.clipped == []


def test_bold_is_heavier_and_three_lines_fit():
    item = {"text": "IIII", "box": [.1, .2, .9, .8], "color": "#000000"}
    regular = pixels(printing.render_panel(panel([item])))
    bold = pixels(printing.render_panel(panel([{**item, "weight": "bold"}])))
    assert np.sum(255-bold.astype(float)) > np.sum(255-regular.astype(float))
    three = printing.render_panel(panel([{**item, "text": "FIRST\nSECOND\nTHIRD"}]))
    assert three.clipped == []
    array = pixels(three)
    rows = np.any(array < 128, axis=(1, 2))
    assert np.count_nonzero(rows & ~np.r_[False, rows[:-1]]) == 3


def test_rows_of_equal_height_get_equal_type_size_whatever_their_letters():
    # A list on a screen: descenders and brackets must not shrink one row below its neighbours.
    rows = ["Product B x2", "Accessory kit (4) x1", "ITEMS", "gjpqy"]
    items = [{"text": text, "box": [.05, .1+.2*i, .95, .25+.2*i], "color": "#000000", "align": "left"}
             for i, text in enumerate(rows)]
    artwork = printing.render_panel(panel(items, size=(.4, .2)))
    assert artwork.clipped == []
    assert len({metric["fontSize"] for metric in artwork.text_metrics}) == 1
    array = pixels(artwork)
    for item in items:
        x0, y0, x1, y1 = printing._pixel_box(item["box"], artwork.width, artwork.height)
        left, top, right, bottom = ink_bounds(array[y0:y1, x0:x1])
        assert left <= 2 and 0 <= top and bottom <= y1-y0
    # A line too long for its box still shrinks on width.
    long_row = {**items[0], "text": "A much longer row of text that cannot fit at all"}
    wide = printing.render_panel(panel([long_row, items[1]], size=(.4, .2)))
    assert wide.text_metrics[0]["fontSize"] < wide.text_metrics[1]["fontSize"]


@pytest.mark.parametrize("size,expected", [((.36, .2), (900, 500)), ((.02, .01), (64, 32)),
                                          ((1, .5), (1024, 512))])
def test_size_aspect_background_and_clean_png(size, expected):
    artwork = printing.render_panel(panel([], size=size, background="#523420"))
    assert (artwork.width, artwork.height) == expected
    assert artwork.width/artwork.height == pytest.approx(size[0]/size[1])
    assert np.all(pixels(artwork) == [0x52, 0x34, 0x20])


def test_rect_rounding_stroke_line_and_physical_circle():
    rect = pixels(printing.render_panel(panel([{"rect": [.1, .1, .9, .9], "fill": "#ff0000",
                                               "stroke": "#000000", "lineMm": 2, "radiusMm": 10}])))
    assert tuple(rect[125, 250]) == (255, 0, 0)
    assert tuple(rect[25, 50]) == (255, 255, 255)
    assert tuple(rect[25, 250]) == (0, 0, 0)
    line = pixels(printing.render_panel(panel([{"line": [.1, .5, .9, .5], "color": "#0000ff", "lineMm": 2}])))
    assert tuple(line[125, 250]) == (0, 0, 255)
    assert 4 <= np.count_nonzero(np.any(line[:, 250] != 255, axis=1)) <= 6
    circle = pixels(printing.render_panel(panel([{"circle": [.5, .5, .1], "fill": "#00ff00",
                                                 "stroke": "#000000"}])))
    left, top, right, bottom = ink_bounds(circle)
    assert abs((right-left)-(bottom-top)) <= 1
    assert tuple(circle[125, 250]) == (0, 255, 0)
    assert tuple(circle[top, 250]) == (0, 0, 0)


def test_stripes_use_physical_width_angle_and_two_colors():
    item = {"stripes": [0, 0, 1, 1], "colors": ["#ff0000", "#0000ff"], "angleDegrees": 0, "widthMm": 10}
    vertical = pixels(printing.render_panel(panel([item])))
    horizontal = pixels(printing.render_panel(panel([{**item, "angleDegrees": 90}])))
    assert tuple(vertical[10, 10]) == (255, 0, 0)
    assert tuple(vertical[10, 35]) == (0, 0, 255)
    assert np.array_equal(vertical[10], vertical[100])
    assert tuple(horizontal[35, 10]) == (0, 0, 255)
    assert np.array_equal(horizontal[:, 10], horizontal[:, 100])


def test_dots_have_physical_pitch_and_radius_without_geometry():
    entry = panel([{"dots": {"area": [.1, .1, .9, .9], "pitchMm": 10, "radiusMm": 2, "color": "#000000"}}])
    array = pixels(printing.render_panel(entry))
    assert tuple(array[37, 62]) == tuple(array[62, 87]) == (0, 0, 0)
    assert tuple(array[37, 75]) == tuple(array[0, 0]) == (255, 255, 255)
    # Tiny pitch on a large panel stays bounded by raster pixels, not dot count.
    dense = panel([{"dots": {"area": [0, 0, 1, 1], "pitchMm": .5, "radiusMm": .1, "color": "#000000"}}], size=(30, 30))
    assert pixels(printing.render_panel(dense)).shape == (1024, 1024, 3)


def test_barcode_is_decorative_seeded_and_confined():
    item = {"barcode": [.1, .2, .9, .8], "seed": 123}
    first = printing.render_panel(panel([item], background="#808080"))
    second = printing.render_panel(panel([item], background="#808080"))
    other = printing.render_panel(panel([{**item, "seed": 124}], background="#808080"))
    assert first.data == second.data and first.data != other.data
    array = pixels(first)
    assert set(map(tuple, array[125, 50:450])) == {(0, 0, 0), (255, 255, 255)}
    assert np.array_equal(array[75, 50:450], array[175, 50:450])
    assert tuple(array[0, 0]) == (128, 128, 128)


def test_coverage_is_checked_even_at_the_renderer_seam():
    entry = panel([{"text": "Cafe", "box": [0, 0, 1, 1], "color": "#000000"}])
    entry["print"]["items"][0]["text"] = "Caf\u00e9"
    with pytest.raises(Error) as caught:
        printing.render_panel(entry)
    assert caught.value.code == "print_invalid" and "\u00e9" in caught.value.problem


def test_small_and_clipped_lints_and_a_clean_negative_case():
    small = panel([{"text": "SMALL", "box": [0, 0, 1, 1], "color": "#000000"}], size=(.01, .005))
    result = build.build_model(recipe(small))
    assert "print_small_text" in {p["code"] for p in result.lints}
    entry = panel([{"text": "NO ROOM", "box": [0, 0, .0001, .0001], "color": "#000000"},
                   {"rect": [-.1, .2, .3, .8], "fill": "#ff0000"}])
    result = build.build_model(recipe(entry))
    clipped = [p for p in result.lints if p["code"] == "print_clipped"]
    assert [p["item"] for p in clipped] == [0, 1]
    assert all(p["entryIds"] == ["body"] and p["instances"] == ["body[0]"] for p in clipped)
    clean = build.build_model(recipe(panel([{"text": "READ", "box": [.1, .1, .9, .9], "color": "#000000"}])))
    assert not any(p["code"].startswith("print_") for p in clean.lints)
    assert not clean.warnings


def test_print_lints_are_capped_and_measure_the_transformed_copy():
    items = [{"text": "A", "box": [0, 0, .001, .001], "color": "#000000"} for _ in range(24)]
    entry = panel(items, size=(.1, .1), scatter={"count": 2, "seed": 32,
        "within": {"min": [-.2, 0, -.2], "max": [.2, .2, .2]}, "sizeJitter": [.3, .3, .3]})
    result = build.build_model(recipe(entry))
    assert sum(p["code"] == "print_clipped" for p in result.lints) == 20
    assert sum(p["code"] == "print_small_text" for p in result.lints) == 20
    component = next(c for c in result.components if c.role == "print")
    artifact = result.prints["body"]
    expected = np.linalg.norm(component.mesh.positions[3]-component.mesh.positions[0])*1000
    expected *= artifact.text_metrics[0]["capHeightPixels"]/artifact.height
    lint = next(p for p in result.lints if p["code"] == "print_small_text")
    assert lint["capHeightMm"] == pytest.approx(expected, abs=1e-6)


def sample_front(mesh, array):
    """A front-facing camera follows the transformed panel up, without consulting UVs."""
    points = mesh.positions
    tri = mesh.indices[0]
    a, b, c = points[tri]
    up = points[3]-points[0]
    height = np.linalg.norm(up)
    up /= height
    normal = np.cross(b-a, c-a)
    normal /= np.linalg.norm(normal)
    right = np.cross(up, normal)
    width = np.linalg.norm(points[1]-points[0])
    h, w = array.shape[:2]
    x = (np.arange(w)+.5)/w-.5
    y = .5-(np.arange(h)+.5)/h
    target = points.mean(axis=0)+x[None, :, None]*width*right+y[:, None, None]*height*up
    coordinates = np.linalg.lstsq(np.column_stack((b-a, c-a)), (target.reshape(-1, 3)-a).T, rcond=None)[0].T
    uv = mesh.uv[tri[0]]+coordinates[:, :1]*(mesh.uv[tri[1]]-mesh.uv[tri[0]])+coordinates[:, 1:]*(mesh.uv[tri[2]]-mesh.uv[tri[0]])
    ix = np.clip(np.floor(uv[:, 0]*w+1e-7).astype(int), 0, w-1)
    iy = np.clip(np.floor(uv[:, 1]*h+1e-7).astype(int), 0, h-1)
    return array[iy, ix].reshape(h, w, 3)


@pytest.mark.parametrize("facing", ["+z", "-z", "+x", "-x", "+y"])
@pytest.mark.parametrize("operation", ["rotate", "mirror-x", "mirror-z", "group-around", "double-mirror"])
def test_asymmetric_print_samples_forward_after_every_transform(facing, operation):
    entry = panel([{"text": "F2", "box": [.05, .05, .85, .95], "color": "#000000"},
                   {"rect": [.9, .1, .98, .4], "fill": "#ff0000"}], size=(.12, .06), facing=facing)
    if operation == "rotate":
        entry["rotate"] = {"x": 25, "y": 70, "z": -17}
    elif operation.startswith("mirror-"):
        entry["mirror"] = {"plane": operation[-1]}
    elif operation == "group-around":
        entry = {"id": "assembly", "group": [entry], "rotate": {"x": 20, "y": 15, "z": 30},
                 "around": {"count": 2, "axis": "y", "center": [0, 0, 0], "degrees": 180}}
    else:
        entry["mirror"] = {"plane": "x"}
        entry = {"id": "assembly", "group": [entry], "mirror": {"plane": "z"}, "rotate": {"y": 30}}
    result = build.build_model(recipe(entry))
    source = pixels(result.prints["body"])
    for component in result.components:
        if component.role == "print":
            assert np.array_equal(sample_front(component.mesh, source), source)


@pytest.mark.parametrize("lit", [0, .6])
def test_artwork_is_neutral_and_lit_textures_share_the_print(lit):
    entry = panel([{"text": "DISPLAY", "box": [.1, .1, .9, .9], "color": "#ffffff"}], background="#523420")
    result = build.build_model(recipe(entry, materials={"paint": {"color": "#123456", "lit": lit}}))
    document = gltf(result.glb)
    front = next(m for m in document["materials"] if m["extras"].get("facilityArtwork"))
    back = next(m for m in document["materials"] if not m["extras"].get("facilityArtwork"))
    assert front["pbrMetallicRoughness"]["baseColorFactor"] == [1, 1, 1, 1]
    assert front["emissiveFactor"] == [lit]*3
    assert "facilityDefaultFinish" not in front["extras"]
    assert all(m["extras"]["facilityAuthoredFinish"] for m in document["materials"])
    if lit:
        assert front["emissiveTexture"] == front["pbrMetallicRoughness"]["baseColorTexture"]
    else:
        assert "emissiveTexture" not in front
    assert "baseColorTexture" not in back["pbrMetallicRoughness"]
    assert back["pbrMetallicRoughness"]["baseColorFactor"][:3] == module("imports").module("transforms").linear_color(entry["back"])
    assert back["emissiveFactor"] == [0, 0, 0]
    assert len(document["images"]) == len(document["textures"]) == 1
    view = printing.preview_model(result.model)
    original = next(m for m in result.model.materials if m.get("artwork"))
    preview = next(m for m in view.materials if m.get("artwork"))
    assert preview["unlit"] == bool(lit) and original["unlit"] is False


@pytest.mark.parametrize("name", ["baler-vertical-42", "gaylord-on-pallet", "pack-station-printer", "carrier-tag-ups"])
def test_reference_text_changes_pixels_only_in_its_declared_box(name):
    raw = normalize(reference(name))
    entries = module("protocol").panels(raw)
    if name == "pack-station-printer":
        assert len(entries["monitor-screen"]["print"]["items"]) == 24
        assert len(entries["scale-display"]["print"]["items"]) == 1
    fonts = printing.Fonts()
    for entry in entries.values():
        rendered = printing.render_panel(entry, fonts=fonts)
        full = pixels(rendered)
        assert rendered.clipped == []
        for index, item in enumerate(entry["print"]["items"]):
            if "text" not in item:
                continue
            without = deepcopy(entry)
            del without["print"]["items"][index]
            changed = np.any(full != pixels(printing.render_panel(without, fonts=fonts)), axis=2)
            left, top, right, bottom = printing._pixel_box(item["box"], rendered.width, rendered.height)
            assert changed[top:bottom, left:right].any(), (entry["id"], index)
            changed[top:bottom, left:right] = False
            assert not changed.any(), (entry["id"], index)
