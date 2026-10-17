"""Owned native host for the normal application and its existing configuration."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import argparse
import asyncio
import os
import threading
from desktop.runtime.application_profile import load_application_profile
from desktop.runtime.control_pipe import NonBlockingControlPipe
from desktop.runtime.managed_backend import bootstrap, checkpoint, emit, PrivateControl, serve


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-file', type=Path, required=True)
    args = parser.parse_args()
    # Use one unbuffered owner for bootstrap and control, so an early shutdown
    # cannot disappear into a separate buffered reader's read-ahead.
    pipe = NonBlockingControlPipe(sys.stdin.fileno())
    private = bootstrap(pipe)
    checkpoint('application-profile', private['instanceId'])
    profile = load_application_profile(args.profile_file)
    # All other settings and provider credentials follow server.py's normal
    # environment/.env loading. These two stores are explicit identity bindings.
    os.environ.pop('PYTHON_DOTENV_DISABLED', None)
    os.environ['INSPECTORPRO_FACILITY_LAYOUT_ROOT'] = profile.value['facilityRoot']
    os.environ['INSPECTORPRO_LIBRARY_DIR'] = profile.value['libraryRoot']
    from desktop.runtime.codex_config import configure_codex
    configure_codex(profile, ROOT)
    os.chdir(ROOT)
    control = PrivateControl(pipe)
    threading.Thread(target=control.read, name='desktop-private-control', daemon=True).start()
    asyncio.run(serve(profile, private, control, application=True))


if __name__ == '__main__':
    try: main()
    except BaseException as error:
        emit('FAILED', {'schemaVersion': 1, 'code': 'desktop_application_failed', 'errorType': type(error).__name__})
        raise SystemExit(1)
