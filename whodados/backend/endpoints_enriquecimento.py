"""Endpoints do agente de enriquecimento de contatos.

Restrito a administradores (require_admin) porque dispara chamada de LLM
com custo por uso e busca dados de terceiros -- nao e' uma acao trivial de
usuario comum, e deve ficar sob controle de quem responde pela conformidade
com a LGPD do produto.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth.dependencies import require_admin, get_active_org
from .data import carregar_empresa_detalhe, carregar_socios
from .agents.enriquecimento_service import enriquecer_empresa
from .db import salvar_enriquecimento, listar_enriquecimento, remover_enriquecimento

router = APIRouter()

_MODELO_LABEL = "claude-sonnet-4-5+web_search"


def _socios_da_empresa(cnpj: str) -> List[str]:
    """Casa socios pelo CNPJ_BASICO (8 primeiros digitos do CNPJ completo) --
    e' assim que o pipeline gera socios_rs.csv (ver pipeline.py::filtrar_socios)."""
    try:
        df = carregar_socios()
        if df is None or df.empty or "CNPJ_BASICO" not in df.columns:
            return []
        base = "".join(ch for ch in cnpj if ch.isdigit())[:8]
        linhas = df[df["CNPJ_BASICO"].astype(str).str.zfill(8) == base]
        col_nome = "NOME_SOCIO" if "NOME_SOCIO" in linhas.columns else None
        if not col_nome:
            return []
        return [str(n) for n in linhas[col_nome].dropna().tolist()]
    except Exception:
        return []


@router.post("/empresas/{cnpj}/enriquecer")
async def enriquecer(cnpj: str, current_user: Dict = Depends(require_admin), org_id: int = Depends(get_active_org)):
    empresa = carregar_empresa_detalhe(cnpj)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa nao encontrada")

    razao_social = empresa.get("RAZAO_SOCIAL") or empresa.get("razao_social") or cnpj
    municipio = empresa.get("MUNIC_NOME") or empresa.get("municipio")
    socios = _socios_da_empresa(cnpj)

    try:
        itens = enriquecer_empresa(razao_social, municipio, socios)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # falha do LLM/rede vira 502, nao 500
        raise HTTPException(status_code=502, detail=f"Falha ao enriquecer: {exc}")

    salvos = salvar_enriquecimento(cnpj, itens, coletado_por=f"agente:{_MODELO_LABEL}", organizacao_id=org_id)
    return {"cnpj": cnpj, "itens_encontrados": len(salvos), "itens": salvos}



@router.get("/empresas/{cnpj}/enriquecimento")
async def listar(cnpj: str, current_user: Dict = Depends(require_admin), org_id: int = Depends(get_active_org)):
    return listar_enriquecimento(cnpj, organizacao_id=org_id)


@router.delete("/empresas/{cnpj}/enriquecimento")
async def remover(cnpj: str, current_user: Dict = Depends(require_admin), org_id: int = Depends(get_active_org)):
    """Direito de exclusao (LGPD): remove o dado pessoal coletado para este
    CNPJ, mantendo so o registro de auditoria de que a remocao ocorreu."""
    total = remover_enriquecimento(cnpj, organizacao_id=org_id)
    return {"cnpj": cnpj, "itens_removidos": total}
