"""No-GUI tests for the directly owned, sequential rendering orchestration."""
from contextlib import contextmanager
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from xml.etree import ElementTree

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "run-rendering-check.py"
spec = importlib.util.spec_from_file_location("rendering_check", SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def passing_lock_snapshot(root_count=3):
    return {"bodyChildren": root_count, "frozen": True,
            "lockEvidence": {"uniqueBanner": True, "totalRoots": root_count, "unlockedRootCount": 0},
            "preloadLockDiagnostics": {"schemaVersion": 1, "acknowledged": True,
                "current": {"allProtectedRootsLocked": True, "protectedRootCount": root_count}}}


def passing_fixture_focus_proof():
    html_namespace = "http://www.w3.org/1999/xhtml"
    return {"schemaVersion": 1, "baseline": {"svgFocusable": True, "svgAttributeStillFocusable": True},
            "svgCount": 1, "bannerCount": 1, "closeButtonCount": 1,
            "expectedSvg": True, "nativeHtmlParent": True, "nativeParentInert": True, "parentInertAttribute": True,
            "closeIsButton": True, "svgFocusAttempted": True, "svgFocusBlocked": True,
            "closeFocusAttempted": True, "closeFocusAllowed": True, "errors": [],
            "svg": {"id": "desktop-fixture-svg", "tagName": "svg", "namespaceURI": "http://www.w3.org/2000/svg", "connected": True},
            "parent": {"id": "", "tagName": "DIV", "namespaceURI": html_namespace, "connected": True},
            "banner": {"id": "inspectorpro-desktop-spike-banner", "tagName": "ASIDE", "namespaceURI": html_namespace, "connected": True},
            "close": {"id": "", "tagName": "BUTTON", "namespaceURI": html_namespace, "connected": True}}


def passing_chrome_layout(width=886, height=637):
    def item(key, x, y, item_width, item_height):
        return {"id": key, "visible": True, "bounds": {"x": x, "y": y, "width": item_width, "height": item_height},
                "clipBounds": {"x": 0, "y": 0, "width": width, "height": height},
                "labelBounds": [{"x": x + 4, "y": y + 5, "width": item_width - 8, "height": 15}], "ancestorIds": []}
    tabs = ("drawing", "3dmodel", "assembly", "training", "dfm", "report", "usage", "sessions")
    return {"revision": "chrome-layout-v1", "viewport": {"width": width, "height": height}, "violations": [],
            "toolbar": {"bounds": {"x": 0, "y": 0, "width": width, "height": 42},
                        "controls": [item("brand", 8, 4, 130, 32), item("search", 160, 4, 150, 32)]},
            "tabbar": {"bounds": {"x": 286, "y": 42, "width": width - 332, "height": 60},
                       "tabs": [item(key, 290 + index % 4 * 130, 44 + index // 4 * 28, 126, 26)
                                for index, key in enumerate(tabs)]}}


def passing_report(identity, kind="inert-fixture"):
    report = {"schemaVersion": 2, "diagnosticRevision": "rendering-readiness-v1", "status": "passed",
            "checks": dict.fromkeys(check.CHECKS, "passed"), "electron": "44.3.0", "backendIdentity": identity,
            "markup": {"kind": kind}, "frozen": True, "nodeExposed": False, "researchViews": 0,
            "webContentsCount": 1, "capabilities": {"researchBrowsing": False, "interactive": False},
            "windowSizePolicy": {
                "revision": "work-area-v1",
                "display": {"id": 1, "bounds": {"x": 0, "y": 0, "width": 1920, "height": 1080},
                            "workArea": {"x": 0, "y": 0, "width": 1920, "height": 1040}, "scaleFactor": 1},
                "nominalWide": [1440, 960], "nominalNarrow": [900, 700], "minimum": [800, 600],
                "availableWorkArea": {"x": 0, "y": 0, "width": 1920, "height": 1040},
                "wide": [1440, 960], "narrow": [900, 700],
                "wideBounds": {"x": 240, "y": 40, "width": 1440, "height": 960}, "exactWide": True},
            "referenceWideCapture": {"requestedOuterSize": [1440, 960], "status": "passed"},
            "captures": {"wide": {"verified": True, "outerSize": {"width": 1440, "height": 960}},
                         "narrow": {"verified": True, "outerSize": {"width": 900, "height": 700}}}}
    root_count = 3 if kind == "inert-fixture" else 33
    report.update(passing_lock_snapshot(root_count))
    report["inputLockRevision"] = "html-root-lock-v1"
    report["events"] = [{"name": "input-lock-rechecked", "phase": phase, **passing_lock_snapshot(root_count)}
                        for phase in ("before-wide-capture", "after-wide-capture", "before-narrow-capture", "after-narrow-capture")]
    if kind == "inert-fixture":
        report["fixtureFocusProof"] = passing_fixture_focus_proof()
    else:
        report["chromeLayout"] = passing_chrome_layout(1426, 897)
        for index, event in enumerate(report["events"]):
            event["chromeLayout"] = passing_chrome_layout(1426, 897) if index < 2 else passing_chrome_layout()
        report["captures"]["wide"]["frameCheckpoint"] = {"viewport": {"width": 1426, "height": 897}}
        report["captures"]["narrow"]["frameCheckpoint"] = {"viewport": {"width": 886, "height": 637}}
    return report


def observed_small_screen_report(identity):
    """Actual display metadata from the user's normal-terminal diagnostic."""
    report = passing_report(identity)
    report["windowSizePolicy"].update({
        "display": {"id": 175881639, "bounds": {"x": 0, "y": 0, "width": 1536, "height": 864},
                    "workArea": {"x": 0, "y": 0, "width": 1536, "height": 816}, "scaleFactor": 1.25},
        "availableWorkArea": {"x": 0, "y": 0, "width": 1536, "height": 816},
        "wide": [1440, 816], "wideBounds": {"x": 48, "y": 0, "width": 1440, "height": 816},
        "exactWide": False})
    report["captures"]["wide"]["outerSize"] = {"width": 1440, "height": 816}
    report["referenceWideCapture"].update({"status": "not-exercised", "reason":
        "The selected display work area cannot fit the nominal 1440x960 DIP window."})
    return report


class RenderingCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.identity = {"schemaVersion": 1, "product": "InspectorPro", "mode": "rendering-spike",
                         "backendId": "b", "storeId": "s", "profileId": "check", "interactive": False,
                         "researchBrowsing": False}
        self.binary = {"executable": str(self.base / "electron.exe"), "version": "44.3.0", "sha256": "hash"}
        self.args = SimpleNamespace(output=self.base / "output", data_root=self.base / "data", profile_id="check",
                                    port=8197, startup_timeout=45, electron_timeout=90, backend_check_only=False)

    def tearDown(self):
        self.temp.cleanup()

    def test_both_inert_fixtures_have_a_direct_focusable_svg_root(self):
        node_source = SCRIPT.with_name("electron-smoke.cjs").read_text(encoding="utf-8")
        literal = re.search(r"response\.end\('(?P<html><!doctype html>.*?)'\)", node_source)
        self.assertIsNotNone(literal, "The standalone smoke fixture must remain inspectable without launching Electron")
        fixtures = {"python-orchestrator": check.FIXTURE_HTML.decode("utf-8"),
                    "node-smoke": literal.group("html")}
        namespace = "{http://www.w3.org/2000/svg}"
        baseline_scripts = []
        for name, html in fixtures.items():
            with self.subTest(fixture=name):
                document = ElementTree.fromstring(html.removeprefix("<!doctype html>"))
                self.assertEqual(document.findtext("head/title"), "InspectorPro fixture")
                body = document.find("body")
                main = body.find("main")
                self.assertEqual(main.get("data-inspectorpro-rendering-fixture"), "true")
                self.assertEqual(main.findtext("h1"), "InspectorPro desktop acceptance fixture")
                self.assertIsNotNone(main.find("button[@id='edit']"))
                # A direct foreign-namespace root exercises the real preload's
                # HTML inert-wrapper path before the full application can start.
                svg = body.find(namespace + "svg")
                self.assertIsNotNone(svg)
                self.assertEqual(svg.get("id"), "desktop-fixture-svg")
                self.assertEqual(svg.get("tabindex"), "0")
                self.assertEqual((svg.get("width"), svg.get("height")), ("24", "24"))
                self.assertNotIn("hidden", svg.attrib)
                self.assertIsNotNone(svg.find(namespace + "circle"))
                self.assertFalse(any(key.endswith("href") for element in svg.iter() for key in element.attrib))
                script = body.find("script")
                self.assertIsNotNone(script)
                self.assertEqual(list(body), [main, svg, script])
                self.assertNotIn("src", script.attrib)
                self.assertNotIn("DOMContentLoaded", script.text)
                self.assertIn("window.__desktopFixtureFocusBaseline = Object.freeze(baseline)", script.text)
                baseline_scripts.append(script.text)
        self.assertEqual(baseline_scripts[0], baseline_scripts[1])

    @unittest.skipUnless(shutil.which("node"), "Node is needed only to verify fixture baseline recording")
    def test_fixture_baseline_records_observed_focus_behavior_and_cleans_up(self):
        document = ElementTree.fromstring(check.FIXTURE_HTML.decode("utf-8").removeprefix("<!doctype html>"))
        baseline_script = document.find("body/script").text
        # Simulate both SVG-attribute behaviors and a nonfocusable SVG. This
        # verifies honest recording and cleanup, not Chromium's native behavior.
        harness = r"""
const vm = require('node:vm'), fs = require('node:fs');
const source = fs.readFileSync(0, 'utf8');
const modes = [{focusable: true, attributeBlocksFocus: false},
  {focusable: true, attributeBlocksFocus: true}, {focusable: false, attributeBlocksFocus: false}];
const results = modes.map(mode => {
  let inert = false;
  const document = {activeElement: null};
  const svg = {
    focus() { if (mode.focusable && !(mode.attributeBlocksFocus && inert)) document.activeElement = svg; },
    blur() { if (document.activeElement === svg) document.activeElement = null; },
    setAttribute(name) { if (name !== 'inert') throw Error('Unexpected attribute'); inert = true; },
    removeAttribute(name) { if (name !== 'inert') throw Error('Unexpected attribute'); inert = false; }
  };
  document.getElementById = id => { if (id !== 'desktop-fixture-svg') throw Error('Unexpected target'); return svg; };
  const window = {};
  vm.runInNewContext(source, {document, window}, {timeout: 1000});
  return {baseline: window.__desktopFixtureFocusBaseline,
    frozen: Object.isFrozen(window.__desktopFixtureFocusBaseline), blurred: document.activeElement === null, inert};
});
process.stdout.write(JSON.stringify(results));
"""
        result = subprocess.run([shutil.which("node"), "-e", harness], input=baseline_script,
                                capture_output=True, text=True, timeout=10, check=True)
        observations = json.loads(result.stdout)
        self.assertEqual([item["baseline"] for item in observations], [
            {"svgFocusable": True, "svgAttributeStillFocusable": True},
            {"svgFocusable": True, "svgAttributeStillFocusable": False},
            {"svgFocusable": False, "svgAttributeStillFocusable": False}])
        for item in observations:
            self.assertTrue(item["frozen"])
            self.assertTrue(item["blurred"])
            self.assertFalse(item["inert"])

    def test_staged_report_requires_every_check_and_exact_identity_kind(self):
        report = passing_report(self.identity)
        check.validate_report(report, kind="inert-fixture", identity=self.identity, electron_version="44.3.0")
        for field, value in [("firstPaint", "running"), ("lifecycleClose", "failed")]:
            broken = passing_report(self.identity)
            broken["checks"][field] = value
            with self.assertRaises(ValueError):
                check.validate_report(broken, kind="inert-fixture", identity=self.identity, electron_version="44.3.0")
        for kind, identity, version in [("full-application", self.identity, "44.3.0"),
                                         ("inert-fixture", {"other": "store"}, "44.3.0"),
                                         ("inert-fixture", self.identity, "43.0.0")]:
            with self.assertRaises(ValueError):
                check.validate_report(report, kind=kind, identity=identity, electron_version=version)

    def validate(self, report):
        check.validate_report(report, kind="inert-fixture", identity=self.identity, electron_version="44.3.0")

    def test_full_application_requires_current_lock_but_no_fixture_focus_proof(self):
        report = passing_report(self.identity, "full-application")
        self.assertNotIn("fixtureFocusProof", report)
        check.validate_report(report, kind="full-application", identity=self.identity, electron_version="44.3.0")
        report.pop("preloadLockDiagnostics")
        with self.assertRaisesRegex(ValueError, "input-lock"):
            check.validate_report(report, kind="full-application", identity=self.identity, electron_version="44.3.0")

    def test_full_application_geometry_is_required_at_each_capture_boundary(self):
        for target in ("initial", 0, 1, 2, 3):
            with self.subTest(target=target):
                report = passing_report(self.identity, "full-application")
                current = report if target == "initial" else report["events"][target]
                current.pop("chromeLayout")
                with self.assertRaisesRegex(ValueError, "chrome layout"):
                    check.validate_report(report, kind="full-application", identity=self.identity, electron_version="44.3.0")

    def test_python_geometry_recomputes_clipping_overlap_and_label_visibility(self):
        for failure in ("toolbar-overlap", "sessions-clipped", "label-clipped", "ancestor-clipped", "tab-hidden", "label-missing"):
            with self.subTest(failure=failure):
                layout = passing_chrome_layout()
                if failure == "toolbar-overlap":
                    control = layout["toolbar"]["controls"][1]
                    control["bounds"]["x"] = 100
                    control["labelBounds"][0]["x"] = 104
                elif failure == "sessions-clipped": layout["tabbar"]["tabs"][7]["bounds"]["x"] = 860
                elif failure == "label-clipped": layout["tabbar"]["tabs"][7]["labelBounds"][0]["width"] = 180
                elif failure == "ancestor-clipped": layout["toolbar"]["controls"][1]["clipBounds"]["width"] = 200
                elif failure == "tab-hidden": layout["tabbar"]["tabs"][7]["visible"] = False
                else: layout["tabbar"]["tabs"][7]["labelBounds"] = []
                self.assertEqual(layout["violations"], [])
                with self.assertRaisesRegex(ValueError, "chrome layout"):
                    check.validate_chrome_layout(layout)

    def test_python_geometry_allows_wrapped_rows_and_actual_ancestor_controls(self):
        layout = passing_chrome_layout()
        layout["tabbar"]["tabs"][0]["labelBounds"].append({"x": 294, "y": 62, "width": 50, "height": 8})
        layout["toolbar"]["controls"].append({"id": "nested", "visible": True,
            "bounds": {"x": 168, "y": 8, "width": 130, "height": 24},
            "clipBounds": {"x": 0, "y": 0, "width": 886, "height": 637}, "labelBounds": [], "ancestorIds": ["search"]})
        check.validate_chrome_layout(layout)
        layout["toolbar"]["controls"][-1]["ancestorIds"] = []
        with self.assertRaisesRegex(ValueError, "overlapping"):
            check.validate_chrome_layout(layout)

    def test_narrow_before_geometry_can_precede_resize_but_after_must_match_capture(self):
        report = passing_report(self.identity, "full-application")
        report["events"][2]["chromeLayout"] = passing_chrome_layout(1426, 897)
        check.validate_report(report, kind="full-application", identity=self.identity, electron_version="44.3.0")
        report["events"][3]["chromeLayout"] = passing_chrome_layout(1426, 897)
        with self.assertRaisesRegex(ValueError, "stale relative"):
            check.validate_report(report, kind="full-application", identity=self.identity, electron_version="44.3.0")

    def test_old_or_incomplete_input_lock_reports_cannot_pass(self):
        for field in ("inputLockRevision", "bodyChildren", "lockEvidence", "preloadLockDiagnostics"):
            with self.subTest(missing=field):
                report = passing_report(self.identity)
                report.pop(field)
                with self.assertRaises(ValueError):
                    self.validate(report)
        for field, value in (("inputLockRevision", "html-root-lock-v2"), ("bodyChildren", 0), ("bodyChildren", True)):
            with self.subTest(field=field, value=value):
                report = passing_report(self.identity)
                report[field] = value
                with self.assertRaises(ValueError):
                    self.validate(report)

    def test_acknowledgement_does_not_override_stale_or_mismatched_current_locks(self):
        cases = (("lockEvidence", "uniqueBanner", False), ("lockEvidence", "unlockedRootCount", 1),
                 ("lockEvidence", "unlockedRootCount", False), ("lockEvidence", "totalRoots", 2),
                 ("preloadLockDiagnostics", "schemaVersion", True),
                 ("preloadLockDiagnostics", "acknowledged", False),
                 ("preloadLockDiagnostics", "current", None))
        for container, key, value in cases:
            with self.subTest(container=container, key=key):
                report = passing_report(self.identity)
                report[container][key] = value
                with self.assertRaises(ValueError):
                    self.validate(report)
        for current in ({}, {"allProtectedRootsLocked": False, "protectedRootCount": 3},
                        {"allProtectedRootsLocked": True, "protectedRootCount": 2},
                        {"allProtectedRootsLocked": 1, "protectedRootCount": 3}):
            with self.subTest(current=current):
                report = passing_report(self.identity)
                report["preloadLockDiagnostics"]["current"] = current
                self.assertTrue(report["preloadLockDiagnostics"]["acknowledged"])
                with self.assertRaisesRegex(ValueError, "current native input lock"):
                    self.validate(report)

    def test_each_capture_recheck_is_required_exactly_once_and_in_order(self):
        report = passing_report(self.identity)
        events = report["events"]
        for invalid in (None, [], events[:3], events + [events[0]], list(reversed(events)),
                        [dict(events[0], phase="unknown")] + events[1:]):
            with self.subTest(events=invalid):
                broken = passing_report(self.identity)
                broken["events"] = invalid
                with self.assertRaisesRegex(ValueError, "recheck"):
                    self.validate(broken)

    def test_current_lock_is_revalidated_at_all_four_capture_boundaries(self):
        for index in range(4):
            for failure in ("missing-main", "missing-preload", "stale-ack", "mismatched-count", "unfrozen"):
                with self.subTest(phase=index, failure=failure):
                    report = passing_report(self.identity)
                    event = report["events"][index]
                    if failure == "missing-main": event.pop("lockEvidence")
                    elif failure == "missing-preload": event.pop("preloadLockDiagnostics")
                    elif failure == "stale-ack": event["preloadLockDiagnostics"]["current"]["allProtectedRootsLocked"] = False
                    elif failure == "mismatched-count": event["lockEvidence"]["totalRoots"] = 4
                    else: event["frozen"] = False
                    with self.assertRaises(ValueError):
                        self.validate(report)

    def test_rechecks_allow_new_protected_roots_with_matching_current_counts(self):
        report = passing_report(self.identity)
        for index, event in enumerate(report["events"]):
            event.update(passing_lock_snapshot(3 + index))
        report["events"].insert(1, {"name": "stage-started", "stage": "wideCapture"})
        self.validate(report)

    def test_fixture_focus_proof_requires_actual_attempts_baseline_and_outcomes(self):
        report = passing_report(self.identity)
        report.pop("fixtureFocusProof")
        with self.assertRaisesRegex(ValueError, "native focus proof"):
            self.validate(report)
        fields = ("expectedSvg", "nativeHtmlParent", "nativeParentInert", "parentInertAttribute",
                  "closeIsButton", "svgFocusAttempted", "svgFocusBlocked", "closeFocusAttempted", "closeFocusAllowed")
        for field in fields:
            with self.subTest(field=field):
                report = passing_report(self.identity)
                report["fixtureFocusProof"][field] = False
                with self.assertRaisesRegex(ValueError, "native focus proof"):
                    self.validate(report)
        for field in ("svgFocusable", "svgAttributeStillFocusable"):
            report = passing_report(self.identity)
            report["fixtureFocusProof"]["baseline"][field] = False
            with self.assertRaisesRegex(ValueError, "native focus proof"):
                self.validate(report)
        for field, value in (("svgCount", 2), ("bannerCount", 0), ("closeButtonCount", True),
                             ("schemaVersion", True), ("errors", None), ("errors", ["native focus failed"])):
            with self.subTest(field=field):
                report = passing_report(self.identity)
                report["fixtureFocusProof"][field] = value
                with self.assertRaisesRegex(ValueError, "native focus proof"):
                    self.validate(report)

    def test_fixture_focus_proof_rejects_false_native_node_identity(self):
        for node, key, value in (("svg", "tagName", "DIV"), ("svg", "id", "another-svg"),
                                 ("parent", "namespaceURI", "http://www.w3.org/2000/svg"),
                                 ("banner", "id", "another-banner"), ("close", "tagName", "A")):
            with self.subTest(node=node, key=key):
                report = passing_report(self.identity)
                report["fixtureFocusProof"][node][key] = value
                with self.assertRaisesRegex(ValueError, "invalid node evidence"):
                    self.validate(report)
        for node in ("svg", "parent", "banner", "close"):
            report = passing_report(self.identity)
            report["fixtureFocusProof"][node]["connected"] = False
            with self.assertRaisesRegex(ValueError, "invalid node evidence"):
                self.validate(report)

    def test_large_display_passes_exact_reference_without_dpi_rescaling(self):
        for scale in (1, 1.25, 2):
            with self.subTest(scale=scale):
                report = passing_report(self.identity)
                report["windowSizePolicy"]["display"]["scaleFactor"] = scale
                self.validate(report)

    def test_observed_small_display_passes_fitted_capture_with_unexercised_reference(self):
        report = observed_small_screen_report(self.identity)
        self.validate(report)
        self.assertEqual(report["windowSizePolicy"]["wide"], [1440, 816])
        self.assertEqual(report["referenceWideCapture"]["status"], "not-exercised")

    def test_fractional_negative_work_area_uses_inner_integer_dip_rectangle(self):
        report = observed_small_screen_report(self.identity)
        report["windowSizePolicy"].update({
            "display": {"id": -2, "bounds": {"x": -1280, "y": -100, "width": 1280, "height": 1000},
                        "workArea": {"x": -1200.75, "y": -40.25, "width": 1200.5, "height": 840.75},
                        "scaleFactor": 1.5},
            "availableWorkArea": {"x": -1200, "y": -40, "width": 1199, "height": 840},
            "wide": [1199, 840], "wideBounds": {"x": -1200, "y": -40, "width": 1199, "height": 840}})
        report["captures"]["wide"]["outerSize"] = {"width": 1199, "height": 840}
        self.validate(report)

    def test_missing_or_changed_window_policy_cannot_pass(self):
        for replacement in (None, {}, {"revision": "work-area-v2"}):
            with self.subTest(replacement=replacement):
                report = passing_report(self.identity)
                report["windowSizePolicy"] = replacement
                with self.assertRaisesRegex(ValueError, "policy"):
                    self.validate(report)
        for key, value in (("revision", "work-area-v2"), ("nominalWide", [1426, 835]),
                           ("nominalNarrow", [899, 700]), ("minimum", [700, 500])):
            with self.subTest(key=key):
                report = passing_report(self.identity)
                report["windowSizePolicy"][key] = value
                with self.assertRaisesRegex(ValueError, "policy"):
                    self.validate(report)

    def test_rejects_insufficient_work_area_and_indistinguishable_stages(self):
        for width, height, reason in ((799, 900, "minimum"), (1600, 599, "minimum"),
                                      (900, 700, "distinct"), (800, 600, "distinct")):
            with self.subTest(width=width, height=height):
                report = passing_report(self.identity)
                work = {"x": 0, "y": 0, "width": width, "height": height}
                report["windowSizePolicy"]["display"]["workArea"] = work
                report["windowSizePolicy"]["availableWorkArea"] = dict(work)
                with self.assertRaisesRegex(ValueError, reason):
                    self.validate(report)

    def test_rejects_noncanonical_geometry_even_when_report_and_capture_agree(self):
        cases = (("availableWorkArea", {"x": 0, "y": 0, "width": 1536, "height": 815}),
                 ("availableWorkArea", {"x": 0, "y": 0, "width": 1536.0, "height": 816}),
                 ("wideBounds", {"x": 0, "y": 0, "width": 1440, "height": 816}),
                 ("wide", [1426, 835]), ("wide", [1440.0, 816]), ("narrow", [899, 700]))
        for key, value in cases:
            with self.subTest(key=key, value=value):
                report = observed_small_screen_report(self.identity)
                report["windowSizePolicy"][key] = value
                if key in {"wide", "narrow"}:
                    report["captures"][key]["outerSize"] = {"width": value[0], "height": value[1]}
                with self.assertRaises(ValueError):
                    self.validate(report)
        # Applying scaleFactor a second time yields physical pixels, not a valid DIP plan.
        report = observed_small_screen_report(self.identity)
        report["windowSizePolicy"]["wide"] = [1800, 1020]
        report["captures"]["wide"]["outerSize"] = {"width": 1800, "height": 1020}
        with self.assertRaisesRegex(ValueError, "fitted window sizes"):
            self.validate(report)

    def test_capture_outer_sizes_must_exactly_equal_planned_integer_dips(self):
        for stage in ("wide", "narrow"):
            for actual in (None, [1440, 816], {"width": 1426, "height": 835},
                           {"width": 1440.0, "height": 816}, {"width": True, "height": 816}):
                with self.subTest(stage=stage, actual=actual):
                    report = observed_small_screen_report(self.identity)
                    report["captures"][stage]["outerSize"] = actual
                    with self.assertRaisesRegex(ValueError, "actual capture size"):
                        self.validate(report)

    def test_false_exact_reference_claims_and_missing_fitted_reasons_cannot_pass(self):
        for exact in (True, 0, "false"):
            with self.subTest(exact=exact):
                report = observed_small_screen_report(self.identity)
                report["windowSizePolicy"]["exactWide"] = exact
                with self.assertRaisesRegex(ValueError, "exact-wide"):
                    self.validate(report)
        for reference in (None, {"requestedOuterSize": [1440, 960], "status": "passed"},
                          {"requestedOuterSize": [1440, 816], "status": "not-exercised", "reason": "work area"},
                          {"requestedOuterSize": [1440, 960], "status": "not-exercised"},
                          {"requestedOuterSize": [1440, 960], "status": "not-exercised", "reason": "clamped"}):
            with self.subTest(reference=reference):
                report = observed_small_screen_report(self.identity)
                report["referenceWideCapture"] = reference
                with self.assertRaises(ValueError):
                    self.validate(report)
        report = passing_report(self.identity)
        report["referenceWideCapture"]["status"] = "not-exercised"
        with self.assertRaisesRegex(ValueError, "reference capture claim"):
            self.validate(report)
        report = passing_report(self.identity)
        report["checks"]["wideCapture"] = "pending"
        with self.assertRaisesRegex(ValueError, "every required check"):
            self.validate(report)

    def test_rejects_invalid_numeric_display_metadata(self):
        for key, value in (("id", True), ("scaleFactor", 0), ("scaleFactor", float("nan")),
                           ("scaleFactor", float("inf"))):
            with self.subTest(key=key, value=value):
                report = passing_report(self.identity)
                report["windowSizePolicy"]["display"][key] = value
                with self.assertRaises(ValueError):
                    self.validate(report)
        for key, value in (("x", float("inf")), ("width", -1), ("height", True)):
            with self.subTest(key=key, value=value):
                report = passing_report(self.identity)
                report["windowSizePolicy"]["display"]["workArea"][key] = value
                with self.assertRaisesRegex(ValueError, "bounds/work area"):
                    self.validate(report)

    def test_work_area_must_be_inside_display_bounds_and_use_safe_coordinates(self):
        for work in ({"x": -1, "y": 0, "width": 1920, "height": 1040},
                     {"x": 0, "y": 0, "width": 1921, "height": 1040},
                     {"x": 0, "y": 0, "width": 1920, "height": 1081}):
            with self.subTest(work=work):
                report = passing_report(self.identity)
                report["windowSizePolicy"]["display"]["workArea"] = work
                with self.assertRaisesRegex(ValueError, "contained"):
                    self.validate(report)
        for rectangle in ({"x": 2 ** 53, "y": 0, "width": 1000, "height": 1000},
                          {"x": 2 ** 53 - 500, "y": 0, "width": 1000, "height": 1000},
                          {"x": -2 ** 53, "y": 0, "width": 1000, "height": 1000}):
            with self.subTest(rectangle=rectangle):
                report = passing_report(self.identity)
                report["windowSizePolicy"]["display"]["bounds"] = rectangle
                with self.assertRaisesRegex(ValueError, "bounds/work area"):
                    self.validate(report)

    def test_bounded_string_display_id_and_work_area_reason_follow_js_contract(self):
        report = observed_small_screen_report(self.identity)
        report["windowSizePolicy"]["display"]["id"] = "diagnostic-display-1"
        report["referenceWideCapture"]["reason"] = "Selected WORK-AREA is too small."
        self.validate(report)
        for display_id in ("", "x" * 129, "\U0001F5A5" * 65, 2 ** 53):
            with self.subTest(display_id=display_id):
                report["windowSizePolicy"]["display"]["id"] = display_id
                with self.assertRaisesRegex(ValueError, "display identity"):
                    self.validate(report)
        report = observed_small_screen_report(self.identity)
        report["referenceWideCapture"]["reason"] = "work area " + "x" * 1024
        with self.assertRaisesRegex(ValueError, "work area limitation"):
            self.validate(report)

    @unittest.skipUnless(shutil.which("node"), "Node is needed only for cross-runtime policy agreement")
    def test_python_parent_accepts_canonical_node_generated_plans_without_electron(self):
        displays = [passing_report(self.identity)["windowSizePolicy"]["display"],
                    observed_small_screen_report(self.identity)["windowSizePolicy"]["display"],
                    {"id": "fractional", "bounds": {"x": -1280, "y": -100, "width": 1280, "height": 1000},
                     "workArea": {"x": -1200.75, "y": -40.25, "width": 1200.5, "height": 840.75},
                     "scaleFactor": 1.5},
                    {"id": "odd-center", "bounds": {"x": 0, "y": 0, "width": 2000, "height": 1100},
                     "workArea": {"x": 11, "y": 15, "width": 1921, "height": 1041}, "scaleFactor": 2},
                    {"id": "short", "bounds": {"x": 0, "y": 0, "width": 1040, "height": 700},
                     "workArea": {"x": 0, "y": 0, "width": 1040, "height": 650}, "scaleFactor": 1}]
        script = ("const {planRenderingWindows}=require(process.argv[1]);"
                  "const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));"
                  "process.stdout.write(JSON.stringify(input.map(planRenderingWindows)));")
        result = subprocess.run([shutil.which("node"), "-e", script,
                                 str(SCRIPT.with_name("rendering-window-policy.cjs"))],
                                input=json.dumps(displays), capture_output=True, text=True, timeout=10, check=True)
        plans = json.loads(result.stdout)
        self.assertEqual(len(plans), len(displays))
        for plan in plans:
            with self.subTest(display=plan["display"]["id"]):
                report = passing_report(self.identity)
                report["windowSizePolicy"] = plan
                for kind in ("wide", "narrow"):
                    report["captures"][kind]["outerSize"] = {"width": plan[kind][0], "height": plan[kind][1]}
                if not plan["exactWide"]:
                    report["referenceWideCapture"].update({"status": "not-exercised", "reason": "work area limitation"})
                self.validate(report)

    def test_no_backend_preparation_after_inert_failure(self):
        @contextmanager
        def fixture(output):
            yield {"identity": self.identity, "origin": "http://127.0.0.1:1234", "marker": output / "identity.json"}
        with patch.object(check.backend, "verify_snapshot", return_value=self.base / "live"), \
             patch.object(check, "resolve_electron", return_value=self.binary), \
             patch.object(check, "inert_fixture", fixture), \
             patch.object(check, "run_electron_stage", side_effect=ValueError("first paint failed")), \
             patch.object(check, "run_backend_stage") as backend_stage:
            with self.assertRaisesRegex(ValueError, "first paint"):
                check.execute(self.args)
        backend_stage.assert_not_called()
        report = json.loads((self.args.output / "rendering-check.json").read_text())
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["fullRenderingPassed"])

    def test_stage_order_and_full_success_receipt(self):
        calls = []
        @contextmanager
        def fixture(output):
            yield {"identity": self.identity, "origin": "http://127.0.0.1:1234", "marker": output / "identity.json"}
            calls.append("inert-server-closed")
        def inert(*args):
            calls.append("inert-passed")
            return {"status": "passed"}
        def backend_stage(*args):
            calls.append("backend-prepared")
            return {"status": "passed", "terminationConfirmed": True}
        with patch.object(check.backend, "verify_snapshot", return_value=self.base / "live"), \
             patch.object(check, "resolve_electron", return_value=self.binary), \
             patch.object(check, "inert_fixture", fixture), patch.object(check, "run_electron_stage", inert), \
             patch.object(check, "run_backend_stage", backend_stage):
            result = check.execute(self.args)
        self.assertEqual(calls, ["inert-passed", "inert-server-closed", "backend-prepared"])
        self.assertTrue(result["fullRenderingPassed"])

    def test_explicit_backend_only_never_resolves_or_launches_electron(self):
        self.args.backend_check_only = True
        with patch.object(check.backend, "verify_snapshot", return_value=self.base / "live"), \
             patch.object(check, "resolve_electron") as resolve, patch.object(check, "run_electron_stage") as electron, \
             patch.object(check, "run_backend_stage", return_value={"status": "passed"}) as stage:
            result = check.execute(self.args)
        resolve.assert_not_called(); electron.assert_not_called()
        self.assertIsNone(stage.call_args.args[2])
        self.assertFalse(result["fullRenderingPassed"])
        self.assertEqual(result["mode"], "backend-check-only")

    def test_output_cannot_reuse_stale_results_or_overlap_backend_data(self):
        self.args.output.mkdir()
        with patch.object(check.backend, "verify_snapshot", return_value=self.base / "live"):
            with self.assertRaises(FileExistsError):
                check.execute(self.args)
            self.args.output = self.args.data_root / "reports"
            with self.assertRaisesRegex(ValueError, "non-overlapping"):
                check.execute(self.args)

    def test_direct_electron_pass_has_no_wrapper_or_false_stdio_eof_claim(self):
        stage = self.base / "stage"
        process = Mock(pid=123)
        process.wait.return_value = 0
        process.poll.return_value = 0
        process.stdout = io.BytesIO(b"Electron diagnostic output\n")
        def spawn(command, **options):
            self.assertEqual(command[0], self.binary["executable"])
            self.assertIn("--expected-page", command)
            self.assertNotIn("node", command)
            check.write_json(stage / "report.json", passing_report(self.identity))
            for name in ("desktop-wide.png", "desktop-narrow.png"):
                (stage / name).write_bytes(b"\x89PNG\r\n\x1a\nsynthetic test capture")
            return process
        with patch.object(check, "file_hash", return_value="hash"), \
             patch.object(check.tempfile, "mkdtemp", return_value=str(self.base / "state")), \
             patch.object(check.backend, "stop_child") as stop:
            result = check.run_electron_stage(self.binary, stage, "http://127.0.0.1:1234", self.base / "identity.json",
                                             self.identity, "inert-fixture", 90, process_factory=spawn)
        stop.assert_called_once_with(process)
        self.assertEqual(result["status"], "passed")
        receipt = json.loads((stage / "process-result.json").read_text())
        self.assertTrue(receipt["terminationConfirmed"])
        self.assertTrue(receipt["stdioClosed"])
        self.assertTrue(receipt["stdioEOFVerified"])
        self.assertFalse(receipt["descendantTerminationVerified"])

    def test_direct_electron_timeout_persists_error_and_stops_owned_process(self):
        stage = self.base / "stage"
        process = Mock(pid=124)
        process.wait.side_effect = subprocess.TimeoutExpired("electron", 90)
        process.poll.return_value = 1
        process.stdout = io.BytesIO(b"before timeout\n")
        with patch.object(check, "file_hash", return_value="hash"), \
             patch.object(check.tempfile, "mkdtemp", return_value=str(self.base / "state")), \
             patch.object(check.backend, "stop_child") as stop:
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                check.run_electron_stage(self.binary, stage, "http://127.0.0.1:1234", self.base / "identity.json",
                    self.identity, "inert-fixture", 90, process_factory=lambda *args, **kwargs: process)
        stop.assert_called_once_with(process)
        self.assertEqual(json.loads((stage / "process-result.json").read_text())["status"], "timed-out")

    def test_parent_exit_without_pipe_eof_cannot_pass(self):
        release = threading.Event()
        class HeldPipe:
            def read1(self, size):
                release.wait(2)
                return b""
            def close(self):
                pass
        process = Mock(pid=126)
        process.wait.return_value = 0
        process.poll.return_value = 0
        process.stdout = HeldPipe()
        stage = self.base / "held-pipe"
        try:
            with patch.object(check, "file_hash", return_value="hash"), \
                 patch.object(check.tempfile, "mkdtemp", return_value=str(self.base / "state")), \
                 patch.object(check.backend, "stop_child"):
                with self.assertRaisesRegex(RuntimeError, "diagnostic EOF"):
                    check.run_electron_stage(self.binary, stage, "http://127.0.0.1:1234", self.base / "identity.json",
                        self.identity, "inert-fixture", 90, process_factory=lambda *args, **kwargs: process, drain_timeout=0.01)
            receipt = json.loads((stage / "process-result.json").read_text())
            self.assertEqual(receipt["status"], "stdio-unconfirmed")
            self.assertFalse(receipt["stdioEOFVerified"])
            self.assertFalse(receipt["stdioClosed"])
        finally:
            release.set()
            for thread in threading.enumerate():
                if thread.name == "electron-diagnostic-pipe":
                    thread.join(timeout=2)

    def test_reader_setup_failure_still_stops_direct_child(self):
        stage = self.base / "reader-failure"
        process = Mock(pid=127)
        process.poll.return_value = 1
        process.stdout = io.BytesIO(b"unread")
        with patch.object(check, "file_hash", return_value="hash"), \
             patch.object(check.tempfile, "mkdtemp", return_value=str(self.base / "state")), \
             patch.object(check, "start_pipe_capture", side_effect=RuntimeError("thread creation failed")), \
             patch.object(check.backend, "stop_child") as stop:
            with self.assertRaisesRegex(RuntimeError, "thread creation"):
                check.run_electron_stage(self.binary, stage, "http://127.0.0.1:1234", self.base / "identity.json",
                    self.identity, "inert-fixture", 90, process_factory=lambda *args, **kwargs: process)
        stop.assert_called_once_with(process)
        self.assertIn("thread creation failed", (stage / "electron.log").read_text())
        self.assertFalse(json.loads((stage / "process-result.json").read_text())["stdioEOFVerified"])

    def test_spawn_failure_has_durable_log_and_receipt(self):
        stage = self.base / "spawn-failure"
        with patch.object(check, "file_hash", return_value="hash"), \
             patch.object(check.tempfile, "mkdtemp", return_value=str(self.base / "state")):
            with self.assertRaisesRegex(OSError, "fixture launch denied"):
                check.run_electron_stage(self.binary, stage, "http://127.0.0.1:1234", self.base / "identity.json",
                    self.identity, "inert-fixture", 90, process_factory=Mock(side_effect=OSError("fixture launch denied")))
        self.assertIn("fixture launch denied", (stage / "electron.log").read_text())
        self.assertEqual(json.loads((stage / "process-result.json").read_text())["status"], "spawn-error")

    def test_partial_diagnostic_writes_preserve_every_byte_before_eof(self):
        class PartialWriter:
            value = bytearray()
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def write(self, data):
                count = min(2, len(data))
                self.value.extend(data[:count])
                return count
            def fileno(self): return 123
        writer = PartialWriter()
        with patch.object(Path, "open", return_value=writer), patch.object(check.os, "fsync"):
            reader, result = check.start_pipe_capture(io.BytesIO(b"complete bytes"), self.base / "diagnostic.log")
            reader.join(timeout=2)
        self.assertEqual(writer.value, b"complete bytes")
        self.assertTrue(result["eof"])
        self.assertTrue(result["closed"])
        self.assertIsNone(result["error"])

    def test_backend_stops_direct_child_when_ready_handshake_rejects(self):
        output = self.base / "backend-reports"
        output.mkdir()
        library = self.base / "empty-library"
        library.mkdir()
        identity = {**self.identity, "origin": "http://127.0.0.1:8197"}
        process = Mock(pid=125)
        process.poll.return_value = 1
        with patch.object(check.backend, "prepare_fixture", return_value=(library, identity)), \
             patch.object(check.backend, "child_environment", return_value={}), \
             patch.object(check.backend, "wait_ready", side_effect=RuntimeError("occupied port")), \
             patch.object(check.backend, "stop_child") as stop, \
             patch.object(check, "run_electron_stage") as electron:
            with self.assertRaisesRegex(RuntimeError, "occupied port"):
                check.run_backend_stage(self.args, output, self.binary, process_factory=lambda *args, **kwargs: process)
        stop.assert_called_once_with(process)
        electron.assert_not_called()
        receipt = json.loads((output / "backend-result.json").read_text())
        self.assertEqual(receipt["status"], "failed")
        self.assertIn("occupied port", receipt["error"])
        self.assertIn("shutdown receipt", receipt["shutdownError"])

    def checkpoint_line(self, instance="instance-one", pid=321, phase="server-import-starting", **extra):
        payload = {"schemaVersion": 1, "pid": pid, "timeUnixMs": 123456,
                   "instanceId": instance, "phase": phase, **extra}
        return check.BACKEND_CHECKPOINT_PREFIX + json.dumps(payload).encode() + b"\n"

    def test_checkpoint_summary_is_bounded_filters_foreign_and_retains_partial_status(self):
        log = self.base / "backend.log"
        rows = [check.BACKEND_BOOTSTRAP_MARKER + b"\n", b"unrelated log\n",
                self.checkpoint_line(secret="DO_NOT_COPY"), self.checkpoint_line(instance="other"),
                self.checkpoint_line(pid=322), check.BACKEND_CHECKPOINT_PREFIX + b"{bad json}\n",
                self.checkpoint_line(phase="server-import-complete")[:-1]]
        log.write_bytes(b"".join(rows))
        proof = check.backend_startup_evidence(log, "instance-one", 321)
        self.assertTrue(proof["bootstrapMarkerObserved"])
        self.assertTrue(proof["incompleteTrailingLine"])
        self.assertEqual(proof["lastCheckpoint"]["phase"], "server-import-starting")
        self.assertEqual(proof["checkpointCountInTail"], 1)
        self.assertEqual(proof["foreignCheckpointLines"], 2)
        self.assertEqual(proof["malformedCheckpointLines"], 1)
        self.assertNotIn("DO_NOT_COPY", json.dumps(proof))
        log.write_bytes(b"x" * 300000 + b"\n" + b"".join(self.checkpoint_line(sequence=i) for i in range(80)))
        proof = check.backend_startup_evidence(log, "instance-one", 321)
        self.assertTrue(proof["truncated"])
        self.assertLessEqual(proof["tailBytes"], 262144)
        self.assertEqual(len(proof["checkpoints"]), 64)
        self.assertEqual(proof["lastCheckpoint"]["sequence"], 79)

    def test_checkpoint_empty_missing_or_deep_json_does_not_invent_progress(self):
        log = self.base / "backend.log"
        missing = check.backend_startup_evidence(log, "instance-one", 321)
        self.assertIsNone(missing["lastCheckpoint"])
        self.assertIn("readError", missing)
        log.write_bytes(b"")
        empty = check.backend_startup_evidence(log, "instance-one", 321)
        self.assertEqual(empty["logBytes"], 0)
        self.assertFalse(empty["bootstrapMarkerObserved"])
        self.assertEqual(empty["checkpointCountInTail"], 0)
        log.write_bytes(check.BACKEND_CHECKPOINT_PREFIX + b"[" * 1100 + b"\n")
        proof = check.backend_startup_evidence(log, "instance-one", 321)
        self.assertEqual(proof["malformedCheckpointLines"], 1)
        self.assertIsNone(proof["lastCheckpoint"])

    @contextmanager
    def backend_case(self, *, prepare_error=None, ready_error=None, with_shutdown=False):
        output = self.base / "backend-case"
        output.mkdir()
        library = self.base / "library"
        library.mkdir()
        identity = {**self.identity, "origin": "http://127.0.0.1:8197"}
        process = Mock(pid=321)
        process.poll.return_value = 1
        launched = {}
        def spawn(command, **options):
            self.assertEqual(command[1], "-u")
            self.assertEqual(options["env"]["PYTHONUNBUFFERED"], "1")
            self.assertIn("spawn-starting", (output / "backend-parent.jsonl").read_text())
            before = json.loads((output / "backend-result.json").read_text())
            self.assertIsNone(before["ownedPid"])
            self.assertEqual(before["phase"], "spawn-starting")
            launched["instance"] = options["env"]["INSPECTORPRO_DESKTOP_INSTANCE_ID"]
            options["stderr"].write(self.checkpoint_line(instance=launched["instance"]))
            return process
        def stop(owned):
            self.assertIs(owned, process)
            with (output / "backend.log").open("ab") as log:
                log.write(self.checkpoint_line(instance=launched.get("instance", "none"), phase="cleanup-starting"))
            if with_shutdown:
                path = check.backend.shutdown_receipt_path(self.args.data_root, launched["instance"])
                check.write_json(path, {"schemaVersion": 1, "instanceId": launched["instance"],
                                       "status": "lifespan-stopped", "resourcesClosed": True})
        with patch.object(check.backend, "prepare_fixture", side_effect=prepare_error,
                          return_value=(library, identity)), \
             patch.object(check.backend, "child_environment", return_value={}), \
             patch.object(check.backend, "wait_ready", side_effect=ready_error) as ready, \
             patch.object(check.backend, "check_http_boundary", return_value={"GET /": 200}), \
             patch.object(check, "fixture_profile_count", return_value=0), \
             patch.object(check.backend, "stop_child", side_effect=stop) as stop_mock, \
             patch.object(check, "run_electron_stage") as electron:
            yield output, spawn, ready, stop_mock, electron

    def test_backend_timeout_snapshots_progress_before_cleanup_and_retains_primary_failure(self):
        with self.backend_case(ready_error=RuntimeError("startup timed out")) as (output, spawn, ready, stop, electron):
            with self.assertRaisesRegex(RuntimeError, "startup timed out"):
                check.run_backend_stage(self.args, output, self.binary, process_factory=spawn)
            self.assertEqual(ready.call_args.args[2], 45)
            stop.assert_called_once(); electron.assert_not_called()
            receipt = json.loads((output / "backend-result.json").read_text())
            self.assertEqual(receipt["failurePhase"], "readiness-wait-starting")
            self.assertEqual(receipt["startupDiagnosticsAtFailure"]["lastCheckpoint"]["phase"], "server-import-starting")
            self.assertEqual(receipt["startupDiagnostics"]["lastCheckpoint"]["phase"], "cleanup-starting")
            self.assertIn("startup timed out", receipt["error"])
            self.assertIn("shutdown receipt", receipt["shutdownError"])
            self.assertTrue(receipt["terminationConfirmed"])
            self.assertFalse(receipt["gracefulResourceCleanupVerified"])
            self.assertFalse(receipt["stdioEOFVerified"])
            self.assertTrue((output / "backend-launch.json").is_file())

    def test_backend_preparation_failure_has_log_and_receipt_without_spawning(self):
        with self.backend_case(prepare_error=ValueError("invalid fixture")) as (output, spawn, ready, stop, electron):
            factory = Mock(side_effect=spawn)
            with self.assertRaisesRegex(ValueError, "invalid fixture"):
                check.run_backend_stage(self.args, output, self.binary, process_factory=factory)
            factory.assert_not_called(); ready.assert_not_called(); stop.assert_not_called(); electron.assert_not_called()
            receipt = json.loads((output / "backend-result.json").read_text())
            self.assertEqual(receipt["failurePhase"], "fixture-preparation-starting")
            self.assertIsNone(receipt["ownedPid"])
            self.assertFalse(receipt["terminationConfirmed"])
            self.assertIn("operation-failed", (output / "backend-parent.jsonl").read_text())

    def test_backend_spawn_failure_keeps_early_diagnostics_and_no_cleanup_claim(self):
        with self.backend_case() as (output, spawn, ready, stop, electron):
            with self.assertRaisesRegex(OSError, "spawn denied"):
                check.run_backend_stage(self.args, output, self.binary,
                    process_factory=Mock(side_effect=OSError("spawn denied")))
            ready.assert_not_called(); stop.assert_not_called(); electron.assert_not_called()
            receipt = json.loads((output / "backend-result.json").read_text())
            self.assertEqual(receipt["failurePhase"], "spawn-starting")
            self.assertIsNone(receipt["ownedPid"])
            self.assertFalse(receipt["gracefulResourceCleanupVerified"])
            self.assertIn("spawn-starting", (output / "backend-parent.jsonl").read_text())

    def test_ready_checkpoints_do_not_replace_resource_cleanup_receipt(self):
        with self.backend_case(with_shutdown=True) as (output, spawn, ready, stop, electron):
            result = check.run_backend_stage(self.args, output, None, process_factory=spawn)
            self.assertEqual(result["status"], "passed")
            self.assertTrue(result["gracefulResourceCleanupVerified"])
            self.assertEqual(result["startupDiagnosticsAtReadiness"]["lastCheckpoint"]["phase"], "server-import-starting")
            self.assertIsNone(result["stdioClosed"])
            self.assertFalse(result["stdioEOFVerified"])
            electron.assert_not_called()

    def test_backend_diagnostic_read_error_does_not_replace_startup_error(self):
        with self.backend_case(ready_error=RuntimeError("primary timeout")) as (output, spawn, ready, stop, electron):
            original_open = Path.open
            def open_path(path, mode="r", *args, **kwargs):
                if path == output / "backend.log" and mode == "rb":
                    raise PermissionError("diagnostic read denied")
                return original_open(path, mode, *args, **kwargs)
            with patch.object(Path, "open", open_path):
                with self.assertRaisesRegex(RuntimeError, "primary timeout"):
                    check.run_backend_stage(self.args, output, None, process_factory=spawn)
            receipt = json.loads((output / "backend-result.json").read_text())
            self.assertIn("read denied", receipt["startupDiagnosticsAtFailure"]["readError"])
            self.assertIn("primary timeout", receipt["error"])
            stop.assert_called_once()

    def test_aggregate_backend_failure_points_to_its_persisted_diagnostics(self):
        self.args.backend_check_only = True
        with patch.object(check.backend, "verify_snapshot", return_value=self.base / "live"), \
             patch.object(check, "run_backend_stage", side_effect=RuntimeError("startup timed out")):
            with self.assertRaisesRegex(RuntimeError, "startup timed out"):
                check.execute(self.args)
        report = json.loads((self.args.output / "rendering-check.json").read_text())
        self.assertEqual(report["stages"]["backend"]["status"], "failed")
        self.assertEqual(report["stages"]["backend"]["report"], str(self.args.output / "backend-result.json"))
        self.assertFalse(report["fullRenderingPassed"])

    def test_final_aggregate_persistence_error_cannot_mask_backend_failure(self):
        self.args.backend_check_only = True
        real_write = check.write_json
        def fail_final(path, value):
            if path.name == "rendering-check.json" and value.get("status") == "failed":
                raise OSError("final report unavailable")
            real_write(path, value)
        stderr = io.StringIO()
        with patch.object(check.backend, "verify_snapshot", return_value=self.base / "live"), \
             patch.object(check, "run_backend_stage", side_effect=RuntimeError("primary backend timeout")), \
             patch.object(check, "write_json", side_effect=fail_final), patch.object(check.sys, "stderr", stderr):
            with self.assertRaisesRegex(RuntimeError, "primary backend timeout"):
                check.execute(self.args)
        self.assertIn("final report unavailable", stderr.getvalue())

    def test_parent_and_real_child_log_writes_use_separate_files(self):
        child_log = self.base / "backend.log"
        parent_log = self.base / "backend-parent.jsonl"
        code = "import sys; print('child-first', flush=True); sys.stdin.readline(); print('child-second', flush=True)"
        with child_log.open("ab", buffering=0) as output:
            process = subprocess.Popen([check.sys.executable, "-u", "-c", code], stdin=subprocess.PIPE,
                                       stdout=output, stderr=output, **check.spawn_options())
            try:
                check.append_backend_parent_event(parent_log, {"phase": "parent-first"})
                process.communicate(input=b"continue\n", timeout=10)
                check.append_backend_parent_event(parent_log, {"phase": "parent-last"})
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(child_log.read_text().splitlines(), ["child-first", "child-second"])
        self.assertEqual([json.loads(line)["phase"] for line in parent_log.read_text().splitlines()],
                         ["parent-first", "parent-last"])
        self.assertNotIn("child-first", parent_log.read_text())

    def test_runtime_resolution_requires_existing_matching_pin_and_never_downloads(self):
        desktop = self.base / "desktop"
        package = desktop / "node_modules" / "electron"
        (package / "dist").mkdir(parents=True)
        check.write_json(desktop / "package.json", {"devDependencies": {"electron": "44.3.0"}})
        check.write_json(package / "package.json", {"version": "44.3.0"})
        (package / "dist/version").write_text("44.3.0")
        (package / "path.txt").write_text("electron.exe")
        with self.assertRaises(ValueError):
            check.resolve_electron(desktop)
        (package / "dist/electron.exe").write_bytes(b"synthetic binary fixture")
        self.assertEqual(check.resolve_electron(desktop)["version"], "44.3.0")
        (package / "dist/version").write_text("43.0.0")
        with self.assertRaisesRegex(ValueError, "does not match"):
            check.resolve_electron(desktop)


if __name__ == "__main__":
    unittest.main()
