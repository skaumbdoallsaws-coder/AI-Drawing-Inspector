"""Isolated full Sage UI for packaging, using an explicitly selected ChatGPT account.

Never changes the desktop profile, loads its engineering data, or falls back to API billing.
"""
from pathlib import Path
import argparse
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def configure(profile_path: Path, output: Path, *, live=False, memory_mode="enforce"):
    from desktop.runtime.application_profile import load_application_profile
    from ai_inspector.codex_runtime.policy import VERIFIED_MODELS
    profile = load_application_profile(profile_path.resolve()).value
    config = profile.get("codexRuntime") or {}
    if config.get("authMode") != "chatgpt_plan" or config.get("model") not in VERIFIED_MODELS:
        raise ValueError("Select an existing supported ChatGPT-plan desktop profile.")
    binary = Path(config.get("binary", ""))
    if not binary.is_absolute() or not binary.is_file():
        raise ValueError("The configured Codex runtime is unavailable.")
    output = output.resolve()
    if ROOT not in output.parents or ".runtime" not in output.relative_to(ROOT).parts:
        raise ValueError("Pilot data must stay in this worktree's .runtime directory.")
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "PYTHON_DOTENV_DISABLED": "1", "INSPECTORPRO_PACKAGING_ENABLED": "1",
        "INSPECTORPRO_PACKAGING_ROOT": str(output / "packages"),
        "INSPECTORPRO_CODEX_PACKAGING": "1", "INSPECTORPRO_CODEX_READONLY_PILOT": "1",
        "INSPECTORPRO_CODEX_EDIT_PREVIEWS": "1", "INSPECTORPRO_CODEX_AUTH_MODE": "chatgpt_plan",
        "INSPECTORPRO_CODEX_ALLOW_SUBSCRIPTION_INFERENCE": "1" if live else "0",
        "INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE": "0", "INSPECTORPRO_CODEX_API_KEY": "",
        "INSPECTORPRO_CODEX_BINARY": str(binary), "INSPECTORPRO_CODEX_MODEL": config["model"],
        "INSPECTORPRO_CODEX_PILOT_ROOT": str(output / "runtime"),
        "INSPECTORPRO_CODEX_AUTH_PROFILE_ID": profile["profileId"],
        "INSPECTORPRO_CODEX_AUTH_ROOT": str(Path(profile["dataRoot"]) / "chatgpt-auth"),
        "INSPECTORPRO_CODEX_DOCUMENTATION": "0", "INSPECTORPRO_CODEX_WEB_RESEARCH": "0",
        "INSPECTORPRO_MEMORY_V1_MODE": memory_mode, "INSPECTORPRO_MEMORY_DB_PATH": str(output / "memory.sqlite"),
        "INSPECTORPRO_METRICS_DB": str(output / "metrics.sqlite"),
        "INSPECTORPRO_FACILITY_LAYOUT_ROOT": str(output / "facility"),
        "INSPECTORPRO_PARTS_MANUAL_ROOT": str(output / "parts-manual"),
        "INSPECTORPRO_OPERATIONS_MANUAL_ROOT": str(output / "operations-manual"),
        "INSPECTORPRO_SPECIFICATION_SHEET_ROOT": str(output / "specification-sheet"),
        "INSPECTORPRO_WORK_INSTRUCTION_ROOT": str(output / "work-instruction"),
        "INSPECTORPRO_CHAT_STREAMING": "1", "INSPECTORPRO_STREAMING_AGENTS": "sage",
    })
    geometry_python = ROOT / ".runtime" / "step-venv" / "Scripts" / "python.exe"
    if geometry_python.is_file():
        os.environ["INSPECTORPRO_PACKAGING_GEOMETRY_PYTHON"] = str(geometry_python)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription-profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / "packaging-sage-pilot")
    parser.add_argument("--port", type=int, default=8180)
    parser.add_argument("--live", action="store_true", help="Enable expressly approved ChatGPT-plan inference")
    parser.add_argument("--memory-mode", choices=("off", "enforce"), default="enforce")
    args = parser.parse_args()
    configure(args.subscription_profile, args.output, live=args.live, memory_mode=args.memory_mode)
    import uvicorn
    import server
    uvicorn.run(server.app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
