"""WhoDados API Endpoints - Campanhas (e-mail e WhatsApp, em lote ou de uma vez)."""
import logging
import random
import re
import time
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header
from typing import Any, Dict, Optional, List
from .auth import get_current_user, get_active_org
from .config import settings
from .db import (
    create_campanha, get_campanha, get_all_campanhas, update_campanha_status,
    get_template, create_notificacao, listar_empresas_db,
    cnpjs_ja_contatados_campanha, registrar_envio_campanha, contar_envios_campanha,
    listar_campanhas_pendentes, buscar_socios_principais, contar_emails_enviados_hoje,
    contar_emails_enviados_hoje_org, limite_diario_org,
    cnpjs_contatados_org, proximo_bloco_pendente, cnpjs_do_bloco,
    marcar_empresas_do_lote, atualizar_status_bloco, vincular_campanha_ao_lote,
    org_escopo_base, email_esta_descadastrado, complementar_empresas_do_lote,
    puxar_da_fila, devolver_para_fila, campanhas_com_fila, agendar_proximo_lote, assumir_rodada,
)
from .mailer import enviar_campanha, montar_email_para_cnpj, validar_lote
from .mailer.service import _titulo

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)

# Folga entre uma rodada e a proxima, em minutos. Fixa seria um padrao facil de
# reconhecer; o sorteio faz o envio parecer o que e': uma pessoa trabalhando.
INTERVALO_RODADA_MIN = (11.0, 12.0)

_STATUS_EXECUTAVEIS = ("rascunho", "agendada", "em_andamento")


