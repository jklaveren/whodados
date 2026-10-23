"""Endpoint de consulta em linguagem natural sobre a base de empresas.

Reaproveita carregar_empresas()/filtrar_empresas() -- o mesmo caminho que
o endpoint /empresas ja usa -- entao o LLM nunca acessa dado nenhum
diretamente: ele so decide OS PARAMETROS do filtro, validados por Pydantic.
"""
from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    import pandas as pd
except ImportError:
    pd = None

from .auth.dependencies import get_current_user
from .data import carregar_empresas, filtrar_empresas
from .nlp.service import interpretar_pergunta, resumir_resultado

router = APIRouter()

_COLS = ["CNPJ_COMPLETO", "RAZAO_SOCIAL", "NOME_FANTASIA", "MUNIC_NOME", "CNAE_PRINCIPAL", "CAPITAL_SOCIAL", "DIVIDA_TOTAL", "PORTE_NOME"]
_COL_ORDENAR = {"capital_social": "CAPITAL_SOCIAL", "divida_total": "DIVIDA_TOTAL"}


class PerguntaRequest(BaseModel):
    pergunta: str


@router.post("/empresas/consulta-natural")
async def consulta_natural(payload: PerguntaRequest, current_user: Dict = Depends(get_current_user)):
    if not payload.pergunta.strip():
        raise HTTPException(status_code=400, detail="Pergunta vazia")

    try:
        filtro = interpretar_pergunta(payload.pergunta)
    except Exception as exc:  # qualquer falha do LLM vira 502, nao 500
        raise HTTPException(status_code=502, detail=f"Nao consegui interpretar a pergunta: {exc}")

    df = carregar_empresas()
    if df.empty:
        return {
            "pergunta_original": payload.pergunta,
            "filtro_interpretado": filtro.model_dump(),
            "total_encontrado": 0,
            "empresas": [],
            "resumo_em_texto": "Nenhuma empresa carregada na base ainda.",
        }

    df_f = filtrar_empresas(df, filtro.cidade, filtro.cnae, filtro.busca)
    available = [c for c in _COLS if c in df_f.columns]
    df_f = df_f[available].copy()

    if filtro.ordenar_por != "nenhum" and pd is not None:
        col = _COL_ORDENAR.get(filtro.ordenar_por)
        if col and col in df_f.columns:
            df_f[col] = pd.to_numeric(df_f[col], errors="coerce")
            df_f = df_f.sort_values(col, ascending=(filtro.ordem == "asc"))

    total = len(df_f)
    df_f = df_f.iloc[: filtro.limite]
    df_f.columns = [c.lower() for c in df_f.columns]
    df_f = df_f.rename(columns={"munic_nome": "municipio"})
    empresas = df_f.fillna("").to_dict(orient="records")

    return {
        "pergunta_original": payload.pergunta,
        "filtro_interpretado": filtro.model_dump(),
        "total_encontrado": total,
        "empresas": empresas,
        "resumo_em_texto": resumir_resultado(payload.pergunta, filtro, total),
    }
