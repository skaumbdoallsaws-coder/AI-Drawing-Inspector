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


def _signature(value: str):
    category = license_class(value)
    if category in {"other", "unknown"}:
        return category, value.casefold()
    versions = tuple(sorted(set(re.findall(r"\b[1-4]\.0\b", value))))
    return category, versions


def _text_fields(text: str) -> list[tuple[str, str]]:
    # Assertions are a sequence: repeated fields must never overwrite evidence.
    result = []
    for line in text.splitlines():
        match = re.match(r"^\s*[*#-]*\s*([^:]{1,40}):\s*(.+)$", line)
        if not match:
            continue
        field = _FIELDS.get(match.group(1).strip().casefold())
        if not field:
            continue
        raw_value = match.group(2).strip().strip('"')
        value = clean_text(raw_value, len(raw_value))
        urls = _URL.findall(value)
        if field in {"author", "license"}:
            result.extend((field + "Url", https_url(url)) for url in urls)
            # Classify the written label independently of any embedded URL.
            for url in urls:
                value = value.replace(url, "")
            value = clean_text(value.rstrip(" ()"), len(value))
        result.append((field, https_url(value) if field.endswith("Url") else
                       value if field == "license" else clean_text(value, 300)))
    return result


def parse_licence(texts: list[tuple[str, str]], asset: dict) -> dict:
    """Parse Sketchfab facts, retaining contradictory labels and URLs independently."""
    assertions = [item for _, text in texts for item in _text_fields(text)]
    extras = asset.get("extras")
    if isinstance(extras, dict):
        for source, target in (("title", "title"), ("author", "author"), ("license", "license"),
                               ("source", "sourceUrl"), ("authorUrl", "authorUrl"), ("licenseUrl", "licenseUrl")):
            value = clean_text(extras.get(source), 300)
            if value:
                if target == "license":
                    assertions.extend(_text_fields("License: " + extras[source]))
                else:
                    assertions.append((target, https_url(value) if target.endswith("Url") else value))
    copyright_text = asset.get("copyright") if isinstance(asset.get("copyright"), str) else ""
    if copyright_text:
        fields = _text_fields(copyright_text)
        assertions.extend(fields)
        if (not any(k in {"license", "licenseUrl"} for k, _ in fields)
                and license_class(copyright_text) not in {"other", "unknown"}):
            assertions.extend(_text_fields("License: " + copyright_text))
    result = {key: "" for key in ("title", "author", "authorUrl", "sourceUrl", "license", "licenseUrl")}
    conflicts = []
    for key in result:
        values = list(dict.fromkeys(v for k, v in assertions if k == key and v))
        if values:
            result[key] = clean_text(values[0], 300)
        distinct = {_signature(v) for v in values} if key == "license" else set(values)
        if len(distinct) > 1:
            shown = values[:3] + values[-1:] if len(values) > 4 else values
            conflicts.append({"field": key, "values": [clean_text(v, 300) for v in shown]})
    evidence = list(dict.fromkeys(v for k, v in assertions if k in {"license", "licenseUrl"} and v))
    classes = {license_class(v) for v in evidence}
    versions = {version for value in evidence for version in re.findall(r"\b[1-4]\.0\b", value)}
    if len(classes) > 1 or len(versions) > 1:
        # Representatives retain independent label/URL contradictions within the cap.
        representatives = {}
        for value in evidence:
            representatives.setdefault(_signature(value), value)
        conflicts = [c for c in conflicts if c["field"] != "license"]
        conflicts.append({"field": "license",
                          "values": [clean_text(v, 300) for v in list(representatives.values())[:4]]})
    result["class"] = "unknown" if conflicts or not classes else next(iter(classes))
    excerpt = clean_text(" ".join(text for _, text in texts) + " " + copyright_text, 2048)
    result["excerpt"] = clean_text(excerpt.encode("utf-8")[:2048].decode("utf-8", errors="ignore"), 2048)
    result["conflicts"] = conflicts
    return result
