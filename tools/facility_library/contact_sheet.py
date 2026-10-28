"""Download ambientCG 128px previews into a given folder and build a labeled contact sheet."""
import sys, json, urllib.request
from pathlib import Path
from PIL import Image, ImageDraw

out_dir = Path(sys.argv[1]); sheet = Path(sys.argv[2]); ids = sys.argv[3:]
out_dir.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "InspectorPro-asset-curation/1.0 (facility appearance library)"}
tiles = []
for asset in ids:
    target = out_dir / f"{asset}.png"
    if not target.exists():
        url = f"https://acg-media.struffelproductions.com/file/ambientCG-Web/media/thumbnail/256-PNG/{asset}.png"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                target.write_bytes(r.read())
        except Exception as exc:
            print("fail", asset, exc); continue
    try:
        im = Image.open(target).convert("RGB").resize((200, 200))
    except Exception as exc:
        print("bad", asset, exc); continue
    tiles.append((asset, im))
cols = 6; rows = (len(tiles) + cols - 1) // cols
canvas = Image.new("RGB", (cols * 210, rows * 228), (40, 40, 40))
draw = ImageDraw.Draw(canvas)
for i, (asset, im) in enumerate(tiles):
    x, y = (i % cols) * 210 + 5, (i // cols) * 228 + 5
    canvas.paste(im, (x, y)); draw.text((x + 2, y + 203), asset, fill=(255, 255, 255))
canvas.save(sheet); print("sheet", sheet, len(tiles))
