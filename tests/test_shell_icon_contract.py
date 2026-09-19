from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
ICON_ROOT = ROOT / "static" / "assets" / "shell-icons"

TOP_COMMANDS = {
    "iconHome": "home.svg",
    "iconOpen": "new_document.svg",
    "iconSave": "save.svg",
    "iconPrint": "print.svg",
    "iconUndo": "undo.svg",
    "iconRedo": "redo.svg",
    "iconSelect": "pointer.svg",
    "iconNews": "notifications.svg",
    "iconSettings": "settings.svg",
}

ALL_ICON_NAMES = {
    *TOP_COMMANDS.values(),
    "drawing.svg",
    "model_3d.svg",
}


def _source() -> str:
    return INDEX.read_text(encoding="utf-8")


def test_shell_commands_keep_stable_ids_and_use_premium_svg_assets() -> None:
    source = _source()

    for command_id, filename in TOP_COMMANDS.items():
        command = re.search(
            rf'<button[^>]*\bid="{command_id}"[^>]*>(.*?)</button>',
            source,
            flags=re.DOTALL,
        )
        assert command, f"missing shell command {command_id}"
        assert command.group(1).count("shell-toolbar-icon") == 1
        assert f'/static/assets/shell-icons/dark/{filename}' in command.group(1)
        assert f"getElementById('{command_id}')" in source

    assert "/static/assets/global-toolbar-icons/" not in source


def test_shell_rail_keeps_navigation_targets_and_switches_theme_assets() -> None:
    source = _source()

    for panel, filename in (("explorer", "drawing.svg"), ("model", "model_3d.svg")):
        item = re.search(
            rf'<div class="activity-bar-icon[^"]*" data-panel="{panel}"[^>]*>(.*?)</div>',
            source,
            flags=re.DOTALL,
        )
        assert item, f"missing activity rail target {panel}"
        markup = item.group(1)
        assert f'/static/assets/shell-icons/dark/{filename}' in markup
        assert f'/static/assets/shell-icons/light/{filename}' in markup

    assert 'querySelectorAll(\'.activity-bar-icon[data-panel]\')' in source


def test_shell_icon_assets_are_crisp_flat_svgs_for_both_themes() -> None:
    for theme in ("dark", "light"):
        theme_dir = ICON_ROOT / theme
        assert {path.name for path in theme_dir.glob("*.svg")} == ALL_ICON_NAMES

        for icon_path in theme_dir.glob("*.svg"):
            svg = icon_path.read_text(encoding="utf-8")
            root = ET.fromstring(svg)
            assert root.tag.endswith("svg")
            assert root.attrib.get("viewBox") in {"0 0 24 24", "0 0 32 32"}
            assert "linearGradient" not in svg
            assert "radialGradient" not in svg
            assert "filter=" not in svg
            assert "#1FA3D7" in svg if theme == "dark" else "#168FC4" in svg


def test_shell_icon_sizing_and_flat_active_state_contract() -> None:
    source = _source()

    assert re.search(r"\.shell-toolbar-icon\s*\{[^}]*width:\s*19px;[^}]*height:\s*19px;", source, re.DOTALL)
    assert re.search(r"\.shell-rail-icon-image\s*\{[^}]*width:\s*27px;[^}]*height:\s*27px;", source, re.DOTALL)

    premium_block = source[source.index("/* Premium shell rail:"):]
    active_state = re.search(r"\.activity-bar-icon\.active\s*\{([^}]*)\}", premium_block, re.DOTALL)
    indicator = re.search(r"\.activity-bar-icon\.active::before\s*\{([^}]*)\}", premium_block, re.DOTALL)
    assert active_state and "linear-gradient" not in active_state.group(1) and "box-shadow: none" in active_state.group(1)
    assert indicator and "linear-gradient" not in indicator.group(1) and "box-shadow: none" in indicator.group(1)
