"""Descadastro de e-mail (LGPD/opt-out) -- link publico, sem login, que
qualquer campanha de qualquer empresa injeta automaticamente no rodape.

O token e' um HMAC do proprio e-mail com o SECRET_KEY do app: nao precisa
guardar token nenhum no banco, e da pra validar sem consultar nada -- so'
recalcula e compara. Nao e' "seguranca" contra abuso serio (o pior que da
pra fazer com o link de outra pessoa e' desinscrever o e-mail dela, o que
e' inocuo -- ela simplesmente para de receber), so' evita que alguem
descadastre um endereco arbitrario digitando a URL a mao.
"""
from __future__ import annotations
import hashlib
import hmac

try:
    from ..config import settings
except ImportError:
    import os
    class _S:
        SECRET_KEY = os.getenv("SECRET_KEY", "")
        API_PUBLIC_URL = os.getenv("API_PUBLIC_URL", "http://localhost:8000")
    settings = _S()


def _assinar(email: str) -> str:
    chave = (settings.SECRET_KEY or "").encode("utf-8")
    return hmac.new(chave, email.strip().lower().encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def gerar_link_descadastro(email: str) -> str:
    if not email:
        return ""
    base = getattr(settings, "API_PUBLIC_URL", "http://localhost:8000").rstrip("/")
    from urllib.parse import quote
    assinatura = _assinar(email)
    return f"{base}/api/v1/descadastro?email={quote(email.strip().lower())}&sig={assinatura}"


def validar_assinatura(email: str, sig: str) -> bool:
    if not email or not sig:
        return False
    return hmac.compare_digest(_assinar(email), sig)
