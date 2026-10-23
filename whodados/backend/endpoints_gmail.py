"""Conectar a conta do Gmail pelo proprio sistema.

Duas conexoes possiveis, espelhando a config de e-mail: a da EMPRESA (padrao,
so' admin) e a da PESSOA naquela empresa (o e-mail e' individual). O envio usa
a da pessoa quando houver e a da empresa no resto -- ver _smtp_efetivo."""
from typing import Dict, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from .auth import get_current_user, get_active_org
from .config import settings
from .db import set_gmail_conexao, remover_gmail_conexao
from .db.service import usuario_tem_acesso_org, obter_gmail_refresh_token
from .logger import get_logger
from .mailer import gmail_oauth

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1")


def _alvo(alvo: str, organizacao_id: Optional[int], current_user: Dict, org_ativa: int) -> Dict:
    """Para onde vai a conexao. A da empresa muda o envio de todo mundo
    dela, entao e' de admin, como o resto da config de e-mail da empresa."""
    if alvo == "empresa":
        if not current_user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
        return {"o": organizacao_id or org_ativa, "u": None}
    if alvo == "eu":
        return {"o": org_ativa, "u": current_user["sub"]}
    raise HTTPException(status_code=400, detail="alvo deve ser 'eu' ou 'empresa'")


@router.get("/gmail/conectar")
async def gmail_conectar(alvo: str = "eu", organizacao_id: Optional[int] = None,
                         current_user: Dict = Depends(get_current_user),
                         org_id: int = Depends(get_active_org)) -> Dict[str, str]:
    """Devolve o endereco da tela de autorizacao do Google."""
    if not gmail_oauth.disponivel():
        raise HTTPException(
            status_code=503,
            detail="Conexao com o Gmail ainda nao habilitada no servidor "
                   "(faltam GMAIL_WEB_CLIENT_ID e GMAIL_WEB_CLIENT_SECRET).")
    destino = _alvo(alvo, organizacao_id, current_user, org_id)
    estado = gmail_oauth.assinar_estado({**destino, "por": current_user["sub"]})
    return {"url": gmail_oauth.url_de_autorizacao(estado)}


def _voltar(resultado: str, detalhe: str = "", aba: str = "meu-email") -> RedirectResponse:
    base = (getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
    url = f"{base}/dashboard/configuracoes?gmail={resultado}&aba={aba}"
    if detalhe:
        url += f"&detalhe={quote(detalhe)}"
    return RedirectResponse(url, status_code=302)


@router.get("/gmail/callback")
async def gmail_callback(code: str = "", state: str = "", error: str = ""):
    """Retorno do Google. Publico (o navegador chega aqui sem o token do
    WhoDados): quem autoriza e' o estado assinado, nao a sessao."""
    dados = gmail_oauth.ler_estado(state)
    if not dados:
        return _voltar("erro", "O pedido de conexao expirou. Tente de novo.")
    org, usuario = dados.get("o"), dados.get("u")
    aba = "meu-email" if usuario else "empresas"
    if error or not code:
        return _voltar("erro", "A autorizacao foi cancelada na tela do Google.", aba)
    if usuario and not usuario_tem_acesso_org(usuario, org):
        # O acesso pode ter sido tirado entre o clique e o retorno.
        return _voltar("erro", "Voce nao tem mais acesso a esta empresa.", aba)
    try:
        conexao = gmail_oauth.trocar_codigo(code)
        set_gmail_conexao(org, conexao["conta"], conexao["refresh_token"], username=usuario)
    except ValueError as e:
        return _voltar("erro", str(e), aba)
    except Exception as e:
        logger.error(f"Falha conectando Gmail (empresa {org}): {e}")
        return _voltar("erro", "Nao foi possivel concluir a conexao.", aba)
    quem = f"pessoa {usuario}" if usuario else "padrao da empresa"
    logger.info(f"Gmail conectado na empresa {org} ({quem}) por {dados.get('por')}")
    return _voltar("ok", conexao["conta"], aba)


@router.delete("/gmail/conexao")
async def gmail_desconectar(alvo: str = "eu", organizacao_id: Optional[int] = None,
                            current_user: Dict = Depends(get_current_user),
                            org_id: int = Depends(get_active_org)) -> Dict[str, bool]:
    destino = _alvo(alvo, organizacao_id, current_user, org_id)
    token = obter_gmail_refresh_token(destino["o"], username=destino["u"])
    remover_gmail_conexao(destino["o"], username=destino["u"])
    revogado = gmail_oauth.revogar(token)
    logger.info(f"Gmail desconectado na empresa {destino['o']} por {current_user['sub']} "
                f"(revogado no Google: {revogado})")
    return {"ok": True, "revogado": revogado}
