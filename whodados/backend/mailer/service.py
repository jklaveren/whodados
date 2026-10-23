"""Mailer Service - WhoDados."""
from __future__ import annotations
import re as _re_nome
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid

from . import gmail_api
from ..titular import sem_documento, titular
from .rastreamento import injetar as injetar_rastreamento
from typing import Dict, Optional, List, Any

try:
    from ..config import settings
except ImportError:
    import os
    class _S:
        SMTP_HOST = os.getenv("SMTP_HOST", "")
        SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
        SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
        SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
        SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
        EMAIL_FROM = os.getenv("EMAIL_FROM", "noreply@whodados.com")
        EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "WhoDados")
    settings = _S()

try:
    from ..logger import get_logger
    from ..db.service import create_email_enviado, update_email_enviado, update_campanha_status, get_template, get_templates_by_categoria
    from ..classifier import classificar_cnae
except ImportError:
    import logging
    get_logger = lambda x: logging.getLogger(x)
    def noop(*a, **k): pass
    update_campanha_status = noop
    create_email_enviado = noop
    update_email_enviado = noop
    get_template = noop
    get_templates_by_categoria = noop
    def classificar_cnae(x): return "servicos"

log = get_logger(__name__)

# Temas por categoria CNAE (usados como variavel {{tema}})
CATEGORIA_TEMAS = {
    "tecnologia": "transformacao digital e inovacao tecnologica",
    "comercio": "otimizacao de vendas e gestao comercial",
    "industria": "gestao industrial e eficiencia operacional",
    "servicos": "gestao de servicos e crescimento de mercado",
    "todos": "inteligencia comercial e oportunidades de negocio",
}
CATEGORIA_DESCRICOES = {
    "tecnologia": "solucoes em tecnologia e inovacao",
    "comercio": "otimizacao para comercio e varejo",
    "industria": "solucoes para industria e construcao",
    "servicos": "gestao de servicos e mercado",
    "todos": "solucoes de negocio",
}

# Nome apresentavel para a saudacao. A razao social da RF vem em CAIXA ALTA
# com marcador societario e situacao cadastral; firma individual traz o CNPJ
# na frente do nome da pessoa.
_SAUDACAO_MAX_PALAVRAS = 3
_MINUSC = {"da", "de", "do", "das", "dos", "e", "di", "du", "van", "von", "del", "la"}
# No corpo dos templates o travessao costuma ser digitado como "--" (habito
# do codigo daqui). No e-mail renderizado isso sai como dois tracos soltos
# no meio da frase. So' "--" entre espacos vira travessao: "---" em linha
# propria e' separador de assinatura e fica como esta.
_TRACO_SOLTO = _re_nome.compile(r"(?<= )--(?= )")
_ROMANOS = _re_nome.compile(
    r"^(?=[MDCLXVI]+$)M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$", _re_nome.I)
# Corta no PRIMEIRO marcador societario: o que vem depois e' ruido de
# registro, nunca o nome pelo qual a empresa e' conhecida.
_CORTE_RAZAO = _re_nome.compile(
    r"\s*[-,]?\s*\b(LTDA|LIMITADA|ME|EPP|EIRELI|S\.?\s?A\.?|SS|SCP|SPE|MEI|"
    r"EM\s+RECUPERACAO\s+JUDICIAL|EM\s+LIQUIDACAO|MASSA\s+FALIDA)\b", _re_nome.I)


def _titulo(nome: str) -> str:
    """CAIXA ALTA -> Capitalizado, preservando preposicao e algarismo romano."""
    saida = []
    for i, palavra in enumerate((nome or "").split()):
        minuscula = palavra.lower()
        if len(palavra) > 1 and _ROMANOS.match(palavra):
            saida.append(palavra.upper())
        elif i and minuscula in _MINUSC:
            saida.append(minuscula)
        else:
            saida.append(minuscula.capitalize())
    return " ".join(saida).strip()


