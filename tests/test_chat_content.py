from __future__ import annotations

from copy import deepcopy

from ai_inspector.chat_content import (
    CHAT_TABLE_TOOL,
    CHAT_VISUALIZATION_TOOL,
    chat_table_block_from_args,
    chat_table_tool_spec,
    chat_visualization_block_from_args,
    chat_visualization_tool_spec,
    complete_chat_table_prose,
    complete_chat_visualization_prose,
    normalize_chat_content_blocks,
    normalize_chat_response_payload,
    requested_visualization_options,
    requested_visualization_type,
    requested_table,
)


def test_generation_source_cards_are_receipt_derived_deduplicated_and_unreviewed():
    from ai_inspector.facility_layout.generation_presentation import generation_research_source_block
    first = {"tool": "search_generation_sources", "status": "succeeded", "result": {
        "sources": [{"url": "https://www.skf.com/a", "title": "First retained title", "retrieval": "search_result"},
                    {"url": "https://example.com/b", "title": "Second", "retrieval": "search_result"}],
        "citations": [{"url": "https://www.skf.com/a", "text": "A retained extract."},
                      {"url": "https://invented.example.com", "text": "Not a retrieved source"}],
        "retrievedAt": "2026-09-22T12:00:00Z"}}
    second = {"tool": "read_generation_source", "status": "succeeded", "result": {
        "complete": True, "requestedUrl": "https://www.skf.com/a",
        "sources": [{"url": "https://www.skf.com/a", "title": "Later title", "retrieval": "fetched_document"},
                    {"url": "https://example.com/manual.pdf", "title": "Manual", "retrieval": "fetched_document"}],
        "citations": [], "retrievedAt": "2026-09-22T12:00:01Z"}}
    observed = [first, second, {**first, "status": "failed"}, {**first, "tool": "model_presentation"}]
    before = deepcopy(observed)
    block = generation_research_source_block(observed)
    sources = block["sources"]
    assert [source["url"] for source in sources] == ["https://www.skf.com/a", "https://example.com/b", "https://example.com/manual.pdf"]
    assert sources[0]["title"] == "Later title" and sources[0]["description"] == ""
    assert sources[0]["retrievedAt"] == second["result"]["retrievedAt"]
    assert sources[0]["sourceType"] == "technical-document"
    assert sources[0]["specifications"]["Retrieval"] == "Document read"
    assert sources[2]["sourceType"] == "web"
    assert sources[2]["specifications"]["Retrieval"] == "Read not confirmed"
    assert generation_research_source_block([second, first])["sources"][0] == sources[0]
    assert all(source["publisher"] == "" and source["inferIdentity"] is False and source["iconUrl"] is None for source in sources)
    assert all(source["specifications"]["Review"] == "Pending" for source in sources)
    assert observed == before
    table = {"type": "table", "title": "Keep this", "columns": [{"label": "Count"}], "rows": [{"cells": ["2"]}]}
    payload = normalize_chat_response_payload({"response": "Preview", "content_blocks": [table, block]})
    assert [item["type"] for item in payload["content_blocks"]] == ["table", "sources"]
    assert payload["content_blocks"][1] == block


def test_incomplete_document_receipt_cannot_upgrade_a_search_card():
    from ai_inspector.facility_layout.generation_presentation import generation_research_source_block
    entry = {"tool": "read_generation_source", "status": "succeeded", "result": {
        "complete": False, "requestedUrl": "https://maker.example/manual", "truncated": True,
        "sources": [{"url": "https://maker.example/manual", "retrieval": "fetched_document"}]}}
    card = generation_research_source_block([entry])["sources"][0]
    assert card["sourceType"] == "web"
    assert card["specifications"]["Retrieval"] == "Read not confirmed"
    assert card["specifications"]["Extract"] == "Truncated"


def test_generation_cards_ignore_failed_absent_unsafe_and_model_only_sources():
    from ai_inspector.facility_layout.generation_presentation import generation_research_source_block
    assert generation_research_source_block([]) is None
    result = {"sources": [{"url": "javascript:alert(1)"}, {"url": "http://127.0.0.1/private"},
                          {"url": "https://user:password@example.com"}]}
    assert generation_research_source_block([{"tool": "read_generation_source", "status": "succeeded", "result": result}]) is None
    result["sources"] = [{"url": "https://example.com/a"}]
    assert generation_research_source_block([{"tool": "read_generation_source", "status": "failed", "result": result}]) is None
    assert generation_research_source_block([{"tool": "preview_generation_package", "status": "succeeded", "result": result}]) is None


def test_generation_source_cards_are_bounded_and_stable():
    from ai_inspector.facility_layout.generation_presentation import generation_research_source_block
    result = {"sources": [{"url": f"https://example.com/{index}", "title": "T" * 1000} for index in range(25)]}
    results = [{"tool": "search_generation_sources", "status": "succeeded", "result": result}]
    block = generation_research_source_block(results)
    assert len(block["sources"]) == 20 and "first 20" in block["title"]
    assert all(len(source["title"]) == 240 for source in block["sources"])
    assert block == generation_research_source_block(results)


