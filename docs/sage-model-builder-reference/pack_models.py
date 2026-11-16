"""Our own models for a shipping-room proposal in one of the user's private layouts (user 2026-11-16: "build the baler, a gaylord and a pack
station with printer"): a 42 in vertical cardboard baler, a gaylord on a pallet, and a dressed pack station (bench
with riser shelf, monitor, thermal label printer, parcel scale, scanner, tape gun, kraft paper roll, boxes).
Metres, Y up, bounds centred on X/Z, base at y = 0, front (operator side) +Z.

  python -P -E pack_models.py build OUT_DIR    -> OUT_DIR/<stem>.glb + models.json
  python -P -E pack_models.py install BACKUP   -> copy into the repo library + append catalog entries
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import geom as G  # noqa: E402
import warehouse_models as WM  # noqa: E402
S = G.S
M = G.material
FOLDER = WM.FOLDER
GEN = "pack_models.py"
DOWNLOADS = {}
credit = WM.credit
rng = np.random.default_rng(20261116)
FONT = "C:/Windows/Fonts/arialbd.ttf"
FONT_R = "C:/Windows/Fonts/arial.ttf"


def font(px, bold=True):
    return ImageFont.truetype(FONT if bold else FONT_R, px)


def obox(b, role, mat, centre, size, R=np.eye(3)):
    """An oriented box: SIZE (x, y, z) about CENTRE, turned by R."""
    c = np.asarray(centre, float)
    hx, hy, hz = np.asarray(size, float) / 2
    faces = {(1, 0, 0): [(1, -1, 1), (1, -1, -1), (1, 1, -1), (1, 1, 1)],
             (-1, 0, 0): [(-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)],
             (0, 1, 0): [(-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1)],
             (0, -1, 0): [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)],
             (0, 0, 1): [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)],
             (0, 0, -1): [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)]}
    for n, corners in faces.items():
        P = [c + R @ (np.array(k, float) * (hx, hy, hz)) for k in corners]
        b.quad(role, mat, P, tuple(R @ np.array(n, float)))


def ring(b, role, mat, centre, radius, tube_r, axis="z", n=24):
    cx, cy, cz = centre
    pts = []
    for i in range(n + 1):
        a = 2 * math.pi * i / n
        if axis == "z":
            pts.append((cx + radius * math.cos(a), cy + radius * math.sin(a), cz))
        else:
            pts.append((cx, cy + radius * math.sin(a), cz + radius * math.cos(a)))
    b.tube(role, mat, pts, tube_r, sides=8)


def front_quad(b, role, mat, x0, x1, y0, y1, z):
    b.quad(role, mat, [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)], (0, 0, 1))


def label_image(lines, bg, fg, size=(512, 256), px=72):
    return S.text_image(lines, bg, fg, size=size, font_px=px)


# --------------------------------------------------------------------------------------------------- baler
BALER = dict(W=1.32, D=0.95, H=2.60)


def baler_model():
    b = G.Builder()
    body = M("baler body", "#2b5c8a", 0.45, 0.3)
    frame = M("baler frame", "#1d2a36", 0.5, 0.4)
    door = M("baler doors", "#24507a", 0.45, 0.3)
    dark = M("baler chamber", "#15191d", 0.9)
    steel = M("baler bars", "#9aa3ab", 0.35, 0.8)
    yellow = M("baler handwheel", "#e8b923", 0.4, 0.2)
    grey = M("baler controls", "#c9ccd0", 0.5, 0.2)
    red = M("baler stop button", "#c62828", 0.4)
    green = M("baler start button", "#2e7d32", 0.4)
    hyd = M("baler power pack", "#30343a", 0.5, 0.5)
    W, D = BALER["W"], BALER["D"]
    zb, zf = -D / 2, D / 2 - 0.06          # chamber back / front face
    # skids and chamber
    for x in (-0.55, 0.55):
        b.box("baler frame", frame, (x - 0.06, 0.0, zb), (x + 0.06, 0.10, zf + 0.04))
    b.box("baler body", body, (-0.60, 0.10, zb + 0.02), (0.60, 1.88, zf))
    # corner posts (full height frame)
    for x in (-0.64, 0.58):
        b.box("baler frame", frame, (x, 0.10, zb), (x + 0.06, 2.50, zb + 0.08))
        b.box("baler frame", frame, (x, 0.10, zf - 0.02), (x + 0.06, 2.05, zf + 0.06))
    # lower bale door with tie slots and a handwheel latch
    b.box("baler doors", door, (-0.54, 0.16, zf), (0.54, 1.24, zf + 0.04))
    for x in (-0.36, -0.12, 0.12, 0.36):
        b.box("baler chamber", dark, (x - 0.008, 0.20, zf + 0.04), (x + 0.008, 1.02, zf + 0.045))
    hx, hy, hz = 0.40, 0.70, zf + 0.08
    ring(b, "baler handwheel", yellow, (hx, hy, hz), 0.10, 0.013)
    for a in (0, 60, 120):
        R = np.array([[math.cos(math.radians(a)), -math.sin(math.radians(a)), 0],
                      [math.sin(math.radians(a)), math.cos(math.radians(a)), 0], [0, 0, 1]])
        obox(b, "baler handwheel", yellow, (hx, hy, hz), (0.20, 0.016, 0.016), R)
    b.box("baler frame", frame, (hx - 0.025, hy - 0.025, zf + 0.04), (hx + 0.025, hy + 0.025, hz))
    # upper loading door: mesh window over the dark chamber
    b.box("baler chamber", dark, (-0.52, 1.30, zf - 0.005), (0.52, 1.84, zf + 0.002))
    b.box("baler frame", frame, (-0.54, 1.28, zf), (0.54, 1.32, zf + 0.05))
    b.box("baler frame", frame, (-0.54, 1.82, zf), (0.54, 1.86, zf + 0.05))
    for x in (-0.54, 0.50):
        b.box("baler frame", frame, (x, 1.28, zf), (x + 0.04, 1.86, zf + 0.05))
    for y in np.linspace(1.36, 1.78, 8):
        b.box("baler bars", steel, (-0.50, y - 0.006, zf + 0.02), (0.50, y + 0.006, zf + 0.032))
    for x in np.linspace(-0.40, 0.40, 5):
        b.box("baler bars", steel, (x - 0.006, 1.32, zf + 0.032), (x + 0.006, 1.82, zf + 0.042))
    b.box("baler doors", door, (-0.12, 1.50, zf + 0.05), (0.12, 1.53, zf + 0.10))      # door handle
    # upper section: cylinder housing, crosshead, cylinder
    b.box("baler body", body, (-0.50, 1.88, zb + 0.06), (0.50, 2.42, zf - 0.08))
    b.box("baler frame", frame, (-0.66, 2.42, zb), (0.66, 2.50, zf - 0.04))
    b.cylinder("baler bars", steel, (0.0, -0.05), 0.075, 2.50, 2.60, segments=20)
    # hydraulic power pack and motor, back right
    b.box("baler power pack", hyd, (0.20, 1.90, zb + 0.04), (0.50, 2.12, zb + 0.32))
    b.cylinder("baler power pack", hyd, (0.35, zb + 0.18), 0.09, 2.12, 2.34, segments=18)
    # control box on the right front post: start / stop
    b.box("baler controls", grey, (0.36, 1.92, zf - 0.08), (0.58, 2.16, zf - 0.02))
    b.cylinder("baler stop button", red, (0.0, 0.0), 0.022, 0.0, 0.03, segments=16)   # placeholder, moved below
    parts = b.parts()
    stop = [p for p in parts if p.name == "baler stop button"][0]
    # the button faces +Z: turn the little cylinder from Y to Z and set it on the box front
    stop.P = stop.P @ np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]]).T + np.array([0.52, 2.04, zf - 0.02])
    stop.N = None
    b2 = G.Builder()
    b2.box("baler start button", green, (0.40, 2.02, zf - 0.02), (0.44, 2.06, zf + 0.005))
    # warning and instruction labels
    warn = M("baler warning label", image=label_image(["DANGER", "KEEP HANDS OUT"], (240, 196, 25), (20, 20, 20),
                                                      px=54))
    front_quad(b2, "baler warning label", warn, -0.42, 0.10, 1.95, 2.21, zf - 0.079)
    info = M("baler use label", image=label_image(["CARDBOARD ONLY"], (245, 245, 245), (25, 70, 130),
                                                  size=(960, 256), px=88))
    front_quad(b2, "baler use label", info, -0.30, 0.30, 1.05, 1.21, zf + 0.041)
    parts += b2.parts()
    G.centred(parts)
    return parts


# --------------------------------------------------------------------------------------------------- gaylord
def gaylord_model():
    b = G.Builder()
    corr = M("gaylord carton", "#c18f5b", 0.85)
    edge = M("gaylord edge", "#9b6e3f", 0.85)
    inside = M("gaylord inside", "#a77b4b", 0.9)
    scrap = M("flattened cartons", "#d2a36b", 0.85)
    ph = WM.PALLET_H
    X, Z, T, H = 0.60, 0.50, 0.012, 0.90     # 1.2 x 1.0 x 0.9 m double-wall box
    y0, y1 = ph, ph + H
    for (lo, hi) in (((-X, y0, Z - T), (X, y1, Z)), ((-X, y0, -Z), (X, y1, -Z + T)),
                     ((-X, y0, -Z), (-X + T, y1, Z)), ((X - T, y0, -Z), (X, y1, Z))):
        b.box("gaylord carton", corr, lo, hi)
    b.box("gaylord inside", inside, (-X + T, y0, -Z + T), (X - T, y0 + 0.01, Z - T))
    for (lo, hi) in (((-X - 0.003, y1 - 0.02, -Z - 0.003), (X + 0.003, y1, -Z + T + 0.003)),
                     ((-X - 0.003, y1 - 0.02, Z - T - 0.003), (X + 0.003, y1, Z + 0.003)),
                     ((-X - 0.003, y1 - 0.02, -Z), (-X + T + 0.003, y1, Z)),
                     ((X - T - 0.003, y1 - 0.02, -Z), (X + 0.003, y1, Z))):
        b.box("gaylord edge", edge, lo, hi)
    # two strap bands round the box
    for y in (y0 + 0.25, y0 + 0.65):
        b.box("gaylord edge", edge, (-X - 0.004, y, -Z - 0.004), (X + 0.004, y + 0.02, Z + 0.004), faces=("+z", "-z", "+x", "-x"))
    # flattened cartons inside, leaning at random angles, about 60 % full
    for k in range(16):
        w, d = rng.uniform(0.45, 0.95), rng.uniform(0.35, 0.75)
        tilt_x, tilt_z, yaw = rng.uniform(-35, 35), rng.uniform(-35, 35), rng.uniform(0, 180)
        Rx = np.array([[1, 0, 0], [0, math.cos(math.radians(tilt_x)), -math.sin(math.radians(tilt_x))],
                       [0, math.sin(math.radians(tilt_x)), math.cos(math.radians(tilt_x))]])
        Rz = np.array([[math.cos(math.radians(tilt_z)), -math.sin(math.radians(tilt_z)), 0],
                       [math.sin(math.radians(tilt_z)), math.cos(math.radians(tilt_z)), 0], [0, 0, 1]])
        R = S.rot_y(yaw) @ Rz @ Rx
        cy = y0 + 0.20 + k * 0.03 + rng.uniform(0, 0.05)
        cx, cz = rng.uniform(-0.18, 0.18), rng.uniform(-0.14, 0.14)
        obox(b, "flattened cartons", scrap, (cx, cy, cz), (w, 0.008, d), R)
    label = M("gaylord label", image=label_image(["CARDBOARD", "TO BALE"], (250, 250, 245), (30, 30, 30)))
    front_quad(b, "gaylord label", label, -0.22, 0.22, y0 + 0.42, y0 + 0.64, Z + 0.002)
    parts = b.parts()
    # cardboard pieces may poke past the walls: clamp them inside
    for p in parts:
        if p.name == "flattened cartons":
            p.P[:, 0] = np.clip(p.P[:, 0], -X + T + 0.005, X - T - 0.005)
            p.P[:, 2] = np.clip(p.P[:, 2], -Z + T + 0.005, Z - T - 0.005)
            p.P[:, 1] = np.clip(p.P[:, 1], y0 + 0.012, y1 - 0.15)
            p.N = None
    parts += WM.copy_parts(WM.pallet_parts())
    G.centred(parts)
    return parts


# ---------------------------------------------------------------------------------------------- pack station
def screen_image():
    W, H = 880, 528
    pic = Image.new("RGB", (W, H), (236, 239, 243))
    d = ImageDraw.Draw(pic)
    d.rectangle((0, 0, W, 56), fill=(31, 58, 96))
    d.text((24, 12), "PACK & SHIP", fill=(255, 255, 255), font=font(30))
    d.text((W - 300, 16), "Station 1   Order #10482", fill=(200, 215, 235), font=font(22, False))
    d.text((24, 80), "Items", fill=(40, 40, 40), font=font(26))
    rows = [("Product A - boxed set", "1"), ("Accessory kit (4)", "1"), ("Product B", "2")]
    for i, (name, qty) in enumerate(rows):
        y = 124 + i * 46
        d.rectangle((24, y, 470, y + 38), fill=(255, 255, 255), outline=(205, 210, 218))
        d.text((36, y + 7), name, fill=(40, 40, 40), font=font(22, False))
        d.text((430, y + 7), qty, fill=(40, 40, 40), font=font(22))
        d.rectangle((444, y + 10, 462, y + 28), fill=(56, 142, 60))
    d.text((24, 278), "Box  14 x 10 x 6 in", fill=(40, 40, 40), font=font(24))
    d.text((24, 318), "Weight  5.8 lb", fill=(40, 40, 40), font=font(24))
    d.rounded_rectangle((24, 420, 330, 492), 10, fill=(56, 142, 60))
    d.text((60, 438), "PRINT LABEL", fill=(255, 255, 255), font=font(28))
    # label preview with a barcode
    d.rectangle((510, 80, 850, 492), fill=(255, 255, 255), outline=(150, 150, 150), width=2)
    d.text((530, 96), "SHIP TO", fill=(20, 20, 20), font=font(20))
    for i, w in enumerate((260, 210, 230)):
        d.rectangle((530, 130 + i * 30, 530 + w, 146 + i * 30), fill=(120, 120, 120))
    x = 540
    while x < 820:
        w = int(rng.integers(2, 7))
        d.rectangle((x, 260, x + w, 380), fill=(10, 10, 10))
        x += w + int(rng.integers(2, 6))
    d.text((560, 400), "1Z 48X 902 03 1048 2", fill=(20, 20, 20), font=font(20, False))
    return pic


def scale_display():
    pic = Image.new("RGB", (256, 96), (18, 30, 22))
    d = ImageDraw.Draw(pic)
    d.text((22, 14), "5.80 lb", fill=(120, 255, 150), font=font(54))
    return pic


def pack_station_model():
    b = G.Builder()
    W, D, TOP = 1.83, 0.91, 0.914                # 72 x 36 in bench, 36 in work height
    hx, hz = W / 2, D / 2
    steel = M("bench frame", "#5b6670", 0.45, 0.6)
    top = M("bench top", "#d8b98d", 0.6)
    shelf_m = M("bench shelves", "#7b8791", 0.5, 0.4)
    black = M("electronics black", "#1c1e21", 0.5, 0.2)
    printer_m = M("label printer", "#3a3f45", 0.45, 0.1)
    printer_lid = M("label printer lid", "#6e757d", 0.4, 0.1)
    white = M("labels", "#fafafa", 0.6)
    scale_m = M("scale platform", "#c7ccd1", 0.25, 0.85)
    tape = M("packing tape", "#b4824a", 0.4)
    kraft = M("kraft paper", "#b8936a", 0.85)
    carton = M("shipping boxes", "#c8955c", 0.85)
    red = M("tape gun", "#c0392b", 0.45)
    # legs, rails, bottom shelf
    for x in (-hx + 0.03, hx - 0.07):
        for z in (-hz + 0.03, hz - 0.07):
            b.box("bench frame", steel, (x, 0.0, z), (x + 0.04, TOP - 0.04, z + 0.04))
    b.box("bench frame", steel, (-hx + 0.03, TOP - 0.10, -hz + 0.03), (hx - 0.03, TOP - 0.04, -hz + 0.07))
    b.box("bench frame", steel, (-hx + 0.03, TOP - 0.10, hz - 0.07), (hx - 0.03, TOP - 0.04, hz - 0.03))
    b.box("bench shelves", shelf_m, (-hx + 0.03, 0.14, -hz + 0.03), (hx - 0.03, 0.16, hz - 0.03))
    b.box("bench top", top, (-hx, TOP - 0.04, -hz), (hx, TOP, hz))
    # riser: back uprights, upper shelf, light bar
    RS = 1.42
    for x in (-hx + 0.01, hx - 0.05):
        b.box("bench frame", steel, (x, TOP, -hz + 0.01), (x + 0.04, 1.80, -hz + 0.05))
    b.box("bench shelves", shelf_m, (-hx + 0.01, RS, -hz + 0.01), (hx - 0.01, RS + 0.02, -hz + 0.31))
    b.box("bench frame", steel, (-hx + 0.01, 1.76, -hz + 0.01), (hx - 0.01, 1.80, -hz + 0.09))
    b.box("labels", white, (-hx + 0.08, 1.755, -hz + 0.03), (hx - 0.08, 1.762, -hz + 0.08))     # LED strip
    # monitor on the riser shelf (screen faces +Z)
    mx = -0.42
    b.box("electronics black", black, (mx - 0.10, RS + 0.02, -hz + 0.08), (mx + 0.10, RS + 0.03, -hz + 0.22))
    b.box("electronics black", black, (mx - 0.02, RS + 0.03, -hz + 0.12), (mx + 0.02, RS + 0.16, -hz + 0.15))
    b.box("electronics black", black, (mx - 0.29, RS + 0.10, -hz + 0.15), (mx + 0.29, RS + 0.45, -hz + 0.18))
    scr = M("monitor screen", image=screen_image(), emissive=[0.55, 0.55, 0.55])
    scr.emissive_image = scr.image
    front_quad(b, "monitor screen", scr, mx - 0.275, mx + 0.275, RS + 0.115, RS + 0.435, -hz + 0.1805)
    # keyboard and mouse on the top
    b.box("electronics black", black, (mx - 0.22, TOP, -0.02), (mx + 0.22, TOP + 0.02, 0.12))
    b.box("electronics black", black, (mx + 0.28, TOP, 0.02), (mx + 0.34, TOP + 0.03, 0.12))
    # thermal label printer (4 x 6 in labels) on the top, right back, a label coming out of its front
    px, pz = 0.55, -0.24
    b.box("label printer", printer_m, (px - 0.11, TOP, pz - 0.14), (px + 0.11, TOP + 0.13, pz + 0.12))
    b.box("label printer lid", printer_lid, (px - 0.105, TOP + 0.13, pz - 0.12), (px + 0.105, TOP + 0.185, pz + 0.10))
    b.box("labels", white, (px - 0.055, TOP + 0.07, pz + 0.12), (px + 0.055, TOP + 0.072, pz + 0.27))
    b.box("printer light", M("printer light", "#43a047", 0.4), (px + 0.06, TOP + 0.135, pz + 0.10),
          (px + 0.08, TOP + 0.145, pz + 0.12))
    # label roll stock on the shelf
    b.cylinder("labels", white, (0.25, -hz + 0.16), 0.07, RS + 0.02, RS + 0.13, segments=20)
    b.cylinder("labels", white, (0.42, -hz + 0.16), 0.07, RS + 0.02, RS + 0.13, segments=20)
    # parcel scale with a box on it, display tower in front
    sx, sz = 0.10, 0.02
    b.box("electronics black", black, (sx - 0.17, TOP, sz - 0.17), (sx + 0.17, TOP + 0.04, sz + 0.17))
    b.box("scale platform", scale_m, (sx - 0.165, TOP + 0.04, sz - 0.165), (sx + 0.165, TOP + 0.055, sz + 0.165))
    b.box("electronics black", black, (sx - 0.08, TOP, sz + 0.20), (sx + 0.08, TOP + 0.07, sz + 0.25))
    disp = M("scale display", image=scale_display(), emissive=[0.6, 0.6, 0.6])
    disp.emissive_image = disp.image
    b.quad("scale display", disp, [(sx - 0.07, TOP + 0.015, sz + 0.2505), (sx + 0.07, TOP + 0.015, sz + 0.2505),
                                    (sx + 0.07, TOP + 0.064, sz + 0.2505), (sx - 0.07, TOP + 0.064, sz + 0.2505)],
           (0, 0, 1))
    b.box("shipping boxes", carton, (sx - 0.18, TOP + 0.055, sz - 0.13), (sx + 0.18, TOP + 0.21, sz + 0.12))
    b.box("packing tape", tape, (sx - 0.18, TOP + 0.2105, sz - 0.025), (sx + 0.18, TOP + 0.212, sz + 0.025))
    # handheld scanner in its stand, next to the printer
    cx, cz = 0.80, 0.05
    b.cylinder("electronics black", black, (cx, cz), 0.04, TOP, TOP + 0.02, segments=16)
    obox(b, "electronics black", black, (cx, TOP + 0.09, cz), (0.035, 0.14, 0.05),
         np.array([[1, 0, 0], [0, math.cos(0.3), -math.sin(0.3)], [0, math.sin(0.3), math.cos(0.3)]]))
    obox(b, "label printer lid", printer_lid, (cx, TOP + 0.165, cz + 0.035), (0.05, 0.05, 0.09))
    # tape gun at the front left
    tx, tz = -0.78, 0.30
    b.lathe("packing tape", tape, [(0.075, 0.0), (0.075, 0.05), (0.038, 0.05), (0.038, 0.0)],
            centre=(tx, TOP, tz), segments=24)
    obox(b, "tape gun", red, (tx + 0.07, TOP + 0.06, tz), (0.16, 0.03, 0.03))
    obox(b, "tape gun", red, (tx + 0.13, TOP + 0.03, tz), (0.03, 0.06, 0.03))
    # kraft paper roll on brackets under the top, at the front
    for x in (-0.78, 0.78):
        b.box("bench frame", steel, (x - 0.01, TOP - 0.28, hz - 0.20), (x + 0.01, TOP - 0.04, hz - 0.17))
    b.tube("kraft paper", kraft, [(-0.76, TOP - 0.22, hz - 0.12), (0.76, TOP - 0.22, hz - 0.12)], 0.09, sides=20)
    # shipping boxes: flat stock on the bottom shelf, a few made-up boxes on the riser shelf
    for k in range(6):
        y = 0.16 + k * 0.012
        b.box("shipping boxes", carton, (-0.80 + 0.01 * (k % 2), y, -0.38), (-0.05 + 0.01 * (k % 2), y + 0.01, 0.30))
    for k in range(4):
        y = 0.16 + k * 0.012
        b.box("shipping boxes", carton, (0.05, y, -0.36), (0.70, y + 0.01, 0.20))
    for (x0, x1, h) in ((0.62, 0.86, 0.16), (-0.86, -0.74, 0.12)):
        b.box("shipping boxes", carton, (x0, RS + 0.02, -hz + 0.03), (x1, RS + 0.02 + h, -hz + 0.28))
    parts = b.parts()
    G.centred(parts)
    return parts


ASSETS = {
    "asset-warehouse-baler-vertical-42": (
        "vertical-baler-42in", "Vertical cardboard baler - 42 in", baler_model, "Machines",
        ["baler", "cardboard baler", "vertical baler", "compactor", "recycling", "cardboard", "warehouse",
         "shipping"],
        "Vertical cardboard baler, 42 in class (about 1.32 m wide, 0.95 m deep, 2.6 m tall; 42 x 30 x 48 in bales "
        "of about 250-450 kg). Front +Z: upper mesh loading door, lower bale door with a handwheel latch, tie slots, "
        "start/stop box and DANGER label; hydraulic power pack at the back. Stand it with its back to a wall and keep "
        "about 1.5 m clear in front to pull bales out onto a pallet. Needs a 230 V or 460 V circuit (check the "
        "chosen model).", None, "Our own model (InspectorPro), generic, not a specific brand.", None),
    "asset-warehouse-gaylord-cardboard": (
        "gaylord-on-pallet", "Gaylord box on pallet - cardboard to bale", gaylord_model, "Storage",
        ["gaylord", "bulk box", "bulk bin", "pallet box", "cardboard", "recycling", "pallet", "warehouse",
         "shipping"],
        "Gaylord (bulk double-wall carton, 1.2 x 1.0 x 0.9 m, open top) on a 1200 x 1000 pallet, 1.03 m tall, "
        "about half full of flattened cartons, labelled CARDBOARD TO BALE. Moves with a pallet jack.", None,
        "Our own model (InspectorPro); the pallet is our library pallet.", None),
    "asset-warehouse-pack-station": (
        "pack-station-printer", "Pack station - label printer, scale, monitor", pack_station_model, "Workstations",
        ["pack station", "packing bench", "packing station", "shipping station", "label printer", "thermal printer",
         "parcel scale", "scale", "scanner", "monitor", "workbench", "warehouse", "shipping"],
        "Packing station on a 72 x 36 in bench, 36 in work height, 1.8 m to the top of its riser. Front +Z is the "
        "packer's side. On the top: thermal 4 x 6 in label printer with a label coming out, parcel scale with a box "
        "on it, keyboard and mouse, handheld scanner in its stand, tape gun. Riser shelf with the monitor (pack-and-"
        "ship screen), label rolls and spare boxes; LED light bar; kraft paper roll on brackets under the front; flat "
        "box stock on the bottom shelf.", None, "Our own model (InspectorPro).", None),
}


def built(only=None):
    out = {}
    for asset_id, (stem, name, builder, *_rest) in ASSETS.items():
        if only is not None and asset_id not in only:
            continue
        print(stem, flush=True)
        parts = [p for p in builder() if len(p.I)]
        for p in parts:
            WM.compact(p)
        payload = G.write_glb(stem, parts, GEN, max_texture=1024)
        lo = np.min([p.P.min(0) for p in parts], axis=0)
        hi = np.max([p.P.max(0) for p in parts], axis=0)
        assert abs(lo[1]) < 1e-4 and abs(lo[0] + hi[0]) < 2e-3 and abs(lo[2] + hi[2]) < 2e-3, (asset_id, lo, hi)
        dims = {"width": round(float(hi[0] - lo[0]), 4), "depth": round(float(hi[2] - lo[2]), 4),
                "height": round(float(hi[1] - lo[1]), 4)}
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
        print(f"{stem:28} {info['triangles']:7} tris {len(info['payload']) // 1024:6} KB  {info['dims']}")
    (out_dir / "models.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")

if __name__ == "__main__" and sys.argv[1] == "install":
    import warehouse_install
    warehouse_install.install(sys.modules[__name__], Path(sys.argv[2]))