def _nome_apresentavel(nome: Optional[str], max_palavras: int = 0) -> str:
    """Nome de empresa sem marcador societario nem sufixo de situacao.

    max_palavras > 0 encurta para caber numa saudacao: "FUNDO MUNICIPAL DE
    DIREITOS DO IDOSO" inteiro num "Oi, ...!" fica pior que o nome curto.
    Preposicao solta no fim e' removida ("Fundo Municipal de" -> "Fundo
    Municipal").
    """
    # Firma individual traz CNPJ ou CPF colado no nome; documento nao e'
    # nome de empresa e nao vai para o corpo do e-mail.
    texto = sem_documento(nome)
    corte = _CORTE_RAZAO.search(texto)
    if corte:
        texto = texto[:corte.start()]
    limpo = _titulo(texto.strip(" -,."))
    if max_palavras > 0:
        palavras = limpo.split()[:max_palavras]
        while palavras and palavras[-1].lower() in _MINUSC:
            palavras.pop()
        limpo = " ".join(palavras)
    return limpo


def _saudacao(nome_socio: Optional[str], razao_social: Optional[str],
              nome_fantasia: Optional[str]) -> str:
    """Pessoa vira primeiro nome; empresa usa o nome curto inteiro."""
    if (nome_socio or "").strip():
        primeiro = _titulo(nome_socio).split()
        if primeiro:
            return primeiro[0]
    pessoa = _titulo(titular(razao_social)).split()
    if pessoa:
        return pessoa[0]
    return (_nome_apresentavel(nome_fantasia, _SAUDACAO_MAX_PALAVRAS)
            or _nome_apresentavel(razao_social, _SAUDACAO_MAX_PALAVRAS))


def _descricao_cnae_fallback(cnae: Optional[str], descricao_informada: Optional[str] = None) -> str:
    """Descricao do CNAE sem nunca vazar o numero cru no texto.

    Se a descricao ja veio da query (JOIN com cnaes), usa ela. Senao tenta
    buscar na tabela cnaes. Se nao achar, retorna "" — nunca o codigo
    numerico, que era o bug que fazia o template mostrar "6201-5/01"
    no meio da frase.
    """
    if (descricao_informada or "").strip():
        return descricao_informada.strip()
    if not (cnae or "").strip():
        return ""
    try:
        from ..db.service import get_db_cursor  # import local p/ evitar ciclo
        with get_db_cursor() as cur:
            cur.execute("SELECT descricao_cnae FROM cnaes WHERE codigo_cnae = %s LIMIT 1", (cnae.strip(),))
            row = cur.fetchone()
            if row and row.get("descricao_cnae"):
                return row["descricao_cnae"]
    except Exception:
        pass
    return ""


def _render_template(template: Dict, vars_dict: Dict[str, str]) -> Dict[str, str]:
    """Substitui {{variavel}} no assunto, corpo_html e corpo_texto."""
    resultado = {}
    for campo in ("assunto", "corpo_html", "corpo_texto"):
        texto = template.get(campo, "")
        if not texto:
            resultado[campo] = ""
            continue
        for key, val in vars_dict.items():
            texto = texto.replace("{{" + key + "}}", str(val))
        resultado[campo] = _TRACO_SOLTO.sub("—", texto)
    return resultado


def _obter_template_para_cnpj(template_base_id: int, cnae: Optional[str]) -> Dict[str, str]:
    """Template que a campanha vai usar para este CNPJ.

    Antes, esta funcao trocava o template escolhido por OUTRO da mesma
    categoria CNAE (a condicao era literalmente id != template_base_id) --
    quem montava a campanha escolhia um template e recebia outro, sem
    aviso. Agora o template escolhido e' respeitado sempre; variar texto
    por setor se faz com uma campanha por setor, que e' explicito e
    visivel em vez de acontecer por baixo dos panos."""
    base = get_template(template_base_id)
    return dict(base) if base else {}

