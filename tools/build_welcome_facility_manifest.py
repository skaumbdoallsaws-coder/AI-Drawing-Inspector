"""Build the curated facility-asset manifest for the local welcome CAD library."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DEFAULT_SOURCE_ROOT = Path(r"C:\Users\might\OneDrive\Desktop\welcome")
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent
    / "manifests"
    / "welcome_facility_library_20260809.json"
)


DISPLAY_NAMES = {
    "2329T24_Steel Flush Platform Truck": "Steel Flush Platform Truck",
    "3783K101_UN-COMPLIANT SHIPPING TANK": "UN-Compliant Shipping Tank",
    "5062T16_Safety Railing": "Safety Railing 5062T16",
    "5062T59_Safety Railing": "Safety Railing 5062T59",
    "57895T116_Bollard": "Safety Bollard 57895T116",
    "5946T21_Bollard Gate": "Bollard Gate 5946T21",
    "5946T22_Bollard Gate": "Bollard Gate 5946T22",
    "5946T23_Bollard Gate": "Bollard Gate 5946T23",
    "5946T24_Bollard Gate": "Bollard Gate 5946T24",
    "5946T25_Bollard Gate": "Bollard Gate 5946T25",
    "5987T14_3 '9-1-4 Wide Solid Polycarbonate Panel for Machine Guard": (
        "Polycarbonate Machine Guard Panel 5987T14"
    ),
    "5987T51_Machine Guard": "Machine Guard Panel 5987T51",
    "5987T91_1'9-5-8 Wide Pegboard Panel for Machine Guard": (
        "Pegboard Machine Guard Panel 5987T91"
    ),
    "7467N11_Fire Hydrant": "Fire Hydrant 7467N11",
    "8069T12_6 Feet x 28-1-2 Wide Plank Size Base Section for Uneven Surface Scaffold": (
        "Uneven-Surface Scaffold Base Section"
    ),
    "9808N113_Low-Height Vehicle Ramp": "Low-Height Vehicle Ramp 9808N113",
    "basket_blue": "Blue Storage Basket",
    "book_250_20_red": "Red Reference Book",
    "bus-green": "Green Transit Bus",
    "chair_black": "Black Office Chair",
    "computer_case_": "Desktop Computer",
    "crowd_control_barrier_14_bars": "14-Bar Crowd-Control Barrier",
    "crowd_control_barrier_18_bars": "18-Bar Crowd-Control Barrier",
    "desk-1400-clear_wood": "1400 mm Wood Office Desk",
    "forklift_2610x2264x986_minimum_height_green": "Compact Green Forklift",
    "green_garbage_container": "Green Waste Container",
    "keyboard": "Computer Keyboard",
    "mouse": "Computer Mouse",
    "office_container-10090_2420": "10.09 x 2.42 m Office Container",
    "office_container-3009_2000": "3.01 x 2.00 m Office Container",
    "phone_tel1": "Office Telephone",
    "public_contemporary_bench": "Contemporary Public Bench",
    "public_double_bench": "Double Public Bench",
    "public_slat_bench": "Slat Public Bench",
    "road_light-double": "Double Road Light",
    "road_light-simple": "Single Road Light",
    "screen_16_9-19_p_300": "19-Inch Widescreen Monitor",
    "screen_21": "21-Inch Monitor",
    "simple_bus_shelter-gray": "Gray Bus Shelter",
    "traffic_cone_50": "Traffic Cone",
    "User Library-1700": "JMP 875 Bottle Filler",
    "User Library-Curved Modular Belt Conveyor V1-1": "Curved Modular Belt Conveyor",
    "User Library-Drawers - 4-6in x 42in W": "42-Inch Drawer Cabinet",
    "User Library-LINEAR MODULAR CONVEYOR 400X1540 P70R30": (
        "400 x 1540 Modular Conveyor"
    ),
    "User Library-Mobile Cart": "Mobile Utility Cart",
    "User Library-NA-300X2100": "NA 300 x 2100 Conveyor",
    "User Library-NA-450X1200": "NA 450 x 1200 Conveyor",
    "User Library-Paper Towel Dispenser": "Paper Towel Dispenser",
    "User Library-roller guide": "Conveyor Roller Guide",
    "User Library-Sink-1": "Facility Sink",
}


PRIMARY_ASSEMBLIES = (
    {
        "assetId": "asset-light-curtain-floor-column",
        "displayName": "Safety Light-Curtain Floor Column",
        "category": "Safety",
        "relativePath": "12007/1200704.SLDASM",
        "description": "Floor-mounting column for a 2000 mm safety light curtain.",
        "tags": ["light curtain", "safety", "floor column"],
    },
    {
        "assetId": "asset-assembled-laboratory-workstation",
        "displayName": "Assembled Laboratory Workstation",
        "category": "Laboratory",
        "relativePath": "assembled lab/User Library-Assembled Lab.SLDASM",
        "description": "Laboratory workstation with bench, cabinets, drawers, and shelves.",
        "tags": ["laboratory", "workstation", "cabinet", "shelf"],
        "supportSurfaces": [{
            "surfaceId": "worktop",
            "label": "Laboratory worktop",
            "elevationRatio": 0.429412,
            "originXRatio": 0.0,
            "originZRatio": 0.162067,
            "widthRatio": 1.0,
            "depthRatio": 0.662069,
            "allowedSides": ["above"],
            "evidenceStatus": "derived",
        }],
    },
    {
        "assetId": "asset-machine-guard-door-lh",
        "displayName": "Left-Hand Machine Guard Door",
        "category": "Safety",
        "relativePath": "backhd/backhd355lh.SLDASM",
        "description": "Three-foot by five-foot welded-wire machine-guard door.",
        "tags": ["machine guard", "door", "safety", "wire mesh"],
    },
    {
        "assetId": "asset-electrical-test-tank",
        "displayName": "Electrical Test Tank",
        "category": "Laboratory",
        "relativePath": "baksvs/User Library-baksvs.SLDASM",
        "description": "Electrical test-tank assembly with controls and protective enclosure.",
        "tags": ["electrical test", "tank", "laboratory", "unverified use"],
    },
    {
        "assetId": "asset-blue-coat-hanger",
        "displayName": "Blue Coat Hanger",
        "category": "Facilities",
        "relativePath": "coathanger/coathanger_blue.SLDASM",
        "description": "Freestanding coat hanger for office and employee-support spaces.",
        "tags": ["coat hanger", "furniture", "support area"],
    },
    {
        "assetId": "asset-iso-container-40ft-applico",
        "displayName": "40 ft ISO Shipping Container",
        "category": "Storage",
        "relativePath": "container/User Library-40' ISO Container- APPLICO Engineering.SLDASM",
        "description": "Detailed 40-foot ISO shipping-container assembly.",
        "tags": ["shipping container", "40 ft", "storage", "iso"],
    },
    {
        "assetId": "asset-shipping-container-40ft-welcome",
        "displayName": "40 ft Shipping Container",
        "category": "Storage",
        "relativePath": "container 2/User Library-40x08x08-SHIPPING-CONTAINER.ZIP.sldasm",
        "description": "Forty-foot shipping container for storage and logistics planning.",
        "tags": ["shipping container", "40 ft", "storage", "logistics"],
    },
    {
        "assetId": "asset-shipping-container-20ft-welcome",
        "displayName": "20 ft Shipping Container",
        "category": "Storage",
        "relativePath": "container 3/User Library-20x08x08-SHIPPING-CONTAINER.sldasm",
        "description": "Twenty-foot shipping container for storage and logistics planning.",
        "tags": ["shipping container", "20 ft", "storage", "logistics"],
    },
    {
        "assetId": "asset-floor-fan-white",
        "displayName": "White Floor Fan",
        "category": "Facilities",
        "relativePath": "fan/foot_fan_white.SLDASM",
        "description": "Floor-standing circulation fan for facility support areas.",
        "tags": ["fan", "ventilation", "facility"],
    },
    {
        "assetId": "asset-forklift-telescopic-red",
        "displayName": "Red Telescopic Forklift",
        "category": "Material Handling",
        "relativePath": "forklift/forklift_truck-with_fork-red.SLDASM",
        "description": "Forklift truck with telescopic arm and fork attachment.",
        "tags": ["forklift", "telescopic", "material handling"],
    },
    {
        "assetId": "asset-tr1631-machine-guard-enclosure",
        "displayName": "TR1631 Mobile Mesh Roll Container",
        "category": "Material Handling",
        "relativePath": "Mesh/User Library-TR1631.sldasm",
        "description": "Mobile mesh roll container with casters and access panels.",
        "tags": ["roll container", "mesh cart", "caster", "material handling"],
    },
    {
        "assetId": "asset-electrical-glove-test-bath",
        "displayName": "Electrical Glove Test Bath",
        "category": "Laboratory",
        "relativePath": "perch/User Library-vannaia12perch-1.SLDASM",
        "description": "Electrical glove test-bath assembly with support and electrical components.",
        "tags": ["electrical test", "glove", "bath", "laboratory", "unverified use"],
    },
)


SUPPORT_SURFACES = {
    "desk-1400-clear_wood.SLDPRT": [{
        "surfaceId": "worktop",
        "label": "Desk worktop",
        "elevationRatio": 1.0,
        "widthRatio": 0.92,
        "depthRatio": 0.88,
        "allowedSides": ["above", "below"],
        "evidenceStatus": "derived",
    }],
    "User Library-Drawers - 4-6in x 42in W.sldprt": [{
        "surfaceId": "cabinet-top",
        "label": "Cabinet top",
        "elevationRatio": 1.0,
        "widthRatio": 0.94,
        "depthRatio": 0.94,
        "allowedSides": ["above"],
        "evidenceStatus": "derived",
    }],
}


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not result:
        raise ValueError(f"Cannot derive an asset ID from {value!r}")
    return result


def _display_name(stem: str) -> str:
    if stem in DISPLAY_NAMES:
        return DISPLAY_NAMES[stem]
    return stem.replace("_", " ").replace("-", " ").title()


def _category(stem: str) -> str:
    value = stem.casefold()
    if "user library-1700" in value:
        return "Packaging"
    if any(token in value for token in ("conveyor", "roller guide", "na-300", "na-450")):
        return "Conveyors"
    if any(token in value for token in (
        "mandatory_sign", "no_entry", "no_left", "no_right", "no_u_turn",
        "no_parking", "traffic_cone", "crowd_control", "safety railing",
        "bollard", "machine guard", "polycarbonate panel", "pegboard panel",
        "fire hydrant",
    )):
        return "Safety"
    if any(token in value for token in (
        "platform truck", "vehicle ramp", "forklift", "mobile cart",
    )):
        return "Material Handling"
    if "bus-green" in value:
        return "Vehicles"
    if any(token in value for token in (
        "desk", "chair", "computer", "keyboard", "mouse", "phone",
        "screen", "book",
    )):
        return "Office & IT"
    if any(token in value for token in ("shipping tank", "basket", "drawers")):
        return "Storage"
    return "Facilities"


def _tags(display_name: str, category: str) -> list[str]:
    words = [
        word for word in re.findall(r"[a-z0-9]+", display_name.casefold())
        if len(word) > 2 and word not in {"the", "and", "for", "inch", "wide"}
    ]
    result = [category.casefold(), *words[:4], "welcome library"]
    return list(dict.fromkeys(result))


def _top_level_assets(source_root: Path) -> list[dict]:
    parts = sorted(
        path for path in source_root.iterdir()
        if path.is_file() and path.suffix.casefold() == ".sldprt"
    )
    if len(parts) != 64:
        raise RuntimeError(
            f"Expected 64 top-level part files in {source_root}, found {len(parts)}"
        )
    assets = []
    for path in parts:
        display_name = _display_name(path.stem)
        category = _category(path.stem)
        item = {
            "assetId": f"asset-{_slug(path.stem)}",
            "displayName": display_name,
            "category": category,
            "relativePath": path.name,
            "sourceKind": "part",
            "description": (
                f"{display_name} CAD model for {category.casefold()} planning "
                "in facility layouts."
            ),
            "tags": _tags(display_name, category),
        }
        support_surfaces = SUPPORT_SURFACES.get(path.name)
        if support_surfaces:
            item["supportSurfaces"] = support_surfaces
        assets.append(item)
    return assets


def build_manifest(source_root: Path) -> dict:
    source_root = source_root.resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"Welcome library folder not found: {source_root}")
    assets = _top_level_assets(source_root)
    for specification in PRIMARY_ASSEMBLIES:
        item = dict(specification)
        item["sourceKind"] = "assembly"
        source_path = source_root / Path(item["relativePath"])
        if not source_path.is_file():
            raise FileNotFoundError(f"Primary assembly not found: {source_path}")
        assets.append(item)
    assets.sort(key=lambda item: item["assetId"])
    identifiers = [item["assetId"] for item in assets]
    if len(identifiers) != len(set(identifiers)):
        raise RuntimeError("Welcome library asset IDs are not unique")
    if len(assets) != 76:
        raise RuntimeError(f"Expected 76 curated assets, found {len(assets)}")
    return {"schemaVersion": 1, "assets": assets}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_manifest(args.source_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(payload['assets'])} assets to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
