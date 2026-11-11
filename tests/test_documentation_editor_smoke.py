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


def test_only_reload_aborted_reads_are_known():
    report = empty_report()
    known = ["http://127.0.0.1:1/api/bridge/status",
             "http://127.0.0.1:1/static/assets/view-toolbar-icons/view-front.png",
             "http://127.0.0.1:1/api/operations-manual/MMLE-50D/renders/" + "a" * 64 + "/page-operations-cover"]
    report["networkFailures"] = [{"url": url, "method": "GET", "error": "net::ERR_ABORTED"} for url in known]
    assert classify_failures(report)
    assert [item["kind"] for item in report["knownFixtureFailures"]] == ["network"] * 3
    for url, method, error in ((known[0], "GET", "net::ERR_CONNECTION_RESET"),
                               (known[2], "POST", "net::ERR_ABORTED"),
                               ("http://127.0.0.1:1/api/parts-manual/MMLE-50D/documentation-scene", "GET", "net::ERR_ABORTED"),
                               ("http://127.0.0.1:1/api/operations-manual/MMLE-50D/documentation-scene/commands", "POST", "net::ERR_ABORTED"),
                               (known[0] + "/extra", "GET", "net::ERR_ABORTED")):
        report = empty_report()
        report["networkFailures"] = [{"url": url, "method": method, "error": error}]
        assert not classify_failures(report), url


def test_p2b_only_the_checked_single_glyph_refusal_is_expected():
    item = failure("/api/specification-sheet/MMLE-50D/pdf", 422, "POST")
    report = empty_report()
    report.update(phase="P2b", httpFailures=[item], consoleErrors=[console_resource(item)],
                  expectedHttpFailures=[{**item, "error": "unsupported_export_glyph", "checked": True}])
    assert classify_failures(report)
    report["httpFailures"].append(deepcopy(item))
    assert not classify_failures(report)
    assert report["unexpectedHttpFailures"] == [item]
    report["httpFailures"].pop()
    report["phase"] = "P2a"
    assert not classify_failures(report)
    report["phase"] = "P2b"
    report["expectedHttpFailures"][0]["error"] = "layout_overflow"
    assert not classify_failures(report)


def test_p3b_only_the_checked_single_column_refusal_is_expected():
    item = failure("/api/documentation/operations_and_maintenance_manual/MMLE-50D/tables", 422, "POST")
    report = empty_report()
    report.update(phase="P3b", httpFailures=[item], consoleErrors=[console_resource(item)],
                  expectedHttpFailures=[{**item, "error": "table_column_too_narrow", "checked": True}])
    assert classify_failures(report)
    report["httpFailures"].append(deepcopy(item))
    assert not classify_failures(report)
    report["httpFailures"].pop()
    for phase in ("P2b", "P3a"):
        report["phase"] = phase
        assert not classify_failures(report)
    report["phase"] = "P3b"
    report["expectedHttpFailures"][0]["checked"] = False
    assert not classify_failures(report)
    report["expectedHttpFailures"][0].update(checked=True, error="invalid_table_operation")
    assert not classify_failures(report)
