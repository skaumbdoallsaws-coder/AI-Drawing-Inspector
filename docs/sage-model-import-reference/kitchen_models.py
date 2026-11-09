"""Gym kitchenette makeover models (user 2026-11-08): a modern kitchen run and a waterfall island of our own (built
here), CC BY 4.0 Sketchfab downloads (untrusted data: read as numbers and images only, each copied into its own
folder dl/<key>/model.glb) for the fridge, counter stool and pendant, and our own art, neon and counter styling.
Metres, Y up, front +Z, bounds centred on X/Z, base at y = 0; wall-mounted items have their back on the -Z face.

  python kitchen_models.py build OUT_DIR   -> OUT_DIR/<stem>.glb + models.json (catalog fields) + art previews
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import geom as G  # noqa: E402
S = G.S
M = G.material
GEN = "kitchen_models.py"
rng = np.random.default_rng(20261108)

# --------------------------------------------------------------------------------------------- shared materials
PRIMER = "#d8d4cc"          # unfinished fronts: the finishes are Sage's job on camera
CARCASS = "#3b3a38"
PLINTH = "#262524"
WORKTOP = "#cfcdc8"
STEEL = "#b8bbbe"
LED = "#e9e5dc"


def mprimer(name):
    return M(name, PRIMER, roughness=0.75)


# --------------------------------------------------------------------------------------------- textures
def zellige_texture(width_m, height_m, tile=0.1, px_per_m=900):
    """Glossy hand-made tiles: warm white, each a little uneven (glaze pooled toward one edge, a darker rim where it
    thins), set in thin cream grout."""
    W, H = int(width_m * px_per_m), int(height_m * px_per_m)
    img = Image.new("RGB", (W, H), (205, 194, 176))
    t = int(tile * px_per_m)
    grout = max(2, int(0.0025 * px_per_m))
    n = t - 2 * grout
    yy, xx = np.mgrid[0:n, 0:n] / max(1, n - 1)
    for y in range(0, H, t):
        for x in range(0, W, t):
            base = np.array([243, 236, 223]) + rng.normal(0, 6) + rng.normal(0, 1.0) * np.array([3, 1.5, -2.5])
            ang = rng.uniform(0, 2 * math.pi)
            ramp = (np.cos(ang) * (xx - 0.5) + np.sin(ang) * (yy - 0.5)) * rng.uniform(8, 18)
            edge = np.minimum(np.minimum(xx, 1 - xx), np.minimum(yy, 1 - yy))
            rim = -16 * np.exp(-edge / 0.05)
            noise = rng.normal(0, 2.0, (n, n))
            tile_px = base[None, None, :] + (ramp + rim + noise)[..., None]
            piece = Image.fromarray(np.clip(tile_px, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
            img.paste(piece, (x + grout, y + grout))
    return img


def cooktop_texture():
    img = Image.new("RGB", (1024, 660), (18, 18, 20))
    d = ImageDraw.Draw(img)
    for cx, cy, r in ((270, 200, 150), (270, 500, 120), (720, 330, 190), (720, 330, 120)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(70, 70, 74), width=4)
    for k in range(7):
        d.rectangle([340 + k * 52, 610, 370 + k * 52, 624], fill=(95, 95, 100))
    return img


def abstract_art(size=(2400, 1600)):
    """Our own warm abstract: organic shapes in terracotta, ochre, olive, blush and charcoal on raw linen."""
    W, H = size
    base = np.full((H, W, 3), (236, 226, 208), float)
    base += rng.normal(0, 4.0, (H, W, 1))
    weave = (np.sin(np.arange(W) * 1.9)[None, :, None] + np.sin(np.arange(H) * 2.3)[:, None, None]) * 2.0
    img = Image.fromarray(np.clip(base + weave, 0, 255).astype(np.uint8))
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # a big terracotta arch rising from the bottom left
    d.pieslice([-260, 520, 1180, 1960], 180, 360, fill=(190, 98, 62, 255))
    d.pieslice([40, 820, 880, 1660], 180, 360, fill=(236, 226, 208, 255))
    d.pieslice([200, 980, 720, 1500], 180, 360, fill=(214, 160, 140, 255))
    # an ochre sun, top right
    d.ellipse([1560, 170, 2060, 670], fill=(214, 158, 62, 255))
    # an olive leaf shape crossing the middle
    leaf = [(1180, 1450), (1320, 980), (1560, 700), (1800, 600), (1700, 900), (1520, 1200), (1260, 1460)]
    d.polygon(leaf, fill=(92, 104, 58, 255))
    # a blush rounded block, bottom right
    d.rounded_rectangle([1840, 980, 2240, 1600], radius=200, fill=(214, 168, 150, 255))
    # a charcoal line drawn across, and a few dots
    pts = [(160, 420), (520, 300), (900, 380), (1200, 620), (1500, 560), (1880, 820), (2300, 760)]
    d.line(pts, fill=(46, 42, 38, 255), width=14, joint="curve")
    for cx, cy, r in ((980, 230, 26), (1060, 270, 16), (2120, 380, 20), (640, 1180, 18)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(46, 42, 38, 255))
    # paint texture: the shapes slightly mottled
    arr = np.array(layer).astype(float)
    mask = arr[..., 3:] / 255
    arr[..., :3] += rng.normal(0, 7, arr[..., :3].shape) * mask
    layer = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2))
    img.paste(layer, (0, 0), layer)
    return img


def neon_images(text, font_file, size=(2048, 680), font_px=300):
    """(alpha mask RGBA, emissive RGB) for neon script letters."""
    W, H = size
    probe = ImageDraw.Draw(Image.new("L", size))
    while True:   # the largest size that fits 92 % of the width and 80 % of the height
        font = ImageFont.truetype(font_file, font_px)
        box = probe.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= W * 0.92 and box[3] - box[1] <= H * 0.8:
            break
        font_px -= 8
    x = (W - (box[2] - box[0])) / 2 - box[0]
    y = (H - (box[3] - box[1])) / 2 - box[1]
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).text((x, y), text, fill=255, font=font)
    mask = mask.filter(ImageFilter.MaxFilter(5))                  # tube thickness
    core = mask.filter(ImageFilter.MinFilter(5))                 # the bright core of each tube
    glow = Image.new("RGB", size, (255, 170, 90))
    glow.paste(Image.new("RGB", size, (255, 236, 205)), (0, 0), core)
    rgba = glow.copy()
    rgba.putalpha(mask)
    return rgba, glow


# --------------------------------------------------------------------------------------------- the kitchen run
RUN_W, NICHE_W = 4.555, 1.2
ZB, ZC = -0.355, 0.285            # back (6 mm off the wall when placed) and carcass front
DOOR_T, GAP = 0.02, 0.003
ZD = ZC + DOOR_T                  # door fronts
TOP_Y = 3.18                      # 2 cm under a 3.2 m ceiling
PLINTH_H, BASE_TOP, WORK_T = 0.10, 0.90, 0.04


def run_model():
    b = G.Builder()
    m_doors, m_base = mprimer("tall cabinet doors"), mprimer("base cabinet fronts")
    m_carc = M("cabinet carcass", CARCASS, 0.8)
    m_plinth = M("plinth", PLINTH, 0.8)
    m_handle = M("handles", STEEL, 0.35, 0.9)
    m_work = M("worktop", WORKTOP, 0.35)
    m_sink = M("sink", STEEL, 0.3, 0.9)
    m_tap = M("faucet", STEEL, 0.25, 0.95)
    m_app = M("built-in appliances", "#141416", 0.12, 0.3)
    m_trim = M("appliance trim", "#8c8f93", 0.35, 0.9)
    m_shelf = mprimer("floating shelves")
    m_led = M("shelf LED strip", LED, 0.3)
    half, nh = RUN_W / 2, NICHE_W / 2
    end_t = 0.02
    # carcass and plinth
    b.box("plinth", m_plinth, (-half + 0.03, 0, ZB), (half - 0.03, PLINTH_H, ZC - 0.06))
    b.box("cabinet carcass", m_carc, (-half + end_t, PLINTH_H, ZB), (-nh - end_t, TOP_Y, ZC))
    b.box("cabinet carcass", m_carc, (nh + end_t, PLINTH_H, ZB), (half - end_t, TOP_Y, ZC))
    b.box("cabinet carcass", m_carc, (-nh, PLINTH_H, ZB), (nh, BASE_TOP, ZC))
    # finished panels: the two outer ends and the two niche sides (full depth to the door fronts)
    for x0, x1 in ((-half, -half + end_t), (half - end_t, half), (-nh - end_t, -nh), (nh, nh + end_t)):
        b.box("tall cabinet doors", m_doors, (x0, 0 if abs(x0) > 2 else BASE_TOP + WORK_T if False else 0, ZB),
              (x1, TOP_Y, ZD))
    # tall doors: west bank = two doors + the appliance column next to the niche; east bank = three doors
    lower_top, upper = 2.30, 2.30 + GAP

    def door(x0, x1, y0, y1, handle="tall"):
        b.box("tall cabinet doors", m_doors, (x0 + GAP / 2, y0 + GAP / 2, ZC), (x1 - GAP / 2, y1 - GAP / 2, ZD))
        if handle == "tall":
            hx = x1 - 0.06 if (x0 + x1) / 2 < 0 else x0 + 0.06
            b.box("handles", m_handle, (hx - 0.006, 0.95, ZD), (hx + 0.006, 1.75, ZD + 0.025))
        elif handle == "upper":
            hx = x1 - 0.06 if (x0 + x1) / 2 < 0 else x0 + 0.06
            b.box("handles", m_handle, (hx - 0.006, y0 + 0.06, ZD), (hx + 0.006, y0 + 0.32, ZD + 0.025))

    west = np.linspace(-half + end_t, -nh - end_t - 0.60, 3)
    for x0, x1 in zip(west[:-1], west[1:]):
        door(x0, x1, PLINTH_H, lower_top)
        door(x0, x1, upper, TOP_Y, "upper")
    east = np.linspace(nh + end_t, half - end_t, 4)
    for x0, x1 in zip(east[:-1], east[1:]):
        door(x0, x1, PLINTH_H, lower_top)
        door(x0, x1, upper, TOP_Y, "upper")
    # the appliance column: drawer, oven, combi microwave, coffee machine, then a top door
    ax0, ax1 = -nh - end_t - 0.60, -nh - end_t
    b.box("tall cabinet doors", m_doors, (ax0 + GAP, PLINTH_H + GAP, ZC), (ax1 - GAP, 0.70, ZD))
    b.box("handles", m_handle, ((ax0 + ax1) / 2 - 0.2, 0.62, ZD), ((ax0 + ax1) / 2 + 0.2, 0.632, ZD + 0.025))
    for y0, y1, kind in ((0.703, 1.30, "oven"), (1.303, 1.75, "microwave"), (1.753, 2.30, "coffee")):
        b.box("built-in appliances", m_app, (ax0 + GAP, y0, ZC), (ax1 - GAP, y1, ZD))
        b.box("appliance trim", m_trim, (ax0 + 0.02, y1 - 0.07, ZD), (ax1 - 0.02, y1 - 0.05, ZD + 0.003))
        if kind in ("oven", "microwave"):
            b.box("handles", m_handle, ((ax0 + ax1) / 2 - 0.22, y1 - 0.12, ZD), ((ax0 + ax1) / 2 + 0.22,
                                                                              y1 - 0.108, ZD + 0.035))
        else:   # the coffee machine's spout and drip tray
            cx = (ax0 + ax1) / 2
            b.box("appliance trim", m_trim, (cx - 0.04, y0 + 0.16, ZD), (cx + 0.04, y0 + 0.22, ZD + 0.05))
            b.box("appliance trim", m_trim, (cx - 0.10, y0 + 0.03, ZD), (cx + 0.10, y0 + 0.045, ZD + 0.08))
    door(ax0, ax1, upper, TOP_Y, "upper")
    # the niche: two doors under a worktop with an undermount sink, zellige up to the ceiling, two shelves
    for x0, x1 in ((-nh, 0), (0, nh)):
        b.box("base cabinet fronts", m_base, (x0 + GAP, PLINTH_H + GAP, ZC), (x1 - GAP, BASE_TOP - GAP, ZD))
        hx = x1 - 0.06 if x0 < 0 else x0 + 0.06
        b.box("handles", m_handle, (hx - 0.006, 0.55, ZD), (hx + 0.006, 0.83, ZD + 0.025))
    y0, y1 = BASE_TOP, BASE_TOP + WORK_T
    sx, sz0, sz1 = 0.25, -0.24, 0.16
    zf = ZD + 0.02
    for lo, hi in (((-nh, y0, ZB), (nh, y1, sz0)), ((-nh, y0, sz1), (nh, y1, zf)),
                   ((-nh, y0, sz0), (-sx, y1, sz1)), ((sx, y0, sz0), (nh, y1, sz1))):
        b.box("worktop", m_work, lo, hi)
    # sink basin (inner faces)
    sb = 0.70
    b.quad("sink", m_sink, [(-sx, sb, sz1), (sx, sb, sz1), (sx, sb, sz0), (-sx, sb, sz0)], (0, 1, 0))
    b.quad("sink", m_sink, [(-sx, sb, sz0), (sx, sb, sz0), (sx, y0, sz0), (-sx, y0, sz0)], (0, 0, 1))
    b.quad("sink", m_sink, [(sx, sb, sz1), (-sx, sb, sz1), (-sx, y0, sz1), (sx, y0, sz1)], (0, 0, -1))
    b.quad("sink", m_sink, [(-sx, sb, sz1), (-sx, sb, sz0), (-sx, y0, sz0), (-sx, y0, sz1)], (1, 0, 0))
    b.quad("sink", m_sink, [(sx, sb, sz0), (sx, sb, sz1), (sx, y0, sz1), (sx, y0, sz0)], (-1, 0, 0))
    b.disc("sink", M("sink drain", "#55585b", 0.4, 0.8), (0, sb + 0.001, -0.04), 0.035)
    # faucet: a gooseneck from the back of the sink
    tz = -0.30
    b.cylinder("faucet", m_tap, (0, tz), 0.028, y1, y1 + 0.05)
    arc = [(0, y1 + 0.05 + 0.33 * t, tz) for t in np.linspace(0, 1, 6)]
    rc, top = 0.12, y1 + 0.38
    arc += [(0, top + rc * math.sin(a), tz + rc - rc * math.cos(a)) for a in np.linspace(0, math.pi, 16)][1:]
    arc += [(0, top - 0.10 * t, tz + 2 * rc) for t in np.linspace(0, 1, 4)][1:]
    b.tube("faucet", m_tap, arc, 0.013)
    b.tube("faucet", m_tap, [(0.03, y1 + 0.16, tz), (0.11, y1 + 0.20, tz)], 0.007)
    # zellige backsplash over the whole niche
    bz = ZB + 0.012
    tex = zellige_texture(NICHE_W, TOP_Y - y1)
    m_tile = M("zellige backsplash", "#ffffff", 0.18, image=tex)
    b.box("zellige backsplash", m_tile, (-nh, y1, ZB), (nh, TOP_Y, bz), faces=())
    b.quad("zellige backsplash", m_tile, [(-nh, y1, bz), (nh, y1, bz), (nh, TOP_Y, bz), (-nh, TOP_Y, bz)],
           (0, 0, 1), uv=((0, 1), (1, 1), (1, 0), (0, 0)))
    # two floating shelves with a LED strip under the front edge
    shelves = (1.48, 2.02)
    for sy in shelves:
        b.box("floating shelves", m_shelf, (-nh + 0.02, sy, bz), (nh - 0.02, sy + 0.04, bz + 0.25))
        b.box("shelf LED strip", m_led, (-nh + 0.05, sy - 0.006, bz + 0.215), (nh - 0.05, sy, bz + 0.235))
    decor_on_shelves(b, [sy + 0.04 for sy in shelves], bz + 0.125)
    parts = b.parts()
    off = G.centred(parts)
    surfaces = []
    for name, x0, x1 in (("niche-worktop-west", -nh + 0.02, -sx - 0.03), ("niche-worktop-east", sx + 0.03, nh - 0.02)):
        surfaces.append(surface(name, f"Niche worktop, {name.split('-')[-1]} of the sink", y1 + off[1],
                                x0 + off[0], x1 + off[0], ZB + 0.03 + off[2], ZD + off[2]))
    return parts, surfaces, off


def surface(sid, label, y, x0, x1, z0, z1):
    """A level surface x0..x1, z0..z1 at height y. Its frame origin is the surface's centre and its bounds are
    symmetric round it: Sage's attachTo puts an item at the origin (2026-11-08 rehearsal: an off-centre origin made
    it refuse the island ends)."""
    cx, cz, hx, hz = (x0 + x1) / 2, (z0 + z1) / 2, (x1 - x0) / 2, (z1 - z0) / 2
    return {"allowedSides": ["above"], "bounds": {"minimumX": round(-hx, 4), "maximumX": round(hx, 4),
                                                   "minimumZ": round(-hz, 4), "maximumZ": round(hz, 4)},
            "evidenceStatus": "derived", "label": label,
            "localFrame": {"normal": {"x": 0, "y": 1, "z": 0},
                           "origin": {"x": round(cx, 4), "y": round(y, 4), "z": round(cz, 4)},
                           "xAxis": {"x": 1, "y": 0, "z": 0}, "zAxis": {"x": 0, "y": 0, "z": 1}},
            "surfaceId": sid}


def pot_profile(r_bottom, r_top, height, wall=0.006, lip=0.004, belly=0.0, neck=None):
    """Outside up, over the lip, inside down: a lathe profile for an open vessel."""
    ys = np.linspace(0, height, 12)
    outer = []
    for y in ys:
        t = y / height
        r = r_bottom + (r_top - r_bottom) * t + belly * math.sin(math.pi * t)
        if neck:
            r = r * (1 - neck * max(0, t - 0.7) / 0.3)
        outer.append((max(r, 0.005), y))
    inner = [(max(r - wall, 0.002), y) for r, y in outer[::-1]][:-1] + [(0.0001, wall)]
    return [(0.0001, 0)] + outer + [(outer[-1][0] - lip * 0.2, height + lip * 0.3)] + inner


def decor_on_shelves(b, tops, zc):
    """The five downloaded vases (SusanKing, CC BY), scaled 0.005 (0.22-0.25 m tall, the widest 0.24 m on a 0.25 m
    shelf): three on the lower shelf, two on the upper."""
    lo, hi = tops
    vases = {p.material.name: p for p in dl("vases-five")}
    spots = {"vase1": (-0.34, lo), "vase4": (0.05, lo), "vase3": (0.38, lo), "vase5": (-0.22, hi), "vase2": (0.30, hi)}
    for name, (x, y) in spots.items():
        v = vases[name]
        c = (v.P.min(0) + v.P.max(0)) / 2
        P = (v.P - [c[0], v.P[:, 1].min(), c[2]]) * 0.005 + [x, y, zc]
        mat = v.material
        if mat.image is not None:
            mat.image = mat.image.convert("RGBA" if mat.blend else "RGB").resize((512, 512))
        mat.emissive = None
        b.add(f"shelf {name[:4]} {name[4:]}", mat, P, v.I, v.N, v.U)   # one role per vase: its own texture


# --------------------------------------------------------------------------------------------- the island
ISL_L, ISL_D_TOP, BODY_D, OVERHANG = 3.5, 1.43, 1.0, 0.40


def island_model():
    b = G.Builder()
    m_front, m_flute = mprimer("island fronts"), mprimer("island fluted panel")
    m_top = M("island top", WORKTOP, 0.35)
    m_carc = M("cabinet carcass", CARCASS, 0.8)
    m_plinth = M("plinth", PLINTH, 0.8)
    m_handle = M("handles", STEEL, 0.35, 0.9)
    m_led = M("toe-kick LED strip", LED, 0.3)
    m_cook = M("cooktop", "#ffffff", 0.08, 0.2, image=cooktop_texture())
    m_vent = M("downdraft vent", "#1a1a1c", 0.4, 0.6)
    half = ISL_L / 2
    wt = 0.04                                   # waterfall slab thickness
    top_y0, top_y1 = 0.91, 0.95
    zs, zn = -0.72, -0.72 + ISL_D_TOP           # top's south (cooking side) and north (seating side) edges
    body_s, body_n = zs + 0.03, zs + 0.03 + BODY_D  # fronts sit 1 cm behind the top's edge
    b.box("island top", m_top, (-half, top_y0, zs), (half, top_y1, zn))
    for x0, x1 in ((-half, -half + wt), (half - wt, half)):
        b.box("island top", m_top, (x0, 0, zs), (x1, top_y0, zn))
    bx0, bx1 = -half + wt, half - wt
    b.box("cabinet carcass", m_carc, (bx0, PLINTH_H, body_s + DOOR_T), (bx1, top_y0, body_n - 0.02))
    b.box("plinth", m_plinth, (bx0 + 0.05, 0, body_s + 0.07), (bx1 - 0.05, PLINTH_H, body_n - 0.07))
    # drawers facing the run: 4 bays x 2 drawers
    bays = np.linspace(bx0, bx1, 5)
    for x0, x1 in zip(bays[:-1], bays[1:]):
        for y0, y1 in ((PLINTH_H, 0.50), (0.50, top_y0 - 0.01)):
            b.box("island fronts", m_front, (x0 + GAP / 2, y0 + GAP / 2, body_s), (x1 - GAP / 2, y1 - GAP / 2,
                                                                                  body_s + DOOR_T))
            cx = (x0 + x1) / 2
            b.box("handles", m_handle, (cx - 0.2, y1 - 0.07, body_s - 0.025), (cx + 0.2, y1 - 0.058, body_s))
    # the seating side: a fluted panel of half-round reeds 4 cm apart
    zf = body_n - 0.02
    reeds = np.arange(bx0 + 0.02, bx1 - 0.01, 0.04)
    for x in reeds:
        pts = []
        for k in range(9):
            a = math.pi * k / 8
            pts.append((x - 0.02 * math.cos(a), zf + 0.016 * math.sin(a)))
        for (xa, za), (xb, zb) in zip(pts[:-1], pts[1:]):
            n = np.array([zb - za, 0, -(xb - xa)])
            n = -n / np.linalg.norm(n)
            b.quad("island fluted panel", m_flute, [(xa, PLINTH_H, za), (xb, PLINTH_H, zb), (xb, top_y0, zb),
                                                    (xa, top_y0, za)], tuple(n))
    # cooktop and downdraft vent, centred
    b.quad("cooktop", m_cook, [(-0.39, top_y1 + 0.003, -0.12), (0.39, top_y1 + 0.003, -0.12),
                               (0.39, top_y1 + 0.003, -0.62), (-0.39, top_y1 + 0.003, -0.62)], (0, 1, 0))
    b.box("cooktop", M("cooktop edge", "#2a2a2d", 0.3, 0.5), (-0.392, top_y1, -0.622), (0.392, top_y1 + 0.003,
                                                                                         -0.118), faces=("+x", "-x", "+z", "-z"))
    b.box("downdraft vent", m_vent, (-0.39, top_y1, -0.085), (0.39, top_y1 + 0.004, -0.03))
    # toe-kick LED: a strip round the base, lens facing down
    ly0, ly1 = PLINTH_H - 0.006, PLINTH_H
    for lo, hi in (((bx0 + 0.05, ly0, body_s + 0.035), (bx1 - 0.05, ly1, body_s + 0.055)),
                   ((bx0 + 0.05, ly0, body_n - 0.055), (bx1 - 0.05, ly1, body_n - 0.035))):
        b.box("toe-kick LED strip", m_led, lo, hi)
    parts = b.parts()
    off = G.centred(parts)
    y = top_y1 + off[1]
    e = 0.05
    surfaces = [surface("island-top-west", "Island top, west of the cooktop", y, -half + e + off[0],
                        -0.45 + off[0], zs + e + off[2], zn - e + off[2]),
                surface("island-top-east", "Island top, east of the cooktop", y, 0.45 + off[0], half - e + off[0],
                        zs + e + off[2], zn - e + off[2]),
                surface("island-top-middle", "Island top, between the vent and the seats", y, -0.45 + off[0],
                        0.45 + off[0], 0.0 + off[2], zn - e + off[2])]
    # Footprint: the body and the two waterfall ends, so stools can tuck under the overhang.
    fp = [[(-half, zs), (half, zs), (half, body_n), (-half, body_n)],
          [(-half, body_n), (-half + wt, body_n), (-half + wt, zn), (-half, zn)],
          [(half - wt, body_n), (half, body_n), (half, zn), (half - wt, zn)]]
    fp = [[(round(x + off[0], 4), round(z + off[2], 4)) for x, z in poly] for poly in fp]
    return parts, surfaces, fp, off


# --------------------------------------------------------------------------------------------- art and neon
def canvas_model():
    b = G.Builder()
    W, H, D = 1.8, 1.2, 0.035
    art = abstract_art()
    art.save(HERE / "build" / "abstract-canvas-art.jpg", quality=90)
    m_art = M("artwork", "#ffffff", 0.9, image=art)
    b.quad("artwork", m_art, [(-W / 2, -H / 2, D), (W / 2, -H / 2, D), (W / 2, H / 2, D), (-W / 2, H / 2, D)],
           (0, 0, 1))
    b.box("canvas edge", M("canvas edge", "#e6dccb", 0.9), (-W / 2, -H / 2, 0), (W / 2, H / 2, D),
          faces=("+x", "-x", "+y", "-y"))
    m_frame = M("frame", "#5b3b26", 0.55)
    g, f = 0.012, 0.02           # float gap and frame width
    X, Y = W / 2 + g, H / 2 + g
    for lo, hi in (((-X - f, -Y - f, 0), (X + f, -Y, D + 0.01)), ((-X - f, Y, 0), (X + f, Y + f, D + 0.01)),
                   ((-X - f, -Y, 0), (-X, Y, D + 0.01)), ((X, -Y, 0), (X + f, Y, D + 0.01))):
        b.box("frame", m_frame, lo, hi)
    b.box("frame", M("frame back", "#1e1c1a", 0.9), (-X, -Y, 0), (X, Y, 0.004), faces=("+z",))
    parts = b.parts()
    G.centred(parts)   # centred bounds: the back is the -Z face
    return parts


NEON_TEXT = "Gainzzz"
NEON_FONT = "C:/Windows/Fonts/LHANDW.TTF"


def neon_model():
    b = G.Builder()
    W, H = 1.40, 0.465
    rgba, glow = neon_images(NEON_TEXT, NEON_FONT)
    rgba.save(HERE / "build" / "neon-letters.png")
    m_tubes = S.Material("neon tubes", color=[1, 1, 1, 1], image=rgba, emissive=[1.0, 0.86, 0.66],
                         emissive_image=glow, roughness=0.3, blend=True)   # blend: written as PNG, then MASK
    z = 0.032
    b.quad("neon tubes", m_tubes, [(-W / 2, -H / 2, z), (W / 2, -H / 2, z), (W / 2, H / 2, z), (-W / 2, H / 2, z)],
           (0, 0, 1))
    m_acr = M("acrylic panel", "#f4f1ea", 0.1, blend=True)
    b.box("acrylic panel", m_acr, (-W / 2 - 0.03, -H / 2 - 0.03, 0.02), (W / 2 + 0.03, H / 2 + 0.03, 0.026))
    m_brass = M("standoffs", "#b08d57", 0.3, 0.9)
    for sx in (-W / 2 + 0.02, W / 2 - 0.02):
        for sy in (-H / 2, H / 2):
            b.tube("standoffs", m_brass, [(sx, sy, 0.0), (sx, sy, 0.034)], 0.012, sides=16)
    parts = b.parts()
    G.centred(parts)
    return parts


# --------------------------------------------------------------------------------------------- counter styling
def fruit_bowl_model():
    """The download as it is (vertexgrocer, CC BY): a wooden oval bowl with its fruit resting in it."""
    parts = dl("fruit-coll")
    for p in parts:
        p.name = "bowl" if p.material.name == "bowl" else p.material.name
        p.material.emissive = None
    G.centred(parts)
    return parts


def board_model():
    """The download (itsjustcavan, CC BY) at 0.85: a 0.41 m board, its wine bottle 0.32 m tall."""
    parts = dl("board-charc")
    names = {"Material.002": "wine bottle", "Material.003": "wine bottle", "Material.004": "wine bottle",
             "red_wine": "wine", "glass": "glasses", "bread": "bread", "baked_FLAT": "board"}
    for p in parts:
        p.name = names.get(p.material.name, "cheese and fruit")
        p.material.emissive = None
        if p.material.name == "Material.004":     # the bottle's picture label: a plain cream one instead
            p.name, p.material, p.U = "wine label", M("wine label", "#e8dcc4", 0.8), None
    S.transform(parts, scale=0.85)
    G.centred(parts)
    return parts


def mugs_model():
    """Three of the download (The Lister, CC BY) at 0.095 m tall, in a row front to back with the handles turned a
    little apart (checked below: no mug touches another)."""
    src = dl("mug-lister")[0]
    # plain dark glaze: the download's texture prints a slogan we keep off the video
    glaze = M("mugs", "#22272e", 0.35)
    lo, hi = src.P.min(0), src.P.max(0)
    s_ = 0.095 / (hi[1] - lo[1])
    P0 = (src.P - [0, lo[1], 0]) * s_
    body = P0[np.abs(P0[:, 2]) > 0.6 * np.abs(P0[:, 2]).max()]        # the cup wall, not the thin handle
    cx = (body[:, 0].min() + body[:, 0].max()) / 2
    P0[:, 0] -= cx
    P0[:, 2] -= (P0[:, 2].min() + P0[:, 2].max()) / 2
    radius = np.hypot(body[:, 0] - cx, body[:, 2]).max()
    out, placed = [], []
    for k, (x, z, turn) in enumerate(((-0.02, -0.11, 20), (0.015, 0.0, -15), (-0.01, 0.11, 35))):
        t = np.radians(turn)
        R = np.array([[np.cos(t), 0, np.sin(t)], [0, 1, 0], [-np.sin(t), 0, np.cos(t)]])
        P = P0 @ R.T + [x, 0, z]
        N = None if src.N is None else src.N @ R.T
        for Q, cxz in placed:   # no point of this mug inside another's cup (radius) or vice versa
            assert np.hypot(P[:, 0] - cxz[0], P[:, 2] - cxz[1]).min() > radius + 0.002, k
            assert np.hypot(Q[:, 0] - x, Q[:, 2] - z).min() > radius + 0.002, k
        placed.append((P, (x, z)))
        out.append(S.Part("mugs", P, N, None, src.I, glaze))
    G.centred(out)
    return out


def dl(key):
    return S.Source(HERE / "dl" / key / "model.glb").parts()


def fridge_model():
    parts = dl("fridge-smok")
    for p in parts:
        p.name = p.material.name.replace("Fridge_", "fridge ").lower()
        p.material.emissive = None
        p.material.blend = False
    G.centred(parts)
    return parts


def stool_model():
    parts = [p for p in dl("stool-dima") if p.material.name != "Plane_lp"]
    seat = [p for p in parts if p.material.name == "Sedalo_LP"][0]
    floor = min(p.P[:, 1].min() for p in parts)
    near = seat.P[(np.abs(seat.P[:, 0]) < 0.08) & (seat.P[:, 2] > -0.05) & (seat.P[:, 2] < 0.25)]
    seat_top = near[:, 1].max()
    scale = 0.66 / (seat_top - floor)
    names = {"Sedalo_LP": "seat", "Metal_LP": "foot ring", "Nogice_LP": "legs"}
    for p in parts:
        p.name = names.get(p.material.name, p.material.name)
        p.material.blend = False
    S.transform(parts, scale=scale)
    G.centred(parts)
    print(f"  stool: seat top {seat_top:.3f} of floor {floor:.3f} -> scale {scale:.4f}")
    return parts


PENDANT_SHADE_W, PENDANT_H = 0.40, 1.40


def pendant_model():
    parts = dl("pend-landshapes")
    axis = np.array([-0.005, 0.164])    # the pendant with the longest rod
    mine = []
    for p in parts:
        c = (p.P.min(0) + p.P.max(0)) / 2
        if np.hypot(c[0] - axis[0], c[2] - axis[1]) < 0.03:
            mine.append(p)
    shade = [p for p in mine if p.material.name == "Plastic"]
    glow = [p for p in mine if p.material.name == "Emission"]
    shade_top = max(p.P[:, 1].max() for p in shade)
    hardware = [p for p in mine if p.material.name == "Metal" and p.P[:, 1].min() > shade_top - 0.05
                and p.P[:, 1].max() < shade_top + 0.03]
    s = PENDANT_SHADE_W / max(p.P[:, 0].max() - p.P[:, 0].min() for p in shade)
    keep = shade + glow + hardware
    out = []
    lens_parts = []
    for p in keep:
        q = S.Part(p.name, (p.P - [axis[0], 0, axis[1]]) * s, p.N, p.U, p.I, p.material)
        if p.material.name in ("Plastic", "Emission"):
            lens_parts.append(q)
        else:
            q.name = "hardware"
            q.material = M("hardware", "#1d1c1b", 0.35, 0.8)
            out.append(q)
    lens = G.S.Part("lamp lens", np.vstack([q.P for q in lens_parts]), None, None,
                    np.concatenate([q.I + sum(len(r.P) for r in lens_parts[:k]) for k, q in enumerate(lens_parts)]),
                    M("lamp lens", "#f3eee6", 0.25))
    out.append(lens)
    lo = min(q.P[:, 1].min() for q in out)
    top = max(q.P[:, 1].max() for q in out)
    # a new rod and canopy up to the ceiling
    b = G.Builder()
    m_rod = M("rod and canopy", "#1d1c1b", 0.35, 0.8)
    rod_top = lo + PENDANT_H - 0.03
    b.cylinder("rod and canopy", m_rod, (0, 0), 0.006, top - 0.01, rod_top)
    b.lathe("rod and canopy", m_rod, [(0.0001, rod_top), (0.06, rod_top), (0.06, rod_top + 0.03),
                                      (0.0001, rod_top + 0.03)], segments=40)
    out += b.parts()
    G.centred(out)
    print(f"  pendant: scale {s:.3f}, shade {PENDANT_SHADE_W} m, height "
          f"{max(q.P[:, 1].max() for q in out):.3f}")
    return out


def terracotta_pot(b, r_top, height, rim=0.025):
    m = M("terracotta pot", "#b4643e", 0.85)
    r_bot = r_top * 0.72
    prof = [(0.0001, 0), (r_bot, 0), (r_top - rim * 0.4, height - rim), (r_top, height - rim),
            (r_top, height), (r_top - 0.012, height), (r_top - 0.014, height - rim), (r_bot - 0.012, 0.03),
            (0.0001, 0.03)]
    b.lathe("terracotta pot", m, prof, segments=56, cap_bottom=False)
    b.disc("soil", M("soil", "#3a2a1e", 0.95), (0, height - 0.035, 0), r_top - 0.016)
    return height - 0.035


def plant_in_pot(key, target_h, pot_r, pot_h, sink=0.02, max_spread=None):
    """The download's plant scaled to TARGET_H overall and, with POT_R, set in a terracotta pot of our own."""
    parts = dl(key)
    for p in parts:
        p.material.emissive = None
    lo = np.min([p.P.min(0) for p in parts], axis=0)
    hi = np.max([p.P.max(0) for p in parts], axis=0)
    s = (target_h - pot_h + (sink if pot_r else 0)) / (hi[1] - lo[1])
    if max_spread:
        s = min(s, max_spread / max(hi[0] - lo[0], hi[2] - lo[2]))
    cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
    b = G.Builder()
    soil_y = terracotta_pot(b, pot_r, pot_h) if pot_r else 0.0
    for k, p in enumerate(parts):
        p.P = (p.P - [cx, lo[1], cz]) * s + [0, soil_y - (sink if pot_r else 0), 0]
        p.name = f"plant {k + 1}" if len(parts) > 1 else "plant"
    out = parts + (b.parts() if pot_r else [])
    G.centred(out)
    print(f"  {key}: scale {s:.4f}, height {max(q.P[:, 1].max() for q in out):.3f}, "
          f"spread {max(q.P[:, 0].max() for q in out) * 2:.2f}")
    return out


