from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


OUT_DIR = Path(__file__).resolve().parent
PNG_PATH = OUT_DIR / "ai_judge_limitations_slide.png"
GIF_PATH = OUT_DIR / "ai_judge_limitations_slide_animated.gif"
OUT_PATH = PNG_PATH

W, H = 1080, 1350
SCALE = 3
FRAME_COUNT = 28
FRAME_DURATION_MS = 70


COLORS = {
    "bg": "#F6FAFD",
    "grid": "#D9ECF5",
    "ink": "#162231",
    "muted": "#5E6E7D",
    "blue": "#2AA7E8",
    "blue_dark": "#1976BD",
    "teal": "#1E9B7B",
    "yellow": "#F2B90B",
    "red": "#DF4F68",
    "slate": "#6B7F92",
    "card": "#FFFFFF",
    "card_line": "#D2E0EA",
}


def rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.strip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def rgba(hex_color: str, alpha: int) -> tuple[int, int, int, int]:
    r, g, b = rgb(hex_color)
    return r, g, b, alpha


def tint(hex_color: str, amount: float = 0.14, base: str = "#FFFFFF") -> str:
    r, g, b = rgb(hex_color)
    br, bg, bb = rgb(base)
    return f"#{int(br + (r - br) * amount):02X}{int(bg + (g - bg) * amount):02X}{int(bb + (b - bb) * amount):02X}"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size * SCALE)
    return ImageFont.load_default()


F = {
    "brand": font(27, True),
    "eyebrow": font(19, True),
    "title": font(52, True),
    "subtitle": font(24, False),
    "body": font(22, False),
    "body_bold": font(22, True),
    "small": font(17, False),
    "small_bold": font(17, True),
    "pill": font(16, True),
}


def measure(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = word if not line else f"{line} {word}"
        if measure(draw, candidate, fnt)[0] <= max_w:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    fnt: ImageFont.FreeTypeFont,
    fill: str,
    max_w: int,
    line_gap: int = 6,
    max_lines: int | None = None,
) -> int:
    x, y = xy
    lines = wrap_text(draw, text, fnt, max_w)
    if max_lines is not None:
        lines = lines[:max_lines]
    line_h = measure(draw, "Ag", fnt)[1] + line_gap * SCALE
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += line_h
    return y


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill: str, outline: str | None = None, width: int = 1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def line(
    draw: ImageDraw.ImageDraw,
    pts: Iterable[tuple[int, int]],
    fill: str,
    width: int = 3,
    dash: bool = False,
    dash_offset: float = 0,
):
    pts = list(pts)
    if not dash:
        draw.line(pts, fill=fill, width=width, joint="curve")
        return
    for a, b in zip(pts, pts[1:]):
        x1, y1 = a
        x2, y2 = b
        length = math.hypot(x2 - x1, y2 - y1)
        if length == 0:
            continue
        dash_len = 16 * SCALE
        gap = 11 * SCALE
        cycle = dash_len + gap
        first_start = -(dash_offset % cycle)
        steps = int((length - first_start) // cycle) + 2
        ux = (x2 - x1) / length
        uy = (y2 - y1) / length
        for i in range(steps):
            start = first_start + i * cycle
            end = start + dash_len
            if end <= 0 or start >= length:
                continue
            start = max(start, 0)
            end = min(end, length)
            draw.line(
                [
                    (int(x1 + ux * start), int(y1 + uy * start)),
                    (int(x1 + ux * end), int(y1 + uy * end)),
                ],
                fill=fill,
                width=width,
            )


def joint(draw: ImageDraw.ImageDraw, xy: tuple[int, int], fill: str, radius: int = 3):
    x, y = xy
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)


