"""Carrier tags for the shipping-room roll cages (user 2026-11-16, "yes" to colour-coding the carrier cages): a
360 x 200 mm plastic placard in the carrier's colour with its name printed in white, clipped to the top rail of a
cart. Our own models. Metres, Y up, centred on X/Z, front (printed side) +Z.

The placard hangs at cart-rail height (bottom 0.635 m, clips to 0.85 m), so the model is NOT based at y = 0: the
geometry sits at its real height and the catalog height runs from the floor (0.85 m), so its clash volume is the
floor-to-rail strip in front of the cart and the placement stays on the floor (no mounting surface needed).

  python -P -E cart_tags.py build OUT_DIR    -> OUT_DIR/<stem>.glb + models.json
  python -P -E cart_tags.py install BACKUP   -> copy into the repo library + append catalog entries
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import geom as G  # noqa: E402
import warehouse_models as WM  # noqa: E402
M = G.material
FOLDER = WM.FOLDER
GEN = "cart_tags.py"
DOWNLOADS = {}
credit = WM.credit
FONT = "C:/Windows/Fonts/arialbd.ttf"

W, H, T = 0.36, 0.20, 0.004          # placard
Y0 = 0.635                           # placard bottom; the cart's top rail runs 0.825-0.85
CLIP_TOP = 0.85
CARRIERS = {   # key -> (name on the tag, colour)
    "usps": ("USPS", "#144d96"),
    "ups": ("UPS", "#523420"),
    "fedex": ("FedEx", "#4d148c"),
}


def face_image(text, colour):
    size = (1080, 600)
    rgb = tuple(int(colour[1 + 2 * k:3 + 2 * k], 16) for k in range(3))
    pic = Image.new("RGB", size, rgb)
    draw = ImageDraw.Draw(pic)
    draw.rounded_rectangle((26, 26, size[0] - 27, size[1] - 27), radius=28, outline=(255, 255, 255), width=12)
    px = 300
    font = ImageFont.truetype(FONT, px)
    while draw.textbbox((0, 0), text, font=font)[2] > size[0] * 0.80:
        px -= 10
        font = ImageFont.truetype(FONT, px)
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((size[0] - (box[2] - box[0])) / 2 - box[0], (size[1] - (box[3] - box[1])) / 2 - box[1]), text,
              fill=(255, 255, 255), font=font)
    return pic


def tag_model(key):
    name, colour = CARRIERS[key]
    b = G.Builder()
    plate = M("carrier tag plate", colour, 0.45)
    printed = M("carrier tag print", image=face_image(name, colour))
    clip = M("carrier tag clips", "#1c1e21", 0.5)
    zb, zf = -0.005, -0.005 + T
    b.box("carrier tag plate", plate, (-W / 2, Y0, zb), (W / 2, Y0 + H, zf))
    b.quad("carrier tag print", printed, [(-W / 2 + 0.002, Y0 + 0.002, zf + 0.0005),
                                          (W / 2 - 0.002, Y0 + 0.002, zf + 0.0005),
                                          (W / 2 - 0.002, Y0 + H - 0.002, zf + 0.0005),
                                          (-W / 2 + 0.002, Y0 + H - 0.002, zf + 0.0005)], (0, 0, 1))
    for x in (-0.12, 0.12):   # spring clips over the plate's top edge, reaching up to the rail
        b.box("carrier tag clips", clip, (x - 0.016, Y0 + H - 0.035, zb), (x + 0.016, CLIP_TOP, 0.005))
    return b.parts()


ASSETS = {
    f"asset-warehouse-carrier-tag-{key}": (
        f"carrier-tag-{key}", f"Carrier tag - {name}", (lambda k=key: tag_model(k)), "Material Handling",
        ["carrier tag", "cart tag", "placard", "sign", "label", name.lower(), "shipping", "carrier", "parcel",
         "roll cage", "warehouse"],
        f"Clip-on placard for a parcel roll cage: 360 x 200 mm, {name} printed in white on the carrier's colour. "
        "Clipped to the top rail of a 0.98 m cart (placard 0.635-0.835 m above the floor, clips to 0.85 m); place "
        "it on the floor right in front of the cart's face, printed side out (front +Z). Its clash volume is the "
        "floor-to-rail strip it hangs in.", None, "Our own model (InspectorPro); text only, no carrier logo.", None)
    for key, (name, _c) in CARRIERS.items()
}


def built(only=None):
    out = {}
    for asset_id, (stem, _name, builder, *_rest) in ASSETS.items():
        if only is not None and asset_id not in only:
            continue
        parts = [p for p in builder() if len(p.I)]
        for p in parts:
            WM.compact(p)
        payload = G.write_glb(stem, parts, GEN, max_texture=1024)
        lo = np.min([p.P.min(0) for p in parts], axis=0)
        hi = np.max([p.P.max(0) for p in parts], axis=0)
        assert abs(lo[0] + hi[0]) < 1e-6 and abs(lo[2] + hi[2]) < 1e-6 and abs(lo[1] - Y0) < 1e-6, (asset_id, lo, hi)
        dims = {"width": round(float(hi[0] - lo[0]), 4), "depth": round(float(hi[2] - lo[2]), 4),
                "height": round(float(hi[1]), 4)}          # from the floor: see the module note
        tris = int(sum(len(p.I) // 3 for p in parts))
        out[asset_id] = {"payload": payload, "dims": dims, "triangles": tris, "surfaces": [], "footprint": None}
    return out


if __name__ == "__main__" and sys.argv[1] == "build":
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for asset_id, info in built(sys.argv[3:] or None).items():
        stem = ASSETS[asset_id][0]
        (out_dir / f"{stem}.glb").write_bytes(info["payload"])
        summary[asset_id] = {k: v for k, v in info.items() if k != "payload"} | {"stem": stem}
        print(f"{stem:20} {info['triangles']:5} tris {len(info['payload']) // 1024:5} KB  {info['dims']}")
    for key, (name, colour) in CARRIERS.items():
        face_image(name, colour).save(out_dir / f"face-{key}.png")
    (out_dir / "models.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")

if __name__ == "__main__" and sys.argv[1] == "install":
    import warehouse_install
    warehouse_install.install(sys.modules[__name__], Path(sys.argv[2]))
