"""Tres regras do envio automatico, todas sem banco e sem rede.

1. O remetente e' da CAMPANHA, nao de quem disparou -- no automatico quem
   dispara e' o cron, que nao tem e-mail proprio.
2. Remetente de outra empresa e' recusado.
3. O teto diario respeita o menor entre a conta e a empresa, pra o warm-up de
   um cliente novo nao obrigar a frear os outros.
"""
import pytest

import backend.endpoints_campanhas as ec
from backend.mailer import gmail_api


# 1 e 2: de quem sai o e-mail

def test_remetente_de_outra_empresa_e_recusado(monkeypatch):
    """Sem isto, mandar o username de alguem de outro cliente faria a campanha
    sair assinada por ele."""
    monkeypatch.setattr(ec, "usuario_tem_acesso_org", lambda u, o: False, raising=False)
    monkeypatch.setattr("backend.db.usuario_tem_acesso_org", lambda u, o: False)
    assert ec._remetente_valido("alguem_da_alfa", 2) is None


def test_remetente_com_acesso_e_aceito(monkeypatch):
    monkeypatch.setattr("backend.db.usuario_tem_acesso_org", lambda u, o: True)
    assert ec._remetente_valido("Nicolas", 2) == "Nicolas"


def test_remetente_vazio_vira_padrao(monkeypatch):
    monkeypatch.setattr("backend.db.usuario_tem_acesso_org", lambda u, o: True)
    assert ec._remetente_valido("", 2) is None
    assert ec._remetente_valido(None, 2) is None
    assert ec._remetente_valido("   ", 2) is None


# 3: o teto do dia

def _tetos(monkeypatch, conta, enviados_conta, org=None, enviados_org=0):
    monkeypatch.setattr(ec.settings, "EMAIL_LIMITE_DIARIO", conta)
    monkeypatch.setattr(ec, "contar_emails_enviados_hoje", lambda: enviados_conta)
    monkeypatch.setattr(ec, "limite_diario_org", lambda _o: org)
    monkeypatch.setattr(ec, "contar_emails_enviados_hoje_org", lambda _o: enviados_org)


def test_sem_org_usa_so_o_teto_da_conta(monkeypatch):
    _tetos(monkeypatch, conta=300, enviados_conta=50)
    assert ec._orcamento_email_hoje() == 250


def test_teto_da_empresa_segura_mesmo_com_folga_na_conta(monkeypatch):
    """O caso do warm-up: a conta tem 280 livres, mas o cliente novo so' pode
    20 por dia -- e saem 20, nao 280."""
    _tetos(monkeypatch, conta=300, enviados_conta=20, org=20, enviados_org=0)
    assert ec._orcamento_email_hoje(2) == 20


def test_teto_da_conta_nao_segura_quem_tem_teto_proprio(monkeypatch):
    """A conta estar no fim NAO limita quem tem teto proprio.

    Era o contrario: valia o menor dos dois, entao a Alfa com 1.900/dia
    configurados via 'ainda cabem 300 hoje' porque a conta global somava os
    envios das tres empresas. Isso vinha do tempo do Brevo, quando havia uma
    conta SMTP so'. Hoje cada empresa envia pelo Gmail dela, com cota propria
    no Google -- o que a Beta manda nao tira nada da Alfa."""
    _tetos(monkeypatch, conta=300, enviados_conta=295, org=50, enviados_org=0)
    assert ec._orcamento_email_hoje(2) == 50


def test_empresa_que_ja_gastou_a_propria_cota_para(monkeypatch):
    _tetos(monkeypatch, conta=300, enviados_conta=20, org=20, enviados_org=20)
    assert ec._orcamento_email_hoje(2) == 0


def test_empresa_sem_teto_proprio_usa_o_padrao_mas_conta_so_o_dela(monkeypatch):
    """Sem teto proprio, EMAIL_LIMITE_DIARIO vira o PADRAO da empresa -- e o
    gasto que conta e' o dela, nao o das outras."""
    _tetos(monkeypatch, conta=300, enviados_conta=100, org=None, enviados_org=40)
    assert ec._orcamento_email_hoje(2) == 260


def test_checagem_desligada_nos_dois_lados_nao_limita(monkeypatch):
    """EMAIL_LIMITE_DIARIO=0 desliga a checagem; sem teto de empresa tambem,
    nao ha limite nenhum (comportamento antigo, preservado)."""
    _tetos(monkeypatch, conta=0, enviados_conta=0, org=None)
    assert ec._orcamento_email_hoje(2) is None


def test_desligado_na_conta_mas_a_empresa_ainda_limita(monkeypatch):
    _tetos(monkeypatch, conta=0, enviados_conta=0, org=20, enviados_org=5)
    assert ec._orcamento_email_hoje(2) == 15


# Descadastro de um clique (RFC 8058)

def test_headers_de_descadastro_quando_ha_link():
    """Gmail/Yahoo/Outlook leem o HEADER pra desenhar o botao nativo. Sem ele,
    a saida facil de quem nao quer receber e' 'marcar como spam', e reclamacao
    e' o sinal que derruba reputacao mais rapido."""
    from email.mime.multipart import MIMEMultipart

    msg = MIMEMultipart("alternative")
    gmail_api._por_um_clique(msg, "nicolas@beta.top", "https://api/descadastro?email=x&sig=y")

    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click", \
        "sem isto o provedor nao mostra o botao"
    cabecalho = msg["List-Unsubscribe"]
    assert "<https://api/descadastro?email=x&sig=y>" in cabecalho
    assert "<mailto:nicolas@beta.top?subject=unsubscribe>" in cabecalho, \
        "mailto junto: funciona mesmo com o endpoint HTTP fora do ar"


def test_sem_link_nao_poe_header_vazio():
    from email.mime.multipart import MIMEMultipart

    msg = MIMEMultipart("alternative")
    gmail_api._por_um_clique(msg, "nicolas@beta.top", None)
    assert msg["List-Unsubscribe"] is None
    assert msg["List-Unsubscribe-Post"] is None


def test_descadastro_de_um_clique_exige_assinatura(monkeypatch):
    """O POST descadastra sem pagina nenhuma -- sem HMAC, qualquer um
    descadastraria qualquer endereco sabendo so' o e-mail."""
    import asyncio

    import backend.endpoints_descadastro as ed

    chamou = []
    monkeypatch.setattr(ed, "descadastrar_email", lambda e, motivo=None: chamou.append(e))
    monkeypatch.setattr(ed, "validar_assinatura", lambda e, s: s == "boa")

    r = asyncio.run(ed.descadastro_um_clique(email="a@b.com", sig="ruim"))
    assert r["ok"] is False
    assert chamou == [], "assinatura invalida nao pode descadastrar"

    r = asyncio.run(ed.descadastro_um_clique(email="a@b.com", sig="boa"))
    assert r["ok"] is True
    assert chamou == ["a@b.com"]
