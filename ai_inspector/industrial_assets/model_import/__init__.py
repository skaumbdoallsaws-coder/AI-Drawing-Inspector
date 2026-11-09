"""Offline model intake, independent of application runtime state.

Import reader.read_model only inside a resource-limited worker. Hosts use
runner.run_inspect, which does not import numpy or Pillow.
"""
from .errors import ModelImportError

__all__ = ["ModelImportError"]
