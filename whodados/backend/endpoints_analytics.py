"""Analytics Endpoints - WhoDados.

Agregacoes sobre a base da Receita/PGFN (dados_empresas / dados_socios),
calculadas no Postgres. Reconstroi as telas analiticas do app legado:
Home (KPIs), Foco por Cidade, Radar de Setores, Mapa de Passivos e
Analise de Socios.

Todos os endpoints aceitam os mesmos filtros via query string (repetiveis):
  ?cidade=Porto Alegre&cidade=Canoas&cnae=6201100&porte=ME
  &divida_min=10000&divida_max=1000000&capital_min=0&capital_max=5000000
  &incluir_inativas=false
"""
from fastapi import APIRouter, Depends, Query
from typing import Any, Dict, List, Optional

from .auth import get_current_user
from .db import (
    analytics_resumo, analytics_por_cidade, analytics_por_setor, analytics_por_porte,
    analytics_top_empresas, analytics_socios_ranking, analytics_socio_detalhe,
    analytics_opcoes_filtro,
)
from .logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/analytics")


def filtros_comuns(
    cidade: Optional[List[str]] = Query(None),
    cnae: Optional[List[str]] = Query(None),
    porte: Optional[List[str]] = Query(None),
    divida_min: Optional[float] = Query(None),
    divida_max: Optional[float] = Query(None),
    capital_min: Optional[float] = Query(None),
    capital_max: Optional[float] = Query(None),
    incluir_inativas: bool = Query(False),
) -> Dict[str, Any]:
    """Traduz a query string nos kwargs esperados por db.analytics.*"""
    return {
        "cidades": cidade or None,
        "cnaes": cnae or None,
        "portes": porte or None,
        "divida_min": divida_min,
        "divida_max": divida_max,
        "capital_min": capital_min,
        "capital_max": capital_max,
        "incluir_inativas": incluir_inativas,
    }


@router.get("/resumo")
async def resumo(
    filtros: Dict = Depends(filtros_comuns),
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Indicadores-chave da base filtrada (os KPIs da Home)."""
    return analytics_resumo(**filtros)


@router.get("/por-cidade")
async def por_cidade(
    limite: int = Query(20, ge=1, le=200),
    filtros: Dict = Depends(filtros_comuns),
    current_user: Dict = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Ranking por municipio: qtd de empresas, capital e divida."""
    return analytics_por_cidade(limite=limite, **filtros)


@router.get("/por-setor")
async def por_setor(
    limite: int = Query(20, ge=1, le=200),
    filtros: Dict = Depends(filtros_comuns),
    current_user: Dict = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Ranking por CNAE (com descricao): qtd, capital, divida, divida media."""
    return analytics_por_setor(limite=limite, **filtros)


@router.get("/por-porte")
async def por_porte(
    filtros: Dict = Depends(filtros_comuns),
    current_user: Dict = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Distribuicao por porte da empresa."""
    return analytics_por_porte(**filtros)


@router.get("/top-empresas")
async def top_empresas(
    ordenar_por: str = Query("divida", pattern="^(divida|capital)$"),
    limite: int = Query(10, ge=1, le=100),
    filtros: Dict = Depends(filtros_comuns),
    current_user: Dict = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Maiores empresas por divida ou capital social."""
    return analytics_top_empresas(ordenar_por=ordenar_por, limite=limite, **filtros)


@router.get("/socios/ranking")
async def socios_ranking(
    limite: int = Query(50, ge=1, le=200),
    filtros: Dict = Depends(filtros_comuns),
    current_user: Dict = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Ranking de socios pelo passivo acumulado das empresas vinculadas."""
    return analytics_socios_ranking(limite=limite, **filtros)


@router.get("/socios/detalhe")
async def socio_detalhe(
    nome: str = Query(..., min_length=2),
    current_user: Dict = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Empresas vinculadas a um socio especifico (drill-down)."""
    return analytics_socio_detalhe(nome)


@router.get("/opcoes-filtro")
async def opcoes_filtro(
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Valores para popular os multiselects (cidades, portes, cnaes)."""
    return analytics_opcoes_filtro()
