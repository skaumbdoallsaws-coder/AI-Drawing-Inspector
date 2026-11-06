"""Small, cited starting catalog; supplier properties are not certifications."""
from .models import Carton, MaterialDensity

PMMA_SOURCE = "https://www.plexiglas.de/files/plexiglas-content/pdf/technische-informationen/211-1-EN-PLEXIGLAS-GS-XT.pdf"
FOAM_SOURCE = "https://dam.sealedair.com/asset/8abcf0fc-1b7a-47e1-bc2f-4a190360bfb4/PROT_Foam_Ethafoam_Brochure_EN_0924-pdf.pdf"
CARTON_SOURCE = "https://www.uline.com/Product/Detail/S-15039/Corrugated-Boxes-200-Test/22-x-18-x-8-Corrugated-Boxes"
CHECKED = "2026-11-05"


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
    # Published L/W/H becomes X/Y/Z = L/H/W, with no implicit product scaling.
    carton = Carton(name="ULINE S-15039 22 x 18 x 8 in", inner_m=(22*.0254, 8*.0254, 18*.0254),
        outer_m=(22.375*.0254, 8.625*.0254, 18.375*.0254), tare_kg=1.82*.45359237,
        tare_evidence=f"Supplier unit weight 1.82 lb; outside tolerance +/- 1/8 in. Checked {CHECKED}. {CARTON_SOURCE}",
        supplier="ULINE", sku="S-15039", source_url=CARTON_SOURCE)
    return {"checked_at": CHECKED, "materials": materials,
        "cartons": [{"id": "uline-s-15039", "carton": carton.model_dump(mode="json"),
                     "purchase_multiple": 20, "dimension_tolerance_m": .125*.0254}],
        "notice": "Confirm actual grade, manufactured dimensions, tare and payload. Prices are not live. No cushioning or transport certification is implied."}