def _smtp_efetivo(organizacao_id: Optional[int], remetente: Optional[str] = None) -> Dict[str, Any]:
    """Config SMTP que vai ser usada no envio.

    E-mail e' individual: o remetente (endereco e nome) e' de quem dispara,
    nao da empresa. Na pratica so' isso costuma mudar -- o servidor continua
    sendo o da empresa -- entao a config do usuario e' aplicada POR CIMA da
    config da empresa, campo a campo. Quem tiver servidor proprio tambem
    pode sobrescrever host/porta/usuario/senha.

    remetente=None (rotina automatica, sem pessoa por tras) usa a config da
    empresa, que e' o comportamento certo pra e-mail do sistema.
    """
    base = _smtp_da_org(organizacao_id)
    if not remetente or organizacao_id is None:
        return base
    try:
        from ..db.service import get_usuario_smtp_config
        meu = get_usuario_smtp_config(remetente, organizacao_id, incluir_password=True)
    except Exception as e:
        log.warning(f"Falha lendo e-mail individual de {remetente}: {e}")
        return base
    if not meu:
        return base

    cfg = dict(base)
    # Servidor proprio so' vale inteiro: host sem a senha correspondente
    # tentaria autenticar no servidor novo com a credencial da empresa.
    if meu.get("smtp_host") and meu.get("smtp_username") and meu.get("smtp_password"):
        cfg.update({
            "host": meu["smtp_host"],
            "port": meu.get("smtp_port") or cfg.get("port") or 587,
            "username": meu["smtp_username"],
            "password": meu["smtp_password"],
            "use_tls": meu["smtp_use_tls"] if meu.get("smtp_use_tls") is not None else cfg.get("use_tls", True),
        })
    if meu.get("gmail_refresh_token"):
        # A conta conectada da pessoa manda no lugar da conta da empresa.
        cfg["gmail_refresh_token"] = meu["gmail_refresh_token"]
    if meu.get("email_from"):
        cfg["email_from"] = meu["email_from"]
    if meu.get("email_from_name"):
        cfg["email_from_name"] = meu["email_from_name"]
    return cfg


def _smtp_da_org(organizacao_id: Optional[int]) -> Dict[str, Any]:
    """Config SMTP da EMPRESA (padrao). O remetente individual entra por cima
    em _smtp_efetivo."""
    if organizacao_id is not None:
        try:
            from ..db.service import get_org_smtp_config
            cfg = get_org_smtp_config(organizacao_id, incluir_password=True)
        except Exception as e:
            log.warning(f"Falha lendo SMTP da empresa {organizacao_id}, usando global: {e}")
            cfg = None
        if not (cfg and cfg.get("configurado")):
            # Empresa sem SMTP proprio NAO cai na config global: o e-mail
            # sairia com o remetente de outra empresa (a config de envio e'
            # uma por
            # empresa). Devolve vazio -- o envio vira "simulado" e aparece
            # como nao configurado, em vez de sair assinado por quem nao e'.
            log.warning(f"Empresa {organizacao_id} sem SMTP configurado -- e-mail nao sera' enviado.")
            return {"host": "", "port": 587, "username": "", "password": "",
                    "use_tls": True, "email_from": "", "email_from_name": ""}
        if cfg and cfg.get("configurado"):
            return {
                "host": cfg.get("smtp_host"),
                "port": cfg.get("smtp_port") or 587,
                "username": cfg.get("smtp_username"),
                "password": cfg.get("smtp_password"),
                "use_tls": cfg.get("smtp_use_tls", True),
                # Sem "or settings.*": empresa que configurou servidor mas
                # deixou o remetente em branco NAO empresta o do global --
                # sairia assinada por outra empresa. Em branco aqui e'
                # bloqueio la' na frente, em enviar_email.
                "email_from": cfg.get("email_from") or "",
                "email_from_name": cfg.get("email_from_name") or "",
                # Viaja junto do remetente que ela autoriza: a conta de uma
                # empresa nunca chega ao envio de outra.
                "gmail_refresh_token": cfg.get("gmail_refresh_token") or "",
                # Empresa so' envia pela conta que ELA (ou a pessoa) conectou. Sem isto,
                # quem nao conectou o Gmail caia na conta geral do servidor e o e-mail
                # saia pela caixa de outra pessoa, com o remetente trocado.
                "conta_propria_obrigatoria": True,
            }
    return {
        "host": settings.SMTP_HOST, "port": settings.SMTP_PORT,
        "username": settings.SMTP_USERNAME, "password": settings.SMTP_PASSWORD,
        "use_tls": settings.SMTP_USE_TLS,
        "email_from": settings.EMAIL_FROM, "email_from_name": settings.EMAIL_FROM_NAME,
    }


