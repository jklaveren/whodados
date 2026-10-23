"""Cifragem simetrica leve para segredos guardados no banco (ex.: senha SMTP
por empresa). Chave derivada da SECRET_KEY -- ninguem com acesso so ao banco
consegue ler os segredos sem a SECRET_KEY do backend.

Tolerante: se o pacote `cryptography` nao estiver disponivel, degrada para
texto puro (com aviso) em vez de quebrar. Em producao o `cryptography` vem
junto do `python-jose[cryptography]`.

decrypt_secret e' tolerante a valores legados em texto puro (sem o prefixo
'enc:'), entao a migracao do SMTP global (.env -> Alfa) continua funcionando e
so vira cifrado no proximo save."""
from __future__ import annotations
import base64
import hashlib
from typing import Optional

try:
    from .config import settings
except ImportError:  # pragma: no cover
    import os as _os

    class _S:
        SECRET_KEY = _os.getenv("SECRET_KEY", "change-me-in-production-use-strong-secret")
    settings = _S()  # type: ignore

try:
    from .logger import get_logger
    log = get_logger(__name__)
except Exception:  # pragma: no cover
    import logging
    log = logging.getLogger(__name__)

_PREFIXO = "enc:"


def _fernet():
    """Instancia Fernet com chave derivada da SECRET_KEY, ou None se o pacote
    `cryptography` nao estiver instalado."""
    try:
        from cryptography.fernet import Fernet
    except Exception:
        return None
    chave = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest())
    return Fernet(chave)


def encrypt_secret(texto: Optional[str]) -> Optional[str]:
    """Cifra um segredo para guardar no banco. Retorna com prefixo 'enc:'.
    Se nao houver `cryptography`, guarda em texto puro (com aviso)."""
    if not texto:
        return texto
    f = _fernet()
    if f is None:
        log.warning("cryptography indisponivel -- guardando segredo em texto puro.")
        return texto
    return _PREFIXO + f.encrypt(texto.encode("utf-8")).decode("utf-8")


def decrypt_secret(valor: Optional[str]) -> Optional[str]:
    """Decifra um segredo. Valores sem o prefixo 'enc:' sao tratados como texto
    puro legado (retornados como estao)."""
    if not valor:
        return valor
    if not valor.startswith(_PREFIXO):
        return valor  # legado em texto puro
    f = _fernet()
    if f is None:
        log.error("Segredo cifrado mas `cryptography` indisponivel para decifrar.")
        return None
    try:
        return f.decrypt(valor[len(_PREFIXO):].encode("utf-8")).decode("utf-8")
    except Exception as e:
        log.error(f"Falha ao decifrar segredo: {e}")
        return None
