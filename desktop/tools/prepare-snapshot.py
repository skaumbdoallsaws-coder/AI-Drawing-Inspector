"""Copy current InspectorPro working source into a new isolated desktop snapshot.

Run from the source project after reviewing its changes. No source files or Git
configuration are changed. On failure, the incomplete destination is retained
without a completion marker; choose a new destination after fixing the cause.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SOURCE_FOLDERS = frozenset({"ai_inspector", "static", "tools", "tests", "docs", "desktop", "scripts"})
SOURCE_EXTENSIONS = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".css", ".json",
    ".yaml", ".yml", ".md", ".txt", ".toml", ".ini", ".cfg", ".sql", ".svg",
    ".ps1", ".sh", ".bat", ".cmd", ".cs", ".csproj", ".sln", ".xml", ".csv",
})
TRACKED_FIXTURE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf",
    ".glb", ".gltf", ".bin", ".stl", ".obj", ".mtl", ".step", ".stp", ".pdf",
})
SOURCE_NAMES = frozenset({"license", "notice", "dockerfile", ".gitignore", ".gitattributes", ".npmrc.example"})
EXCLUDED_DIRECTORIES = frozenset({
    ".git", ".runtime", "runtime", "runtime_logs", "runtime_metrics", "runtime_data",
    "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".cache", ".mypy_cache",
    ".ruff_cache", ".codex", ".claude", ".agents", ".ssh", ".aws", ".azure",
    "secrets", "credentials", "private-keys", "uploads", "downloads", "attachments",
    "400s_sorted_library", "demo_library", "local_library", "library", "libraries",
    "dist", "build", "coverage", "test-results", "playwright-report", "tmp", "temp",
    "outputs", "output", "work",
})
EXCLUDED_FILENAMES = frozenset({
    "desktop-checkpoint.json", "desktop-source-manifest.json", ".npmrc", ".pypirc", ".netrc",
    "credentials.json", "secrets.json", "secrets.yaml", "secrets.yml", "token.json", "tokens.json",
    "bridge_token", "bridge.json", "id_rsa", "id_ed25519",
})
SECRET_MARKERS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    re.compile(rb"\bsk-(?:proj-|ant-)[A-Za-z0-9_-]{24,}"),
)
# These exact synthetic strings exercise redaction in existing repository tests.
# Reviewed as repeated-character/alphabet fixtures, not provider credentials.
# Scope exceptions to both path and literal digest; no blanket tests/ exemption.
SYNTHETIC_REDACTION_FIXTURES = {
    "tests/test_chat_feedback.py": frozenset({"72ef07ca1ccc5307e85c9f7835ceba1ed46a400314e80330ccfddc0c226045cf"}),
    "tests/test_memory_models.py": frozenset({"2c6d42e7459781d25d05c53cd1faa36ebdaedb2df4b8d88bba9a55c31ec6e7e5"}),
    "tests/test_memory_sqlite_repository.py": frozenset({
        "72ef07ca1ccc5307e85c9f7835ceba1ed46a400314e80330ccfddc0c226045cf",
        "8adc58edb9cc1d4b910b855175d398e2919f96d7712f8581d452e5933c83c791",
    }),
}


def has_potential_secret(relative: Path, content: bytes) -> bool:
    reviewed = SYNTHETIC_REDACTION_FIXTURES.get(relative.as_posix(), frozenset())
    return any(hashlib.sha256(match.group()).hexdigest() not in reviewed
               for pattern in SECRET_MARKERS for match in pattern.finditer(content))


def is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def checked_local_path(value: Path) -> Path:
    raw = str(value)
    if raw.startswith("\\\\?\\") and not raw.startswith("\\\\?\\UNC\\"):
        value = Path(raw[4:])
    elif raw.startswith("\\\\"):
        raise ValueError("Source and destination must be local filesystem paths")
    absolute = value.absolute()
    for item in (absolute, *absolute.parents):
        if is_link(item):
            raise ValueError("Source/destination ancestors must not be symlinks or junctions")
    return absolute.resolve()


def within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def excluded_directory(name: str, relative_parent: Path) -> bool:
    # This is Python source, not a mutable runtime-data tree.
    if name.casefold() == 'runtime' and relative_parent.as_posix().casefold() == 'desktop':
        return False
    # Published browser dependencies commonly place their runnable JS/CSS under
    # static/vendor/<package>/build or dist. Those are application source assets.
    static_tree = bool(relative_parent.parts) and relative_parent.parts[0].casefold() == "static"
    return name.casefold() in EXCLUDED_DIRECTORIES and not (
        static_tree and name.casefold() in {"build", "dist"}
    )


def relative_is_allowed(relative: Path, *, tracked: bool) -> bool:
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        return False
    parts = [part.casefold() for part in relative.parts]
    if not parts or any(excluded_directory(part, Path(*relative.parts[:index]))
                        for index, part in enumerate(parts[:-1])):
        return False
    name = parts[-1]
    if parts[:2] == ['desktop', 'runtime'] and relative.suffix.casefold() != '.py':
        return False
    if name in EXCLUDED_FILENAMES or name.startswith(".env") or name.startswith("service-account"):
        return False
    if name.endswith((".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3", ".db", ".log")):
        return False
    if not tracked and len(parts) > 1 and parts[0] not in SOURCE_FOLDERS:
        return False
    if not tracked and len(parts) == 1 and relative.suffix.casefold() not in {
        ".py", ".js", ".mjs", ".cjs", ".html", ".css", ".ps1", ".sh", ".md", ".toml"
    } and name not in {"requirements.txt", "package.json", "package-lock.json", "setup.cfg", *SOURCE_NAMES}:
        return False
    return (relative.suffix.casefold() in SOURCE_EXTENSIONS or name in SOURCE_NAMES
            or (tracked and relative.suffix.casefold() in TRACKED_FIXTURE_EXTENSIONS))


def git_inventory(source: Path) -> tuple[str, set[Path]]:
    git_root = next((path for path in (source, *source.parents) if (path / ".git").exists()), None)
    if git_root is None:
        raise ValueError("Source must belong to a Git repository")
    # Scope trust to this invocation; never change system/global/repository config.
    command = ["git", "-c", f"safe.directory={git_root}", "-C", str(source)]
    def run(*arguments):
        result = subprocess.run([*command, *arguments], capture_output=True, timeout=60)
        if result.returncode:
            raise ValueError("Read-only Git inventory failed; verify source ownership and repository state")
        return result.stdout
    head = run("rev-parse", "HEAD").decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", head):
        raise ValueError("Git returned an invalid source revision")
    paths = {Path(os.fsdecode(raw)) for raw in run("ls-files", "-z", "--cached", "--", ".").split(b"\0") if raw}
    return head, paths


def source_candidates(source: Path, tracked: set[Path]) -> list[tuple[Path, bool]]:
    candidates = {path: True for path in tracked if relative_is_allowed(path, tracked=True)}
    # Include current untracked source without traversing ignored dependency/data trees.
    for item in source.iterdir():
        if item.is_file() and not is_link(item):
            relative = Path(item.name)
            if relative_is_allowed(relative, tracked=False):
                candidates.setdefault(relative, False)
    for folder in sorted(SOURCE_FOLDERS):
        top = source / folder
        if not top.is_dir() or is_link(top):
            continue
        for current, directories, files in os.walk(top, followlinks=False):
            current_path = Path(current)
            directories[:] = sorted(name for name in directories
                                    if not excluded_directory(name, current_path.relative_to(source))
                                    and not is_link(current_path / name))
            for name in sorted(files):
                relative = (current_path / name).relative_to(source)
                if relative_is_allowed(relative, tracked=False):
                    candidates.setdefault(relative, False)
    return sorted(candidates.items(), key=lambda pair: pair[0].as_posix())


def write_exclusive(path: Path, content: bytes) -> None:
    checked_local_path(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def prepare_snapshot(source: Path, destination: Path) -> dict:
    source = checked_local_path(source)
    destination = checked_local_path(destination)
    if not source.is_dir() or not (source / "server.py").is_file():
        raise ValueError("Source must be the InspectorPro project containing server.py")
    if within(destination, source) or within(source, destination):
        raise ValueError("Source and destination must not overlap")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("Destination must be new or empty; existing data will not be overwritten")
    head, tracked = git_inventory(source)
    candidates = source_candidates(source, tracked)
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    skipped = {"missingTracked": 0, "linked": 0}
    for relative, is_tracked in candidates:
        path = source / relative
        if any(is_link(item) for item in (path, *path.parents) if within(item, source)):
            skipped["linked"] += 1
            continue
        if not path.is_file():
            skipped["missingTracked"] += int(is_tracked)
            continue  # Preserve current deletions; never recover bytes from Git HEAD.
        if not within(path.resolve(), source):
            raise ValueError("Source candidate escaped the project root")
        before = path.stat()
        content = path.read_bytes()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError(f"Source changed during snapshot: {relative.as_posix()}")
        if has_potential_secret(relative, content):
            raise ValueError(f"Potential embedded secret; snapshot stopped without copying it: {relative.as_posix()}")
        write_exclusive(destination / relative, content)
        records.append({"path": relative.as_posix(), "bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(), "tracked": is_tracked})
    copied_paths = {record["path"] for record in records}
    if "server.py" not in copied_paths or not any(path.startswith("static/") for path in copied_paths) or not any(path.startswith("ai_inspector/") for path in copied_paths):
        raise ValueError("Snapshot is missing required application source; no completion marker written")
    # Empty generated is required by real server mounting even with no tracked fixture.
    for folder in ("generated", "desktop"):
        (destination / folder).mkdir(exist_ok=True)
    manifest_bytes = json.dumps(records, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    write_exclusive(destination / "desktop-source-manifest.json", manifest_bytes)
    checkpoint = {
        "schemaVersion": 1, "source": str(source), "head": head, "files": len(records),
        "sourceManifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "sourceManifest": "desktop-source-manifest.json", "contentMode": "current-working-files",
        "createdAt": datetime.now(timezone.utc).isoformat(), "skipped": skipped,
        "excluded": "live libraries, runtime stores, secrets/.env, Git metadata, dependencies, symlinks/junctions; generated fixtures only when tracked",
    }
    # The compatible completion marker is deliberately the final write.
    write_exclusive(destination / "desktop-checkpoint.json", (json.dumps(checkpoint, indent=2) + "\n").encode("utf-8"))
    return checkpoint


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        checkpoint = prepare_snapshot(args.source, args.destination)
        print(json.dumps({"status": "ready", "destination": str(args.destination.resolve()),
                          "files": checkpoint["files"], "head": checkpoint["head"],
                          "sourceManifestSha256": checkpoint["sourceManifestSha256"]}))
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"Snapshot refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
