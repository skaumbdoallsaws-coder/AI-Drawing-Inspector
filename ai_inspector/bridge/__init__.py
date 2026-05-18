"""
SOLIDWORKS extraction bridge client.

This is the InspectorPro app's side of the localhost bridge served by
the InspectorPro SOLIDWORKS add-in. The bridge lives at
http://127.0.0.1:{port}/ where {port} is published by the add-in to
%LOCALAPPDATA%\\InspectorPro\\Bridge\\bridge.json on add-in start.

See also:
  - InspectorPro.SolidWorks repo:  Bridge/BridgeServer.cs
  - Add-in audit log:               %LOCALAPPDATA%\\InspectorPro\\Bridge\\audit.log
"""

from .client import (
    BridgeClient,
    BridgeInfo,
    BridgeStatus,
    BridgeActiveDoc,
    BridgeUnavailableError,
    BridgeUnauthorizedError,
    BridgeJobConflictError,
    BridgeBadResponseError,
    JobCreateResult,
    JobSnapshot,
    JOB_STATE_AWAITING_APPROVAL,
    JOB_STATE_APPROVED,
    JOB_STATE_RUNNING,
    JOB_STATE_DONE,
    JOB_STATE_FAILED,
    JOB_STATE_DENIED,
    TERMINAL_STATES,
    KIND_DRAWING,
    KIND_PART,
    KIND_ASSEMBLY,
    SUPPORTED_KINDS,
    DEFAULT_KIND,
)

__all__ = [
    "BridgeClient",
    "BridgeInfo",
    "BridgeStatus",
    "BridgeActiveDoc",
    "BridgeUnavailableError",
    "BridgeUnauthorizedError",
    "BridgeJobConflictError",
    "BridgeBadResponseError",
    "JobCreateResult",
    "JobSnapshot",
    "JOB_STATE_AWAITING_APPROVAL",
    "JOB_STATE_APPROVED",
    "JOB_STATE_RUNNING",
    "JOB_STATE_DONE",
    "JOB_STATE_FAILED",
    "JOB_STATE_DENIED",
    "TERMINAL_STATES",
    "KIND_DRAWING",
    "KIND_PART",
    "KIND_ASSEMBLY",
    "SUPPORTED_KINDS",
    "DEFAULT_KIND",
]
