"""The editor smoke tolerates only known sanitized-fixture failures.

Pure report classification tests; these do not launch the app or a browser.
"""
from copy import deepcopy

import pytest

from tests.smoke_documentation_editor import classify_failures, known_http_failure

BASE = "http://127.0.0.1:8000"


def empty_report():
    return {key: [] for key in ("httpFailures", "consoleErrors", "browserErrors",
                               "networkFailures", "outboundRequests")}


def failure(route, status, method="GET"):
    return {"url": BASE + route, "status": status, "method": method}


def console_resource(item):
    return {"message": f"Failed to load resource: the server responded with a status of {item['status']} (Not Found)",
            "location": {"url": item["url"]}}


@pytest.mark.parametrize("route,status", [
    ("/api/drawing-map/MMLE-50D", 404),
    ("/api/drawing-pdf/MMLE-50D?revision=1", 404),
    ("/api/part-features/MMLE-50D", 404),
    ("/api/training/process-map-for-assembly/MMLE-50D", 404),
    ("/api/training/process-map/mmle-50d", 404),
    ("/api/reference-views/MMLE-50D", 500),
])
def test_known_optional_gets_and_corresponding_console_errors_are_reported(route, status):
    report = empty_report()
    item = failure(route, status)
    report["httpFailures"].append(item)
    report["consoleErrors"].append(console_resource(item))
    original = deepcopy(report)
    assert classify_failures(report)
    assert len(report["knownFixtureFailures"]) == 2
    assert report["httpFailures"] == original["httpFailures"]
    assert report["consoleErrors"] == original["consoleErrors"]


@pytest.mark.parametrize("route", [
    "/api/parts-manual/MMLE-50D/documentation-scene",
    "/api/operations-manual/MMLE-50D/documentation-scene",
    "/api/specification-sheet/MMLE-50D/values",
    "/api/work-instructions/MMLE-50D/documentation-scene",
    "/api/inspection-sheet/MMLE-50D",
    "/__p1a/tool",
])
@pytest.mark.parametrize("status", [404, 409, 500])
def test_documentation_route_errors_are_always_fatal(route, status):
    report = empty_report()
    item = failure(route, status)
    report["httpFailures"] = [failure("/api/drawing-map/MMLE-50D", 404), item]
    report["consoleErrors"] = [console_resource(item)]
    assert not classify_failures(report)
    assert report["unexpectedHttpFailures"] == [item]
    assert report["unexpectedConsoleErrors"] == report["consoleErrors"]


@pytest.mark.parametrize("item", [
    failure("/api/drawing-map/MMLE-50D", 500),
    failure("/api/reference-views/MMLE-50D", 404),
    failure("/api/drawing-map/MMLE-50D", 404, "POST"),
    failure("/api/drawing-map/MMLE-50D/documentation-scene", 404),
    failure("/api/training/process-maps/mmle-50d/revisions", 404),
    failure("/static/contracts/semantic-knowledge-prototype-v1.json", 404),
])
def test_unknown_status_method_or_route_is_not_exempt(item):
    assert known_http_failure(item) is None


def test_reference_json_console_error_requires_observed_reference_failure():
    report = empty_report()
    report["consoleErrors"] = [{"message": "Failed to load reference views: SyntaxError: Unexpected token I in JSON",
                                "location": {"url": BASE + "/"}}]
    assert not classify_failures(report)
    report["httpFailures"] = [failure("/api/reference-views/MMLE-50D", 500)]
    assert classify_failures(report)
    report["consoleErrors"].append({"message": "Unexpected document editor error", "location": {}})
    assert not classify_failures(report)


def test_unlocated_console_errors_and_network_failures_are_not_hidden():
    report = empty_report()
    item = failure("/api/drawing-map/MMLE-50D", 404)
    report["httpFailures"] = [item]
    report["consoleErrors"] = [{**console_resource(item), "location": {}}]
    assert not classify_failures(report)
    report["consoleErrors"] = []
    report["networkFailures"] = [{"url": item["url"], "error": "net::ERR_CONNECTION_RESET"}]
    assert not classify_failures(report)
