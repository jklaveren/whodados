"""Auth Service - WhoDados."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
try:
    from ..config import settings
except ImportError:
    import os
    class _S:
        SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
        ALGORITHM = "HS256"
        ACCESS_TOKEN_EXPIRE_MINUTES = 480
        BCRYPT_ROUNDS = 12
    settings = _S()
try:
    from ..logger import get_logger
except ImportError:
    import logging
    get_logger = lambda x: logging.getLogger(x)
log = get_logger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.BCRYPT_ROUNDS)

def hash_senha(senha: str) -> str:
    return pwd_context.hash(senha)

def verificar_senha(senha_plana: str, hash_armazenado: str) -> bool:
    try:
        return pwd_context.verify(senha_plana, hash_armazenado)
    except Exception:
        return False

def criar_access_token(dados: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = dados.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc), "iss": "whodados"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decodificar_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM], options={"verify_iss": False})
    except JWTError:
        return None

def autenticar_usuario(username: str, password: str) -> Optional[Dict[str, Any]]:
    from ..db.service import get_user_by_username
    user = get_user_by_username(username)
    if not user or not user.get("is_active", True):
        return None
    if not verificar_senha(password, user.get("password_hash", "")):
        return None
    return {"sub": user["username"], "is_admin": user.get("is_admin", False), "email": user.get("email")}

def criar_usuario(username: str, password: str, email: Optional[str] = None, is_admin: bool = False) -> Dict[str, Any]:
    from ..db.service import create_user_record, get_user_by_username
    if get_user_by_username(username):
        raise ValueError(f"Usuario {username} ja existe")
    password_hash = hash_senha(password)
    user = create_user_record(username, password_hash, email, is_admin)
    return {"username": user["username"], "email": user.get("email"), "is_admin": user.get("is_admin", False), "created_at": user.get("created_at"), "is_active": user.get("is_active", True)}
