"""Tests for source-catalog and placement-only process-map contracts."""

from __future__ import annotations

from copy import deepcopy

from ai_inspector.process_map import (
    PROCESS_MAP_LAYOUT_VERSION,
    migrate_to_placement_map,
    product_structure_from_legacy,
    validate_placement_map,
    validate_product_structure,
)


def _legacy_map() -> dict:
    return {
        "schemaVersion": 2,
        "productName": "Fixture Assembly",
        "nodes": [
            {
                "nodeId": "root",
                "type": "assembly",
                "level": 0,
                "name": "Root Assembly",
                "parentNodeId": None,
                "partIds": ["P-1"],
            },
            {
                "nodeId": "part-a",
                "type": "input",
                "level": 3,
                "name": "Repeated Part",
                "componentId": "P-1",
                "parentNodeId": "root",
                "partIds": ["P-1"],
            },
            {
                "nodeId": "part-b",
                "type": "input",
                "level": 3,
                "name": "Repeated Part",
                "componentId": "P-1",
                "parentNodeId": "root",
                "partIds": ["P-1"],
            },
        ],
        "edges": [],
    }


def _placement(node_id: str, occurrence_id: str) -> dict:
    return {
        "nodeId": node_id,
        "nodeKind": "product_occurrence",
        "sourceOccurrenceId": occurrence_id,
        "position": {"x": 10, "y": 20},
    }


def _junction(node_id: str = "junction-a") -> dict:
    return {
        "nodeId": node_id,
        "nodeKind": "junction",
        "junctionType": "wire_branch",
        "position": {"x": 240, "y": 120},
    }


def test_legacy_hierarchy_becomes_occurrence_catalog_and_blank_canvas():
    legacy = _legacy_map()
    structure, structure_findings = product_structure_from_legacy(legacy, "fixture")
    migrated, map_findings = migrate_to_placement_map(
        legacy,
        product_id="fixture",
        structure_revision="structure-revision",
        product_structure=structure,
    )
    assert not [item for item in structure_findings if item["severity"] == "error"]
    assert {item["occurrenceId"] for item in structure["occurrences"]} == {
        "root",
        "part-a",
        "part-b",
    }
    assert [item["itemId"] for item in structure["occurrences"][1:]] == ["P-1", "P-1"]
    assert migrated["schemaVersion"] == 3
    assert migrated["layoutVersion"] == PROCESS_MAP_LAYOUT_VERSION
    assert migrated["canvasGroups"] == []
    assert migrated["canvasNodes"] == []
    assert migrated["canvasEdges"] == []
    assert map_findings[0]["code"] == "placement_map_migrated"


def test_layout_v1_placement_map_upgrades_without_losing_unknown_fields():
    source = {
        "schemaVersion": 3,
        "mapId": "default",
        "productId": "fixture",
        "sourceStructureRevision": "structure-revision",
        "layoutVersion": 1,
        "canvasNodes": [],
        "canvasEdges": [],
        "futureTopLevelField": {"preserve": True},
    }
    migrated, findings = migrate_to_placement_map(
        source,
        product_id="fixture",
        structure_revision="structure-revision",
        product_structure={"occurrences": []},
    )
    assert findings == []
    assert migrated["layoutVersion"] == PROCESS_MAP_LAYOUT_VERSION
    assert migrated["canvasGroups"] == []
    assert migrated["futureTopLevelField"] == {"preserve": True}
    assert "canvasGroups" not in source
    assert source["layoutVersion"] == 1


def test_layout_v2_group_migrates_to_v3_and_preserves_unknown_group_fields():
    source = {
        "schemaVersion": 3,
        "mapId": "default",
        "productId": "fixture",
        "sourceStructureRevision": "structure-revision",
        "layoutVersion": 2,
        "canvasNodes": [_placement("node-a", "part-a")],
        "canvasEdges": [],
        "canvasGroups": [
            {
                "groupId": "group-a",
                "label": "Machining cell",
                "position": {"x": 0, "y": 0},
                "size": {"width": 500, "height": 320},
                "colorKey": "orange",
                "memberNodeIds": ["node-a"],
                "collapsed": False,
                "futureGroupField": {"preserve": True},
            }
        ],
    }
    migrated, findings = migrate_to_placement_map(
        source,
        product_id="fixture",
        structure_revision="structure-revision",
        product_structure={"occurrences": [{"occurrenceId": "part-a"}]},
    )
    assert findings == []
    assert migrated["layoutVersion"] == PROCESS_MAP_LAYOUT_VERSION
    assert migrated["canvasGroups"] == source["canvasGroups"]
    assert source["layoutVersion"] == 2
    assert validate_placement_map(migrated, {"part-a"}) == []


