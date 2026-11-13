"""One publication safety-symbol vocabulary, consumed by compilers and PDF drawing."""
from copy import deepcopy

SAFETY_SYMBOL_STYLES = {
    "DANGER": {"kind": "safety_alert", "color": (0.78, 0.04, 0.09)},
    "WARNING": {"kind": "safety_alert", "color": (0.93, 0.39, 0.05)},
    "CAUTION": {"kind": "safety_alert", "color": (0.90, 0.67, 0.03)},
    "NOTICE": {"kind": "notice_information", "color": (0.03, 0.43, 0.67)},
}


def safety_symbol_semantics(signal_word):
    return deepcopy(SAFETY_SYMBOL_STYLES.get(str(signal_word or "NOTICE").upper(), SAFETY_SYMBOL_STYLES["NOTICE"]))


def annotate_safety_symbols(pages):
    for page in pages:
        for block in page.get("layoutBlocks", []):
            if block.get("blockType") in {"note", "status_panel", "draft_banner"}:
                block["safetySymbol"] = safety_symbol_semantics(block.get("signalWord") or block.get("tone"))