def _conectar_smtp(cfg: Dict[str, Any]) -> smtplib.SMTP:
    """Abre a conexao no modo certo pro provedor: porta 465 e' SSL implicito
    desde o connect (SMTP_SSL) -- tentar STARTTLS nela trava ou derruba a
    conexao sem erro claro. Qualquer outra porta (587, 25, ...) e' texto
    puro + STARTTLS depois de conectar, como a maioria dos provedores
    (Gmail, Outlook, SendGrid) espera."""
    host = cfg.get("host")
    port = int(cfg.get("port") or 587)
    if port == 465:
        return smtplib.SMTP_SSL(host, port, timeout=20)
    server = smtplib.SMTP(host, port, timeout=20)
    if cfg.get("use_tls", True):
        server.starttls()
    return server


def enviar_email(para: str, assunto: str, corpo_html: str, corpo_texto: Optional[str] = None,
                 smtp: Optional[Dict[str, Any]] = None,
                 unsubscribe_url: Optional[str] = None) -> Dict[str, Any]:
    cfg = smtp or _smtp_da_org(None)

    # REGRA UNICA DE REMETENTE, antes de escolher transporte: sai com o
    # remetente configurado ou nao sai. Nunca com o padrao global.
    #
    # Fica aqui, e nao em cada transporte, porque este e' o unico ponto por
    # onde todo transporte passa. Guard repetido caminho a caminho falha no
    # caminho novo: basta um transporte entrar na frente para refazer o
    # fallback que o guard recusa.
    #
    # _smtp_da_org(None) (e-mail do sistema: recuperacao de senha,
    # boas-vindas) devolve o global e passa aqui de proposito -- esse nao e'
    # de empresa nenhuma.
    remetente = (cfg.get("email_from") or "").strip()
    if not remetente:
        log.warning(f"Envio bloqueado para {para}: empresa sem remetente proprio configurado")
        return {"sucesso": False, "nao_configurado": True, "para": para,
                "erro": "Esta empresa nao tem e-mail de envio configurado. "
                        "Configure em Configuracoes > E-mail antes de enviar."}

    # Empresa: a conta geral do servidor (GMAIL_OAUTH_*) nunca serve de reserva.
    sem_conta_propria = bool(cfg.get("conta_propria_obrigatoria")) and not cfg.get("gmail_refresh_token")
    if sem_conta_propria and not cfg.get("host"):
        log.warning(f"Envio bloqueado para {para}: {remetente} nao conectou o Gmail")
        return {"sucesso": False, "nao_configurado": True, "para": para,
                "erro": f"A conta do Gmail de {remetente} ainda nao foi conectada. "
                        "A pessoa precisa conectar em Configuracoes > Meu e-mail."}

    # Gmail API tem prioridade: fala HTTPS, e o Render bloqueia SMTP 587/465.
    # Configurada, ela e a resposta final: cair para SMTP so trocaria o erro
    # real por "Network is unreachable" do socket bloqueado.
    if gmail_api.configurado() and not sem_conta_propria:
        return gmail_api.enviar(para, assunto, corpo_html, corpo_texto,
                                remetente=remetente,
                                remetente_nome=cfg.get("email_from_name"),
                                unsubscribe_url=unsubscribe_url,
                                refresh_token=cfg.get("gmail_refresh_token") or None)

    if not cfg.get("host"):
        log.warning(f"SMTP nao configurado. Email simulado para {para}")
        return {"sucesso": True, "simulado": True, "para": para, "assunto": assunto}
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = assunto
        msg["From"] = f"{cfg.get('email_from_name')} <{cfg.get('email_from')}>"
        msg["To"] = para
        # Message-ID proprio: casa os eventos do webhook com este envio.
        dominio = (cfg.get("email_from") or "").split("@")[-1] or None
        msg_id = make_msgid(domain=dominio)
        msg["Message-ID"] = msg_id
        # Mesmo cabecalho no caminho SMTP: regra de entrega vale para todo
        # transporte, nao so' para o que esta' em uso hoje. Transporte que
        # entra na frente herda a regra em vez de contorna-la.
        if unsubscribe_url:
            alvos = [f"<{unsubscribe_url}>"]
            if remetente and "@" in remetente:
                alvos.insert(0, f"<mailto:{remetente}?subject=unsubscribe>")
            msg["List-Unsubscribe"] = ", ".join(alvos)
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        if corpo_texto:
            msg.attach(MIMEText(corpo_texto, "plain", "utf-8"))
        msg.attach(MIMEText(corpo_html, "html", "utf-8"))
        with _conectar_smtp(cfg) as server:
            if cfg.get("username") and cfg.get("password"):
                server.login(cfg.get("username"), cfg.get("password"))
            server.sendmail(cfg.get("email_from"), [para], msg.as_string())
        log.info(f"Email enviado para {para}: {assunto}")
        return {"sucesso": True, "para": para, "assunto": assunto, "message_id": msg_id}
    except Exception as e:
        log.error(f"Erro ao enviar email para {para}: {e}")
        return {"sucesso": False, "para": para, "erro": str(e)}

