"""BOM-aware revision compare for assembly drawings.

Produces a normalized, row-keyed compare payload from two revisions of the
same assembly. Composes the BOM row highlight JSONs into a single response
with explicit diff status and procurement classification.

Distinct from compute_assembly_diff in ai_inspector.comparison.assembly_differ:
- assembly_differ runs at the partDataCache level (geometry, features, mates)
- bom_compare runs at the BOM-row level (item_no, qty, procurement)

Both views are valid and coexist; this module never modifies assembly_differ.

Diff status vocabulary
----------------------
- ``added``                  : PN present in B, missing in A
- ``removed``                : PN present in A, missing in B
- ``qty_changed``            : same PN, different qty
- ``unchanged``              : same PN, same qty, no supplier evidence asymmetry
- ``substitution_unverified``: same PN, same qty, but supplier-spec sidecar
  asymmetry suggests the supplier may have changed without an internal-PN
  change. This is a soft signal, NEVER a proven substitution. The frontend
  is expected to keep this status out of "Changed only" filters by default.
"""

from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Procurement classification
# ---------------------------------------------------------------------------

# Explicit allow-list anchored to the conveyor demo (6000302). Adding a
# part to one of these sets is the cleanest, most auditable way to set
# procurement classification.
KNOWN_PURCHASED_PNS = frozenset({"1040016", "1040017", "1040018", "1040019"})
KNOWN_CUSTOM_PNS = frozenset({"1030031", "1030032", "1030033"})

# Numeric-prefix fallback used only when the explicit lists do not match.
# 1040xxx is the reserved purchased-parts range; 1030xxx is custom parts.
_PURCHASED_PREFIX = "1040"
_CUSTOM_PREFIX = "1030"


def classify_procurement(part_number: Optional[str]) -> str:
    """Return ``'purchased'`` | ``'custom'`` | ``'unknown'`` for a part number.

    Explicit allow-list wins over the numeric-prefix heuristic.
    """
    pn = (part_number or "").strip()
    if not pn:
        return "unknown"
    if pn in KNOWN_PURCHASED_PNS:
        return "purchased"
    if pn in KNOWN_CUSTOM_PNS:
        return "custom"
    if pn.startswith(_PURCHASED_PREFIX):
        return "purchased"
    if pn.startswith(_CUSTOM_PREFIX):
        return "custom"
    return "unknown"


# ---------------------------------------------------------------------------
# BOM row normalization
# ---------------------------------------------------------------------------

def _row_payload(row: dict) -> dict:
    """Trim a raw BOM highlight row to the fields the frontend needs."""
    return {
        "row_index": row.get("row_index"),
        "item_no": row.get("item_no"),
        "part_no": row.get("part_no"),
        "description": row.get("description"),
        "qty": row.get("qty"),
        "row_bounds_sheet": row.get("row_bounds_sheet"),
        "row_bounds_image": row.get("row_bounds_image"),
    }


def _qty_to_int(qty_value) -> int:
    """Parse a BOM ``qty`` field as an int. Returns 0 on failure (treated as unknown)."""
    if qty_value is None:
        return 0
    try:
        return int(str(qty_value).strip())
    except (ValueError, TypeError):
        return 0


def _index_rows_by_pn(bom_highlights: dict):
    """Index BOM highlight rows by ``part_no`` and capture BOM order.

    Returns ``(indexed, order)`` where ``indexed`` is ``{pn: row_dict}`` and
    ``order`` is a list of part numbers in the order they first appear in the
    BOM (header rows skipped). If a PN appears multiple times the last
    occurrence wins for the row payload, but the PN is recorded in the order
    list only at its first occurrence.
    """
    indexed: dict = {}
    order: list = []
    for row in (bom_highlights or {}).get("rows", []) or []:
        if row.get("is_header"):
            continue
        pn = (row.get("part_no") or "").strip()
        if not pn:
            continue
        if pn not in indexed:
            order.append(pn)
        indexed[pn] = row
    return indexed, order


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