def test_visualization_tool_contract_is_closed_and_normalizes_rows() -> None:
    spec = chat_visualization_tool_spec()
    assert spec["name"] == CHAT_VISUALIZATION_TOOL
    assert spec["input_schema"]["additionalProperties"] is False
    assert set(spec["input_schema"]["required"]) == set(
        spec["input_schema"]["properties"]
    )

    block = chat_visualization_block_from_args({
        "chart_type": "bar",
        "metric_id": "placement_count",
        "title": "Assets by zone",
        "subtitle": None,
        "unit": "placements",
        "data": [
            {
                "label": "Machining",
                "value": 12,
                "entity_id": "zone-machining",
                "series": None,
            },
            {
                "label": "Invalid numeric row",
                "value": float("nan"),
                "entity_id": None,
                "series": None,
            },
        ],
    })

    assert block is not None
    assert block["type"] == "visualization"
    assert block["spec"]["metricId"] == "placement_count"
    assert block["spec"]["data"] == [{
        "label": "Machining",
        "value": 12.0,
        "entityId": "zone-machining",
        "series": None,
    }]


def test_visualization_preamble_is_replaced_with_data_derived_conclusion() -> None:
    block = chat_visualization_block_from_args({
        "chart_type": "bar",
        "title": "Placed assets by department",
        "subtitle": "Trusted saved layout",
        "unit": "placements",
        "data": [
            {
                "label": "Machining",
                "value": 9,
                "entity_id": "zone-machining",
                "series": None,
            },
            {
                "label": "Assembly",
                "value": 4,
                "entity_id": "zone-assembly",
                "series": None,
            },
            {
                "label": "Shipping",
                "value": 2,
                "entity_id": "zone-shipping",
                "series": None,
            },
        ],
    })

    prose = complete_chat_visualization_prose(
        "I'll analyze the saved layout and create a chart.",
        [block],
    )

    assert prose.startswith("## Placed assets by department")
    assert "**Machining** (9 placements)" in prose
    assert "**Shipping** (2 placements)" in prose
    assert "Priority review" in prose
    assert "I'll analyze" not in prose


def test_visualization_completion_typesets_area_units() -> None:
    block = chat_visualization_block_from_args({
        "chart_type": "bar",
        "title": "Department floor area",
        "subtitle": None,
        "unit": "m^2",
        "data": [
            {
                "label": "Machining Hall",
                "value": 8324,
                "entity_id": "zone-machining",
                "series": None,
            },
        ],
    })

    prose = complete_chat_visualization_prose(
        "I'll create that chart.",
        [block],
    )

    assert "using m\u00b2" in prose
    assert "8324 m\u00b2" in prose
    assert "m^2" not in prose


def test_visualization_completion_preserves_substantive_model_analysis() -> None:
    block = chat_visualization_block_from_args({
        "chart_type": "pareto",
        "title": "Observed findings",
        "subtitle": None,
        "unit": "findings",
        "data": [
            {
                "label": "Clearance",
                "value": 3,
                "entity_id": None,
                "series": None,
            },
        ],
    })
    analysis = "Clearance findings account for all three observed records."

    assert complete_chat_visualization_prose(analysis, [block]) == analysis


def test_response_payload_preserves_text_and_normalizes_rich_blocks() -> None:
    original = {
        "response": "Measured values.",
        "contentBlocks": [
            {
                "type": "sources",
                "sources": [
                    {
                        "id": "source_skf",
                        "title": "SKF 6205",
                        "url": "https://www.skf.com/6205",
                        "sourceType": "manufacturer",
                        "specifications": {"bore": "25 mm"},
                    },
                    {"title": "unsafe", "url": "javascript:alert(1)"},
                ],
            },
            {
                "type": "facts",
                "facts": [
                    {
                        "label": "Bore",
                        "value": "25",
                        "unit": "mm",
                        "sourceId": "source_skf",
                        "provenance": "source",
                    }
                ],
            },
        ],
    }

    normalized = normalize_chat_response_payload(original)

    assert normalized["response"] == "Measured values."
    assert "contentBlocks" not in normalized
    assert [block["type"] for block in normalized["content_blocks"]] == [
        "sources",
        "facts",
    ]
    assert len(normalized["content_blocks"][0]["sources"]) == 1
    assert original["contentBlocks"][0]["sources"][1]["url"].startswith("javascript")


def test_unknown_blocks_actions_and_chart_types_fail_closed() -> None:
    blocks = normalize_chat_content_blocks([
        {"type": "raw_html", "html": "<script>bad()</script>"},
        {
            "type": "actions",
            "actions": [
                {"actionId": "delete_layout", "entityId": "layout_1"},
                {"actionId": "locate_in_plan", "entityId": "asset_1"},
            ],
        },
        {
            "type": "visualization",
            "spec": {"type": "custom-javascript", "data": [{"x": 1}]},
        },
    ])

    assert blocks == [
        {
            "type": "actions",
            "actions": [
                {
                    "actionId": "locate_in_plan",
                    "label": "locate in plan",
                    "entityId": "asset_1",
                    "entityType": "",
                }
            ],
        }
    ]


