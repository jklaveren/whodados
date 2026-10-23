"""Rastreamento de abertura e clique.

Rotas publicas (o destinatario nao tem sessao); a protecao e' o HMAC na URL.
Nunca retornam erro ao destinatario: falha custa a metrica, nao o e-mail.
"""
import base64

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse, Response

from .db import marcar_email_aberto, marcar_email_clicado
from .logger import get_logger
from .mailer.rastreamento import assinatura_abertura, assinatura_clique, confere

router = APIRouter(prefix="/api/v1")
log = get_logger(__name__)

# GIF 1x1 transparente.
_PIXEL = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)
_CABECALHOS_PIXEL = {
    # Sem cache: cliente de e-mail que guardasse o pixel esconderia as
    # aberturas seguintes.
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}


@router.get("/t/a/{email_id}/{assinatura}.png")
async def pixel_abertura(email_id: int, assinatura: str):
    """Pixel de abertura. Marca aberto_em na primeira vez."""
    if confere(assinatura, assinatura_abertura(email_id)):
        try:
            marcar_email_aberto(email_id)
        except Exception as e:
            log.warning(f"pixel de abertura falhou para {email_id}: {e}")
    return Response(content=_PIXEL, media_type="image/gif", headers=_CABECALHOS_PIXEL)


@router.get("/t/c/{email_id}/{assinatura}")
async def redirecionar_clique(email_id: int, assinatura: str, u: str = Query("")):
    """Registra o clique e manda para o destino.

    So' redireciona se a assinatura cobrir ESTA url -- sem isso a rota
    viraria open redirect no nosso dominio.
    """
    if not u:
        return RedirectResponse(url="/", status_code=302)
    if not confere(assinatura, assinatura_clique(email_id, u)):
        log.warning(f"clique com assinatura invalida (email {email_id})")
        return RedirectResponse(url="/", status_code=302)
    try:
        marcar_email_clicado(email_id, u)
    except Exception as e:
        log.warning(f"registro de clique falhou para {email_id}: {e}")
    return RedirectResponse(url=u, status_code=302)
