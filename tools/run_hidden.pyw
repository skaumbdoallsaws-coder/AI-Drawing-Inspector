"""Run a command without a Windows console; invoke directly using pythonw.exe."""
import os
import subprocess
import sys


def main():
    if len(sys.argv) < 2:
        return 2
    result = subprocess.run(
        sys.argv[1:], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )
    # pythonw has no console streams, but the agent supplies redirected pipes.
    for handle, payload in ((1, result.stdout), (2, result.stderr)):
        try:
            os.write(handle, payload)
        except OSError:
            pass
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
