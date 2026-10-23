"""Transforma o que a pessoa sabe do negocio em uma proposta pronta.

Existe porque o caminho contrario nao funciona: eu escrevendo o texto por
conta propria e a dona corrigindo depois. Foram quatro versoes dos modelos da
Alfa e nenhuma serviu, porque quem conhece o cliente e' ela, nao eu. Aqui ela
preenche o que sabe e o modelo monta a proposta.

A estrutura segue o guia que ela passou:

  1. Apresente-se        -- por que voce e' a pessoa certa para ESTE projeto
  2. Plano de trabalho   -- escopo, prazos e recursos, sem deixar margem
  3. Disponibilidade     -- como e quando o cliente fala com voce

Serve tanto para colar numa plataforma (Workana, 99freelas) quanto para sair
por e-mail: `montar_html` veste a proposta no desenho da empresa, e
`montar_texto` devolve a versao limpa para copiar.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

try:
    import anthropic
except ImportError:  # pragma: no cover - ambiente sem o pacote
    anthropic = None

# Trocavel por variavel de ambiente: a geracao de proposta e' barata em
# qualquer um dos tres, entao a escolha e' de qualidade de texto, nao de custo.
#   claude-opus-5-5   ~US$ 0,018 por proposta  (melhor escrita)
#   claude-sonnet-5-5 ~US$ 0,009
#   claude-haiku-5-5  ~US$ 0,0004
_MODELO = os.environ.get("MODELO_PROPOSTA", "claude-opus-5-5")
_MAX_TOKENS = 4000

_FERRAMENTA = {
    "name": "entregar_proposta",
    "description": "Devolve a proposta pronta, parte por parte.",
    "input_schema": {
        "type": "object",
        "properties": {
            "titulo": {
                "type": "string",
                "description": "Titulo da proposta, ate' 70 caracteres. Fala do "
                               "resultado para o cliente, nao do servico.",
            },
            "apresentacao": {
                "type": "string",
                "description": "Por que voce e' a pessoa certa para ESTE projeto. "
                               "2 a 3 frases, concretas. Nada de curriculo generico.",
            },
            "plano": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "etapa": {"type": "string", "description": "Nome curto da etapa."},
                        "entrega": {"type": "string", "description": "O que o cliente recebe nela."},
                        "prazo": {"type": "string", "description": "Prazo da etapa, ex.: '3 dias'."},
                    },
                    "required": ["etapa", "entrega"],
                },
                "description": "3 a 5 etapas. Deixa claro o alcance -- e, por "
                               "consequencia, o que fica de fora.",
            },
            "fora_do_escopo": {
                "type": "array",
                "items": {"type": "string"},
                "description": "O que esta proposta NAO cobre. E' o que evita "
                               "briga depois. Pode vir vazio se nao houver duvida.",
            },
            "recursos": {
                "type": "string",
                "description": "O que voce precisa do cliente para comecar "
                               "(acessos, conteudo, decisoes). Uma frase.",
            },
            "disponibilidade": {
                "type": "string",
                "description": "Como e quando o cliente fala com voce e recebe "
                               "acompanhamento. Uma ou duas frases.",
            },
            "investimento": {
                "type": "string",
                "description": "Valor e forma de pagamento, se a autora informou. "
                               "Vazio se ela nao disse -- nunca invente preco.",
            },
            "proximo_passo": {
                "type": "string",
                "description": "O que o cliente faz para seguir. Pequeno e concreto.",
            },
            "porque": {
                "type": "string",
                "description": "Em uma frase, para a autora: as escolhas que voce fez "
                               "e o que ela deveria revisar.",
            },
        },
        "required": ["titulo", "apresentacao", "plano", "disponibilidade", "proximo_passo"],
    },
}

_SYSTEM = """Voce escreve propostas comerciais em portugues do Brasil, com
acentuacao correta, para quem vai enviar a um cliente que esta' decidindo
entre algumas opcoes.

A estrutura e' sempre a mesma, e cada parte tem uma funcao:

APRESENTACAO. Por que esta pessoa e' a certa para ESTE projeto -- nao um
curriculo. Se a autora deu um caso parecido que ela ja' fez, use. Se nao
deu, fale da leitura que ela tem do problema, nao de qualidades dela.

PLANO DE TRABALHO. Etapas com entrega e prazo. E' aqui que se evita briga
depois: o cliente precisa terminar a leitura sabendo exatamente o que vai
receber e quando. Se a autora nao deu prazos, proponha prazos plausiveis e
avise no campo "porque" que eles sao sugestao.

