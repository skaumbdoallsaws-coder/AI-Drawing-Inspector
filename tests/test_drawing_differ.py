"""Regression tests for drawing revision diff engine.

Tests the annotation matching, view matching, and verdict logic against
the golden expected-result fixture for 1030017 Rev A vs Rev B.
"""

import json
import sys
from pathlib import Path

import pytest

# Stub fitz (PyMuPDF) if not installed — required for ai_inspector import chain
if "fitz" not in sys.modules:
    sys.modules["fitz"] = type(sys)("fitz")

from ai_inspector.utils.drawing_map import normalize_drawing_map
from ai_inspector.comparison.drawing_differ import (
    compute_drawing_diff,
    _compute_ann_match_cost,
    _diff_annotations_for_view,
    _outline_diagonal,
    _DIFFABLE_ANNOTATION_TYPES,
    _ANN_MATCH_ABSTAIN,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

LIBRARY = Path(__file__).resolve().parent.parent / "400S_Sorted_Library"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "drawing_diff"


def _load_drawing_map(path: Path) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        raw = json.load(f)
    return normalize_drawing_map(raw, part_number="1030017")


@pytest.fixture(scope="module")
def map_a():
    return _load_drawing_map(LIBRARY / "parts" / "1030017" / "revA" / "1030017_drawing_map.json")


@pytest.fixture(scope="module")
def map_b():
    return _load_drawing_map(LIBRARY / "parts" / "1030017" / "revB" / "1030017_drawing_map.json")


@pytest.fixture(scope="module")
def map_c():
    return _load_drawing_map(LIBRARY / "parts" / "1030017" / "revC" / "1030017_drawing_map.json")


@pytest.fixture(scope="module")
def geometry_diff_ac():
    with open(LIBRARY / "parts" / "1030017" / "geometry_diff" / "A_vs_C" / "diff_result.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def diff_result(map_a, map_b):
    result = compute_drawing_diff(map_a, map_b)
    # Strip internals (same as server does)
    vi = result["viewIdentity"]
    vi.pop("_viewsA", None)
    vi.pop("_viewsB", None)
    return result


@pytest.fixture(scope="module")
def diff_result_ac(map_a, map_c):
    result = compute_drawing_diff(map_a, map_c)
    # Strip internals (same as server does)
    vi = result["viewIdentity"]
    vi.pop("_viewsA", None)
    vi.pop("_viewsB", None)
    return result


@pytest.fixture(scope="module")
def expected():
    with open(FIXTURES / "1030017_A_vs_B_expected.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def expected_ac():
    with open(FIXTURES / "1030017_A_vs_C_expected.json", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# View matching tests
# ---------------------------------------------------------------------------

class TestViewMatching:
    def test_matched_view_count(self, diff_result, expected):
        vi = diff_result["viewIdentity"]
        assert len(vi["matched"]) == expected["viewIdentity"]["totalMatchedViews"]

    def test_no_unmatched_views(self, diff_result, expected):
        vi = diff_result["viewIdentity"]
        assert len(vi["unmatchedBase"]) == expected["viewIdentity"]["totalUnmatchedBase"]
        assert len(vi["unmatchedTarget"]) == expected["viewIdentity"]["totalUnmatchedTarget"]

    def test_matched_view_keys(self, diff_result, expected):
        vi = diff_result["viewIdentity"]
        actual_keys = sorted(m["viewKey"] for m in vi["matched"])
        expected_keys = sorted(expected["viewIdentity"]["matchedViewKeys"])
        assert actual_keys == expected_keys

    def test_no_ambiguous_matches(self, diff_result, expected):
        vi = diff_result["viewIdentity"]
        assert len(vi["ambiguous"]) == expected["viewIdentity"]["totalAmbiguous"]


# ---------------------------------------------------------------------------
# Summary tests
# ---------------------------------------------------------------------------

class TestSummary:
    def test_matched_views(self, diff_result, expected):
        assert diff_result["summary"]["matchedViews"] == expected["summary"]["matchedViews"]

    def test_changed_views(self, diff_result, expected):
        assert diff_result["summary"]["changedViews"] == expected["summary"]["changedViews"]

    def test_annotation_counts(self, diff_result, expected):
        s = diff_result["summary"]
        e = expected["summary"]
        assert s["totalAnnotationsModified"] == e["totalAnnotationsModified"]
        assert s["totalAnnotationsRemoved"] == e["totalAnnotationsRemoved"]
        assert s["totalAnnotationsAdded"] == e["totalAnnotationsAdded"]


# ---------------------------------------------------------------------------
# Per-view interpretation tests
# ---------------------------------------------------------------------------

class TestPerViewInterpretations:
    def test_all_interpretations_match(self, diff_result, expected):
        findings = diff_result["userFacingFindings"]["perView"]
        for vk, exp_interp in expected["perViewInterpretations"].items():
            assert vk in findings, f"Missing viewKey {vk} in findings"
            assert findings[vk]["interpretation"] == exp_interp, (
                f"{vk}: expected {exp_interp}, got {findings[vk]['interpretation']}"
            )

    def test_changed_view_set(self, diff_result, expected):
        findings = diff_result["userFacingFindings"]["perView"]
        actual_changed = sorted(
            vk for vk, f in findings.items()
            if f["interpretation"] not in ("unchanged", "not_compared")
        )
        assert actual_changed == sorted(expected["changedViewKeys"])

    def test_unchanged_view_set(self, diff_result, expected):
        findings = diff_result["userFacingFindings"]["perView"]
        actual_unchanged = sorted(
            vk for vk, f in findings.items()
            if f["interpretation"] == "unchanged"
        )
        assert actual_unchanged == sorted(expected["unchangedViewKeys"])


# ---------------------------------------------------------------------------
# Per-view annotation diff tests
# ---------------------------------------------------------------------------

class TestAnnotationDiff:
    def test_drawing_view1_modified_text(self, diff_result, expected):
        """Drawing View1: RD1 dimension text changed."""
        vk = "Drawing View1@Sheet1"
        diff = diff_result["annotationDiff"]["perView"][vk]
        exp = expected["perViewAnnotationDiff"][vk]
        assert len(diff["modified"]) == exp["modified"]
        assert len(diff["added"]) == exp["added"]
        assert len(diff["removed"]) == exp["removed"]
        # Verify the specific modification
        mod = diff["modified"][0]
        assert mod["annotationNameA"] == "RD1"
        assert mod["annotationNameB"] == "RD1"
        changed_fields = [c["field"] for c in mod["changes"]]
        assert "dimensionText" in changed_fields

    def test_drawing_view2_changes(self, diff_result, expected):
        """Drawing View2: RD3 removed, DetailItem666 note added."""
        vk = "Drawing View2@Sheet1"
        diff = diff_result["annotationDiff"]["perView"][vk]
        exp = expected["perViewAnnotationDiff"][vk]
        assert len(diff["removed"]) == exp["removed"]
        assert len(diff["added"]) == exp["added"]
        assert len(diff["modified"]) == exp["modified"]
        assert diff["unchangedCount"] == exp["unchanged"]
        # Verify the specific removal
        removed_names = [r["annotationName"] for r in diff["removed"]]
        assert "RD3" in removed_names
        # Verify the added note (BREAK SHARP EDGES, now correctly classified as note)
        added_names = [a["annotationName"] for a in diff["added"]]
        assert "DetailItem666" in added_names
        added_note = [a for a in diff["added"] if a["annotationName"] == "DetailItem666"][0]
        assert added_note["annotationType"] == "note"

    def test_detail_view_b_unchanged(self, diff_result, expected):
        """Detail View B: isReference-only change suppressed — treated as unchanged."""
        vk = "Detail View B (1 : 1)@Sheet1"
        diff = diff_result["annotationDiff"]["perView"][vk]
        exp = expected["perViewAnnotationDiff"][vk]
        assert len(diff["modified"]) == 0, "isReference-only change should be suppressed"
        assert diff["unchangedCount"] == exp["unchanged"]

    def test_section_view_unchanged(self, diff_result, expected):
        """Section View C-C: fully unchanged."""
        vk = "Section View C-C@Sheet1"
        diff = diff_result["annotationDiff"]["perView"][vk]
        exp = expected["perViewAnnotationDiff"][vk]
        assert len(diff["added"]) == 0
        assert len(diff["removed"]) == 0
        assert len(diff["modified"]) == 0
        assert diff["unchangedCount"] == exp["unchanged"]

    def test_all_view_counts_match_fixture(self, diff_result, expected):
        """All views: annotation counts match fixture."""
        for vk, exp in expected["perViewAnnotationDiff"].items():
            diff = diff_result["annotationDiff"]["perView"].get(vk)
            assert diff is not None, f"Missing {vk} in annotationDiff"
            assert len(diff["added"]) == exp["added"], f"{vk} added"
            assert len(diff["removed"]) == exp["removed"], f"{vk} removed"
            assert len(diff["modified"]) == exp["modified"], f"{vk} modified"
            assert diff["unchangedCount"] == exp["unchanged"], f"{vk} unchanged"


# ---------------------------------------------------------------------------
# Annotation matching quality tests (unit-level)
# ---------------------------------------------------------------------------

class TestAnnotationMatchingQuality:
    def test_same_name_same_position_low_cost(self):
        """Two annotations with same name and position should have low cost."""
        ann_a = {
            "annotationType": "displayDimension",
            "annotationName": "RD1",
            "positionSheet": {"x": 0.17, "y": 0.50},
            "dimensionValue": 0.254,
            "dimensionText": "254.00",
        }
        ann_b = dict(ann_a)  # identical
        cost = _compute_ann_match_cost(ann_a, ann_b, view_diagonal=0.1)
        assert cost < 0.1, f"Identical annotations should have near-zero cost, got {cost}"

    def test_different_type_infinite_cost(self):
        """Different annotation types should be hard-gated."""
        ann_a = {"annotationType": "displayDimension", "annotationName": "RD1"}
        ann_b = {"annotationType": "note", "annotationName": "N1"}
        cost = _compute_ann_match_cost(ann_a, ann_b, view_diagonal=0.1)
        assert cost >= 1e5, "Different types should have infinite cost"

    def test_same_name_different_value_moderate_cost(self):
        """Same name, large value change should have moderate cost (still matches)."""
        ann_a = {
            "annotationType": "displayDimension",
            "annotationName": "RD1",
            "positionSheet": {"x": 0.17, "y": 0.50},
            "dimensionValue": 0.254,
            "dimensionText": "254.00",
        }
        ann_b = {
            "annotationType": "displayDimension",
            "annotationName": "RD1",
            "positionSheet": {"x": 0.17, "y": 0.50},
            "dimensionValue": 0.260,
            "dimensionText": "260.00",
        }
        cost = _compute_ann_match_cost(ann_a, ann_b, view_diagonal=0.1)
        assert 0.1 < cost < 1.0, f"Same name, different value should be moderate cost, got {cost}"

    def test_different_name_far_position_high_cost(self):
        """Different name and far position should have high cost."""
        ann_a = {
            "annotationType": "displayDimension",
            "annotationName": "RD1",
            "positionSheet": {"x": 0.10, "y": 0.10},
            "dimensionValue": 0.050,
        }
        ann_b = {
            "annotationType": "displayDimension",
            "annotationName": "RD5",
            "positionSheet": {"x": 0.80, "y": 0.80},
            "dimensionValue": 0.200,
        }
        cost = _compute_ann_match_cost(ann_a, ann_b, view_diagonal=0.1)
        assert cost > _ANN_MATCH_ABSTAIN, f"Unrelated annotations should exceed abstain threshold, got {cost}"

    def test_abstention_on_truly_ambiguous_input(self):
        """When two A annotations have the SAME name and are equidistant to one B,
        the ambiguity gap rule should prevent forcing one of them into a match
        if neither has a strong cost advantage."""
        # Both A annotations have the same generic name and identical values.
        # Neither has a name advantage — the only differentiator is position,
        # and both are equidistant from B. This is a truly ambiguous case.
        ann_a1 = {
            "annotationType": "displayDimension",
            "annotationName": "D1",
            "positionSheet": {"x": 0.200, "y": 0.400},
            "dimensionValue": 0.050,
            "dimensionText": "50.00",
        }
        ann_a2 = {
            "annotationType": "displayDimension",
            "annotationName": "D1",
            "positionSheet": {"x": 0.210, "y": 0.400},
            "dimensionValue": 0.050,
            "dimensionText": "50.00",
        }
        ann_b1 = {
            "annotationType": "displayDimension",
            "annotationName": "D1",
            "positionSheet": {"x": 0.205, "y": 0.400},
            "dimensionValue": 0.050,
            "dimensionText": "50.00",
        }
        result = _diff_annotations_for_view(
            [ann_a1, ann_a2], [ann_b1], view_diagonal=0.5
        )
        # With Hungarian, one of the two A's will be assigned to B at very low cost.
        # The other A should remain unmatched (removed), NOT forced into a bad match.
        total_matched = result["unchangedCount"] + len(result["modified"])
        assert total_matched <= 1, "At most one A should match the single B"
        assert len(result["removed"]) >= 1, "The unmatched A should appear as removed"

    def test_added_annotation_detected(self):
        """When B has an annotation that A does not, it should appear as added."""
        ann_a1 = {
            "annotationType": "displayDimension",
            "annotationName": "RD1",
            "positionSheet": {"x": 0.10, "y": 0.50},
            "dimensionValue": 0.025,
            "dimensionText": "25.00",
        }
        # B has the same annotation PLUS a new note
        ann_b1 = {
            "annotationType": "displayDimension",
            "annotationName": "RD1",
            "positionSheet": {"x": 0.10, "y": 0.50},
            "dimensionValue": 0.025,
            "dimensionText": "25.00",
        }
        ann_b2 = {
            "annotationType": "note",
            "annotationName": "Note1",
            "positionSheet": {"x": 0.30, "y": 0.20},
            "noteText": "BREAK SHARP EDGES",
        }
        result = _diff_annotations_for_view(
            [ann_a1], [ann_b1, ann_b2], view_diagonal=0.3
        )
        assert result["unchangedCount"] == 1, "RD1 should match as unchanged"
        assert len(result["added"]) == 1, "Note1 should be added"
        assert result["added"][0]["annotationName"] == "Note1"
        assert result["added"][0]["annotationType"] == "note"
        assert result["hasChanges"] is True

    def test_removed_annotation_detected(self):
        """When A has an annotation that B does not, it should appear as removed."""
        ann_a1 = {
            "annotationType": "displayDimension",
            "annotationName": "RD1",
            "positionSheet": {"x": 0.10, "y": 0.50},
            "dimensionValue": 0.025,
            "dimensionText": "25.00",
        }
        ann_a2 = {
            "annotationType": "surfaceFinish",
            "annotationName": "SF1",
            "positionSheet": {"x": 0.40, "y": 0.30},
            "noteText": "Ra 1.6",
        }
        ann_b1 = {
            "annotationType": "displayDimension",
            "annotationName": "RD1",
            "positionSheet": {"x": 0.10, "y": 0.50},
            "dimensionValue": 0.025,
            "dimensionText": "25.00",
        }
        result = _diff_annotations_for_view(
            [ann_a1, ann_a2], [ann_b1], view_diagonal=0.3
        )
        assert result["unchangedCount"] == 1, "RD1 should match as unchanged"
        assert len(result["removed"]) == 1, "SF1 should be removed"
        assert result["removed"][0]["annotationName"] == "SF1"
        assert result["hasChanges"] is True


# ---------------------------------------------------------------------------
# Self-diff sanity test
# ---------------------------------------------------------------------------

class TestSelfDiff:
    def test_self_diff_has_no_changes(self, map_a):
        """Diffing a map against itself should produce zero changes."""
        result = compute_drawing_diff(map_a, map_a)
        s = result["summary"]
        assert s["changedViews"] == 0
        assert s["totalAnnotationsModified"] == 0
        assert s["totalAnnotationsRemoved"] == 0
        assert s["totalAnnotationsAdded"] == 0
        assert s["matchedViews"] > 0


# ---------------------------------------------------------------------------
# Rev A vs Rev C checkpoint regression
# ---------------------------------------------------------------------------

class TestRevACCheckpoint:
    def test_a_vs_c_summary_matches_checkpoint(self, diff_result_ac, expected_ac):
        """Rev C should expose one annotation change and two exact-geometry views."""
        s = diff_result_ac["summary"]
        e = expected_ac["summary"]
        for key in (
            "matchedViews",
            "totalAnnotationsModified",
            "totalAnnotationsRemoved",
            "totalAnnotationsAdded",
            "geometryDiffAvailable",
        ):
            assert s[key] == e[key], key
        assert s["changedViews"] == 2
        assert s["annotationOnlyChanges"] == 0
        assert s["nativeGeometryDiffAvailable"] is True
        assert s["totalNativeGeometryAdded"] == 5
        assert s["totalNativeGeometryRemoved"] == 5

    def test_a_vs_c_changed_view_set(self, diff_result_ac, expected_ac):
        findings = diff_result_ac["userFacingFindings"]["perView"]
        actual_changed = sorted(
            vk for vk, f in findings.items()
            if f["interpretation"] not in ("unchanged", "not_compared")
        )
        assert actual_changed == sorted([
            "Drawing View1@Sheet1",
            "Detail View B (1 : 1)@Sheet1",
        ])

    def test_a_vs_c_only_rd1_is_modified(self, diff_result_ac, expected_ac):
        """Only the main four-hole callout should be modified from A to C."""
        vk = "Drawing View1@Sheet1"
        diff = diff_result_ac["annotationDiff"]["perView"][vk]
        exp = expected_ac["perViewAnnotationDiff"][vk]
        assert len(diff["modified"]) == exp["modified"]
        assert len(diff["added"]) == exp["added"]
        assert len(diff["removed"]) == exp["removed"]

        mod = diff["modified"][0]
        assert mod["annotationNameA"] == "RD1"
        assert mod["annotationNameB"] == "RD1"
        changed_fields = [c["field"] for c in mod["changes"]]
        assert changed_fields == ["dimensionValue", "dimensionText"]

    def test_a_vs_c_detail_view_b_typ_is_not_false_positive(self, diff_result_ac, expected_ac):
        """25.40 TYP in Detail View B is unchanged and should not be highlighted."""
        vk = "Detail View B (1 : 1)@Sheet1"
        diff = diff_result_ac["annotationDiff"]["perView"][vk]
        exp = expected_ac["perViewAnnotationDiff"][vk]
        assert len(diff["added"]) == exp["added"]
        assert len(diff["removed"]) == exp["removed"]
        assert len(diff["modified"]) == exp["modified"]
        assert diff["unchangedCount"] == exp["unchanged"]


class TestProjectedModelDelta:
    def test_bbox_projection_emits_sheet_bounds(self, map_a, map_c, geometry_diff_ac):
        geo = json.loads(json.dumps(geometry_diff_ac))
        geo["changed_regions"] = [{
            "type": "removed",
            "centroid": [0.0, 0.0, 25.4],
            "bbox": {
                "min": [-12.7, -12.7, 0.0],
                "max": [12.7, 12.7, 50.8],
                "extents": [25.4, 25.4, 50.8],
            },
            "volume_mm3": 24131.944,
        }]

        result = compute_drawing_diff(map_a, map_c, geometry_diff=geo)
        view_delta = result["geometryDiff"]["perView"]["Drawing View1@Sheet1"]

        assert view_delta["deltaPresent"] is True
        assert len(view_delta["projectedRegions"]) >= 1
        region = view_delta["projectedRegions"][0]
        assert region["source"] == "bbox_projection"
        assert "sheetBounds" in region
        assert len(region["sheetBounds"]) == 4

    def test_centroid_projection_still_falls_back_without_bbox(self, map_a, map_c, geometry_diff_ac):
        geo = json.loads(json.dumps(geometry_diff_ac))
        geo.pop("changed_regions", None)
        geo["changed_centroids"] = [{
            "type": "removed",
            "centroid": [0.0, 0.0, 25.4],
            "volume_mm3": 24131.944,
        }]

        result = compute_drawing_diff(map_a, map_c, geometry_diff=geo)
        view_delta = result["geometryDiff"]["perView"]["Drawing View1@Sheet1"]

        assert view_delta["deltaPresent"] is True
        assert len(view_delta["projectedRegions"]) >= 1
        region = view_delta["projectedRegions"][0]
        assert region["source"] == "centroid_projection"
        assert "sheetBounds" not in region

    def test_secondary_projection_views_are_suppressed_for_display(self, map_a, map_c, geometry_diff_ac):
        result = compute_drawing_diff(map_a, map_c, geometry_diff=geometry_diff_ac)
        geom = result["geometryDiff"]["perView"]

        # Keep primary/front-view evidence where the annotation also changed.
        assert len(geom["Drawing View1@Sheet1"]["projectedRegions"]) == 4

        # Secondary top/right projections remain part of verdict reasoning
        # (deltaPresent stays True), but their advisory boxes are suppressed
        # from the UI because they are weaker duplicate evidence.
        assert geom["Drawing View2@Sheet1"]["deltaPresent"] is True
        assert geom["Drawing View3@Sheet1"]["deltaPresent"] is True
        assert geom["Drawing View2@Sheet1"]["projectedRegions"] == []
        assert geom["Drawing View3@Sheet1"]["projectedRegions"] == []


class TestNativeGeometryDiff:
    @staticmethod
    def _map_with_primitives(points_view, points_sheet):
        return normalize_drawing_map(
            {
                "partNumber": "2000001",
                "sheetWidth": 0.4318,
                "sheetHeight": 0.2794,
                "sheets": [
                    {
                        "sheetName": "Sheet1",
                        "sheetWidth": 0.4318,
                        "sheetHeight": 0.2794,
                        "views": [
                            {
                                "viewName": "Drawing View1",
                                "viewType": "Standard",
                                "viewOrientation": "Front",
                                "viewScale": 1.0,
                                "viewOutline": [0.05, 0.05, 0.20, 0.20],
                                "viewPosition": [0.125, 0.125],
                                "annotations": [],
                                "primitives": [
                                    {
                                        "primitiveType": "line",
                                        "sourceKind": "modelEdge",
                                        "geometrySource": "exact",
                                        "boundsView": [min(p[0] for p in points_view), min(p[1] for p in points_view), max(p[0] for p in points_view), max(p[1] for p in points_view)],
                                        "boundsSheet": [min(p[0] for p in points_sheet), min(p[1] for p in points_sheet), max(p[0] for p in points_sheet), max(p[1] for p in points_sheet)],
                                        "pointsView": points_view,
                                        "pointsSheet": points_sheet,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )

    def test_native_geometry_diff_detects_shifted_line(self):
        map_a = self._map_with_primitives(
            points_view=[[-0.02, 0.00], [0.02, 0.00]],
            points_sheet=[[0.10, 0.12], [0.14, 0.12]],
        )
        map_b = self._map_with_primitives(
            points_view=[[-0.02, 0.01], [0.02, 0.01]],
            points_sheet=[[0.10, 0.13], [0.14, 0.13]],
        )

        result = compute_drawing_diff(map_a, map_b)
        native = result["nativeGeometryDiff"]["perView"]["Drawing View1@Sheet1"]
        finding = result["userFacingFindings"]["perView"]["Drawing View1@Sheet1"]

        assert result["nativeGeometryDiff"]["available"] is True
        assert native["hasChanges"] is True
        assert len(native["removed"]) == 1
        assert len(native["added"]) == 1
        assert finding["evidence"]["nativeGeometryDeltaPresent"] is True
        assert finding["interpretation"] == "native_geometry_changed"

    def test_native_geometry_diff_ignores_identical_line(self):
        map_a = self._map_with_primitives(
            points_view=[[-0.02, 0.00], [0.02, 0.00]],
            points_sheet=[[0.10, 0.12], [0.14, 0.12]],
        )
        map_b = self._map_with_primitives(
            points_view=[[-0.02, 0.00], [0.02, 0.00]],
            points_sheet=[[0.10, 0.12], [0.14, 0.12]],
        )

        result = compute_drawing_diff(map_a, map_b)
        native = result["nativeGeometryDiff"]["perView"]["Drawing View1@Sheet1"]

        assert native["hasChanges"] is False
        assert native["removed"] == []
        assert native["added"] == []
        assert result["summary"]["totalNativeGeometryAdded"] == 0
        assert result["summary"]["totalNativeGeometryRemoved"] == 0


class TestNativeGeometryPriority:
    def test_holder_a_vs_c_prioritizes_front_and_detail_views(self, map_a, map_c, geometry_diff_ac):
        result = compute_drawing_diff(map_a, map_c, geometry_diff=geometry_diff_ac)
        priority = result["nativeGeometryPriority"]

        assert priority["extractNowViewKeys"] == ["Drawing View1@Sheet1"]
        assert "Detail View B (1 : 1)@Sheet1" in priority["considerViewKeys"]
        assert priority["preferredExtractionOrder"][:2] == [
            "Drawing View1@Sheet1",
            "Detail View B (1 : 1)@Sheet1",
        ]

    def test_holder_a_vs_c_suppressed_projection_views_are_skipped(self, map_a, map_c, geometry_diff_ac):
        result = compute_drawing_diff(map_a, map_c, geometry_diff=geometry_diff_ac)
        priority = result["nativeGeometryPriority"]["perView"]

        for vk in ("Drawing View2@Sheet1", "Drawing View3@Sheet1"):
            assert priority[vk]["tier"] == "skip"
            assert "projected_model_delta_present_but_suppressed" in priority[vk]["reasons"]
            assert "projection_weaker_than_other_views" in priority[vk]["reasons"]

    def test_holder_a_vs_c_section_view_remains_unsupported(self, map_a, map_c, geometry_diff_ac):
        result = compute_drawing_diff(map_a, map_c, geometry_diff=geometry_diff_ac)
        section = result["nativeGeometryPriority"]["perView"]["Section View C-C@Sheet1"]

        assert section["tier"] == "skip"
        assert section["signals"]["nativeGeometrySupported"] is False
        assert "view_family_section_not_supported_for_native_geometry" in section["reasons"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
