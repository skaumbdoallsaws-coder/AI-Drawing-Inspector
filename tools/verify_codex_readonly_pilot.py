"""Offline App Server/MCP verification against a copied, real facility layout.

Never starts a model turn. The provider points at a closed loopback port, and no
API credential is read or passed. Output contains evidence, not engineering data.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import site
import sys


async def verify(args):
    from ai_inspector.codex_runtime.app_server import AppServer
    from ai_inspector.codex_runtime.facility_tools import FacilityReadGateway
    from ai_inspector.codex_runtime.mcp_bridge import serve_gateway
    from ai_inspector.codex_runtime.pilot import INSTRUCTIONS
    from ai_inspector.codex_runtime.policy import READONLY_PROFILE, RUNTIME_VERSION, child_environment, runtime_config
    from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID

    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = args.layout_file.read_bytes()
    source_hash = hashlib.sha256(source).hexdigest()
    document = json.loads(source)
    isolated_store = output / "facility"
    authority_source = (args.source_root / "authorities").resolve()
    if sys.platform == "win32":
        isolated_store = Path("\\\\?\\" + str(isolated_store))
        authority_source = Path("\\\\?\\" + str(authority_source))
    shutil.copytree(authority_source, isolated_store / "authorities")
    host = LocalFacilityLayoutHost(isolated_store, private_assets=True, private_asset_root=args.catalog_root)
    try:
        host.ensure_bootstrap()
        principal = host.principal()
        created = host.layout_repository.create_layout(principal, LOCAL_SITE_ID, document)
        reference = {"siteId": LOCAL_SITE_ID, "layoutId": document["layoutId"], "revision": created["revision"]}
        gateway = FacilityReadGateway(host.agent_runtime, principal, reference, turn_id="offline-verification")
        child_root = output / "runtime"
        async with serve_gateway(gateway) as (url, token):
            env = child_environment(child_root, token)
            config = runtime_config(url, "offline-not-a-model", offline=True)
            async with AppServer(args.binary, child_root, env, config) as runtime:
                effective = (await runtime.request("config/read", {"includeLayers": False}))["config"]
                if effective.get("features", {}).get("shell_tool") is not False:
                    raise RuntimeError("Runtime did not apply the shell restriction")
                if set(effective.get("mcp_servers", {})) != {"inspectorpro"}:
                    raise RuntimeError("Unexpected MCP servers in effective runtime configuration")
                started = await runtime.request("thread/start", {
                    "model": config["model"], "modelProvider": "inspectorpro",
                    "cwd": str(child_root / "workspace"), "approvalPolicy": "never",
                    "permissions": READONLY_PROFILE, "runtimeWorkspaceRoots": [str(child_root / "workspace")],
                    "baseInstructions": INSTRUCTIONS, "config": config,
                }, timeout=45)
                if started.get("activePermissionProfile", {}).get("id") != READONLY_PROFILE:
                    raise RuntimeError("Runtime did not select the restricted permissions profile")
                thread_id = started["thread"]["id"]
                calls = [
                    ("inspect_facility_context", {}),
                    ("inspect_facility_semantics", {"view": "overview"}),
                    ("analyze_facility_spatial", {"analysis": "resolve_entities", "query": "gym"}),
                ]
                for name, arguments in calls:
                    result = await runtime.request("mcpServer/tool/call", {
                        "threadId": thread_id, "server": "inspectorpro", "tool": name, "arguments": arguments,
                    }, timeout=60)
                    # Verify the domain envelope, not merely a successful JSON-RPC response.
                    structured = result.get("structuredContent")
                    if structured is None:
                        for block in result.get("content", []):
                            if block.get("type") == "text":
                                structured = json.loads(block["text"])
                                break
                    if not structured or not structured.get("ok"):
                        raise RuntimeError("Offline inspection did not return successful domain evidence: " + name)
                current = host.service.get_layout(principal, LOCAL_SITE_ID, document["layoutId"])
                if current["revision"] != created["revision"]:
                    raise RuntimeError("Read-only verification changed the copied layout")
        if hashlib.sha256(args.layout_file.read_bytes()).hexdigest() != source_hash:
            raise RuntimeError("Source layout changed during verification")
        evidence = {
            "runtimeVersion": RUNTIME_VERSION, "modelTurns": 0, "apiCredentialsPassed": False,
            "permissionProfile": READONLY_PROFILE,
            "copiedLayoutId": document["layoutId"], "sourceSha256": source_hash,
            "sourceUnchanged": True, "copiedRevisionUnchanged": True,
            "zones": len(document.get("zones", [])), "placements": len(document.get("placements", [])),
            "tools": gateway.receipts, "limitations": ["No model planning or live Sage UI behavior verified by this check."],
        }
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(evidence, indent=2))
    finally:
        host.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--dependency-dir", type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--layout-file", required=True, type=Path)
    parser.add_argument("--catalog-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", required=True, type=Path, help="New disposable directory; must not already exist")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if args.dependency_dir:
        site.addsitedir(str(args.dependency_dir.resolve()))
    asyncio.run(verify(args))


if __name__ == "__main__":
    main()
