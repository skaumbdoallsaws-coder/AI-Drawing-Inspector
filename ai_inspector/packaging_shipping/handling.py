"""Contents handling: what each classification means for rating, with its documented sources.

A classification recorded in a design is never carrier acceptance. This workflow sends no contents or
hazardous-materials information to carriers, so only ordinary contents are rated and every other class is
reported as unsupported. No carrier eligibility rule is applied: for magnetized material the USPS sources
disagree, and a USPS ruling is needed before any rule is implemented (checked 2026-11-07).
"""
from __future__ import annotations

CHECKED = "2026-11-07"

CONTENTS_LABELS = {
    "unconfirmed": "Not confirmed",
    "ordinary_nonhazardous": "Ordinary, non-hazardous",
    "magnetized_material": "Magnetized material (not supported for rating)",
    "special_handling": "Special handling (not supported for rating)",
}
BASIS_LABELS = {
    "product_declaration": "declaration about the real product",
    "test_assumption": "test assumption (not a declaration about a real product; results are not shipping clearance)",
}

UNSUPPORTED_CONTENTS = {
    "magnetized_material": (
        "Magnetized material is not supported for rating. No hazardous-materials option is sent to carriers, and carrier "
        "eligibility rules wait for a USPS ruling on Publication 52 sections 349.42 and 349.6, so this shipment stays unrated."),
    "special_handling": (
        "Special-handling contents are not supported for rating. This workflow sends no contents or hazardous-materials "
        "information to carriers, so a returned rate would not reflect them."),
}

NO_TRANSMISSION = ("No contents or hazardous-materials information was sent to the carrier. A returned rate is not "
                   "carrier acceptance of the contents.")

# Documented requirements, reported only. Paraphrased from the sources; nothing here decides eligibility.
REQUIREMENTS = {
    "magnetized_material": {
        "status": "unresolved",
        "eligibility": ("Not implemented. USPS Publication 52 349.42 allows domestic air for magnetized material of 0.002 "
                        "gauss or more at 7 ft (up to 0.00525 gauss at 15 ft) with Packaging Instruction 9B, the warning "
                        "label and a shipping paper, while 349.6 and 327.12 bar from air material that deflects a compass "
                        "at 7 ft. A USPS ruling is needed before any eligibility rule is applied."),
        "evidence_needed": ("Field strength of the packed carton as shipped, from every face: at 7 ft (2.1 m) with a "
                            "gaussmeter or compass, and at 15 ft (4.6 m) for the air limit."),
        "carrier_option": ("EasyPost shipment option hazmat = CLASS_9_MAGNETIZED exists and is not sent. EasyPost returns "
                           "rates only from carriers that support the type, which is not carrier acceptance."),
        "carriers": [
            {"carrier": "USPS", "transport": "surface",
             "services": "USPS Ground Advantage, Parcel Select Lightweight (Publication 52 Appendix D)",
             "requirement": ("Not regulated as hazardous by surface (349.42). Mailpieces with unconfined fields are marked "
                             "Surface Only (or Surface Mail Only) and Magnetic - Keep 7 Feet Away From Navigational "
                             "Equipment (Packaging Instruction 9B; the term is not defined).")},
            {"carrier": "USPS", "transport": "air",
             "services": "Priority Mail, Priority Mail Express (Publication 52 327.12 and Appendix D)",
             "requirement": ("Below 0.002 gauss or 0.5 degrees of compass deviation at 7 ft: not magnetized material "
                             "(349.41). Above 0.00525 gauss at 15 ft: not mailable by air (349.42). In between: "
                             "Publication 52 is inconsistent (349.42 against 349.6 and 327.12); unresolved.")},
            {"carrier": "UPS", "transport": "all services",
             "services": "UPS services, including UPS Small Package (carrier variation 5X-07, DGR edition 65, 2024)",
             "requirement": ("UN 2807 above 0.00525 gauss at 4.6 m from any surface is not accepted. UPS ground policy "
                             "was not verified (pages unavailable).")},
            {"carrier": "FedEx", "transport": "domestic",
             "services": "FedEx Express within the US (FedEx dangerous goods service guide)",
             "requirement": ("Shipped in accordance with 49 CFR. 49 CFR 173.21(d) forbids on aircraft any package above "
                             "0.00525 gauss at 4.5 m (15 ft); no highway limit was found.")},
        ],
        "sources": [
            "https://www.ecfr.gov/current/title-49/subtitle-B/chapter-I/subchapter-C/part-173/subpart-A/section-173.21",
            "https://pe.usps.com/text/pub52/pub52c3_028.htm",
            "https://pe.usps.com/text/pub52/pub52c3_008.htm",
            "https://pe.usps.com/text/pub52/pub52apxc_030.htm",
            "https://pe.usps.com/text/pub52/pub52apxd.htm",
            "https://www.ups.com/assets/resources/webcontent/en_US/UPS_Carrier_Variations.pdf",
            "https://www.fedex.com/en-us/service-guide/dangerous-goods/how-to-ship.html",
            "https://docs.easypost.com/docs/shipments/options",
        ],
    },
    "special_handling": {
        "status": "unsupported",
        "eligibility": "Not implemented. Each special-handling class needs its own documented carrier requirements.",
        "evidence_needed": "The hazard class, its carrier requirements and any measurements those requirements name.",
        "carrier_option": "None is sent.",
        "carriers": [],
        "sources": [],
    },
}


def requirements(classification):
    """Documented handling requirements for a contents class, or None for ordinary or unconfirmed contents."""
    entry = REQUIREMENTS.get(classification)
    return None if entry is None else {"classification": classification, "checked": CHECKED, **entry}
