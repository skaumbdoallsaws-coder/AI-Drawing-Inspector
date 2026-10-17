"""Opt-in native gateway acceptance through the existing normal-app harness."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_inspector.model_gateway import CONFIG_ENV, parse_config


def summarize_native_reports(output):
    report = json.loads((output / "generation-check.json").read_text(encoding="utf-8"))
    runtime = json.loads((output / "last-application-run.json").read_text(encoding="utf-8"))
    backends = runtime.get("backends", [])
    cleanups = [backend.get("cleanup") or {} for backend in backends]
    return {"status": report.get("status", "no-stage-report"), "saveCalls": report.get("saveCalls"),
            "networkSaveCalls": runtime.get("network", {}).get("saveCalls"),
            "cleanupConfirmed": bool(cleanups) and all(
                all(cleanup.get(field) is True for field in ("terminationConfirmed", "stdioClosed", "resourcesClosed"))
                and not cleanup.get("shutdown", {}).get("cleanupErrors") for cleanup in cleanups)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--deployment", choices=("astra-candidate", "claude-baseline"), required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dependency-dir", type=Path)
    parser.add_argument("--desktop-profile", type=Path,
                        help="Verify the installed native profile's gateway binding on an isolated layout copy.")
    parser.add_argument("--port", type=int, default=8513)
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to authorize paid requests and a native test window.")
    if args.desktop_profile and args.dependency_dir:
        parser.error("The desktop profile owns its dependency directory; do not override it.")
    output = args.output.resolve()
    if output.exists() or ROOT not in output.parents:
        parser.error("Use a fresh output directory inside this project.")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    if args.dependency_dir:
        dependencies = args.dependency_dir.resolve(strict=True)
        if ROOT not in dependencies.parents or not (dependencies / "litellm").is_dir():
            parser.error("Dependency directory must contain the isolated project LiteLLM install.")
        env["PYTHONPATH"] = str(dependencies) + os.pathsep + env.get("PYTHONPATH", "")
    prepared = subprocess.run([sys.executable, str(ROOT / "desktop/tools/prepare-application-check.py"),
        "--destination", str(output), "--port", str(args.port)], cwd=ROOT, env=env,
        capture_output=True, timeout=60, creationflags=flags)
    if prepared.returncode:
        raise RuntimeError("Isolated preparation failed: " + prepared.stderr.decode("utf-8", errors="replace")[-2000:])
    scenario = json.loads(args.scenario.read_text(encoding="utf-8-sig"))
    if scenario.get("saveAfterApply"):
        parser.error("Gateway acceptance does not authorize Save.")
    (output / "scenario.json").write_text(json.dumps(scenario, indent=2), encoding="utf-8")
    if args.desktop_profile:
        from desktop.runtime.application_profile import load_application_profile
        native = load_application_profile(args.desktop_profile)
        binding = native.value.get("modelGateway")
        if not binding:
            parser.error("The selected native profile has no gateway binding.")
        config_path = Path(binding["configPath"])
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config["roles"]["facility-planner"] != args.deployment:
            parser.error("The installed planner does not match the requested deployment.")
        profile_path = output / "profile.json"
        isolated = json.loads(profile_path.read_text(encoding="utf-8"))
        isolated["modelGateway"] = binding
        profile_path.write_text(json.dumps(isolated, indent=2), encoding="utf-8")
        env.pop(CONFIG_ENV, None)
    else:
        config = json.loads((ROOT / "config/sage-gateway.json").read_text(encoding="utf-8"))
        config["roles"]["facility-planner"] = args.deployment
        config_path = output / "gateway.json"
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        env[CONFIG_ENV] = str(config_path)
    route = parse_config(config)
    # Telemetry and conversation stores are isolated along with the facility.
    env.update(INSPECTORPRO_METRICS_DB=str(output / "metrics.sqlite"),
               INSPECTORPRO_MEMORY_DB_PATH=str(output / "memory.sqlite"),
               INSPECTORPRO_CHAT_FEEDBACK_DB_PATH=str(output / "feedback.sqlite"))
    command = [str(ROOT / "desktop/node_modules/electron/dist/electron.exe"), str(ROOT / "desktop/src/entry.cjs"),
               "--application", "--profile-file", str(output / "profile.json"), "--python", sys.executable,
               "--generation-acceptance-output", str(output)]
    result = {"gateway": route.metadata(), "status": "running", "startedAt": time.time(),
              "bindingSource": "desktop-profile" if args.desktop_profile else "test-environment"}
    with (output / "electron.stdout.log").open("wb") as stdout, (output / "electron.stderr.log").open("wb") as stderr:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=stdout, stderr=stderr, creationflags=flags)
        result["pid"] = child.pid
        (output / "launcher.json").write_text(json.dumps(result, indent=2))
        try:
            result["exitCode"] = child.wait(timeout=900)
        except subprocess.TimeoutExpired:
            result["timeout"] = True
            cleanup = subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                                     capture_output=True, timeout=30, creationflags=flags)
            result["forcedCleanupExitCode"] = cleanup.returncode
            result["exitCode"] = child.wait(timeout=15)
    try:
        result.update(summarize_native_reports(output))
    except (OSError, ValueError) as error:
        result.update(status="report-unavailable", reportError=type(error).__name__, cleanupConfirmed=False)
    result["elapsedSeconds"] = round(time.time() - result["startedAt"], 3)
    (output / "launcher.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if (result["exitCode"] == 0 and result["status"] == "passed" and result.get("saveCalls") == 0
                 and result.get("networkSaveCalls") == 0 and result["cleanupConfirmed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
