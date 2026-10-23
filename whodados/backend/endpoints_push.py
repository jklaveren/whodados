"""WhoDados API Endpoints - Push (PWA) + broadcast de avisos.

Dois canais saem daqui juntos, de proposito: o sino interno (tabela
notificacoes, que o badge do menu ja le) e o push no celular (Web Push).
Quem recebe o push e quem ve no sino sao sempre os mesmos -- nao ha
como um aviso chegar no celular e sumir do app.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, List, Optional

from .auth import get_current_user, get_active_org, get_papel_ativo
from .config import settings
from .db import (
    create_notificacao, salvar_push_subscription, remover_push_subscription,
    listar_push_subscriptions, listar_todas_organizacoes_ids,
)
from .push import push_configurado, disparar_push

router = APIRouter(prefix="/api/v1")


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeBody(BaseModel):
    endpoint: str = Field(..., min_length=10, max_length=2000)
    keys: Optional[PushKeys] = None
    p256dh: Optional[str] = None
    auth: Optional[str] = None


class UnsubscribeBody(BaseModel):
    endpoint: str = Field(..., min_length=10, max_length=2000)


class BroadcastBody(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=120)
    mensagem: str = Field("", max_length=500)
    alvo: str = Field("minha_empresa", pattern="^(minha_empresa|todas)$")


def resolver_alvos_broadcast(alvo: str, is_global_admin: bool, papel_org: str,
                             org_ativa: int, todas_orgs: List[int]) -> List[int]:
    """Quem recebe o aviso. Pura (sem banco) pra dar pra testar isolada:
    - minha_empresa: admin DA empresa (ou global) -> so a empresa ativa.
    - todas: so global -> todas as empresas ativas."""
    if alvo == "todas":
        if not is_global_admin:
            raise HTTPException(status_code=403, detail="Broadcast global restrito ao administrador geral")
        if not todas_orgs:
            raise HTTPException(status_code=400, detail="Nenhuma empresa ativa para avisar")
        return list(todas_orgs)
    if not (is_global_admin or papel_org == "admin"):
        raise HTTPException(status_code=403, detail="Avisar a empresa restrito ao admin dela")
    return [org_ativa]


@router.get("/push/vapid-public-key")
async def vapid_public_key(current_user: Dict = Depends(get_current_user)):
    """Chave publica que o navegador usa pra assinar a inscricao push."""
    return {"publicKey": settings.VAPID_PUBLIC_KEY or None, "enabled": push_configurado()}


@router.post("/push/subscribe")
async def subscribe(body: SubscribeBody, current_user: Dict = Depends(get_current_user),
                    org_id: int = Depends(get_active_org)):
    """Liga os avisos neste navegador/celular. A inscricao fica vinculada
    a empresa ativa -- broadcast da outra empresa nao acorda este aparelho."""
    p256dh = (body.keys.p256dh if body.keys else None) or body.p256dh or ""
    auth = (body.keys.auth if body.keys else None) or body.auth or ""
    if not p256dh or not auth:
        raise HTTPException(status_code=400, detail="Inscricao push incompleta (faltam chaves)")
    if not push_configurado():
        raise HTTPException(status_code=503, detail="Push nao configurado no servidor (VAPID)")
    salvar_push_subscription(
        username=current_user.get("sub"), organizacao_id=org_id,
        endpoint=body.endpoint, p256dh=p256dh, auth=auth,
    )
    return {"ok": True}


@router.post("/push/unsubscribe")
async def unsubscribe(body: UnsubscribeBody, current_user: Dict = Depends(get_current_user)):
    remover_push_subscription(body.endpoint, username=current_user.get("sub"))
    return {"ok": True}


@router.post("/push/broadcast")
async def broadcast(body: BroadcastBody, current_user: Dict = Depends(get_current_user),
                    org_id: int = Depends(get_active_org),
                    papel: str = Depends(get_papel_ativo)):
    """Avisa todo mundo: grava no sino + empurra pro celular.
    - alvo=minha_empresa: admin da empresa ativa (ou geral).
    - alvo=todas: so o geral; grava um aviso por empresa e empurra pra todos."""
    is_global = bool(current_user.get("is_admin"))
    orgs = resolver_alvos_broadcast(
        body.alvo, is_global, papel, org_id,
        listar_todas_organizacoes_ids() if is_global and body.alvo == "todas" else [],
    )
    avisos = 0
    subs = []
    for oid in orgs:
        create_notificacao(tipo="sistema", titulo=body.titulo, mensagem=body.mensagem,
                           user_id=None, organizacao_id=oid)
        avisos += 1
        subs.extend(listar_push_subscriptions(organizacao_id=oid))
    push = disparar_push(subs, body.titulo, body.mensagem or "")
    return {"ok": True, "organizacoes": len(orgs), "avisos_sino": avisos,
            "push": push, "push_configurado": push_configurado()}
