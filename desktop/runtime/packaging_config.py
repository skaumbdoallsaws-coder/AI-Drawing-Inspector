"""Profile-only Packaging opt-in; neither credentials nor storage paths are configurable.

packagingRuntime = {schemaVersion: 1, dependencyRoot: <local package directory>,
                    geometryPython?: <separate local STEP Python executable>}
Omit the entire object to disable Packaging; omit geometryPython to disable STEP.
"""
import os
from pathlib import Path
import re
import sys

from desktop.runtime.profile import local_path

PACKAGES = ('py3dbp', 'trimesh', 'reportlab', 'numpy', 'PIL')  # numpy and PIL: the GLB worker imports them directly.
KEYS = {'schemaVersion', 'dependencyRoot'}
ENV_DEFAULTS = {
    'INSPECTORPRO_PACKAGING_ENABLED': '0',
    'INSPECTORPRO_CODEX_PACKAGING': '0',
    'INSPECTORPRO_PACKAGING_ROOT': '',
    'INSPECTORPRO_PACKAGING_GEOMETRY_PYTHON': '',
    'INSPECTORPRO_PACKAGING_GEOMETRY_TMP': '',
    'INSPECTORPRO_PACKAGING_EASYPOST_KEY': '',
}


def _path(value):
    # Match Node's local-path contract, including dangling links and raw traversal.
    if (not isinstance(value, str) or not value or re.search(r'[\x00-\x1f]', value)
            or re.match(r'^[\\/]{2}', value) or '..' in re.split(r'[\\/]', value)
            or ':' in os.path.splitdrive(value)[1]):
        raise ValueError()
    selected = Path(value)
    if not selected.is_absolute():
        raise ValueError()
    for item in (selected, *selected.parents):
        if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            raise ValueError()
    return local_path(selected)


def _overlaps(a, b):
    return a == b or a in b.parents or b in a.parents


def validate_config(value, profile):
    try:
        if (not isinstance(value, dict) or not KEYS <= set(value) or set(value) - KEYS - {'geometryPython'}
                or type(value['schemaVersion']) not in (int, float) or value['schemaVersion'] != 1):
            raise ValueError()
        dependencies = _path(value['dependencyRoot'])
        stores = [_path(profile[key]) for key in ('dataRoot', 'facilityRoot', 'libraryRoot')]
        if (not dependencies.is_dir() or any(not root.is_dir() for root in stores)
                or any(_overlaps(dependencies, root) for root in stores)
                or any(not _path(str(dependencies / name / '__init__.py')).is_file() for name in PACKAGES)):
            raise ValueError()
        root = _path(str(stores[0] / 'packaging'))
        for target in (root, _path(str(root / 'step-jobs'))):
            if target.exists() and not target.is_dir():
                raise ValueError()
        if any(_overlaps(root, store) for store in stores[1:]):
            raise ValueError()
        result = dict(value, dependencyRoot=str(dependencies))
        if 'geometryPython' in value:
            python = _path(value['geometryPython'])
            if not python.is_file() or any(_overlaps(python, store) for store in [*stores, dependencies]):
                raise ValueError()
            result['geometryPython'] = str(python)
        return result
    except Exception:
        raise ValueError('desktop_packaging_config_invalid') from None


def configure_packaging(profile, *, environment=None, search_path=None):
    """Run after configure_codex and before importing server; do not alter auth."""
    env = os.environ if environment is None else environment
    for name in list(env):
        if name.upper().startswith('INSPECTORPRO_PACKAGING_') or name.upper() == 'INSPECTORPRO_CODEX_PACKAGING':
            del env[name]
    # Explicit values block the server's non-overriding dotenv loader as well.
    env.update(ENV_DEFAULTS)
    from ai_inspector.packaging_shipping.sources import configure_glb_runtime
    configure_glb_runtime()
    if 'packagingRuntime' not in profile.value:
        return
    config = validate_config(profile.value['packagingRuntime'], profile.value)
    configure_glb_runtime(config['dependencyRoot'])
    paths = sys.path if search_path is None else search_path
    if config['dependencyRoot'] not in paths:
        # Do not execute arbitrary .pth files or displace existing app packages.
        paths.append(config['dependencyRoot'])
    root = Path(profile.value['dataRoot']) / 'packaging'
    env.update({
        'INSPECTORPRO_PACKAGING_ENABLED': '1',
        'INSPECTORPRO_CODEX_PACKAGING': '1' if 'codexRuntime' in profile.value else '0',
        'INSPECTORPRO_PACKAGING_ROOT': str(root),
        'INSPECTORPRO_PACKAGING_GEOMETRY_PYTHON': config.get('geometryPython', ''),
        'INSPECTORPRO_PACKAGING_GEOMETRY_TMP': str(root / 'step-jobs'),
    })
