"""Regressions from the independent review of MI0a."""
import asyncio
import threading

import pytest

from tests.model_import_test_support import module, textured_box

licence = module("licence")
validation = module("validation")
runner = module("runner")
ModelImportError = module("errors").ModelImportError


@pytest.mark.parametrize("text", [
    "License: CC BY 4.0\nLicense URL: https://creativecommons.org/licenses/by-nc-nd/4.0/",
    "License: CC BY-NC-ND 4.0\nLicense: CC BY 4.0",
    "License: CC BY 4.0 (https://creativecommons.org/licenses/by-nc-nd/4.0/)",
])
def test_conflicting_license_assertions_are_never_permissive(text):
    result = licence.parse_licence([("license.txt", text)], {})
    assert result["class"] == "unknown"
    evidence = " ".join(v for c in result["conflicts"] for v in c["values"])
    assert "CC BY" in evidence
    assert "by-nc-nd" in evidence.lower()


@pytest.mark.parametrize("limit", [80, 200, 300, 600, 2048])
def test_clean_text_is_idempotent_at_whitespace_boundary(limit):
    value = "a" * (limit - 1) + " b"
    cleaned = validation.clean_text(value, limit)
    assert cleaned == "a" * (limit - 1)
    assert validation.clean_text(cleaned, limit) == cleaned


def test_summary_truncation_remains_valid():
    model = module("reader").read_model(textured_box().bytes(), "a" * 79 + " b")
    for field in ("name", "node", "mesh"):
        setattr(model.parts[0], field, validation.clean_text("a" * 79 + " b", 80))
    model.materials[0]["name"] = validation.clean_text("a" * 79 + " b", 80)
    model.generator = validation.clean_text("a" * 299 + " b", 300)
    model.licence = licence.parse_licence([("license.txt", "Title: " + "a" * 299 + " b")], {})
    model.licence["excerpt"] = "a" * 599 + " b"
    model.licence["conflicts"] = [{"field": "title", "values": ["a" * 79 + " b", "other"]}]
    result = module("summary").build_summary(model)
    assert module("protocol").validate_summary(result) == result
    assert result["licence"]["excerpt"] == "a" * 599
    assert result["licence"]["conflicts"][0]["values"][0] == "a" * 79


@pytest.mark.parametrize("preexisting", [False, True])
def test_late_async_cancel_cleans_only_owned_outputs(tmp_path, monkeypatch, preexisting):
    job = tmp_path / "job"
    job.mkdir()
    output = job / "summary.json"
    if preexisting:
        output.write_bytes(b"original")
    finished, release = threading.Event(), threading.Event()

    def fake_inspect(*args, _owned=None, **kwargs):
        if not preexisting:
            _owned.set()
            output.write_bytes(b"completed")
        finished.set()
        release.wait(3)
        if preexisting:
            raise ModelImportError("model_worker_failed")
        return {}

    monkeypatch.setattr(runner, "run_inspect", fake_inspect)

    async def exercise():
        pending = asyncio.create_task(runner.run_inspect_async(job, tmp_path))
        while not finished.is_set():
            await asyncio.sleep(0.001)
        # Result has been produced, but cancellation wins its delivery.
        pending.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending

    asyncio.run(exercise())
    assert output.read_bytes() == b"original" if preexisting else not output.exists()


def test_license_evidence_is_classified_before_display_truncation():
    value = "License: CC BY 4.0 " + "x" * 350 + " (https://creativecommons.org/licenses/by-nc-nd/4.0/)"
    result = licence.parse_licence([("license.txt", value)], {})
    assert result["class"] == "unknown"
    assert all(len(v) <= 300 for c in result["conflicts"] for v in c["values"])
    assert "by-nc-nd" in result["licenseUrl"]


def test_repeated_copyright_labels_and_distinct_unknown_licenses_conflict():
    result = licence.parse_licence([], {"copyright": "License: CC BY 4.0\nLicense: CC BY-NC-ND 4.0"})
    assert result["class"] == "unknown"
    result = licence.parse_licence([("license.txt", "License: MIT\nLicense: BSD")], {})
    assert result["class"] == "unknown" and result["conflicts"]


def test_distinct_license_versions_are_not_silently_overwritten():
    result = licence.parse_licence([("license.txt", "License: CC BY 3.0\nLicense: CC BY 4.0")], {})
    assert result["class"] == "unknown"
    equivalent = licence.parse_licence([("license.txt", "License: CC-BY-4.0\nLicense: CC BY 4.0\n"
        "License URL: https://creativecommons.org/licenses/by/4.0/")], {})
    assert equivalent["class"] == "cc-by" and equivalent["conflicts"] == []
