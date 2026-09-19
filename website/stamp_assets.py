"""Stamp the css/js links in index.html with a short content hash.

index.html is served must-revalidate, but css/js carry a multi-hour max-age.
Without a version in the URL, a deploy that changes only an asset leaves
returning visitors on fresh HTML with a stale script - which silently breaks
anything the script renders. Hashing the query string makes the browser refetch
exactly when the file changed, and not otherwise.

Run this before `wrangler pages deploy`.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "index.html"

ASSETS = (
    ("css/style.css", "href"),
    ("js/main.js", "src"),
)


def digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:10]


def main() -> None:
    html = HTML.read_text(encoding="utf-8")
    for rel, attr in ASSETS:
        stamp = digest(rel)
        pattern = rf'{attr}="{re.escape(rel)}(?:\?v=[0-9a-f]+)?"'
        replacement = f'{attr}="{rel}?v={stamp}"'
        html, count = re.subn(pattern, replacement, html)
        if count != 1:
            raise SystemExit(f"expected exactly one {rel} reference, found {count}")
        print(f"  {rel}?v={stamp}")
    HTML.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
