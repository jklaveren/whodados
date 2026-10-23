"""
Agente de enriquecimento de contatos.

Busca na web (ferramenta web_search do lado do servidor da API da
Anthropic, tipo "web_search_20250305") informacoes de contato PUBLICAMENTE
disponiveis sobre uma empresa e seus socios, e devolve os itens
encontrados -- cada um com a URL de origem, para virar proveniencia
registrada no banco (ver db.service.salvar_enriquecimento).

Este modulo NUNCA grava no banco. Ele so devolve itens; quem persiste e o
endpoint, que tambem decide a base legal e o "coletado_por". Isso mantem o
agente testavel sem precisar de banco, e deixa claro que toda gravacao de
dado pessoal passa por um unico ponto (db.service.salvar_enriquecimento),
que exige fonte_url em cada item.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

try:
    import anthropic
except ImportError:
    anthropic = None

_MODELO = "claude-sonnet-4-5"

_FERRAMENTA_BUSCA = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}

_FERRAMENTA_REGISTRAR = {
    "name": "registrar_contatos_encontrados",
    "description": (
        "Registra os contatos publicos que voce encontrou pesquisando a empresa "
        "e/ou os socios informados. Chame isso ao final, depois de pesquisar. "
        "Cada item PRECISA ter uma fonte_url real, de uma busca que voce de fato "
        "fez -- nunca invente valor ou fonte. Se nao encontrar nada confiavel, "
        "chame com itens=[]."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "itens": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tipo_alvo": {"type": "string", "enum": ["empresa", "socio"]},
                        "nome_alvo": {
                            "type": "string",
                            "description": "Nome do socio (se tipo_alvo=socio) ou razao social (se tipo_alvo=empresa)",
                        },
                        "campo": {"type": "string", "enum": ["email", "telefone", "site", "linkedin"]},
                        "valor": {"type": "string"},
                        "fonte_url": {"type": "string", "description": "URL exata da pagina onde a informacao foi encontrada"},
                        "fonte_titulo": {"type": "string"},
                    },
                    "required": ["tipo_alvo", "nome_alvo", "campo", "valor", "fonte_url"],
                },
            }
        },
        "required": ["itens"],
    },
}

_SYSTEM_PROMPT = """Voce e um agente que busca informacoes de CONTATO
PUBLICAMENTE DISPONIVEIS sobre empresas e seus socios, para fins comerciais
legitimos (prospeccao B2B). Regras:

1. Use apenas fontes publicas (site oficial da empresa, redes sociais
   publicas, cadastros publicos, LinkedIn publico). Nunca tente acessar
   dado privado, pago ou protegido por login.
2. Nunca invente ou "complete" um contato que voce nao encontrou de fato
   buscando -- prefira devolver menos itens, todos verificados, a mais
   itens especulativos.
3. Todo item registrado precisa citar a URL exata de onde veio.
4. Ao final da pesquisa, chame SEMPRE a ferramenta
   registrar_contatos_encontrados -- mesmo que a lista de itens fique
   vazia."""


def _cliente() -> "anthropic.Anthropic":
    if anthropic is None:
        raise RuntimeError("pacote 'anthropic' nao instalado -- rode: pip install anthropic")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("variavel de ambiente ANTHROPIC_API_KEY nao configurada")
    return anthropic.Anthropic(api_key=api_key)


def enriquecer_empresa(razao_social: str, municipio: Optional[str], socios: List[str]) -> List[Dict[str, Any]]:
    """Busca contatos publicos da empresa e dos socios nomeados.
    Retorna uma lista de dicts prontos para db.service.salvar_enriquecimento
    (chave por chave: tipo_alvo, nome_alvo, campo, valor, fonte_url, fonte_titulo).
    """
    cliente = _cliente()
    nomes_socios = ", ".join(s for s in socios if s) or "nenhum socio informado"
    pergunta = (
        f"Empresa: {razao_social}"
        + (f", municipio de {municipio}" if municipio else "")
        + f". Socios conhecidos: {nomes_socios}.\n\n"
        "Pesquise contatos publicos (email, telefone, site oficial, LinkedIn) "
        "desta empresa e, se possivel, dos socios nomeados. Ao final, chame "
        "registrar_contatos_encontrados com o que encontrou (ou itens=[] se nada)."
    )

    resposta = cliente.messages.create(
        model=_MODELO,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        tools=[_FERRAMENTA_BUSCA, _FERRAMENTA_REGISTRAR],
        messages=[{"role": "user", "content": pergunta}],
    )

    for bloco in reversed(resposta.content):
        if getattr(bloco, "type", None) == "tool_use" and getattr(bloco, "name", None) == "registrar_contatos_encontrados":
            itens = bloco.input.get("itens", [])
            # Defesa extra: descarta qualquer item sem fonte_url, mesmo que o
            # modelo tenha ignorado a instrucao -- nunca persistimos sem proveniencia.
            return [i for i in itens if i.get("fonte_url")]
    return []
