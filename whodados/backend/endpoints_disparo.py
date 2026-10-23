"""Disparar: mandar os proximos N da lista propria, numa tela so'.

Substitui o caminho Lote -> Campanha -> Executar para quem prospecta sobre
lista propria. Nao ha' copia da lista: os contatos ficam na carteira e so'
mudam de situacao (disponivel -> em trabalho), e e' da carteira "em trabalho"
que sai o publico do follow-up. Por baixo reaproveita o mesmo motor de envio
das campanhas (conferencia do texto, descadastro, remetente, rastreio)."""
from datetime import datetime, timezone
import os
from typing import Callable, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from .auth import get_current_user, get_active_org
from .db import (
    tamanho_carteira, dias_followup_org, max_por_clique_org,
    resumo_disparo, campanha_de_disparo, reservar_proximos, devolver_nao_enviados,
    historico_disparo, remetentes_da_empresa, get_template, org_escopo_base,
    contar_followups_devidos, listar_followups_devidos, reservar_followups,
    marcar_situacao_contato, DIAS_FOLLOWUP, SITUACOES_CONTATO, resumo_fila, cancelar_fila,
    sortear_modelos, metricas_modelos,
)
from .mailer.service import _smtp_efetivo
from .whatsapp_manual import (
    contar_para_chamar, listar_para_chamar, marcar_whatsapp, buscar_contato, contar_por_site,
    STATUS_WHATSAPP, FILTROS_SITE,
)
from .endpoints_campanhas import (
    INTERVALO_RODADA_MIN, _janela_de_envio, _orcamento_email_hoje, _remetente_valido, rodar_fila,
    avancar_filas,
)
from .config import settings
from .logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/disparo")

# Teto por clique, alem do teto do dia: um engano de digitacao (2000 em vez de
# 20) nao pode virar um disparo gigante de dominio novo.
# Padrao de fabrica; cada empresa pode ter o seu em organizacoes.max_por_clique.
# A trava existe pra um 2000 digitado no lugar de 20 nao virar disparo gigante,
# mas o numero certo depende do volume de quem envia -- logo, e' por empresa.
MAX_POR_CLIQUE = int(os.getenv("MAX_POR_CLIQUE", "100"))
# Quantos modelos cabem num mesmo teste. Mais que isso dilui a amostra de cada um.
MAX_MODELOS = 5


def _remetente_permitido(current_user: Dict, org_id: int, pedido) -> str:
    """Quem assina o disparo. Cada pessoa envia pela PROPRIA caixa: conectar o Gmail
    autoriza a pessoa, nao a equipe. So' o administrador pode assinar por outro, e fica
    no log. Antes qualquer membro da empresa podia enviar pelo Gmail de um colega."""
    eu = current_user["sub"]
    pedido = (pedido or "").strip()
    if not pedido or pedido == eu:
        return eu
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403,
                            detail="Voce so' pode enviar pela sua propria caixa de e-mail.")
    valido = _remetente_valido(pedido, org_id)
    if valido:
        logger.info(f"Envio de {eu} assinado como {valido} (empresa {org_id})")
    return valido or eu


def _exigir_conta_conectada(org_id: int, remetente: str) -> None:
    """Recusa ANTES de reservar ninguem: quem nao conectou o Gmail nao tem de onde enviar,
    e a fila queimaria os contatos em erro."""
    cfg = _smtp_efetivo(org_id, remetente)
    if not cfg.get("gmail_refresh_token") and not cfg.get("host"):
        raise HTTPException(
            status_code=400,
            detail=f"{remetente} ainda nao conectou o Gmail. A pessoa entra em Configuracoes > "
                   "Meu e-mail e conecta a conta; so' depois da' para enviar por ela.")


def _exigir_lista_propria(org_id: int) -> None:
    """O Disparar trabalha sobre empresas_carteira. O que importa e' TER uma
    lista, nao o escopo_base.

    Antes a checagem era escopo_base == 'carteira', o que barrava a Alfa: ela
    pesquisa sobre a base inteira da Receita (escopo 'receita') mas tem uma
    lista de trabalho recortada dali -- engenharia e arquitetura. Pelo criterio
    velho, ou ela perdia a pesquisa na base cheia ou nao disparava nunca."""
    if not tamanho_carteira(org_id):
        raise HTTPException(
            status_code=400,
            detail="Esta empresa ainda nao tem lista de trabalho. Carregue a carteira antes de disparar.")