def add_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    accent: str,
    title: str,
    body: str,
    tag: str,
):
    x1, y1, x2, y2 = box
    rounded(draw, box, 28 * SCALE, COLORS["card"], COLORS["card_line"], 2 * SCALE)
    draw.rounded_rectangle((x1 + 18 * SCALE, y1 + 20 * SCALE, x1 + 52 * SCALE, y1 + 54 * SCALE), radius=17 * SCALE, fill=accent)
    draw.ellipse((x1 + 29 * SCALE, y1 + 31 * SCALE, x1 + 41 * SCALE, y1 + 43 * SCALE), fill=COLORS["card"])
    draw.text((x1 + 68 * SCALE, y1 + 23 * SCALE), title, font=F["body_bold"], fill=COLORS["ink"])
    draw_wrapped(draw, (x1 + 68 * SCALE, y1 + 63 * SCALE), body, F["small"], COLORS["muted"], x2 - x1 - 92 * SCALE, 4)
    pill_w = measure(draw, tag, F["pill"])[0] + 30 * SCALE
    rounded(draw, (x1 + 68 * SCALE, y2 - 42 * SCALE, x1 + 68 * SCALE + pill_w, y2 - 14 * SCALE), 14 * SCALE, tint(accent, 0.16), None)
    draw.text((x1 + 83 * SCALE, y2 - 37 * SCALE), tag, font=F["pill"], fill=accent)


