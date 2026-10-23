"""Conferencia do lote antes do disparo.

Regras deterministicas em todos os itens; camada LLM opcional (desligada por
padrao) sobre as saudacoes distintas. O relatorio informa a cobertura.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional

try:
    import anthropic
except ImportError:
    anthropic = None

try:
    from ..logger import get_logger
except ImportError:
    import logging
    get_logger = lambda x: logging.getLogger(x)

log = get_logger(__name__)

_MODELO = "claude-haiku-4-5-20251001"
_NOMES_POR_CHAMADA = 80

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")
_VARIAVEL_NAO_SUBSTITUIDA = re.compile(r"\{\{\s*\w+\s*\}\}")
_MARCADOR_SOCIETARIO = re.compile(
    r"\b(ltda|limitada|eireli|epp|scp|spe|s/?a|me)\b", re.I)
_SO_CONSOANTES = re.compile(r"^[^aeiouáéíóúâêôãõà]+$", re.I)

# Barram apenas como termo unico: "Comercio Radunz" passa.
_GENERICOS = {
    "comercio", "servicos", "servico", "industria", "industrias", "construtora",
    "transportes", "transporte", "distribuidora", "representacoes", "participacoes",
    "empreendimentos", "administradora", "assessoria", "consultoria", "consultores",
    "associacao", "instituto", "fundacao", "fundo", "cooperativa", "condominio",
    "sociedade", "organizacao", "grupo", "centro", "clinica", "escritorio",
    "agencia", "atacado", "varejo", "loja", "casa", "oficina", "deposito",
    "prefeitura", "municipio", "camara", "sindicato", "empresa", "firma",
}

# bloqueio = nao envia. aviso = envia, mas aparece no relatorio.
BLOQUEIO, AVISO = "bloqueio", "aviso"


def _normalizar_ascii(texto: str) -> str:
    """minusculo e sem acento, para comparar com _GENERICOS."""
    base = unicodedata.normalize("NFKD", (texto or "").strip().lower())
    return "".join(c for c in base if not unicodedata.combining(c))


def _checar_item(item: Dict[str, Any], vistos: set) -> List[Dict[str, str]]:
    """Problemas deterministicos de UM e-mail montado."""
    achados: List[Dict[str, str]] = []
    saud = (item.get("saudacao") or "").strip()
    email = (item.get("email") or "").strip()
    assunto = item.get("assunto") or ""
    corpo = (item.get("corpo_texto") or "") + (item.get("corpo_html") or "")

    if not saud:
        achados.append({"regra": "saudacao_vazia",
                        "severidade": BLOQUEIO,
                        "detalhe": "e-mail comecaria com 'Oi, !'"})
    else:
        if any(c.isdigit() for c in saud):
            achados.append({"regra": "saudacao_com_numero", "severidade": BLOQUEIO,
                            "detalhe": f"saudacao {saud!r} contem digito"})
        if _MARCADOR_SOCIETARIO.search(saud):
            achados.append({"regra": "saudacao_com_marcador_societario",
                            "severidade": BLOQUEIO,
                            "detalhe": f"saudacao {saud!r} traz LTDA/ME/SA/SCP"})
        if len(saud.replace(" ", "")) <= 2:
            achados.append({"regra": "saudacao_curta", "severidade": BLOQUEIO,
                            "detalhe": f"saudacao {saud!r} tem 2 letras ou menos"})
        elif _SO_CONSOANTES.match(saud.replace(" ", "")):
            achados.append({"regra": "saudacao_sem_vogal", "severidade": BLOQUEIO,
                            "detalhe": f"saudacao {saud!r} nao tem vogal -- e' sigla"})
        if _normalizar_ascii(saud) in _GENERICOS:
            achados.append({"regra": "saudacao_generica", "severidade": BLOQUEIO,
                            "detalhe": f"{saud!r} e' palavra de ramo, nao identifica a empresa"})

    if not _EMAIL_RE.match(email):
        achados.append({"regra": "email_invalido", "severidade": BLOQUEIO,
                        "detalhe": f"endereco {email!r} nao e' um e-mail valido"})
    elif email.lower() in vistos:
        achados.append({"regra": "email_duplicado_no_lote", "severidade": BLOQUEIO,
                        "detalhe": f"{email} ja aparece neste lote"})
    else:
        vistos.add(email.lower())

    if not (assunto or "").strip():
        achados.append({"regra": "assunto_vazio", "severidade": BLOQUEIO,
                        "detalhe": "mensagem sairia sem assunto"})

    # Modelo que usa a cidade e contato sem cidade: o assunto sairia "em ?".
    if item.get("exige_cidade") and not (item.get("cidade") or "").strip():
        achados.append({"regra": "cidade_vazia", "severidade": BLOQUEIO,
                        "detalhe": "o modelo cita a cidade e este contato nao tem cidade"})

    sobrou = _VARIAVEL_NAO_SUBSTITUIDA.findall(assunto + corpo)
    if sobrou:
        achados.append({"regra": "variavel_nao_substituida", "severidade": BLOQUEIO,
                        "detalhe": f"placeholder no texto final: {sorted(set(sobrou))}"})
    return achados


_PROMPT = """Voce confere vocativos de e-mail comercial em portugues do Brasil.

