import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402


def _piston_feature_context():
    return {
        "part_number": "100006",
        "part_name": "Piston",
        "profile_features": [
            {
                "name": "Pin bores through bosses",
                "type": "through_bore",
                "spatial_description": "Opposed wrist-pin bores through the two piston bosses.",
                "highlight_target_ids": ["ice_cut_extrude1"],
            },
            {
                "name": "Boss face counterbores",
                "type": "counterbore",
                "spatial_description": "Counterbore reliefs around the pin bore boss faces.",
                "highlight_target_ids": ["ice_boss_extrude1", "mirrorpattern_mirror1"],
            },
            {
                "name": "Ring grooves",
                "type": "groove",
                "spatial_description": "Three circumferential piston-ring grooves near the crown.",
                "highlight_target_ids": ["semantic:ring_grooves"],
            },
            {
                "name": "Crown dome",
                "type": "crown",
                "spatial_description": "Domed upper crown surface.",
                "highlight_target_ids": ["dome1"],
            },
            {
                "name": "Skirt with arched reliefs",
                "type": "skirt_relief",
                "spatial_description": "Lower skirt and arched clearance reliefs around the pin bosses.",
                "highlight_target_ids": ["ice_cut_extrude3"],
            },
        ],
        "available_cad_features": [
            {
                "cad_feature_id": "ice_cut_extrude1",
                "display_label": "Pin bores through bosses",
                "color_name": "green",
                "semantic_aliases": ["green feature", "pin bore", "pin bores"],
            },
            {
                "cad_feature_id": "ice_boss_extrude1",
                "display_label": "Boss face counterbore",
                "color_name": "blue",
            },
            {
                "cad_feature_id": "mirrorpattern_mirror1",
                "display_label": "Opposite boss face counterbore",
                "color_name": "orange",
            },
            {
                "cad_feature_id": "dome1",
                "display_label": "Crown dome",
                "color_name": "red",
            },
            {
                "cad_feature_id": "ice_cut_extrude3",
                "display_label": "Skirt with arched reliefs",
                "color_name": "yellow",
            },
        ],
    }


def _highlight_ids(message: str):
    result = server._profile_feature_highlight_chat_result(
        _piston_feature_context(),
        message,
        "inspector",
    )
    assert result is not None
    assert result["tool_source"] == "profile_feature_highlight"
    return result["highlight_features"]


def test_individual_profile_feature_commands_highlight_one_semantic_group():
    assert _highlight_ids("show me the pin bores") == ["ice_cut_extrude1"]
    assert _highlight_ids("show me the pin bore") == ["ice_cut_extrude1"]
    assert _highlight_ids("show me the dome") == ["dome1"]
    assert _highlight_ids("show me the ring grooves") == ["semantic:ring_grooves"]
    assert _highlight_ids("show me the skirt reliefs") == ["ice_cut_extrude3"]


def test_counterbores_do_not_overmatch_pin_bores():
    assert _highlight_ids("show me the boss counterbores") == [
        "ice_boss_extrude1",
        "mirrorpattern_mirror1",
    ]


def test_color_aliases_still_resolve_to_profile_feature_group():
    assert not server._is_user_facing_feature_list_request("show me the green feature")
    assert _highlight_ids("show me the green feature") == ["ice_cut_extrude1"]
    assert not server._is_user_facing_feature_list_request("what feature is highlighted in green")
    assert _highlight_ids("what feature is highlighted in green") == ["ice_cut_extrude1"]


def test_all_features_request_still_uses_feature_list_route():
    assert server._is_user_facing_feature_list_request("show me all the features on this part")
