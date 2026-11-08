"""Version-bound engineering review report; no certification claims."""
from io import BytesIO
from xml.sax.saxutils import escape

STATUS = {"passed": "PASSED (geometric)", "failed": "FAILED", "needs_review": "NEEDS REVIEW",
          "not_evaluated": "NOT EVALUATED", "not_required": "NOT REQUIRED"}
CONTENTS = {"unconfirmed": "Not confirmed", "ordinary_nonhazardous": "Ordinary, non-hazardous (declared by the user)",
            "magnetized_material": "Magnetized material (not supported for rating)",
            "special_handling": "Special handling (not supported as ordinary parcels)"}
TEST_CONTENTS = ("Ordinary, non-hazardous (TEST ASSUMPTION for a synthetic or test design; not a declaration about a "
                 "real product; its rates are not shipping clearance)")
DIRECTION_ORDER = ("-x", "+x", "-y", "+y", "-z", "+z")


def restraint_row(design, assessment, codes, placed):
    """The movement row: PASSED only against a recorded requirement, on bounding boxes; otherwise review."""
    requirement = (design.get("constraints") or {}).get("restraint")
    rows = assessment.get("restraint") or []
    worst = max((r["max_travel_m"] for r in rows if r.get("max_travel_m") is not None), default=None)
    found = "" if worst is None else f"; largest predicted clearance {worst * 1000:.1f} mm"
    if not placed:
        return "not_evaluated", "No placed products"
    if not rows:
        return "not_evaluated", "No product geometry to check"
    if not requirement:
        return "needs_review", "No restraint requirement recorded" + found + " (bounding-box model, translation only)"
    state = ("failed" if codes & {"restraint_insufficient", "products_can_touch"}
             else "needs_review" if codes & {"restraint_not_verified"} else "passed")
    return state, (f"Predicted translational clearance of at most {requirement['max_travel_m'] * 1000:.1f} mm in six directions"
                   + found + "; bounding-box model; rotation, foam compression and shipping protection unverified")
STALE = {"revision_changed": "revision changed", "design_changed": "design changed",
         "account_changed": "carrier account changed", "account_removed": "carrier account removed"}
KINDS = {"carton_sku": "Carton SKU", "material_density": "Material density", "cushioning_guidance": "Cushioning guidance",
         "comparable_packaging": "Comparable packaging"}


def check_rows(design, assessment):
    """(check, status, basis) from the saved assessment. Geometry passes are envelope-level only."""
    codes = {f.get("code") for f in assessment["findings"]}
    constraints = design.get("constraints") or {}
    placed = any(box["placements"] for box in design["packages"])

    def status(failed=(), review=(), required=True):
        if not required:
            return "not_required"
        if not placed:
            return "not_evaluated"
        return "failed" if codes & set(failed) else "needs_review" if codes & set(review) else "passed"

    return [
        ("Carton fit: product and insert envelopes inside the usable carton, so the lid closes on them",
         status({"outside_usable_carton", "insert_outside_carton"}), "Bounding envelopes and the recorded clearance"),
        ("Product and insert envelopes do not overlap",
         status({"envelope_overlap", "insert_overlap"}), "Bounding envelopes and the recorded gap"),
        ("Minimum cushion between products and carton walls",
         status({"cushion_insufficient"}, {"cushion_not_verified"}, bool(constraints.get("cushion"))),
         "Insert material along each axis; not a cushioning-performance rating"),
        ("No-contact regions keep their air gap",
         status({"no_contact_violated", "no_contact_area_outside"}, {"no_contact_faces_down"}, bool(constraints.get("no_contact"))),
         "Air-gap zones on the recorded product faces"),
        ("Carton payload limit", status({"payload_exceeded"}, {"load_limit_unknown"}), "Declared carton payload capacity"),
        ("Products only in allowed orientations", status({"orientation_forbidden"}),
         "Allowed orthogonal orientations: " + ", ".join(str(o) for o in constraints.get("allowed_orientations", [0]))),
        ("Support of elevated products", "needs_review",
         "Elevated products without detected insert contact" if "support_not_verified" in codes
         else "Contact detection only; load support is not verified"),
        ("Movement and restraint: predicted translational clearance (bounding-box model) before a product meets packing "
         "material, another product or a carton wall",
         *restraint_row(design, assessment, codes, placed)),
        ("Packing and removal access", "needs_review", "Not evaluated; see each package's proposed packing order"),
        ("Drop, vibration, compression and stacking performance", "not_evaluated",
         "Requires engineering review and transport testing"),
    ]


