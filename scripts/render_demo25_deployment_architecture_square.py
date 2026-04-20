from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
OUT = STATIC / "demo25_deployment_architecture_square_1080x1080.png"


def load_font(size: int, bold: bool = False):
    candidates = []
    if bold:
        candidates += [
            "C:/Windows/Fonts/seguisb.ttf",
            "C:/Windows/Fonts/bahnschrift.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/consolab.ttf",
        ]
    else:
        candidates += [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/bahnschrift.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/consola.ttf",
        ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_round_rect(base, xy, radius, fill, outline=None, width=1, shadow=True):
    x0, y0, x1, y1 = xy
    if shadow:
        shadow_img = Image.new("RGBA", base.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow_img)
        sd.rounded_rectangle((x0 + 5, y0 + 10, x1 + 5, y1 + 10), radius=radius, fill=(0, 0, 0, 125))
        shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(20))
        base.alpha_composite(shadow_img)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)
    base.alpha_composite(overlay)


def wrap_lines(draw, text_value, font, max_width):
    words = text_value.split()
    lines = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_text_block(draw, xy, text_value, font, fill, max_width, line_gap=8):
    x, y = xy
    lines = wrap_lines(draw, text_value, font, max_width)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, y), line, font=font)
        y = bbox[3] + line_gap
    return y


def draw_centered_text(draw, box, text_value, font, fill):
    x0, y0, x1, y1 = box
    bbox = draw.textbbox((0, 0), text_value, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((x0 + (x1 - x0 - tw) / 2, y0 + (y1 - y0 - th) / 2 - 2), text_value, font=font, fill=fill)


def draw_chip(base, xy, text_value, fill, text_fill, outline=None):
    draw = ImageDraw.Draw(base)
    font = load_font(14, bold=True)
    x, y = xy
    bbox = draw.textbbox((0, 0), text_value, font=font)
    width = (bbox[2] - bbox[0]) + 26
    height = 32
    draw_round_rect(base, (x, y, x + width, y + height), 12, fill=fill, outline=outline, width=1, shadow=False)
    draw.text((x + 13, y + 7), text_value, font=font, fill=text_fill)
    return width


def draw_logo(base, xy):
    x, y = xy
    d = ImageDraw.Draw(base)
    d.rounded_rectangle((x, y, x + 34, y + 34), radius=9, fill=(27, 118, 210, 255))
    cx = x + 17
    cy = y + 17
    d.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), outline=(255, 255, 255, 230), width=2)
    d.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=(255, 255, 255, 235))
    d.line((cx, y + 4, cx, y + 11), fill=(255, 255, 255, 230), width=2)
    d.line((cx, y + 23, cx, y + 30), fill=(255, 255, 255, 230), width=2)
    d.line((x + 4, cy, x + 11, cy), fill=(255, 255, 255, 230), width=2)
    d.line((x + 23, cy, x + 30, cy), fill=(255, 255, 255, 230), width=2)


def draw_cloud_icon(draw, cx, cy, accent):
    draw.ellipse((cx - 40, cy - 8, cx + 8, cy + 40), fill=accent)
    draw.ellipse((cx - 10, cy - 30, cx + 48, cy + 28), fill=accent)
    draw.ellipse((cx + 28, cy - 2, cx + 76, cy + 44), fill=accent)
    draw.rounded_rectangle((cx - 48, cy + 18, cx + 84, cy + 52), radius=18, fill=accent)


def draw_device_icon(draw, cx, cy, accent):
    draw.rounded_rectangle((cx - 54, cy - 42, cx + 54, cy + 46), radius=16, outline=accent, width=5)
    draw.rounded_rectangle((cx - 36, cy - 22, cx + 36, cy + 18), radius=8, fill=accent)
    draw.line((cx - 34, cy + 62, cx + 34, cy + 62), fill=accent, width=5)
    draw.line((cx, cy + 46, cx, cy + 62), fill=accent, width=5)


def draw_hybrid_icon(draw, cx, cy, accent):
    draw.rounded_rectangle((cx - 66, cy - 38, cx - 8, cy + 38), radius=13, outline=accent, width=5)
    draw.ellipse((cx + 10, cy - 34, cx + 82, cy + 38), outline=accent, width=5)
    draw.line((cx - 8, cy, cx + 10, cy), fill=accent, width=5)
    draw.line((cx - 34, cy + 48, cx + 46, cy + 48), fill=accent, width=4)
    draw.line((cx + 46, cy + 48, cx + 34, cy + 36), fill=accent, width=4)
    draw.line((cx + 46, cy + 48, cx + 34, cy + 60), fill=accent, width=4)


