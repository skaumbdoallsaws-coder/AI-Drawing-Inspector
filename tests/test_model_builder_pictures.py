"""MB4b picture properties. Run outside the low-memory sandbox."""
from dataclasses import replace
from io import BytesIO

import numpy as np
from PIL import Image
import pytest

from tests.model_builder_test_support import module, recipe, reference

builder = module("build")
reader = module("imports").module("reader")
pictures = module("pictures")


def image(data):
    with Image.open(BytesIO(data)) as opened:
        return np.array(opened.convert("RGB"))


@pytest.mark.parametrize("name", ["baler-vertical-42", "gaylord-on-pallet", "pack-station-printer",
                                  "carrier-tag-ups", "pallet-plain", "roll-cage-plain"])
def test_reference_contact_sheet_has_front_arrow_and_person_when_tall(name):
    built = builder.build_model(reference(name))
    assert built.lints == []
    restored = reader.read_model(built.glb, extended_materials=True)
    rendered = pictures.render_previews(restored)
    pixels = image(rendered.preview)
    assert pixels.shape == (768, 768, 3)
    assert np.count_nonzero(np.all(pixels[384:728, 384:] == [22, 84, 169], axis=2)) > 4
    person = np.count_nonzero(np.all(pixels[:384, 384:] == [35, 78, 112], axis=2))
    assert (person > 8) == (built.dimensions["height"] > .5)


def test_lit_screen_keeps_dark_text_and_focus_reframes_scale_display():
    built = builder.build_model(reference("pack-station-printer"))
    restored = reader.read_model(built.glb, extended_materials=True)
    normal = image(pictures.render_previews(restored).preview)
    blank_images = []
    for source in restored.images:
        with Image.new("RGB", (source.width, source.height), "white") as blank, BytesIO() as stream:
            blank.save(stream, format="PNG")
            blank_images.append(replace(source, data=stream.getvalue()))
    blank = image(pictures.render_previews(replace(restored, images=blank_images)).preview)
    # Ink survives even though the recipe's screen is lit. Compare the same
    # geometry with its texture replaced by white, avoiding model silhouettes.
    front = normal[:384, :384]
    ink = np.all(front < 100, axis=2) & np.all(blank[:384, :384] > 150, axis=2)
    assert np.count_nonzero(ink) > 20
    indices = [i for i, part in enumerate(restored.parts) if part.name == "scale display"]
    assert indices
    focused = image(pictures.render_previews(restored, focus_indices=indices, thumbnail=False).preview)
    assert not np.array_equal(front, focused[:384, :384])
    assert np.count_nonzero(np.all(focused[:384, :384] < 100, axis=2)) > 20


def test_import_preview_default_camera_bytes_are_unchanged_by_optional_frame():
    built = builder.build_model(reference("pallet-plain"))
    restored = reader.read_model(built.glb, extended_materials=True)
    geometry = module("imports").module("preview_geometry").build_geometry(restored)
    raster = module("imports").module("preview_raster")
    first = raster.rasterize(geometry, restored.images)
    second = raster.rasterize(geometry, restored.images, frame_box=None)
    assert np.array_equal(first, second)


def test_preview_uses_default_finish_base_color_and_print_keeps_its_image():
    raw = recipe()
    raw["materials"]["paint"]["finish"] = {"appearanceId": "paint-machine-gray"}
    built = builder.build_model(raw, allowed_appearance_ids=["paint-machine-gray"])
    restored = reader.read_model(built.glb, extended_materials=True)
    assert any(material.get("defaultFinish") for material in restored.materials)
    tinted = image(pictures.render_previews(restored, appearance_colors={"paint-machine-gray": "#ff0000"}).preview)
    untinted = image(pictures.render_previews(restored).preview)
    assert not np.array_equal(tinted, untinted)
    printed = reader.read_model(builder.build_model(reference("carrier-tag-ups")).glb, extended_materials=True)
    assert any(material.get("artwork") for material in printed.materials)
    assert pictures.render_previews(printed).preview