def _assinatura_efetiva(organizacao_id: Optional[int], remetente: Optional[str] = None) -> str:
    """Assinatura do e-mail. A da pessoa vem primeiro (o e-mail e' dela); sem
    assinatura propria, usa a da empresa."""
    if remetente and organizacao_id is not None:
        try:
            from ..db.service import get_usuario_smtp_config
            meu = get_usuario_smtp_config(remetente, organizacao_id)
            if meu and meu.get("assinatura_html"):
                return _resolver_logo(meu["assinatura_html"], organizacao_id)
        except Exception as e:
            log.warning(f"Falha lendo assinatura de {remetente}: {e}")
    return _assinatura_da_org(organizacao_id)


def _resolver_logo(assinatura: str, organizacao_id: int) -> str:
    """Troca {{logo}} pela URL publica do logo da empresa."""
    try:
        base = getattr(settings, "API_PUBLIC_URL", "") or ""
    except Exception:
        base = ""
    return assinatura.replace("{{logo}}", f"{base}/api/v1/organizacoes/{organizacao_id}/logo")


def _assinatura_da_org(organizacao_id: Optional[int]) -> str:
    """HTML da assinatura da empresa, com {{logo}} resolvido para a URL publica
    do logo. Vazio se a empresa nao tiver assinatura."""
    if organizacao_id is None:
        return ""
    try:
        from ..db.service import get_org_smtp_config
        cfg = get_org_smtp_config(organizacao_id)
        assinatura = (cfg or {}).get("assinatura_html") or ""
    except Exception:
        return ""
    if not assinatura:
        return ""
    try:
        base = getattr(settings, "API_PUBLIC_URL", "") or ""
    except Exception:
        base = ""
    return assinatura.replace("{{logo}}", f"{base}/api/v1/organizacoes/{organizacao_id}/logo")


