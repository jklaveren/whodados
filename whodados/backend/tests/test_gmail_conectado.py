"""Conta do Gmail conectada pelo sistema. Sem rede e sem banco.

Tres coisas que nao podem quebrar:
1. o retorno do Google e' publico -- so' o estado assinado diz para quem gravar;
2. o envio usa a conta de quem esta' enviando, nunca a de outra empresa;
3. a autorizacao guardada nunca sai no JSON da tela.
"""
import asyncio

import pytest

import backend.endpoints_gmail as eg
from backend.db import service as db
from backend.mailer import gmail_api, gmail_oauth
from backend.mailer import service as mailer


@pytest.fixture
def ambiente(monkeypatch):
    """Cliente web presente, nenhuma conta geral."""
    for nome in list(gmail_api.os.environ):
        if nome.startswith("GMAIL_"):
            monkeypatch.delenv(nome)
    monkeypatch.setenv("GMAIL_WEB_CLIENT_ID", "web-id")
    monkeypatch.setenv("GMAIL_WEB_CLIENT_SECRET", "web-segredo")
    monkeypatch.setattr(gmail_api, "CredenciaisOAuth", lambda **k: k)
    return monkeypatch


# 1: o estado assinado

def test_estado_volta_inteiro():
    dados = gmail_oauth.ler_estado(gmail_oauth.assinar_estado({"o": 2, "u": "nicolas"}))
    assert (dados["o"], dados["u"]) == (2, "nicolas")


def test_estado_adulterado_e_recusado():
    """Sem isto, trocar o numero da empresa no retorno ligaria a conta do
    Gmail de quem clicou na empresa de outro cliente."""
    corpo, assinatura = gmail_oauth.assinar_estado({"o": 2, "u": None}).split(".")
    outro = gmail_oauth.assinar_estado({"o": 1, "u": None}).split(".")[0]
    assert gmail_oauth.ler_estado(f"{outro}.{assinatura}") is None
    assert gmail_oauth.ler_estado(corpo) is None
    assert gmail_oauth.ler_estado("") is None


def test_estado_vencido_e_recusado(monkeypatch):
    estado = gmail_oauth.assinar_estado({"o": 2})
    agora = gmail_oauth.time.time()
    monkeypatch.setattr(gmail_oauth.time, "time", lambda: agora + 3600)
    assert gmail_oauth.ler_estado(estado) is None


def test_pedido_de_autorizacao_exige_token_permanente(ambiente):
    url = gmail_oauth.url_de_autorizacao("x")
    assert "access_type=offline" in url and "prompt=consent" in url, \
        "sem os dois, reconectar a mesma conta volta sem refresh token"
    assert "gmail.send" in url


def test_callback_com_estado_invalido_nao_grava(monkeypatch):
    gravou = []
    monkeypatch.setattr(eg, "set_gmail_conexao", lambda *a, **k: gravou.append(a))
    monkeypatch.setattr(eg.gmail_oauth, "trocar_codigo",
                        lambda c: {"conta": "x@y.com", "refresh_token": "t"})
    r = asyncio.run(eg.gmail_callback(code="abc", state="forjado.assinatura"))
    assert gravou == []
    assert "gmail=erro" in r.headers["location"]


def test_callback_grava_na_empresa_do_estado(monkeypatch):
    gravou = []
    monkeypatch.setattr(eg, "set_gmail_conexao",
                        lambda org, conta, token, username=None: gravou.append((org, conta, token, username)))
    monkeypatch.setattr(eg, "usuario_tem_acesso_org", lambda u, o: True)
    monkeypatch.setattr(eg.gmail_oauth, "trocar_codigo",
                        lambda c: {"conta": "contato@beta.top", "refresh_token": "t-beta"})
    estado = gmail_oauth.assinar_estado({"o": 2, "u": "nicolas", "por": "nicolas"})
    r = asyncio.run(eg.gmail_callback(code="abc", state=estado))
    assert gravou == [(2, "contato@beta.top", "t-beta", "nicolas")]
    assert "gmail=ok" in r.headers["location"]


def test_callback_recusa_quem_perdeu_o_acesso(monkeypatch):
    gravou = []
    monkeypatch.setattr(eg, "set_gmail_conexao", lambda *a, **k: gravou.append(a))
    monkeypatch.setattr(eg, "usuario_tem_acesso_org", lambda u, o: False)
    estado = gmail_oauth.assinar_estado({"o": 2, "u": "nicolas"})
    asyncio.run(eg.gmail_callback(code="abc", state=estado))
    assert gravou == []


