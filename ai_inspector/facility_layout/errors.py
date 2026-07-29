"""Stable domain errors for the Facility Layout backend."""

from __future__ import annotations

from typing import Any, Mapping


class FacilityLayoutError(RuntimeError):
    """Base error carrying an API-safe code, status, and structured details."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(code, str) or not code or not code.isascii():
            raise ValueError("facility error code must be non-empty ASCII")
        if not isinstance(message, str) or not message:
            raise ValueError("facility error message must be non-empty")
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = int(status_code)
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            result["details"] = dict(self.details)
        return result


class FacilityValidationError(FacilityLayoutError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, status_code=422, details=details)


class FacilityConflictError(FacilityLayoutError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, status_code=409, details=details)


class FacilityAuthorizationError(FacilityLayoutError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, status_code=403, details=details)


class FacilityNotFoundError(FacilityLayoutError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, status_code=404, details=details)


class FacilityCompatibilityError(FacilityLayoutError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, status_code=409, details=details)


class FacilityIntegrityError(FacilityLayoutError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, status_code=422, details=details)
