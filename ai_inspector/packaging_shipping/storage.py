"""Storage limits and the user-confirmed Remove unused (retention decision, 2026-11-06).

Nothing is deleted automatically. Documents, recovery drafts, receipts, quotes and quote attempts are never
removed. A full workspace refuses new imports instead of deleting anything to make room. Remove unused deletes
only imported models and artwork images that no stored record names, after the user confirms the exact list
(by its digest), and keeps items imported in the last hour so an import that is about to be saved stays.
"""
from __future__ import annotations

from hashlib import sha256
import re

MIB, GIB = 1024 ** 2, 1024 ** 3
DEFAULT_LIMITS = {"sources": 100, "source_bytes": 2 * GIB, "images": 500, "image_bytes": 512 * MIB}
RECENT_SECONDS = 3600
KINDS = {"source": ("sources", "glb"), "image": ("images", "png")}
REFERENCE = re.compile(r"\b(?:src|img)_[0-9a-f]{32}\b")
# Every stored record that can name a model or an image, in any scope. Any ID found here is kept.
REFERENCED_BY = (("documents", ("design", "past", "future")), ("receipts", ("result",)), ("create_receipts", ("result",)),
                 ("quotes", ("result",)), ("alternative_quotes", ("result",)), ("comparison_baselines", ("baseline", "selected")),
                 ("alternatives", ("design",)), ("drafts", ("checkpoint",)), ("research_evidence", ("record",)))
SCHEMA = """
    CREATE TABLE IF NOT EXISTS storage_settings (
        scope TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(scope,key));
    CREATE TABLE IF NOT EXISTS asset_imports (
        scope TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, imported REAL NOT NULL, PRIMARY KEY(scope,kind,id));
    CREATE TABLE IF NOT EXISTS storage_removals (
        scope TEXT NOT NULL, id TEXT NOT NULL, removed TEXT NOT NULL, items TEXT NOT NULL, PRIMARY KEY(scope,id));
"""
NOTICE = ("Nothing is deleted automatically. Remove unused deletes only imported models and artwork images that no "
          "document, alternative, Undo or Redo step, recovery draft, receipt or quote names. Items imported in the last "
          "hour are kept. Freed space is reused for new imports; the store file does not shrink.")


def size_text(value):
    return f"{value / GIB:.1f} GiB" if value >= GIB else f"{value / MIB:.0f} MiB"


def unused_digest(items):
    return sha256("\n".join(sorted(f"{item['kind']}:{item['id']}" for item in items)).encode()).hexdigest()
