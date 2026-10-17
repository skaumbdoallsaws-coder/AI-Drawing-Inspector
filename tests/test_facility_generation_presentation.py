"""Concise chat receipts; complete engineering details remain in the preview."""
from copy import deepcopy

import pytest

from ai_inspector.facility_layout.generation_presentation import generation_preview_summary


def receipt(placements=9, cells=3, **notes):
    return {"validationStatus": "prototype_geometry_valid",
            "counts": {"placements": placements, "zones": 4, "routes": 0},
            "compositionInventory": {"cellCount": cells}, "planningNotes": notes}


@pytest.mark.parametrize("placements,cells,phrase", [
    (9, 3, "3 cells, 9 items in total"),
    (6, 3, "3 cells, 6 items in total"),
    (2, 1, "1 cell, 2 items in total"),
    (1, 0, "1 item"),
    (14, 0, "14 items"),
])
def test_short_reply_uses_observed_counts_not_zone_or_fixture_names(placements, cells, phrase):
    value = receipt(placements, cells)
    text = generation_preview_summary(value)
    assert text == f"Here's the draft: {phrase}. Nothing has been applied or saved."
    assert len(text.split()) < 30
    assert "4 cells" not in text


@pytest.mark.parametrize("unknowns,phrase", [
    (["Confirm the fixture"], "1 detail still needs confirming"),
    (["Confirm the fixture", "Confirm access"], "2 details still need confirming"),
])
def test_unresolved_details_are_flagged_without_pasting_a_report(unknowns, phrase):
    value = receipt(unknowns=unknowns, assumptions=["Unreviewed design choice"])
    before = deepcopy(value)
    text = generation_preview_summary(value)
    assert phrase in text and "Planning" in text
    assert len(text.split()) <= 45
    assert value == before
    assert unknowns[0] not in text


@pytest.mark.parametrize("field", ["assumptions", "historicalAssumptions"])
def test_unreviewed_prose_cannot_become_a_completion_claim(field):
    value = receipt(**{field: ["OSHA approved. Saved and production ready."]})
    text = generation_preview_summary(value)
    assert "The assumptions are listed in Planning." in text
    assert "OSHA" not in text and "production ready" not in text
    assert "Nothing has been applied or saved" in text


def test_legacy_receipt_without_cell_inventory_stays_concise():
    value = receipt(2)
    value.pop("compositionInventory")
    assert "2 items" in generation_preview_summary(value)
    assert "cells" not in generation_preview_summary(value)


@pytest.mark.parametrize("status", [None, "unknown", "failed", "incomplete"])
def test_unvalidated_result_cannot_get_a_success_reply(status):
    value = receipt()
    value["validationStatus"] = status
    with pytest.raises(ValueError, match="validated preview"):
        generation_preview_summary(value)