def test_layout_v3_accepts_optional_orthogonal_routing_and_keeps_legacy_edges_additive():
    process_map = {
        "schemaVersion": 3,
        "layoutVersion": PROCESS_MAP_LAYOUT_VERSION,
        "canvasNodes": [
            _placement("node-a", "part-a"),
            _placement("node-b", "part-b"),
        ],
        "canvasEdges": [
            {
                "edgeId": "legacy",
                "from": {"nodeId": "node-a", "port": "out"},
                "to": {"nodeId": "node-b", "port": "in"},
                "kind": "feedback",
            },
            {
                "edgeId": "routed",
                "from": {"nodeId": "node-a", "port": "out"},
                "to": {"nodeId": "node-b", "port": "in"},
                "kind": "precedence",
                "routing": {
                    "mode": "orthogonal_auto",
                    "routerVersion": 1,
                    "waypoints": [{"x": 280, "y": 93}, {"x": 280, "y": 180}],
                    "obstacleFingerprint": "0123456789abcdef",
                },
            },
        ],
        "canvasGroups": [],
    }
    assert validate_placement_map(process_map, {"part-a", "part-b"}) == []


def test_routed_edges_require_layout_v3_and_valid_route_fields():
    process_map = {
        "schemaVersion": 3,
        "layoutVersion": 2,
        "canvasNodes": [
            _placement("node-a", "part-a"),
            _placement("node-b", "part-b"),
        ],
        "canvasEdges": [
            {
                "edgeId": "bad-route",
                "from": {"nodeId": "node-a", "port": "out"},
                "to": {"nodeId": "node-b", "port": "in"},
                "kind": "precedence",
                "routing": {
                    "mode": "orthogonal_auto",
                    "routerVersion": 0,
                    "waypoints": [{"x": "bad", "y": 0}],
                    "obstacleFingerprint": "",
                },
            }
        ],
        "canvasGroups": [],
    }
    codes = {finding["code"] for finding in validate_placement_map(process_map, {"part-a", "part-b"})}
    assert {
        "routing_requires_layout_version_3",
        "invalid_edge_router_version",
        "invalid_edge_route_waypoint",
        "invalid_edge_obstacle_fingerprint",
    }.issubset(codes)


def test_manual_polyline_edges_allow_authored_diagonal_points_without_obstacle_hash():
    process_map = {
        "schemaVersion": 3,
        "layoutVersion": 3,
        "canvasNodes": [
            _placement("node-a", "part-a"),
            _placement("node-b", "part-b"),
        ],
        "canvasEdges": [
            {
                "edgeId": "manual-route",
                "from": {"nodeId": "node-a", "port": "out"},
                "to": {"nodeId": "node-b", "port": "in"},
                "kind": "precedence",
                "routing": {
                    "mode": "polyline_manual",
                    "routerVersion": 1,
                    "waypoints": [{"x": 310.5, "y": 92.0}, {"x": 455.0, "y": 238.5}],
                },
            }
        ],
        "canvasGroups": [],
    }
    assert validate_placement_map(process_map, {"part-a", "part-b"}) == []

    process_map["canvasEdges"][0]["routing"]["waypoints"][1]["x"] = "bad"
    codes = {
        finding["code"]
        for finding in validate_placement_map(process_map, {"part-a", "part-b"})
    }
    assert "invalid_edge_route_waypoint" in codes
    assert "invalid_edge_obstacle_fingerprint" not in codes


