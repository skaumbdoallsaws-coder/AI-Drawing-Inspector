"""Seed an isolated application snapshot for the native documentation gate.

Run ONLY in a prepare-snapshot.py output. --inputs names the explicitly supplied
engineering fixture checkout; only documentation_baseline.local_inventory's
allowlist and the two browser-proof plan/scene files are copied from it.
No server is imported, no package is installed, no account files are inspected.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
ROOTS = {"PARTS_MANUAL_ROOT": "p", "OPERATIONS_MANUAL_ROOT": "o",
         "SPECIFICATION_SHEET_ROOT": "s", "WORK_INSTRUCTION_ROOT": "w",
         "INSPECTION_SHEET_ROOT": "i", "ASSEMBLY_APPEARANCE_ROOT": "a",
         "PART_APPEARANCE_ROOT": "b"}


def local_path(value):
    value = Path(value)
    if not value.is_absolute() or str(value).startswith("\\\\"):
        raise ValueError("An absolute local path is required")
    for parent in (value, *value.parents):
        if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
            raise ValueError("Linked paths are not allowed")
    return value.resolve()


def snapshot_root(root):
    root = local_path(root)
    checkpoint = root / "desktop-checkpoint.json"
    if (root / ".git").exists() or not checkpoint.is_file():
        raise ValueError("Use an isolated prepare-snapshot.py output, never a live checkout")
    value = json.loads(checkpoint.read_text("utf-8"))
    source = local_path(value["source"])
    if root == source or root.is_relative_to(source) or source.is_relative_to(root):
        raise ValueError("The snapshot and live checkout must not overlap")
    if value.get("schemaVersion") != 1 or not (root / "desktop-source-manifest.json").is_file():
        raise ValueError("The snapshot checkpoint is incomplete")
    # Only test existence; never read an environment file. application_backend
    # deliberately permits dotenv, so both explicit server.py lookup sites must be absent.
    if (root / ".env").exists() or (root.parent / ".env").exists():
        raise ValueError("The isolated snapshot and its parent must have no .env file")
    return root


def prepare(root, output, inputs, dependencies=()):
    root, output, inputs = snapshot_root(root), local_path(output), local_path(inputs)
    if not output.is_relative_to(root / ".runtime") or output == root / ".runtime":
        raise ValueError("The disposable output must be below the snapshot's .runtime")
    if output.exists():
        raise ValueError("Use a new output folder; existing profiles are never overwritten")
    dependencies = [local_path(item) for item in dependencies]
    if any(not item.is_dir() or item.is_relative_to(output) for item in dependencies):
        raise ValueError("Dependency folders must already exist outside the output")
    sys.path.insert(0, str(root))
    try:
        from tools.documentation_baseline import local_inventory, safe_source
    finally:
        sys.path.pop(0)
    local_path(inputs / "ai_inspector/assembly_knowledge/documentation_assembly_registry.json")
    inventory = local_inventory(inputs)
    if not inventory["available"]:
        raise ValueError("Required MMLE inputs absent: " + repr(inventory["missingInputs"]))
    names = list(inventory["inputFiles"])
    contract = "static/contracts/semantic-knowledge-prototype-v1.json"
    if safe_source(contract, inputs).is_file():
        names.append(contract)
    seeds = ["generated/parts_manual/mmle-50d/" + name
             for name in ("manual-plan.json", "documentation-scene.json")]
    for name in seeds:
        if not safe_source(name, inputs).is_file():
            raise ValueError("Missing browser-proof seed: " + name)
    # Validate every source/destination before creating anything. No recursive library copy.
    sources = [(name, local_path(inputs / name)) for name in sorted(set(names + seeds))]
    output.mkdir(parents=True)
    data = output / "d"
    stores = {key: str(data / short) for key, short in ROOTS.items()}
    profile = dict(schemaVersion=1, mode="application", profileId="de-native-" + uuid4().hex[:8],
                   backendId=str(uuid4()), storeId=str(uuid4()), startupLayoutId=None,
                   dataRoot=str(data), facilityRoot=str(data / "f"), libraryRoot=str(data / "l"))
    for directory in [data, Path(profile["facilityRoot"]), Path(profile["libraryRoot"]),
                      output / "e", output / "tmp", output / "os", *map(Path, stores.values())]:
        directory.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    if port == 8480:
        raise ValueError("The user's desktop port is reserved; prepare a new profile")
    profile["origin"] = "http://127.0.0.1:" + str(port)
    manifest = []
    for name, source in sources:
        if name in seeds:
            target = Path(stores["PARTS_MANUAL_ROOT"]) / "mmle-50d" / Path(name).name
        elif name.startswith("400S_Sorted_Library/"):
            target = Path(profile["libraryRoot"]) / Path(name).relative_to("400S_Sorted_Library")
        else:
            target = root / name
        local_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        manifest.append(dict(source=name, destination=str(target), bytes=target.stat().st_size,
                             sha256=hashlib.sha256(target.read_bytes()).hexdigest(), seed=name in seeds))
    marker = dict(schemaVersion=1, disposable=True, codeRoot=str(root), output=str(output),
                  profileId=profile["profileId"], storeId=profile["storeId"], stores=stores,
                  dependencies=list(map(str, dependencies)), assemblyNumber="MMLE-50D", inputRoot=str(inputs), inputs=manifest,
                  flag="INSPECTORPRO_DOCUMENTATION_RICH_TEXT=1")
    # The marker is written last. A partial preparation can never launch.
    (output / "profile.json").write_text(json.dumps(profile, indent=2) + "\n", encoding="ascii", newline="\n")
    (data / "documentation-editor-check.json").write_text(json.dumps(marker, indent=2) + "\n", encoding="ascii", newline="\n")
    return {"profile": str(output / "profile.json"), "evidence": str(output / "e"),
            "origin": profile["origin"], "inputs": len(manifest), "stores": stores}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--dependencies", type=Path, action="append", default=[])
    args = parser.parse_args()
    print(json.dumps(prepare(ROOT, args.output, args.inputs, args.dependencies), indent=2))


if __name__ == "__main__":
    main()