FORA DO ESCOPO. O que nao esta incluido. Parece ariscado e e' o contrario:
quem le' confia mais em quem delimita.

DISPONIBILIDADE. Como o cliente fala com voce e com que frequencia tem
noticia do andamento.

Regras que nao se negociam:

1. NADA DE FRASE DE CATALOGO. "Solucoes sob medida", "excelencia",
   "parceria de confianca", "profissionais altamente qualificados" estao
   proibidas. Se a frase serve para qualquer proposta de qualquer ramo, ela
   nao serve para esta.

2. NUNCA INVENTE FATO. Preco, prazo de empresa, numero de clientes, anos de
   mercado, tecnologia usada: so' entra o que a autora informou. Se faltar
   algo importante, deixe o campo vazio e diga no "porque" o que falta.

3. CONCRETO NO LUGAR DE ADJETIVO. "Entrego o site em 10 dias com as 5
   paginas revisadas" vale mais que "entrego com agilidade e qualidade".

4. VOZ DE PESSOA. Primeira pessoa, profissional falando com profissional.
   Sem "prezados", sem "venho por meio desta", sem "att".

5. TAMANHO. A proposta inteira cabe em uma tela. Cliente que recebe cinco
   propostas nao le' a mais longa.

Chame sempre a ferramenta entregar_proposta."""


def _cliente() -> "anthropic.Anthropic":
    if anthropic is None:
        raise RuntimeError("pacote 'anthropic' nao instalado -- rode: pip install anthropic")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("variavel de ambiente ANTHROPIC_API_KEY nao configurada")
    return anthropic.Anthropic(api_key=api_key)


CAMPOS = [
    ("quem_sou", "Quem envia a proposta"),
    ("cliente", "Cliente / projeto"),
    ("necessidade", "O que o cliente precisa"),
    ("meu_diferencial", "Por que eu sou a pessoa certa"),
    ("escopo", "O que eu vou entregar"),
    ("prazo", "Prazos"),
    ("investimento", "Valor e forma de pagamento"),
    ("disponibilidade", "Minha disponibilidade"),
    ("tom", "Tom"),
    ("observacoes", "Outras observacoes"),
]


def _pergunta(dados: Dict[str, Any]) -> str:
    linhas = [
        f"{rotulo}: {str(dados.get(chave) or '').strip()}"
        for chave, rotulo in CAMPOS
        if str(dados.get(chave) or "").strip()
    ]
    if not linhas:
        raise ValueError("Preencha pelo menos o cliente e o que ele precisa.")
    return (
        "Monte a proposta com base nisto:\n\n"
        + "\n".join(linhas)
        + "\n\nChame entregar_proposta com o resultado."
    )


def gerar(dados: Dict[str, Any]) -> Dict[str, Any]:
    """Pede a proposta ao modelo e devolve as partes, ainda sem formato."""
    resposta = _cliente().messages.create(
        model=_MODELO,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM,
        tools=[_FERRAMENTA],
        tool_choice={"type": "tool", "name": "entregar_proposta"},
        messages=[{"role": "user", "content": _pergunta(dados)}],
    )
    for bloco in resposta.content:
        if getattr(bloco, "type", None) == "tool_use":
            return dict(bloco.input)
    raise RuntimeError("o modelo nao devolveu a proposta")


def montar_texto(p: Dict[str, Any]) -> str:
    """Versao em texto puro -- e' esta que se cola numa plataforma."""
    linhas: List[str] = [p.get("titulo", "").strip(), ""]
    linhas += [p.get("apresentacao", "").strip(), ""]

    if p.get("plano"):
        linhas.append("COMO EU TRABALHO")
        for i, etapa in enumerate(p["plano"], 1):
            prazo = f" ({etapa['prazo']})" if etapa.get("prazo") else ""
            linhas.append(f"{i}. {etapa.get('etapa', '')}{prazo}")
            if etapa.get("entrega"):
                linhas.append(f"   {etapa['entrega']}")
        linhas.append("")

    if p.get("fora_do_escopo"):
        linhas.append("NAO ESTA INCLUIDO")
        linhas += [f"- {x}" for x in p["fora_do_escopo"]]
        linhas.append("")

    for rotulo, chave in (("PARA COMECAR", "recursos"),
                          ("INVESTIMENTO", "investimento"),
                          ("DISPONIBILIDADE", "disponibilidade")):
        if p.get(chave):
            linhas += [rotulo, p[chave].strip(), ""]

    if p.get("proximo_passo"):
        linhas.append(p["proximo_passo"].strip())
    return "\n".join(linhas).strip()


