"""Version-bound engineering review report; no certification claims."""
from io import BytesIO
from xml.sax.saxutils import escape


def render_report(document, quotes=()):
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
    from reportlab.graphics.shapes import Drawing, Rect, String
    from .components import insert_geometry, pocket_volume
    from .geometry import oriented
    from .models import Insert
    output = BytesIO()
    styles = getSampleStyleSheet()
    styles["BodyText"].fontSize = 9.5
    styles["BodyText"].leading = 13
    styles["BodyText"].spaceAfter = 6
    styles["BodyText"].splitLongWords = True
    story = []

    def para(text, style="BodyText", *, keep_with_next=False):
        paragraph = Paragraph(escape(str(text)), styles[style])
        if keep_with_next:
            paragraph.keepWithNext = True
        story.append(paragraph)

    def number(value, precision=None):
        if value is None:
            return "Unavailable"
        return f"{value:.{precision}f}" if precision is not None else f"{value:.8g}"

    def millimetres(values):
        return " x ".join(f"{value * 1000:.2f}" for value in values)

    def position(values):
        return ", ".join(f"{value * 1000:.2f}" for value in values)

    def table(rows):
        result = Table([[Paragraph(escape(str(cell)), styles["BodyText"]) for cell in row] for row in rows],
                       colWidths=[2.7 * inch, .5 * inch, 3.8 * inch], repeatRows=1, hAlign="LEFT")
        result.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7edf2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LINEBELOW", (0, 0), (-1, 0), .5, colors.gray),
        ]))
        story.append(result)

    design, assessment = document["design"], document["assessment"]
    para("InspectorPro | Packaging Review", "Title")
    para(design["name"], "Heading1")
    para(f"Document {document['id']} | Revision {document['revision']} | {document['updated_at']}")
    para("DRAFT FOR ENGINEERING REVIEW. Bounding-envelope checks do not certify cushioning, packing access, stacking strength or transport performance. "
         "Detected geometric contact is not verification of load support or cushioning. Material properties, support, packing sequence and transport testing require engineering review before release.")
    para(f"Saved assessment: {assessment['status']} | Validation level: {assessment['validation_level']}")
    p = design["product"]
    if p:
        para("Product", "Heading2")
        para(f"{p['name']} | Quantity: {design['quantity']} | Dimensions X/Y/Z (mm): {millimetres(p['dimensions_m'])}")
        para(f"Mass per item: {number(p['mass_kg'])} kg | Basis: {p['mass_basis']} | Evidence: {p['mass_evidence'] or 'Missing'}")
        para(f"Source: {p['source_id'] or 'Manual geometry'} | Source revision: {p['source_revision'] or 'Not available'}")
        calculation = p.get("mass_calculation")
        if calculation:
            material = calculation["material"]
            para("Density-based mass calculation (estimate)", "Heading3")
            para(f"Recorded solid volume: {number(calculation['volume_m3'])} m3 | Material: {material['name']} | "
                 f"Physical density: {number(material['density_kg_m3'])} kg/m3. Mass = recorded volume x density.")
            para(f"Density evidence: {material['evidence']}")
            para(f"Calculation exclusions: {calculation['exclusions'] or 'None recorded; review required'}")
            para("This is a documented estimate, not a measured item mass. The source revision and exclusions remain part of its basis.")
    saved_totals = {entry["package_id"]: entry for entry in assessment["packages"]}
    for box in design["packages"]:
        totals = saved_totals.get(box["id"], {})
        carton = box["carton"]
        para(f"Package {box['id']}: {box['carton']['name']}", "Heading2")
        para(f"External dimensions X/Y/Z (mm): {millimetres(carton['outer_m'])}")
        para(f"Internal dimensions X/Y/Z (mm): {millimetres(carton['inner_m'])}")
        para(f"Gross mass: {number(totals.get('gross_kg'))} kg | Products: {number(totals.get('product_kg'))} kg | "
             f"Carton: {number(totals.get('carton_kg'))} kg | Inserts: {number(totals.get('insert_kg'), 4)} kg | "
             f"Allowance: {number(totals.get('allowance_kg'))} kg")
        if totals.get("insert_kg") is None:
            para("Insert mass is unavailable. Resolve invalid cutout geometry or missing assessment evidence before using a gross shipping mass.")
        para(f"Carton mass source: {carton['tare_evidence'] or 'Missing'}")
        para(f"Allowance source: {box['allowance_evidence'] or 'Missing'}")
        para(f"Catalog supplier: {carton.get('supplier') or 'Not recorded'} | SKU: {carton.get('sku') or 'Not recorded'}")
        para(f"Catalog source / evidence: {carton.get('source_url') or 'Not recorded'}")
        blank = carton.get("board_blank")
        if blank:
            para(f"Full board blank (mm): {millimetres(blank['dimensions_m'])} | Quantity: {blank['quantity']} | "
                 f"Basis weight: {number(blank['mass_per_area_kg_m2'])} kg/m2. Estimated tare includes the recorded blank, flaps and overlaps.")
            para(f"Board blank evidence: {blank['evidence']}")
        if p:
            inner = carton["inner_m"]
            drawing = Drawing(440, 200)
            scale = min(400 / inner[0], 160 / inner[2])
            drawing.add(Rect(15, 20, inner[0] * scale, inner[2] * scale, fillColor=None, strokeColor=colors.HexColor("#40576a")))
            omitted = 0
            for placement in box["placements"]:
                size = oriented(p["dimensions_m"], placement["orientation"])
                x, _, z = placement["position_m"]
                if x < 0 or z < 0 or x + size[0] > inner[0] + 1e-6 or z + size[2] > inner[2] + 1e-6:
                    omitted += 1
                    continue
                drawing.add(Rect(15 + x * scale, 20 + z * scale, size[0] * scale, size[2] * scale,
                                 fillColor=None, strokeColor=colors.HexColor("#187a7a"), strokeWidth=1))
            drawing.add(String(15, 5, "Top projection of product envelopes (X/Z). Layers can overlap in projection.", fontSize=8))
            story.append(drawing)
            if omitted:
                para(f"{omitted} out-of-bounds product envelope(s) omitted from the projection; see the placement schedule and validation findings.")
        rows = [["Component", "Qty", "Material / mass basis"]]
        rows.append([p["name"] if p else "Product", str(len(box["placements"])), p["mass_basis"] if p else "Missing"])
        rows.append([box["carton"]["name"], "1", "Carton tare"])
        for insert in box["inserts"]:
            rows.append([insert["name"], "1", f"{insert['material']}, {insert['density_kg_m3']} kg/m3"])
        table(rows)
        for insert in box["inserts"]:
            component = Insert.model_validate(insert)
            shape = insert_geometry(component)
            para(f"Insert {insert['id']}: {insert['name']}", "Heading3")
            para(f"Dimensions X/Y/Z (mm): {millimetres(insert['dimensions_m'])}; carton-local minimum-corner position (mm): {position(insert['position_m'])}")
            para(f"Material: {insert['material']} | Physical density: {number(insert['density_kg_m3'])} kg/m3")
            para(f"Density source: {insert['material_evidence']}")
            para(f"Gross block volume: {number(shape['gross_volume_m3'])} m3 | Nominal pocket volume: {number(shape['removed_volume_m3'])} m3 | "
                 f"Net material volume: {number(shape['net_volume_m3'])} m3")
            mass = shape["net_volume_m3"] * component.density_kg_m3 if shape["valid"] else None
            para(f"Insert mass from net volume x density: {number(mass, 4)} kg | Geometry basis: {shape['basis']}")
            para(f"Required side wall / web: {component.minimum_wall_m * 1000:.2f} mm | Required remaining floor: {component.minimum_floor_m * 1000:.2f} mm")
            if not shape["valid"]:
                para("INVALID CUTOUT GEOMETRY. Nominal pocket volumes are not accepted subtraction volumes; net material volume and insert mass are unavailable.")
                for code, message in shape["findings"]:
                    para(f"{code}: {message}")
            if not component.pockets:
                para("No pockets; solid rectangular insert.")
            for pocket in component.pockets:
                para(f"Pocket {pocket.id}: {pocket.shape} | Insert-local minimum-corner position X/Y/Z (mm): {position(pocket.position_m)}",
                     keep_with_next=True)
                if pocket.shape == "cylindrical":
                    para(f"Diameter: {pocket.dimensions_m[0] * 1000:.2f} mm | Depth along +Y: {pocket.dimensions_m[1] * 1000:.2f} mm | "
                         f"Nominal volume: {number(pocket_volume(pocket))} m3")
                else:
                    para(f"Dimensions X/Y/Z (mm): {millimetres(pocket.dimensions_m)} | Nominal volume: {number(pocket_volume(pocket))} m3")
            if component.pockets:
                para("Pocket positions are relative to the insert, not the carton. Supported pockets must open exactly at the insert's +Y face.")
        para("Placement schedule", "Heading3")
        for placement in box["placements"]:
            para(f"{placement['id']}: minimum-corner position X/Y/Z (mm): {position(placement['position_m'])}; orthogonal orientation {placement['orientation']}.")
        para("Packing sequence must be reviewed before release. This report records positions, not a verified insertion/removal sequence.")
        para("Surface graphic schedule", "Heading3")
        if not box.get("graphics"):
            para("No surface graphics are recorded for this package.")
        for graphic in box.get("graphics", []):
            target = "carton" if graphic["target"] == "carton" else "insert " + graphic["target_id"]
            para(f"Graphic {graphic['id']}: {graphic['kind']} | Target: {target} | Face: {graphic['face']} | Color: {graphic['color']}",
                 keep_with_next=True)
            para(f"Face-local center (u, v): {graphic['u']:.3f}, {graphic['v']:.3f} | "
                 f"Fit region: {graphic['width_fraction'] * 100:.1f}% width x {graphic['height_fraction'] * 100:.1f}% height | "
                 f"Rotation: {graphic['rotation_degrees']} degrees", keep_with_next=True)
            para(f"Lettering: {graphic['text']}" if graphic["kind"] == "text" else f"Scoped image reference: {graphic['image_id']}")
        if box.get("graphics"):
            para("Graphics are a design schedule, not print-ready artwork or a verified carrier label. Image references are recorded without retrieving external media.")
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
        canvas.drawRightString(7.85 * inch, .35 * inch, f"Revision {document['revision']} | Page {doc.page}")

    SimpleDocTemplate(output, pagesize=(8.5 * inch, 11 * inch), leftMargin=.65 * inch, rightMargin=.65 * inch,
                      topMargin=.6 * inch, bottomMargin=.6 * inch, title="InspectorPro Packaging Review").build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