def test_conexao_da_empresa_e_so_de_admin():
    with pytest.raises(eg.HTTPException) as e:
        eg._alvo("empresa", 2, {"sub": "nicolas", "is_admin": False}, 2)
    assert e.value.status_code == 403
    assert eg._alvo("eu", None, {"sub": "nicolas"}, 2) == {"o": 2, "u": "nicolas"}


# 2: de qual conta sai

def test_envio_usa_a_conta_conectada(ambiente):
    cred = gmail_api._credencial("nicolas@beta.top", "t-beta")
    assert cred["refresh_token"] == "t-beta"
    assert cred["client_id"] == "web-id", "token so' vale com o cliente que o emitiu"


def test_sem_conta_conectada_nem_geral_recusa(ambiente):
    """So' existem contas conectadas de outros: nao envia pela de ninguem."""
    assert gmail_api.configurado()
    r = gmail_api.enviar("a@b.com", "oi", "<p>oi</p>", None, remetente="contato@outra.com.br")
    assert r["sucesso"] is False and r.get("nao_configurado") is True


def test_conta_da_empresa_chega_ao_envio(monkeypatch):
    enviados = []

    def falso_enviar(para, assunto, corpo_html, corpo_texto, remetente,
                     remetente_nome=None, unsubscribe_url=None, refresh_token=None):
        enviados.append((remetente, refresh_token))
        return {"sucesso": True, "para": para}

    monkeypatch.setattr(mailer.gmail_api, "configurado", lambda: True)
    monkeypatch.setattr(mailer.gmail_api, "enviar", falso_enviar)
    monkeypatch.setattr(
        "backend.db.service.get_org_smtp_config",
        lambda org_id, incluir_password=False: {
            "configurado": True, "email_from": "contato@beta.top",
            "gmail_refresh_token": "t-beta"})
    mailer.enviar_email("a@b.com", "oi", "<p>oi</p>", smtp=mailer._smtp_da_org(2))
    assert enviados == [("contato@beta.top", "t-beta")]


def test_conta_da_pessoa_vence_a_da_empresa(monkeypatch):
    monkeypatch.setattr(
        "backend.db.service.get_org_smtp_config",
        lambda org_id, incluir_password=False: {
            "configurado": True, "email_from": "contato@beta.top",
            "gmail_refresh_token": "t-empresa"})
    monkeypatch.setattr(
        "backend.db.service.get_usuario_smtp_config",
        lambda u, o, incluir_password=False: {
            "email_from": "nicolas@beta.top", "gmail_refresh_token": "t-nicolas"})
    cfg = mailer._smtp_efetivo(2, "nicolas")
    assert (cfg["email_from"], cfg["gmail_refresh_token"]) == ("nicolas@beta.top", "t-nicolas")


# 3: a autorizacao nao vaza

def test_autorizacao_nao_sai_para_a_tela():
    dados = {"smtp_password": "enc:x", "gmail_refresh_token": "enc:y", "gmail_conta": "a@b.com"}
    db._segredos_de_envio(dados, incluir=False)
    assert "gmail_refresh_token" not in dados and "smtp_password" not in dados
    assert dados["gmail_conectado"] is True and dados["gmail_conta"] == "a@b.com"


def test_diagnostico_publico_so_diz_se_esta_habilitado(ambiente):
    d = gmail_api.diagnostico()
    assert d["conexao_pelo_sistema"] is True
    assert "web-segredo" not in str(d)


def test_desconectar_revoga_a_autorizacao_no_google(monkeypatch):
    """Apagar so' a copia daqui deixava o token valido no Google."""
    import asyncio
    import backend.endpoints_gmail as eg
    visto = {}
    monkeypatch.setattr(eg, "obter_gmail_refresh_token", lambda org, username=None: "refresh-secreto")
    monkeypatch.setattr(eg, "remover_gmail_conexao", lambda org, username=None: visto.update(removeu=True))
    monkeypatch.setattr(eg.gmail_oauth, "revogar", lambda t: visto.update(revogou=t) or True)
    r = asyncio.run(eg.gmail_desconectar(alvo="eu", organizacao_id=None,
                                         current_user={"sub": "nicolas"}, org_id=2))
    assert visto == {"removeu": True, "revogou": "refresh-secreto"} and r["revogado"] is True


def test_revogar_sem_token_nao_chama_o_google(monkeypatch):
    from backend.mailer import gmail_oauth
    chamou = []
    monkeypatch.setattr(gmail_oauth.requests, "post", lambda *a, **k: chamou.append(1))
    assert gmail_oauth.revogar(None) is False and not chamou