def test_group_validator_reports_membership_and_shape_failures():
    process_map = {
        "schemaVersion": 3,
        "layoutVersion": 2,
        "canvasNodes": [_placement("node-a", "part-a")],
        "canvasEdges": [],
        "canvasGroups": [
            {
                "groupId": "large",
                "label": "Large",
                "position": {"x": 0, "y": 0},
                "size": {"width": 800, "height": 500},
                "colorKey": "blue",
                "memberNodeIds": ["node-a", "missing"],
                "collapsed": False,
            },
            {
                "groupId": "small",
                "label": "Small",
                "position": {"x": 50, "y": 50},
                "size": {"width": 400, "height": 260},
                "colorKey": "green",
                "memberNodeIds": ["node-a"],
                "collapsed": False,
            },
            {
                "groupId": "empty",
                "label": "Empty",
                "position": {"x": 900, "y": 0},
                "size": {"width": 400, "height": 260},
                "colorKey": "purple",
                "memberNodeIds": [],
                "collapsed": False,
            },
        ],
    }
    findings = validate_placement_map(process_map, {"part-a"})
    codes = {finding["code"] for finding in findings}
    assert {"dangling_group_member", "node_in_multiple_groups", "empty_group"}.issubset(codes)
    assert next(item for item in findings if item["code"] == "dangling_group_member")["groupId"] == "large"


def test_groups_require_layout_v2_and_valid_geometry_palette_and_members():
    process_map = {
        "schemaVersion": 3,
        "layoutVersion": 1,
        "canvasNodes": [],
        "canvasEdges": [],
        "canvasGroups": [
            {
                "groupId": "bad",
                "label": " ",
                "position": {"x": "left", "y": 0},
                "size": {"width": 0, "height": 200},
                "colorKey": "raw-hex",
                "memberNodeIds": "node-a",
                "collapsed": True,
            }
        ],
    }
    codes = {finding["code"] for finding in validate_placement_map(process_map)}
    assert {
        "groups_require_layout_version_2",
        "invalid_group_label",
        "invalid_group_position",
        "invalid_group_size",
        "unknown_group_color",
        "group_members_not_array",
        "group_collapse_not_supported",
    }.issubset(codes)


def test_explicit_position_is_preserved_as_authored_placement():
    legacy = _legacy_map()
    legacy["nodes"][1]["position"] = {"x": 125, "y": 250}
    structure, _ = product_structure_from_legacy(legacy, "fixture")
    migrated, _ = migrate_to_placement_map(
        legacy,
        product_id="fixture",
        structure_revision="structure-revision",
        product_structure=structure,
    )
    assert migrated["canvasNodes"] == [
        {
            "nodeId": "part-a",
            "nodeKind": "product_occurrence",
            "sourceOccurrenceId": "part-a",
            "nameSnapshot": "Repeated Part",
            "itemIdSnapshot": "P-1",
            "position": {"x": 125, "y": 250},
            "positionMode": "manual",
        }
    ]


def test_repeated_part_numbers_remain_distinct_occurrences():
    structure, _ = product_structure_from_legacy(_legacy_map(), "fixture")
    occurrence_ids = {item["occurrenceId"] for item in structure["occurrences"]}
    process_map = {
        "schemaVersion": 3,
        "sourceStructureRevision": "structure-revision",
        "canvasNodes": [
            _placement("node-a", "part-a"),
            _placement("node-b", "part-b"),
        ],
        "canvasEdges": [],
    }
    assert validate_placement_map(process_map, occurrence_ids) == []


def test_duplicate_occurrence_and_dangling_source_are_errors():
    process_map = {
        "schemaVersion": 3,
        "canvasNodes": [
            _placement("node-a", "part-a"),
            _placement("node-b", "part-a"),
            _placement("node-c", "missing"),
        ],
        "canvasEdges": [],
    }
    codes = {
        item["code"] for item in validate_placement_map(process_map, {"part-a"})
        if item["severity"] == "error"
    }
    assert {"duplicate_occurrence_placement", "dangling_source_occurrence"}.issubset(codes)


def test_node_deletion_contract_rejects_dangling_canvas_edges():
    process_map = {
        "schemaVersion": 3,
        "canvasNodes": [_placement("node-a", "part-a")],
        "canvasEdges": [
            {
                "edgeId": "edge-a",
                "from": {"nodeId": "node-a", "port": "out"},
                "to": {"nodeId": "missing", "port": "in"},
                "kind": "precedence",
            }
        ],
    }
    assert "dangling_edge_endpoint" in {
        item["code"] for item in validate_placement_map(process_map, {"part-a"})
    }