def _rodape_descadastro(email_dest: str) -> Dict[str, str]:
    """Rodape de opt-out (LGPD) -- discreto, sem cara de spam generico, e
    injetado pelo MOTOR de envio (nao pelo template): assim toda campanha,
    de qualquer empresa, sempre tem esse link, sem depender de quem
    escreveu o template lembrar de incluir."""
    from .descadastro import gerar_link_descadastro
    link = gerar_link_descadastro(email_dest)
    if not link:
        return {"html": "", "texto": "", "url": ""}
    html = (
        '<p style="margin:20px 0 0 0;font-family:Arial,Helvetica,sans-serif;'
        'font-size:11px;line-height:1.5;color:#9CA3AF;">'
        f'Prefere não receber mais e-mails como este? <a href="{link}" style="color:#9CA3AF;">É só avisar aqui</a>.'
        '</p>'
    )
    texto = f"\n\nPrefere nao receber mais e-mails como este? {link}"
    return {"html": html, "texto": texto}


def montar_email_para_cnpj(
    template: Dict, cnpj: str, email_dest: str,
    dados: Optional[Dict[str, str]] = None, organizacao_id: Optional[int] = None,
    remetente: Optional[str] = None,
) -> Dict[str, Any]:
    """Monta o e-mail FINAL de um destinatario: variaveis substituidas +
    assinatura da empresa + rodape de descadastro (LGPD).

    E' o mesmo caminho usado no envio real -- o preview chama esta funcao
    justamente pra mostrar o que vai sair, e nao uma aproximacao."""
    dados = dados or {}
    cnae = dados.get("cnae_principal") or dados.get("cnae")
    categoria = classificar_cnae(cnae) if cnae else "servicos"

    template_id_base = template.get("id") or template.get("template_id")
    tpl = (_obter_template_para_cnpj(template_id_base, cnae) if template_id_base else template) or template

    # MEI nao tem socio em dados_socios: a pessoa e' o proprio nome
    # empresarial. Resolvido aqui porque campanha, preview e teste passam
    # todos por esta funcao.
    nome_socio = ((dados.get("nome_socio") or "").strip()
                  or titular(dados.get("razao_social"), dados.get("porte_nome")))
    empresa = (_nome_apresentavel(dados.get("nome_fantasia"))
               or _nome_apresentavel(dados.get("razao_social")) or cnpj)
    saudacao = _saudacao(nome_socio, dados.get("razao_social"),
                         dados.get("nome_fantasia")) or empresa
    vars_dict = {
        "empresa": empresa,
        "saudacao": saudacao,
        "nome_socio": _titulo(nome_socio) if nome_socio else "",
        "cnpj": cnpj,
        "cidade": _titulo(dados.get("municipio") or ""),
        "cnae": cnae or "",
        "cnae_descricao": _descricao_cnae_fallback(cnae, dados.get("cnae_descricao")),
        "tema": CATEGORIA_TEMAS.get(categoria, CATEGORIA_TEMAS["todos"]),
        "categoria": CATEGORIA_DESCRICOES.get(categoria, CATEGORIA_DESCRICOES["todos"]),
        "nome_fantasia": dados.get("nome_fantasia") or "",
        "porte": dados.get("porte_nome") or "",
        "imagem": tpl.get("imagem_url") or "",
    }
    rendered = _render_template(tpl, vars_dict)
    rodape = _rodape_descadastro(email_dest)
    return {
        "assunto": rendered.get("assunto", ""),
        "corpo_html": rendered.get("corpo_html", "") + _assinatura_efetiva(organizacao_id, remetente) + rodape["html"],
        "corpo_texto": (rendered.get("corpo_texto") or "") + rodape["texto"],
        "template_usado": tpl.get("nome", ""),
        "categoria_cnae": categoria,
        "variaveis": vars_dict,
        # Para o header List-Unsubscribe. Mesmo link do rodape -- um lugar
        # so' gera, dois lugares consomem.
        "unsubscribe_url": rodape.get("url", ""),
    }


