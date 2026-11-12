"""Collect publication fit failures using the PDF builders' own bounded fitting."""
from contextlib import contextmanager
from contextvars import ContextVar
from .commands import DocumentEditError

_CURRENT = ContextVar("documentation_fit", default=None)


def collecting():
    return _CURRENT.get() is not None


def overflow(items, message="Authored objects must fit inside the page."):
    collector = _CURRENT.get()
    normalized = []
    for item in items:
        reason = item.get("reason") or next(iter(item.get("reasons") or []), "text_does_not_fit")
        normalized.append({**item, "reason": "column_too_narrow" if reason == "table_column_too_narrow" else reason})
    if collector is not None:
        for item in normalized:
            collector.add(item)
    else:
        raise DocumentEditError("layout_overflow", message, targets=normalized)


def refuse(items, limit=None):
    if items:
        raise DocumentEditError("layout_overflow", f"{len(items)} items do not fit this page setup.",
                                targets=items if limit is None else items[:limit], count=len(items))


def new_failures(current, candidate):
    """Keep new keys and excess-height regressions above four points; pagination is not identity."""
    previous = {}
    for item in current:
        key = (item["targetId"], item["reason"])
        excess = _excess(item)
        previous.setdefault(key, [])
        if excess is not None:
            previous[key].append(excess)
    result = []
    for item in candidate:
        key = (item["targetId"], item["reason"])
        excess = _excess(item)
        if key not in previous or (excess is not None and previous[key]
                                  and excess - max(previous[key]) > 4.0):
            result.append(item)
    return result


def _excess(item):
    if "measuredHeight" not in item or "frame" not in item:
        return None
    frame = item["frame"]
    height = frame["height"] if isinstance(frame, dict) else frame[3] - frame[1]
    return item["measuredHeight"] - height


class Collector:
    def __init__(self, document):
        self.pages = {p["pageId"]: i for i, p in enumerate(document.get("pages", []))}
        self.items = []
        self.aliases = document.get("aliasMap", {})

    def add(self, item):
        alias = self.aliases.get(item["pageId"], {}).get(item["targetId"], {})
        if alias.get("targetId"):
            item = {**item, "targetId": alias["targetId"]}
        key = (item["pageId"], item["targetId"], item["reason"])
        for previous in self.items:
            if (previous["pageId"], previous["targetId"], previous["reason"]) == key:
                previous.update(item)  # Retain the richer preflight evidence (legacy reasons and measuredHeight).
                return
        self.items.append(item)

    def report(self):
        return sorted(self.items, key=lambda v: self.pages.get(v["pageId"], len(self.pages)))


@contextmanager
def collect(document):
    collector = Collector(document)
    token = _CURRENT.set(collector)
    try:
        yield collector
    finally:
        _CURRENT.reset(token)


def target(page, descriptor, key, frame=None):
    if isinstance(page, MeasuredPage):
        page.target = {"pageId": descriptor["pageId"], "targetId": key or descriptor["pageId"]}
        if frame is not None:
            page.target["frame"] = list(frame)
            if frame[0] < -1e-4 or frame[1] < -1e-4 or frame[2] > page.rect.width + 1e-4 or frame[3] > page.rect.height + 1e-4:
                page.failure("outside_page")


def failure(page, reason="text_does_not_fit", **extra):
    if isinstance(page, MeasuredPage):
        page.failure(reason, **extra)
        return True
    return False


class MeasuredPage:
    """A scratch PDF page. Type sizes, fit results and draw order are untouched."""
    def __init__(self, page, descriptor):
        self._fit_page = page
        self.target = {"pageId": descriptor["pageId"], "targetId": descriptor["pageId"]}

    def __getattr__(self, key):
        return getattr(self._fit_page, key)

    def failure(self, reason, **extra):
        _CURRENT.get().add({**self.target, "reason": reason, **extra})

    def insert_text(self, point, text, **kwargs):
        # Generated point text has no fitting API; measure its real built-in glyph advances.
        import fitz
        font = kwargs.get("fontname", "helv")
        if font in {"helv", "hebo", "heit", "hebi", "tiro", "tibo", "tiit", "tibi", "cour", "cobo", "coit", "cobi"}:
            size = kwargs.get("fontsize", 11)
            lines = str(text).splitlines()
            width = max((fitz.get_text_length(line, fontname=font, fontsize=size) for line in lines), default=0)
            if point[0] < 0 or point[0] + width > self.rect.width + .01 or point[1] > self.rect.height + .01:
                self.failure("outside_page")
        return self._fit_page.insert_text(point, text, **kwargs)

    def insert_textbox(self, rect, text, **kwargs):
        if text and (rect.x0 < -1e-4 or rect.y0 < -1e-4
                     or rect.x1 > self.rect.width + 1e-4 or rect.y1 > self.rect.height + 1e-4):
            self.failure("outside_page", frame=list(rect))
        if rect.width <= 0 or rect.height <= 0:
            if text:
                self.failure("text_does_not_fit", frame=list(rect))
            return -1
        spare = self._fit_page.insert_textbox(rect, text, **kwargs)
        if spare < -.01:
            self.failure("text_does_not_fit", frame=list(rect), measuredHeight=rect.height-spare)
        return spare


def measured_page(page, descriptor):
    return MeasuredPage(page, descriptor) if collecting() else page


def authored_bounds(document):
    from .objects import ordered_objects, page_size, box
    width, height = page_size(document)
    for page in document.get("pages", []):
        for key, value in ordered_objects(page):
            frame = box(value["frame"], (width, height))
            if frame["x"] < -1e-9 or frame["y"] < -1e-9 or frame["x"]+frame["width"] > 1+1e-9 or frame["y"]+frame["height"] > 1+1e-9:
                overflow([{ "pageId": page["pageId"], "targetId": key, "reason": "outside_page",
                    "frame": [frame["x"]*width, frame["y"]*height,
                              (frame["x"]+frame["width"])*width, (frame["y"]+frame["height"])*height]}])