def test_product_structure_rejects_duplicate_occurrence_identity():
    structure, _ = product_structure_from_legacy(_legacy_map(), "fixture")
    duplicate = deepcopy(structure["occurrences"][1])
    structure["occurrences"].append(duplicate)
    assert "duplicate_occurrence_id" in {
        item["code"] for item in validate_product_structure(structure)
    }


def test_wire_junction_is_a_valid_persistent_canvas_node():
    process_map = {
        "schemaVersion": 3,
        "canvasNodes": [
            _placement("node-a", "part-a"),
            _placement("node-b", "part-b"),
            _placement("node-c", "part-c"),
            _junction(),
        ],
        "canvasEdges": [
            {
                "edgeId": "trunk-left",
                "logicalConnectionId": "trunk",
                "from": {"nodeId": "node-a", "port": "out"},
                "to": {"nodeId": "junction-a", "port": "in"},
                "kind": "precedence",
            },
            {
                "edgeId": "trunk-right",
                "logicalConnectionId": "trunk",
                "from": {"nodeId": "junction-a", "port": "out"},
                "to": {"nodeId": "node-b", "port": "in"},
                "kind": "precedence",
            },
            {
                "edgeId": "branch",
                "logicalConnectionId": "branch",
                "from": {"nodeId": "node-c", "port": "out"},
                "to": {"nodeId": "junction-a", "port": "in"},
                "kind": "precedence",
            },
        ],
    }
    assert validate_placement_map(process_map, {"part-a", "part-b", "part-c"}) == []


def test_junction_and_logical_connection_metadata_are_validated():
    process_map = {
        "schemaVersion": 3,
        "canvasNodes": [
            _placement("node-a", "part-a"),
            _placement("node-b", "part-b"),
            {**_junction(), "junctionType": "visual_only"},
        ],
        "canvasEdges": [
            {
                "edgeId": "edge-a",
                "logicalConnectionId": "   ",
                "from": {"nodeId": "node-a", "port": "out"},
                "to": {"nodeId": "junction-a", "port": "in"},
                "kind": "precedence",
            }
        ],
    }
    codes = {item["code"] for item in validate_placement_map(process_map, {"part-a", "part-b"})}
    assert {"unknown_junction_type", "invalid_logical_connection_id"}.issubset(codes)


def test_precedence_cycle_detection_includes_junction_topology():
    process_map = {
        "schemaVersion": 3,
        "canvasNodes": [
            _placement("node-a", "part-a"),
            _placement("node-b", "part-b"),
            _junction(),
        ],
        "canvasEdges": [
            {
                "edgeId": "a-j",
                "from": {"nodeId": "node-a", "port": "out"},
                "to": {"nodeId": "junction-a", "port": "in"},
                "kind": "precedence",
            },
            {
                "edgeId": "j-b",
                "from": {"nodeId": "junction-a", "port": "out"},
                "to": {"nodeId": "node-b", "port": "in"},
                "kind": "precedence",
            },
            {
                "edgeId": "b-a",
                "from": {"nodeId": "node-b", "port": "out"},
                "to": {"nodeId": "node-a", "port": "in"},
                "kind": "precedence",
            },
        ],
    }
    assert "precedence_cycle" in {
        item["code"] for item in validate_placement_map(process_map, {"part-a", "part-b"})
    }


def test_card_port_orientation_is_validated_and_junctions_cannot_use_it():
    vertical = _placement("node-a", "part-a")
    vertical["portOrientation"] = "vertical"
    vertical["portOrder"] = "output_first"
    assert validate_placement_map(
        {"schemaVersion": 3, "canvasNodes": [vertical], "canvasEdges": []},
        {"part-a"},
    ) == []

    invalid = _placement("node-a", "part-a")
    invalid["portOrientation"] = "diagonal"
    invalid_codes = {
        item["code"] for item in validate_placement_map(
            {"schemaVersion": 3, "canvasNodes": [invalid], "canvasEdges": []},
            {"part-a"},
        )
    }
    assert "unknown_port_orientation" in invalid_codes

    invalid_order = _placement("node-a", "part-a")
    invalid_order["portOrder"] = "inside_out"
    invalid_order_codes = {
        item["code"] for item in validate_placement_map(
            {"schemaVersion": 3, "canvasNodes": [invalid_order], "canvasEdges": []},
            {"part-a"},
        )
    }
    assert "unknown_port_order" in invalid_order_codes

    junction = _junction()
    junction["portOrientation"] = "vertical"
    junction_codes = {
        item["code"] for item in validate_placement_map(
            {"schemaVersion": 3, "canvasNodes": [junction], "canvasEdges": []}
        )
    }
    assert "junction_port_layout_not_allowed" in junction_codes


