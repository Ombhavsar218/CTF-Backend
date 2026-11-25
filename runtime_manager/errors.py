"""Bounded manager errors. Never include secrets or raw Docker details."""

from __future__ import annotations


class ManagerError(Exception):
    code = "MANAGER_ERROR"
    status = 500

    def __init__(self, message: str = "Internal error", *, code: str | None = None, status: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status is not None:
            self.status = status


class AuthError(ManagerError):
    code = "AUTH_FAILED"
    status = 401


class ForbiddenError(ManagerError):
    code = "FORBIDDEN"
    status = 403


class ValidationError(ManagerError):
    code = "INVALID_REQUEST"
    status = 422


class NotFoundError(ManagerError):
    code = "NOT_FOUND"
    status = 404


class ConflictError(ManagerError):
    code = "CONFLICT"
    status = 409


class UnavailableError(ManagerError):
    code = "UNAVAILABLE"
    status = 503