@router.get("/campanhas")
async def listar_campanhas(current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    campanhas = get_all_campanhas(organizacao_id=org_id)
    for c in campanhas:
        if c.get("tamanho_lote"):
            c["ja_contatados"] = contar_envios_campanha(c["id"])
    return campanhas


@router.post("/campanhas")
async def criar_campanha(data: Dict, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    canal = (data.get("canal") or "email").strip()
    if canal != "email":
        raise HTTPException(status_code=400, detail="So' ha' campanha por e-mail (o WhatsApp automatico foi removido)")

    t = get_template(data.get("template_id"), organizacao_id=org_id)
    if not t:
        raise HTTPException(status_code=400, detail="Template nao encontrado")

    tamanho_lote = data.get("tamanho_lote")
    if tamanho_lote is not None:
        tamanho_lote = int(tamanho_lote)
        if tamanho_lote <= 0:
            raise HTTPException(status_code=400, detail="tamanho_lote deve ser maior que zero")

    return create_campanha(
        data.get("nome"), data.get("template_id"), data.get("filtros", {}),
        created_by=current_user.get("sub"), eh_sequencia=data.get("eh_sequencia", False),
        remetente_username=_remetente_valido(data.get("remetente_username"), org_id),
        agendada_para=data.get("agendada_para"), organizacao_id=org_id,
        canal=canal, mensagem=data.get("mensagem"), tamanho_lote=tamanho_lote,
        repetir_ate=data.get("repetir_ate"),
    )


@router.get("/campanhas/{campanha_id}")
async def get_campanha_by_id(campanha_id: int, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    c = get_campanha(campanha_id, organizacao_id=org_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campanha nao encontrada")
    c["ja_contatados"] = contar_envios_campanha(campanha_id)
    return c


def _selecionar_lote(campanha: Dict, org_id: int) -> Dict:
    """Quem entra no proximo lote, e de onde essa lista saiu.

    E' a MESMA selecao usada no disparo -- a previa chama esta funcao pra
    mostrar exatamente o que vai sair, nao uma estimativa parecida.
    """
    # Campanha de lote: publico e a lista fixa do proximo bloco pendente, e
    # o modelo vem do bloco. Sem lote_id, segue pelo filtro (comportamento
    # das campanhas antigas).
    lote_id = campanha.get("lote_id")
    if lote_id:
        canal_lote = campanha.get("canal") or "email"
        bloco = proximo_bloco_pendente(lote_id, canal_lote)
        if not bloco:
            return {"fonte": f"lote {lote_id}", "no_filtro": 0, "ja_contatados": 0,
                    "pendentes": 0, "lote": [], "restantes_depois": 0, "bloco": None}
        linhas = cnpjs_do_bloco(lote_id, canal_lote, bloco["bloco"])
        # A supressao vale aqui tambem: estar num bloco nao autoriza reenvio
        # pra quem ja foi contatado por outra campanha da empresa.
        recontato = (campanha.get("filtros") or {}).get("recontato_dias")
        suprimidos = cnpjs_ja_contatados_campanha(campanha["id"]) | cnpjs_contatados_org(
            org_id, desde_dias=None if recontato in (None, "") else int(recontato))
        # lote_empresas ja guarda e-mail, telefone e razao social.
        todas = [{"cnpj_completo": l["cnpj"], "email": l["email"],
                  "contato_fone": l["telefone"], "razao_social": l["razao_social"]}
                 for l in linhas]
        empresas = [e for e in todas if e["cnpj_completo"] not in suprimidos]
        # O tamanho do lote da campanha vale tambem aqui. Sem isto, "20 por
        # lote" mandava o bloco inteiro (~300) de uma vez: o limite de
        # seguranca do warm-up so' existia no caminho por filtro.
        tamanho_lote = campanha.get("tamanho_lote")
        a_enviar = empresas[:tamanho_lote] if tamanho_lote else empresas
        a_enviar = complementar_empresas_do_lote(org_id, a_enviar)
        return {"fonte": f"lote {lote_id} · bloco {bloco['bloco']}",
                "no_filtro": len(todas), "ja_contatados": len(todas) - len(empresas),
                "pendentes": len(empresas), "lote": a_enviar,
                "restantes_depois": len(empresas) - len(a_enviar), "bloco": bloco}

    filtros = campanha.get("filtros") or {}
    ja_contatados = cnpjs_ja_contatados_campanha(campanha["id"])

    # Supressao global. filtros.recontato_dias libera recontato apos N dias.
    recontato_dias = filtros.get("recontato_dias")
    ja_contatados |= cnpjs_contatados_org(
        org_id, desde_dias=None if recontato_dias in (None, "") else int(recontato_dias)
    )

    # Passa o filtro INTEIRO. Antes so ia cidade/cnae/porte/busca/divida_min:
    # uma campanha feita a partir de um lote com capital minimo ou data de
    # fundacao disparava pra um conjunto maior do que o lote mostrava.
    empresas = listar_empresas_db(
        cidade=filtros.get("cidade"), cnae=filtros.get("cnae"), porte=filtros.get("porte"),
        busca=filtros.get("busca"),
        divida_min=filtros.get("divida_min"), divida_max=filtros.get("divida_max"),
        capital_min=filtros.get("capital_min"), capital_max=filtros.get("capital_max"),
        fundacao_de=filtros.get("fundacao_de"), fundacao_ate=filtros.get("fundacao_ate"),
        incluir_inativas=filtros.get("incluir_inativas", False),
        contato=filtros.get("contato"),
        potencial=filtros.get("potencial"), categoria=filtros.get("categoria"),
        limit=100000, offset=0, organizacao_id=org_id,
    )
    pendentes = [e for e in empresas if e.get("cnpj_completo") and e["cnpj_completo"] not in ja_contatados]
    tamanho_lote = campanha.get("tamanho_lote")
    lote = pendentes[:tamanho_lote] if tamanho_lote else pendentes
    return {
        "fonte": "carteira" if org_escopo_base(org_id) == "carteira" else "Receita Federal",
        "no_filtro": len(empresas),
        "ja_contatados": len(empresas) - len(pendentes),
        "pendentes": len(pendentes),
        "lote": lote,
        "restantes_depois": max(len(pendentes) - len(lote), 0),
    }


@router.get("/campanhas/{campanha_id}/previa")
async def previa_do_lote(campanha_id: int, current_user: Dict = Depends(get_current_user),
                         org_id: int = Depends(get_active_org)):
    """De onde vem a carga e o que realmente vai sair no proximo disparo.

    Existe porque "mandar a campanha" escondia decisoes que mudam muito o
    resultado: quanta gente do filtro nem tem e-mail, quantos ja' foram
    contatados, quantos pediram descadastro, e quantos endereços sao
    repetidos (o mesmo e-mail de contabilidade responde por dezenas de
    empresas na base da Receita -- disparar pros dois e' o mesmo destinatario
    recebendo duas vezes).
    """
    campanha = get_campanha(campanha_id, organizacao_id=org_id)
    if not campanha:
        raise HTTPException(status_code=404, detail="Campanha nao encontrada")

    sel = _selecionar_lote(campanha, org_id)
    lote = sel.pop("lote")

    com_email, sem_email_com_fone, sem_contato, descadastrados = [], 0, 0, 0
    vistos: Dict[str, int] = {}
    for e in lote:
        email = (e.get("email") or "").strip().lower()
        if email and "@" in email:
            if email_esta_descadastrado(email):
                descadastrados += 1
                continue
            vistos[email] = vistos.get(email, 0) + 1
            com_email.append({
                "cnpj": e.get("cnpj_completo"), "razao_social": e.get("razao_social"),
                "municipio": e.get("municipio"), "email": email,
            })
        elif (e.get("contato_fone") or "").strip(" ()-"):
            sem_email_com_fone += 1
        else:
            sem_contato += 1

    repetidos = sum(n - 1 for n in vistos.values() if n > 1)
    return {
        **sel,
        "no_lote": len(lote),
        "vao_receber": len(com_email),
        "enderecos_distintos": len(vistos),
        "repetidos_no_lote": repetidos,
        "sem_email_viram_ligacao": sem_email_com_fone,
        "sem_nenhum_contato": sem_contato,
        "descadastrados_lgpd": descadastrados,
        "amostra": com_email[:10],
    }


def _janela_de_envio() -> Dict[str, Any]:
    """Se agora esta dentro da janela de envio, no fuso do negocio."""
    try:
        from zoneinfo import ZoneInfo
        agora = datetime.now(ZoneInfo(getattr(settings, "ENVIO_TIMEZONE", "America/Sao_Paulo")))
    except Exception:
        agora = datetime.now(timezone.utc)

    dias = {int(d) for d in str(getattr(settings, "ENVIO_DIAS_SEMANA", "1,2,3,4,5")).split(",") if d.strip()}
    if agora.isoweekday() not in dias:
        return {"aberta": False, "motivo": f"fora dos dias de envio ({agora:%A})"}

    def minutos(hhmm: str, padrao: int) -> int:
        try:
            h, m = str(hhmm).split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return padrao

    inicio = minutos(getattr(settings, "ENVIO_JANELA_INICIO", "07:00"), 7 * 60)
    fim = minutos(getattr(settings, "ENVIO_JANELA_FIM", "19:30"), 19 * 60 + 30)
    atual = agora.hour * 60 + agora.minute
    if not (inicio <= atual <= fim):
        return {"aberta": False,
                "motivo": f"fora da janela ({agora:%H:%M} nao esta entre "
                          f"{getattr(settings, 'ENVIO_JANELA_INICIO', '07:00')} e "
                          f"{getattr(settings, 'ENVIO_JANELA_FIM', '19:30')})"}
    agora_min = agora.hour * 60 + agora.minute
    return {"aberta": True, "agora": agora.strftime("%Y-%m-%d %H:%M %Z"),
            # quanto ainda cabe de envio hoje, em minutos -- e' o que permite
            # calcular o ritmo sem ninguem configurar nada
            "minutos_restantes": max(fim - agora_min, 0)}


def _remetente_valido(username: Optional[str], org_id: int) -> Optional[str]:
    """Aceita o username so' se ele tiver acesso a esta empresa.

    Sem isto, mandar `remetente_username` de alguem de outro cliente faria a
    campanha sair assinada por ele. Username sem acesso vira None (padrao),
    e nao erro: a
    campanha nasce valida, so' sem remetente individual.
    """
    username = (username or "").strip()
    if not username:
        return None
    from .db import usuario_tem_acesso_org
    return username if usuario_tem_acesso_org(username, org_id) else None


def _orcamento_email_hoje(org_id: Optional[int] = None) -> Optional[int]:
    """Quantos e-mails ainda cabem hoje. None = sem checagem.

    Dois tetos, e vale o MENOR:

    - o da conta (`EMAIL_LIMITE_DIARIO`), que e' do provedor e e' compartilhado
      por todas as empresas;
    - o da empresa (`organizacoes.email_limite_diario`), opcional, que existe
      pro warm-up de um cliente novo nao obrigar a frear os outros.

    Sem `org_id` devolve so' o teto da conta -- e' o que o disparo manual de
    uma campanha usava, e continua valendo.
    """
    padrao = int(getattr(settings, "EMAIL_LIMITE_DIARIO", 0) or 0)

    if org_id is None:
        # Rotina sem empresa (disparo manual antigo): so' resta o padrao, e
        # ai a contagem e' geral mesmo, por falta de coisa melhor.
        return max(padrao - contar_emails_enviados_hoje(), 0) if padrao > 0 else None

    limite = limite_diario_org(org_id) or padrao
    if limite <= 0:
        return None
    # Conta SO' os envios desta empresa: cada uma manda pelo Gmail dela, com
    # cota propria no Google. O que a Beta envia nao tira nada da Alfa.
    return max(limite - contar_emails_enviados_hoje_org(org_id), 0)


def _executar_um_lote(campanha: Dict, current_user: Dict, org_id: int,
                      max_envios: Optional[int] = None) -> Dict:
    """Manda o proximo lote (ou a campanha inteira, se tamanho_lote nao
    estiver definido -- comportamento antigo preservado). Pode ser chamado
    repetidas vezes: cada chamada avanca sobre quem ainda nao foi
    contatado por essa campanha. Marca 'concluida' quando o filtro inteiro
    ja foi coberto, ou 'em_andamento' quando ainda falta gente."""
    campanha_id = campanha["id"]
    canal = campanha.get("canal") or "email"
    if canal != "email":
        # Campanha antiga de WhatsApp (Twilio, removido): nao manda nada.
        raise HTTPException(status_code=400, detail="Campanha de WhatsApp nao pode mais ser executada")

    sel = _selecionar_lote(campanha, org_id)
    lote = sel["lote"]
    pendentes_total = sel["pendentes"]

    if not lote:
        update_campanha_status(campanha_id, "concluida", concluida_em=datetime.now(timezone.utc))
        return {"sucessos": 0, "erros": 0, "restantes": 0, "status": "concluida"}

    # Teto diario do provedor.
    if max_envios is not None:
        if max_envios <= 0:
            return {"sucessos": 0, "erros": 0, "restantes": pendentes_total,
                    "status": campanha.get("status") or "em_andamento",
                    "adiado_por_limite": True}
        lote = lote[:max_envios]

    bloco = sel.get("bloco")
    campanha_efetiva = dict(campanha)
    if bloco and bloco.get("template_id"):
        campanha_efetiva["template_id"] = bloco["template_id"]

    # O remetente da campanha manda mais que quem disparou: no automatico
    # quem dispara e' o cron, que nao tem e-mail proprio e cairia no
    # endereco da empresa. Com ele definido, a campanha de cada pessoa
    # sai do endereco dela mesmo sem ninguem logado.
    resultado = _enviar_lote_email(campanha_id, lote, campanha_efetiva, org_id,
                                   remetente=(campanha.get("remetente_username")
                                              or current_user.get("sub")))

    lote_id = campanha.get("lote_id")
    mais_blocos = False
    if lote_id and bloco:
        marcar_empresas_do_lote(lote_id, [e["cnpj_completo"] for e in lote])
        # O bloco so' fecha quando todo mundo dele foi atendido. Lote menor
        # que o bloco (tamanho_lote, ou o teto do dia) deixa o resto pro
        # proximo disparo; marcar como enviado aqui largava essa gente pra
        # sempre, sem nunca ter sido contatada.
        if len(lote) >= pendentes_total:
            restam = proximo_bloco_pendente(lote_id, bloco["canal"])
            mais_blocos = bool(restam)
            atualizar_status_bloco(lote_id, bloco["canal"], bloco["bloco"], "enviado")
            if not restam:
                update_campanha_status(campanha_id, "concluida",
                                       concluida_em=datetime.now(timezone.utc))

    restantes = pendentes_total - len(lote)
    # Campanha de lote so' conclui quando nao sobra bloco: terminar o primeiro
    # bloco nao e' terminar a campanha.
    novo_status = "em_andamento" if (restantes > 0 or mais_blocos) else "concluida"
    update_campanha_status(
        campanha_id, novo_status,
        ultimo_lote_em=datetime.now(timezone.utc),
        **({"concluida_em": datetime.now(timezone.utc)} if novo_status == "concluida" else {}),
    )
    create_notificacao(
        "campanha_lote_concluido" if novo_status == "em_andamento" else "campanha_concluida",
        f"Campanha {campanha['nome']}: lote enviado",
        f"Enviados: {resultado.get('sucessos', 0)} | Erros: {resultado.get('erros', 0)} | Restam: {restantes}",
        # user_id=None (em vez do usuario que clicou) -- assim a notificacao
        # aparece pra todo mundo da organizacao, nao so pra quem executou.
        # Necessario tambem pro lote automatico via cron, que nao tem um
        # usuario de verdade por tras do clique.
        organizacao_id=org_id,
    )
    resultado["restantes"] = restantes
    resultado["status"] = novo_status
    return resultado


def _enviar_lote_email(campanha_id: int, empresas: list, campanha: Dict, org_id: int,
                       remetente: Optional[str] = None) -> Dict:
    """remetente: quem disparou. O e-mail e' individual -- sai do endereco
    e com a assinatura da pessoa, pelo servidor da empresa."""
    template = get_template(campanha["template_id"], organizacao_id=org_id)
    emails_por_cnpj, sem_email_com_fone = {}, []
    for e in empresas:
        cnpj = e["cnpj_completo"]
        email = (e.get("email") or "").strip()
        if email and "@" in email:
            emails_por_cnpj[cnpj] = email
        elif (e.get("contato_fone") or "").strip(" ()-"):
            sem_email_com_fone.append(e)

    _LIMITE_LIGAR = 100
    for e in sem_email_com_fone[:_LIMITE_LIGAR]:
        create_notificacao(
            "ligar", f"Ligar: {e.get('razao_social') or e['cnpj_completo']}",
            f"Sem e-mail. Telefone: {(e.get('contato_fone') or '').strip()} | {e.get('municipio', '')}",
            cnpj=e["cnpj_completo"], organizacao_id=org_id,
        )
        registrar_envio_campanha(campanha_id, e["cnpj_completo"], "email", status="sem_email_ligar")

    # Nome do socio responsavel de cada empresa -- permite personalizar a
    # saudacao com o nome de uma pessoa em vez de so' a razao social.
    basicos_por_cnpj = {e["cnpj_completo"]: e["cnpj_completo"][:8] for e in empresas if e.get("cnpj_completo")}
    socios_por_basico = buscar_socios_principais(list(set(basicos_por_cnpj.values())))

    dados_empresas = {
        e["cnpj_completo"]: {
            "razao_social": e.get("razao_social", ""), "nome_fantasia": e.get("nome_fantasia", ""),
            "municipio": e.get("municipio", ""), "cnae_principal": e.get("cnae_principal", ""),
            "cnae_descricao": e.get("cnae_descricao", ""),
            "porte_nome": e.get("porte_nome", ""),
            "nome_socio": socios_por_basico.get(basicos_por_cnpj.get(e["cnpj_completo"]), ""),
        }
        for e in empresas if e.get("cnpj_completo")
    }
    # Confere o texto ja montado; reprovado fica registrado e nao e enviado.
    montados = []
    texto_modelo = " ".join(str(template.get(k) or "") for k in ("assunto", "corpo_html", "corpo_texto"))
    exige_cidade = "{{cidade}}" in texto_modelo
    for cnpj, email in emails_por_cnpj.items():
        m = montar_email_para_cnpj(template, cnpj, email,
                                   dados_empresas.get(cnpj, {}), org_id, remetente)
        montados.append({
            "cnpj": cnpj,
            "email": email,
            "cidade": m["variaveis"].get("cidade", ""),
            "exige_cidade": exige_cidade,
            "saudacao": m["variaveis"].get("saudacao", ""),
            "assunto": m["assunto"],
            "corpo_texto": m["corpo_texto"],
            "corpo_html": m["corpo_html"],
        })
    conferencia = validar_lote(montados)
    for cnpj in conferencia["cnpjs_bloqueados"]:
        registrar_envio_campanha(campanha_id, cnpj, "email", status="bloqueado_conferencia")
        emails_por_cnpj.pop(cnpj, None)

    # Descadastrado nao recebe e nao deve voltar para a fila.
    for cnpj, email in list(emails_por_cnpj.items()):
        if email_esta_descadastrado(email):
            registrar_envio_campanha(campanha_id, cnpj, "email", status="descadastrado")
            emails_por_cnpj.pop(cnpj, None)

    cnpjs = list(emails_por_cnpj.keys())
    resultado = enviar_campanha(campanha_id, template, cnpjs, emails_por_cnpj, dados_empresas, organizacao_id=org_id, remetente=remetente) \
        if cnpjs else {"sucessos": 0, "erros": 0}
    # So' conta como contatado quem saiu de verdade. Antes todos viravam
    # 'enviado' mesmo com a Gmail API recusando: o contato saia da fila sem
    # nunca ter recebido nada.
    saiu = {e["cnpj"] for e in resultado.get("enviados", [])}
    for cnpj in cnpjs:
        registrar_envio_campanha(campanha_id, cnpj, "email",
                                 status="enviado" if cnpj in saiu else "erro_envio")
    resultado["conferencia"] = conferencia
    return resultado


@router.post("/campanhas/{campanha_id}/executar")
async def executar_campanha(campanha_id: int, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    campanha = get_campanha(campanha_id, organizacao_id=org_id)
    if not campanha:
        raise HTTPException(status_code=404, detail="Campanha nao encontrada")
    if campanha.get("status") not in _STATUS_EXECUTAVEIS:
        raise HTTPException(status_code=400, detail="Campanha ja concluida")
    # O teto da empresa entra aqui como no agendador: so' o da conta deixava
    # o warm-up de uma empresa nova furar o proprio limite no clique manual.
    return _executar_um_lote(campanha, current_user, org_id,
                             max_envios=_orcamento_email_hoje(org_id))


# Mesmo com muita cota, nunca mais que isto de uma vez: o que marca spam nao
# e' o total do dia, e' a rajada.
TETO_RODADA = 60


def _por_rodada(org_id: Optional[int], restante: Optional[int]) -> int:
    """Quantos mandar nesta rodada, a partir do limite DA EMPRESA.

    Divide o que ainda cabe hoje pelas rodadas que ainda cabem na janela.
    Assim o teto diario e' o unico numero a configurar: o ritmo se ajusta,
    e uma rodada perdida e' compensada nas seguintes (a conta usa o que
    resta, nao o total).

    Sem teto diario, cai no ENVIO_POR_RODADA de antes.
    """
    padrao = int(getattr(settings, "ENVIO_POR_RODADA", 10) or 10)
    if not restante:
        return padrao

    janela = _janela_de_envio()
    minutos_restantes = janela.get("minutos_restantes")
    if not minutos_restantes:
        return padrao

    intervalo = sum(INTERVALO_RODADA_MIN) / 2.0
    rodadas = max(int(minutos_restantes // intervalo), 1)
    preciso = -(-restante // rodadas)   # divisao arredondando pra cima
    # Nunca MAIS LENTO que o padrao: quando o que resta e' pouco, dividir
    # por 65 rodadas espalharia 4 e-mails pelo dia inteiro sem ganho nenhum.
    # O ritmo so' acelera; a cota do dia ja' limita o total.
    return min(TETO_RODADA, max(padrao, preciso))


def rodar_fila(campanha: Dict) -> Dict:
    """UMA rodada da fila do Disparar/Follow-up: ate' ENVIO_POR_RODADA
    contatos, respeitando o que ainda cabe hoje na empresa, e agenda a proxima
    para daqui a 11-12 minutos. Chamada pelo agendador e, na primeira rodada,
    pelo proprio clique -- por isso mora aqui e nao no endpoint do Disparar."""
    campanha_id, org = campanha["id"], campanha["organizacao_id"]
    cota = _orcamento_email_hoje(org)
    por_rodada = _por_rodada(org, cota)
    n = por_rodada if cota is None else min(por_rodada, cota)
    if n <= 0:
        agendar_proximo_lote(campanha_id, 30)   # teto do dia: tenta de novo mais tarde
        return {"sucessos": 0, "erros": 0, "adiado_por_limite": True}

    # Quem chega primeiro leva a rodada e ja' marca a proxima (11-12 min). Quem
    # chega depois (outro relogio, outra aba) volta de maos vazias.
    if not assumir_rodada(campanha_id, random.uniform(*INTERVALO_RODADA_MIN)):
        return {"sucessos": 0, "erros": 0, "pulou": True}

    lote = puxar_da_fila(campanha_id, n)
    if not lote:
        return {"sucessos": 0, "erros": 0}
    cnpjs = [e["cnpj_completo"] for e in lote]
    # Cada contato tem o modelo SORTEADO na hora de entrar na fila; contato
    # antigo (sem sorteio) segue no modelo da propria campanha.
    grupos: Dict[Any, list] = {}
    for e in lote:
        grupos.setdefault(e.get("template_id") or campanha["template_id"], []).append(e)
    try:
        sucessos = erros = bloqueados = total_conf = 0
        for tid, grupo in grupos.items():
            parcial = _enviar_lote_email(campanha_id, grupo, {**campanha, "template_id": tid}, org,
                                         remetente=campanha.get("remetente_username"))
            sucessos += int(parcial.get("sucessos", 0) or 0)
            erros += int(parcial.get("erros", 0) or 0)
            conf = parcial.get("conferencia") or {}
            bloqueados += int(conf.get("bloqueados", 0) or 0)
            total_conf += int(conf.get("total", 0) or 0)
        r = {"sucessos": sucessos, "erros": erros,
             "conferencia": {"bloqueados": bloqueados, "total": total_conf}}
    except Exception as e:
        # Rodada inteira falhou: ninguem foi contatado, todos voltam para a fila.
        logger.exception("Rodada da fila falhou (campanha %s)", campanha_id)
        devolver_para_fila(campanha_id, cnpjs)
        agendar_proximo_lote(campanha_id, 15)
        return {"sucessos": 0, "erros": len(cnpjs), "erro": str(e)}

    devolver_para_fila(campanha_id, cnpjs)      # so' mexe em quem ficou 'reservado'
    return {"sucessos": int(r.get("sucessos", 0) or 0), "erros": int(r.get("erros", 0) or 0),
            "conferencia": r.get("conferencia")}


def avancar_filas(organizacao_id: Optional[int] = None) -> List[Dict]:
    """Roda a rodada de toda fila que ja' esta' na hora. Fora do horario de
    envio nao faz nada. E' o que os tres relogios chamam: o laco interno do
    servidor, o agendador do GitHub e a tela Disparar aberta."""
    if not _janela_de_envio()["aberta"]:
        return []
    resultados = []
    for campanha in campanhas_com_fila(organizacao_id):
        try:
            r = rodar_fila(campanha)
        except Exception as e:
            logger.exception("Fila falhou (campanha %s)", campanha.get("id"))
            r = {"erro": str(e)}
        resultados.append({"campanha_id": campanha["id"], "nome": campanha["nome"], "fila": True, **r})
    return resultados


@router.post("/campanhas/{campanha_id}/pausar")
async def pausar_campanha(campanha_id: int, current_user: Dict = Depends(get_current_user),
                          org_id: int = Depends(get_active_org)):
    """Tira a campanha da fila sem apagar o historico de contatados."""
    campanha = get_campanha(campanha_id, organizacao_id=org_id)
    if not campanha:
        raise HTTPException(status_code=404, detail="Campanha nao encontrada")
    if campanha.get("status") == "concluida":
        raise HTTPException(status_code=400, detail="Campanha ja concluida")
    update_campanha_status(campanha_id, "pausada")
    return {"ok": True, "status": "pausada"}


@router.post("/campanhas/{campanha_id}/retomar")
async def retomar_campanha(campanha_id: int, current_user: Dict = Depends(get_current_user),
                           org_id: int = Depends(get_active_org)):
    """Devolve a campanha para a fila."""
    campanha = get_campanha(campanha_id, organizacao_id=org_id)
    if not campanha:
        raise HTTPException(status_code=404, detail="Campanha nao encontrada")
    if campanha.get("status") != "pausada":
        raise HTTPException(status_code=400, detail="Campanha nao esta pausada")
    novo = "em_andamento" if campanha.get("ultimo_lote_em") else "agendada"
    update_campanha_status(campanha_id, novo)
    return {"ok": True, "status": novo}


@router.post("/campanhas/executar-pendentes")
async def executar_campanhas_pendentes(x_cron_secret: Optional[str] = Header(None)):
    """Avanca um lote de cada campanha agendada/em andamento que ainda nao
    rodou hoje. Feito pra ser chamado 1x/dia por um cron externo (GitHub
    Actions) -- o Render free hiberna quando ocioso, entao um scheduler
    dentro do proprio processo nao e' confiavel; um cron batendo aqui de
    fora e' o mesmo padrao ja usado pelo ETL neste repo.

    Protegido por CRON_SECRET (nao pelo login normal, o cron nao tem
    usuario) -- sem o secret configurado, o endpoint fica desligado."""
    secret_esperado = getattr(settings, "CRON_SECRET", "") or ""
    if not secret_esperado or x_cron_secret != secret_esperado:
        raise HTTPException(status_code=403, detail="CRON_SECRET invalido ou nao configurado")

    janela = _janela_de_envio()
    if not janela["aberta"]:
        return {"processadas": 0, "janela": janela, "resultados": []}

    # Orcamento do dia e' da conta inteira, nao por campanha.
    orcamento = _orcamento_email_hoje()
    orcamento_inicial = orcamento

    # Teto da rodada, para nao gastar o orcamento do dia de uma vez.
    por_rodada = int(getattr(settings, "ENVIO_POR_RODADA", 10) or 0)
    if por_rodada > 0:
        orcamento = por_rodada if orcamento is None else min(orcamento, por_rodada)

    resultados = []
    for campanha in listar_campanhas_pendentes():
        try:
            # O teto da empresa entra AQUI, e nao no orcamento do dia: cada
            # campanha e' de uma empresa, e o warm-up de uma nao pode comer a
            # cota da outra. Vale o menor entre o que resta da conta, o teto
            # desta empresa e o teto da rodada.
            org_da_campanha = campanha.get("organizacao_id")
            cota = _orcamento_email_hoje(org_da_campanha)
            limites = [v for v in (orcamento, cota) if v is not None]
            max_envios = min(limites) if limites else None
            r = _executar_um_lote(campanha, {"sub": "cron"}, org_da_campanha,
                                  max_envios=max_envios)
            if orcamento is not None and (campanha.get("canal") or "email") == "email":
                orcamento = max(orcamento - int(r.get("sucessos", 0) or 0), 0)
            resultados.append({"campanha_id": campanha["id"], "nome": campanha["nome"], **r})
        except Exception as e:
            resultados.append({"campanha_id": campanha["id"], "nome": campanha["nome"], "erro": str(e)})
    # Fila do Disparar/Follow-up: 10 por rodada, uma rodada a cada ~11-12 min.
    resultados.extend(avancar_filas())
    return {
        "processadas": len(resultados),
        "janela": janela,
        "limite_diario": int(getattr(settings, "EMAIL_LIMITE_DIARIO", 0) or 0),
        "por_rodada": por_rodada,
        "orcamento_dia_inicial": orcamento_inicial,
        "orcamento_rodada_restante": orcamento,
        "resultados": resultados,
    }


@router.put("/campanhas/{campanha_id}/lote")
async def redirecionar_campanha(campanha_id: int, data: Dict,
                                current_user: Dict = Depends(get_current_user),
                                org_id: int = Depends(get_active_org)):
    """Aponta uma campanha existente para outro lote.

    Nao mexe em quem ja foi contatado: o historico e por campanha, entao
    trocar o lote muda o publico dali pra frente, nao o que ja saiu.
    """
    campanha = get_campanha(campanha_id, organizacao_id=org_id)
    if not campanha:
        raise HTTPException(status_code=404, detail="Campanha nao encontrada")

    lote_id = data.get("lote_id")
    if lote_id in (None, ""):
        vincular_campanha_ao_lote(campanha_id, None)
        return {"ok": True, "lote_id": None, "fonte": "filtro salvo na campanha"}

    from .db import get_lote_db
    lote = get_lote_db(int(lote_id), organizacao_id=org_id)
    if not lote:
        raise HTTPException(status_code=404, detail="Lote nao encontrado")

    vincular_campanha_ao_lote(campanha_id, int(lote_id))
    if campanha.get("status") == "concluida":
        update_campanha_status(campanha_id, "agendada")
    return {"ok": True, "lote_id": int(lote_id), "lote": lote["nome"]}


@router.put("/campanhas/{campanha_id}/remetente")
async def definir_remetente(campanha_id: int, data: Dict,
                            current_user: Dict = Depends(get_current_user),
                            org_id: int = Depends(get_active_org)):
    """De quem sai o e-mail desta campanha. `remetente_username` vazio volta
    ao padrao (quem dispara, ou a empresa).

    Quem nao tem remetente proprio cadastrado em Meu E-mail nao passa pelo
    guard de `enviar_email` -- a campanha simplesmente nao envia, em vez de
    sair assinada por outro. Por isso a pessoa precisa preencher o endereco
    dela antes de a campanha dela rodar.
    """
    from .db import definir_remetente_campanha
    username = (data.get("remetente_username") or "").strip() or None
    if not definir_remetente_campanha(campanha_id, org_id, username):
        raise HTTPException(
            status_code=400,
            detail="Campanha nao encontrada nesta empresa, ou usuario sem acesso a ela")
    return {"campanha_id": campanha_id, "remetente_username": username}