def enviar_template_para_cnpjs(
    campanha_id: Optional[int],
    template: Dict,
    cnpjs: List[str],
    emails_por_cnpj: Dict[str, str],
    dados_empresas: Optional[Dict[str, Dict[str, str]]] = None,
    organizacao_id: Optional[int] = None,
    remetente: Optional[str] = None,
) -> Dict[str, Any]:
    """Envia template para CNPJs, escolhendo o template correto por CNAE.
    Usa o SMTP e a assinatura da empresa (organizacao_id). Pula quem ja
    pediu descadastro (LGPD/opt-out) -- regra do negocio, nao do template."""
    from ..db.service import email_esta_descadastrado
    resultados = {"sucessos": 0, "erros": 0, "descadastrados": 0, "enviados": [], "erros_list": []}
    # remetente = quem disparou. O e-mail e' individual: sai com o endereco e
    # a assinatura da pessoa, usando o servidor da empresa.
    smtp_cfg = _smtp_efetivo(organizacao_id, remetente)
    assinatura = _assinatura_efetiva(organizacao_id, remetente)
    if campanha_id:
        try:
            update_campanha_status(campanha_id, "em_andamento", total_destinatarios=len(cnpjs))
        except Exception:
            pass

    template_id_base = template.get("id") or template.get("template_id")
    dados_map = dados_empresas or {}

    for i, cnpj in enumerate(cnpjs):
        email_dest = emails_por_cnpj.get(cnpj, f"contato@{cnpj[:8]}.com")
        if email_esta_descadastrado(email_dest):
            resultados["descadastrados"] += 1
            continue
        dados = dados_map.get(cnpj, {})
        montado = montar_email_para_cnpj(template, cnpj, email_dest, dados, organizacao_id, remetente)
        categoria = montado["categoria_cnae"]
        tpl = {"nome": montado["template_usado"]}

        email_rec = None
        if campanha_id:
            try:
                email_rec = create_email_enviado(campanha_id, cnpj, email_dest, montado["assunto"],
                                                 template_id=template.get("id") or template.get("template_id"))
            except Exception:
                pass

        # Precisa do id do registro, entao so depois de create_email_enviado.
        corpo_html = injetar_rastreamento(montado["corpo_html"],
                                          email_rec.get("id") if email_rec else None)
        result = enviar_email(
            email_dest, montado["assunto"], corpo_html, montado["corpo_texto"],
            smtp=smtp_cfg,
            unsubscribe_url=montado.get("unsubscribe_url") or None,
        )
        if result.get("sucesso"):
            resultados["sucessos"] += 1
            resultados["enviados"].append({
                "cnpj": cnpj, "email": email_dest,
                "template_usado": tpl.get("nome", ""),
                "categoria_cnae": categoria,
            })
            if email_rec and "id" in email_rec:
                try:
                    update_email_enviado(email_rec["id"], "enviado",
                                         message_id=result.get("message_id"))
                except Exception:
                    pass
        else:
            resultados["erros"] += 1
            resultados["erros_list"].append({"cnpj": cnpj, "erro": result.get("erro", "desconhecido")})
            if email_rec and "id" in email_rec:
                try:
                    update_email_enviado(email_rec["id"], "erro", result.get("erro"))
                except Exception:
                    pass
        if i < len(cnpjs) - 1:
            time.sleep(0.05)

    if campanha_id:
        try:
            update_campanha_status(
                campanha_id, "concluida",
                enviados=resultados["sucessos"], erros=resultados["erros"],
            )
        except Exception:
            pass
    return resultados


