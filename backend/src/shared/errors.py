"""
Centralized error definitions and handlers for Privas AI backend.
Ensures all API errors follow a consistent JSON format.

Example response:
{
  "error": "DOMAIN_ALREADY_EXISTS",
  "message": "Domain name is already used within this tenant.",
  "status": 409,
  "details": {"name": "chat.acme.ai", "constraint": "tenantId_name_unique"},
  "requestId": "req_01HXYZ...",
  "timestamp": "2025-10-23T03:21:45Z"
}
"""

import datetime
import uuid
from fastapi import Request
from fastapi.responses import JSONResponse


# ============================================================
# Application Exception Classes
# ============================================================

class AppError(Exception):
    """Base class for all application-level errors."""
    def __init__(self, error: str, message: str, status: int = 500, details: dict | None = None):
        self.error = error
        self.message = message
        self.status = status
        self.details = details or {}


class ValidationError(AppError):
    def __init__(self, message="Invalid input.", details: dict | None = None):
        super().__init__("VALIDATION_ERROR", message, 422, details)


class ConflictError(AppError):
    def __init__(self, message="Conflict with existing resource.", details: dict | None = None):
        super().__init__("DOMAIN_ALREADY_EXISTS", message, 409, details)


class ForbiddenError(AppError):
    def __init__(self, message="Forbidden access.", details: dict | None = None):
        super().__init__("FORBIDDEN", message, 403, details)


class UnauthenticatedError(AppError):
    def __init__(self, message="Authentication required."):
        super().__init__("UNAUTHENTICATED", message, 401)


class NotFoundError(AppError):
    def __init__(self, message="Resource not found.", details: dict | None = None):
        super().__init__("DOMAIN_NOT_FOUND", message, 404, details)


class RateLimitedError(AppError):
    def __init__(self, message="Rate limit exceeded."):
        super().__init__("RATE_LIMITED", message, 429)


class GraphProvisionFailed(AppError):
    def __init__(self, message="Graph provisioning failed.", details: dict | None = None):
        super().__init__("GRAPH_PROVISION_FAILED", message, 500, details)


class GraphNotReady(AppError):
    def __init__(self, message="Graph not ready yet.", details: dict | None = None):
        super().__init__("GRAPH_NOT_READY", message, 503, details)


class GraphTimeout(AppError):
    def __init__(self, message="Graph provisioning timeout.", details: dict | None = None):
        super().__init__("GRAPH_PROVISION_TIMEOUT", message, 504, details)


class Neo4jUnavailable(AppError):
    def __init__(self, message="Neo4j admin unavailable.", details: dict | None = None):
        super().__init__("NEO4J_ADMIN_UNAVAILABLE", message, 502, details)


class TenantQuotaExceeded(AppError):
    def __init__(self, message="Tenant quota exceeded."):
        super().__init__("TENANT_QUOTA_EXCEEDED", message, 403)


class InternalServerError(AppError):
    def __init__(self, message="Internal server error.", details: dict | None = None):
        super().__init__("INTERNAL_ERROR", message, 500, details)


# ============================================================
# Error response formatter
# ============================================================

def format_error_response(error: AppError, request_id: str | None = None) -> dict:
    """
    Standard error payload generator.
    """
    return {
        "error": error.error,
        "message": error.message,
        "status": error.status,
        "details": error.details or None,
        "requestId": request_id or f"req_{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }


# ============================================================
# FastAPI Exception Handler
# ============================================================

async def app_error_handler(request: Request, exc: AppError):
    """
    Global handler for custom AppError exceptions.
    """
    payload = format_error_response(exc, getattr(request.state, "request_id", None))
    return JSONResponse(status_code=exc.status, content=payload)


async def generic_error_handler(request: Request, exc: Exception):
    """
    Fallback handler for uncaught exceptions.
    """
    err = InternalServerError(str(exc))
    payload = format_error_response(err, getattr(request.state, "request_id", None))
    return JSONResponse(status_code=500, content=payload)
