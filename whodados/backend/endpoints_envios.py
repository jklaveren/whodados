"""Painel de envios: fila, volume e engajamento numa tela so."""
from fastapi import APIRouter, Depends, Query
from typing import Any, Dict

from .auth import get_current_user, get_active_org
from .config import settings
from .db import painel_envios, contar_emails_enviados_hoje

router = APIRouter(prefix="/api/v1")


@router.get("/envios/painel")
async def get_painel(dias: int = Query(30, ge=1, le=365),
                     current_user: Dict = Depends(get_current_user),
                     org_id: int = Depends(get_active_org)) -> Dict[str, Any]:
    painel = painel_envios(org_id, dias=dias)
    limite = int(getattr(settings, "EMAIL_LIMITE_DIARIO", 0) or 0)
    enviados_hoje = contar_emails_enviados_hoje() if limite else 0
    painel["hoje"] = {
        "enviados": enviados_hoje,
        "limite": limite,
        "restante": max(limite - enviados_hoje, 0) if limite else None,
        "por_rodada": int(getattr(settings, "ENVIO_POR_RODADA", 10) or 0),
        "janela": f"{getattr(settings, 'ENVIO_JANELA_INICIO', '07:00')} às "
                  f"{getattr(settings, 'ENVIO_JANELA_FIM', '19:30')}",
    }
    return painel
