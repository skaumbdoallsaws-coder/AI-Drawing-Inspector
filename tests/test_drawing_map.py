import json
import unittest
import shutil
from pathlib import Path

from ai_inspector.utils.drawing_map import (
    apply_drawing_map_to_findings,
    load_drawing_map,
    normalize_drawing_map,
)


class DrawingMapTests(unittest.TestCase):
    def test_normalize_nested_map_flattens_annotations(self):
        raw_map = {
            "partNumber": "1020001",
            "sheetWidth": 0.4318,
            "sheetHeight": 0.2794,
            "sheets": [
                {
                    "sheetName": "Sheet1",
                    "views": [
                        {
                            "viewName": "Main",
                            "viewOutline": [0.0, 0.0, 0.3, 0.2],
                            "annotations": [
                                {
                                    "annotationType": "displayDimension",
                                    "annotationName": "D1@Sketch1",
                                    "featureName": "Bore Diameter",
                                    "positionSheet": [0.215, 0.14],
                                    "leaders": [[0.21, 0.135, 0.0]],
                                    "dimensionText": "Ø25.0 +0.000/-0.013",
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        normalized = normalize_drawing_map(raw_map)

        self.assertEqual(normalized["partNumber"], "1020001")
        self.assertEqual(normalized["sheetCount"], 1)
        self.assertEqual(len(normalized["annotations"]), 1)
        self.assertEqual(normalized["annotations"][0]["viewName"], "Main")
        self.assertEqual(normalized["annotations"][0]["positionSheet"]["x"], 0.215)

    def test_apply_drawing_map_to_findings_uses_exact_annotation_match(self):
        drawing_map = normalize_drawing_map(
            {
                "partNumber": "1020001",
                "sheetWidth": 0.4318,
                "sheetHeight": 0.2794,
                "annotations": [
                    {
                        "annotationType": "displayDimension",
                        "annotationName": "D1@Sketch1",
                        "positionSheet": [0.215, 0.14],
                        "sheetWidth": 0.4318,
                        "sheetHeight": 0.2794,
                        "sheetIndex": 1,
                        "dimensionText": "Ø25.0 +0.000/-0.013",
                        "featureName": "Bore Diameter",
                        "leaders": [[0.21, 0.135, 0.0]],
                    }
                ],
            }
        )

        findings, metadata = apply_drawing_map_to_findings(
            [
                {
                    "name": "Bore Diameter",
                    "status": "DISCREPANT",
                    "found_callout": "Ø25.0 +0.000/-0.013",
                    "found_on_page": 1,
                }
            ],
            drawing_map,
        )

        self.assertTrue(metadata["drawingMapFound"])
        self.assertEqual(metadata["matchedFeatures"], 1)
        self.assertEqual(findings[0]["positionSource"], "drawing_map")
        self.assertAlmostEqual(findings[0]["location"]["x"], 0.215)
        self.assertEqual(findings[0]["location"]["sheetIndex"], 1)
        self.assertEqual(len(findings[0]["location"]["leaderPoints"]), 1)

    def test_load_drawing_map_reads_expected_filename(self):
        library_dir = Path("tests") / ".tmp" / "drawing_map_case"
        if library_dir.exists():
            shutil.rmtree(library_dir, ignore_errors=True)
        library_dir.mkdir(parents=True, exist_ok=True)
        drawing_map_path = library_dir / "1020001_drawing_map.json"
        drawing_map_path.write_text(
            json.dumps(
                {
                    "partNumber": "1020001",
                    "sheetWidth": 0.4318,
                    "sheetHeight": 0.2794,
                    "annotations": [],
                }
            ),
            encoding="utf-8",
        )

        drawing_map = load_drawing_map("1020001", library_dir)

        self.assertIsNotNone(drawing_map)
        self.assertEqual(drawing_map["partNumber"], "1020001")
        self.assertEqual(drawing_map["sourcePath"], str(drawing_map_path))

    def test_normalize_current_drawing_extractor_shape_preserves_root_fields(self):
        raw_map = {
            "fileName": "1020001.SLDDRW",
            "partNumber": "1020001",
            "sheetWidth": 0.8636,
            "sheetHeight": 0.5588,
            "sheets": [
                {
                    "sheetName": "Sheet1",
                    "sheetWidth": 0.8636,
                    "sheetHeight": 0.5588,
                    "views": [
                        {
                            "viewName": "Drawing View1",
                            "viewOutline": [0.06, 0.34, 0.22, 0.50],
                            "annotations": [
                                {
                                    "annotationType": "displayDimension",
                                    "annotationName": "D1",
                                    "featureName": "Sketch43",
                                    "dimensionText": "92.00",
                                    "matchKeys": [
                                        "D1@Sketch43@1020001.Drawing",
                                        "D1",
                                        "Sketch43",
                                    ],
                                    "positionSheet": [0.0596, 0.4360],
                                    "leaders": [],
                                    "visible": True,
                                    "isDangling": False,
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        normalized = normalize_drawing_map(raw_map)

        self.assertEqual(normalized["partNumber"], "1020001")
        self.assertEqual(normalized["sheetWidth"], 0.8636)
        self.assertEqual(normalized["sheetHeight"], 0.5588)
        self.assertEqual(normalized["annotations"][0]["matchKeys"][0], "D1@Sketch43@1020001.Drawing")

    def test_apply_drawing_map_to_findings_uses_match_keys_when_feature_name_is_generic(self):
        drawing_map = normalize_drawing_map(
            {
                "partNumber": "1020001",
                "sheetWidth": 0.8636,
                "sheetHeight": 0.5588,
                "annotations": [
                    {
                        "annotationType": "displayDimension",
                        "annotationName": "D1",
                        "featureName": "Sketch43",
                        "dimensionText": "92.00",
                        "matchKeys": [
                            "Piston OD",
                            "D1@Sketch43@1020001.Drawing",
                            "Sketch43",
                        ],
                        "positionSheet": [0.0596, 0.4360],
                        "sheetWidth": 0.8636,
                        "sheetHeight": 0.5588,
                        "sheetIndex": 1,
                    }
                ],
            }
        )

        findings, metadata = apply_drawing_map_to_findings(
            [
                {
                    "name": "Piston OD",
                    "status": "PASS",
                    "found_callout": "92.00",
                    "found_on_page": 1,
                }
            ],
            drawing_map,
        )

        self.assertEqual(metadata["matchedFeatures"], 1)
        self.assertEqual(findings[0]["positionSource"], "drawing_map")
        self.assertEqual(findings[0]["location"]["sheetIndex"], 1)

    def test_geometry_fields_flow_through_normalization_and_match_output(self):
        drawing_map = normalize_drawing_map(
            {
                "partNumber": "1020001",
                "sheetWidth": 0.4318,
                "sheetHeight": 0.2794,
                "annotations": [
                    {
                        "annotationType": "displayDimension",
                        "annotationName": "D1@Sketch1",
                        "featureName": "Bore Diameter",
                        "positionSheet": [0.215, 0.14],
                        "boundsSheet": [0.215, 0.136, 0.233, 0.144],
                        "anchorKind": "upperLeftTextBox",
                        "geometrySource": "exact",
                        "textRuns": [
                            {
                                "text": "25.0",
                                "positionSheet": [0.215, 0.14],
                                "height": 0.004,
                                "positionKind": "upperLeftTextBox",
                            }
                        ],
                        "dimensionText": "25.0",
                        "sheetIndex": 1,
                    }
                ],
            }
        )

        self.assertEqual(drawing_map["annotations"][0]["boundsSheet"], [0.215, 0.136, 0.233, 0.144])
        self.assertEqual(drawing_map["annotations"][0]["anchorKind"], "upperLeftTextBox")
        self.assertEqual(drawing_map["annotations"][0]["geometrySource"], "exact")

        findings, _ = apply_drawing_map_to_findings(
            [
                {
                    "name": "Bore Diameter",
                    "status": "PASS",
                    "found_callout": "25.0",
                    "found_on_page": 1,
                }
            ],
            drawing_map,
        )

        self.assertEqual(findings[0]["location"]["boundsSheet"], [0.215, 0.136, 0.233, 0.144])
        self.assertEqual(findings[0]["location"]["anchorKind"], "upperLeftTextBox")
        self.assertEqual(findings[0]["location"]["geometrySource"], "exact")
        self.assertEqual(findings[0]["location"]["textRuns"][0]["positionKind"], "upperLeftTextBox")

    def test_view_primitives_flow_through_normalization(self):
        drawing_map = normalize_drawing_map(
            {
                "partNumber": "1020001",
                "sheetWidth": 0.4318,
                "sheetHeight": 0.2794,
                "sheets": [
                    {
                        "sheetName": "Sheet1",
                        "views": [
                            {
                                "viewName": "Main",
                                "viewOutline": [0.0, 0.0, 0.3, 0.2],
                                "annotations": [],
                                "primitives": [
                                    {
                                        "primitiveType": "line",
                                        "sourceKind": "modelEdge",
                                        "geometrySource": "exact",
                                        "boundsView": [-0.02, -0.01, 0.02, -0.01],
                                        "boundsSheet": [0.10, 0.09, 0.14, 0.09],
                                        "pointsView": [[-0.02, -0.01], [0.02, -0.01]],
                                        "pointsSheet": [[0.10, 0.09], [0.14, 0.09]],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )

        primitives = drawing_map["sheets"][0]["views"][0]["primitives"]
        self.assertEqual(len(primitives), 1)
        self.assertEqual(primitives[0]["primitiveType"], "line")
        self.assertEqual(primitives[0]["pointsView"][0]["x"], -0.02)
        self.assertEqual(primitives[0]["pointsSheet"][1]["y"], 0.09)


if __name__ == "__main__":
    unittest.main()
