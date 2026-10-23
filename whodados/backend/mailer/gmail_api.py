"""Envio pela API do Gmail (HTTPS), alternativa ao SMTP.

O Render bloqueia saida SMTP nas portas 587 e 465; a API do Gmail fala 443.

Dois modos de autenticacao, nesta ordem:
1. OAuth com refresh token (GMAIL_OAUTH_*). Nao exige ser admin do
   Workspace -- a pessoa autoriza a propria conta uma vez.
2. Service account com delegacao no dominio (GMAIL_SERVICE_ACCOUNT_JSON).
   Exige superadmin, mas nao precisa de autorizacao por usuario.

Na frente dos dois vem a conta CONECTADA PELO SISTEMA (gmail_oauth): cada
empresa/pessoa autoriza a propria conta e o envio usa a de quem esta'
enviando. Os modos acima sao de uma conta so' para todo mundo, e o Gmail so'
respeita o From que pertence a' conta autenticada -- com eles o remetente de
cada empresa e' apenas o nome exibido.
"""
from __future__ import annotations

import base64
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from typing import Any, Dict, Optional

try:
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials as CredenciaisOAuth
    from google.auth.transport.requests import AuthorizedSession
except ImportError:
    service_account = None
    CredenciaisOAuth = None
    AuthorizedSession = None

try:
    from ..logger import get_logger
except ImportError:
    import logging
    get_logger = lambda x: logging.getLogger(x)

log = get_logger(__name__)

_ESCOPOS = ["https://www.googleapis.com/auth/gmail.send"]
_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
_ENV = "GMAIL_SERVICE_ACCOUNT_JSON"
_ENV_OAUTH = ("GMAIL_OAUTH_CLIENT_ID", "GMAIL_OAUTH_CLIENT_SECRET", "GMAIL_OAUTH_REFRESH_TOKEN")
# Cliente "Aplicativo da Web" das contas conectadas pelo sistema. Separado do
# de cima porque refresh token so' vale com o cliente que o emitiu.
_ENV_WEB = ("GMAIL_WEB_CLIENT_ID", "GMAIL_WEB_CLIENT_SECRET")


def _tem_oauth() -> bool:
    return all(os.environ.get(k) for k in _ENV_OAUTH) and CredenciaisOAuth is not None


def _tem_web() -> bool:
    return all(os.environ.get(k) for k in _ENV_WEB) and CredenciaisOAuth is not None


def _tem_conta_geral() -> bool:
    return _tem_oauth() or (bool(os.environ.get(_ENV)) and service_account is not None)


def configurado() -> bool:
    return _tem_web() or _tem_conta_geral()


def diagnostico() -> Dict[str, Any]:
    """Por que a API do Gmail esta (ou nao) ativa. Nao expoe valor nenhum."""
    return {
        "ativo": configurado(),
        "modo": "oauth" if _tem_oauth() else ("service_account" if _tem_conta_geral() else None),
        "conexao_pelo_sistema": _tem_web(),
        "biblioteca_google_auth": CredenciaisOAuth is not None,
        "envs_oauth_presentes": {k: bool(os.environ.get(k)) for k in _ENV_OAUTH},
        "env_service_account": bool(os.environ.get(_ENV)),
    }


def _credencial(remetente: str, refresh_token: Optional[str] = None):
    """Conta conectada de quem envia; senao a conta geral (OAuth, depois
    service account delegada)."""
    if refresh_token and _tem_web():
        cid, secret = (os.environ[k] for k in _ENV_WEB)
        return CredenciaisOAuth(
            token=None, refresh_token=refresh_token, client_id=cid, client_secret=secret,
            token_uri="https://oauth2.googleapis.com/token", scopes=_ESCOPOS,
        )
    if _tem_oauth():
        cid, secret, refresh = (os.environ[k] for k in _ENV_OAUTH)
        return CredenciaisOAuth(
            token=None, refresh_token=refresh, client_id=cid, client_secret=secret,
            token_uri="https://oauth2.googleapis.com/token", scopes=_ESCOPOS,
        )
    info = json.loads(os.environ.get(_ENV, ""))
    cred = service_account.Credentials.from_service_account_info(info, scopes=_ESCOPOS)
    # subject precisa ser um usuario do dominio autorizado na delegacao.
    return cred.with_subject(remetente)


