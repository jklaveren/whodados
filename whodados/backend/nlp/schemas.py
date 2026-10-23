"""
Schema do filtro estruturado que o LLM (via tool use da API da Anthropic)
deve produzir para consultas em linguagem natural sobre a base de empresas.

O modelo NUNCA gera SQL nem texto livre de filtro: ele so pode chamar a
tool "filtrar_empresas" preenchendo estes campos, que o Pydantic valida
antes de qualquer coisa tocar em dados reais. Os campos batem exatamente
com o que data.filtrar_empresas() ja suporta hoje (cidade, cnae, busca) --
nao inventamos capacidade de filtro que o backend nao tem.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class FiltroEmpresas(BaseModel):
    cidade: Optional[str] = Field(default=None, description="Nome do municipio, ex: Porto Alegre")
    cnae: Optional[str] = Field(default=None, description="Prefixo ou trecho do CNAE, ex: '47' para comercio")
    busca: Optional[str] = Field(default=None, description="Busca livre por razao social, nome fantasia etc.")
    ordenar_por: Literal["capital_social", "divida_total", "nenhum"] = "nenhum"
    ordem: Literal["asc", "desc"] = "desc"
    limite: int = Field(default=50, ge=1, le=200)

    @field_validator("cnae")
    @classmethod
    def cnae_razoavel(cls, v):
        if v is not None and len(v) > 20:
            raise ValueError("cnae parece invalido (muito longo)")
        return v


class RespostaConsultaNatural(BaseModel):
    pergunta_original: str
    filtro_interpretado: FiltroEmpresas
    total_encontrado: int
    empresas: list[dict]
    resumo_em_texto: str