def test_card_position_lock_is_validated_and_junctions_share_position_ownership():
    locked = _placement("node-a", "part-a")
    locked["locked"] = True
    assert validate_placement_map(
        {"schemaVersion": 3, "canvasNodes": [locked], "canvasEdges": []},
        {"part-a"},
    ) == []

    invalid = _placement("node-a", "part-a")
    invalid["locked"] = "yes"
    invalid_codes = {
        item["code"] for item in validate_placement_map(
            {"schemaVersion": 3, "canvasNodes": [invalid], "canvasEdges": []},
            {"part-a"},
        )
    }
    assert "invalid_node_locked" in invalid_codes

    junction = _junction()
    junction["locked"] = True
    assert validate_placement_map(
        {"schemaVersion": 3, "canvasNodes": [junction], "canvasEdges": []}
    ) == []


def test_card_label_override_and_note_are_validated():
    product = _placement("node-a", "part-a")
    product["labelOverride"] = "Finish-grind housing"
    product["note"] = "Verify the sealing land before the next operation."
    assert validate_placement_map(
        {"schemaVersion": 3, "canvasNodes": [product], "canvasEdges": []},
        {"part-a"},
    ) == []

    invalid_label = deepcopy(product)
    invalid_label["labelOverride"] = " "
    invalid_note = deepcopy(product)
    invalid_note["note"] = "x" * 2001
    codes = {
        finding["code"]
        for finding in validate_placement_map(
            {
                "schemaVersion": 3,
                "canvasNodes": [invalid_label, {**invalid_note, "nodeId": "node-b", "sourceOccurrenceId": "part-b"}],
                "canvasEdges": [],
            },
            {"part-a", "part-b"},
        )
    }
    assert {"invalid_node_label_override", "invalid_node_note"}.issubset(codes)


def test_process_step_label_and_junction_card_metadata_are_validated():
    step = {
        "nodeId": "step-a",
        "nodeKind": "process_step",
        "processType": "operation",
        "name": "Machine bore",
        "note": "Use the approved setup sheet.",
        "position": {"x": 20, "y": 30},
    }
    assert validate_placement_map(
        {"schemaVersion": 3, "canvasNodes": [step], "canvasEdges": []}
    ) == []

    invalid_step = {**step, "name": ""}
    junction = {**_junction(), "note": "Not allowed"}
    codes = {
        finding["code"]
        for finding in validate_placement_map(
            {
                "schemaVersion": 3,
                "canvasNodes": [invalid_step, junction],
                "canvasEdges": [],
            }
        )
    }
    assert {"invalid_process_step_name", "junction_card_metadata_not_allowed"}.issubset(codes)


def test_stage_properties_and_semantic_junction_types_are_native_map_data():
    stage = {
        "nodeId": "stage-a",
        "nodeKind": "process_step",
        "processType": "operation",
        "name": "Install lower panels",
        "position": {"x": 120, "y": 80},
        "properties": {
            "description": "Join both lower panels before the upper fairing is installed.",
            "duration": "12 min",
            "fastenersConsumables": "8 x M6 fasteners; medium-strength threadlocker",
            "torqueRequirements": "10 N m",
            "inspectionRequirements": "Verify flushness and fastener witness marks.",
            "constraints": "Use fixture F-14.",
        },
    }
    junctions = [
        {
            "nodeId": f"junction-{junction_type}",
            "nodeKind": "junction",
            "junctionType": junction_type,
            "position": {"x": 400, "y": index * 80},
        }
        for index, junction_type in enumerate(("parallel_and", "merge", "split"))
    ]
    findings = validate_placement_map({
        "schemaVersion": 3,
        "canvasNodes": [stage, *junctions],
        "canvasEdges": [],
    })
    assert not [finding for finding in findings if finding["severity"] == "error"]
    warning_codes = {finding["code"] for finding in findings}
    assert {
        "junction_has_fewer_than_two_inputs",
        "split_junction_has_fewer_than_two_outputs",
    }.issubset(warning_codes)


