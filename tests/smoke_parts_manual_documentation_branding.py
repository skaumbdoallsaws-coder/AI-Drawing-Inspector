"""Browser proof for branded Documentation text, images, and shapes."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import traceback

from PIL import Image, ImageDraw

from parts_manual_smoke_support import IsolatedPartsManualServer


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".runtime" / "parts_manual_documentation_branding_proof"
OUT.mkdir(parents=True, exist_ok=True)
ASSEMBLY = "tricycle"


def _approve_plan(request, app_url: str) -> None:
    initial = request.get(f"{app_url}/api/parts-manual/{ASSEMBLY}").json()
    proposal = request.get(
        f"{app_url}/api/parts-manual/{ASSEMBLY}/proposal"
    ).json()["proposal"]
    ready = [
        row["candidateId"]
        for row in proposal["candidates"]
        if row["status"] == "ready"
    ]
    response = request.post(
        f"{app_url}/api/parts-manual/{ASSEMBLY}/proposals/"
        f"{proposal['proposalRevision']}/approve",
        data={
            "baseRevision": initial["revision"],
            "sourceRevision": initial["sourceRevision"],
            "candidateIds": ready,
        },
    )
    if not response.ok:
        raise RuntimeError(response.text())


def _logo(path: Path) -> None:
    image = Image.new("RGB", (480, 150), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 479, 149), fill=(16, 43, 58))
    draw.text((30, 48), "ACME TECHNICAL", fill=(230, 57, 70))
    image.save(path, format="PNG")


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    report: dict[str, object] = {
        "checks": {},
        "browserErrors": [],
        "consoleErrors": [],
        "failedResponses": [],
    }

    def record(name: str, ok: bool, detail=None) -> None:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if not ok else ""))

    logo_path = OUT / "acme-logo.png"
    _logo(logo_path)
    server = IsolatedPartsManualServer(ROOT, OUT, ASSEMBLY)
    try:
        server.start()
        report["appUrl"] = server.app_url
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1720, "height": 1080})
            page = context.new_page()
            request = playwright.request.new_context(
                base_url=server.app_url, timeout=180_000
            )
            page.on("pageerror", lambda error: report["browserErrors"].append(str(error)))
            page.on(
                "console",
                lambda message: report["consoleErrors"].append(message.text)
                if message.type == "error"
                else None,
            )

            def failed_response(response) -> None:
                relevant = (
                    "/api/parts-manual/" in response.url
                    or "/api/documentation/" in response.url
                )
                if response.status < 400 or not relevant:
                    return
                report["failedResponses"].append(
                    {"status": response.status, "url": response.url}
                )

            page.on("response", failed_response)
            _approve_plan(request, server.app_url)
            page.goto(
                f"{server.app_url}/?assemblyProfile={ASSEMBLY}",
                wait_until="domcontentloaded",
                timeout=90_000,
            )
            page.wait_for_function(
                """assembly => Boolean(
                    window.__compareDbg?.state.partNumber === assembly
                    && window.__compareDbg.state.assyLiveScene
                    && window.__compareDbg.state.assyOccurrenceMeshMap
                )""",
                arg=ASSEMBLY,
                timeout=90_000,
            )
            page.evaluate("() => window.__compareDbg.openDocumentationWorkflow()")
            page.wait_for_function(
                """() => Boolean(
                    document.querySelector('#documentationWorkspace')
                    || window.__compareDbg.state.partsManualMessage?.tone === 'error'
                )""",
                timeout=120_000,
            )
            if page.locator("#documentationWorkspace").count() == 0:
                detail = page.evaluate(
                    """() => ({
                        activeTab: window.__compareDbg.state.activeTab,
                        trainingType: typeof trainingState === 'undefined'
                            ? null : trainingState.type,
                        contextAvailable: typeof assemblyContextAvailable === 'undefined'
                            ? null : assemblyContextAvailable,
                        assemblyNumber: typeof assemblyContext === 'undefined'
                            ? null : assemblyContext?.assembly_number,
                        message: window.__compareDbg.state.partsManualMessage,
                        initializing: window.__compareDbg.state.partsManualDocumentationInitializing,
                        planStatus: window.__compareDbg.state.partsManualPayload
                            ?.publicationReadiness?.status,
                        documentLoaded: Boolean(
                            window.__compareDbg.state.partsManualDocumentation
                        ),
                        bootstrap: Boolean(
                            document.querySelector('.documentation-workflow-bootstrap')
                        ),
                        resources: performance.getEntriesByType('resource')
                            .filter(value => value.name.includes('/api/parts-manual/'))
                            .map(value => ({
                                name: value.name,
                                duration: Math.round(value.duration),
                                responseEnd: Math.round(value.responseEnd),
                            })),
                        viewportText: document.querySelector('#viewportContent')?.innerText,
                    })"""
                )
                raise RuntimeError(f"Documentation workflow did not mount: {detail}")
            workspace = page.locator("#documentationWorkspace")
            workspace.wait_for(state="visible", timeout=120_000)
            page.evaluate(
                """() => {
                    window.__documentationBaselinePromise =
                        window.__compareDbg.startDocumentationBaseline();
                }"""
            )
            page.wait_for_function(
                """() => {
                    const value = window.__compareDbg.documentationGenerationSnapshot();
                    return value.generationState === 'complete'
                        && !value.working
                        && value.visiblePageCount === value.totalPageCount;
                }""",
                timeout=180_000,
            )
            page.evaluate("() => window.__documentationBaselinePromise")
            cover = workspace.locator(
                '.documentation-page-item[title="Tricycle Illustrated Parts Manual"]'
            )
            cover.click()
            page.wait_for_function(
                """() => !document.querySelector('#documentationWorkspace.busy')
                    && document.querySelector(
                        '#documentationPageList .documentation-page-item.active'
                    )?.textContent?.includes('Tricycle Illustrated Parts Manual')""",
                timeout=120_000,
            )

            page.locator("#documentationInsertTextRibbon").click()
            page.wait_for_function(
                """() => Object.keys(
                    window.__compareDbg.state.partsManualDocumentation.document.pages.find(
                        value => value.pageId === window.__compareDbg.state.partsManualDocumentationPageId
                    )?.documentationObjects || {}
                ).length === 1""",
                timeout=30_000,
            )
            text_object = page.locator("#documentationObjectLayer .documentation-object.text")
            text_object.dblclick()
            text_object.press("Control+A")
            text_object.type("CUSTOM SERVICE NOTE")
            text_object.press("Enter")
            page.wait_for_function(
                """() => Object.values(
                    window.__compareDbg.state.partsManualDocumentation.document.pages.find(
                        value => value.pageId === window.__compareDbg.state.partsManualDocumentationPageId
                    )?.documentationObjects || {}
                ).some(value => value.content === 'CUSTOM SERVICE NOTE')""",
                timeout=30_000,
            )
            record(
                "direct_text_edit_is_persistent_and_semantic",
                text_object.text_content() == "CUSTOM SERVICE NOTE",
            )

            page.locator("#documentationShapesMenuRibbon").click()
            page.get_by_role("button", name="Rectangle", exact=True).click()
            page.wait_for_function(
                """() => Object.values(
                    window.__compareDbg.state.partsManualDocumentation.document.pages.find(
                        value => value.pageId === window.__compareDbg.state.partsManualDocumentationPageId
                    )?.documentationObjects || {}
                ).some(value => value.type === 'shape')""",
                timeout=30_000,
            )
            record(
                "technical_shape_is_a_persistent_document_object",
                page.locator("#documentationObjectLayer .documentation-object.shape").count() == 1,
            )

            with page.expect_file_chooser() as chooser_info:
                page.locator("#documentationInsertImageRibbon").click()
            chooser_info.value.set_files(str(logo_path))
            page.wait_for_function(
                """() => Object.values(
                    window.__compareDbg.state.partsManualDocumentation.document.pages.find(
                        value => value.pageId === window.__compareDbg.state.partsManualDocumentationPageId
                    )?.documentationObjects || {}
                ).some(value => value.type === 'image' && value.asset?.assetId)""",
                timeout=60_000,
            )
            image_object = page.locator(
                "#documentationObjectLayer .documentation-object.image img"
            )
            record(
                "managed_image_asset_renders_on_the_page",
                image_object.count() == 1
                and image_object.evaluate("image => image.complete && image.naturalWidth > 0"),
            )

            with page.expect_file_chooser() as chooser_info:
                page.locator("#documentationInsertLogoRibbon").click()
            chooser_info.value.set_files(str(logo_path))
            page.wait_for_function(
                """() => Boolean(
                    window.__compareDbg.state.partsManualDocumentation
                        ?.document?.theme?.logo?.assetId
                )""",
                timeout=60_000,
            )
            logo_proof = page.evaluate(
                """() => ({
                    logo: window.__compareDbg.state.partsManualDocumentation
                        ?.document?.theme?.logo || null,
                    wordmark: document.querySelector(
                        '#documentationPublicationSurface .documentation-page-wordmark'
                    )?.innerHTML || null,
                    imageCount: document.querySelectorAll(
                        '#documentationPublicationSurface .documentation-page-wordmark img'
                    ).length,
                })"""
            )
            record(
                "managed_company_logo_is_bound_to_the_page_master_theme",
                logo_proof["imageCount"] == 1,
                logo_proof,
            )

            page.locator("#documentationThemeRibbon").click()
            page.locator("#documentationThemecompanyName").fill("Acme Manufacturing")
            page.locator("#documentationThemeprimary").evaluate(
                "input => { input.value = '#102B3A'; input.dispatchEvent(new Event('input', {bubbles:true})); }"
            )
            page.locator("#documentationThemeaccent").evaluate(
                "input => { input.value = '#E63946'; input.dispatchEvent(new Event('input', {bubbles:true})); }"
            )
            page.get_by_role("button", name="Apply Theme", exact=True).click()
            page.wait_for_function(
                """() => window.__compareDbg.state.partsManualDocumentation
                    ?.document?.theme?.companyName === 'Acme Manufacturing'""",
                timeout=30_000,
            )
            theme_proof = page.evaluate(
                """() => {
                    const surface = document.querySelector('#documentationPublicationSurface');
                    const style = getComputedStyle(surface);
                    return {
                        company: window.__compareDbg.state.partsManualDocumentation.document
                            .theme.companyName,
                        primary: style.getPropertyValue('--doc-primary').trim().toUpperCase(),
                        accent: style.getPropertyValue('--doc-accent').trim().toUpperCase(),
                        objectCount: document.querySelectorAll(
                            '#documentationObjectLayer .documentation-object'
                        ).length,
                    };
                }"""
            )
            record(
                "company_theme_updates_live_page_tokens",
                theme_proof == {
                    "company": "Acme Manufacturing",
                    "primary": "#102B3A",
                    "accent": "#E63946",
                    "objectCount": 3,
                },
                theme_proof,
            )

            page.locator("#documentationUndoRibbon").click()
            page.wait_for_function(
                """() => window.__compareDbg.state.partsManualDocumentation
                    ?.document?.theme?.companyName === 'InspectorPro'""",
                timeout=30_000,
            )
            page.locator("#documentationRedoRibbon").click()
            page.wait_for_function(
                """() => window.__compareDbg.state.partsManualDocumentation
                    ?.document?.theme?.companyName === 'Acme Manufacturing'""",
                timeout=30_000,
            )
            record("theme_change_is_undoable_and_redoable", True)

            page.locator("#documentationThemeRibbon").click()
            page.get_by_role("button", name="Save Company Template", exact=True).click()
            page.wait_for_function(
                """() => !document.querySelector('.documentation-theme-dialog')""",
                timeout=30_000,
            )
            templates = request.get(
                f"{server.app_url}/api/documentation/templates"
            ).json().get("templates", [])
            record(
                "company_theme_and_page_masters_save_as_a_reusable_template",
                any(
                    row.get("name") == "InspectorPro Technical"
                    and row.get("theme", {}).get("companyName") == "Acme Manufacturing"
                    and row.get("theme", {}).get("logo", {}).get("assetId")
                    and row.get("pageMasters")
                    for row in templates
                ),
                templates,
            )

            workspace.screenshot(
                path=str(OUT / "documentation_branding_workspace.png"),
                timeout=60_000,
            )
            scene = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene"
            ).json()
            cover_page = next(
                row for row in scene["document"]["pages"] if row["pageType"] == "cover"
            )
            values = list(cover_page.get("documentationObjects", {}).values())
            record(
                "scene_reload_preserves_theme_and_all_object_types",
                scene["scene"]["schemaVersion"] == 2
                and scene["document"]["theme"]["companyName"] == "Acme Manufacturing"
                and scene["document"]["theme"]["logo"]["assetId"]
                and {row["type"] for row in values} == {"text", "shape", "image"},
            )
            record("no_browser_errors", not report["browserErrors"], report["browserErrors"])
            documentation_console_errors = [
                value for value in report["consoleErrors"]
                if "[Documentation]" in value
            ]
            record(
                "no_documentation_console_errors",
                not documentation_console_errors,
                documentation_console_errors,
            )
            record(
                "no_failed_documentation_api_responses",
                not report["failedResponses"],
                report["failedResponses"],
            )
            request.dispose()
            context.close()
            browser.close()
    except Exception as error:
        report["fatalError"] = str(error)
        report["traceback"] = traceback.format_exc()
        try:
            page.screenshot(
                path=str(OUT / "documentation_branding_failure.png"),
                full_page=True,
                timeout=30_000,
            )
        except Exception:
            pass
        print(f"FATAL {error}", file=sys.stderr)
        print(report["traceback"], file=sys.stderr)
    finally:
        server.stop()

    report["passed"] = all(
        value.get("ok") for value in report["checks"].values()
    ) and not report.get("fatalError")
    (OUT / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