def test_visualization_rows_and_fields_are_bounded() -> None:
    blocks = normalize_chat_content_blocks([
        {
            "type": "visualization",
            "spec": {
                "type": "bar",
                "data": [
                    {**{f"field_{column}": column for column in range(25)}, "label": row}
                    for row in range(240)
                ],
                "encoding": {"x": "label", "y": "field_1"},
            },
        }
    ])

    chart = blocks[0]["spec"]
    assert len(chart["data"]) == 200
    assert len(chart["data"][0]) == 20


def test_requested_visualization_type_honors_corrections_and_negation() -> None:
    assert requested_visualization_type(
        "Show a Pareto chart of placements, zones, markings, and routes."
    ) == "pareto"
    assert requested_visualization_type(
        "Show a Pareto chart, not a bar chart."
    ) == "pareto"
    assert requested_visualization_type(
        "Use a bar chart instead of a Pareto chart."
    ) == "bar"
    assert requested_visualization_type(
        "Compare the Machining Hall and Automation zone in a table."
    ) is None
    assert requested_visualization_type(
        "Show a heatmap of asset categories by department."
    ) == "heatmap"
    assert requested_visualization_type(
        "Generate a pie chart for the six departments."
    ) == "pie"
    assert requested_visualization_type(
        "Use a doughnut chart for the same values."
    ) == "donut"


def test_visualization_display_preferences_are_explicit_and_overridable() -> None:
    assert requested_visualization_options(
        "Use placement-count labels only, with no percentage labels."
    ) == {
        "showPercentages": False,
        "showValues": True,
    }
    assert requested_visualization_options(
        "Show percentages and the legend, but hide value labels."
    ) == {
        "showPercentages": True,
        "showValues": False,
        "showLegend": True,
    }

    block = chat_visualization_block_from_args(
        {
            "chart_type": "pie",
            "title": "Placements by department",
            "subtitle": None,
            "unit": "placements",
            "show_values": False,
            "show_percentages": True,
            "show_legend": True,
            "data": [
                {
                    "label": "Machining Hall",
                    "value": 32,
                    "entity_id": "zone-machining",
                    "series": None,
                }
            ],
        },
        required_options={
            "showValues": True,
            "showPercentages": False,
        },
    )
    assert block is not None
    assert block["spec"]["type"] == "pie"
    assert block["spec"]["options"] == {
        "showValues": True,
        "showPercentages": False,
        "showLegend": True,
    }


def test_visualization_contract_enforces_explicit_requested_type() -> None:
    spec = chat_visualization_tool_spec(required_chart_type="pareto")
    chart_type = spec["input_schema"]["properties"]["chart_type"]
    assert chart_type == {"type": "string", "enum": ["pareto"]}

    block = chat_visualization_block_from_args(
        {
            "chart_type": "bar",
            "metric_id": "placement_count",
            "title": "Entity distribution",
            "subtitle": None,
            "unit": "entities",
            "data": [
                {
                    "label": "Placements",
                    "value": 827,
                    "entity_id": None,
                    "series": None,
                },
                {
                    "label": "Zones",
                    "value": 45,
                    "entity_id": None,
                    "series": None,
                },
            ],
        },
        required_chart_type="pareto",
    )
    assert block is not None
    assert block["spec"]["type"] == "pareto"


def test_table_request_and_closed_table_contract() -> None:
    assert requested_table(
        "Compare the Machining Hall and Automation zone in a table."
    ) is True
    assert requested_table("Compare them, but not as a table.") is False

    spec = chat_table_tool_spec()
    assert spec["name"] == CHAT_TABLE_TOOL
    assert spec["input_schema"]["additionalProperties"] is False
    assert set(spec["input_schema"]["required"]) == set(
        spec["input_schema"]["properties"]
    )
    block = chat_table_block_from_args({
        "title": "Department comparison",
        "subtitle": None,
        "columns": [
            {"label": "Department", "unit": None},
            {"label": "Placements", "unit": "count"},
        ],
        "rows": [
            {
                "cells": ["Machining Hall", "32"],
                "entity_id": "zone-machining",
            },
            {
                "cells": ["Automation + Robot cells", "492"],
                "entity_id": "zone-automation",
            },
        ],
    })
    assert block is not None
    assert block["type"] == "table"
    assert block["table"]["rows"][1]["cells"] == [
        "Automation + Robot cells",
        "492",
    ]

    prose = complete_chat_table_prose(
        "No response from agent.",
        [block],
        request_message=(
            "Compare them in a table. End by asking whether I want the asset "
            "category breakdown."
        ),
    )
    assert prose.startswith("## Department comparison")
    assert "across 2 supplied rows" in prose
    assert prose.endswith("Would you like the asset category breakdown?")
