"""Password Reset Service - WhoDados."""
from __future__ import annotations
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

try:
    from ..config import settings
except ImportError:
    import os
    class _S:
        FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
        PASSWORD_RESET_EXPIRE_MINUTES = 60
    settings = _S()

try:
    from ..logger import get_logger
    from ..db.service import (
        get_user_by_username_or_email,
        create_password_reset_token,
        get_password_reset_token,
        mark_password_reset_token_used,
        update_user_password,
    )
    from ..mailer import enviar_email
    from ..mailer.service import _smtp_da_org
    from ..db.service import get_orgs_do_user_id, get_org_smtp_config
except ImportError:
    import logging
    get_logger = lambda x: logging.getLogger(x)
    def _noop(*a, **k): return None
    get_user_by_username_or_email = create_password_reset_token = get_password_reset_token = _noop
    mark_password_reset_token_used = update_user_password = _noop
    enviar_email = _noop
    _smtp_da_org = get_orgs_do_user_id = get_org_smtp_config = _noop

log = get_logger(__name__)

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def gerar_token_reset(username_or_email: str) -> Dict[str, Any]:
    if not settings.DATABASE_URL:
        return {"sucesso": False, "message": "Servico indisponivel"}
    user = get_user_by_username_or_email(username_or_email)
    if not user or not user.get("is_active", True):
        return {"sucesso": True, "message": "Se existir, email sera enviado"}
    if not user.get("email"):
        return {"sucesso": False, "message": "Sem email cadastrado. Contate o admin."}
    token_raw = secrets.token_urlsafe(32)
    token_hash = _hash_token(token_raw)
    expire_minutes = getattr(settings, "PASSWORD_RESET_EXPIRE_MINUTES", 60)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    create_password_reset_token(user["id"], token_hash, expires_at)
    frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
    reset_url = f"{frontend_url.rstrip('/')}/reset-password?token={token_raw}"
    html_body = (
        f"<html><body style='font-family:Arial;max-width:600px;margin:0 auto;padding:20px'>"
        f"<h2 style='color:#4f46e5'>WhoDados - Recuperacao de Senha</h2>"
        f"<p>Ola, <strong>{user['username']}</strong></p>"
        f"<p>Clique no link para redefinir sua senha:</p>"
        f"<p style='margin:30px 0'><a href='{reset_url}' style='background:#4f46e5;color:white;padding:12px 24px;text-decoration:none;border-radius:6px'>Redefinir Senha</a></p>"
        f"<p style='word-break:break-all;color:#666;font-size:12px'>{reset_url}</p>"
        f"<p><strong>Este link expira em {expire_minutes} minutos.</strong></p>"
        f"<p style='color:#999;font-size:12px'>Se nao foi voce, ignore este email.</p>"
        f"</body></html>"
    )
    text_body = f"WhoDados - Recuperacao de Senha\n\nOla {user['username']},\n\nAcesse: {reset_url}\n\nExpira em {expire_minutes} minutos.\n\nSe nao foi voce, ignore."
    # Sem isto, enviar_email cai no SMTP global (settings.SMTP_HOST) que nunca
    # foi preenchido -- cada empresa configura o proprio SMTP em
    # org_smtp_config, entao um usuario sem org associada a nenhum SMTP
    # configurado nunca recebia o e-mail (sucesso "simulado" e silencioso).
    # Usa a primeira organizacao do usuario que tiver SMTP configurado.
    smtp_cfg = None
    try:
        for org_id in get_orgs_do_user_id(user["id"]):
            cfg = get_org_smtp_config(org_id)
            if cfg and cfg.get("configurado"):
                smtp_cfg = _smtp_da_org(org_id)
                break
    except Exception as e:
        log.warning(f"Falha resolvendo SMTP da organizacao para reset de senha: {e}")
    if not smtp_cfg:
        log.warning(f"Nenhuma organizacao do usuario '{user['username']}' tem SMTP configurado -- e-mail de reset nao sera enviado de verdade.")
    result = enviar_email(para=user["email"], assunto="WhoDados - Recuperacao de Senha", corpo_html=html_body, corpo_texto=text_body, smtp=smtp_cfg)
    if result.get("sucesso"):
        return {"sucesso": True, "message": "Email enviado", "_dev_token": token_raw if not getattr(settings, "is_production", False) else None}
    return {"sucesso": False, "message": "Erro ao enviar email"}

def validar_token_reset(token_raw: str) -> bool:
    if not token_raw: return False
    return get_password_reset_token(_hash_token(token_raw)) is not None

def redefinir_senha(token_raw: str, nova_senha: str) -> Dict[str, Any]:
    from .service import hash_senha
    if not nova_senha or len(nova_senha) < 8:
        return {"sucesso": False, "message": "Minimo 8 caracteres"}
    record = get_password_reset_token(_hash_token(token_raw))
    if not record:
        return {"sucesso": False, "message": "Token invalido ou expirado"}
    mark_password_reset_token_used(record["id"])
    ok = update_user_password(record["user_id"], hash_senha(nova_senha))
    if ok:
        return {"sucesso": True, "message": "Senha redefinida"}
    return {"sucesso": False, "message": "Erro ao redefinir"}
