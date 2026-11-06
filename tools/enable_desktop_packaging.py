"""Opt Packaging into an existing local application profile, with an exact backup."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.runtime.application_profile import load_application_profile
from desktop.runtime.packaging_config import validate_config


def enable(profile_file, dependencies, geometry_python):
    profile_file = Path(profile_file).resolve(strict=True)
    profile = load_application_profile(profile_file)
    original = profile_file.read_bytes()
    value = json.loads(original)
    config = dict(schemaVersion=1, dependencyRoot=str(Path(dependencies).resolve(strict=True)),
                  geometryPython=str(Path(geometry_python).resolve(strict=True)))
    config = validate_config(config, profile.value)
    if value.get('packagingRuntime') == config:
        print('Packaging is already enabled. Profile unchanged.')
        return
    if 'packagingRuntime' in value:
        raise ValueError('Existing Packaging runtime differs; review that profile before changing it.')
    value['packagingRuntime'] = config
    backup = profile_file.with_name(profile_file.name + '.before-packaging-' + uuid4().hex[:12])
    shutil.copy2(profile_file, backup)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.json',
                                         dir=profile_file.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        load_application_profile(temporary)
        if profile_file.read_bytes() != original:
            raise ValueError('Profile changed during promotion; no replacement was performed.')
        os.replace(temporary, profile_file)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print('Packaging enabled; all other profile settings retained.')
    print('Backup:', backup)
    print('Packaging store:', profile.data / 'packaging')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--dependencies', type=Path, required=True)
    parser.add_argument('--geometry-python', type=Path, required=True)
    args = parser.parse_args()
    enable(args.profile, args.dependencies, args.geometry_python)
