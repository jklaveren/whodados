"""WhoDados API Endpoints - Painel inicial.

A tela que abre depois de escolher a empresa. Dominio proprio (e nao mais um
endpoint em endpoints_empresas) porque ela nao fala da base da Receita: ela
fala do que ESTA empresa esta fazendo -- alcance, funil, fila, atividades --
e serve igual pras duas fontes de prospeccao.
"""
from fastapi import APIRouter, Depends, Query
from typing import Any, Dict

from .auth import get_current_user, get_active_org
from .db import painel_inicio

router = APIRouter(prefix="/api/v1")


@router.get("/painel/inicio")
async def inicio(
    dias: int = Query(14, ge=1, le=90),
    current_user: Dict = Depends(get_current_user),
    org_id: int = Depends(get_active_org),
) -> Dict[str, Any]:
    """KPIs e serie de envios da empresa ativa, numa chamada so'.

    `dias` so' afeta a serie temporal e o engajamento; os totais (base,
    alcance, funil) sao acumulados desde sempre -- "quanto da minha lista eu
    ja' toquei" nao e' uma pergunta de janela.

    Sem papel especial: visitante tambem le, porque aqui nao sai CNPJ nem
    contato -- so' contagem agregada da propria empresa dele.

    `ver_conta_inteira` so' pra admin global. O teto diario do Gmail e' da
    conta, compartilhada entre as empresas; devolver esse numero pra um admin
    de empresa entregaria, por subtracao, quanto a outra empresa mandou hoje.
    """
    return painel_inicio(
        org_id, dias=dias,
        ver_conta_inteira=bool(current_user.get("is_admin")),
    )
