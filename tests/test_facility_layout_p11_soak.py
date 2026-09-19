from __future__ import annotations

from pathlib import Path

from tools.verify_facility_layout_p11 import (
    build_real_soak_evidence,
    run_accelerated_soak,
)


def test_accelerated_soak_proves_mechanics_but_not_elapsed_time(
    tmp_path: Path,
):
    ledger = run_accelerated_soak(
        tmp_path / "soak",
        real_soak_evidence=build_real_soak_evidence(
            tmp_path / "missing-real-soak-ledger.json"
        ),
    )
    accelerated = ledger["acceleratedDeterministicSoak"]
    counts = accelerated["counts"]

    assert accelerated["status"] == "passed"
    assert all(accelerated["checks"].values())
    assert counts["layouts"] >= 10
    assert counts["proposalPreviews"] >= 20
    assert counts["approvedReceiptBackedApplies"] >= 10
    assert counts["byteIdenticalDismissals"] >= 5
    assert counts["rejectedStaleOrUnauthorizedAttempts"] >= 5
    assert counts["reopenCyclesPerLayout"] >= 5

    receipts = accelerated["canonicalReceipts"]
    assert len(receipts) >= 10
    assert len({item["receiptId"] for item in receipts}) == len(receipts)
    assert all(
        item["retrievedExactly"]
        and item["replayReceiptMatches"]
        and len(item["canonicalReceiptSha256"]) == 64
        for item in receipts
    )

    literal = ledger["realElapsedSoak"]
    assert literal["status"] == "not_started"
    assert literal["checks"]["evidenceLedgerPresent"] is False
    assert literal["releaseGateMet"] is False
    assert ledger["releaseGateMet"] is False