def render_slide(dash_offset: float = 0) -> Image.Image:
    img = Image.new("RGB", (W * SCALE, H * SCALE), COLORS["bg"])
    draw = ImageDraw.Draw(img)

    # Background grid.
    for x in range(70 * SCALE, W * SCALE, 82 * SCALE):
        draw.line((x, 70 * SCALE, x, (H - 70) * SCALE), fill=COLORS["grid"], width=1 * SCALE)
    for y in range(82 * SCALE, H * SCALE, 82 * SCALE):
        draw.line((35 * SCALE, y, (W - 35) * SCALE, y), fill=COLORS["grid"], width=1 * SCALE)

    # Brand.
    icon = (45 * SCALE, 36 * SCALE, 82 * SCALE, 73 * SCALE)
    rounded(draw, icon, 10 * SCALE, COLORS["blue_dark"])
    draw.line((63 * SCALE, 45 * SCALE, 63 * SCALE, 65 * SCALE), fill=COLORS["card"], width=3 * SCALE)
    draw.line((53 * SCALE, 55 * SCALE, 73 * SCALE, 55 * SCALE), fill=COLORS["card"], width=3 * SCALE)
    draw.text((95 * SCALE, 42 * SCALE), "InspectorPro", font=F["brand"], fill=COLORS["ink"])
    rounded(draw, (760 * SCALE, 38 * SCALE, 1006 * SCALE, 72 * SCALE), 17 * SCALE, tint(COLORS["blue"], 0.08, COLORS["bg"]), COLORS["card_line"], 1 * SCALE)
    draw.text((797 * SCALE, 46 * SCALE), "AI evaluation boundaries", font=F["pill"], fill=COLORS["blue_dark"])

    # Header.
    draw.text((62 * SCALE, 116 * SCALE), "LIMITATIONS OF AI AS A JUDGE", font=F["eyebrow"], fill=COLORS["teal"])
    draw.text((62 * SCALE, 166 * SCALE), "AI Judges Are Useful Signals,", font=F["title"], fill=COLORS["ink"])
    draw.text((62 * SCALE, 225 * SCALE), "Not Final Verdicts", font=F["title"], fill=COLORS["ink"])
    draw_wrapped(
        draw,
        (64 * SCALE, 303 * SCALE),
        "An AI judge is another probabilistic model making a judgment. Its score needs boundaries, calibration, and human-reviewed ground truth.",
        F["subtitle"],
        COLORS["muted"],
        920 * SCALE,
        7,
    )

    # Central node and branches.
    center = (W // 2 * SCALE, 468 * SCALE)
    rounded(draw, (330 * SCALE, 400 * SCALE, 750 * SCALE, 482 * SCALE), 38 * SCALE, COLORS["card"], COLORS["card_line"], 2 * SCALE)
    draw.text((411 * SCALE, 420 * SCALE), "AI judge score", font=F["body_bold"], fill=COLORS["ink"])
    draw.text((386 * SCALE, 452 * SCALE), "helpful signal, not objective truth", font=F["small"], fill=COLORS["muted"])

    trunk_color = COLORS["blue"]
    branch_y = 570 * SCALE
    line(draw, [(540 * SCALE, 482 * SCALE), (540 * SCALE, branch_y)], trunk_color, 4 * SCALE, True, dash_offset)
    line(draw, [(170 * SCALE, branch_y), (910 * SCALE, branch_y)], trunk_color, 4 * SCALE, True, dash_offset)
    for x in [185, 540, 895]:
        line(draw, [(x * SCALE, branch_y), (x * SCALE, 625 * SCALE)], trunk_color, 4 * SCALE, True, dash_offset)
    for x in [360, 720]:
        line(draw, [(x * SCALE, branch_y), (x * SCALE, 852 * SCALE)], trunk_color, 4 * SCALE, True, dash_offset)
    for x in [185, 360, 540, 720, 895]:
        joint(draw, (x * SCALE, branch_y), trunk_color, 5 * SCALE)

    # Cards.
    add_card(
        draw,
        (55 * SCALE, 625 * SCALE, 335 * SCALE, 820 * SCALE),
        COLORS["blue"],
        "Inconsistency",
        "Same input, different prompt or run, different score.",
        "reproducibility risk",
    )
    add_card(
        draw,
        (400 * SCALE, 625 * SCALE, 680 * SCALE, 820 * SCALE),
        COLORS["teal"],
        "Ambiguous criteria",
        "Faithfulness, quality, and helpfulness are not universal metrics.",
        "rubric mismatch",
    )
    add_card(
        draw,
        (745 * SCALE, 625 * SCALE, 1025 * SCALE, 820 * SCALE),
        COLORS["yellow"],
        "Cost + latency",
        "Each criterion can add another model call before the user sees an answer.",
        "production tradeoff",
    )
    add_card(
        draw,
        (210 * SCALE, 852 * SCALE, 490 * SCALE, 1047 * SCALE),
        COLORS["red"],
        "Bias",
        "Self-preference, first-position bias, and verbosity bias can distort scores.",
        "not neutral",
    )
    add_card(
        draw,
        (590 * SCALE, 852 * SCALE, 870 * SCALE, 1047 * SCALE),
        COLORS["slate"],
        "Privacy + IP",
        "A proprietary judge may require sending sensitive prompts, outputs, or domain data.",
        "data boundary",
    )

    # Bottom conclusion.
    rounded(draw, (84 * SCALE, 1108 * SCALE, 996 * SCALE, 1262 * SCALE), 36 * SCALE, COLORS["card"], COLORS["blue"], 2 * SCALE)
    draw.text((125 * SCALE, 1138 * SCALE), "Use AI judges with guardrails", font=F["body_bold"], fill=COLORS["blue_dark"])
    guardrails = [
        ("transparent prompts", COLORS["blue"]),
        ("clear rubrics", COLORS["teal"]),
        ("calibration examples", COLORS["yellow"]),
        ("human-reviewed test sets", COLORS["red"]),
        ("task-specific ground truth", COLORS["slate"]),
    ]
    start_x = 124 * SCALE
    max_x = 955 * SCALE
    x = start_x
    y = 1190 * SCALE
    for text, color in guardrails:
        text_w = measure(draw, text, F["pill"])[0]
        chip_w = text_w + 34 * SCALE
        if x + chip_w > max_x:
            x = start_x
            y += 36 * SCALE
        rounded(draw, (x, y, x + chip_w, y + 32 * SCALE), 16 * SCALE, tint(color, 0.18), COLORS["card_line"], 1 * SCALE)
        draw.ellipse((x + 12 * SCALE, y + 11 * SCALE, x + 22 * SCALE, y + 21 * SCALE), fill=color)
        draw.text((x + 29 * SCALE, y + 7 * SCALE), text, font=F["pill"], fill=COLORS["ink"])
        x += text_w + 48 * SCALE

    rounded(draw, (95 * SCALE, 1292 * SCALE, 985 * SCALE, 1332 * SCALE), 20 * SCALE, COLORS["card"], COLORS["card_line"], 1 * SCALE)
    footer = "The goal is not to stop using AI judges. It is to stop treating their scores as final verdicts."
    tw = measure(draw, footer, F["small_bold"])[0]
    draw.text(((W * SCALE - tw) // 2, 1302 * SCALE), footer, font=F["small_bold"], fill=COLORS["ink"])

    # Downsample for antialiasing.
    return img.resize((W, H), Image.Resampling.LANCZOS)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    still = render_slide(0)
    still.save(PNG_PATH, quality=95)

    dash_cycle = (16 + 11) * SCALE
    frames = [render_slide(dash_cycle * i / FRAME_COUNT) for i in range(FRAME_COUNT)]
    frames[0].save(
        GIF_PATH,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_DURATION_MS,
        loop=0,
        disposal=2,
        optimize=True,
    )
    print(PNG_PATH)
    print(GIF_PATH)


if __name__ == "__main__":
    main()
