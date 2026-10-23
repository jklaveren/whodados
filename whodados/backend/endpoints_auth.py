"""WhoDados API Endpoints - Autenticacao (login, reset e troca de senha)."""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.security import OAuth2PasswordRequestForm
from typing import Dict
from datetime import timedelta
from .auth import (
    autenticar_usuario, criar_access_token, get_current_user,
    gerar_token_reset, validar_token_reset, redefinir_senha,
    hash_senha, verificar_senha,
)
try:
    from .security import log_login
    HAS_AUDIT = True
except ImportError:
    HAS_AUDIT = False
from .db.service import get_user_by_username, update_user_password
from .logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1")


@router.post("/auth/login")
async def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), remember_me: bool = Form(False)):
    if HAS_AUDIT:
        log_login(request, form.username, False, "attempt")
    user = autenticar_usuario(form.username, form.password)
    if not user:
        if HAS_AUDIT:
            log_login(request, form.username, False, "invalid_credentials")
        raise HTTPException(status_code=401, detail="Credenciais invalidas", headers={"WWW-Authenticate": "Bearer"})
    expires_delta = timedelta(days=30) if remember_me else None
    token = criar_access_token(user, expires_delta=expires_delta)
    expires_in = int(expires_delta.total_seconds()) if expires_delta else 8 * 3600
    if HAS_AUDIT:
        log_login(request, form.username, True)
    return {"access_token": token, "token_type": "bearer", "expires_in": expires_in}


@router.post("/auth/forgot-password")
async def forgot_password(request: Request, data: Dict):
    """Solicita recuperacao de senha. Envia e-mail com link de reset."""
    username_or_email = (data.get("username") or data.get("email") or "").strip()
    if not username_or_email:
        raise HTTPException(status_code=400, detail="Username ou email obrigatorio")
    result = gerar_token_reset(username_or_email)
    # Sempre retorna sucesso para nao enumerar usuarios
    response = {"message": result.get("message", "")}
    if result.get("_dev_token"):
        response["_dev_token"] = result["_dev_token"]
    return response


@router.get("/auth/validate-reset-token/{token}")
async def validate_reset_token(token: str):
    """Valida se o token de reset e valido."""
    if not token:
        raise HTTPException(status_code=400, detail="Token obrigatorio")
    valido = validar_token_reset(token)
    if not valido:
        raise HTTPException(status_code=400, detail="Token invalido ou expirado")
    return {"valido": True}


@router.post("/auth/reset-password")
async def reset_password(data: Dict):
    """Redefine a senha usando o token recebido por e-mail."""
    token = (data.get("token") or "").strip()
    nova_senha = (data.get("nova_senha") or "").strip()
    if not token or not nova_senha:
        raise HTTPException(status_code=400, detail="Token e nova senha obrigatorios")
    result = redefinir_senha(token, nova_senha)
    if not result.get("sucesso"):
        raise HTTPException(status_code=400, detail=result.get("message", "Erro"))
    return {"message": result.get("message", "Senha redefinida")}


@router.get("/auth/me")
async def me(current_user: Dict = Depends(get_current_user)):
    return {"username": current_user["sub"], "is_admin": current_user.get("is_admin", False), "email": current_user.get("email")}


@router.put("/auth/me/senha")
async def trocar_minha_senha(data: Dict, current_user: Dict = Depends(get_current_user)):
    """Usuario logado troca a propria senha, informando a senha atual."""
    senha_atual = data.get("senha_atual") or ""
    nova_senha = data.get("nova_senha") or ""
    if not senha_atual or not nova_senha:
        raise HTTPException(status_code=400, detail="Senha atual e nova senha sao obrigatorias")
    if len(nova_senha) < 8:
        raise HTTPException(status_code=400, detail="A nova senha precisa ter ao menos 8 caracteres")

    user = get_user_by_username(current_user["sub"])
    if not user or not verificar_senha(senha_atual, user.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Senha atual incorreta")

    update_user_password(user["id"], hash_senha(nova_senha))
    logger.info(f"Usuario '{current_user['sub']}' trocou a propria senha")
    return {"sucesso": True, "message": "Senha atualizada com sucesso."}
