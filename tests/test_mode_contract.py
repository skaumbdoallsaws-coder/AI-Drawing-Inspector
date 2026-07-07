"""Tests for mode-aware Sage (the mode contract), Increments 1 + 2.

The frontend sends a FACTUAL contract under
``attachments.session.mode_contract`` (built by ``buildModeContract()`` in
static/index.html). The backend:

* preserves ``active_tab`` / ``active_mode`` / ``mode_submode`` / ``mode_state``
  in ``normalize_agent_context`` (previously ``active_tab`` was dropped);
* renders a factual ``[MODE]`` + per-mode block in ``_build_context_message``;
* layers a durable per-mode reasoning contract onto the system prompt via
  ``_mode_system_addendum`` (sourced from ``MODE_CONTRACTS``).

Increment 2 implements two modes: ``facility_layout`` and ``plant_process``.
These tests prove the contract is populated per mode, that switching modes
changes the next request, and that one mode's framing does not leak into the
other.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers / fixtures-as-data
# ---------------------------------------------------------------------------

def _session_ctx(mode, state, submode=None, tab="training"):
    """Build a raw agent context exactly as the frontend would send it."""
    return {
        "attachments": {
            "session": {
                "agent": "inspector",
                "active_tab": tab,
                "active_mode": mode,
                "mode_contract": {
                    "contract_version": 1,
                    "tab": tab,
                    "mode": mode,
                    "submode": submode,
                    "state": state,
                },
            }
        }
    }


FACILITY_STATE = {
    "selected_row_id": None,
    "selected_rack_ids": ["Rack_Row_C_Lower_Middle"],
    "selected_zone_ids": ["Aisle_BC_Center_Clear_Aisle"],
    "selected_footprint_ids": [],
    "route": {
        "start_label": "05 Southeast Aisle",
        "end_label": "C Lower Middle",
        "distance_m": 7.893,
        "eta_text": "~5 s",
        "via_aisles": ["C Lower Middle / D South Wall aisle"],
        "step_count": 4,
        "matches_current_selection": True,
    },
    "analysis": {
        "headline": "Adding an east cross-aisle would cut total travel ~3%",
        "reduction_percent": 3.4,
    },
    "capacity": {
        "estimated_total_boxes": 1280,
        "row_count": 2,
        "rows": [{"row_id": "A", "boxes": 640, "racks": 5},
                 {"row_id": "B", "boxes": 640, "racks": 5}],
    },
}

PLANT_STATE = {
    "active_zone": {"id": "heat_rejection", "label": "Heat rejection core"},
    "available_zones": [
        {"id": "overview", "label": "System overview"},
        {"id": "heat_rejection", "label": "Heat rejection core"},
    ],
    "active_flow_ids": ["warm_return", "cooled_supply"],
    "selected_group_ids": ["fan_deck", "basin"],
}

ASSEMBLY_TRAINING_STATE = {
    "product_name": "Racing Bike Assembly",
    "target_role": "technician",
    "target_component": "Complete Racing Bike Assembly",
    "goal": "Assemble the racing bike using the product structure map",
    "viewport_mode": "assembly3d",
    "active_viewer": {
        "node_id": "L0-000",
        "node_name": "Complete Racing Bike Assembly",
        "asset_glb_url": "/generated/training/racing-bike/assembly_glb/racing_bike_assembly.glb",
        "part_count": 47,
    },
    "selected_node": {
        "node_id": "L0-000",
        "name": "Complete Racing Bike Assembly",
        "level": 0,
        "purpose": "Root assembly completed by joining internal mechanical assembly with bodywork/exterior assembly.",
        "part_count": 47,
        "part_names": ["Front Wheel Rim", "Rear Wheel Rim", "Seat / Tail Body Shell"],
    },
    "procedure": {
        "title": "Assembly procedure - Complete Racing Bike Assembly",
        "node_id": "L0-000",
        "step_index": 0,
        "step_count": 5,
        "current_step_title": "Identify major subassemblies",
        "current_step_instruction": "Confirm the racing bike frame, wheels, brakes, and bodywork before starting.",
    },
    "available_top_nodes": [
        {"node_id": "L0-000", "name": "Complete Racing Bike Assembly", "level": 0},
        {"node_id": "L1-001", "name": "Internal Mechanical Assembly", "level": 1},
        {"node_id": "L1-002", "name": "Bodywork / Exterior Assembly", "level": 1},
    ],
}


def _flat(ctx):
    return server.normalize_agent_context(ctx)["flat"]


def _context_message(mode, state, submode=None):
    return server._build_context_message(_flat(_session_ctx(mode, state, submode)))


# ---------------------------------------------------------------------------
# Increment 1: plumbing — active_tab / active_mode survive normalization
# ---------------------------------------------------------------------------

def test_normalize_preserves_active_tab_previously_dropped():
    # active_tab was sent by the frontend but silently dropped before this work.
    flat = _flat(_session_ctx("facility_layout", FACILITY_STATE))
    assert flat["active_tab"] == "training"


def test_normalize_preserves_mode_fields():
    flat = _flat(_session_ctx("plant_process", PLANT_STATE, submode="heat_rejection"))
    assert flat["active_mode"] == "plant_process"
    assert flat["mode_submode"] == "heat_rejection"
    assert flat["mode_state"]["active_zone"]["id"] == "heat_rejection"
    assert flat["mode_contract"]["contract_version"] == 1


def test_normalize_tolerates_missing_mode_contract():
    # Back-compat: a payload with no session.mode_contract must not error and
    # must not invent a mode.
    flat = server.normalize_agent_context({"attachments": {"part": {"part_number": "X"}}})["flat"]
    assert "active_mode" not in flat
    assert server._build_context_message(flat).find("[MODE]") == -1


# ---------------------------------------------------------------------------
# Increment 2: facility_layout
# ---------------------------------------------------------------------------

def test_facility_layout_context_has_route_capacity_facts():
    msg = _context_message("facility_layout", FACILITY_STATE)
    assert "[MODE]" in msg
    assert "[FACILITY LAYOUT]" in msg
    # Deterministic numbers must be surfaced verbatim (Sage must cite, not invent).
    assert "7.893 m" in msg
    assert "ETA ~5 s" in msg
    assert "1280 boxes" in msg
    assert "Aisle_BC_Center_Clear_Aisle" in msg


def test_facility_layout_system_addendum_is_mode_specific():
    add = server._mode_system_addendum("facility_layout")
    assert "Facility Layout mode" in add
    assert "racks" in add and "aisles" in add
    # Acceptance: must not invent distances/capacities.
    assert "Do NOT invent" in add
    # Acceptance: must avoid plant framing unless asked to compare.
    assert "plant-process" in add and "compare" in add


def test_facility_layout_stale_route_is_flagged():
    state = dict(FACILITY_STATE)
    state["route"] = dict(FACILITY_STATE["route"], matches_current_selection=False)
    msg = _context_message("facility_layout", state)
    assert "[STALE" in msg


# ---------------------------------------------------------------------------
# Increment 2: plant_process
# ---------------------------------------------------------------------------

def test_plant_process_context_has_zone_group_flow_facts():
    msg = _context_message("plant_process", PLANT_STATE, submode="heat_rejection")
    assert "[PLANT PROCESS]" in msg
    assert "Heat rejection core" in msg
    assert "fan_deck" in msg and "basin" in msg          # selected equipment groups
    assert "warm_return" in msg and "cooled_supply" in msg  # active flow ids


def test_plant_process_system_addendum_is_mode_specific():
    add = server._mode_system_addendum("plant_process")
    assert "Plant / Process" in add
    assert "process flow" in add
    # Acceptance: must avoid facility routing framing unless asked to compare.
    assert "facility-layout" in add and "compare" in add


# ---------------------------------------------------------------------------
# Assembly training: separate from the normal Assembly tab
# ---------------------------------------------------------------------------

def test_assembly_training_context_has_viewport_facts_without_drawing_prereqs():
    flat = _flat(_session_ctx("assembly_training", ASSEMBLY_TRAINING_STATE))
    flat.update({
        "has_drawing_file": False,
        "has_part_number": False,
        "inspection_can_run": False,
    })
    msg = server._build_context_message(flat)
    assert "[ASSEMBLY TRAINING]" in msg
    assert "Racing Bike Assembly" in msg
    assert "Complete Racing Bike Assembly" in msg
    assert "racing_bike_assembly.glb" in msg
    assert "NO DRAWING" not in msg
    assert "NO PART" not in msg


def test_assembly_training_addendum_blocks_product_guessing():
    add = server._mode_system_addendum("assembly_training")
    assert "Assembly Training mode" in add
    assert "training viewport" in add
    assert "engine" in add and "Do NOT identify" in add


# ---------------------------------------------------------------------------
# Mode switching + cross-mode isolation
# ---------------------------------------------------------------------------

def test_switching_modes_changes_the_next_request():
    fac = _context_message("facility_layout", FACILITY_STATE)
    plant = _context_message("plant_process", PLANT_STATE, submode="heat_rejection")
    assert fac != plant
    assert "[FACILITY LAYOUT]" in fac and "[FACILITY LAYOUT]" not in plant
    assert "[PLANT PROCESS]" in plant and "[PLANT PROCESS]" not in fac


def test_no_cross_mode_leakage_in_context():
    fac = _context_message("facility_layout", FACILITY_STATE)
    plant = _context_message("plant_process", PLANT_STATE)
    # Facility facts (route distance) absent from plant context, and vice versa.
    assert "7.893 m" not in plant
    assert "Heat rejection core" not in fac


# ---------------------------------------------------------------------------
# Unregistered modes: plumbing only (one-line echo, no addendum)
# ---------------------------------------------------------------------------

def test_unregistered_mode_gets_echo_but_no_addendum():
    # 'dfm' is a real tab with no registered contract (drawing/3dmodel/assembly/
    # report/report_fai became registered in Increment 3).
    assert "dfm" not in server.MODE_CONTRACTS
    msg = _context_message("dfm", {})
    assert "Active mode: dfm" in msg
    assert "[FACILITY LAYOUT]" not in msg and "[PLANT PROCESS]" not in msg
    assert server._mode_system_addendum("dfm") == ""


def test_no_mode_renders_nothing():
    assert server._render_mode_contract_section(None, None, None) == ""
    assert server._mode_system_addendum(None) == ""


# ---------------------------------------------------------------------------
# Frontend static guard: the wiring exists in the served app
# ---------------------------------------------------------------------------

def test_frontend_builds_and_sends_mode_contract():
    html = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "function buildModeContract(" in html
    assert "att.session.mode_contract" in html
    assert "att.session.active_mode" in html
    # Facility + plant are the two populated modes in Increment 2.
    assert "facilityLayoutRoute" in html and "plantProcessActiveZone" in html


# ---------------------------------------------------------------------------
# Increment 3: drawing / 3dmodel / assembly / report / report_fai
# These modes' facts already flow via existing context sections, so the
# contracts add reasoning style + guardrails only (no duplicated state).
# ---------------------------------------------------------------------------

INCREMENT3_MODES = ["drawing", "3dmodel", "assembly", "report", "report_fai"]


def test_increment3_modes_are_registered():
    for m in INCREMENT3_MODES:
        assert m in server.MODE_CONTRACTS, f"missing contract for {m}"


def test_increment3_addenda_are_mode_specific_and_guarded():
    for m in INCREMENT3_MODES:
        add = server._mode_system_addendum(m)
        assert add, f"empty addendum for {m}"
        assert server.MODE_CONTRACTS[m]["label"] in add
        # Every Increment 3 contract carries a do-not-invent guardrail and keeps
        # facility/plant framing out of CAD/inspection modes.
        assert "Do NOT invent" in add
        assert "facility-layout or plant-process framing" in add


def test_drawing_addendum_specifics():
    add = server._mode_system_addendum("drawing")
    assert "GD&T" in add and "ASME" in add and "dimension" in add.lower()


def test_3dmodel_addendum_specifics():
    add = server._mode_system_addendum("3dmodel")
    assert "CAD features" in add and "revision" in add.lower()


def test_assembly_addendum_specifics():
    add = server._mode_system_addendum("assembly")
    assert "mates" in add.lower() and "parts" in add.lower()
    assert "[MOTION] group labels/functions/part_numbers" in add
    assert "set_part_highlight mode replace" in add
    assert "play_motion at 30-40 RPM" in add
    assert "pin_bore_fai_affected" not in add


def test_motion_context_renders_group_function():
    sec = server._render_mode_contract_section("assembly", None, {
        "motion": {
            "available": True,
            "motions": [{
                "motion_id": "m1",
                "name": "Sample motion",
                "driver": "driver-1",
                "default_rpm": 90,
                "rpm_range": [10, 600],
                "moving_component_count": 2,
                "groups": [{
                    "id": "joint_a",
                    "label": "Joint A",
                    "part_numbers": ["100001", "100002"],
                    "component_count": 2,
                    "function": "Transfers rotation through the joint interface.",
                }],
            }],
            "playback": {"playing": False},
        }
    })
    assert "[MOTION]" in sec
    assert "Function: Transfers rotation through the joint interface." in sec


def test_report_fai_addendum_specifics():
    add = server._mode_system_addendum("report_fai")
    assert "FAI" in add
    assert "measured" in add.lower() and "pending" in add.lower()


def test_increment3_modes_render_echo_without_duplicating_facts():
    # The [MODE] echo appears, but no facility/plant facts blocks leak in
    # (their facts come from the existing drawing/selection/inspection sections).
    for m in INCREMENT3_MODES:
        sec = server._render_mode_contract_section(m, None, {})
        assert sec.startswith("[MODE]") and m in sec
        assert "[FACILITY LAYOUT]" not in sec and "[PLANT PROCESS]" not in sec


def test_frontend_resolves_report_fai():
    html = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "report_fai" in html
    assert "faiCharacteristics" in html


if __name__ == "__main__":
    # Allow running without pytest (the project venv with pytest may not be
    # active locally): execute every test_* function and report.
    import traceback

    _tests = sorted(
        (name, obj) for name, obj in list(globals().items())
        if name.startswith("test_") and callable(obj)
    )
    _passed = _failed = 0
    for _name, _fn in _tests:
        try:
            _fn()
            _passed += 1
            print(f"PASS {_name}")
        except Exception:  # noqa: BLE001
            _failed += 1
            print(f"FAIL {_name}")
            traceback.print_exc()
    print(f"\n{_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)