def enviar_campanha(
    campanha_id: int,
    template: Dict,
    cnpjs: List[str],
    emails_por_cnpj: Dict[str, str],
    dados_empresas: Optional[Dict[str, Dict[str, str]]] = None,
    organizacao_id: Optional[int] = None,
    remetente: Optional[str] = None,
) -> Dict[str, Any]:
    return enviar_template_para_cnpjs(campanha_id, template, cnpjs, emails_por_cnpj, dados_empresas,
                                      organizacao_id=organizacao_id, remetente=remetente)



def notificar_tarefa_por_email(
    para: str, titulo: str, mensagem: str, organizacao_id: Optional[int] = None,
    prazo: Optional[str] = None, atribuida_por: Optional[str] = None,
) -> Dict[str, Any]:
    """Manda o aviso de tarefa pro e-mail cadastrado do usuario, usando o SMTP
    da propria empresa. Sem e-mail cadastrado (ou SMTP nao configurado), a
    notificacao no app continua valendo -- isto aqui e' um extra, nunca pode
    derrubar a criacao da tarefa."""
    if not para:
        return {"sucesso": False, "motivo": "usuario sem e-mail cadastrado"}
    detalhes = []
    if atribuida_por:
        detalhes.append(f"<p style='margin:4px 0;color:#475569'>Atribuída por <b>{atribuida_por}</b></p>")
    if prazo:
        detalhes.append(f"<p style='margin:4px 0;color:#475569'>Prazo: <b>{prazo}</b></p>")
    html = f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:520px">
      <p style="color:#64748b;font-size:13px;margin:0 0 12px">WhoDados · nova tarefa pra você</p>
      <h2 style="margin:0 0 8px;color:#1e293b;font-size:18px">{titulo}</h2>
      {''.join(detalhes)}
      <p style="margin:12px 0;color:#334155;white-space:pre-wrap">{mensagem or ''}</p>
      <p style="margin-top:20px;font-size:12px;color:#94a3b8">
        Você recebeu este aviso porque é o responsável por esta atividade no WhoDados.
      </p>
    </div>"""
    partes = [titulo, "", mensagem or ""]
    if prazo:
        partes.append(f"Prazo: {prazo}")
    texto = "\n".join(partes)
    try:
        # Sai de quem atribuiu a tarefa -- responder o aviso cai na pessoa
        # certa, nao num endereco generico da empresa.
        return enviar_email(para, f"[WhoDados] {titulo}", html, texto,
                            smtp=_smtp_efetivo(organizacao_id, atribuida_por))
    except Exception as e:  # nunca deixa o e-mail quebrar a criacao da tarefa
        log.warning(f"Falha ao notificar tarefa por e-mail para {para}: {e}")
        return {"sucesso": False, "erro": str(e)}


def enviar_email_teste(para: str, template: Dict, organizacao_id: Optional[int] = None,
                       dados_empresa: Optional[Dict[str, Any]] = None,
                       remetente: Optional[str] = None) -> Dict[str, Any]:
    """Envia UM e-mail de teste do template renderizado.

    Usa montar_email_para_cnpj -- o mesmo caminho do envio real. Montar as
    variaveis a parte aqui fazia o teste divergir do que sai de verdade
    ({{saudacao}} e {{nome_socio}} nao existiam nesta lista e chegavam sem
    substituir).
    """
    if dados_empresa:
        cnpj = dados_empresa.get("cnpj_completo") or ""
        dados = dict(dados_empresa)
    else:
        cnpj = "00000000000000"
        dados = {
            "razao_social": "Empresa Exemplo LTDA", "nome_fantasia": "Exemplo",
            "municipio": "Porto Alegre", "cnae_principal": "", "cnae_descricao": "",
            "porte_nome": "", "nome_socio": "Maria Souza",
        }

    montado = montar_email_para_cnpj(template, cnpj, para, dados, organizacao_id, remetente)
    return enviar_email(
        para, "[TESTE] " + (montado["assunto"] or "Sem assunto"),
        montado["corpo_html"], montado["corpo_texto"],
        smtp=_smtp_efetivo(organizacao_id, remetente),
    )
