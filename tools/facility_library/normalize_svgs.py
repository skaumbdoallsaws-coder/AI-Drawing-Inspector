"""Give every sign SVG an explicit viewBox (derived from width/height) and report aspect ratios."""
import sys, re, json, hashlib
from pathlib import Path
folder = Path(sys.argv[1]); report_path = Path(sys.argv[2])
report = json.loads(report_path.read_text(encoding="utf-8"))
by_file = {r["file"]: r for r in report}
num = lambda s: float(re.match(r"\s*([0-9.]+)", s).group(1))
for svg in sorted(folder.glob("*.svg")):
    text = svg.read_bytes().decode("utf-8")
    root = re.search(r"<svg\b[^>]*>", text, re.S)
    tag = root.group(0)
    vb = re.search(r'viewBox\s*=\s*"([^"]+)"', tag)
    if vb:
        parts = [float(v) for v in re.split(r"[\s,]+", vb.group(1).strip())]
        w, h = parts[2], parts[3]; changed = False
    else:
        w = num(re.search(r'\bwidth\s*=\s*"([^"]+)"', tag).group(1)); h = num(re.search(r'\bheight\s*=\s*"([^"]+)"', tag).group(1))
        new_tag = tag[:-1].rstrip("/").rstrip() + f' viewBox="0 0 {w:g} {h:g}"' + ("/>" if tag.endswith("/>") else ">")
        text = text.replace(tag, new_tag, 1); svg.write_bytes(text.encode("utf-8")); changed = True
    record = by_file[svg.name]
    record["aspect"] = round(w / h, 4); record["viewBoxAdded"] = changed
    record["originalSha256"] = record["sha256"]; record["sha256"] = hashlib.sha256(svg.read_bytes()).hexdigest()
    record["bytes"] = svg.stat().st_size
    print(svg.name, round(w / h, 3), "viewBox added" if changed else "")
report_path.write_bytes(json.dumps(report, indent=1).encode("utf-8"))
