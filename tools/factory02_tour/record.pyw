"""Open the maximized Factory 02 tour and wait for the user's recording cue."""
from datetime import datetime
from uuid import uuid4

from launch import main


if __name__ == '__main__':
    name = 'record-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:6]
    main(['--name', name, '--full', '--wait-for-cue'])
