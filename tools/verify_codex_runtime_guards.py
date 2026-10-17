"""Offline native-tool audit and write-denial probe; no remote API or credentials.

A scripted loopback provider asks the real pinned runtime to create a canary.
Passing means the runtime rejects the write, not that a real model was tested.
"""
from __future__ import annotations

import argparse
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import site
import sys
import threading


def tool_names(tools, prefix=""):
    names = set()
    for tool in tools:
        name = prefix + tool.get("name", tool.get("type", ""))
        if tool.get("type") == "namespace":
            names.update(tool_names(tool.get("tools", []), name + "__"))
        else:
            names.add(name)
    return names


async def verify(args):
    from ai_inspector.codex_runtime.app_server import AppServer
    from ai_inspector.codex_runtime.facility_tools import FacilityReadGateway
    from ai_inspector.codex_runtime.mcp_bridge import serve_gateway
    from ai_inspector.codex_runtime.policy import child_environment, runtime_config
    from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID, LOCAL_LAYOUT_ID

    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            if self.path != "/v1/responses" or not 0 < length < 2000000:
                self.send_error(400)
                return
            requests.append(json.loads(self.rfile.read(length)))
            if len(requests) > 2:
                self.send_error(400)
                return
            if len(requests) == 1:
                item = {"id": "probe-call", "type": "custom_tool_call", "name": "apply_patch",
                    "call_id": "probe-call", "input": "*** Begin Patch\n*** Add File: denied-canary.txt\n+must not be written\n*** End Patch\n"}
            else:
                item = {"id": "probe-answer", "type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "Offline guard check complete."}]}
            events = [{"type": "response.output_item.added", "output_index": 0, "item": item}]
            if len(requests) == 2:
                events.append({"type": "response.output_text.delta", "output_index": 0, "content_index": 0,
                    "item_id": "probe-answer", "delta": "Offline guard check complete."})
            events.extend([
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {"type": "response.completed", "response": {"id": "probe-response", "status": "completed",
                    "output": [item], "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}},
            ])
            raw = "".join("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n" for event in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    host = LocalFacilityLayoutHost(root / "facility", private_assets=False)
    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    try:
        host.ensure_bootstrap()
        doc = host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
        reader = FacilityReadGateway(host.agent_runtime, host.principal(), {
            "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": doc["revision"]}, turn_id="offline-guard")
        async with serve_gateway(reader) as (url, token):
            config = runtime_config(url, args.model, offline=True, auth_mode=args.auth_mode)
            config["model_providers"]["inspectorpro"]["base_url"] = f"http://127.0.0.1:{http.server_port}/v1"
            child_root = root / "runtime"
            async with AppServer(args.binary.resolve(), child_root, child_environment(child_root, token), config) as runtime:
                await asyncio.wait_for(runtime.inspect(message="Offline write guard probe", thread_id=None,
                    instructions="Offline scripted provider test.", on_thread=lambda _: None,
                    text_sink=None, status_sink=None, check=reader.check), 60)
        tools = requests[0].get("tools", [])
        (root / "offline-requests.json").write_text(json.dumps(requests, indent=2) + "\n", encoding="utf-8")
        names = tool_names(tools)
        authorized_mcp = {"mcp__inspectorpro__" + name for name in config["mcp_servers"]["inspectorpro"]["enabled_tools"]}
        allowed = {"list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource",
                   "request_user_input", "apply_patch", "tool_search"}
        if not names or not names.issubset(allowed | authorized_mcp):
            raise RuntimeError("Unexpected native tool surface; do not start live inference: " + repr(sorted(names)))
        outputs = [item.get("output") for request in requests for item in request.get("input", [])
                   if item.get("type") == "custom_tool_call_output"]
        exists = (child_root / "workspace" / "denied-canary.txt").exists()
        if exists or not any("blocked by read-only sandbox" in str(output) for output in outputs):
            raise RuntimeError("Runtime did not prove write denial")
        evidence = {"model": args.model, "authMode": args.auth_mode, "modelInference": False, "apiCredentialsPassed": False,
            "nativeTools": sorted(names - authorized_mcp), "mcpToolCount": len(names & authorized_mcp),
            "writeRejected": True, "canaryCreated": exists,
            "scriptedProviderRequests": len(requests)}
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(evidence, indent=2))
    finally:
        http.shutdown()
        http.server_close()
        worker.join()
        host.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--dependency-dir", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--auth-mode", choices=["api_key", "chatgpt_plan"], default="api_key")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    site.addsitedir(str(args.dependency_dir.resolve()))
    asyncio.run(verify(args))


if __name__ == "__main__":
    main()
