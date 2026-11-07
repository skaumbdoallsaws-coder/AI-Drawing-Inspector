"""Public-source evidence Sage records for a packaging document.

A record is bound to a page Sage read in the same turn (read_public_source). The claim must appear in a
passage the provider quoted from that page (basis "source_quote") or, failing that, in the provider's
summary of the read (basis "provider_summary", an interpretation rather than a quotation). Any value,
unit or SKU/grade Sage attaches must appear in the claim, and an effective date in the read. The source
link, title and retrieval time come from the research receipt, never from the model. Records are
supporting, unreviewed evidence until the user accepts them; they never edit a design, pass validation,
approve anything or show that packaging is safe.
"""
from __future__ import annotations

import math
import re

KINDS = ("carton_sku", "material_density", "cushioning_guidance", "comparable_packaging")
MAX_PER_DOCUMENT = 200
MIN_CLAIM = 12
NOTICE = ("Public-source evidence recorded by Sage, unreviewed until you accept it. Accepting marks it reviewed; it never "
          "edits the design, passes validation or shows that packaging is safe.")
# Superscripts, micro sign, dashes, multiplication sign, no-break space and curly quotes, by code point.
_SYMBOLS = str.maketrans({chr(0xB3): "3", chr(0xB2): "2", chr(0xB5): "u", chr(0x2013): "-", chr(0x2014): "-",
                          chr(0xD7): "x", chr(0xA0): " ", chr(0x2019): "'", chr(0x201C): '"', chr(0x201D): '"'})
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d*\.\d+|\d+")


def normalized(text):
    return " ".join(str(text or "").translate(_SYMBOLS).split()).casefold()


def _quoted(read):
    """Passages the provider quoted from the page that was read. OpenAI citations carry no text."""
    url = read.get("requestedUrl")
    return [c.get("text") or "" for c in read.get("citations") or [] if isinstance(c, dict) and c.get("url") == url]


def claim_basis(read, claim):
    """source_quote, provider_summary, or None when the read does not contain the claim."""
    wanted = normalized(claim)
    if len(wanted) < MIN_CLAIM:
        return None
    if any(wanted in normalized(text) for text in _quoted(read)):
        return "source_quote"
    if wanted in normalized(read.get("summary")):
        return "provider_summary"
    return None


def numbers(text):
    return [float(match.replace(",", "")) for match in _NUMBER.findall(str(text or "").translate(_SYMBOLS))]


def refusal(read, item):
    """Why this item cannot be recorded from this research result, or None."""
    if not isinstance(read, dict) or read.get("operation") != "read" or not read.get("requestedUrl"):
        return "research_id is not a page read in this turn"
    if claim_basis(read, item.claim) is None:
        return "the page as read does not state this claim"
    if item.value is not None and not any(math.isclose(item.value, n, rel_tol=1e-9, abs_tol=1e-12)
                                          for n in numbers(item.claim)):
        return "the claim does not state this value"
    if item.unit and normalized(item.unit).replace(" ", "") not in normalized(item.claim).replace(" ", ""):
        return "the claim does not state this unit"
    if item.sku_or_grade and normalized(item.sku_or_grade) not in normalized(item.claim):
        return "the claim does not name this SKU or grade"
    if item.effective_date and normalized(item.effective_date) not in normalized(
            " ".join([read.get("summary") or "", *_quoted(read)])):
        return "the page as read does not state this date"
    return None


def key(record):
    """Records that say the same thing from the same page are stored once."""
    return (record["kind"], record["source"]["url"], normalized(record["claim"]), record["value"],
            normalized(record["unit"]), normalized(record["sku_or_grade"]))


def record(read, item):
    """The stored record. Source and provenance come from the research receipt, not the model."""
    url = read["requestedUrl"]
    source = next((s for s in read.get("sources") or [] if isinstance(s, dict) and s.get("url") == url), {})
    age = source.get("pageAge")
    return {"kind": item.kind, "subject": item.subject, "claim": item.claim, "claim_basis": claim_basis(read, item.claim),
            "value": item.value, "unit": item.unit, "sku_or_grade": item.sku_or_grade,
            "effective_date": item.effective_date, "confidence": item.confidence, "note": item.note,
            "source": {"url": url, "title": str(source.get("title") or url)[:240],
                       "page_age": age[:80] if isinstance(age, str) else None, "retrieved_at": read.get("retrievedAt")},
            "research": {"provider": read.get("provider"), "model": read.get("model"), "research_id": item.research_id,
                         "result_revision": read.get("resultRevision")},
            "recorded_by": "sage", "authority": "supporting"}
