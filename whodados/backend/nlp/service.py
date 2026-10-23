"""
Traducao de pergunta em portugues -> FiltroEmpresas, via tool use forcado
da API da Anthropic. O modelo so pode chamar a ferramenta filtrar_empresas
com argumentos que batem com o schema Pydantic -- nao existe caminho para
o modelo devolver SQL ou texto livre que toque o banco/dataframe.

Variavel de ambiente necessaria: ANTHROPIC_API_KEY (mesmo padrao de
.env.example que RF_SHARE_TOKEN e SMTP_* ja seguem no projeto).
"""
from __future__ import annotations

import os

try:
    import anthropic
except ImportError:  # pacote opcional -- so falha se essa rota for usada de fato
    anthropic = None

from .schemas import FiltroEmpresas

_MODELO = "claude-sonnet-4-5"

_FERRAMENTA_FILTRO = {
    "name": "filtrar_empresas",
    "description": (
        "Filtra a base de empresas do RS de acordo com os criterios extraidos "
        "da pergunta do usuario. So preencha os campos que a pergunta menciona "
        "de fato -- nao invente valores."
    ),
    "input_schema": FiltroEmpresas.model_json_schema(),
}

_SYSTEM_PROMPT = """Voce traduz perguntas em portugues sobre empresas do RS
em filtros estruturados. Voce NUNCA responde em texto livre e NUNCA escreve
SQL -- sua unica saida e uma chamada da ferramenta filtrar_empresas.

Exemplos:
- "empresas de comercio em Porto Alegre" -> cidade="Porto Alegre", cnae="47"
- "as 10 maiores empresas por capital social" -> ordenar_por="capital_social", ordem="desc", limite=10

Se a pergunta nao tiver relacao com dados de empresas, preencha o filtro
mais neutro possivel (sem cidade/cnae) e deixe o limite padrao."""


def _cliente() -> "anthropic.Anthropic":
    if anthropic is None:
        raise RuntimeError(
            "pacote 'anthropic' nao instalado -- rode: pip install anthropic"
        )
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("variavel de ambiente ANTHROPIC_API_KEY nao configurada")
    return anthropic.Anthropic(api_key=api_key)


def interpretar_pergunta(pergunta: str) -> FiltroEmpresas:
    cliente = _cliente()
    resposta = cliente.messages.create(
        model=_MODELO,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        tools=[_FERRAMENTA_FILTRO],
        tool_choice={"type": "tool", "name": "filtrar_empresas"},
        messages=[{"role": "user", "content": pergunta}],
    )
    bloco_ferramenta = next(b for b in resposta.content if b.type == "tool_use")
    return FiltroEmpresas.model_validate(bloco_ferramenta.input)


def resumir_resultado(pergunta: str, filtro: FiltroEmpresas, total: int) -> str:
    partes = [f"{total} empresa(s) encontrada(s)"]
    if filtro.cidade:
        partes.append(f"em {filtro.cidade}")
    if filtro.cnae:
        partes.append(f"no setor CNAE {filtro.cnae}")
    return " ".join(partes) + "."
