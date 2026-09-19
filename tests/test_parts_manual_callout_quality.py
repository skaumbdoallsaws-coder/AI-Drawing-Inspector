"""Deterministic unit tests for server-recomputed callout quality metrics.

These are pure functions over a balloon manifest, so they run without a browser
and prove the publication gate can measure elegance independently of whatever
the client reports.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.parts_manual.version import (  # noqa: E402
    PARTS_MANUAL_DEFAULT_END_CONDITION,
    PARTS_MANUAL_RENDER_PIPELINE_VERSION,
)
from ai_inspector.parts_manual.artifacts import (  # noqa: E402
    PARTS_MANUAL_DEFAULT_REPEATED_PART_STRATEGY,
    PARTS_MANUAL_MIN_BALLOON_GAP,
    _balloon_lane_aligned_count,
    _frame_clip_balloon_count,
    _maximum_elbow_count,
    _minimum_balloon_gap,
    _repeated_items_without_indication,
    _requested_repeated_strategy,
    _soft_parallel_pair_count,
)


def _row(item, bx, by, tx, ty, path=None, **extra):
    row = {
        "itemNumber": item,
        "balloon": {"x": bx, "y": by},
        "target": {"x": tx, "y": ty},
        "leaderPath": [dict(point) for point in (path or [])],
        "branches": [],
        "representativeCount": 1,
        "calloutType": "single",
    }
    row.update(extra)
    return row


def test_minimum_balloon_gap_detects_crowding():
    crowded = [_row(1, 0.30, 0.30, 0.40, 0.40), _row(2, 0.33, 0.32, 0.45, 0.45)]
    spaced = [_row(1, 0.20, 0.20, 0.40, 0.40), _row(2, 0.20, 0.40, 0.45, 0.45)]
    assert _minimum_balloon_gap(crowded) < PARTS_MANUAL_MIN_BALLOON_GAP
    assert _minimum_balloon_gap(spaced) >= PARTS_MANUAL_MIN_BALLOON_GAP


def test_frame_clip_counts_only_balloons_outside_the_safe_margin():
    rows = [
        _row(1, 0.5, 0.5, 0.4, 0.4),      # safe
        _row(2, 0.005, 0.5, 0.4, 0.4),    # clipped left
        _row(3, 0.5, 0.995, 0.4, 0.4),    # clipped bottom
    ]
    assert _frame_clip_balloon_count(rows) == 2


def test_soft_parallel_detects_congestion_the_strict_predicate_misses():
    # two long vertical leaders 3% apart: not exactly coincident, but a human
    # reads them as congested.
    rows = [
        _row(1, 0.40, 0.20, 0.40, 0.60),
        _row(2, 0.43, 0.20, 0.43, 0.60),
    ]
    assert _soft_parallel_pair_count(rows) >= 1

    far = [
        _row(1, 0.20, 0.20, 0.20, 0.60),
        _row(2, 0.80, 0.20, 0.80, 0.60),
    ]
    assert _soft_parallel_pair_count(far) == 0


def test_maximum_elbow_count_counts_direction_changes():
    straight = [_row(1, 0.20, 0.50, 0.60, 0.50)]
    dogleg = [_row(
        1, 0.20, 0.20, 0.60, 0.60,
        path=[{"x": 0.60, "y": 0.40}, {"x": 0.20, "y": 0.40}],
    )]
    assert _maximum_elbow_count(straight) == 0
    assert _maximum_elbow_count(dogleg) >= 1


def test_repeated_items_require_branches_or_a_count_badge():
    missing = [_row(1, 0.2, 0.2, 0.4, 0.4, representativeCount=2)]
    badged = [_row(
        1, 0.2, 0.2, 0.4, 0.4,
        representativeCount=2, calloutType="representative_with_count",
    )]
    branched = [_row(
        1, 0.2, 0.2, 0.4, 0.4,
        representativeCount=2, calloutType="branched",
        branches=[{"target": {"x": 0.5, "y": 0.5}}],
    )]
    assert _repeated_items_without_indication(missing) == [1]
    assert _repeated_items_without_indication(badged) == []
    assert _repeated_items_without_indication(branched) == []


def test_lane_alignment_is_reported_as_evidence():
    aligned = [
        _row(1, 0.15, 0.20, 0.4, 0.4),
        _row(2, 0.15, 0.50, 0.4, 0.4),
        _row(3, 0.85, 0.30, 0.4, 0.4),
    ]
    # items 1 and 2 share a lane; item 3 does not
    assert _balloon_lane_aligned_count(aligned) == 2


def test_metrics_are_deterministic_across_repeated_calls():
    rows = [
        _row(1, 0.15, 0.20, 0.40, 0.30),
        _row(2, 0.15, 0.45, 0.42, 0.50),
        _row(3, 0.85, 0.30, 0.60, 0.35, representativeCount=2,
             calloutType="representative_with_count"),
    ]
    first = (
        _minimum_balloon_gap(rows),
        _frame_clip_balloon_count(rows),
        _soft_parallel_pair_count(rows),
        _maximum_elbow_count(rows),
        _balloon_lane_aligned_count(rows),
        tuple(_repeated_items_without_indication(rows)),
    )
    for _ in range(5):
        again = (
            _minimum_balloon_gap(rows),
            _frame_clip_balloon_count(rows),
            _soft_parallel_pair_count(rows),
            _maximum_elbow_count(rows),
            _balloon_lane_aligned_count(rows),
            tuple(_repeated_items_without_indication(rows)),
        )
        assert again == first


# --- repeated-part strategy resolution -------------------------------------
#
# Automatic generation must produce one balloon, one leader and an nX badge for
# every repeated part. A branched (Y-shaped) leader stays supported but is only
# reachable when a user explicitly authored one, so the entitlement resolver is
# what keeps the generator from choosing it on its own.

_ITEM = {"itemNumber": 4, "calloutId": "callout-item-4"}


def _request(*, contract_default=None, override=None, callout_id="callout-item-4"):
    request = {"calloutItems": [dict(_ITEM)]}
    if contract_default is not None:
        request["calloutContract"] = {"defaultRepeatedPartStrategy": contract_default}
    if override is not None:
        request["composition"] = {"leaderOverrides": {callout_id: override}}
    return request


def test_repeated_strategy_defaults_to_a_single_counted_leader():
    assert PARTS_MANUAL_DEFAULT_REPEATED_PART_STRATEGY == "representative_with_count"
    assert (
        _requested_repeated_strategy(_request(), _ITEM)
        == "representative_with_count"
    )
    assert (
        _requested_repeated_strategy(
            _request(contract_default="representative_with_count"), _ITEM
        )
        == "representative_with_count"
    )


def test_repeated_strategy_honours_an_explicit_branched_override():
    request = _request(override={"repeatedPartStrategy": "branched"})
    assert _requested_repeated_strategy(request, _ITEM) == "branched"


def test_repeated_strategy_ignores_unrelated_or_invalid_overrides():
    # An override on a different callout must not entitle this one.
    other = _request(
        override={"repeatedPartStrategy": "branched"}, callout_id="callout-item-9"
    )
    assert _requested_repeated_strategy(other, _ITEM) == "representative_with_count"

    # Leader overrides that carry no strategy, or a value outside the contract,
    # leave the default in place rather than being taken at face value.
    for override in (
        {},
        {"anchorSide": "left"},
        {"repeatedPartStrategy": ""},
        {"repeatedPartStrategy": "star_burst"},
    ):
        assert (
            _requested_repeated_strategy(_request(override=override), _ITEM)
            == "representative_with_count"
        )


def test_repeated_strategy_resolves_a_callout_id_from_its_item_number():
    """Rows predating explicit callout ids still resolve their override."""
    request = _request(override={"repeatedPartStrategy": "branched"})
    assert _requested_repeated_strategy(request, {"itemNumber": 4}) == "branched"
    assert (
        _requested_repeated_strategy(request, {"itemNumber": 5})
        == "representative_with_count"
    )


def test_repeated_indication_accepts_a_counted_representative_callout():
    """A qty>1 row with one leader still counts as indicated via its nX badge."""
    counted = _row(
        4, 0.7, 0.4, 0.4, 0.4,
        representativeCount=2,
        quantityLabel="2X",
        calloutType="representative_with_count",
    )
    assert _repeated_items_without_indication([counted]) == []

    silent = dict(counted)
    silent["calloutType"] = "single"
    assert _repeated_items_without_indication([silent]) == [4]


# --- automatic leader endpoint ---------------------------------------------


def test_automatic_parts_manual_leaders_terminate_on_a_dot():
    """Generated leaders end on a small solid dot, not an arrowhead."""
    assert PARTS_MANUAL_DEFAULT_END_CONDITION == "dot"

    from ai_inspector.parts_manual import document as document_module
    from ai_inspector.parts_manual import documentation as documentation_module
    from ai_inspector.parts_manual import artifacts as artifacts_module
    from ai_inspector.parts_manual import pdf as pdf_module

    # Every module that materialises the generated default agrees, so the
    # viewport, the manifest gate and the PDF cannot disagree about the endpoint.
    for module in (document_module, artifacts_module, pdf_module):
        assert module.PARTS_MANUAL_DEFAULT_END_CONDITION == "dot"
    assert documentation_module.DOCUMENTATION_DEFAULT_END_CONDITION == "dot"

    # An arrowhead stays reachable, just never by default.
    assert "arrow" in documentation_module.DOCUMENTATION_LEADER_END_CONDITIONS


def test_render_pipeline_version_invalidates_branch_and_arrow_captures():
    """v4 captures carry branched leaders and arrowheads; they must not publish."""
    assert PARTS_MANUAL_RENDER_PIPELINE_VERSION >= 5