Para cada nome da lista, decida se serve para completar a frase "Oi, <nome>!"
num e-mail a uma empresa. Serve: primeiro nome de pessoa (Ana, Paulo) ou nome
pelo qual uma empresa e' conhecida (Viva Urbanismo, Bing Imoveis).
Nao serve: fragmento sem sentido (Fm, Sv, Xyz), palavra generica isolada
(Comercio, Servicos, Construtora), texto truncado, ou qualquer coisa que
soaria errada para quem le.

Responda SO um array JSON, um objeto por nome, na mesma ordem:
[{"nome": "<nome>", "ok": true|false, "motivo": "<curto, so' se ok=false>"}]

Nomes:
%s"""


def _validar_nomes_llm(nomes: List[str]) -> Dict[str, str]:
    """{nome: motivo} apenas para os reprovados. {} se o LLM nao rodou."""
    if anthropic is None or not os.environ.get("ANTHROPIC_API_KEY"):
        return {}
    cliente = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    reprovados: Dict[str, str] = {}
    for i in range(0, len(nomes), _NOMES_POR_CHAMADA):
        bloco = nomes[i:i + _NOMES_POR_CHAMADA]
        listado = "\n".join(f"- {n}" for n in bloco)
        try:
            r = cliente.messages.create(
                model=_MODELO, max_tokens=4000,
                messages=[{"role": "user", "content": _PROMPT % listado}],
            )
            texto = r.content[0].text.strip()
            inicio, fim = texto.find("["), texto.rfind("]")
            if inicio < 0 or fim < 0:
                continue
            for linha in json.loads(texto[inicio:fim + 1]):
                if not linha.get("ok", True):
                    reprovados[linha.get("nome", "")] = linha.get("motivo") or "reprovado pelo LLM"
        except Exception as e:
            log.warning(f"validacao LLM falhou no bloco {i}: {e}")
    return reprovados


def validar_lote(itens: Iterable[Dict[str, Any]], usar_llm: bool = False) -> Dict[str, Any]:
    """Confere todos os e-mails montados e devolve o relatorio.

    itens: cada um com cnpj, email, saudacao, assunto, corpo_texto/corpo_html.
    """
    itens = list(itens)
    vistos: set = set()
    problemas: List[Dict[str, Any]] = []

    for item in itens:
        for p in _checar_item(item, vistos):
            problemas.append({"cnpj": item.get("cnpj"), "email": item.get("email"),
                              "saudacao": item.get("saudacao"), **p})

    bloqueados_regra = {p["cnpj"] for p in problemas if p["severidade"] == BLOQUEIO}

    llm_rodou = False
    if usar_llm:
        candidatos = sorted({
            (i.get("saudacao") or "").strip() for i in itens
            if i.get("cnpj") not in bloqueados_regra and (i.get("saudacao") or "").strip()
        })
        reprovados = _validar_nomes_llm(candidatos) if candidatos else {}
        llm_rodou = bool(anthropic and os.environ.get("ANTHROPIC_API_KEY"))
        for item in itens:
            saud = (item.get("saudacao") or "").strip()
            if saud in reprovados and item.get("cnpj") not in bloqueados_regra:
                problemas.append({
                    "cnpj": item.get("cnpj"), "email": item.get("email"),
                    "saudacao": saud, "regra": "saudacao_reprovada_llm",
                    "severidade": BLOQUEIO, "detalhe": reprovados[saud],
                })

    bloqueados = {p["cnpj"] for p in problemas if p["severidade"] == BLOQUEIO}
    por_regra: Dict[str, int] = {}
    for p in problemas:
        por_regra[p["regra"]] = por_regra.get(p["regra"], 0) + 1

    return {
        "total": len(itens),
        "aprovados": len(itens) - len(bloqueados),
        "bloqueados": len(bloqueados),
        "cnpjs_bloqueados": sorted(x for x in bloqueados if x),
        "por_regra": dict(sorted(por_regra.items(), key=lambda kv: -kv[1])),
        "llm_disponivel": llm_rodou,
        # Sem LLM o relatorio nao pode se dizer completo -- quem chama decide
        # se envia mesmo assim.
        "cobertura": "regras+llm" if llm_rodou else "somente regras",
        "problemas": problemas[:500],
        "problemas_truncados": max(len(problemas) - 500, 0),
    }