@router.get("/resumo")
async def resumo(current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    _exigir_lista_propria(org_id)
    return {
        **resumo_disparo(org_id),
        "followup_devidos": contar_followups_devidos(org_id, dias_followup_org(org_id)),
        "dias_followup": dias_followup_org(org_id),
        "fila": resumo_fila(org_id),
        "por_rodada": int(getattr(settings, "ENVIO_POR_RODADA", 10) or 10),
        "intervalo_min": list(INTERVALO_RODADA_MIN),
        "pode_enviar_hoje": _orcamento_email_hoje(org_id),
        "max_por_clique": max_por_clique_org(org_id, MAX_POR_CLIQUE),
        # Membro so' ve a propria caixa; o administrador ve todas.
        "remetentes": [r for r in remetentes_da_empresa(org_id)
                       if current_user.get("is_admin") or r["username"] == current_user["sub"]],
    }


@router.get("/historico")
async def historico(current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    _exigir_lista_propria(org_id)
    return historico_disparo(org_id)


def _disparar(data: Dict, current_user: Dict, org_id: int, prefixo: str,
              reservar: Callable[[int, int, int], List[Dict]]) -> Dict:
    """Pedido -> entra na fila -> a primeira rodada sai agora, o resto no ritmo.

    Nao manda tudo de uma vez: dominio novo que despeja dezenas de e-mails de
    uma vez cai no spam. Sai ENVIO_POR_RODADA por rodada, uma rodada a cada
    11-12 minutos, ate' completar o pedido. Igual para o primeiro contato e
    para o follow-up: as travas de quantidade, de teto do dia e de duplicidade
    vivem num lugar so'."""
    _exigir_lista_propria(org_id)
    try:
        quantidade = int(data.get("quantidade"))
        pedidos = data.get("template_ids") or [data.get("template_id")]
        modelos = list(dict.fromkeys(int(t) for t in pedidos))   # sem repetir, na ordem
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Informe a quantidade e o modelo de e-mail.")
    if quantidade <= 0:
        raise HTTPException(status_code=400, detail="A quantidade deve ser maior que zero.")
    if not modelos or len(modelos) > MAX_MODELOS:
        raise HTTPException(status_code=400, detail=f"Escolha de 1 a {MAX_MODELOS} modelos.")
    for tid in modelos:
        if not get_template(tid, organizacao_id=org_id):
            raise HTTPException(status_code=404, detail="Modelo de e-mail nao encontrado.")
    template_id = modelos[0]   # a campanha de apoio leva o 1o; o sorteio sobrescreve por contato

    remetente = _remetente_permitido(current_user, org_id, data.get("remetente"))
    _exigir_conta_conectada(org_id, remetente)

    # O menor entre o pedido, o teto por clique e o que ainda cabe hoje.
    pode_hoje = _orcamento_email_hoje(org_id)
    if pode_hoje is not None and pode_hoje <= 0:
        raise HTTPException(status_code=429,
                            detail="O limite de envios de hoje ja' foi atingido. Tente amanha.")
    teto_clique = max_por_clique_org(org_id, MAX_POR_CLIQUE)
    n = min(quantidade, teto_clique, pode_hoje if pode_hoje is not None else quantidade)

    campanha = campanha_de_disparo(org_id, template_id, remetente, current_user["sub"], prefixo=prefixo)
    # Entra na fila ANTES de qualquer envio: dois cliques seguidos nao pegam os
    # mesmos contatos, e uma queda do servidor nao perde ninguem.
    enfileirados = reservar(campanha["id"], org_id, n)
    if not enfileirados:
        return {"enviados": 0, "erros": 0, "pedidos": quantidade, "enfileirados": 0,
                "mensagem": "Nao ha' contatos disponiveis."}

    # Sorteio EQUILIBRADO do modelo de cada contato (um so' por lead).
    distribuicao = sortear_modelos(campanha["id"], org_id,
                                   [e["cnpj_completo"] for e in enfileirados], modelos)

    # A primeira rodada sai agora, se der: janela de envio aberta e a campanha
    # nao estar no meio do intervalo de uma fila que ja' corre.
    proxima = campanha.get("proximo_lote_em")
    no_ritmo = proxima is None or proxima <= datetime.now(timezone.utc)
    janela = _janela_de_envio()
    rodada = {"sucessos": 0, "erros": 0}
    if janela["aberta"] and no_ritmo:
        rodada = rodar_fila(campanha)
    confer = rodada.get("conferencia") or {}
    na_fila = resumo_fila(org_id)["na_fila"]
    return {
        "enviados": int(rodada.get("sucessos", 0) or 0),
        "erros": int(rodada.get("erros", 0) or 0),
        "barrados_na_conferencia": int(confer.get("bloqueados", 0) or 0),
        "pedidos": quantidade,
        "enfileirados": len(enfileirados),
        "distribuicao": {str(k): v for k, v in distribuicao.items()},
        "na_fila": na_fila,
        "janela_fechada": not janela["aberta"],
        "remetente": remetente,
        "erro_rodada": rodada.get("erro"),
        "mensagem": None,
    }


@router.post("/enviar")
async def enviar(data: Dict, current_user: Dict = Depends(get_current_user),
                 org_id: int = Depends(get_active_org)):
    """Primeiro contato: os proximos N disponiveis."""
    return _disparar(data, current_user, org_id, "Disparo",
                     lambda cid, org, n: reservar_proximos(cid, org, n, status="na_fila"))


@router.post("/followup")
async def followup(data: Dict, current_user: Dict = Depends(get_current_user),
                   org_id: int = Depends(get_active_org)):
    """Segundo (e ultimo) contato: quem esta 'em trabalho' ha' DIAS_FOLLOWUP
    dias ou mais, sem ter respondido nem pedido para sair."""
    dias = dias_followup_org(org_id)
    return _disparar(data, current_user, org_id, "Follow-up",
                     lambda cid, org, n: reservar_followups(cid, org, n, dias, status="na_fila"))


@router.get("/followup/lista")
async def followup_lista(current_user: Dict = Depends(get_current_user),
                         org_id: int = Depends(get_active_org)):
    _exigir_lista_propria(org_id)
    return listar_followups_devidos(org_id, dias_followup_org(org_id))


@router.post("/fila/avancar")
async def fila_avancar(current_user: Dict = Depends(get_current_user),
                       org_id: int = Depends(get_active_org)):
    """Relogio da tela aberta: roda a rodada desta empresa se ja' estiver na
    hora (a reivindicacao atomica impede rodada dobrada com os outros relogios)."""
    _exigir_lista_propria(org_id)
    avancar_filas(org_id)
    return resumo_fila(org_id)


@router.get("/modelos")
async def modelos_resultado(current_user: Dict = Depends(get_current_user),
                            org_id: int = Depends(get_active_org)):
    """Resultado por modelo de primeiro contato (o teste de abordagens)."""
    _exigir_lista_propria(org_id)
    return metricas_modelos(org_id)


@router.post("/fila/cancelar")
async def fila_cancelar(current_user: Dict = Depends(get_current_user),
                        org_id: int = Depends(get_active_org)):
    """Para o que ainda nao saiu: volta para disponivel (ou devido, no follow-up)."""
    _exigir_lista_propria(org_id)
    return {"canceladas": cancelar_fila(org_id)}


@router.get("/whatsapp")
async def whatsapp_lista(limite: int = 30, eu: str = "", site: str = "todos",
                         current_user: Dict = Depends(get_current_user),
                         org_id: int = Depends(get_active_org)):
    """Quem chamar no WhatsApp (manual): numero e texto prontos, por prioridade.
    site: todos | com (e-mail de dominio da empresa) | sem."""
    _exigir_lista_propria(org_id)
    if site not in FILTROS_SITE:
        raise HTTPException(status_code=400, detail="site deve ser 'todos', 'com' ou 'sem'.")
    limite = max(1, min(int(limite), 100))
    return {
        "faltam": contar_para_chamar(org_id),
        "sites": contar_por_site(org_id),
        "contatos": listar_para_chamar(org_id, limite, eu=(eu or "").strip()[:40], site=site),
    }


@router.get("/contato/buscar")
async def contato_buscar(q: str = "", current_user: Dict = Depends(get_current_user),
                         org_id: int = Depends(get_active_org)):
    """Acha um contato por telefone, CNPJ, nome ou e-mail, para registrar a resposta dele."""
    _exigir_lista_propria(org_id)
    return buscar_contato(org_id, q[:80])


@router.post("/whatsapp/marcar")
async def whatsapp_marcar(data: Dict, current_user: Dict = Depends(get_current_user),
                          org_id: int = Depends(get_active_org)):
    """chamado / sem_whatsapp (tiram da lista). 'respondeu' e 'sem_interesse' usam /situacao."""
    _exigir_lista_propria(org_id)
    cnpj = "".join(ch for ch in str(data.get("cnpj") or "") if ch.isdigit())
    valor = data.get("status")
    if not cnpj:
        raise HTTPException(status_code=400, detail="Informe o CNPJ.")
    if valor is not None and valor not in STATUS_WHATSAPP:
        raise HTTPException(status_code=400, detail="Status deve ser 'chamado' ou 'sem_whatsapp'.")
    marcar_whatsapp(org_id, cnpj, valor, current_user["sub"])
    return {"ok": True}


@router.post("/situacao")
async def situacao(data: Dict, current_user: Dict = Depends(get_current_user),
                   org_id: int = Depends(get_active_org)):
    """Tira (ou devolve) um contato do follow-up: respondeu / sem_interesse."""
    _exigir_lista_propria(org_id)
    cnpj = "".join(ch for ch in str(data.get("cnpj") or "") if ch.isdigit())
    valor = data.get("situacao")
    if not cnpj:
        raise HTTPException(status_code=400, detail="Informe o CNPJ.")
    if valor is not None and valor not in SITUACOES_CONTATO:
        raise HTTPException(status_code=400, detail="Situacao deve ser 'respondeu', 'sem_interesse' ou 'desinteresse_comercial'.")
    marcar_situacao_contato(org_id, cnpj, valor, current_user["sub"])
    return {"ok": True}
