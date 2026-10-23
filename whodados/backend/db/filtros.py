"""Normalizacao dos filtros de porte/cidade/CNAE compartilhada por
service.py (listagem/contagem/lotes/campanhas) e analytics.py (agregacoes).

Codigos PORTE_EMPRESA da Receita Federal (layout oficial):
  00 = nao informado, 01 = micro empresa, 03 = pequeno porte, 05 = demais.
(O mapeamento antigo tratava '01' como "NAO INFORMADO" e esperava um '02'
que nao existe na base: filtrar "ME" devolvia zero empresas.)
"""
from __future__ import annotations
import re
import unicodedata
from typing import Any, List, Tuple

PORTE_NOME_SQL = (
    "CASE e.\"PORTE_EMPRESA\" "
    "WHEN '01' THEN 'ME' "
    "WHEN '03' THEN 'EPP' "
    "WHEN '05' THEN 'DEMAIS' "
    "ELSE 'NAO INFORMADO' END"
)

# Dominio fixo da Receita, na ordem que faz sentido na tela. Descobrir isto
# com SELECT DISTINCT custava 7s de varredura em 752 mil linhas pra devolver
# 3 valores que nunca mudam.
PORTES_DISPONIVEIS = ["ME", "EPP", "DEMAIS", "NAO INFORMADO"]

# Nome (e apelidos que telas/filtros antigos mandam) -> codigo.
PORTE_NOME_TO_CODE = {
    "ME": "01", "MICRO": "01", "MICRO EMPRESA": "01", "MICROEMPRESA": "01",
    "EPP": "03", "PEQUENO": "03", "PEQUENO PORTE": "03", "EMPRESA DE PEQUENO PORTE": "03",
    "DEMAIS": "05", "MEDIO E GRANDE": "05",
    "NAO INFORMADO": "00", "SEM INFORMACAO": "00",
}


def sem_acento_upper(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(ch for ch in s if not unicodedata.combining(ch)).upper().strip()


def codigos_porte(portes: List[str]) -> List[str]:
    """Nomes de porte -> codigos PORTE_EMPRESA (ignora desconhecidos)."""
    out: List[str] = []
    for p in portes:
        cod = PORTE_NOME_TO_CODE.get(sem_acento_upper(p))
        if cod and cod not in out:
            out.append(cod)
    return out


def cidades_normalizadas(cidades: List[str]) -> List[str]:
    """municipios.nome_municipio e MAIUSCULO sem acento ('SAO LEOPOLDO');
    quem digita 'São Leopoldo' tem que casar."""
    return [c for c in (sem_acento_upper(x) for x in cidades) if c]


def clausula_cnae(cnaes: List[str], coluna: str = 'e."CNAE_PRINCIPAL"') -> Tuple[str, List[Any]]:
    """CNAE completo (7 digitos) casa exato; prefixo (2-6 digitos, ex. '47'
    = comercio varejista, '47113') casa por faixa -- a base guarda so o
    codigo de 7 digitos. Faixa BETWEEN usa o indice de CNAE. Aceita
    '4711-3/01' ou '4711301 - Descricao' (pega so os digitos iniciais)."""
    exatos: List[str] = []
    faixas: List[Tuple[str, str]] = []
    for raw in cnaes:
        m = re.match(r"\s*([\d./\-]+)", str(raw))
        dig = re.sub(r"\D", "", m.group(1)) if m else ""
        if len(dig) >= 7:
            exatos.append(dig[:7])
        elif len(dig) >= 2:
            faixas.append((dig.ljust(7, "0"), dig.ljust(7, "9")))
    partes: List[str] = []
    params: List[Any] = []
    if exatos:
        partes.append(f"{coluna} = ANY(%s)"); params.append(exatos)
    for lo, hi in faixas:
        partes.append(f"{coluna} BETWEEN %s AND %s"); params.extend([lo, hi])
    if not partes:
        # Pediu CNAE mas nada era codigo: melhor zero resultado do que
        # ignorar o filtro e devolver a base inteira.
        return ("FALSE", []) if cnaes else ("", [])
    return "(" + " OR ".join(partes) + ")", params