def draw_arch_card(base, box, title, subtitle, bullets, accent, icon_fn, emphasized=False):
    draw = ImageDraw.Draw(base)
    x0, y0, x1, y1 = box
    outline = (*accent[:3], 180 if emphasized else 58)
    fill = (14, 20, 27, 248) if emphasized else (16, 22, 29, 238)
    draw_round_rect(base, box, radius=26, fill=fill, outline=outline, width=2 if emphasized else 1, shadow=True)

    if emphasized:
        glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.rounded_rectangle((x0 - 8, y0 - 8, x1 + 8, y1 + 8), radius=34, outline=(*accent[:3], 95), width=6)
        glow = glow.filter(ImageFilter.GaussianBlur(12))
        base.alpha_composite(glow)

    icon_fn(draw, (x0 + x1) // 2, y0 + 82, (*accent[:3], 215))

    title_font = load_font(34, bold=True)
    sub_font = load_font(16, bold=True)
    bullet_font = load_font(19)
    muted = (178, 190, 203, 225)
    white = (248, 251, 253, 255)

    draw_centered_text(draw, (x0 + 16, y0 + 146, x1 - 16, y0 + 190), title, title_font, white)
    draw_centered_text(draw, (x0 + 18, y0 + 196, x1 - 18, y0 + 224), subtitle, sub_font, (*accent[:3], 245))

    yy = y0 + 260
    for bullet in bullets:
        draw.ellipse((x0 + 30, yy + 7, x0 + 42, yy + 19), fill=(*accent[:3], 235))
        yy = draw_text_block(draw, (x0 + 54, yy), bullet, bullet_font, muted, x1 - x0 - 86, line_gap=5)
        yy += 24


def main():
    w = h = 1080
    img = Image.new("RGBA", (w, h), (8, 11, 16, 255))
    draw = ImageDraw.Draw(img)

    top = (15, 20, 28)
    bottom = (6, 8, 12)
    for y in range(h):
        t = y / (h - 1)
        col = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        draw.line((0, y, w, y), fill=col)

    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-120, -60, 380, 310), fill=(54, 170, 255, 72))
    gd.ellipse((700, -20, 1100, 280), fill=(255, 176, 52, 54))
    gd.ellipse((760, 700, 1140, 1080), fill=(0, 230, 118, 42))
    glow = glow.filter(ImageFilter.GaussianBlur(48))
    img.alpha_composite(glow)

    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for x in range(0, w, 56):
        gd.line((x, 0, x, h), fill=(130, 150, 170, 18))
    for y in range(0, h, 56):
        gd.line((0, y, w, y), fill=(130, 150, 170, 18))
    img.alpha_composite(grid)

    eyebrow_font = load_font(16, bold=True)
    headline_font = load_font(59, bold=True)
    sub_font = load_font(21)
    brand_font = load_font(23, bold=True)
    meta_font = load_font(13, bold=True)
    callout_font = load_font(23, bold=True)
    callout_body_font = load_font(18)

    draw.rounded_rectangle((52, 56, 92, 60), radius=4, fill=(109, 214, 255, 255))
    draw.text((106, 43), "DEPLOYMENT ARCHITECTURE", font=eyebrow_font, fill=(175, 232, 255, 255))
    draw.text((52, 82), "From Demo to", font=headline_font, fill=(248, 251, 253, 255))
    draw.text((52, 140), "Production.", font=headline_font, fill=(248, 251, 253, 255))

    sub = "A prototype proves potential. Architecture decides if it survives production."
    draw_text_block(draw, (52, 218), sub, sub_font, (221, 229, 236, 208), 940, line_gap=8)

    draw_round_rect(
        img,
        (48, 288, 1032, 846),
        radius=28,
        fill=(11, 16, 22, 224),
        outline=(224, 236, 248, 34),
        width=1,
        shadow=True,
    )

    card_y0 = 322
    card_y1 = 800
    gap = 22
    card_w = 294
    x0 = 78
    cards = [
        (
            (x0, card_y0, x0 + card_w, card_y1),
            "CLOUD",
            "Scale + access",
            ["Elastic capacity", "Fast model updates", "Watch privacy and cost"],
            (84, 185, 255, 255),
            draw_cloud_icon,
            False,
        ),
        (
            (x0 + card_w + gap, card_y0 - 12, x0 + 2 * card_w + gap, card_y1 + 12),
            "HYBRID",
            "Production balance",
            ["Sensitive work local", "Escalate when justified", "Best fit for InspectorPro"],
            (0, 230, 118, 255),
            draw_hybrid_icon,
            True,
        ),
        (
            (x0 + 2 * (card_w + gap), card_y0, x0 + 3 * card_w + 2 * gap, card_y1),
            "ON-DEVICE",
            "Control + latency",
            ["Data stays inside", "No network round trip", "Harder scale and updates"],
            (255, 183, 54, 255),
            draw_device_icon,
            False,
        ),
    ]

    for card in cards:
        draw_arch_card(img, *card)

    draw_round_rect(
        img,
        (48, 864, 1032, 976),
        radius=24,
        fill=(11, 15, 20, 244),
        outline=(224, 236, 248, 28),
        width=1,
        shadow=False,
    )
    draw.text((76, 894), "InspectorPro direction", font=callout_font, fill=(247, 250, 252, 255))
    draw_text_block(
        draw,
        (76, 929),
        "Local for CAD, drawings, geometry, FAI and inspection data. Cloud only when advanced reasoning justifies the tradeoff.",
        callout_body_font,
        (218, 228, 236, 205),
        900,
        line_gap=6,
    )

    draw_chip(img, (786, 887), "HYBRID BY DESIGN", (0, 230, 118, 35), (125, 255, 190, 255), outline=(0, 230, 118, 75))

    draw_logo(img, (52, 1018))
    draw.text((96, 1021), "Inspector", font=brand_font, fill=(255, 255, 255, 225))
    draw.text((194, 1021), "Pro", font=brand_font, fill=(156, 223, 255, 255))
    draw.text((735, 1023), "AI AGENTS  |  PRODUCTION ARCHITECTURE", font=meta_font, fill=(153, 167, 182, 215))

    img.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
