"""Opt-in real STEP/API/viewport acceptance; originals are read-only."""
from pathlib import Path
import argparse
import hashlib
import json
from uuid import uuid4

import httpx
from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright, expect


def verify(url, source, output):
    output.mkdir(parents=True, exist_ok=False)
    payload = source.read_bytes()
    before = hashlib.sha256(payload).hexdigest()
    headers = {"X-InspectorPro-Request": "packaging"}
    def checked(response):
        response.raise_for_status()
        return response.json()
    with httpx.Client(base_url=url, headers=headers, timeout=120) as client:
        status = checked(client.get("/api/packaging/status"))
        assert "step_import" in status["capabilities"]
        imported = checked(client.post("/api/packaging/sources/step", params={"name": "TEST straight rack and pusher"}, content=payload))
        assert imported["source_revision"] == before
        entries = checked(client.get("/api/packaging/catalog"))
        material = next(m["material"] for m in entries["materials"] if m["id"] == "pmma-plexiglas-gs-xt")
        foam = next(m["material"] for m in entries["materials"] if m["id"] == "ethafoam-220-0924")
        product = checked(client.post(f"/api/packaging/sources/{imported['id']}/mass-estimate", json={
            "source_revision": before, "material": material,
            "exclusions": "Density estimate for the user-confirmed PMMA solids only. Magnets and adhesive excluded; verify finished-product weight."}))["product"]
        product["appearance"] = {"color": "#17191C", "roughness": .3, "metalness": 0., "opacity": 1.}
        x, y, z = product["dimensions_m"]
        pocket = (x+.002, y+.01, z+.002)
        inner = (x+.052, y+.05, 4*pocket[2]+.03+.04)
        name = "TEST real STEP four-pair pockets " + uuid4().hex[:8]
        design = {"name": name, "product": product, "quantity": 4,
            "constraints": {"clearance_m": .02, "gap_m": .01, "allowed_orientations": [0], "contents": "unconfirmed"},
            "packages": [{"id": "box", "carton": {"name": "Custom concept - weights unconfirmed", "inner_m": inner,
                "outer_m": [d+.01 for d in inner]},
                "placements": [{"id": f"pair_{n}", "position_m": [.026, .02, .021+n*(pocket[2]+.01)], "orientation": 0} for n in range(4)],
                "inserts": [{"id": "foam", "name": "Four top-open pockets", "dimensions_m": [x+.012, y+.03, 4*pocket[2]+.03+.02],
                    "position_m": [.02, 0., .01], "material": foam["name"], "density_kg_m3": foam["density_kg_m3"], "material_evidence": foam["evidence"],
                    "pockets": [{"id": f"pocket_{n}", "position_m": [.005, .02, .01+n*(pocket[2]+.01)], "dimensions_m": pocket} for n in range(4)],
                    "appearance": {"color": "#35393E", "roughness": .9, "metalness": 0., "opacity": 1.}}],
                "graphics": [{"id": "label", "face": "z+", "kind": "text", "text": "FOUR RACKS + FOUR PUSHERS", "color": "#17191C"}]}]}
        saved = checked(client.post("/api/packaging/documents", json=design))
        findings = saved["assessment"]["findings"]
        assert not any(f["code"] in {"insert_overlap", "envelope_overlap", "outside_usable_carton", "support_not_verified"} or f["code"].startswith("pocket_") for f in findings), findings
        assert saved["assessment"]["rate_ready"] is False
        assert saved["assessment"]["packages"][0]["insert_kg"] > 0
        assert saved["assessment"]["packages"][0]["product_kg"] == product["mass_kg"]*4
        path = f"/api/packaging/documents/{saved['id']}"
        alternate = checked(client.post(path+"/alternatives", json={"expected_revision": 0, "request_id": "save-four-pocket", "name": "Four-pocket PMMA concept"}))
        assert alternate["design"] == saved["design"]
        report = client.get(path+"/report.pdf", params={"revision": 0})
        report.raise_for_status()
        (output/"review.pdf").write_bytes(report.content)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url+"/packaging", wait_until="networkidle")
        page.get_by_role("button", name="Open", exact=True).click()
        page.locator("#document-list > div").filter(has_text=name).get_by_role("button", name="Open", exact=True).click()
        expect(page.locator("#document-name")).to_have_value(name)
        expect(page.locator("#scene-message")).to_have_text("", timeout=60000)
        page.get_by_role("button", name="Fit view", exact=True).click()
        for view in ("Top", "Front", "Orbit"):
            page.get_by_role("button", name=view, exact=True).click()
            page.wait_for_timeout(300)
            page.screenshot(path=str(output/(view.lower()+".png")))
        page.locator("#viewport canvas").screenshot(path=str(output/"canvas.png"))
        deviations = ImageStat.Stat(Image.open(output/"canvas.png").convert("RGB")).stddev
        assert max(deviations) > 8, deviations
        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("button", name="Fit view", exact=True).click()
        page.screenshot(path=str(output/"mobile.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        browser.close()
    assert not errors, errors
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    result = {"source_unchanged": True, "source_sha256": before, "source": imported, "document_id": saved["id"],
        "quantity": 4, "product_kg": product["mass_kg"]*4, "mass_basis": "estimate", "assessment": saved["assessment"],
        "page_errors": errors, "canvas_stddev": deviations, "live_rates_requested": False}
    (output/"result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"document_id": saved["id"], "source_unchanged": True, "solid_count": imported["solid_count"],
                      "product_kg": result["product_kg"], "page_errors": errors}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8181")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / ".runtime"
    if not args.output.resolve().is_relative_to(root):
        raise ValueError("Evidence must remain in the isolated worktree .runtime directory")
    verify(args.url.rstrip("/"), args.source, args.output)
