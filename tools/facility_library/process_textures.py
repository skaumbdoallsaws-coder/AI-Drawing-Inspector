"""Convert extracted ambientCG maps into the compact library texture sets.

Usage: python -I process_textures.py <extracted_root> <output_root>
Color sets keep their sRGB color map. Tintable sets get a neutral 'detail' map whose
median sits near white, so the appearance color sets the hue and the map adds variation.
"""
import sys, json, hashlib
from pathlib import Path
from PIL import Image
import numpy as np

SETS = {
    "wood-maple":      dict(src="Wood095",      size=1024, mode="color"),
    "wood-oak":        dict(src="Wood049",      size=1024, mode="color"),
    "wood-walnut":     dict(src="Wood027",      size=1024, mode="color"),
    "metal-brushed":   dict(src="Metal009",     size=1024, mode="detail", contrast=0.45),
    "fabric-woven":    dict(src="Fabric030",    size=512,  mode="detail", contrast=0.9, ao=True),
    "cardboard-kraft": dict(src="Cardboard002", size=512,  mode="detail", contrast=0.8),
    "paper-matte":     dict(src="Paper001",     size=512,  mode="detail", contrast=0.6),
    "concrete-smooth": dict(src="Concrete030",  size=1024, mode="color", ao=True),
    "marble-white":    dict(src="Marble012",    size=1024, mode="color"),
    "rubber-speckled": dict(src="Rubber001",    size=1024, mode="color"),
}

def save_jpg(image, path, quality):
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=quality, optimize=True, progressive=False)

def main(ext_root, out_root):
    report = {}
    for name, cfg in SETS.items():
        src = Path(ext_root) / cfg["src"]; prefix = cfg["src"] + "_1K-JPG_"
        out = Path(out_root) / name; size = cfg["size"]; half = max(256, size // 2)
        files = {}
        color = Image.open(src / (prefix + "Color.jpg")).convert("RGB")
        if cfg["mode"] == "color":
            save_jpg(color.resize((size, size), Image.LANCZOS), out / "color.jpg", 84); files["color"] = "color.jpg"
        else:
            lum = np.asarray(color.convert("L").resize((size, size), Image.LANCZOS), dtype=np.float32)
            ratio = lum / max(1.0, float(np.percentile(lum, 50)))
            detail = np.clip((1.0 + (ratio - 1.0) * cfg["contrast"]) * 248.0, 0, 255).astype(np.uint8)
            save_jpg(Image.fromarray(detail, "L"), out / "detail.jpg", 85); files["detail"] = "detail.jpg"
        normal = Image.open(src / (prefix + "NormalGL.jpg")).convert("RGB")
        save_jpg(normal.resize((size, size), Image.LANCZOS), out / "normal.jpg", 90); files["normal"] = "normal.jpg"
        rough = Image.open(src / (prefix + "Roughness.jpg")).convert("L")
        save_jpg(rough.resize((half, half), Image.LANCZOS), out / "roughness.jpg", 85); files["roughness"] = "roughness.jpg"
        if cfg.get("ao") and (src / (prefix + "AmbientOcclusion.jpg")).exists():
            ao = Image.open(src / (prefix + "AmbientOcclusion.jpg")).convert("L")
            save_jpg(ao.resize((half, half), Image.LANCZOS), out / "ao.jpg", 85); files["ao"] = "ao.jpg"
        rough_mean = float(np.asarray(rough, dtype=np.float32).mean() / 255.0)
        report[name] = {"source": cfg["src"], "files": {k: {"path": v, "bytes": (out / v).stat().st_size,
                        "sha256": hashlib.sha256((out / v).read_bytes()).hexdigest()} for k, v in files.items()},
                        "roughnessMean": round(rough_mean, 3), "pixels": size}
    print(json.dumps(report, indent=1))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