def _esc(texto: Any) -> str:
    return (str(texto or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").strip())


def montar_html(p: Dict[str, Any], identidade: Dict[str, str]) -> str:
    """Veste a proposta no desenho da empresa, para sair por e-mail.

    Sem rodape de contato: a assinatura da empresa e' injetada pelo motor de
    envio, e repetir endereco e telefone so' ocupa espaco.
    """
    cor = identidade.get("cor_principal", "#1F2A44")
    txt = identidade.get("cor_texto", "#3A4556")
    fundo = identidade.get("cor_fundo", "#F1F3F6")
    selo = _esc(identidade.get("selo", ""))
    fonte = identidade.get("fonte", "Arial,Helvetica,sans-serif")

    def par(conteudo: str, margem: str = "0 0 14px 0") -> str:
        return (f'<p style="margin:{margem};font-size:15px;line-height:1.6;'
                f'color:{txt};">{conteudo}</p>')

    blocos = [par(_esc(p.get("apresentacao")))]

    if p.get("plano"):
        itens = "".join(
            f'<li style="margin:0 0 10px 0;"><b style="color:{cor};">'
            f'{_esc(e.get("etapa"))}</b>'
            + (f' <span style="color:#8A94A6;">&middot; {_esc(e.get("prazo"))}</span>'
               if e.get("prazo") else "")
            + (f'<br>{_esc(e.get("entrega"))}' if e.get("entrega") else "")
            + "</li>"
            for e in p["plano"]
        )
        blocos.append(
            f'<p style="margin:22px 0 8px 0;font-size:12px;letter-spacing:.08em;'
            f'color:{cor};font-weight:bold;">COMO EU TRABALHO</p>'
            f'<ol style="margin:0 0 14px 0;padding-left:20px;font-size:15px;'
            f'line-height:1.6;color:{txt};">{itens}</ol>'
        )

    if p.get("fora_do_escopo"):
        itens = "".join(f"<li>{_esc(x)}</li>" for x in p["fora_do_escopo"])
        blocos.append(
            f'<p style="margin:18px 0 6px 0;font-size:12px;letter-spacing:.08em;'
            f'color:{cor};font-weight:bold;">NÃO ESTÁ INCLUÍDO</p>'
            f'<ul style="margin:0 0 14px 0;padding-left:20px;font-size:14px;'
            f'line-height:1.6;color:#8A94A6;">{itens}</ul>'
        )

    for rotulo, chave in (("PARA COMEÇAR", "recursos"),
                          ("INVESTIMENTO", "investimento"),
                          ("DISPONIBILIDADE", "disponibilidade")):
        if p.get(chave):
            blocos.append(
                f'<p style="margin:18px 0 6px 0;font-size:12px;letter-spacing:.08em;'
                f'color:{cor};font-weight:bold;">{rotulo}</p>' + par(_esc(p[chave]))
            )

    if p.get("proximo_passo"):
        blocos.append(
            f'<p style="margin:22px 0 0 0;font-size:15px;line-height:1.6;'
            f'color:{cor};font-weight:bold;">{_esc(p["proximo_passo"])}</p>'
        )

    cabecalho = (
        f'<tr><td style="background-color:{cor};padding:26px 32px;text-align:center;">'
        f'<span style="display:inline-block;width:56px;height:56px;border-radius:50%;'
        f'border:2px solid #FFFFFF;color:#FFFFFF;font-weight:bold;font-size:18px;'
        f'line-height:52px;letter-spacing:1px;">{selo}</span></td></tr>'
    ) if selo else ""

    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background-color:{fundo};padding:32px 0;"><tr><td align="center">'
        f'<table role="presentation" width="580" cellpadding="0" cellspacing="0" '
        f'style="background-color:#FFFFFF;border-radius:12px;overflow:hidden;'
        f'font-family:{fonte};box-shadow:0 1px 3px rgba(0,0,0,0.08);">'
        + cabecalho +
        f'<tr><td style="padding:30px 32px 8px 32px;">'
        f'<h1 style="margin:0 0 16px 0;font-size:21px;line-height:1.35;color:{cor};'
        f'font-weight:bold;">{_esc(p.get("titulo"))}</h1></td></tr>'
        f'<tr><td style="padding:0 32px 30px 32px;">{"".join(blocos)}</td></tr>'
        f'</table></td></tr></table>'
    )
