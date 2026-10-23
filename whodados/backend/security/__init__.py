"""Security Module - WhoDados."""
from .rate_limiter import RateLimiterMiddleware
from .headers import SecurityHeadersMiddleware
from .visitante import VisitanteMiddleware
from .auditoria_requests import AuditoriaRequestsMiddleware
from .audit import (
    AuditAction,
    audit,
    log_login,
    log_access,
    log_rate_limit,
    log_auth_error,
    log_forbidden,
)

__all__ = [
    "RateLimiterMiddleware",
    "SecurityHeadersMiddleware",
    "VisitanteMiddleware",
    "AuditoriaRequestsMiddleware",
    "AuditAction",
    "audit",
    "log_login",
    "log_access",
    "log_rate_limit",
    "log_auth_error",
    "log_forbidden",
]
