"""Provision/check the optional worktree-local Python 3.11 STEP geometry worker."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check the existing venv without installing")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = root / ".runtime" / "step-venv"
    python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    system = os.environ.get("SystemRoot", os.environ.get("SYSTEMROOT", "C:/Windows"))
    env = {"PATH": str(Path(sys.executable).parent), "HOME": str(target),
           "USERPROFILE": str(target), "TMP": str(root / ".runtime"),
           "TEMP": str(root / ".runtime"), "TMPDIR": str(root / ".runtime")}
    if os.name == "nt":
        env.update(SYSTEMROOT=system, WINDIR=system)
        env["PATH"] += os.pathsep + str(Path(system) / "System32")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def run(command):
        subprocess.run(command, check=True, env=env, cwd=root, creationflags=flags, timeout=300)

    if not args.check:
        if sys.version_info[:2] != (3, 11):
            parser.error("Run setup with Python 3.11; the application venv remains unchanged.")
        (root / ".runtime").mkdir(exist_ok=True)
        if not python.is_file():
            run([sys.executable, "-I", "-m", "venv", str(target)])
        run([str(python), "-I", "-m", "pip", "--isolated", "install", "--disable-pip-version-check",
             "--no-input", "--timeout", "30", "--retries", "1", "-r", str(root / "requirements-packaging-step.txt")])
    run([str(python), "-I", "-c", "import sys,importlib.metadata; import OCP; "
         "assert sys.version_info[:2] == (3,11); "
         "assert importlib.metadata.version('cadquery-ocp-novtk') == '7.9.3.1.1'"])
    print("Geometry runtime verified. Configure the server process:")
    print("INSPECTORPRO_PACKAGING_GEOMETRY_PYTHON=" + str(python))
    print("INSPECTORPRO_PACKAGING_GEOMETRY_TMP=" + str(root / ".runtime" / "step-jobs"))


if __name__ == "__main__":
    main()
