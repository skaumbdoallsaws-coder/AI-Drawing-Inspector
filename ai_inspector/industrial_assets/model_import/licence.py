"""Keep bounded source attribution as evidence, never as executable instructions."""
import re

from .validation import clean_text

_FIELDS = {"title": "title", "model title": "title", "author": "author", "creator": "author",
           "source": "sourceUrl", "model url": "sourceUrl", "source url": "sourceUrl",
           "license": "license", "licence": "license", "license type": "license",
           "licence type": "license", "license url": "licenseUrl", "licence url": "licenseUrl",
           "author url": "authorUrl"}
_URL = re.compile(r"https://[^\s<>\"()]+", re.IGNORECASE)


def https_url(value) -> str:
    text = clean_text(value, 300)
    if not text.lower().startswith("https://") or any(c in text for c in "\\ <>\""):
        return ""
    authority = text[8:].split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if not authority or "@" in authority or "%" in authority:
        return ""
    return text


def license_class(value: str) -> str:
    text = value.casefold()
    if re.search(r"\bcc[\s-]*0\b|creativecommons\.org/publicdomain/zero", text):
        return "cc0"
    if "creativecommons.org/licenses/" in text:
        match = re.search(r"creativecommons\.org/licenses/(by(?:-(?:nc|nd|sa))*)/", text)
        if match:
            result = "cc-" + match.group(1)
            if result in {"cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nd", "cc-by-nc-sa", "cc-by-nc-nd"}:
                return result
    if re.search(r"\bcc[\s-]*by\b|\bcc attribution\b|creative commons.*attribution", text):
        nc = bool(re.search(r"\bnc\b|non[\s-]?commercial", text))
        nd = bool(re.search(r"\bnd\b|no[\s-]?(?:derivatives|derivs)", text))
        sa = bool(re.search(r"\bsa\b|share[\s-]?alike", text))
        if nd and sa:
            return "unknown"
        return "cc-by" + ("-nc" if nc else "") + ("-nd" if nd else "-sa" if sa else "")
    return "other" if text.strip() else "unknown"


def _text_fields(text: str) -> dict:
    result = {}
    for line in text.splitlines():
        match = re.match(r"^\s*[*#-]*\s*([^:]{1,40}):\s*(.+)$", line)
        if not match:
            continue
        field = _FIELDS.get(match.group(1).strip().casefold())
        if not field:
            continue
        value = clean_text(match.group(2).strip().strip('"'), 300)
        if field == "author":
            urls = _URL.findall(value)
            if urls:
                result["authorUrl"] = https_url(urls[0])
                value = clean_text(value.replace(urls[0], "").rstrip(" ()"), 300)
        if field == "license":
            urls = _URL.findall(value)
            if urls:
                result["licenseUrl"] = https_url(urls[0])
        result[field] = https_url(value) if field.endswith("Url") else value
    return result


def parse_licence(texts: list[tuple[str, str]], asset: dict) -> dict:
    """Parse Sketchfab's '* title/source/author/license type:' format and glTF facts."""
    records = [_text_fields(text) for _, text in texts]
    extras = asset.get("extras")
    if isinstance(extras, dict):
        fields = {}
        for source, target in (("title", "title"), ("author", "author"), ("license", "license"),
                               ("source", "sourceUrl"), ("authorUrl", "authorUrl"), ("licenseUrl", "licenseUrl")):
            value = clean_text(extras.get(source), 300)
            if value:
                fields[target] = https_url(value) if target.endswith("Url") else value
        if fields:
            records.append(fields)
    copyright_text = clean_text(asset.get("copyright"), 2048)
    if copyright_text:
        fields = _text_fields(copyright_text)
        if license_class(copyright_text) not in {"other", "unknown"}:
            fields.setdefault("license", clean_text(copyright_text, 300))
        records.append(fields)
    result = {key: "" for key in ("title", "author", "authorUrl", "sourceUrl", "license", "licenseUrl")}
    conflicts = []
    for key in result:
        values = list(dict.fromkeys(r[key] for r in records if r.get(key)))
        if values:
            result[key] = values[0]
        # Equivalent license spellings/URLs do not manufacture a conflict.
        distinct = {license_class(v) for v in values} if key == "license" else set(values)
        if len(distinct) > 1:
            conflicts.append({"field": key, "values": values[:4]})
    classes = {license_class(r.get("license", "") or r.get("licenseUrl", "")) for r in records
               if r.get("license") or r.get("licenseUrl")}
    if len(classes) > 1 and not any(c["field"] == "license" for c in conflicts):
        conflicts.append({"field": "license", "values": sorted(classes)})
    result["class"] = "unknown" if conflicts or not classes else next(iter(classes))
    excerpt = clean_text(" ".join(text for _, text in texts) + " " + copyright_text, 2048)
    result["excerpt"] = excerpt.encode("utf-8")[:2048].decode("utf-8", errors="ignore")
    result["conflicts"] = conflicts
    return result
