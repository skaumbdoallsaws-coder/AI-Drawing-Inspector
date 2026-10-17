"""Opt-in, bounded provider smoke check. Does not open or modify any layout."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_inspector.model_gateway import GatewayClient, GatewayError, parse_config


async def check(config, deployment):
    value = json.loads(json.dumps(config))
    value["roles"]["facility-planner"] = deployment
    route = parse_config(value).route("facility-planner")
    client = GatewayClient(route)
    messages = [{"role": "user", "content": "Inspect the draft layout identified by layout-demo. Do not change or save it."}]
    tools = [{"name": "inspect_layout", "description": "Read an explicit layout identity.",
              "input_schema": {"type": "object", "properties": {"layout_id": {"type": "string"}},
                               "required": ["layout_id"], "additionalProperties": False}}]
    started = time.monotonic()
    record = {"deployment": deployment, "gateway": route.metadata(), "calls": [], "savedLayoutAccess": False}
    try:
        first = await client.invoke(system="Use only the supplied read-only tool. Never claim edits.", messages=messages,
                                    tools=tools, required_tool_name="inspect_layout", max_tokens=4096)
        record["calls"].append({"stopReason": first.stop_reason, "receipt": first.gateway_metadata,
                                "usage": vars(first.usage)})
        calls = [block for block in first.content if block.type == "tool_use"]
        if len(calls) != 1 or calls[0].name != "inspect_layout" or calls[0].input != {"layout_id": "layout-demo"}:
            raise GatewayError("gateway_smoke_tool_mismatch", "The forced read-only call did not match its schema and explicit identity.")
        call = calls[0]
        messages.extend([
            {"role": "assistant", "content": [{"type": "tool_use", "id": call.id, "name": call.name, "input": call.input}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": call.id,
                "content": json.dumps({"layout_id": "layout-demo", "placements": 3, "saved": False})}]},
        ])
        deltas = []
        second = await client.invoke(system="Report only the observed placement count and that no Save occurred in one sentence.",
                                     messages=messages, max_tokens=4096, stream_sink=deltas.append)
        text = "".join(block.text for block in second.content if block.type == "text")
        if second.stop_reason != "end_turn" or "3" not in text or not deltas:
            raise GatewayError("gateway_smoke_followup_mismatch", "The streamed follow-up did not confirm the observed count.")
        record["calls"].append({"stopReason": second.stop_reason, "receipt": second.gateway_metadata,
                                "usage": vars(second.usage), "text": text, "streamDeltas": len(deltas)})
        record["status"] = "passed"
    except GatewayError as exc:
        record.update(status="failed", error={"code": exc.code, "message": str(exc), "details": exc.details})
    record["elapsedSeconds"] = round(time.monotonic() - started, 3)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Authorize paid, bounded provider calls.")
    parser.add_argument("--deployment", choices=("claude-baseline", "astra-candidate"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to authorize provider calls.")
    from dotenv import load_dotenv
    load_dotenv(ROOT.parent / ".env", override=False)
    load_dotenv(ROOT / ".env", override=False)
    config = json.loads((ROOT / "config/sage-gateway.json").read_text())
    result = asyncio.run(check(config, args.deployment))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
