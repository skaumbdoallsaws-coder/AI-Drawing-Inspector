"""Local pricing table for runtime cost estimation.

Per docs/usage-cost-dashboard-plan.md §5:
- Rates are USD per million tokens.
- Each telemetry event stores the computed `estimatedCostUsd` at write time
  so historical events stay correct if rates are later updated.
- Cost confidence is carried per event so the dashboard can label
  "estimated" rates separately from "verified" ones.

Per user direction at Phase 1 kick-off: "If exact pricing is uncertain,
mark pricing entry as estimated/unknown and set cost to 0 rather than
guessing silently." This module honors that by:
- Marking every entry below `confidence="estimated"` (best-known but not
  verified against current provider published pricing).
- Returning cost=0.0 + confidence="unknown" when the (provider, model)
  pair is not in the table OR is in the table with confidence="unknown".
- Never silently computing a cost without a confidence label.

Verify these rates against current provider pricing before reporting any
absolute cost number externally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# Confidence values used on PricingEntry.confidence and on the return
# value of compute_cost(). Centralised here so other modules + tests
# refer to the literals via constant import rather than string copies.
CONFIDENCE_VERIFIED  = "verified"
CONFIDENCE_ESTIMATED = "estimated"
CONFIDENCE_UNKNOWN   = "unknown"


@dataclass(frozen=True)
class PricingEntry:
    provider: str
    model:    str
    effectiveDate: str   # ISO date this rate became effective in our records.
    inputCostPerMillionTokens:      float
    outputCostPerMillionTokens:     float
    cacheReadCostPerMillionTokens:  float = 0.0
    cacheWriteCostPerMillionTokens: float = 0.0
    confidence: str = CONFIDENCE_ESTIMATED
    notes:      str = ""


# Known models in this repo. Survey performed 2026-05-18 across:
#   server.py
#   ai_inspector/spatial/engine.py
#   ai_inspector/report/qc_report.py
#
# All entries below are marked `confidence="estimated"` because the
# planner cannot verify rates against the current Anthropic/OpenAI
# published pricing pages from this environment. The dashboard should
# render any aggregated cost number with an "estimated" qualifier
# until a verified rate refresh lands.
PRICING_TABLE: Dict[Tuple[str, str], PricingEntry] = {
    # ── Anthropic ─────────────────────────────────────────────────
    ("anthropic", "claude-sonnet-4-5-20250929"): PricingEntry(
        provider="anthropic", model="claude-sonnet-4-5-20250929",
        effectiveDate="2026-05-18",
        inputCostPerMillionTokens=3.00,
        outputCostPerMillionTokens=15.00,
        cacheReadCostPerMillionTokens=0.30,
        cacheWriteCostPerMillionTokens=3.75,
        confidence=CONFIDENCE_ESTIMATED,
        notes="Sonnet 4.5 (Sep 2025). Best-known rates as of plan author's "
              "knowledge cutoff; verify before reporting cost numbers externally.",
    ),
    ("anthropic", "claude-haiku-4-5-20251001"): PricingEntry(
        provider="anthropic", model="claude-haiku-4-5-20251001",
        effectiveDate="2026-05-18",
        inputCostPerMillionTokens=0.80,
        outputCostPerMillionTokens=4.00,
        cacheReadCostPerMillionTokens=0.08,
        cacheWriteCostPerMillionTokens=1.00,
        confidence=CONFIDENCE_ESTIMATED,
        notes="Haiku 4.5 (Oct 2025). Estimated; verify.",
    ),
    ("anthropic", "claude-sonnet-4-20250514"): PricingEntry(
        provider="anthropic", model="claude-sonnet-4-20250514",
        effectiveDate="2026-05-18",
        inputCostPerMillionTokens=3.00,
        outputCostPerMillionTokens=15.00,
        cacheReadCostPerMillionTokens=0.30,
        cacheWriteCostPerMillionTokens=3.75,
        confidence=CONFIDENCE_ESTIMATED,
        notes="Sonnet 4 (May 2025). Estimated; verify.",
    ),

    # ── OpenAI ────────────────────────────────────────────────────
    ("openai", "gpt-4o"): PricingEntry(
        provider="openai", model="gpt-4o",
        effectiveDate="2026-05-18",
        inputCostPerMillionTokens=2.50,
        outputCostPerMillionTokens=10.00,
        confidence=CONFIDENCE_ESTIMATED,
        notes="Estimated. OpenAI cache pricing model differs from Anthropic; "
              "cache fields left at 0.0 until we model that surface.",
    ),
    ("openai", "gpt-4o-mini"): PricingEntry(
        provider="openai", model="gpt-4o-mini",
        effectiveDate="2026-05-18",
        inputCostPerMillionTokens=0.15,
        outputCostPerMillionTokens=0.60,
        confidence=CONFIDENCE_ESTIMATED,
        notes="Estimated; verify.",
    ),
    ("openai", "whisper-1"): PricingEntry(
        provider="openai", model="whisper-1",
        effectiveDate="2026-05-18",
        inputCostPerMillionTokens=0.0,
        outputCostPerMillionTokens=0.0,
        confidence=CONFIDENCE_UNKNOWN,
        notes="Whisper is priced per AUDIO MINUTE, not per token. The token-cost "
              "model does not apply. This entry exists so lookups do not 404; "
              "cost calculation always returns 0.0 for this model. Audio-minute "
              "pricing belongs in a separate dimension not yet modeled — track "
              "in a Phase 2+ enhancement.",
    ),
}


def lookup_pricing(provider: str, model: str) -> Optional[PricingEntry]:
    """Return PricingEntry or None if (provider, model) not in the table.

    Both args are treated as exact-match (no fuzzy lookup) — a typo in the
    provider/model identifier deserves a None and a 0.0 cost rather than a
    coincidental near-match.
    """
    if not provider or not model:
        return None
    return PRICING_TABLE.get((provider, model))


def compute_cost(
    provider: str,
    model:    str,
    *,
    inputTokens:      int = 0,
    outputTokens:     int = 0,
    cacheReadTokens:  int = 0,
    cacheWriteTokens: int = 0,
) -> Tuple[float, str]:
    """Compute estimated USD cost for a single provider call.

    Returns (cost_usd, confidence).

    confidence values:
      - "verified":  rates confirmed against provider's current pricing.
                     No entry in PRICING_TABLE carries this today.
      - "estimated": rates are best-known but unverified; cost is computed.
      - "unknown":   no usable rate; cost is always 0.0. Returned when the
                     (provider, model) pair is not in the table OR when
                     the entry's own confidence is "unknown".

    Negative token counts are treated as 0 (defensive — Anthropic's cache
    token fields can be absent in some response shapes and a caller
    miscounting them as -1 should not flip the cost sign).
    """
    entry = lookup_pricing(provider, model)
    if entry is None or entry.confidence == CONFIDENCE_UNKNOWN:
        return 0.0, CONFIDENCE_UNKNOWN

    it = max(0, int(inputTokens or 0))
    ot = max(0, int(outputTokens or 0))
    cr = max(0, int(cacheReadTokens or 0))
    cw = max(0, int(cacheWriteTokens or 0))

    cost = (
        it * entry.inputCostPerMillionTokens
        + ot * entry.outputCostPerMillionTokens
        + cr * entry.cacheReadCostPerMillionTokens
        + cw * entry.cacheWriteCostPerMillionTokens
    ) / 1_000_000.0

    return cost, entry.confidence
