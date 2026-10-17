"""Create inspectable contact sheets and canvas-pixel evidence from native captures."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".runtime/independent-factory-layer2-20260928"


def main():
    report = json.loads((OUTPUT / "native-check.json").read_text())
    if report["status"] != "passed" or len(report["layer2"]["zones"]) != 52:
        raise RuntimeError("Wait for the complete successful native zone review.")
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 20)
    records = report["layer2"]["zones"]
    pixel_checks = []
    for start in range(0, len(records), 4):
        sheet = Image.new("RGB", (1600, 760), "#edf1f5")
        draw = ImageDraw.Draw(sheet)
        for index, record in enumerate(records[start:start + 4]):
            image = Image.open(OUTPUT / record["capture"]).convert("RGB")
            if image.size != (1920, 1020):
                raise ValueError("Review crop must be remeasured for a different window size.")
            # Bounds read from this native 1920x1020 capture; exclude toolbar/chrome.
            region = image.crop((114, 275, 1806, 914))
            pixels = region.resize((160, 60))
            colors = len(set(pixels.getdata()))
            deviation = max(ImageStat.Stat(pixels).stddev)
            if colors < 30 or deviation < 2:
                raise ValueError("Unexpectedly blank 3D region: " + record["capture"])
            pixel_checks.append({"capture": record["capture"], "colors": colors,
                                 "maxChannelStdDev": round(deviation, 3)})
            x, y = index % 2 * 800, index // 2 * 380
            draw.text((x + 12, y + 8), record["label"], fill="#17212b", font=font)
            region.thumbnail((790, 335))
            sheet.paste(region, (x + 5, y + 38))
        sheet.save(OUTPUT / f"contact-{start // 4 + 1:02d}.png")
    (OUTPUT / "canvas-pixel-checks.json").write_text(json.dumps({
        "crop": [114, 275, 1806, 914], "status": "passed", "checks": pixel_checks,
        "qualification": "Nonblank pixel test only. Contact sheets require visual review; geometry assertions are separate."
    }, indent=2), encoding="utf-8")
    print(json.dumps({"zoneCaptures": len(records), "contactSheets": 13, "pixelChecks": len(pixel_checks)}))


if __name__ == "__main__":
    main()
