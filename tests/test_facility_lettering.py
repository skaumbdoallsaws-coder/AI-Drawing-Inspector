from copy import deepcopy

import pytest

from ai_inspector.facility_layout.decals import normalize_lettering
from tests.test_facility_decals import apply, art, document


def lettering():
    return dict(text="Build with purpose", reference="APEX", font="Arial", align="center", color="#C99B39")


def test_lettering_is_editable_and_preserves_geometry():
    before = document()
    after = apply(before, [art(lettering=lettering())])
    record = after["extensions"]["facilityDecals"]["artworks"][0]
    assert record["lettering"]["color"] == "#c99b39"
    assert after["placements"] == before["placements"]
    assert after["extensions"]["facilityPerimeterWalls"] == before["extensions"]["facilityPerimeterWalls"]
    changed = deepcopy(record)
    changed["lettering"]["text"] = "Revised text"
    assert apply(after, [changed])["extensions"]["facilityDecals"]["artworks"][0]["lettering"]["text"] == "Revised text"


@pytest.mark.parametrize("key,value", [("text", ""), ("text", "a"*1001), ("text", "\n"*16),
    ("text", "bad\x00"), ("reference", "a"*161), ("font", "../../font"), ("align", "justify"), ("color", "gold")])
def test_invalid_lettering_rejected(key, value):
    settings = lettering()
    settings[key] = value
    with pytest.raises(ValueError):
        normalize_lettering(settings)
