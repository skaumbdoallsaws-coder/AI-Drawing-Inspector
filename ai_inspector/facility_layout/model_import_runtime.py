"""Trusted host dependency discovery for imports, including Windows user installs.

Native startup's packaging binding wins. Discovery reads only installed package
specs from this host, never an upload, PYTHONPATH value or request parameter.
Packaging's own default resolution deliberately remains unchanged.
"""
from importlib.util import find_spec
from pathlib import Path


def model_import_runtime():
    from ..packaging_shipping import sources

    if sources._RUNTIME is not None:
        return sources.glb_runtime()
    try:
        roots = []
        for name in ("numpy", "PIL"):
            spec = find_spec(name)
            if spec is None or not spec.origin:
                break
            origin = Path(spec.origin)
            if not origin.is_absolute() or origin.name != "__init__.py" or origin.parent.name != name:
                break
            # Validate package directories too: the site itself may be ordinary
            # while a package below it is a symlink or junction.
            sources.GlbRuntime(origin.parent)
            if (origin.is_symlink() or getattr(origin, "is_junction", lambda: False)()
                    or not origin.is_file()):
                break
            roots.append(origin.parent.parent)
        if len(roots) == 2 and roots[0] == roots[1]:
            return sources.GlbRuntime(roots[0])
    except (ImportError, AttributeError, OSError, ValueError):
        pass
    return sources.glb_runtime()
