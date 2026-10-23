"""Audit Logger - WhoDados.

Log de auditoria para todas as acoes dos usuarios.
Os logs vao para o banco (tabela audit_log) + log padrao.
"""
from __future__ import annotations
import json
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from enum import Enum

try:
    from ..config import settings
    from ..logger import get_logger
except ImportError:
    import os
    settings = None
    get_logger = lambda x: __import__("logging").getLogger(x)

try:
    from ..db.service import create_audit_log
except ImportError:
    create_audit_log = None

log = get_logger(__name__)


class AuditAction(str, Enum):
    """Acoes auditadas."""
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    TOKEN_EXPIRED = "token_expired"
    CRM_VIEW = "crm_view"
    CRM_CREATE = "crm_create"
    CRM_UPDATE = "crm_update"
    EMPRESA_VIEW = "empresa_view"
    EMPRESA_SEARCH = "empresa_search"
    TEMPLATE_CREATE = "template_create"
    TEMPLATE_UPDATE = "template_update"
    TEMPLATE_DELETE = "template_delete"
    CAMPANHA_CREATE = "campanha_create"
    CAMPANHA_EXECUTE = "campanha_execute"
    CAMPANHA_DELETE = "campanha_delete"
    NOTIFICACAO_VIEW = "notificacao_view"
    NOTIFICACAO_READ = "notificacao_read"
    RATE_LIMIT_HIT = "rate_limit_hit"
    AUTH_DENIED = "auth_denied"
    FORBIDDEN_ACCESS = "forbidden_access"
    HEALTH_CHECK = "health_check"
    SYSTEM_ERROR = "system_error"


# Rotas que NAO devem ser auditadas
SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/", "/favicon.ico"}

# Acoes consideradas sensiveis
SENSITIVE_ACTIONS = {
    AuditAction.LOGIN_FAILED,
    AuditAction.RATE_LIMIT_HIT,
    AuditAction.AUTH_DENIED,
    AuditAction.FORBIDDEN_ACCESS,
    AuditAction.CAMPANHA_EXECUTE,
}


def _safe_log_audit(
    action: AuditAction,
    user: Optional[str],
    ip: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    request=None,
    success: bool = True,
):
    """Log de auditoria em thread separada (fire-and-forget)."""
    def _do():
        try:
            entry_user = user
            user_agent = _get_user_agent(request) if request else None

            log_extra = {
                "audit": True,
                "action": action.value,
                "user": entry_user or "anonymous",
                "ip": ip,
                "success": success,
            }

            if action in SENSITIVE_ACTIONS:
                log.warning(
                    f"[AUDIT] {action.value} | user={entry_user} | ip={ip} | "
                    f"resource={resource_type}/{resource_id}",
                    extra=log_extra,
                )
            else:
                log.info(
                    f"[AUDIT] {action.value} | user={entry_user} | ip={ip} | "
                    f"resource={resource_type}/{resource_id}",
                    extra=log_extra,
                )

            if create_audit_log and settings and settings.DATABASE_URL:
                create_audit_log(
                    action=action.value,
                    user_id=entry_user,
                    ip_address=ip,
                    resource_type=resource_type,
                    resource_id=str(resource_id) if resource_id else None,
                    details=details,
                    success=success,
                )
        except Exception as e:
            log.error(f"[AUDIT] Falha ao registrar audit log: {e}")

    threading.Thread(target=_do, daemon=True).start()


def audit(action: AuditAction, resource_type: Optional[str] = None):
    """Decorator para marcar endpoints auditaveis."""
    def decorator(func):
        func._audit_action = action
        func._audit_resource_type = resource_type
        return func
    return decorator


def log_login(request, username: str, success: bool, reason: Optional[str] = None):
    """Log de tentativa de login."""
    action = AuditAction.LOGIN_SUCCESS if success else AuditAction.LOGIN_FAILED
    _safe_log_audit(
        action=action,
        user=username if success else None,
        ip=_get_client_ip(request),
        request=request,
        success=success,
        details={"reason": reason} if reason else None,
    )


def log_access(
    request,
    action: AuditAction,
    user: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    success: bool = True,
):
    """Log generico de acesso."""
    if request and request.url.path in SKIP_PATHS:
        return
    _safe_log_audit(
        action=action,
        user=user,
        ip=_get_client_ip(request),
        request=request,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        success=success,
    )


def log_rate_limit(request):
    """Log quando rate limit e atingido."""
    _safe_log_audit(
        action=AuditAction.RATE_LIMIT_HIT,
        user=None,
        ip=_get_client_ip(request),
        request=request,
        success=False,
        details={"path": request.url.path},
    )


def log_auth_error(request, reason: str):
    """Log de erro de autenticacao."""
    _safe_log_audit(
        action=AuditAction.AUTH_DENIED,
        user=None,
        ip=_get_client_ip(request),
        request=request,
        success=False,
        details={"reason": reason},
    )


def log_forbidden(request, user: str, resource: str):
    """Log de acesso proibido."""
    _safe_log_audit(
        action=AuditAction.FORBIDDEN_ACCESS,
        user=user,
        ip=_get_client_ip(request),
        request=request,
        success=False,
        details={"resource": resource},
    )
def _get_client_ip(request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return getattr(request.client, "host", "unknown") if request.client else "unknown"


def _get_user_agent(request) -> str:
    return request.headers.get("user-agent", "unknown")