def test_stage_properties_fail_closed_on_wrong_owner_or_unknown_field():
    step = {
        "nodeId": "stage-a",
        "nodeKind": "process_step",
        "processType": "operation",
        "name": "Install panel",
        "position": {"x": 20, "y": 30},
        "properties": {"unknownField": "not supported", "duration": " "},
    }
    product = _placement("node-a", "part-a")
    product["properties"] = {"duration": "10 min"}
    invalid_junction = {
        "nodeId": "junction-a",
        "nodeKind": "junction",
        "junctionType": "conditional_merge",
        "position": {"x": 300, "y": 30},
    }
    codes = {
        finding["code"]
        for finding in validate_placement_map(
            {
                "schemaVersion": 3,
                "canvasNodes": [step, product, invalid_junction],
                "canvasEdges": [],
            },
            {"part-a"},
        )
    }
    assert {
        "unknown_process_step_property",
        "invalid_process_step_property",
        "process_step_properties_not_allowed",
        "unknown_junction_type",
    }.issubset(codes)


def test_cards_and_connections_accept_reusable_process_references():
    node_a = _placement("node-a", "part-a")
    node_a["referenceIds"] = ["machine-1"]
    process_map = {
        "schemaVersion": 3,
        "referenceCatalog": [
            {
                "referenceId": "machine-1",
                "kind": "machine",
                "name": "Five-axis machining center",
                "identifier": "MC-01",
                "details": "Approved fixture setup required.",
            },
            {
                "referenceId": "standard-1",
                "kind": "standard",
                "name": "Dimensioning and tolerancing",
                "identifier": "ASME Y14.5",
                "revision": "2018",
                "clause": "7.5",
            },
        ],
        "canvasNodes": [node_a, _placement("node-b", "part-b")],
        "canvasEdges": [
            {
                "edgeId": "edge-a",
                "logicalConnectionId": "edge-a",
                "label": "Inspection release",
                "referenceIds": ["standard-1"],
                "from": {"nodeId": "node-a", "port": "out"},
                "to": {"nodeId": "node-b", "port": "in"},
                "kind": "precedence",
            }
        ],
    }
    assert validate_placement_map(process_map, {"part-a", "part-b"}) == []


def test_invalid_and_stale_process_references_fail_closed():
    node = _placement("node-a", "part-a")
    node["referenceIds"] = ["missing", "missing"]
    junction = _junction()
    junction["referenceIds"] = ["standard-1"]
    process_map = {
        "schemaVersion": 3,
        "referenceCatalog": [
            {
                "referenceId": "standard-1",
                "kind": "standard",
                "name": "Dimensioning and tolerancing",
            }
        ],
        "canvasNodes": [node, junction],
        "canvasEdges": [],
    }
    codes = {
        finding["code"]
        for finding in validate_placement_map(process_map, {"part-a"})
        if finding["severity"] == "error"
    }
    assert {
        "standard_identifier_required",
        "duplicate_target_reference",
        "unknown_target_reference",
        "junction_references_not_allowed",
    }.issubset(codes)


def test_split_logical_connections_require_consistent_references_and_labels():
    process_map = {
        "schemaVersion": 3,
        "referenceCatalog": [
            {
                "referenceId": "tool-1",
                "kind": "tool",
                "name": "Digital bore gauge",
                "identifier": "BG-12",
            }
        ],
        "canvasNodes": [
            _placement("node-a", "part-a"),
            _placement("node-b", "part-b"),
            _junction(),
        ],
        "canvasEdges": [
            {
                "edgeId": "trunk-left",
                "logicalConnectionId": "trunk",
                "label": "Release",
                "referenceIds": ["tool-1"],
                "from": {"nodeId": "node-a", "port": "out"},
                "to": {"nodeId": "junction-a", "port": "in"},
                "kind": "precedence",
            },
            {
                "edgeId": "trunk-right",
                "logicalConnectionId": "trunk",
                "label": "Ship",
                "from": {"nodeId": "junction-a", "port": "out"},
                "to": {"nodeId": "node-b", "port": "in"},
                "kind": "precedence",
            },
        ],
    }
    codes = {
        finding["code"]
        for finding in validate_placement_map(process_map, {"part-a", "part-b"})
    }
    assert {
        "logical_connection_reference_mismatch",
        "logical_connection_label_conflict",
    }.issubset(codes)
