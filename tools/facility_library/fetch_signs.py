"""Download public-domain (or CC0) ISO 7010 SVGs listed in commons.json, verify SHA-1, screen content."""
import sys, json, re, hashlib, datetime, urllib.request
from pathlib import Path
src = Path(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "InspectorPro-asset-curation/1.0 (https://inspectorpro.io)"}
pages = json.loads((src / "commons.json").read_text(encoding="utf-8"))["query"]["pages"].values()
records = []
for page in sorted(pages, key=lambda p: p["title"]):
    info = page["imageinfo"][0]; meta = info.get("extmetadata", {})
    license_name = re.sub("<[^>]+>", "", meta.get("LicenseShortName", {}).get("value", ""))
    # CC0 is a public-domain dedication: no attribution or share-alike terms. Anything else is skipped.
    license_key = license_name.strip().lower()
    if license_key not in ("public domain", "cc0"):
        print("skip (license)", page["title"], license_name); continue
    code = re.search(r"ISO 7010 ([A-Z]\d{3})", page["title"]).group(1)
    with urllib.request.urlopen(urllib.request.Request(info["url"], headers=UA), timeout=30) as response:
        data = response.read()
    if hashlib.sha1(data).hexdigest() != info["sha1"]:
        print("skip (sha1 mismatch)", code); continue
    text = data.decode("utf-8", errors="replace")
    bad = [p for p in (r"<script", r"foreignObject", r"\bon[a-z]+\s*=", r"(href|src)\s*=\s*['\"](https?:|//|data:)", r"@import", r"url\(\s*['\"]?https?:") if re.search(p, text, re.I)]
    if bad:
        print("skip (content)", code, bad); continue
    (out / f"iso7010-{code.lower()}.svg").write_bytes(data)
    desc = re.sub("<[^>]+>", "", meta.get("ImageDescription", {}).get("value", "")).strip()
    records.append({"code": code, "file": f"iso7010-{code.lower()}.svg", "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(), "sourceUrl": info["descriptionurl"],
                    "fileUrl": info["url"], "license": "Public domain" if license_key == "public domain" else "CC0 1.0",
                    "retrieved": datetime.date.today().isoformat(), "description": desc})
(out.parent / "signs_report.json").write_bytes(json.dumps(records, indent=1).encode("utf-8"))
print(len(records), "signs saved,", sum(r["bytes"] for r in records), "bytes")
