"""Inspect or atomically change backend-owned model aliases. Never invokes a model."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_inspector.model_gateway import CONFIG_ENV, GatewayError, load_config, parse_config


def select_deployment(path, role, deployment):
    path = Path(path).resolve(strict=True)
    lock = path.with_suffix(path.suffix + ".lock")
    try:
        handle = lock.open("x", encoding="ascii")
    except FileExistsError:
        raise GatewayError("model_gateway_config_busy", "Another configuration update owns the lock; no change made.") from None
    temporary = None
    try:
        with handle:
            handle.write(str(os.getpid()))
        prior = path.read_bytes()
        load_config({CONFIG_ENV: str(path)})
        value = json.loads(prior.decode("utf-8-sig"))
        if role not in value["roles"] or deployment not in value["deployments"]:
            raise GatewayError("model_gateway_config_invalid", "Unknown role or deployment.")
        value["roles"][role] = deployment
        config = parse_config(value)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump(value, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        if path.read_bytes() != prior:
            raise GatewayError("model_gateway_config_changed", "Configuration changed during update; no replacement made.")
        os.replace(temporary, path)
        return config.metadata()
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/sage-gateway.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show")
    commands.add_parser("validate")
    select = commands.add_parser("select")
    select.add_argument("role")
    select.add_argument("deployment")
    args = parser.parse_args()
    try:
        if args.command == "select":
            result = select_deployment(args.config, args.role, args.deployment)
            result["activeRunPolicy"] = "Existing runs reject a changed configuration; finish them before switching."
        else:
            result = load_config({CONFIG_ENV: str(args.config)}).metadata()
            result["configurationValid"] = True
            result["activationVariable"] = CONFIG_ENV
        print(json.dumps(result, indent=2))
        return 0
    except (GatewayError, OSError) as error:
        print(json.dumps({"error": {"code": getattr(error, "code", "model_gateway_file_failed"),
                                    "message": str(error) if isinstance(error, GatewayError) else type(error).__name__}}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
