"""WhoDados API Endpoints - Monitor de e-mails (follow-up com semaforo / SLA)."""
from fastapi import APIRouter, Depends
from typing import Dict, Optional
from .auth import get_current_user, get_active_org
from .db import (
    get_emails_for_monitor, get_monitor_stats, get_emails_vermelhos_para_followup,
)

router = APIRouter(prefix="/api/v1")


@router.get("/emails-enviados/monitor")
async def monitor_emails(
    campaign_id: Optional[int] = None,
    semaforo: Optional[str] = None,
    dias_sla: int = 7,
    limit: int = 200,
    offset: int = 0,
    current_user: Dict = Depends(get_current_user),
    org_id: int = Depends(get_active_org),
):
    """
    Lista e-mails enviados para acompanhamento de follow-up com semaforo.

    - campaign_id: filtra por campanha (opcional)
    - semaforo: 'verde' | 'amarelo' | 'vermelho' | 'cinza' (opcional)
    - dias_sla: dias do SLA (padrao 7)
    """
    items = get_emails_for_monitor(
        campaign_id=campaign_id,
        dias_sla=dias_sla,
        limit=limit,
        offset=offset,
        organizacao_id=org_id,
    )
    if semaforo:
        items = [i for i in items if i.get("semaforo_status") == semaforo]
    # Serializa campos de data para ISO
    out = []
    for item in items:
        row = dict(item)
        for k in ("enviado_em", "aberto_em", "criado_em"):
            v = row.get(k)
            if v is not None and hasattr(v, "isoformat"):
                row[k] = v.isoformat()
        # garante tipos primitivos
        for k in ("id", "campaign_id", "sequencia_passo"):
            if k in row and row[k] is not None:
                row[k] = int(row[k])
        if "dias_desde_envio" in row and row["dias_desde_envio"] is not None:
            row["dias_desde_envio"] = float(row["dias_desde_envio"])
        out.append(row)
    return out


@router.get("/emails-enviados/monitor/stats")
async def monitor_stats(
    dias_sla: int = 7,
    current_user: Dict = Depends(get_current_user),
    org_id: int = Depends(get_active_org),
):
    """Resumo agregado (verde/amarelo/vermelho/cinza) para o dashboard."""
    stats = get_monitor_stats(dias_sla=dias_sla, organizacao_id=org_id)
    # normaliza tipos para JSON
    for k in ("total_enviados", "verde", "amarelo", "vermelho", "cinza"):
        if k in stats and stats[k] is not None:
            stats[k] = int(stats[k])
        else:
            stats[k] = 0
    total = stats["verde"] + stats["amarelo"] + stats["vermelho"] + stats["cinza"]
    stats["total"] = total
    return stats


@router.get("/emails-enviados/monitor/vermelhos")
async def monitor_vermelhos(
    limite: int = 50,
    current_user: Dict = Depends(get_current_user),
    org_id: int = Depends(get_active_org),
):
    """Lista e-mails no estado vermelho (>5 dias sem abertura) para disparo de follow-up."""
    rows = get_emails_vermelhos_para_followup(limite=limite, organizacao_id=org_id)
    out = []
    for item in rows:
        row = dict(item)
        for k in ("enviado_em", "aberto_em", "criado_em"):
            v = row.get(k)
            if v is not None and hasattr(v, "isoformat"):
                row[k] = v.isoformat()
        out.append(row)
    return out
