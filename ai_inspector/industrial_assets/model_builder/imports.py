"""Load only the adjacent leaf package, using the worker's stable private name.

This also makes numerical in-process tests independent of application __init__.
MB1b's worker bootstrap can pre-load the same package before calling the kernel.
"""
import importlib
import importlib.util
from pathlib import Path
import sys


def module(name):
    package_name = "_model_import_worker"
    if package_name not in sys.modules:
        folder = Path(__file__).resolve().parent.parent / "model_import"
        spec = importlib.util.spec_from_file_location(package_name, folder / "__init__.py",
                                                     submodule_search_locations=[str(folder)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[package_name] = package
        spec.loader.exec_module(package)
    return importlib.import_module(package_name + "." + name)
