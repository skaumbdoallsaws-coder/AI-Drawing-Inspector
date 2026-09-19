from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
ICON_ROOT = ROOT / "static" / "assets" / "workflow-dropdown-icons"

WORKFLOWS = {
    "assembly": ("Process Map", "process_map.svg"),
    "plant_process": ("Plant / Process Explanation", "plant_process_explanation.svg"),
    "facility_layout": ("Facility Layout", "facility_layout.svg"),
    "documentation": ("Documentation", "documentation.svg"),
    "service": ("Service Training", "service_training.svg"),
    "maintenance": ("Maintenance Training", "maintenance_training.svg"),
    "troubleshooting": ("Troubleshooting", "troubleshooting.svg"),
    "operator": ("Operator Training", "operator_training.svg"),
}


def _source() -> str:
    return INDEX.read_text(encoding="utf-8")


def test_existing_workflow_configuration_is_the_only_icon_mapping() -> None:
    source = _source()

    for value, (label, icon) in WORKFLOWS.items():
        pattern = (
            rf"\{{\s*value:\s*'{re.escape(value)}',\s*"
            rf"label:\s*'{re.escape(label)}',\s*icon:\s*'{re.escape(icon)}'\s*\}}"
        )
        assert re.search(pattern, source), f"missing TRAINING_TYPES icon mapping for {value}"

    assert source.count("function _trainCreateWorkflowTypeSelector()") == 1
    assert "TRAINING_TYPES.map((type, index) =>" in source
    assert "wrap.appendChild(_trainCreateWorkflowTypeSelector());" in source
    assert "group.appendChild(_trainCreateWorkflowTypeSelector());" in source


def test_original_select_id_and_change_routing_remain_authoritative() -> None:
    source = _source()

    assert "nativeSelect.id = 'trainingTypeRibbonSelect';" in source
    assert "_trainChangeTypeFromRibbon(nativeSelect)" in source
    assert "nativeSelect.dispatchEvent(new Event('change', { bubbles: true }))" in source
    assert "nativeSelect.setAttribute('aria-hidden', 'true')" in source
    assert "nativeSelect.tabIndex = -1" in source


def test_custom_selector_keeps_listbox_keyboard_and_accessibility_contract() -> None:
    source = _source()

    for marker in (
        "trigger.setAttribute('role', 'combobox')",
        "trigger.setAttribute('aria-haspopup', 'listbox')",
        "trigger.setAttribute('aria-controls', 'trainingTypeRibbonListbox')",
        "listbox.setAttribute('role', 'listbox')",
        "row.setAttribute('role', 'option')",
        "row.setAttribute('aria-selected'",
        "event.key === 'ArrowDown'",
        "event.key === 'ArrowUp'",
        "event.key === 'Home'",
        "event.key === 'End'",
        "event.key === 'Escape'",
        "event.key === 'Tab'",
        "applyTypeAhead(event.key)",
    ):
        assert marker in source


def test_premium_workflow_assets_and_layout_metrics() -> None:
    source = _source()
    expected_assets = {icon for _, icon in WORKFLOWS.values()}

    for theme in ("dark", "light"):
        paths = set((ICON_ROOT / theme).glob("*.svg"))
        assert {path.name for path in paths} == expected_assets
        for path in paths:
            svg = path.read_text(encoding="utf-8")
            root = ET.fromstring(svg)
            assert root.tag.endswith("svg")
            assert root.attrib.get("viewBox") == "0 0 24 24"
            assert "linearGradient" not in svg
            assert "radialGradient" not in svg
            assert "filter=" not in svg

    assert re.search(
        r"\.workflow-type-icon-image\s*\{[^}]*width:\s*18px;[^}]*height:\s*18px;",
        source,
        re.DOTALL,
    )
    assert re.search(
        r"\.workflow-type-option\s*\{[^}]*height:\s*34px;",
        source,
        re.DOTALL,
    )
    assert re.search(
        r"\.workflow-type-listbox\s*\{[^}]*position:\s*fixed;[^}]*min-width:\s*260px;",
        source,
        re.DOTALL,
    )
    assert "grid-template-columns: 24px minmax(0, 1fr);" in source


def test_dropdown_portals_above_panes_and_tracks_the_trigger() -> None:
    source = _source()

    for marker in (
        "document.body.appendChild(listbox)",
        "trigger.getBoundingClientRect()",
        "document.addEventListener('scroll', positionListbox, true)",
        "window.addEventListener('resize', positionListbox)",
        "!root.contains(event.target) && !listbox.contains(event.target)",
        "window._closeActiveWorkflowTypeSelector = closeListbox",
    ):
        assert marker in source

    z_index = re.search(
        r"\.workflow-type-listbox\s*\{[^}]*z-index:\s*(\d+);",
        source,
        re.DOTALL,
    )
    assert z_index and int(z_index.group(1)) > 10002


def test_property_manager_is_closed_by_default_and_on_workflow_change() -> None:
    source = _source()

    assert re.search(
        r"panels:\s*\{\s*setupOpen:\s*false,\s*playbackOpen:\s*false,",
        source,
        re.DOTALL,
    )
    assert "Default-open the Setup panel when entering Training tab" not in source
    assert re.search(
        r"if \(prevType && prevType !== trainingState\.type\) \{\s*"
        r"trainingState\.panels\.setupOpen = false;\s*\}",
        source,
        re.DOTALL,
    )
    assert "setupIcon.addEventListener('click', () => _trainTogglePanel('setup'))" in source
