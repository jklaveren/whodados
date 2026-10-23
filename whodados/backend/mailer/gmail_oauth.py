"""Conexao da conta do Gmail pelo proprio sistema (OAuth de aplicacao web).

A pessoa clica em "Conectar Gmail", autoriza na tela do Google e o sistema
guarda a autorizacao -- da empresa ou dela -- junto da config de e-mail. Antes
isso era um script rodado na mao e tres variaveis coladas no Render, uma conta
so' para todas as empresas: o Gmail so' respeita o From que pertence a' conta
autenticada, entao o remetente de cada empresa era apenas o nome exibido.

Exige um cliente OAuth do tipo "Aplicativo da Web" no Google Cloud
(GMAIL_WEB_CLIENT_ID / GMAIL_WEB_CLIENT_SECRET). O cliente "desktop" do script
antigo nao serve: so' aceita retorno para a propria maquina.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    from ..config import settings
except ImportError:  # pragma: no cover
    class _S:
        SECRET_KEY = os.getenv("SECRET_KEY", "")
        API_PUBLIC_URL = os.getenv("API_PUBLIC_URL", "http://localhost:8000")
    settings = _S()

# openid + email so' para saber QUAL conta foi conectada e mostrar na tela.
ESCOPOS = ["https://www.googleapis.com/auth/gmail.send", "openid", "email"]
ENV_CLIENTE = ("GMAIL_WEB_CLIENT_ID", "GMAIL_WEB_CLIENT_SECRET")
_AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN = "https://oauth2.googleapis.com/token"
# Tempo para a pessoa passar pela tela do Google. Curto de proposito: o estado
# e' a unica coisa que liga o retorno (publico, sem login) a quem pediu.
_VALIDADE_ESTADO = 600


def disponivel() -> bool:
    return all(os.environ.get(k) for k in ENV_CLIENTE) and requests is not None


def url_de_retorno() -> str:
    base = (getattr(settings, "API_PUBLIC_URL", "") or "").rstrip("/")
    return f"{base}/api/v1/gmail/callback"


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode().rstrip("=")


def _b64_ler(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _hmac(corpo: str) -> str:
    chave = (settings.SECRET_KEY or "").encode("utf-8")
    return hmac.new(chave, corpo.encode("utf-8"), hashlib.sha256).hexdigest()


def assinar_estado(dados: Dict[str, Any]) -> str:
    """O retorno do Google chega sem login. O estado assinado e' o que diz
    para qual empresa/pessoa gravar -- sem assinatura, qualquer um apontaria
    a propria conta do Gmail para a empresa dos outros."""
    corpo = _b64(json.dumps({**dados, "exp": int(time.time()) + _VALIDADE_ESTADO},
                            separators=(",", ":")).encode("utf-8"))
    return f"{corpo}.{_hmac(corpo)}"


def ler_estado(estado: str) -> Optional[Dict[str, Any]]:
    try:
        corpo, assinatura = (estado or "").split(".", 1)
        if not hmac.compare_digest(_hmac(corpo), assinatura):
            return None
        dados = json.loads(_b64_ler(corpo))
    except Exception:
        return None
    if int(dados.get("exp") or 0) < time.time():
        return None
    return dados


def url_de_autorizacao(estado: str) -> str:
    return _AUTORIZAR + "?" + urlencode({
        "client_id": os.environ.get(ENV_CLIENTE[0], ""),
        "redirect_uri": url_de_retorno(),
        "response_type": "code",
        "scope": " ".join(ESCOPOS),
        # offline + consent: sem os dois o Google so' devolve refresh token na
        # primeira autorizacao daquela conta, e reconectar viria sem token.
        "access_type": "offline",
        "prompt": "consent",
        "state": estado,
    })


_REVOGAR = "https://oauth2.googleapis.com/revoke"


def revogar(refresh_token: Optional[str]) -> bool:
    """Cancela a autorizacao no Google. Sem isto, 'desconectar' so' apagava a copia
    daqui e o token seguia valido la' -- quem o tivesse copiado continuava podendo
    enviar e-mail como a pessoa. Melhor esforco: falha de rede nao impede desconectar."""
    if not refresh_token or requests is None:
        return False
    try:
        r = requests.post(_REVOGAR, timeout=15, data={"token": refresh_token},
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        return r.status_code == 200
    except Exception:
        return False


def trocar_codigo(code: str) -> Dict[str, str]:
    """Troca o codigo do retorno pela autorizacao permanente. Devolve a conta
    conectada e o refresh token; levanta ValueError com o motivo legivel."""
    r = requests.post(_TOKEN, timeout=30, data={
        "code": code,
        "client_id": os.environ.get(ENV_CLIENTE[0], ""),
        "client_secret": os.environ.get(ENV_CLIENTE[1], ""),
        "redirect_uri": url_de_retorno(),
        "grant_type": "authorization_code",
    })
    if r.status_code >= 400:
        raise ValueError(f"o Google recusou a autorizacao ({(r.text or '')[:200]})")
    corpo = r.json()
    refresh = corpo.get("refresh_token")
    if not refresh:
        raise ValueError("o Google nao devolveu a autorizacao permanente")
    if "gmail.send" not in (corpo.get("scope") or ""):
        # A tela do Google deixa desmarcar permissao por permissao.
        raise ValueError("a permissao de enviar e-mail nao foi concedida")
    conta = ""
    try:
        # Veio direto do Google por TLS nesta mesma chamada: o conteudo do
        # id_token e' confiavel sem conferir a assinatura.
        conta = json.loads(_b64_ler(corpo["id_token"].split(".")[1])).get("email", "")
    except Exception:
        pass
    return {"conta": conta.strip().lower(), "refresh_token": refresh}
