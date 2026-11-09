"""Best-effort cleanup must not hide the operation's real refusal or cancellation."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile
import time

from .job_io import local_directory
from .errors import ModelImportError


def retry_cleanup(action) -> bool:
    for delay in (0, .1, .15, .25, .4):
        if delay:
            time.sleep(delay)
        try:
            action()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            continue
    return False  # MI1's sweep can reclaim the owned remainder after handle release.


@contextmanager
def temporary_job(parent: Path):
    parent = local_directory(parent)
    job = Path(tempfile.mkdtemp(prefix=".model-prepare-", dir=parent))
    try:
        yield job
    finally:
        # Delete only the exact directory this invocation created, without following
        # a replacement symlink/junction or crossing its checked parent.
        try:
            checked = local_directory(job)
            if checked.parent == parent and checked.name.startswith(".model-prepare-"):
                retry_cleanup(lambda: shutil.rmtree(checked))
        except (OSError, ValueError, ModelImportError):
            pass