def packing_order(box):
    """Inserts and products, lowest bottom face first; at equal height inserts first, then by Z, X and ID."""
    items = [(x["position_m"], 0, "Insert", x) for x in box["inserts"]] + [(x["position_m"], 1, "Product", x) for x in box["placements"]]
    return sorted(items, key=lambda item: (round(item[0][1], 6), item[1], round(item[0][2], 6), round(item[0][0], 6), item[3]["id"]))


def render_report(document, quotes=(), evidence=(), source=None):
    try:
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
        from reportlab.graphics.shapes import Drawing, Rect, String
    except ImportError:
        from .service import PackagingError
        raise PackagingError("report_unavailable", "PDF reports are not available in this installation: the ReportLab "
                             "component is missing. The saved design is unchanged.", 503) from None
    from .components import insert_geometry, pocket_volume
    from .geometry import oriented
    from .handling import BASIS_LABELS, requirements as handling_requirements
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

    def table(rows, widths=(2.7, .5, 3.8)):
        result = Table([[Paragraph(escape(str(cell)), styles["BodyText"]) for cell in row] for row in rows],
                       colWidths=[width * inch for width in widths], repeatRows=1, hAlign="LEFT")
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
    para("Packed assembly: all dimensions, positions, projections and masses in this report describe the packed carton contents. "
         "Exploded or transparent views in the editor are display aids only; rate requests use each packed carton's outer "
         "dimensions and gross mass.")
    para("Check status", "Heading2", keep_with_next=True)
    table([["Check", "Status", "Basis"]] + [[check, STATUS[state], basis] for check, state, basis in check_rows(design, assessment)],
          widths=(2.8, 1.55, 2.65))
    para("PASSED means the saved geometry meets the recorded requirement on bounding envelopes. It is not a protective-performance result.")
    p = design["product"]
    if p:
        para("Product", "Heading2")
        para(f"{p['name']} | Quantity: {design['quantity']} | Dimensions X/Y/Z (mm): {millimetres(p['dimensions_m'])}")
        para(f"Mass per item: {number(p['mass_kg'])} kg | Basis: {p['mass_basis']} | Evidence: {p['mass_evidence'] or 'Missing'}")
        for item in p.get("additional_mass") or []:
            amount = "unknown (left out of rated weights)" if item.get("mass_kg") is None else f"{number(item['mass_kg'])} kg"
            para(f"Added mass {item['id']}: {item['name']} | {amount} per item | Basis: {item['basis']} | "
                 f"Evidence: {item.get('evidence') or 'None recorded'}")
        para(f"Source: {p['source_id'] or 'Manual geometry'} | Source revision: {p['source_revision'] or 'Not available'}")
        library = (source or {}).get("library") if (source or {}).get("id") == p["source_id"] else None
        if library:
            para(f"InspectorPro library {library['kind']} {library['id']} | Revision: {library['revision'] or 'not recorded'} | "
                 f"Configuration: {library['configuration'] or 'as extracted (name not recorded)'} | "
                 f"Record SHA-256: {library['record_sha256'][:16]}... | Model SHA-256: {library['model_sha256'][:16]}...")
            para(f"Geometry evidence: {source.get('geometry_evidence') or 'Not recorded'}")
        calculation = p.get("mass_calculation")
        if calculation:
            material = calculation["material"]
            para("Density-based mass calculation (estimate)", "Heading3")
            para(f"Recorded solid volume: {number(calculation['volume_m3'])} m3 | Material: {material['name']} | "
                 f"Physical density: {number(material['density_kg_m3'])} kg/m3. Mass = recorded volume x density.")
            para(f"Density evidence: {material['evidence']}")
            para(f"Calculation exclusions: {calculation['exclusions'] or 'None recorded; review required'}")
            para("This is a documented estimate, not a measured item mass. The source revision and exclusions remain part of its basis.")
    constraints = design.get("constraints") or {}
    para("Protection requirements", "Heading2")
    contents = constraints.get("contents")
    test_contents = contents == "ordinary_nonhazardous" and constraints.get("contents_basis") == "test_assumption"
    para(f"Contents declaration: {TEST_CONTENTS if test_contents else CONTENTS.get(contents, 'Not recorded')}")
    if constraints.get("contents_basis"):
        para(f"Contents basis: {BASIS_LABELS.get(constraints['contents_basis'], 'not recorded')} | "
             f"Evidence: {constraints.get('contents_evidence') or 'None recorded'}")
    needs = handling_requirements(contents)
    if needs:
        para(f"Handling requirements ({needs['status']}, sources checked {needs['checked']}): {needs['eligibility']}")
        para(f"Evidence needed: {needs['evidence_needed']}")
        para(f"Carrier option: {needs['carrier_option']}")
        for carrier in needs["carriers"]:
            para(f"{carrier['carrier']} ({carrier['transport']}): {carrier['services']}. {carrier['requirement']}")
        if needs["sources"]:
            para("Sources: " + "; ".join(needs["sources"]))
    para("A recorded classification is not carrier acceptance. No contents or hazardous-materials information is sent to carriers.")
    para("Allowed product orientations (orthogonal index; 0 is the product as modelled): "
         + ", ".join(str(o) for o in constraints.get("allowed_orientations", [0])))
    if "clearance_m" in constraints:
        para(f"Minimum clearance from product envelopes to carton walls: {constraints['clearance_m'] * 1000:.2f} mm | "
             f"Minimum gap between product envelopes: {constraints.get('gap_m', 0) * 1000:.2f} mm")
    cushion = constraints.get("cushion")
    if cushion:
        material = cushion["material"]
        para(f"Minimum cushion (insert material between every product envelope and each carton wall): floor {cushion['floor_m'] * 1000:.2f} mm | "
             f"top {cushion['top_m'] * 1000:.2f} mm | sides {cushion['sides_m'] * 1000:.2f} mm. Lining material for rebuilt proposals: "
             f"{material['name']}, {number(material['density_kg_m3'])} kg/m3 (density source: {material['evidence']}).")
        para(f"Cushion requirement source: {cushion['evidence']}")
        def least(row, field):  # The assessment measures only required directions.
            if cushion[field] <= 0:
                return "not required"
            return "not determined" if row.get(field) is None else f"{row[field] * 1000:.2f} mm"
        for row in assessment.get("cushion") or []:
            para(f"Package {row['package_id']}: least insert material found: floor {least(row, 'floor_m')} | top {least(row, 'top_m')} | "
                 f"sides {least(row, 'sides_m')}{'' if row.get('verified') else ' | not fully verified'}")
    else:
        para("No minimum-cushion requirement is recorded.")
    rule = constraints.get("package_allowance")
    if rule:
        para(f"Package allowance rule: {number(rule['allowance_kg'])} kg per package, applied to every package a proposal builds. "
             f"Source: {rule['evidence']}")
    else:
        para("No package allowance rule is recorded; each package's own allowance applies.")
    regions = constraints.get("no_contact") or []
    if not regions:
        para("No no-contact regions are recorded.")
    for region in regions:
        area = region.get("area")
        where = "whole face" if not area else (f"area u {area['u_m'][0] * 1000:.2f}-{area['u_m'][1] * 1000:.2f} mm, "
                                              f"v {area['v_m'][0] * 1000:.2f}-{area['v_m'][1] * 1000:.2f} mm")
        para(f"No-contact region {region['id']}: {region['name']} | Product face {region['face']} ({where}) | "
             f"Air gap {region['air_gap_m'] * 1000:.2f} mm | Source: {region['evidence']}")
    for row in assessment.get("no_contact") or []:
        para(f"Package {row['package_id']}, region {row['region_id']}: {row['touching']} of {row['products']} products have material, "
             f"a wall or another product within the air gap; {row['facing_down']} face the carton floor.")
    para("These are geometric requirements checked on bounding envelopes. Cushioning, drop, vibration and compression performance are not evaluated.")
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
        if box.get("measured_gross_kg") is not None:
            para(f"Gross mass basis: weighed packed carton, {number(box['measured_gross_kg'])} kg (the rated weight) | "
                 f"Component estimate: {number(totals.get('estimated_gross_kg'))} kg | Weighing record: {box.get('measured_gross_evidence')}")
        else:
            para("Gross mass basis: estimate (sum of component masses; no weighed packed carton recorded).")
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
        movement = [r for r in assessment.get("restraint") or [] if r["package_id"] == box["id"]]
        if movement:
            para("Predicted translational clearance (bounding-box model)", "Heading3", keep_with_next=True)
            for row in movement:
                parts = []
                for name in DIRECTION_ORDER:
                    found = row["directions"].get(name)
                    parts.append(f"{name} not checked" if found is None else
                                 f"{name} {found['travel_m'] * 1000:.1f} mm to {'/'.join(found['stops'])}")
                para(f"{row['item_id']}: " + "; ".join(parts))
            para("Predicted translational clearance is the distance each product's bounding box can slide along an axis before it "
                 "meets packing material, another product or a carton wall. Product shape and friction are not modelled. Rotation, "
                 "foam compression and shipping protection remain unverified; this is not a protective-performance result.")
        para("Proposed packing order (derived from saved positions; not verified)", "Heading3", keep_with_next=True)
        steps = packing_order(box)
        for n, (where, _, kind, item) in enumerate(steps, 1):
            name = f" ({item['name']})" if kind == "Insert" else ""
            para(f"{n}. {kind} {item['id']}{name}: bottom face at Y {where[1] * 1000:.2f} mm.")
        para(f"{len(steps) + 1}. Close the carton. Lid closure is checked on bounding envelopes only.")
        para("Order rule: lowest bottom face first; at equal height, inserts before products, then by Z and X. "
             "Whether each item can be inserted and removed in this order is not evaluated and needs review.")
        para("Packing sequence must be reviewed before release. This report records positions and a derived order, not a verified insertion/removal sequence.")
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
    para("Public-source evidence", "Heading2")
    shown = [r for r in evidence if r.get("review_status") in ("accepted", "unreviewed")]
    if not evidence:
        para("No research evidence is recorded for this document.")
    for record in shown:
        accepted = record["review_status"] == "accepted"
        para(f"{KINDS.get(record.get('kind'), 'Evidence')}: {record['subject']} | {'ACCEPTED by the user' if accepted else 'UNREVIEWED'} | "
             f"Sage confidence: {record.get('confidence')}", keep_with_next=True)
        basis = "quoted from the page" if record.get("claim_basis") == "source_quote" else "provider summary of the page, not a quotation"
        para(f"Claim ({basis}): {record['claim']}", keep_with_next=True)
        details = [f"Value: {record['value']:g}{' ' + record['unit'] if record.get('unit') else ''}" if record.get("value") is not None else None,
                   f"SKU/grade: {record['sku_or_grade']}" if record.get("sku_or_grade") else None,
                   f"Effective: {record['effective_date']}" if record.get("effective_date") else None]
        if any(details):
            para(" | ".join(d for d in details if d), keep_with_next=True)
        source = record.get("source") or {}
        para(f"Source: {source.get('title') or 'Untitled'} | {source.get('url')} | retrieved {source.get('retrieved_at') or 'not recorded'}"
             + (f" | page date: {source['page_age']}" if source.get("page_age") else ""))
    if len(shown) < len(evidence):
        para(f"{len(evidence) - len(shown)} rejected record(s) are not shown.")
    if evidence:
        para("Evidence is supporting information only. It does not edit the design, pass validation or certify packaging.")
    para("Carrier estimates", "Heading2")
    current_quotes, superseded, seen = [], 0, set()
    for quote in quotes:  # Newest first; one snapshot per identity (design, scenario, account).
        if quote["revision"] != document["revision"]:
            continue
        identity = quote.get("fingerprint")
        if identity in seen:
            superseded += 1
            continue
        seen.add(identity)
        current_quotes.append(quote)
    if not current_quotes:
        para("No quotes are saved for this revision. No shipping price has been inferred.")
    for quote in current_quotes:
        modes = sorted({rate["mode"] for result in quote["results"] for rate in result["totals"]})
        para(f"{quote['provider']} | {quote['quoted_at']} | {quote['notice']}", keep_with_next=True)
        para(f"Quote {quote.get('id') or 'ID not recorded'} | Mode: {quote.get('mode') or ', '.join(modes) or 'not recorded'} | "
             f"Design hash: {quote.get('design_hash') or 'not recorded'} | Scenario hash: {quote.get('scenario_hash') or 'not recorded'} | "
             f"Account reference: {quote.get('account_ref') or 'not recorded'} | Fingerprint: {quote.get('fingerprint') or 'not recorded'}",
             keep_with_next=True)
        weight = quote.get("weight_basis")
        para(("Weight basis: " + weight["summary"] + (f" | Mass exclusions: {weight['exclusions']}" if weight.get("exclusions") else ""))
             if weight else "Weight basis: not recorded (saved before weight provenance was recorded).", keep_with_next=True)
        recorded = quote.get("contents")
        if recorded:
            para(f"Contents at quote time: {recorded['label']} | Basis: {recorded['basis_label']} | {recorded['notice']}", keep_with_next=True)
        mode = quote.get("account_mode")
        if mode:
            para(f"Key mode: recorded {mode.get('declared') or 'not recorded'}; EasyPost answered {mode.get('observed') or 'not recorded'}.",
                 keep_with_next=True)
        if quote.get("stale"):
            para(f"STALE ({STALE.get(quote.get('stale_reason'), 'no longer current')}): amounts are not shown. This snapshot is not a current price.")
            continue
        for result in quote["results"]:
            dest = result["destination"]
            para(f"Destination: {dest['city']}, {dest['state']} {dest['zip']}{' (residential)' if dest.get('residential') else ''}")
            for rate in result["totals"]:
                para(f"{rate['mode'].upper()} | {rate['carrier']} {rate['service']} | Account {rate.get('account_id') or 'not supplied'}: {rate['amount']} {rate['currency']} | {rate['basis']}")
        para("Each amount adds one account rate per package for that carrier service. It is not a consolidated or all-in price; "
             "carrier adjustments and API fees may apply.")
        if quote.get("fees_notice"):
            para(quote["fees_notice"])
    if superseded:
        para(f"{superseded} older quote(s) at this revision with the same identity, or with no recorded identity, are not shown; the newest is printed.")
    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#53616b"))
        canvas.drawString(.65 * inch, .35 * inch, "InspectorPro | Draft packaging review")
        canvas.drawRightString(7.85 * inch, .35 * inch, f"Revision {document['revision']} | Page {doc.page}")

    SimpleDocTemplate(output, pagesize=(8.5 * inch, 11 * inch), leftMargin=.65 * inch, rightMargin=.65 * inch,
                      topMargin=.6 * inch, bottomMargin=.6 * inch, title="InspectorPro Packaging Review").build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