def olive_model():
    """The olive (massive-graphisme, CC BY) centred on its trunk, scaled so its canopy is 1.2 m across, in a 0.5 m
    terracotta pot."""
    parts = dl("olive")
    for p in parts:
        p.material.emissive = None
        if p.material.image is not None:
            p.material.image = p.material.image.convert("RGBA" if p.material.blend else "RGB").resize((1024, 1024))
    bark = np.vstack([p.P for p in parts if p.material.name == "olive-tree-bark"])
    y0 = min(p.P[:, 1].min() for p in parts)
    foot = bark[bark[:, 1] < y0 + 0.25]
    cx, cz = foot[:, 0].mean(), foot[:, 2].mean()
    reach = max(np.hypot(p.P[:, 0] - cx, p.P[:, 2] - cz).max() for p in parts)
    s_ = 0.7 / reach
    b = G.Builder()
    soil = terracotta_pot(b, 0.25, 0.45)
    for k, p in enumerate(parts):
        p.P = (p.P - [cx, y0, cz]) * s_ + [0, soil - 0.03, 0]
        p.name = "olive leaves" if p.material.name == "olive-leaves" else "olive trunk"
    out = parts + b.parts()
    G.centred(out)
    print(f"  olive: scale {s_:.4f}, height {max(q.P[:, 1].max() for q in out):.3f}, canopy {2 * reach * s_:.2f}")
    return out


