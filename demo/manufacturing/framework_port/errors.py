"""Stable error model for the demo Facade.

Both backends raise the same exception types with the same stable codes for
the same violations. Codes are part of the public contract; messages are not
(each backend localises its own messages). Error payloads never embed internal
implementation details such as class names, module names or storage schemas.
"""

from __future__ import annotations

# Stable public error codes.
CODE_AUTH_FAILED = "AUTH_FAILED"
CODE_AUTHZ_DENIED = "AUTHZ_DENIED"
CODE_NOT_FOUND = "NOT_FOUND"
CODE_VALIDATION_FAILED = "VALIDATION_FAILED"
CODE_VERSION_CONFLICT = "VERSION_CONFLICT"
CODE_RETRY_REFUSED = "RETRY_REFUSED"
CODE_DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
CODE_BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
CODE_NOT_SUPPORTED_IN_BACKEND = "NOT_SUPPORTED_IN_BACKEND"


class FacadeError(Exception):
    """Base class for all Facade errors."""

    code = "FACADE_ERROR"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.code)
        if code is not None:
            self.code = code


class AuthenticationFailed(FacadeError):
    code = CODE_AUTH_FAILED


class AuthorizationDenied(FacadeError):
    code = CODE_AUTHZ_DENIED


class NotFound(FacadeError):
    code = CODE_NOT_FOUND


class ValidationFailed(FacadeError):
    code = CODE_VALIDATION_FAILED


class VersionConflict(FacadeError):
    code = CODE_VERSION_CONFLICT


class RetryRefused(FacadeError):
    """A governed action whose outcome is unknown may not be blindly retried."""

    code = CODE_RETRY_REFUSED


class DuplicateRequest(FacadeError):
    code = CODE_DUPLICATE_REQUEST


class BackendUnavailable(FacadeError):
    code = CODE_BACKEND_UNAVAILABLE


class NotSupportedInBackend(FacadeError):
    """The selected backend does not implement an optional capability."""

    code = CODE_NOT_SUPPORTED_IN_BACKEND
