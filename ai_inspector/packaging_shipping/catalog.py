"""Small, cited starting catalog; supplier properties are not certifications."""
from .models import Carton, MaterialDensity

PMMA_SOURCE = "https://www.plexiglas.de/files/plexiglas-content/pdf/technische-informationen/211-1-EN-PLEXIGLAS-GS-XT.pdf"
FOAM_SOURCE = "https://dam.sealedair.com/asset/8abcf0fc-1b7a-47e1-bc2f-4a190360bfb4/PROT_Foam_Ethafoam_Brochure_EN_0924-pdf.pdf"
CHECKED = "2026-11-05"  # Material sources.
CARTONS_CHECKED = "2026-11-06"  # Every carton page below was read on this date.
INCH_M, POUND_KG = .0254, .45359237
ULINE_200 = "https://www.uline.com/Product/Detail/{sku}/Corrugated-Boxes-200-Test/{slug}"
# ULINE 200 lb test kraft cartons as each product page states them: inside L x W x H, "Outside: ... (+/- 1/8")",
# "Unit Weight: ... lbs.", the bundle quantity, "200 LB. TEST" and "Meets ASTM D5118". Smallest inner volume first.
# (SKU, inside L/W/H in, outside L/W/H in, unit weight lb, bundle quantity, page slug)
ULINE_CARTONS = (
    ("S-4080", (8, 6, 4), (8.375, 6.375, 4.625), .26, 25, "8-x-6-x-4-Corrugated-Boxes"),
    ("S-4103", (10, 8, 6), (10.375, 8.375, 6.625), .44, 25, "10-x-8-x-6-Corrugated-Boxes"),
    ("S-4120", (12, 10, 8), (12.375, 10.375, 8.625), .67, 25, "12-x-10-x-8-Corrugated-Boxes"),
    ("S-4187", (18, 12, 6), (18.375, 12.375, 6.625), .92, 25, "18-x-12-x-6-Corrugated-Boxes"),
    ("S-4235", (16, 12, 8), (16.375, 12.375, 8.625), 1.01, 25, "16-x-12-x-8-Corrugated-Boxes"),
    ("S-4415", (24, 12, 6), (24.375, 12.375, 6.625), 1.15, 20, "24-x-12-x-6-Corrugated-Boxes"),
    ("S-4196", (20, 14, 10), (20.375, 14.375, 10.625), 1.35, 20, "20-x-14-x-10-Corrugated-Boxes"),
    ("S-15039", (22, 18, 8), (22.375, 18.375, 8.625), 1.82, 20, "22-x-18-x-8-Corrugated-Boxes"),
    ("S-4219", (24, 18, 12), (24.375, 18.375, 12.625), 2.06, 10, "24-x-18-x-12-Corrugated-Boxes"),
)


def uline_carton(sku, inside, outside, pounds, bundle, slug):
    source = ULINE_200.format(sku=sku, slug=slug)
    (length, width, height), (out_length, out_width, out_height) = inside, outside
    # Published L/W/H becomes X/Y/Z = L/H/W, with no implicit product scaling.
    carton = Carton(name=f"ULINE {sku} {length} x {width} x {height} in",
        inner_m=(length * INCH_M, height * INCH_M, width * INCH_M),
        outer_m=(out_length * INCH_M, out_height * INCH_M, out_width * INCH_M), tare_kg=pounds * POUND_KG,
        tare_evidence=f"Supplier unit weight {pounds:g} lb; outside tolerance +/- 1/8 in. Checked {CARTONS_CHECKED}. {source}",
        supplier="ULINE", sku=sku, source_url=source)
    return {"id": "uline-" + sku.lower(), "carton": carton.model_dump(mode="json"),
            "grade": "200 lb test; meets ASTM D5118 (supplier statements)", "checked_at": CARTONS_CHECKED,
            "purchase_multiple": bundle, "outer_tolerance_m": .125 * INCH_M}  # ULINE states it for outside dimensions only.


def catalog():
    materials = [{"id": "pmma-plexiglas-gs-xt", "use": "product", "material": MaterialDensity(
        name="PMMA - PLEXIGLAS GS/XT typical", density_kg_m3=1190.,
        evidence=f"PLEXIGLAS 211-1, 04/25, p4, ISO 1183; typical density, actual grade unconfirmed. {PMMA_SOURCE}"
    ).model_dump(mode="json")}]
    for grade, density in ((150, 25.), (180, 28.), (220, 37.), (400, 57.), (700, 105.), (900, 146.)):
        materials.append({"id": f"ethafoam-{grade}-0924", "use": "insert", "material": MaterialDensity(
            name=f"Ethafoam {grade} - typical", density_kg_m3=density,
            evidence=f"Sealed Air EN 09/24, p3, ASTM D3575-08 / ISO 845:2006; typical, not specification limits. {FOAM_SOURCE}"
        ).model_dump(mode="json")})
    return {"checked_at": CHECKED, "materials": materials, "cartons": [uline_carton(*row) for row in ULINE_CARTONS],
        "notice": "Confirm actual grade, manufactured dimensions, tare and payload. Prices are not live. Payload capacity is not "
                  "recorded: 200 lb test is a burst-strength grade, not a carton load limit. No cushioning or transport "
                  "certification is implied."}
