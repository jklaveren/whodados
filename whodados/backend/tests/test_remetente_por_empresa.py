"""Regras de remetente por empresa (sem banco, sem rede).

Protege as duas pontas do mesmo problema:

1. Empresa SEM remetente proprio nao pode herdar o global -- heranca silenciosa
   faz uma empresa mandar e-mail assinado como outra.
2. Empresa COM remetente proprio e sem servidor SMTP TEM que conseguir enviar
   -- quem envia e' a Gmail API, que nao usa host nem usuario. A checagem
   antiga exigia SMTP e bloqueava justamente a configuracao correta.
"""
import pytest

from backend.mailer import service as mailer


@pytest.fixture
def sem_gmail(monkeypatch):
    """Desliga a Gmail API pra exercitar o caminho SMTP/simulado."""
    monkeypatch.setattr(mailer.gmail_api, "configurado", lambda: False)


@pytest.fixture
def com_gmail(monkeypatch):
    enviados = []

    def falso_enviar(para, assunto, corpo_html, corpo_texto, remetente,
                     remetente_nome=None, unsubscribe_url=None, refresh_token=None):
        enviados.append({"para": para, "remetente": remetente, "nome": remetente_nome,
                         "unsubscribe_url": unsubscribe_url, "refresh_token": refresh_token})
        return {"sucesso": True, "para": para}

    monkeypatch.setattr(mailer.gmail_api, "configurado", lambda: True)
    monkeypatch.setattr(mailer.gmail_api, "enviar", falso_enviar)
    return enviados


def _org(monkeypatch, **campos):
    """Config de empresa como o banco devolveria."""
    base = {
        "smtp_host": None, "smtp_port": None, "smtp_username": None,
        "smtp_password": None, "smtp_use_tls": True,
        "email_from": None, "email_from_name": None,
    }
    base.update(campos)
    # Mesma regra de get_org_smtp_config: configurada = tem remetente.
    base["configurado"] = bool(base.get("email_from"))
    monkeypatch.setattr("backend.db.service.get_org_smtp_config",
                        lambda org_id, incluir_password=False: dict(base))


def test_empresa_sem_remetente_nao_envia(monkeypatch, com_gmail):
    """Sem isto o remetente cai no global e a empresa manda e-mail assinado
    por OUTRA empresa."""
    _org(monkeypatch)  # nada preenchido
    cfg = mailer._smtp_da_org(7)
    assert cfg["email_from"] == ""

    r = mailer.enviar_email("alguem@exemplo.com", "oi", "<p>oi</p>", smtp=cfg)
    assert r["sucesso"] is False
    assert r.get("nao_configurado") is True
    assert com_gmail == [], "nao podia ter chamado a Gmail API"


def test_empresa_so_com_remetente_envia_pela_gmail(monkeypatch, com_gmail):
    """A configuracao CERTA: remetente proprio e nenhum servidor SMTP.

    Antes isto era barrado -- 'configurado' exigia smtp_host + smtp_username,
    entao preencher so' o remetente deixava a empresa como nao configurada e o
    envio era bloqueado, apesar de a Gmail API nao precisar de host nenhum.
    """
    _org(monkeypatch, email_from="comercial@beta.com.br", email_from_name="Beta Software",
         gmail_refresh_token="token-da-conta-conectada")
    cfg = mailer._smtp_da_org(7)
    assert cfg["email_from"] == "comercial@beta.com.br"

    r = mailer.enviar_email("alguem@exemplo.com", "oi", "<p>oi</p>", smtp=cfg)
    assert r["sucesso"] is True
    assert len(com_gmail) == 1
    assert com_gmail[0]["remetente"] == "comercial@beta.com.br"
    assert com_gmail[0]["nome"] == "Beta Software"


def test_quem_nao_conectou_o_gmail_nao_envia_pela_conta_geral(monkeypatch, com_gmail):
    """Sem conta conectada nao sai e-mail. Antes caia na conta geral do servidor (GMAIL_OAUTH_*)
    e saia pela caixa de outra pessoa, com o remetente trocado."""
    _org(monkeypatch, email_from="vendas@beta.com.br", email_from_name="Vendas | Beta Software")
    cfg = mailer._smtp_da_org(7)
    r = mailer.enviar_email("alguem@exemplo.com", "oi", "<p>oi</p>", smtp=cfg)
    assert r["sucesso"] is False and r.get("nao_configurado") is True
    assert "nao foi conectada" in r["erro"]
    assert com_gmail == [], "nao podia ter usado a conta geral"


def test_email_do_sistema_sem_empresa_continua_saindo_pela_conta_geral(monkeypatch, com_gmail):
    """Recuperacao de senha e boas-vindas nao sao de empresa nenhuma."""
    cfg = mailer._smtp_da_org(None)
    r = mailer.enviar_email("alguem@exemplo.com", "oi", "<p>oi</p>", smtp=cfg)
    assert len(com_gmail) == 1 and r["sucesso"] is True


def test_remetente_em_branco_com_servidor_proprio_tambem_nao_envia(monkeypatch, com_gmail):
    """Empresa que configurou servidor mas deixou o remetente vazio tambem nao
    pode emprestar o global -- mesma familia de problema."""
    _org(monkeypatch, smtp_host="smtp.exemplo.com", smtp_username="u", email_from=None)
    cfg = mailer._smtp_da_org(7)
    assert cfg["email_from"] == ""
    r = mailer.enviar_email("alguem@exemplo.com", "oi", "<p>oi</p>", smtp=cfg)
    assert r["sucesso"] is False
    assert com_gmail == []


def test_email_do_sistema_ainda_usa_o_global(monkeypatch, com_gmail):
    """Recuperacao de senha e boas-vindas nao sao de empresa nenhuma: sem
    organizacao, o remetente global e' o certo e deve continuar saindo."""
    monkeypatch.setattr(mailer.settings, "EMAIL_FROM", "noreply@whodados.com")
    cfg = mailer._smtp_da_org(None)
    assert cfg["email_from"] == "noreply@whodados.com"
    r = mailer.enviar_email("alguem@exemplo.com", "senha", "<p>link</p>", smtp=cfg)
    assert r["sucesso"] is True
    assert com_gmail[0]["remetente"] == "noreply@whodados.com"
