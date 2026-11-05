"""Version-bound engineering review report; no certification claims."""
from io import BytesIO
from xml.sax.saxutils import escape


def render_report(document, quotes=()):
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.graphics.shapes import Drawing, Rect, String
    from .geometry import oriented
    output = BytesIO()
    styles = getSampleStyleSheet()
    story = []

    def para(text, style="BodyText"):
        story.append(Paragraph(escape(str(text)), styles[style]))
        space = Spacer(1, 6)
        space.keepWithNext = style.startswith("Heading") or style == "Title"
        story.append(space)

    design, assessment = document["design"], document["assessment"]
    para("InspectorPro | Packaging Review", "Title")
    para(design["name"], "Heading1")
    para(f"Document {document['id']} | Revision {document['revision']} | {document['updated_at']}")
    para("DRAFT FOR ENGINEERING REVIEW. Bounding-envelope checks do not certify cushioning, packing access, stacking strength or transport performance.")
    p = design["product"]
    if p:
        para("Product", "Heading2")
        para(f"{p['name']} | Quantity: {design['quantity']} | Dimensions (mm): " + " x ".join(f"{d * 1000:.2f}" for d in p["dimensions_m"]))
        para(f"Mass per item: {p['mass_kg']} kg | Basis: {p['mass_basis']} | Evidence: {p['mass_evidence'] or 'Missing'}")
        para(f"Source: {p['source_id'] or 'Manual geometry'} | Source revision: {p['source_revision'] or 'Not available'}")
    for box, totals in zip(design["packages"], assessment["packages"]):
        para(f"Package {box['id']}: {box['carton']['name']}", "Heading2")
        para("External dimensions (mm): " + " x ".join(f"{d * 1000:.2f}" for d in box["carton"]["outer_m"]))
        para(f"Gross mass: {totals['gross_kg']} kg | Carton: {totals['carton_kg']} kg | Inserts: {totals['insert_kg']:.4f} kg | Allowance: {totals['allowance_kg']} kg")
        para(f"Carton mass source: {box['carton']['tare_evidence'] or 'Missing'}")
        para(f"Allowance source: {box['allowance_evidence'] or 'Missing'}")
        if p:
            inner = box["carton"]["inner_m"]
            drawing = Drawing(440, 200)
            scale = min(400 / inner[0], 160 / inner[2])
            drawing.add(Rect(15, 20, inner[0] * scale, inner[2] * scale, fillColor=None, strokeColor=colors.HexColor("#40576a")))
            for placement in box["placements"]:
                size = oriented(p["dimensions_m"], placement["orientation"])
                x, y, z = placement["position_m"]
                drawing.add(Rect(15 + x * scale, 20 + z * scale, size[0] * scale, size[2] * scale,
                                 fillColor=None, strokeColor=colors.HexColor("#187a7a"), strokeWidth=1))
            drawing.add(String(15, 5, "Top projection of product envelopes (X/Z). Layers can overlap in projection.", fontSize=8))
            story.append(drawing)
        rows = [["Component", "Qty", "Material / mass basis"]]
        rows.append([p["name"] if p else "Product", str(len(box["placements"])), p["mass_basis"] if p else "Missing"])
        rows.append([box["carton"]["name"], "1", "Carton tare"])
        for insert in box["inserts"]:
            rows.append([insert["name"], "1", f"{insert['material']}, {insert['density_kg_m3']} kg/m3"])
        table = Table([[Paragraph(escape(x), styles["BodyText"]) for x in row] for row in rows], colWidths=[2.7 * inch, .5 * inch, 3 * inch], repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7edf2")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), .5, colors.gray)]))
        story.append(table)
        for insert in box["inserts"]:
            para(f"Insert {insert['name']}: dimensions (mm) "
                 + " x ".join(f"{x * 1000:.2f}" for x in insert["dimensions_m"])
                 + "; minimum-corner position (mm) " + ", ".join(f"{x * 1000:.2f}" for x in insert["position_m"]))
            para(f"Density source: {insert['material_evidence']}")
        para("Placement schedule", "Heading3")
        for placement in box["placements"]:
            para(f"{placement['id']}: minimum-corner position (mm) " + ", ".join(f"{x * 1000:.2f}" for x in placement["position_m"]) + f"; orthogonal orientation {placement['orientation']}.")
        para("Packing sequence must be reviewed before release. This report records positions, not a verified insertion/removal sequence.")
    para("Validation findings", "Heading2")
    for finding in assessment["findings"]:
        para(f"{finding['severity'].upper()}: {finding['message']} {' / '.join(finding['entity_ids'])}")
    para("Carrier estimates", "Heading2")
    current_quotes = [q for q in quotes if q["revision"] == document["revision"]]
    if not current_quotes:
        para("No quotes are saved for this revision. No shipping price has been inferred.")
    for quote in current_quotes[:1]:
        para(f"{quote['provider']} | {quote['quoted_at']} | {quote['notice']}")
        for result in quote["results"]:
            dest = result["destination"]
            para(f"Destination: {dest['city']}, {dest['state']} {dest['zip']}")
            for rate in result["totals"]:
                para(f"{rate['mode'].upper()} | {rate['carrier']} {rate['service']} | Account {rate.get('account_id') or 'not supplied'}: {rate['amount']} {rate['currency']} | {rate['basis']}")
    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#53616b"))
        canvas.drawString(.65 * inch, .35 * inch, "InspectorPro | Draft packaging review")
        canvas.drawRightString(7.85 * inch, .35 * inch, f"Page {doc.page}")

    SimpleDocTemplate(output, pagesize=(8.5 * inch, 11 * inch), leftMargin=.65 * inch, rightMargin=.65 * inch,
                      topMargin=.6 * inch, bottomMargin=.6 * inch, title="InspectorPro Packaging Review").build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
