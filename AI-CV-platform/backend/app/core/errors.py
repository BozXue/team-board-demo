"""Domain errors mapped to HTTP responses in ``app.main``."""

from __future__ import annotations


class PlatformError(Exception):
    status_code = 400

    def __init__(self, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class NotFoundError(PlatformError):
    status_code = 404


class ValidationError(PlatformError):
    status_code = 422


class ConflictError(PlatformError):
    status_code = 409


class NotImplementedFeature(PlatformError):
    """Reserved interface: declared, wired into the API, implemented later."""

    status_code = 501