def basil_model():
    """Two of the basil download (ellievaskali, CC BY; plant and pot), 0.3 m tall, side by side front to back."""
    src = dl("basil")[0]
    src.material.emissive = None
    src.material.image = src.material.image.convert("RGB").resize((1024, 1024))
    lo, hi = src.P.min(0), src.P.max(0)
    P0 = src.P - [(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2]
    out = []
    for x, z, turn, sc in ((0.0, -0.105, 0, 1.0), (0.01, 0.105, 70, 0.92)):
        t = np.radians(turn)
        R = np.array([[np.cos(t), 0, np.sin(t)], [0, 1, 0], [-np.sin(t), 0, np.cos(t)]])
        P = (P0 * sc) @ R.T + [x, 0, z]
        out.append(S.Part("basil", P, None if src.N is None else src.N @ R.T, src.U, src.I, src.material))
    G.centred(out)
    return out


# --------------------------------------------------------------------------------------------- catalog entries
FOLDER = "generated/industrial_assets/private_gym/kitchenette"
LICENSE = "CC BY 4.0 (http://creativecommons.org/licenses/by/4.0/)"
DOWNLOADS = {
    "fridge-smok": ("French Door Refrigerator - Stainless", "Smokahontas", "https://sketchfab.com/Smokahontas",
                    "https://sketchfab.com/3d-models/ebe62ed6dd9b446a9c9b7d7d6a8086e7"),
    "stool-dima": ("Dima upholstered barstool", "Andriano Milanovic (andriano82)", "https://sketchfab.com/andriano82",
                   "https://sketchfab.com/3d-models/2be0e4efd95d4b9b9740eeeaae318af6"),
    "pend-landshapes": ("Landshapes by Daniel Arsham", "eltayerkebulan", "https://sketchfab.com/eltayerkebulan",
                        "https://sketchfab.com/3d-models/3dc08c1d6d664a8891b699237e0fa878"),
    "olive": ("Old olive tree", "massive-graphisme", "https://sketchfab.com/massive-graphisme",
              "https://sketchfab.com/3d-models/6328df8a0f214143a880a72b86db2ab4"),
    "fruit-coll": ("Fruit bowl collection", "vertexgrocer", "https://sketchfab.com/vertexgrocer",
                   "https://sketchfab.com/3d-models/d89f6311cb0c4c37b0bf9cdd1e5abcb3"),
    "mug-lister": ("Coffee Mug", "The Lister", "https://sketchfab.com/MortemNightshade",
                   "https://sketchfab.com/3d-models/6c95897de04143aeb5c75b7630707d27"),
    "board-charc": ("Charcuterie board for OnCyber spaces", "itsjustcavan", "https://sketchfab.com/itsjustcavan",
                    "https://sketchfab.com/3d-models/be21bdac1e394d9d8a81fc9f50dfa856"),
    "vases-five": ("Five decorative vases", "SusanKing", "https://sketchfab.com/krolzuzannapl",
                   "https://sketchfab.com/3d-models/bf3f4a94da6f4cc1961f777349acb1b4"),
    "basil": ("Basil plant", "ellievaskali", "https://sketchfab.com/ellievaskali",
              "https://sketchfab.com/3d-models/66923d135a1c4cb7814358cbdb80fda6"),
}


def credit(key):
    title, author, author_url, url = DOWNLOADS[key]
    return f"Model from \"{title}\" by {author} ({author_url}), {LICENSE}, {url}."


LANTERN = "light-lantern-warm"
ASSETS = {  # id -> (stem, display name, builder, category, tags, description, download key or None, change note,
            #        lit roles {role: finish}, mask roles)
    "asset-gym-kitchen-modern-run": (
        "modern-kitchen-run", "Modern kitchen run - floor to ceiling", run_model, "Building Elements",
        ["kitchen", "kitchenette", "cabinets", "tall cabinets", "pantry", "built-in oven", "coffee machine", "sink",
         "backsplash", "zellige", "open shelves", "floating shelves", "modern"],
        "Modern kitchen run, 4.555 m long, 0.74 m deep, 3.18 m tall (floor to a 3.2 m ceiling). Stand it against a "
        "wall with its back (-Z) to the wall and leave 6 mm. Tall cabinets either side (one column holds a built-in "
        "oven, combi microwave and coffee machine) and a 1.2 m niche in the middle: two base cabinets under a "
        "worktop with an undermount sink and a gooseneck faucet, hand-made zellige tile up to the ceiling, and two "
        "floating shelves styled with five decorative vases, each shelf with a LED strip under its front edge. Parts to finish with "
        "set_component_materials: tall cabinet doors (also the end panels), base cabinet fronts, worktop, floating "
        "shelves, handles, faucet. The shelf LED strips are lamps: give them a Lights finish to light them. The "
        "worktop either side of the sink is a support surface for small items.", None,
        "Our own model (InspectorPro), following the layout of the Kitchen Assembly it replaces. The shelf vases: "
        + credit("vases-five") + " Changed: scaled to 0.22-0.25 m, textures reduced to 512 px.", {}, ()),
    "asset-gym-kitchen-waterfall-island": (
        "waterfall-island", "Waterfall kitchen island - with cooktop", island_model, "Building Elements",
        ["kitchen", "kitchenette", "island", "kitchen island", "waterfall", "cooktop", "induction", "downdraft",
         "breakfast bar", "seating", "fluted", "modern"],
        "Waterfall kitchen island, 3.5 m long, 1.43 m deep, 0.95 m worktop height: a stone-look top that runs down "
        "both ends to the floor, two rows of drawers on the cooking side (-Z), a centred induction cooktop with a "
        "downdraft extractor (no hood), and a 0.40 m overhang on the seating side (+Z) over a fluted panel, for "
        "counter stools (seat about 0.65 m) tucked under it. The footprint is the body and the two ends, so stools "
        "can stand under the overhang. Parts to finish with set_component_materials: island top (top and waterfall "
        "ends), island fronts, island fluted panel, handles. The toe-kick LED strip round its base is a lamp: give "
        "it a Lights finish to make the island float on a glow. The top beside and behind the cooktop is a support "
        "surface for small items.", None, "Our own model (InspectorPro).", {}, ()),
    "asset-gym-kitchen-fridge-french-door": (
        "french-door-fridge", "French door refrigerator - stainless", fridge_model, "Building Elements",
        ["fridge", "refrigerator", "french door", "stainless", "appliance", "kitchen", "freezer", "ice dispenser"],
        "French door refrigerator in stainless steel: two doors over two freezer drawers, ice and water dispenser, "
        "0.96 m wide, 1.82 m tall, 0.55 m deep. Front +Z; stand it with its back to a wall.", "fridge-smok",
        "Changed: textures reduced to 1024 px.", {}, ()),
    "asset-gym-kitchen-counter-stool-dima": (
        "dima-counter-stool", "Dima counter stool - mustard", stool_model, "Furniture",
        ["stool", "counter stool", "bar stool", "barstool", "upholstered", "mustard", "wood legs", "kitchen island",
         "seating"],
        "Dima counter stool: a mustard upholstered seat with a low back on four wooden legs with a black foot ring, "
        "seat 0.66 m high for a 0.9-1.0 m counter. Its back is on the -Z side: turn it so its front (+Z) faces the "
        "counter, about 0.65 m apart.", "stool-dima",
        "Changed: scaled to a 0.66 m seat (counter height), the ground plane left out, textures reduced to 1024 px.",
        {}, ()),
    "asset-gym-kitchen-pendant-landshapes": (
        "landshapes-pendant", "Landshapes pendant - draped glass", pendant_model, "Facilities",
        ["pendant", "pendant light", "ceiling light", "hanging", "glass", "sculptural", "kitchen island", "island",
         "dining", "indoor", "lighting"],
        "Landshapes pendant: a sculptural sheet of white glass draped over a glowing sphere, 0.40 m across, on a "
        "black rod. Hang it from a ceiling over a kitchen island or a table, usually 2 or 3 in a row about 0.8-1 m "
        "apart: its top meets the ceiling, so from a 3.2 m ceiling its shade hangs down to 1.80 m. It comes lit "
        "(Lantern warm).", "pend-landshapes",
        "Changed: one pendant of the set of three, scaled to a 0.40 m shade, a new rod and canopy for a 1.40 m drop, "
        "the glass and the sphere made the lamp-lens part.", {"lamp lens": LANTERN}, ()),
    "asset-gym-kitchen-abstract-canvas": (
        "abstract-canvas-warm", "Abstract canvas - warm tones", canvas_model, "Facilities",
        ["art", "artwork", "canvas", "painting", "abstract", "wall art", "framed", "wall-mounted", "decor"],
        "Abstract canvas in warm tones (terracotta arches, an ochre sun, an olive leaf, blush and a charcoal line on "
        "raw linen), 1.8 x 1.2 m in a slim walnut float frame. Hang it on a wall with its back (-Z) against it, "
        "centre usually 1.5-1.6 m up. Light it with an accent spot.", None,
        "Our own artwork and model (InspectorPro).", {}, ()),
    "asset-gym-kitchen-neon-gainzzz": (
        "neon-gainzzz", "Neon sign - Gainzzz", neon_model, "Facilities",
        ["neon", "sign", "neon sign", "script", "gainz", "wall-mounted", "kitchen", "cafe", "lounge", "decor", "lighting"],
        f"Neon sign reading \"{NEON_TEXT}\" in warm white script on a clear acrylic panel with brass standoffs, "
        "1.46 x 0.53 m. Mount it on a wall with its back (-Z) against it. Its tubes glow by themselves.", None,
        "Our own model (InspectorPro).", {}, ("neon tubes",)),
    "asset-gym-kitchen-fruit-bowl": (
        "fruit-bowl", "Fruit bowl - wooden", fruit_bowl_model, "Facilities",
        ["fruit bowl", "fruit", "bowl", "wooden", "kitchen", "counter", "decor", "styling"],
        "An oval wooden bowl, 0.52 x 0.37 m, with apples, pears, plums, a lemon, a lime, a banana, a small pineapple "
        "and a pumpkin. Put it on a counter or an island (a surface attachment on its top).", "fruit-coll",
        "Changed: the materials' emission removed.", {}, ()),
    "asset-gym-kitchen-serving-board": (
        "serving-board-set", "Charcuterie board - with wine", board_model, "Facilities",
        ["charcuterie", "cheese board", "serving board", "bread", "wine", "glasses", "kitchen", "counter", "decor",
         "styling"],
        "A wooden charcuterie board with cheese, fruit and bread, a bottle of red wine and two filled glasses, about "
        "0.4 x 0.41 m and 0.32 m tall. Put it on a counter or an island (a surface attachment on its top).",
        "board-charc", "Changed: scaled to 0.85, a plain cream bottle label, textures reduced to 1024 px.", {}, ()),
    "asset-gym-kitchen-mugs": (
        "ceramic-mugs", "Ceramic mugs - set of 3", mugs_model, "Facilities",
        ["mugs", "cups", "coffee", "ceramic", "kitchen", "counter", "decor", "styling"],
        "Three plain dark-glazed ceramic coffee mugs in a row, about 0.16 x 0.31 m. Put them on a worktop near the coffee "
        "machine (a surface attachment).", "mug-lister",
        "Changed: three copies, scaled to 0.095 m tall and set in a row, a plain dark glaze instead of the printed "
        "texture.", {}, ()),
}
if (HERE / "dl" / "olive" / "model.glb").exists():
    ASSETS["asset-gym-kitchen-olive-tree"] = (
        "olive-tree-terracotta", "Olive tree in terracotta pot", olive_model, "Facilities",
        ["plant", "tree", "olive tree", "potted plant", "indoor plant", "terracotta", "greenery", "decor"],
        "An old olive tree with a gnarled trunk and a 1.4 m canopy in a 0.5 m terracotta pot, about 1.35 m tall. "
        "Stand it in a corner or beside a wall, clear of walking routes.", "olive",
        "Changed: scaled to a 1.4 m canopy and set in a terracotta pot of our own, textures reduced to 1024 px.",
        {}, ("olive leaves",))
if (HERE / "dl" / "basil" / "model.glb").exists():
    ASSETS["asset-gym-kitchen-basil-pot"] = (
        "basil-pots", "Basil pots - pair", basil_model, "Facilities",
        ["plant", "herb", "basil", "herbs", "potted plant", "kitchen", "counter", "decor"],
        "Two pots of fresh basil, 0.3 m tall, side by side front to back (about 0.19 x 0.4 m). Put them on a "
        "worktop, a sill or an island (a surface attachment).", "basil",
        "Changed: two copies set side by side, textures reduced to 1024 px.", {}, ())


def built(only=None):
    out = {}
    (HERE / "build").mkdir(exist_ok=True)
    for asset_id, (stem, name, builder, *_rest) in ASSETS.items():
        if only is not None and asset_id not in only:
            continue
        print(stem, flush=True)
        result = builder()
        surfaces, footprint = [], None
        if builder is run_model:
            parts, surfaces, _ = result
        elif builder is island_model:
            parts, surfaces, footprint, _ = result
        else:
            parts = result
        lit, mask = ASSETS[asset_id][8], ASSETS[asset_id][9]
        payload = G.write_glb(stem, parts, GEN, finishes=lit, mask_roles=mask,
                              max_texture=2048 if builder in (run_model, canvas_model) else 1024)
        lo = np.min([p.P.min(0) for p in parts], axis=0)
        hi = np.max([p.P.max(0) for p in parts], axis=0)
        assert abs(lo[1]) < 1e-4 and abs(lo[0] + hi[0]) < 2e-3 and abs(lo[2] + hi[2]) < 2e-3, (asset_id, lo, hi)
        dims = {"width": round(float(hi[0] - lo[0]), 4), "depth": round(float(hi[2] - lo[2]), 4),
                "height": round(float(hi[1] - lo[1]), 4)}
        tris = int(sum(len(p.I) // 3 for p in parts))
        out[asset_id] = {"payload": payload, "dims": dims, "triangles": tris, "surfaces": surfaces,
                         "footprint": footprint}
    return out


if __name__ == "__main__" and sys.argv[1] == "build":
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for asset_id, info in built().items():
        stem = ASSETS[asset_id][0]
        (out_dir / f"{stem}.glb").write_bytes(info["payload"])
        summary[asset_id] = {k: v for k, v in info.items() if k != "payload"} | {"stem": stem,
                                                                                 "bytes": len(info["payload"])}
        print(f"{stem:28} {info['triangles']:7} tris {len(info['payload']) // 1024:6} KB  {info['dims']}")
    (out_dir / "models.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")

if __name__ == "__main__" and sys.argv[1] == "install":
    # python kitchen_models.py install BACKUP_DIR [ROOT]
    import kitchen_install_part
    kitchen_install_part.install(sys.modules[__name__], Path(sys.argv[2]),
                                 *([Path(sys.argv[3])] if len(sys.argv) > 3 else []))

if __name__ == "__main__" and sys.argv[1] == "update":
    # python kitchen_models.py update BACKUP_DIR ASSET_ID...
    import kitchen_install_part
    # --ignore LAYOUT_ID (repeatable): my own scratch copies, archived after the update
    ids = [a for a in sys.argv[3:] if a.startswith("asset-")]
    ignore = [sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--ignore"]
    kitchen_install_part.update(sys.modules[__name__], ids, Path(sys.argv[2]), ignore_layouts=ignore)
