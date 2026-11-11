"""Loopback-only real server used by smoke_documentation_editor.py.

This file is copied into the sanitized snapshot, never imported by production.
The small HTTP bridge invokes the real Sage gateway/host without a provider or
credentials. It is a host contract proof, not a live Sage inference run.
"""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import socket
import sys


def install_source_fixture(server, scratch):
    """Install only in the isolated launcher; no production fixture reader exists."""
    from copy import deepcopy
    import hashlib
    import json
    from fastapi import Request
    from fastapi.responses import JSONResponse

    scratch = Path(scratch).resolve()
    fixture_path = scratch / "source-fixture.json"
    original = server._parts_manual_catalog_for_assembly
    fixture = json.loads(fixture_path.read_text("ascii")) if fixture_path.exists() else None

    def catalog(number):
        assembly, value = original(number)
        if fixture is None or number != fixture["assemblyNumber"]:
            return assembly, value
        value = deepcopy(value)
        value["sourceRevision"] = fixture["sourceRevision"]
        for row in value["occurrences"]:
            if row.get("definitionId") == fixture["definitionId"]:
                row["description"] = fixture["description"]
                row["partNumber"] = fixture["partNumber"]
                row["displayPartNumber"] = fixture["partNumber"]
        value["occurrences"].reverse()
        return assembly, value

    async def source_fixture(request: Request):
        nonlocal fixture
        if request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            return JSONResponse(status_code=403, content={"error": "loopback only"})
        body = await request.json()
        if (set(body) != {"assemblyNumber", "definitionId", "description", "partNumber"}
                or body.get("assemblyNumber") != "MMLE-50D"
                or any(not isinstance(value, str) or not value for value in body.values())):
            return JSONResponse(status_code=422, content={"error": "invalid fixture"})
        _, baseline = original(body["assemblyNumber"])
        if body["definitionId"] not in {row.get("definitionId") for row in baseline["occurrences"]}:
            return JSONResponse(status_code=422, content={"error": "unknown definition"})
        candidate = {**body, "sourceRevision": hashlib.sha256(
            json.dumps({"source": baseline["sourceRevision"], **body}, sort_keys=True).encode("ascii")).hexdigest()}
        temporary = fixture_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(candidate, sort_keys=True) + "\n", encoding="ascii", newline="\n")
        temporary.replace(fixture_path)
        fixture = candidate
        return {"success": True, **fixture}

    server._parts_manual_catalog_for_assembly = catalog
    source_fixture.__annotations__["request"] = Request
    server.app.add_api_route("/__p1c/source-fixture", source_fixture, methods=["POST"])
    return catalog


def main():
    scratch = Path(sys.argv[1]).resolve()
    port = int(sys.argv[2])
    code = Path(__file__).resolve().parent
    code.relative_to(scratch)
    sys.path.insert(0, str(code))
    sys.dont_write_bytecode = True

    def within(path):
        try:
            text = os.fsdecode(path)
            # Stores use Windows' extended-length form (\\?\C:\...); compare the plain path.
            if text.startswith("\\\\?\\UNC\\"):
                text = "\\\\" + text[8:]
            elif text.startswith("\\\\?\\"):
                text = text[4:]
            Path(text).resolve().relative_to(scratch)
            return True
        except (ValueError, TypeError):
            return False

    def audit(event, args):
        if event == "socket.connect":
            address = args[1]
            if isinstance(address, tuple) and not ipaddress.ip_address(address[0]).is_loopback:
                raise PermissionError("Smoke forbids outbound connections")
        if event == "socket.getaddrinfo" and args[0] not in {None, "localhost", "127.0.0.1", "::1"}:
            raise PermissionError("Smoke forbids outbound DNS")
        if event == "open":
            target, mode, flags = args
            if isinstance(target, (str, bytes, os.PathLike)):
                target_path = Path(os.fsdecode(target))
                if any(part.lower().startswith(".env") or part.lower() == "ui-data"
                       for part in target_path.parts):
                    raise PermissionError("Smoke forbids private files")
                writing = bool((flags or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
                if writing and not within(target):
                    raise PermissionError("Smoke write escaped temporary store")
        if event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.truncate"}:
            if not isinstance(args[0], int) and not within(args[0]):
                raise PermissionError("Smoke mutation escaped temporary store")
        if event in {"os.rename", "os.link", "os.symlink"}:
            if not within(args[0]) or not within(args[1]):
                raise PermissionError("Smoke move escaped temporary store")

    sys.addaudithook(audit)
    import dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False
    import server
    assert Path(server.__file__).resolve() == code / "server.py"
    expected = {"PARTS_MANUAL_ROOT": "p", "OPERATIONS_MANUAL_ROOT": "o",
                "SPECIFICATION_SHEET_ROOT": "s", "WORK_INSTRUCTION_ROOT": "w",
                "INSPECTION_SHEET_ROOT": "i", "ASSEMBLY_APPEARANCE_ROOT": "a",
                "PART_APPEARANCE_ROOT": "b"}
    for name, short in expected.items():
        assert getattr(server, name).resolve() == scratch / "d" / short, name
    assert Path(server.LIBRARY_DIR).resolve() == code / "400S_Sorted_Library"

    install_source_fixture(server, scratch)

    from fastapi import Request
    from fastapi.responses import JSONResponse
    from types import SimpleNamespace
    from ai_inspector.codex_runtime.documentation_tools import DocumentationGateway
    gateway = DocumentationGateway(server._DOCUMENTATION_AGENT_HOST,
        SimpleNamespace(tenant_id="isolated-proof", principal_id="reviewer", roles=(), allowed_site_ids=()),
        {"assemblyNumber": "MMLE-50D", "documentType": "illustrated_parts_manual"},
        turn_id="documentation-browser-proof", max_calls=80, timeout=1800,
        user_message=("Resolve only the selected description conflict using merge_text with P1c reviewed merged description."
                      if (scratch / "source-fixture.json").exists() else
                      "Change the selected description in this temporary proof document."))

    async def tool(request: Request):
        if request.client.host not in {"127.0.0.1", "::1"}:
            return JSONResponse(status_code=403, content={"error": "loopback only"})
        data = await request.json()
        if data.get("name") not in {"find_document_text", "read_document_pages", "edit_document_text", "apply_document_edits",
                                    "propose_document_value_confirmation", "inspect_document_change", "undo_document_change",
                                    "read_document_conflicts", "resolve_document_conflicts"}:
            return JSONResponse(status_code=403, content={"error": "proof tool denied"})
        return await gateway.call(data["name"], data.get("arguments") or {})

    async def isolation():
        return {"roots": {name: str(getattr(server, name)) for name in expected},
                "snapshot": str(code), "dotenvDisabled": True, "outboundBlocked": True}

    # Request was imported after the isolation guard, inside main. Resolve the
    # postponed annotation explicitly for FastAPI's signature inspection.
    tool.__annotations__["request"] = Request
    server.app.add_api_route("/__p1a/tool", tool, methods=["POST"])
    server.app.add_api_route("/__p1a/isolation", isolation, methods=["GET"])
    import uvicorn
    # Avoid unrelated background services, as in the P0 TestClient collector.
    uvicorn.run(server.app, host="127.0.0.1", port=port, lifespan="off", log_level="warning")


if __name__ == "__main__":
    main()
