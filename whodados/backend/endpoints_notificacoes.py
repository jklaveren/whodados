"""WhoDados API Endpoints - Notificacoes do usuario (isoladas por empresa)."""
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Optional
from .auth import get_current_user, get_active_org
from .db import get_notificacoes, mark_notificacao_lida, contar_notificacoes_nao_lidas

router = APIRouter(prefix="/api/v1")


@router.get("/notificacoes")
async def listar_notificacoes(lidas: Optional[bool] = None, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    return get_notificacoes(user_id=current_user.get("sub"), lidas=lidas, organizacao_id=org_id)


@router.get("/notificacoes/nao-lidas")
async def contar_nao_lidas(current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    """Badge do menu. Rota literal registrada antes de qualquer /{param}
    do mesmo prefixo -- Starlette casa rota por ordem de registro."""
    return {"total": contar_notificacoes_nao_lidas(user_id=current_user.get("sub"), organizacao_id=org_id)}


@router.post("/notificacoes/{notificacao_id}/ler")
async def marcar_lida(notificacao_id: int, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    success = mark_notificacao_lida(notificacao_id, user_id=current_user.get("sub"), organizacao_id=org_id)
    if not success:
        raise HTTPException(status_code=404, detail="Notificacao nao encontrada")
    return {"ok": True}