def _por_um_clique(msg, remetente: str, unsubscribe_url: Optional[str]) -> None:
    """Cabecalhos de descadastro de um clique (RFC 8058).

    O link no rodape nao basta: Gmail, Yahoo e Outlook leem o HEADER pra
    desenhar o proprio botao "cancelar inscricao" ao lado do remetente. Sem
    ele, quem nao quer mais receber tem um caminho obvio a mao -- "marcar
    como spam" -- e reclamacao e' o sinal que mais rapido derruba reputacao
    de dominio. O header existe pra dar uma saida mais facil que a denuncia.

    mailto junto com https de proposito: o provedor escolhe, e o mailto
    funciona mesmo que o endpoint HTTP esteja fora do ar.

    List-Unsubscribe-Post declara que o POST nao precisa de confirmacao --
    sem ele o provedor nao mostra o botao nativo.
    """
    if not unsubscribe_url:
        return
    alvos = [f"<{unsubscribe_url}>"]
    if remetente and "@" in remetente:
        alvos.insert(0, f"<mailto:{remetente}?subject=unsubscribe>")
    msg["List-Unsubscribe"] = ", ".join(alvos)
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"


def enviar(
    para: str, assunto: str, corpo_html: str, corpo_texto: Optional[str],
    remetente: str, remetente_nome: Optional[str] = None,
    unsubscribe_url: Optional[str] = None,
    refresh_token: Optional[str] = None,
) -> Dict[str, Any]:
    if not configurado():
        return {"sucesso": False, "erro": f"{_ENV} nao configurada"}
    if not remetente:
        return {"sucesso": False, "erro": "remetente nao definido"}
    if not (refresh_token and _tem_web()) and not _tem_conta_geral():
        # So' ha' contas conectadas, e nenhuma e' de quem esta' enviando.
        return {"sucesso": False, "nao_configurado": True, "para": para,
                "erro": "Nenhuma conta do Gmail conectada para este remetente. "
                        "Conecte em Configuracoes > E-mail antes de enviar."}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = assunto
    msg["From"] = f"{remetente_nome} <{remetente}>" if remetente_nome else remetente
    msg["To"] = para
    msg_id = make_msgid(domain=remetente.split("@")[-1] or None)
    msg["Message-ID"] = msg_id
    _por_um_clique(msg, remetente, unsubscribe_url)
    if corpo_texto:
        msg.attach(MIMEText(corpo_texto, "plain", "utf-8"))
    msg.attach(MIMEText(corpo_html, "html", "utf-8"))

    try:
        sessao = AuthorizedSession(_credencial(remetente, refresh_token))
        r = sessao.post(
            _ENDPOINT,
            json={"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()},
            timeout=30,
        )
        if r.status_code >= 400:
            # O corpo do erro do Google diz o motivo real (delegacao faltando,
            # escopo errado, usuario inexistente).
            detalhe = (r.text or "")[:300]
            log.error(f"Gmail API {r.status_code} para {para}: {detalhe}")
            return {"sucesso": False, "para": para, "erro": f"Gmail API {r.status_code}: {detalhe}"}
        log.info(f"Email enviado via Gmail API para {para}: {assunto}")
        return {"sucesso": True, "para": para, "assunto": assunto, "message_id": msg_id}
    except Exception as e:
        log.error(f"Falha na Gmail API para {para}: {e}")
        if "invalid_grant" in str(e):
            # Acesso revogado na conta Google, ou senha trocada.
            return {"sucesso": False, "para": para,
                    "erro": "A autorizacao do Gmail expirou ou foi revogada. "
                            "Conecte a conta de novo em Configuracoes > E-mail."}
        return {"sucesso": False, "para": para, "erro": str(e)}