def compute_bom_compare(
    bom_highlights_a: dict,
    bom_highlights_b: dict,
    *,
    supplier_evidence_a: Optional[Callable[[str], bool]] = None,
    supplier_evidence_b: Optional[Callable[[str], bool]] = None,
) -> dict:
    """Compute a normalized BOM compare payload for two revisions.

    Args:
        bom_highlights_a: parsed ``*_bom_row_highlights.json`` for revision A
        bom_highlights_b: parsed ``*_bom_row_highlights.json`` for revision B
        supplier_evidence_a: optional ``callable(part_number) -> bool`` that
            returns ``True`` when revision A has a supplier-spec sidecar for
            the given part number. Used together with ``supplier_evidence_b``
            to detect supplier-evidence asymmetry; see ``substitution_unverified``.
        supplier_evidence_b: same role as ``supplier_evidence_a`` for revision B.

    Returns:
        ``dict`` with keys ``rows``, ``summary``, ``honesty_notes``.
    """
    rows_a, order_a = _index_rows_by_pn(bom_highlights_a)
    rows_b, order_b = _index_rows_by_pn(bom_highlights_b)

    # Preserve BOM order so the panel lines up with the visible BOM in the
    # drawing. Rev B is primary because the compare typically reads as
    # "what changed from A to B" — the new state should drive the row
    # sequence. Rows that exist only in Rev A (removed) are appended at the
    # end in their original Rev A order so they do not get re-sorted away.
    seen_in_b = set(order_b)
    pn_order = list(order_b) + [pn for pn in order_a if pn not in seen_in_b]

    rows = []
    for display_index, pn in enumerate(pn_order, start=1):
        in_a = pn in rows_a
        in_b = pn in rows_b
        row_a = _row_payload(rows_a[pn]) if in_a else None
        row_b = _row_payload(rows_b[pn]) if in_b else None
        procurement = classify_procurement(pn)

        substitution_evidence = None  # filled in only for the unverified case

        if in_a and not in_b:
            diff_status = "removed"
        elif in_b and not in_a:
            diff_status = "added"
        else:
            qty_a = _qty_to_int(row_a.get("qty"))
            qty_b = _qty_to_int(row_b.get("qty"))
            if qty_a != qty_b:
                diff_status = "qty_changed"
            else:
                # Same PN, same qty. Default to unchanged. Promote to
                # substitution_unverified ONLY when we have positive evidence
                # of supplier-evidence asymmetry between the two revisions
                # (sidecar present for one rev, absent for the other) AND
                # the row is purchased. We never claim substitution; we
                # only flag that the BOM cannot rule it out.
                supplier_a_present = bool(supplier_evidence_a and supplier_evidence_a(pn))
                supplier_b_present = bool(supplier_evidence_b and supplier_evidence_b(pn))
                if procurement == "purchased" and supplier_a_present != supplier_b_present:
                    diff_status = "substitution_unverified"
                    substitution_evidence = {
                        "supplier_spec_in_revA": supplier_a_present,
                        "supplier_spec_in_revB": supplier_b_present,
                        "reason": (
                            "supplier_spec sidecar asymmetry: present in one "
                            "revision but missing in the other"
                        ),
                    }
                else:
                    diff_status = "unchanged"

        row = {
            "key": pn,
            "display_order": display_index,
            "rev_a": row_a,
            "rev_b": row_b,
            "diff_status": diff_status,
            "procurement": procurement,
        }
        if substitution_evidence is not None:
            row["substitution_evidence"] = substitution_evidence
        rows.append(row)

    # ------------------------------------------------------------------
    # Summary + honesty notes
    # ------------------------------------------------------------------
    counts = {
        "added": 0,
        "removed": 0,
        "qty_changed": 0,
        "unchanged": 0,
        "substitution_unverified": 0,
    }
    procurement_counts = {"purchased": 0, "custom": 0, "unknown": 0}
    for r in rows:
        counts[r["diff_status"]] += 1
        procurement_counts[r["procurement"]] += 1

    proven_changed = counts["added"] + counts["removed"] + counts["qty_changed"]

    honesty_notes = []
    if counts["substitution_unverified"] > 0:
        honesty_notes.append(
            "substitution_unverified rows have the same internal part number "
            "and quantity in both revisions, but a supplier-spec sidecar is "
            "present for one revision and missing for the other. This is a "
            "soft signal, not a proven substitution. These rows are excluded "
            "from the 'Changed only' filter by default."
        )
    if proven_changed == 0 and counts["substitution_unverified"] == 0:
        honesty_notes.append(
            "No proven structural BOM differences detected between the two "
            "revisions. Hardware substitution detection across same internal "
            "PNs cannot be performed from BOM data alone."
        )

    return {
        "rows": rows,
        "summary": {
            "added": counts["added"],
            "removed": counts["removed"],
            "qty_changed": counts["qty_changed"],
            "unchanged": counts["unchanged"],
            "substitution_unverified": counts["substitution_unverified"],
            "proven_changed": proven_changed,
            "procurement": procurement_counts,
            "total_rows": len(rows),
        },
        "honesty_notes": honesty_notes,
    }
