"""WhoDados API Endpoints - Gastos (despesas ja' realizadas, por empresa).

Isolado por empresa como o resto do controle: o gasto nasce amarrado a
organizacao ativa e nunca e' lido fora dela.

Excluir aqui e' exclusao logica (ver remover_gasto em db/service.py). Gasto
e' registro de dinheiro que saiu -- apagar de vez deixaria o total de um mes
mudar sem rastro de quem mudou.
"""
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from .auth import get_current_user, get_active_org
from .db import (
    criar_gasto, listar_gastos, resumo_gastos,
    remover_gasto, restaurar_gasto, atualizar_gasto,
)

router = APIRouter(prefix="/api/v1")

# Categorias fixas pra soma por categoria fazer sentido -- campo livre viraria
# "Marketing", "marketing" e "mkt" como tres linhas diferentes no resumo.
CATEGORIAS_GASTO = [
    "software", "marketing", "infraestrutura", "servicos",
    "equipamento", "impostos", "viagem", "outros",
]


def _valor_valido(bruto) -> float:
    try:
        valor = float(bruto)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Valor invalido")
    if valor <= 0:
        raise HTTPException(status_code=400, detail="Valor precisa ser maior que zero")
    return round(valor, 2)


@router.get("/gastos/categorias")
async def gastos_categorias(current_user: Dict = Depends(get_current_user)):
    return CATEGORIAS_GASTO


@router.get("/gastos")
async def gastos_listar(
    de: Optional[str] = None, ate: Optional[str] = None,
    categoria: Optional[str] = None, incluir_removidos: bool = False,
    current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org),
):
    return listar_gastos(org_id, de=de, ate=ate, categoria=categoria,
                         incluir_removidos=incluir_removidos)


@router.get("/gastos/resumo")
async def gastos_resumo(
    de: Optional[str] = None, ate: Optional[str] = None,
    current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org),
):
    return resumo_gastos(org_id, de=de, ate=ate)


@router.post("/gastos")
async def gastos_criar(
    data: Dict, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org),
):
    descricao = (data.get("descricao") or "").strip()
    if not descricao:
        raise HTTPException(status_code=400, detail="Descricao e' obrigatoria")
    categoria = data.get("categoria") or "outros"
    if categoria not in CATEGORIAS_GASTO:
        categoria = "outros"
    return criar_gasto(
        org_id, descricao, _valor_valido(data.get("valor")),
        data=(data.get("data") or "").strip() or None,
        categoria=categoria,
        forma_pagamento=(data.get("forma_pagamento") or "").strip() or None,
        observacao=(data.get("observacao") or "").strip() or None,
        criado_por=current_user.get("sub"),
    )


@router.put("/gastos/{gasto_id}")
async def gastos_atualizar(
    gasto_id: int, data: Dict,
    current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org),
):
    campos = {k: v for k, v in data.items()
              if k in ("descricao", "valor", "data", "categoria", "forma_pagamento", "observacao")}
    if "valor" in campos:
        campos["valor"] = _valor_valido(campos["valor"])
    if "categoria" in campos and campos["categoria"] not in CATEGORIAS_GASTO:
        campos["categoria"] = "outros"
    gasto = atualizar_gasto(gasto_id, org_id, campos)
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto nao encontrado ou nada para atualizar")
    return gasto


@router.delete("/gastos/{gasto_id}")
async def gastos_remover(
    gasto_id: int, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org),
):
    """Tira da lista e do total, mas mantem o registro (da' pra restaurar)."""
    if not remover_gasto(gasto_id, org_id, removido_por=current_user.get("sub")):
        raise HTTPException(status_code=404, detail="Gasto nao encontrado")
    return {"ok": True}


@router.post("/gastos/{gasto_id}/restaurar")
async def gastos_restaurar(
    gasto_id: int, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org),
):
    if not restaurar_gasto(gasto_id, org_id):
        raise HTTPException(status_code=404, detail="Gasto nao encontrado")
    return {"ok": True}
