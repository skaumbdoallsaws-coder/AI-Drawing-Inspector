"""Run a source-bound automated accessibility audit on Facility Layout.

The runner exercises the production InspectorPro shell and Facility Layout
workspace in Chromium. It deliberately does not claim to perform a manual
screen-reader audit. Automated evidence and the human checklist remain
separate release gates.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import sys
import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Route,
    sync_playwright,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "accessibility"
)
MANUAL_CHECKLIST = (
    ROOT / "docs" / "facility-layout-manual-screen-reader-checklist.md"
)
SOURCE_PATHS = (
    "static/index.html",
    "static/facility_layout_app.js",
    "static/facility_layout_editor.js",
    "static/facility_layout_session.js",
    "static/facility_layout_three_adapter.js",
    "static/facility_layout_transport.js",
    "static/facility_layout_workspace.css",
    "static/facility_layout_workspace.js",
    "tools/audit_facility_layout_accessibility.py",
)
THEMES = ("light", "dark")
RAW_SCHEMA = "facility-layout-accessibility-raw-v1"
SUMMARY_SCHEMA = "facility-layout-accessibility-summary-v1"

CATEGORY_CHECKS: dict[str, tuple[str, ...]] = {
    "keyboard": (
        "enteredWorkspaceByTab",
        "forwardTraversalProgresses",
        "reverseTraversalExitsWorkspace",
        "noKeyboardTrap",
        "shortcutActionWorks",
        "assetActionWorks",
        "undoActionWorks",
        "tabKeyboardActivationWorks",
    ),
    "focus": (
        "samplesPresent",
        "allSamplesUseFocusVisible",
        "allSamplesHaveVisibleIndicator",
        "focusScreenshotsCaptured",
    ),
    "semantics": (
        "ariaSnapshotCaptured",
        "workspaceNamed",
        "toolbarNamed",
        "treeNamed",
        "treeItemsNamed",
        "tabsNamed",
        "tabStateValid",
        "panelsNamed",
        "controlsNamed",
        "busyStatePresent",
        "pressedStatePresent",
        "duplicateIdsAbsent",
    ),
    "announcements": (
        "liveRegionsPresent",
        "announcementsObserved",
        "actionAnnouncementObserved",
    ),
    "reducedMotion": (
        "mediaQueryMatched",
        "transitionsSuppressed",
        "animationsSuppressed",
    ),
    "contrast": (
        "bothThemesMeasured",
        "textSamplesPresent",
        "controlSamplesPresent",
        "textContrastPasses",
        "controlContrastPasses",
    ),
    "network": (
        "blockingPolicyInstalled",
        "externalBlockCanaryObserved",
        "sameOriginApplicationLoaded",
        "noExternalResponses",
    ),
    "runtime": (
        "auditCompleted",
        "sourceStableDuringAudit",
        "noPageErrors",
        "noConsoleErrors",
    ),
}


CONTRAST_SCRIPT = r"""
({ rootSelector, maximumTextSamples, maximumControlSamples }) => {
    const root = document.querySelector(rootSelector);
    if (!root) throw new Error('Facility workspace is missing');

    const number = value => Number.isFinite(Number(value))
        ? Number(value) : 0;

    const parseColor = raw => {
        const value = String(raw || '').trim().toLowerCase();
        if (!value || value === 'transparent') return [0, 0, 0, 0];
        const match = value.match(/^rgba?\((.*)\)$/);
        if (!match) {
            const canvas = document.createElement('canvas');
            const context = canvas.getContext('2d');
            context.fillStyle = '#010203';
            context.fillStyle = value;
            const normalized = context.fillStyle;
            if (normalized === value || normalized === '#010203') {
                if (/^#[0-9a-f]{6}$/i.test(normalized)) {
                    return [
                        parseInt(normalized.slice(1, 3), 16),
                        parseInt(normalized.slice(3, 5), 16),
                        parseInt(normalized.slice(5, 7), 16),
                        1,
                    ];
                }
                return null;
            }
            return parseColor(normalized);
        }
        const body = match[1].replace(/\s*\/\s*/, ',');
        let parts = body.includes(',')
            ? body.split(',').map(item => item.trim())
            : body.split(/\s+/).map(item => item.trim());
        if (parts.length < 3) return null;
        const channel = item => item.endsWith('%')
            ? Math.max(0, Math.min(255, number(item.slice(0, -1)) * 2.55))
            : Math.max(0, Math.min(255, number(item)));
        const alpha = parts.length > 3
            ? (parts[3].endsWith('%')
                ? number(parts[3].slice(0, -1)) / 100
                : number(parts[3]))
            : 1;
        return [
            channel(parts[0]),
            channel(parts[1]),
            channel(parts[2]),
            Math.max(0, Math.min(1, alpha)),
        ];
    };

    const over = (foreground, background) => {
        const alpha = foreground[3] + background[3] * (1 - foreground[3]);
        if (alpha <= 0) return [0, 0, 0, 0];
        return [
            (
                foreground[0] * foreground[3]
                + background[0] * background[3] * (1 - foreground[3])
            ) / alpha,
            (
                foreground[1] * foreground[3]
                + background[1] * background[3] * (1 - foreground[3])
            ) / alpha,
            (
                foreground[2] * foreground[3]
                + background[2] * background[3] * (1 - foreground[3])
            ) / alpha,
            alpha,
        ];
    };

    const effectiveBackground = element => {
        let result = [0, 0, 0, 0];
        let current = element;
        while (current && current.nodeType === Node.ELEMENT_NODE) {
            const layer = parseColor(getComputedStyle(current).backgroundColor);
            if (layer) result = over(result, layer);
            current = current.parentElement;
        }
        return over(result, [255, 255, 255, 1]);
    };

    const luminance = color => {
        const channels = color.slice(0, 3).map(value => {
            const normalized = value / 255;
            return normalized <= 0.04045
                ? normalized / 12.92
                : Math.pow((normalized + 0.055) / 1.055, 2.4);
        });
        return 0.2126 * channels[0]
            + 0.7152 * channels[1]
            + 0.0722 * channels[2];
    };

    const ratio = (first, second) => {
        const left = luminance(first);
        const right = luminance(second);
        return (Math.max(left, right) + 0.05)
            / (Math.min(left, right) + 0.05);
    };

    const visible = element => {
        if (!element || element.hidden) return false;
        if (element.closest(
                '[aria-hidden="true"], .ip-flw-visually-hidden'
        )) return false;
        const style = getComputedStyle(element);
        if (style.display === 'none'
                || style.visibility === 'hidden'
                || number(style.opacity) === 0) return false;
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    };

    const label = element => {
        const explicit = element.getAttribute('aria-label');
        if (explicit) return explicit.trim();
        const text = String(element.textContent || '')
            .replace(/\s+/g, ' ').trim();
        if (text) return text.slice(0, 160);
        return (
            element.getAttribute('placeholder')
            || element.getAttribute('title')
            || element.id
            || element.tagName.toLowerCase()
        ).slice(0, 160);
    };

    const directText = element => Array.from(element.childNodes)
        .filter(node => node.nodeType === Node.TEXT_NODE)
        .map(node => String(node.nodeValue || '').replace(/\s+/g, ' ').trim())
        .filter(Boolean)
        .join(' ');

    const textCandidates = Array.from(root.querySelectorAll('*'))
        .filter(visible)
        .filter(element => directText(element))
        .slice(0, maximumTextSamples);
    const textSamples = textCandidates.map((element, index) => {
        const style = getComputedStyle(element);
        const background = effectiveBackground(element);
        const foregroundRaw = parseColor(style.color);
        const foreground = foregroundRaw
            ? over(foregroundRaw, background) : null;
        const fontSize = number(style.fontSize.replace('px', ''));
        const weight = number(style.fontWeight) || (
            String(style.fontWeight).toLowerCase() === 'bold' ? 700 : 400
        );
        const requiredRatio = (
            fontSize >= 24 || (fontSize >= 18.66 && weight >= 700)
        ) ? 3 : 4.5;
        const measuredRatio = foreground
            ? ratio(foreground, background) : 0;
        return {
            sampleId: 'text-' + String(index + 1).padStart(3, '0'),
            selectorHint: (
                element.id ? '#' + element.id
                : element.classList.length
                    ? element.tagName.toLowerCase() + '.'
                        + Array.from(element.classList).slice(0, 2).join('.')
                    : element.tagName.toLowerCase()
            ),
            label: directText(element).slice(0, 160),
            fontSizePx: fontSize,
            fontWeight: weight,
            foreground: style.color,
            background: style.backgroundColor,
            contrastRatio: Number(measuredRatio.toFixed(3)),
            requiredRatio,
            passed: measuredRatio + 0.001 >= requiredRatio,
        };
    });

    const controlSelector = [
        'button:not(:disabled)',
        'input:not(:disabled)',
        '[role="treeitem"][tabindex]',
        '[role="tab"][tabindex]',
        '[role="tabpanel"][tabindex]',
    ].join(',');
    const controlCandidates = Array.from(
        root.querySelectorAll(controlSelector)
    ).filter(visible).slice(0, maximumControlSamples);
    const controlSamples = controlCandidates.map((element, index) => {
        const style = getComputedStyle(element);
        const background = effectiveBackground(element);
        const outside = effectiveBackground(element.parentElement || element);
        const foregroundRaw = parseColor(style.color);
        const foreground = foregroundRaw
            ? over(foregroundRaw, background) : null;
        const ownBackground = parseColor(style.backgroundColor);
        const visibleFill = ownBackground && ownBackground[3] > 0
            ? over(ownBackground, outside) : background;
        const border = parseColor(style.borderTopColor);
        const borderWidth = number(style.borderTopWidth.replace('px', ''));
        const textRatio = foreground ? ratio(foreground, background) : 0;
        const borderRatio = border && borderWidth > 0
            ? ratio(over(border, outside), outside) : 0;
        const fillRatio = ratio(visibleFill, outside);
        const measuredRatio = Math.max(textRatio, borderRatio, fillRatio);
        return {
            sampleId: 'control-' + String(index + 1).padStart(3, '0'),
            selectorHint: (
                element.id ? '#' + element.id
                : element.getAttribute('data-command')
                    ? '[data-command="' + element.getAttribute(
                        'data-command'
                    ) + '"]'
                    : element.getAttribute('data-view')
                        ? '[data-view="' + element.getAttribute(
                            'data-view'
                        ) + '"]'
                        : element.tagName.toLowerCase()
            ),
            label: label(element),
            foregroundContrast: Number(textRatio.toFixed(3)),
            borderContrast: Number(borderRatio.toFixed(3)),
            fillContrast: Number(fillRatio.toFixed(3)),
            contrastRatio: Number(measuredRatio.toFixed(3)),
            requiredRatio: 3,
            passed: measuredRatio + 0.001 >= 3,
        };
    });

    return {
        textSamples,
        controlSamples,
        textFailures: textSamples.filter(item => !item.passed),
        controlFailures: controlSamples.filter(item => !item.passed),
        textSampleLimitReached:
            textCandidates.length >= maximumTextSamples,
        controlSampleLimitReached:
            controlCandidates.length >= maximumControlSamples,
    };
}
"""


SEMANTICS_SCRIPT = r"""
rootSelector => {
    const root = document.querySelector(rootSelector);
    if (!root) throw new Error('Facility workspace is missing');
    const visible = element => {
        if (!element || element.hidden) return false;
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== 'none'
            && style.visibility !== 'hidden'
            && rect.width > 0
            && rect.height > 0;
    };
    const name = element => {
        const explicit = element.getAttribute('aria-label');
        if (explicit) return explicit.trim();
        const labelledBy = element.getAttribute('aria-labelledby');
        if (labelledBy) {
            const result = labelledBy.split(/\s+/)
                .map(id => document.getElementById(id))
                .filter(Boolean)
                .map(node => String(node.textContent || '').trim())
                .filter(Boolean).join(' ');
            if (result) return result;
        }
        if (element.labels && element.labels.length) {
            const result = Array.from(element.labels)
                .map(node => String(node.textContent || '').trim())
                .filter(Boolean).join(' ');
            if (result) return result;
        }
        return String(
            element.textContent
            || element.getAttribute('title')
            || element.getAttribute('placeholder')
            || ''
        ).replace(/\s+/g, ' ').trim();
    };
    const role = element => {
        if (element.getAttribute('role')) return element.getAttribute('role');
        const tag = element.tagName.toLowerCase();
        if (tag === 'button') return 'button';
        if (tag === 'input') {
            return element.type === 'search' ? 'searchbox' : 'textbox';
        }
        if (tag === 'aside') return 'complementary';
        if (tag === 'main') return 'main';
        return 'generic';
    };
    const controls = Array.from(root.querySelectorAll(
        'button,input,[role="treeitem"],[role="tab"],[role="tabpanel"]'
    )).filter(visible).map(element => ({
        tag: element.tagName.toLowerCase(),
        role: role(element),
        name: name(element),
        disabled: Boolean(element.disabled),
        selected: element.getAttribute('aria-selected'),
        pressed: element.getAttribute('aria-pressed'),
        expanded: element.getAttribute('aria-expanded'),
        tabIndex: element.tabIndex,
    }));
    const tabs = Array.from(root.querySelectorAll('[role="tab"]')).map(
        element => ({
            name: name(element),
            selected: element.getAttribute('aria-selected'),
            tabIndex: element.tabIndex,
            disabled: Boolean(element.disabled),
        })
    );
    const ids = Array.from(root.querySelectorAll('[id]'))
        .map(element => element.id);
    const duplicates = Array.from(new Set(
        ids.filter((id, index) => ids.indexOf(id) !== index)
    )).sort();
    const treeItems = Array.from(
        root.querySelectorAll('[role="treeitem"]')
    ).filter(visible).map(element => name(element));
    const panels = Array.from(
        root.querySelectorAll('[role="tabpanel"]')
    ).map(element => ({
        name: name(element),
        hidden: Boolean(element.hidden),
        tabIndex: element.tabIndex,
    }));
    const liveRegions = Array.from(root.querySelectorAll('[aria-live]')).map(
        element => ({
            role: role(element),
            live: element.getAttribute('aria-live'),
            atomic: element.getAttribute('aria-atomic'),
            text: String(element.textContent || '')
                .replace(/\s+/g, ' ').trim(),
        })
    );
    const toolbar = root.querySelector('[role="toolbar"]');
    const tree = root.querySelector('[role="tree"]');
    const tablist = root.querySelector('[role="tablist"]');
    return {
        workspaceName: name(root),
        workspaceAriaBusy: root.getAttribute('aria-busy'),
        toolbar: toolbar ? { name: name(toolbar), role: role(toolbar) } : null,
        tree: tree ? { name: name(tree), role: role(tree) } : null,
        tablist: tablist
            ? { name: name(tablist), role: role(tablist) } : null,
        controls,
        tabs,
        panels,
        treeItems,
        liveRegions,
        duplicateIds: duplicates,
    };
}
"""


REDUCED_MOTION_SCRIPT = r"""
rootSelector => {
    const root = document.querySelector(rootSelector);
    if (!root) throw new Error('Facility workspace is missing');
    const milliseconds = raw => String(raw || '').split(',').reduce(
        (maximum, item) => {
            const value = item.trim();
            const parsed = parseFloat(value) || 0;
            const result = value.endsWith('ms') ? parsed : parsed * 1000;
            return Math.max(maximum, result);
        },
        0
    );
    const records = Array.from(root.querySelectorAll('*')).map(element => {
        const style = getComputedStyle(element);
        return {
            transitionMs: milliseconds(style.transitionDuration),
            animationMs: milliseconds(style.animationDuration),
            selectorHint: element.id
                ? '#' + element.id
                : element.tagName.toLowerCase(),
        };
    });
    const maximumTransitionMs = Math.max(
        0,
        ...records.map(item => item.transitionMs)
    );
    const maximumAnimationMs = Math.max(
        0,
        ...records.map(item => item.animationMs)
    );
    return {
        mediaQueryMatches: matchMedia(
            '(prefers-reduced-motion: reduce)'
        ).matches,
        maximumTransitionMs,
        maximumAnimationMs,
        transitionOffenders: records.filter(
            item => item.transitionMs > 0.011
        ).slice(0, 25),
        animationOffenders: records.filter(
            item => item.animationMs > 0.011
        ).slice(0, 25),
    };
}
"""


FOCUS_SCRIPT = r"""
() => {
    const element = document.activeElement;
    if (!element) return null;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return {
        tag: element.tagName.toLowerCase(),
        id: element.id || null,
        className: String(element.className || ''),
        command: element.getAttribute('data-command'),
        view: element.getAttribute('data-view'),
        role: element.getAttribute('role'),
        name: (
            element.getAttribute('aria-label')
            || element.textContent
            || element.getAttribute('placeholder')
            || ''
        ).replace(/\s+/g, ' ').trim().slice(0, 160),
        focusVisible: element.matches(':focus-visible'),
        outlineStyle: style.outlineStyle,
        outlineWidth: style.outlineWidth,
        outlineColor: style.outlineColor,
        outlineOffset: style.outlineOffset,
        boxShadow: style.boxShadow,
        rect: {
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
        },
    };
}
"""


ACTIVE_SCRIPT = r"""
rootSelector => {
    const element = document.activeElement;
    const root = document.querySelector(rootSelector);
    if (!element) return null;
    return {
        tag: element.tagName.toLowerCase(),
        id: element.id || null,
        command: element.getAttribute('data-command'),
        view: element.getAttribute('data-view'),
        role: element.getAttribute('role'),
        assetId: element.getAttribute('data-asset-id'),
        name: (
            element.getAttribute('aria-label')
            || element.textContent
            || element.getAttribute('placeholder')
            || ''
        ).replace(/\s+/g, ' ').trim().slice(0, 160),
        insideWorkspace: Boolean(root && root.contains(element)),
    };
}
"""


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _relative(path: Path, root: Path = ROOT) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _artifact(path: Path, root: Path = ROOT) -> dict[str, Any]:
    return {
        "path": _relative(path, root),
        "byteLength": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="ascii",
    )


def build_source_binding(
    root: Path = ROOT,
    source_paths: Sequence[str] = SOURCE_PATHS,
) -> dict[str, Any]:
    files = []
    resolved_root = root.resolve()
    for relative in sorted(source_paths):
        path = (root / relative).resolve()
        try:
            path.relative_to(resolved_root)
        except ValueError as error:
            raise ValueError(
                f"Accessibility source escapes the repository: {relative}"
            ) from error
        if not path.is_file():
            raise FileNotFoundError(
                f"Accessibility source is missing: {relative}"
            )
        files.append(
            {
                "path": relative,
                "byteLength": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return {
        "algorithm": "sha256",
        "aggregateAlgorithm": "sha256-canonical-json-v1",
        "files": files,
        "aggregateSha256": _sha256_bytes(_canonical_json_bytes(files)),
    }


def source_binding_status(
    captured: Any,
    *,
    root: Path = ROOT,
    source_paths: Sequence[str] = SOURCE_PATHS,
) -> dict[str, Any]:
    current = build_source_binding(root, source_paths)
    captured_map = captured if isinstance(captured, Mapping) else {}
    raw_files = captured_map.get("files")
    captured_files = raw_files if isinstance(raw_files, list) else []
    captured_by_path: dict[str, Mapping[str, Any]] = {}
    duplicates = []
    for item in captured_files:
        if not isinstance(item, Mapping):
            continue
        relative = str(item.get("path") or "")
        if relative in captured_by_path:
            duplicates.append(relative)
        captured_by_path[relative] = item
    current_by_path = {
        str(item["path"]): item for item in current["files"]
    }
    captured_paths = set(captured_by_path)
    current_paths = set(current_by_path)
    missing = sorted(current_paths - captured_paths)
    unexpected = sorted(captured_paths - current_paths)
    stale = sorted(
        relative
        for relative in captured_paths & current_paths
        if (
            captured_by_path[relative].get("sha256")
            != current_by_path[relative]["sha256"]
            or int(
                captured_by_path[relative].get("byteLength") or -1
            )
            != int(current_by_path[relative]["byteLength"])
        )
    )
    algorithms_match = (
        captured_map.get("algorithm") == current["algorithm"]
        and captured_map.get("aggregateAlgorithm")
        == current["aggregateAlgorithm"]
    )
    exact_inputs = (
        not missing
        and not unexpected
        and not duplicates
        and len(captured_files) == len(current["files"])
    )
    aggregate_matches = (
        captured_map.get("aggregateSha256")
        == current["aggregateSha256"]
    )
    matches = (
        bool(captured_map)
        and algorithms_match
        and exact_inputs
        and not stale
        and aggregate_matches
    )
    return {
        "present": bool(captured_map),
        "algorithmsMatch": algorithms_match,
        "requiredInputsExact": exact_inputs,
        "aggregateMatches": aggregate_matches,
        "matches": matches,
        "capturedAggregateSha256": str(
            captured_map.get("aggregateSha256") or ""
        ),
        "currentAggregateSha256": current["aggregateSha256"],
        "missingPaths": missing,
        "unexpectedPaths": unexpected,
        "duplicatePaths": sorted(set(duplicates)),
        "stalePaths": stale,
    }


def _category_status(
    raw_categories: Any,
    category_name: str,
    required_checks: Sequence[str],
) -> dict[str, Any]:
    categories = (
        raw_categories if isinstance(raw_categories, Mapping) else {}
    )
    raw_category = categories.get(category_name)
    category = raw_category if isinstance(raw_category, Mapping) else {}
    checks_value = category.get("checks")
    checks = checks_value if isinstance(checks_value, Mapping) else {}
    observed = {
        check: checks.get(check) is True for check in required_checks
    }
    missing = [
        check for check in required_checks if check not in checks
    ]
    observed_passed = all(observed.values()) and not missing
    reported_passed = category.get("passed") is True
    report_matches = reported_passed == observed_passed
    return {
        "passed": observed_passed and report_matches,
        "observedChecks": observed,
        "missingChecks": missing,
        "reportedPassed": reported_passed,
        "reportedResultMatchesChecks": report_matches,
    }


def _contrast_records_valid(raw: Mapping[str, Any]) -> bool:
    runs = raw.get("runs")
    if not isinstance(runs, list):
        return False
    by_theme = {
        str(run.get("theme")): run
        for run in runs
        if isinstance(run, Mapping)
    }
    if set(by_theme) != set(THEMES):
        return False
    for theme in THEMES:
        contrast = by_theme[theme].get("contrast")
        if not isinstance(contrast, Mapping):
            return False
        for field in ("textSamples", "controlSamples"):
            samples = contrast.get(field)
            if not isinstance(samples, list) or not samples:
                return False
            for sample in samples:
                if not isinstance(sample, Mapping):
                    return False
                ratio = sample.get("contrastRatio")
                required = sample.get("requiredRatio")
                if (
                    not isinstance(ratio, (int, float))
                    or isinstance(ratio, bool)
                    or not math.isfinite(float(ratio))
                    or not isinstance(required, (int, float))
                    or isinstance(required, bool)
                    or not math.isfinite(float(required))
                    or float(ratio) + 0.001 < float(required)
                    or sample.get("passed") is not True
                ):
                    return False
        if contrast.get("textFailures") not in ([], ()):
            return False
        if contrast.get("controlFailures") not in ([], ()):
            return False
    return True


def _manual_checklist_status(
    path: Path,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    if not path.is_file():
        return {
            "present": False,
            "status": "missing",
            "pendingMarkerPresent": False,
        }
    text = path.read_text(encoding="utf-8")
    pending = bool(
        re.search(
            r"(?im)^\s*(?:\*\*)?status\s*:\s*pending(?:\*\*)?\s*$",
            text,
        )
    )
    return {
        "present": True,
        "status": "pending" if pending else "unrecognized",
        "pendingMarkerPresent": pending,
        "artifact": _artifact(path, root),
    }


def interpret_accessibility_evidence(
    raw: Any,
    *,
    root: Path = ROOT,
    source_paths: Sequence[str] = SOURCE_PATHS,
    raw_artifact_path: Path | None = None,
    manual_checklist_path: Path = MANUAL_CHECKLIST,
) -> dict[str, Any]:
    """Derive a fail-closed summary from raw automated evidence."""

    raw_map = raw if isinstance(raw, Mapping) else {}
    blockers: list[str] = []
    integrity_findings: list[str] = []

    schema_valid = raw_map.get("schemaVersion") == RAW_SCHEMA
    if not schema_valid:
        blockers.append("automated_evidence_schema_invalid")

    if raw_map.get("screenReaderAudit") != "not_performed":
        blockers.append("automated_runner_screen_reader_claim_invalid")

    binding = source_binding_status(
        raw_map.get("sourceBinding"),
        root=root,
        source_paths=source_paths,
    )
    if not binding["matches"]:
        blockers.append("accessibility_evidence_source_binding_invalid")

    if raw_map.get("sourceStableDuringAudit") is not True:
        blockers.append("accessibility_source_changed_during_audit")

    categories = {}
    for name, required in CATEGORY_CHECKS.items():
        status = _category_status(raw_map.get("categories"), name, required)
        categories[name] = status
        if not status["passed"]:
            blockers.append(f"automated_{name}_audit_failed")
        if not status["reportedResultMatchesChecks"]:
            integrity_findings.append(
                f"{name}_reported_result_mismatch"
            )

    contrast_records_valid = _contrast_records_valid(raw_map)
    if not contrast_records_valid:
        categories["contrast"]["passed"] = False
        blockers.append("contrast_evidence_records_invalid")

    network = raw_map.get("network")
    network_map = network if isinstance(network, Mapping) else {}
    external_responses = network_map.get("externalResponses")
    if not isinstance(external_responses, list) or external_responses:
        categories["network"]["passed"] = False
        blockers.append("external_network_response_observed")

    manual = _manual_checklist_status(
        manual_checklist_path,
        root=root,
    )
    if not manual["present"] or not manual["pendingMarkerPresent"]:
        blockers.append("manual_screen_reader_checklist_invalid")
    blockers.append("manual_screen_reader_audit_pending")

    raw_artifact = None
    if raw_artifact_path is not None:
        if raw_artifact_path.is_file():
            raw_artifact = _artifact(raw_artifact_path, root)
        else:
            blockers.append("raw_accessibility_artifact_missing")

    blockers = sorted(set(blockers))
    automated_passed = (
        schema_valid
        and binding["matches"]
        and raw_map.get("sourceStableDuringAudit") is True
        and raw_map.get("screenReaderAudit") == "not_performed"
        and contrast_records_valid
        and all(
            status["passed"] for status in categories.values()
        )
        and not integrity_findings
    )
    return {
        "schemaVersion": SUMMARY_SCHEMA,
        "generatedAtUtc": _utc_now(),
        "scope": (
            "Automated keyboard, focus, semantics, live-region, reduced-"
            "motion, contrast, network, and runtime checks in the real "
            "Facility Layout workspace."
        ),
        "claims": {
            "automatedBrowserAudit": True,
            "manualScreenReaderAudit": False,
            "screenReaderSimulation": False,
        },
        "automatedAuditPassed": automated_passed,
        "manualScreenReaderAudit": manual,
        "releaseGateMet": False,
        "releaseGateReason": (
            "Automated browser evidence cannot clear the pending manual "
            "screen-reader audit."
        ),
        "categoryStatus": categories,
        "contrastRecordsValid": contrast_records_valid,
        "sourceBinding": binding,
        "rawArtifact": raw_artifact,
        "integrityFindings": sorted(integrity_findings),
        "blockers": blockers,
        "status": (
            "automated_pass_manual_screen_reader_pending"
            if automated_passed
            else "automated_audit_failed"
        ),
    }


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("app URL must use HTTP or HTTPS")
    return f"{parsed.scheme}://{parsed.netloc}"


def _same_origin(url: str, expected_origin: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme in {"data", "blob", "about"}:
        return True
    return _origin(url) == expected_origin


def _open_facility(page: Page, timeout_ms: int) -> None:
    page.wait_for_function(
        """() => (
            window.__inspectorProMainScriptReady === true
            && typeof switchTab === 'function'
            && typeof _trainApplyTrainingTypeDefaults === 'function'
        )""",
        timeout=timeout_ms,
    )
    page.evaluate(
        """() => {
            const previous = trainingState.type;
            trainingState.type = 'facility_layout';
            trainingState.viewportMode = 'facility_layout';
            _trainApplyTrainingTypeDefaults(previous);
            switchTab('training');
        }"""
    )
    page.wait_for_selector(
        "#trainFacilityLayoutAuthoring.ip-flw-root",
        state="visible",
        timeout=timeout_ms,
    )
    page.wait_for_function(
        """() => !!(
            _trainFacilityLayoutAuthoringApp
            && _trainFacilityLayoutAuthoringApp.workspace
            && !_trainFacilityLayoutAuthoringApp.session.getState().busy
            && document.querySelectorAll(
                '#trainFacilityLayoutAuthoring '
                + '.ip-flw-asset-row[data-asset-id]'
            ).length >= 1
        )""",
        timeout=timeout_ms,
    )


def _active(page: Page) -> dict[str, Any]:
    value = page.evaluate(
        ACTIVE_SCRIPT,
        "#trainFacilityLayoutAuthoring",
    )
    return value if isinstance(value, dict) else {}


def _blur(page: Page) -> None:
    page.evaluate(
        """() => {
            if (document.activeElement
                    && typeof document.activeElement.blur === 'function') {
                document.activeElement.blur();
            }
            if (document.body && typeof document.body.focus === 'function') {
                document.body.focus();
            }
        }"""
    )


def _matches_active(page: Page, selector: str) -> bool:
    return bool(
        page.evaluate(
            """selector => {
                const active = document.activeElement;
                return Boolean(active && active.matches(selector));
            }""",
            selector,
        )
    )


def _tab_until(
    page: Page,
    selector: str,
    *,
    maximum_tabs: int,
) -> tuple[bool, list[dict[str, Any]]]:
    sequence = []
    for _ in range(maximum_tabs):
        page.keyboard.press("Tab")
        descriptor = _active(page)
        sequence.append(descriptor)
        if _matches_active(page, selector):
            return True, sequence
    return False, sequence


def _focus_indicator(page: Page) -> dict[str, Any]:
    # Reduced-motion CSS uses a 0.01 ms transition. Let Chromium paint the
    # resulting focus ring before reading computed styles.
    page.wait_for_timeout(20)
    value = page.evaluate(FOCUS_SCRIPT)
    return value if isinstance(value, dict) else {}


def _focus_first_workspace_control(page: Page) -> dict[str, Any]:
    value = page.evaluate(
        """() => {
            const root = document.querySelector(
                '#trainFacilityLayoutAuthoring'
            );
            if (!root) return null;
            const selector = [
                'button:not(:disabled)',
                'input:not(:disabled)',
                '[tabindex]:not([tabindex="-1"])',
            ].join(',');
            const target = Array.from(root.querySelectorAll(selector))
                .find(element => {
                    const style = getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return !element.hidden
                        && style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && rect.width > 0
                        && rect.height > 0;
                });
            if (!target) return null;
            target.focus();
            return {
                command: target.getAttribute('data-command'),
                name: (
                    target.getAttribute('aria-label')
                    || target.textContent
                    || ''
                ).replace(/\\s+/g, ' ').trim(),
            };
        }"""
    )
    return value if isinstance(value, dict) else {}


def _indicator_visible(record: Mapping[str, Any]) -> bool:
    try:
        width = float(
            str(record.get("outlineWidth") or "0").replace("px", "")
        )
    except ValueError:
        width = 0
    outline_visible = (
        str(record.get("outlineStyle") or "") not in {"", "none"}
        and width >= 1.0
    )
    shadow_visible = str(record.get("boxShadow") or "") not in {
        "",
        "none",
    }
    return bool(outline_visible or shadow_visible)


def _install_live_observer(page: Page) -> None:
    page.evaluate(
        """() => {
            const root = document.querySelector(
                '#trainFacilityLayoutAuthoring'
            );
            window.__ipFacilityA11yLiveEvents = [];
            window.__ipFacilityA11yObservers = [];
            if (!root) return;
            root.querySelectorAll('[aria-live]').forEach((node, index) => {
                const capture = () => {
                    const text = String(node.textContent || '')
                        .replace(/\\s+/g, ' ').trim();
                    if (!text) return;
                    const records = window.__ipFacilityA11yLiveEvents;
                    if (records.length
                            && records[records.length - 1].text === text
                            && records[records.length - 1].index === index) {
                        return;
                    }
                    records.push({
                        index,
                        live: node.getAttribute('aria-live'),
                        role: node.getAttribute('role'),
                        text,
                        recordedAtMs: performance.now(),
                    });
                };
                const observer = new MutationObserver(capture);
                observer.observe(node, {
                    childList: true,
                    characterData: true,
                    subtree: true,
                });
                window.__ipFacilityA11yObservers.push(observer);
            });
        }"""
    )


def _live_events(page: Page) -> list[dict[str, Any]]:
    value = page.evaluate(
        "() => window.__ipFacilityA11yLiveEvents || []"
    )
    return value if isinstance(value, list) else []


def _workspace_focusable_count(page: Page) -> int:
    return int(
        page.evaluate(
            """() => {
                const root = document.querySelector(
                    '#trainFacilityLayoutAuthoring'
                );
                if (!root) return 0;
                return Array.from(root.querySelectorAll(
                    'button:not(:disabled),input:not(:disabled),'
                    + '[tabindex]:not([tabindex="-1"])'
                )).filter(element => {
                    const style = getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return !element.hidden
                        && style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && rect.width > 0
                        && rect.height > 0;
                }).length;
            }"""
        )
    )


def _set_safe_keyboard_point(page: Page) -> dict[str, float]:
    value = page.evaluate(
        """() => {
            const workspace = _trainFacilityLayoutAuthoringApp.workspace;
            const placements = _trainFacilityLayoutAuthoringApp.session
                .getState().layout.placements || [];
            const candidates = [
                {x: 35, y: 0, z: 25},
                {x: 35, y: 0, z: 5},
                {x: 5, y: 0, z: 25},
                {x: 20, y: 0, z: 25},
                {x: 30, y: 0, z: 15},
            ];
            const score = point => placements.reduce((minimum, item) => {
                const position = item.transform.position;
                const distance = Math.hypot(
                    point.x - position.x,
                    point.z - position.z
                );
                return Math.min(minimum, distance);
            }, Infinity);
            candidates.sort((left, right) => score(right) - score(left));
            workspace.options.keyboardPlacementPoint = candidates[0];
            return candidates[0];
        }"""
    )
    return {
        "x": float(value["x"]),
        "y": float(value["y"]),
        "z": float(value["z"]),
    }


def _keyboard_audit(
    page: Page,
    *,
    maximum_tabs: int,
) -> dict[str, Any]:
    _install_live_observer(page)
    initial = page.evaluate(
        """() => {
            const state = _trainFacilityLayoutAuthoringApp.session.getState();
            return {
                placements: state.layout.placements.length,
                dirty: state.dirty,
                toolMode:
                    _trainFacilityLayoutAuthoringApp.workspace.toolMode,
            };
        }"""
    )

    _blur(page)
    entered, entry_sequence = _tab_until(
        page,
        "#trainFacilityLayoutAuthoring *",
        maximum_tabs=maximum_tabs,
    )
    entry_focus = _active(page)
    entry_indicator = _focus_indicator(page) if entered else {}

    reverse_start = _focus_first_workspace_control(page)
    reverse_exits = False
    if reverse_start:
        page.keyboard.press("Shift+Tab")
        reverse_exits = not bool(_active(page).get("insideWorkspace"))

    _blur(page)
    reentered, _ = _tab_until(
        page,
        "#trainFacilityLayoutAuthoring *",
        maximum_tabs=maximum_tabs,
    )
    focusable_count = _workspace_focusable_count(page)
    traversal = []
    exited = False
    if reentered:
        for _ in range(max(8, focusable_count + 8)):
            page.keyboard.press("Tab")
            descriptor = _active(page)
            traversal.append(descriptor)
            if not descriptor.get("insideWorkspace"):
                exited = True
                break
    distinct_focus = {
        (
            item.get("id"),
            item.get("command"),
            item.get("view"),
            item.get("assetId"),
            item.get("name"),
        )
        for item in traversal
        if item.get("insideWorkspace")
    }

    _blur(page)
    shortcut_entry, shortcut_sequence = _tab_until(
        page,
        '#trainFacilityLayoutAuthoring [data-command="select"]',
        maximum_tabs=maximum_tabs,
    )
    shortcut = {
        "entryReached": shortcut_entry,
        "sequence": shortcut_sequence,
        "panActivated": False,
        "selectRestored": False,
    }
    if shortcut_entry:
        page.keyboard.press("h")
        shortcut["panActivated"] = (
            page.locator(
                '#trainFacilityLayoutAuthoring [data-command="pan"]'
            ).get_attribute("aria-pressed")
            == "true"
        )
        page.keyboard.press("v")
        shortcut["selectRestored"] = (
            page.locator(
                '#trainFacilityLayoutAuthoring [data-command="select"]'
            ).get_attribute("aria-pressed")
            == "true"
        )

    _blur(page)
    plan_reached, plan_sequence = _tab_until(
        page,
        '#trainFacilityLayoutAuthoring [data-view="plan"]',
        maximum_tabs=maximum_tabs,
    )
    tab_audit = {
        "planReachedByTab": plan_reached,
        "sequence": plan_sequence,
        "arrowMovedFocusTo3d": False,
        "enterActivated3d": False,
        "directFocusEnterActivated3dDiagnostic": False,
    }
    if plan_reached:
        page.keyboard.press("ArrowRight")
        tab_audit["arrowMovedFocusTo3d"] = _matches_active(
            page,
            '#trainFacilityLayoutAuthoring [data-view="3d"]',
        )
        if tab_audit["arrowMovedFocusTo3d"]:
            page.keyboard.press("Enter")
            tab_audit["enterActivated3d"] = (
                page.locator(
                    '#trainFacilityLayoutAuthoring [data-view="3d"]'
                ).get_attribute("aria-selected")
                == "true"
            )
    page.locator(
        '#trainFacilityLayoutAuthoring [data-view="3d"]'
    ).focus()
    page.keyboard.press("Enter")
    tab_audit["directFocusEnterActivated3dDiagnostic"] = (
        page.locator(
            '#trainFacilityLayoutAuthoring [data-view="3d"]'
        ).get_attribute("aria-selected")
        == "true"
    )
    page.locator(
        '#trainFacilityLayoutAuthoring [data-view="plan"]'
    ).focus()
    page.keyboard.press("Enter")

    safe_point = _set_safe_keyboard_point(page)
    _blur(page)
    asset_reached, asset_sequence = _tab_until(
        page,
        "#trainFacilityLayoutAuthoring "
        '.ip-flw-asset-row[data-asset-id]',
        maximum_tabs=maximum_tabs,
    )
    asset_action: dict[str, Any] = {
        "rowReachedByTab": asset_reached,
        "sequence": asset_sequence,
        "safeWorldPoint": safe_point,
        "placementAdded": False,
        "selectionUpdated": False,
        "dirtyAfterAction": False,
        "undoRestoredPlacementCount": False,
        "undoRestoredDirtyState": False,
    }
    if asset_reached:
        page.keyboard.press("Enter")
        page.evaluate(
            "() => _trainFacilityLayoutAuthoringApp.workspace.whenIdle()"
        )
        page.wait_for_function(
            """() => !_trainFacilityLayoutAuthoringApp
                .session.getState().busy""",
            timeout=60_000,
        )
        after_action = page.evaluate(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp
                    .session.getState();
                return {
                    placements: state.layout.placements.length,
                    selection: state.selection,
                    dirty: state.dirty,
                    status: document.querySelector(
                        '#trainFacilityLayoutAuthoring .ip-flw-status'
                    ).textContent,
                };
            }"""
        )
        asset_action.update(
            {
                "afterAction": after_action,
                "placementAdded": (
                    after_action["placements"]
                    == initial["placements"] + 1
                ),
                "selectionUpdated": bool(after_action["selection"]),
                "dirtyAfterAction": after_action["dirty"] is True,
            }
        )
        page.keyboard.press("Control+z")
        page.evaluate(
            "() => _trainFacilityLayoutAuthoringApp.workspace.whenIdle()"
        )
        after_undo = page.evaluate(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp
                    .session.getState();
                return {
                    placements: state.layout.placements.length,
                    selection: state.selection,
                    dirty: state.dirty,
                    status: document.querySelector(
                        '#trainFacilityLayoutAuthoring .ip-flw-status'
                    ).textContent,
                };
            }"""
        )
        asset_action.update(
            {
                "afterUndo": after_undo,
                "undoRestoredPlacementCount": (
                    after_undo["placements"] == initial["placements"]
                ),
                "undoRestoredDirtyState": (
                    after_undo["dirty"] == initial["dirty"]
                ),
            }
        )

    events = _live_events(page)
    action_announcements = [
        item for item in events
        if any(
            token in str(item.get("text") or "").lower()
            for token in (
                "working",
                "unsaved",
                "selected",
                "saved",
                "plan view",
                "3d view",
            )
        )
    ]
    checks = {
        "enteredWorkspaceByTab": entered,
        "forwardTraversalProgresses": len(distinct_focus) >= 3,
        "reverseTraversalExitsWorkspace": reverse_exits,
        "noKeyboardTrap": exited,
        "shortcutActionWorks": (
            shortcut["panActivated"] and shortcut["selectRestored"]
        ),
        "assetActionWorks": (
            asset_action["placementAdded"]
            and asset_action["selectionUpdated"]
            and asset_action["dirtyAfterAction"]
        ),
        "undoActionWorks": (
            asset_action["undoRestoredPlacementCount"]
            and asset_action["undoRestoredDirtyState"]
        ),
        "tabKeyboardActivationWorks": (
            tab_audit["arrowMovedFocusTo3d"]
            and tab_audit["enterActivated3d"]
        ),
    }
    return {
        "initial": initial,
        "entry": {
            "reached": entered,
            "focus": entry_focus,
            "indicator": entry_indicator,
            "sequence": entry_sequence,
        },
        "focusableCount": focusable_count,
        "forwardTraversal": traversal,
        "distinctWorkspaceFocusCount": len(distinct_focus),
        "reverseTraversalStart": reverse_start,
        "reverseTraversalExitsWorkspace": reverse_exits,
        "shortcut": shortcut,
        "tabs": tab_audit,
        "assetAction": asset_action,
        "liveEvents": events,
        "actionAnnouncements": action_announcements,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _semantics_checks(
    semantics: Mapping[str, Any],
    aria_snapshot: str,
) -> dict[str, bool]:
    controls = semantics.get("controls")
    control_list = controls if isinstance(controls, list) else []
    tabs = semantics.get("tabs")
    tab_list = tabs if isinstance(tabs, list) else []
    panels = semantics.get("panels")
    panel_list = panels if isinstance(panels, list) else []
    tree_items = semantics.get("treeItems")
    item_list = tree_items if isinstance(tree_items, list) else []
    selected_tabs = [
        item for item in tab_list
        if isinstance(item, Mapping) and item.get("selected") == "true"
    ]
    pressed = [
        item for item in control_list
        if isinstance(item, Mapping) and item.get("pressed") is not None
    ]
    return {
        "ariaSnapshotCaptured": bool(aria_snapshot.strip()),
        "workspaceNamed": (
            semantics.get("workspaceName") == "Facility layout workspace"
        ),
        "toolbarNamed": semantics.get("toolbar") == {
            "name": "Facility layout tools",
            "role": "toolbar",
        },
        "treeNamed": semantics.get("tree") == {
            "name": "Available facility assets",
            "role": "tree",
        },
        "treeItemsNamed": (
            bool(item_list)
            and all(isinstance(item, str) and bool(item) for item in item_list)
        ),
        "tabsNamed": (
            len(tab_list) == 2
            and all(
                isinstance(item, Mapping) and bool(item.get("name"))
                for item in tab_list
            )
        ),
        "tabStateValid": (
            len(selected_tabs) == 1
            and selected_tabs[0].get("tabIndex") == 0
            and all(
                item.get("tabIndex") == -1
                for item in tab_list
                if item is not selected_tabs[0]
            )
        ),
        "panelsNamed": (
            len(panel_list) == 2
            and all(
                isinstance(item, Mapping) and bool(item.get("name"))
                for item in panel_list
            )
        ),
        "controlsNamed": (
            bool(control_list)
            and all(
                isinstance(item, Mapping) and bool(item.get("name"))
                for item in control_list
            )
        ),
        "busyStatePresent": semantics.get("workspaceAriaBusy") in {
            "true",
            "false",
        },
        "pressedStatePresent": bool(pressed),
        "duplicateIdsAbsent": semantics.get("duplicateIds") == [],
    }


def _theme_run(
    browser: Browser,
    *,
    app_url: str,
    app_origin: str,
    output_dir: Path,
    theme: str,
    smoke: bool,
    run_interactions: bool,
    timeout_ms: int,
    network: dict[str, Any],
) -> dict[str, Any]:
    context: BrowserContext = browser.new_context(
        viewport={"width": 1440, "height": 960},
        device_scale_factor=1,
        color_scheme=theme,
        reduced_motion="reduce",
        service_workers="block",
    )
    context.add_init_script(
        "localStorage.setItem('inspectorpro.theme', "
        + json.dumps(theme)
        + ");"
    )

    def route_request(route: Route) -> None:
        request_url = route.request.url
        if _same_origin(request_url, app_origin):
            network["sameOriginRequests"].append(request_url)
            route.continue_()
            return
        network["blockedExternalRequests"].append(request_url)
        route.abort()

    context.route("**/*", route_request)
    external_canary_url = (
        "https://facility-layout-a11y.invalid/network-block-canary"
    )
    canary_page = context.new_page()
    external_canary_blocked = canary_page.evaluate(
        """async url => {
            try {
                await fetch(url, {
                    cache: 'no-store',
                    credentials: 'omit',
                    mode: 'cors',
                });
                return false;
            } catch (error) {
                return true;
            }
        }""",
        external_canary_url,
    )
    canary_page.close()

    page = context.new_page()
    page_errors: list[str] = []
    console_errors: list[str] = []
    request_failures: list[dict[str, str]] = []
    same_origin_responses: list[str] = []
    external_responses: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "console",
        lambda message: (
            console_errors.append(message.text)
            if message.type == "error"
            else None
        ),
    )
    page.on(
        "requestfailed",
        lambda request: request_failures.append(
            {
                "url": request.url,
                "failure": str(request.failure or ""),
            }
        ),
    )

    def record_response(response: Any) -> None:
        if _same_origin(response.url, app_origin):
            same_origin_responses.append(response.url)
        else:
            external_responses.append(response.url)

    page.on("response", record_response)
    page.goto(app_url, wait_until="load", timeout=timeout_ms)
    _open_facility(page, timeout_ms)
    root = page.locator("#trainFacilityLayoutAuthoring")
    page.evaluate(
        """() => _trainFacilityLayoutAuthoringApp.workspace
            .executeCommand('fit')"""
    )
    page.evaluate(
        "() => _trainFacilityLayoutAuthoringApp.workspace.whenIdle()"
    )

    semantics = page.evaluate(
        SEMANTICS_SCRIPT,
        "#trainFacilityLayoutAuthoring",
    )
    aria_snapshot = root.aria_snapshot(timeout=timeout_ms)
    contrast = page.evaluate(
        CONTRAST_SCRIPT,
        {
            "rootSelector": "#trainFacilityLayoutAuthoring",
            "maximumTextSamples": 160 if smoke else 600,
            "maximumControlSamples": 80 if smoke else 300,
        },
    )
    reduced_motion = page.evaluate(
        REDUCED_MOTION_SCRIPT,
        "#trainFacilityLayoutAuthoring",
    )

    _blur(page)
    focus_reached, focus_sequence = _tab_until(
        page,
        '#trainFacilityLayoutAuthoring [data-command="pan"]',
        maximum_tabs=180 if smoke else 360,
    )
    focus = _focus_indicator(page) if focus_reached else {}
    focus["reachedByTab"] = focus_reached
    focus["entrySequence"] = focus_sequence
    focus_path = output_dir / f"facility-layout-focus-{theme}.png"
    page.screenshot(path=str(focus_path), full_page=False)

    keyboard = (
        _keyboard_audit(
            page,
            maximum_tabs=180 if smoke else 360,
        )
        if run_interactions
        else None
    )
    semantics_checks = _semantics_checks(semantics, aria_snapshot)
    reduced_checks = {
        "mediaQueryMatched": (
            reduced_motion.get("mediaQueryMatches") is True
        ),
        "transitionsSuppressed": (
            float(reduced_motion.get("maximumTransitionMs") or 0)
            <= 0.011
        ),
        "animationsSuppressed": (
            float(reduced_motion.get("maximumAnimationMs") or 0)
            <= 0.011
        ),
    }
    focus_checks = {
        "samplesPresent": focus_reached,
        "allSamplesUseFocusVisible": (
            focus.get("focusVisible") is True
        ),
        "allSamplesHaveVisibleIndicator": _indicator_visible(focus),
        "focusScreenshotsCaptured": (
            focus_path.is_file() and focus_path.stat().st_size > 32
        ),
    }
    network["externalResponses"].extend(external_responses)
    result = {
        "theme": theme,
        "requestedReducedMotion": "reduce",
        "semantics": semantics,
        "semanticsChecks": semantics_checks,
        "ariaSnapshot": aria_snapshot,
        "focus": focus,
        "focusChecks": focus_checks,
        "focusScreenshot": _artifact(focus_path),
        "contrast": contrast,
        "reducedMotion": reduced_motion,
        "reducedMotionChecks": reduced_checks,
        "keyboard": keyboard,
        "network": {
            "externalCanaryUrl": external_canary_url,
            "externalCanaryBlocked": external_canary_blocked is True,
            "sameOriginResponseCount": len(same_origin_responses),
            "externalResponses": external_responses,
            "requestFailures": request_failures,
        },
        "errors": {
            "page": page_errors,
            "console": console_errors,
        },
    }
    context.close()
    return result


def _aggregate_categories(
    runs: Sequence[Mapping[str, Any]],
    *,
    source_stable: bool,
    network: Mapping[str, Any],
) -> dict[str, Any]:
    interaction_runs = [
        run for run in runs if isinstance(run.get("keyboard"), Mapping)
    ]
    keyboard_checks = {
        check: any(
            run["keyboard"].get("checks", {}).get(check) is True
            for run in interaction_runs
        )
        for check in CATEGORY_CHECKS["keyboard"]
    }
    focus_checks = {
        check: all(
            run.get("focusChecks", {}).get(check) is True
            for run in runs
        )
        for check in CATEGORY_CHECKS["focus"]
    }
    semantics_checks = {
        check: all(
            run.get("semanticsChecks", {}).get(check) is True
            for run in runs
        )
        for check in CATEGORY_CHECKS["semantics"]
    }
    live_events = [
        event
        for run in interaction_runs
        for event in run["keyboard"].get("liveEvents", [])
        if isinstance(event, Mapping)
    ]
    action_events = [
        event
        for run in interaction_runs
        for event in run["keyboard"].get("actionAnnouncements", [])
        if isinstance(event, Mapping)
    ]
    announcement_checks = {
        "liveRegionsPresent": all(
            bool(run.get("semantics", {}).get("liveRegions"))
            for run in runs
        ),
        "announcementsObserved": bool(live_events),
        "actionAnnouncementObserved": bool(action_events),
    }
    reduced_checks = {
        check: all(
            run.get("reducedMotionChecks", {}).get(check) is True
            for run in runs
        )
        for check in CATEGORY_CHECKS["reducedMotion"]
    }
    by_theme = {
        str(run.get("theme")): run for run in runs
    }
    text_samples = [
        sample
        for run in runs
        for sample in run.get("contrast", {}).get("textSamples", [])
    ]
    control_samples = [
        sample
        for run in runs
        for sample in run.get("contrast", {}).get("controlSamples", [])
    ]
    contrast_checks = {
        "bothThemesMeasured": set(by_theme) == set(THEMES),
        "textSamplesPresent": all(
            bool(
                by_theme.get(theme, {}).get(
                    "contrast",
                    {},
                ).get("textSamples")
            )
            for theme in THEMES
        ),
        "controlSamplesPresent": all(
            bool(
                by_theme.get(theme, {}).get(
                    "contrast",
                    {},
                ).get("controlSamples")
            )
            for theme in THEMES
        ),
        "textContrastPasses": (
            bool(text_samples)
            and all(sample.get("passed") is True for sample in text_samples)
        ),
        "controlContrastPasses": (
            bool(control_samples)
            and all(
                sample.get("passed") is True
                for sample in control_samples
            )
        ),
    }
    network_checks = {
        "blockingPolicyInstalled": (
            network.get("blockingPolicyInstalled") is True
        ),
        "externalBlockCanaryObserved": (
            bool(runs)
            and all(
                run.get("network", {}).get("externalCanaryBlocked") is True
                for run in runs
            )
            and any(
                "facility-layout-a11y.invalid/network-block-canary"
                in str(url)
                for url in network.get("blockedExternalRequests", [])
            )
        ),
        "sameOriginApplicationLoaded": bool(
            network.get("sameOriginRequests")
        ),
        "noExternalResponses": not network.get("externalResponses"),
    }
    page_errors = [
        error
        for run in runs
        for error in run.get("errors", {}).get("page", [])
    ]
    console_errors = [
        error
        for run in runs
        for error in run.get("errors", {}).get("console", [])
    ]
    runtime_checks = {
        "auditCompleted": len(runs) == len(THEMES),
        "sourceStableDuringAudit": source_stable,
        "noPageErrors": not page_errors,
        "noConsoleErrors": not console_errors,
    }
    category_checks = {
        "keyboard": keyboard_checks,
        "focus": focus_checks,
        "semantics": semantics_checks,
        "announcements": announcement_checks,
        "reducedMotion": reduced_checks,
        "contrast": contrast_checks,
        "network": network_checks,
        "runtime": runtime_checks,
    }
    return {
        name: {
            "checks": checks,
            "passed": all(checks.values()),
        }
        for name, checks in category_checks.items()
    }


def audit(
    *,
    app_url: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    smoke: bool = False,
    headed: bool = False,
    browser_executable: Path | None = None,
    timeout_ms: int = 120_000,
) -> tuple[dict[str, Any], dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_before = build_source_binding()
    app_origin = _origin(app_url)
    network: dict[str, Any] = {
        "policy": "allow exact application origin; abort all other requests",
        "blockingPolicyInstalled": True,
        "applicationOrigin": app_origin,
        "sameOriginRequests": [],
        "blockedExternalRequests": [],
        "externalResponses": [],
    }
    started = time.time()
    runs: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        launch_options: dict[str, Any] = {"headless": not headed}
        if browser_executable is not None:
            launch_options["executable_path"] = str(
                browser_executable.resolve()
            )
        browser = playwright.chromium.launch(**launch_options)
        browser_version = browser.version
        for theme in THEMES:
            runs.append(
                _theme_run(
                    browser,
                    app_url=app_url,
                    app_origin=app_origin,
                    output_dir=output_dir,
                    theme=theme,
                    smoke=smoke,
                    run_interactions=(not smoke or theme == "dark"),
                    timeout_ms=timeout_ms,
                    network=network,
                )
            )
        browser.close()

    source_after = build_source_binding()
    source_stable = source_before == source_after
    categories = _aggregate_categories(
        runs,
        source_stable=source_stable,
        network=network,
    )
    raw = {
        "schemaVersion": RAW_SCHEMA,
        "generatedAtUtc": _utc_now(),
        "mode": "smoke" if smoke else "full",
        "appUrl": app_url,
        "scope": (
            "Real InspectorPro Facility Layout workspace loaded in Chromium; "
            "keyboard interaction uses production controls and an unsaved "
            "session draft."
        ),
        "screenReaderAudit": "not_performed",
        "claims": {
            "manualScreenReaderAudit": False,
            "automatedBrowserAudit": True,
        },
        "environment": {
            "os": platform.platform(),
            "python": sys.version,
            "playwright": importlib.metadata.version("playwright"),
            "browser": f"Chromium {browser_version}",
            "headed": headed,
            "elapsedSeconds": round(time.time() - started, 3),
        },
        "protocol": {
            "themes": list(THEMES),
            "reducedMotion": "reduce",
            "externalNetworkBlocking": True,
            "keyboardOnlyAfterWorkspaceEntry": True,
            "smoke": smoke,
        },
        "sourceBinding": source_before,
        "sourceStableDuringAudit": source_stable,
        "network": {
            **network,
            "sameOriginRequests": sorted(
                set(network["sameOriginRequests"])
            ),
            "blockedExternalRequests": sorted(
                set(network["blockedExternalRequests"])
            ),
            "externalResponses": sorted(
                set(network["externalResponses"])
            ),
        },
        "runs": runs,
        "categories": categories,
        "automatedChecksPassed": all(
            category["passed"] for category in categories.values()
        ),
    }
    raw_path = output_dir / "facility-layout-accessibility-raw.json"
    _write_json(raw_path, raw)
    summary = interpret_accessibility_evidence(
        raw,
        raw_artifact_path=raw_path,
    )
    summary_path = (
        output_dir / "facility-layout-accessibility-summary.json"
    )
    _write_json(summary_path, summary)
    return raw, summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the automated Facility Layout accessibility audit. "
            "This does not perform a manual screen-reader audit."
        )
    )
    parser.add_argument(
        "--app-url",
        default=os.getenv(
            "FACILITY_LAYOUT_ACCESSIBILITY_APP_URL",
            "http://127.0.0.1:8023/",
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help=(
            "Run all core checks but execute the destructive-free keyboard "
            "interaction sequence in one theme instead of both."
        ),
    )
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--browser-executable", type=Path)
    parser.add_argument("--timeout-ms", type=int, default=120_000)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    raw, summary = audit(
        app_url=args.app_url,
        output_dir=args.output_dir.resolve(),
        smoke=args.smoke,
        headed=args.headed,
        browser_executable=args.browser_executable,
        timeout_ms=args.timeout_ms,
    )
    for name, category in raw["categories"].items():
        print(
            ("PASS" if category["passed"] else "FAIL")
            + "\t"
            + name
        )
        for check, passed in category["checks"].items():
            if not passed:
                print("  FAIL\t" + check)
    print(
        "AUTOMATED\t"
        + (
            "PASS"
            if summary["automatedAuditPassed"]
            else "FAIL"
        )
    )
    print("SCREEN_READER\tPENDING (manual audit not performed)")
    print(
        "RAW\t"
        + str(
            (
                args.output_dir.resolve()
                / "facility-layout-accessibility-raw.json"
            )
        )
    )
    print(
        "SUMMARY\t"
        + str(
            (
                args.output_dir.resolve()
                / "facility-layout-accessibility-summary.json"
            )
        )
    )
    return 0 if summary["automatedAuditPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
