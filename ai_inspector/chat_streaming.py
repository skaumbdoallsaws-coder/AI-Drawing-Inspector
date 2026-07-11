"""Shared contracts and safety primitives for provisional chat streaming.

Streamed prose is display-only. Batch parsing of the complete response remains
authoritative for tools, workflow state, and the committed assistant message.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Optional, Sequence, Tuple


@dataclass(frozen=True)
class BlockDirective:
    kind: str
    opener: str
    closer: str


BLOCK_DIRECTIVES: Tuple[BlockDirective, ...] = (
    BlockDirective("tool_calls", "<tool_calls>", "</tool_calls>"),
    BlockDirective("ui_actions", "[UI_ACTIONS]", "[/UI_ACTIONS]"),
)

# This registry is shared by the stream firewall and the batch parser tests.
# A new line directive must be registered here before it can ship.
LINE_DIRECTIVE_MARKERS: Tuple[str, ...] = (
    "HIGHLIGHT_DIMS",
    "HIGHLIGHT_VIEWS",
    "HIGHLIGHT_FEATURE",
    "HIGHLIGHT_FEATURES",
    "HIGHLIGHT_REGIONS",
    "COMPARE_FEATURES",
    "COMPARE_PARTS",
    "CAMERA_VIEW",
    "EXPLODE_LEVEL",
    "CAMERA_FOCUS",
    "HIGHLIGHT_PARTS",
    "ISOLATE_PART",
    "FAI_FILL",
    "FAI_TOL",
    "SHOW_GEOMETRY_DIFF",
    "RUN_INSPECTION",
    "ANIMATE_MOTION",
)


@dataclass(frozen=True)
class DirectiveStart:
    start: int
    end: int
    kind: str
    marker: str


@dataclass(frozen=True)
class FilterRelease:
    text: str = ""
    directive: Optional[DirectiveStart] = None


def _block_start_regex(spec: BlockDirective) -> re.Pattern[str]:
    if spec.kind == "tool_calls":
        # The closing angle bracket is optional on purpose: malformed or
        # truncated machine syntax must still be hidden from the user.
        return re.compile(r"<\s*tool_calls\b\s*[^>]*>?", re.IGNORECASE)
    return re.compile(r"\[\s*ui_actions\b\s*\]?", re.IGNORECASE)


_BLOCK_START_REGEXES = tuple(
    (spec, _block_start_regex(spec)) for spec in BLOCK_DIRECTIVES
)
_LINE_START_REGEXES = tuple(
    (
        marker,
        re.compile(
            rf"(?im)^[ \t]*{re.escape(marker)}\b[ \t]*(?::|$)",
        ),
    )
    for marker in LINE_DIRECTIVE_MARKERS
)


def find_first_directive_start(text: str) -> Optional[DirectiveStart]:
    """Return the earliest machine-directive start in *text*.

    Detection is case-insensitive and deliberately accepts malformed block
    openers. The browser must never display a half-written tool block.
    """

    best: Optional[DirectiveStart] = None
    for spec, pattern in _BLOCK_START_REGEXES:
        match = pattern.search(text)
        if match:
            item = DirectiveStart(match.start(), match.end(), spec.kind, spec.opener)
            if best is None or item.start < best.start:
                best = item
    for marker, pattern in _LINE_START_REGEXES:
        match = pattern.search(text)
        if match:
            item = DirectiveStart(match.start(), match.end(), "line_marker", marker)
            if best is None or item.start < best.start:
                best = item
    return best


def provisional_display_prefix(text: str) -> str:
    """Reference display policy for a complete raw model response."""

    directive = find_first_directive_start(text or "")
    return (text or "")[:directive.start] if directive else (text or "")


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "").upper()


_BLOCK_PREFIXES = tuple(_compact(spec.opener) for spec in BLOCK_DIRECTIVES)
_LINE_PREFIXES = tuple(marker.upper() for marker in LINE_DIRECTIVE_MARKERS)


def _possible_partial_start(text: str) -> Optional[int]:
    """Find the earliest suffix that may become a directive on more input."""

    candidates = []

    # Block directives can appear after prose on the same line.
    scan_from = max(0, len(text) - max(len(v) for v in _BLOCK_PREFIXES) - 12)
    for index in range(scan_from, len(text)):
        if text[index] not in "<[":
            continue
        compact = _compact(text[index:])
        if compact and any(prefix.startswith(compact) for prefix in _BLOCK_PREFIXES):
            candidates.append(index)

    # Line markers are only valid at the beginning of the current line.
    line_start = text.rfind("\n") + 1
    line_value = text[line_start:]
    stripped = line_value.lstrip(" \t")
    compact_line = _compact(stripped).rstrip(":")
    if compact_line and any(prefix.startswith(compact_line) for prefix in _LINE_PREFIXES):
        # Hold the indentation too. Otherwise spaces can leak one token at a
        # time before enough marker characters arrive to confirm a directive.
        candidates.append(line_start)
    elif not stripped and line_value:
        # Leading whitespace may still precede a marker.
        candidates.append(line_start)

    return min(candidates) if candidates else None


class StreamDirectiveFilter:
    """Incrementally release prose without ever leaking machine directives.

    After the first directive begins, the filter seals permanently. This is
    intentional: prompt contracts put directives after prose, and the batch
    pipeline remains the authority for any trailing content.
    """

    def __init__(self, release_margin: int = 8):
        self.release_margin = max(0, int(release_margin))
        self._buffer = ""
        self._sealed = False
        self._directive: Optional[DirectiveStart] = None
        self.released_text = ""

    @property
    def sealed(self) -> bool:
        return self._sealed

    @property
    def directive(self) -> Optional[DirectiveStart]:
        return self._directive

    def feed(self, chunk: str) -> FilterRelease:
        if self._sealed or not chunk:
            return FilterRelease()
        self._buffer += str(chunk)

        directive = find_first_directive_start(self._buffer)
        if directive is not None:
            safe = self._buffer[:directive.start]
            self._sealed = True
            self._directive = directive
            self._buffer = ""
            self.released_text += safe
            return FilterRelease(text=safe, directive=directive)

        partial_start = _possible_partial_start(self._buffer)
        margin_start = max(0, len(self._buffer) - self.release_margin)
        release_end = margin_start
        if partial_start is not None:
            release_end = min(release_end, partial_start)
        if release_end <= 0:
            return FilterRelease()
        safe = self._buffer[:release_end]
        self._buffer = self._buffer[release_end:]
        self.released_text += safe
        return FilterRelease(text=safe)

    def finish(self) -> FilterRelease:
        if self._sealed:
            return FilterRelease()
        directive = find_first_directive_start(self._buffer)
        if directive is not None:
            safe = self._buffer[:directive.start]
            self._sealed = True
            self._directive = directive
            self._buffer = ""
            self.released_text += safe
            return FilterRelease(text=safe, directive=directive)

        partial_start = _possible_partial_start(self._buffer)
        if partial_start is None:
            safe = self._buffer
        else:
            safe = self._buffer[:partial_start]
            self._sealed = True
        self._buffer = ""
        self.released_text += safe
        return FilterRelease(text=safe)


class SentenceStreamBuffer:
    """Incrementally split prose at completed sentence boundaries."""

    def __init__(self):
        self._buffer = ""

    def feed(self, text: str) -> Sequence[str]:
        self._buffer += str(text or "")
        sentences = []
        while True:
            boundary = re.search(r"(?<=[.!?])\s+", self._buffer)
            if not boundary:
                break
            sentence = self._buffer[:boundary.start()].strip()
            self._buffer = self._buffer[boundary.end():]
            if sentence:
                sentences.append(sentence)
        return sentences

    def finish(self) -> Sequence[str]:
        sentence = self._buffer.strip()
        self._buffer = ""
        return [sentence] if sentence else []


def iter_filter_chunks(
    chunks: Iterable[str], *, release_margin: int = 8
) -> Sequence[FilterRelease]:
    """Test/helper adapter for scripted provider streams."""

    firewall = StreamDirectiveFilter(release_margin=release_margin)
    releases = [firewall.feed(chunk) for chunk in chunks]
    releases.append(firewall.finish())
    return releases
