from ai_inspector.facility_layout.tool_knowledge import (
    compile_command_explanation,
    compile_facility_ui_metadata,
)


def test_motion_path_is_a_bounded_ui_only_navigation_command() -> None:
    explanation = compile_command_explanation("motion-path")
    command = explanation["command"]

    assert command["agentAvailability"] == "ui_only"
    assert command["entityScope"] == "navigation_intent"
    assert command["supportedStages"] == ["floor_communication"]
    assert command["requiredCapabilities"] == ["manual_edit", "routing"]
    assert command["inputSchema"] == {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "actorPlacementId": {"type": "string"},
            "authoringMode": {"type": "string", "enum": ["plan_pointer"]},
        },
        "required": ["actorPlacementId"],
        "additionalProperties": False,
    }
    assert all(
        coordinate not in command["inputSchema"]["properties"]
        for coordinate in ("x", "y", "z", "points", "polyline", "vertices")
    )
    prohibited = " ".join(command["prohibitedUses"])
    assert "coordinates authored by model text" in prohibited
    assert "proof of clearance" in prohibited


def test_motion_path_is_present_once_on_the_current_ui_surface() -> None:
    metadata = compile_facility_ui_metadata()
    command_ids = [item["commandId"] for item in metadata["commands"]]
    ribbon_ids = [
        command_id
        for group in metadata["ribbonGroups"]
        for command_id in group["commandIds"]
    ]

    assert command_ids.count("motion-path") == 1
    assert ribbon_ids.count("motion-path") == 1
