"""WhatsApp manual: so' celular, link pronto, e quem foi chamado sai das duas filas."""
import asyncio

import pytest
from fastapi import HTTPException

import backend.endpoints_disparo as ed
from backend import whatsapp_manual as wa


@pytest.mark.parametrize("fone,esperado", [
    ("(51) 98396703", "5551998396703"),     # 8 digitos da Receita, sem o 9 do celular
    ("(51) 96339894", "5551996339894"),
    ("(51) 998396703", "5551998396703"),    # ja' com o 9
    ("+55 51 99617893", "5551999617893"),
    ("(51) 36341020", None),                # fixo
    ("(54) 33584881", None),
    ("(0) 0", None),
    ("(55) 0", None),
    ("", None),
    (None, None),
])
def test_so_celular_e_com_o_nove(fone, esperado):
    assert wa.celular_br(fone) == esperado


def test_texto_cita_o_email_so_para_quem_recebeu_um():
    com = wa.mensagem("abriu", "Ana", "Guaiba", "Jessica")
    sem = wa.mensagem("novo", "Ana", "Guaiba", "Jessica")
    assert "e-mail" in com and "e-mail" not in sem
    assert "Guaiba" in sem and "R$ 400,00" in sem


@pytest.mark.parametrize("grupo", wa.GRUPOS)
def test_todo_texto_tem_a_saida_de_quem_nao_quer_receber(grupo):
    assert "Se não quiser receber mais mensagens" in wa.mensagem(grupo, "Ana", "Guaiba", "")


def test_texto_sem_nome_nao_deixa_buraco():
    t = wa.mensagem("novo", "", "", "")
    assert "Oi, tudo bem?" in t and "{" not in t and "  " not in t


def test_quem_foi_chamado_sai_do_primeiro_contato_e_do_followup():
    from backend.db import service
    assert "FROM contato_whatsapp w" in service._SQL_DISPONIVEIS
    assert "contato_whatsapp" in service._SQL_FOLLOWUP


def test_a_lista_exclui_o_que_o_email_ja_exclui():
    sql = wa._SQL_CHAMAR
    for regra in ("email_compartilhado", "contab", "emails_descadastrados", "contato_situacao", "contato_whatsapp"):
        assert regra in sql, regra


def test_marcar_status_invalido_e_recusado(monkeypatch):
    monkeypatch.setattr(ed, "org_escopo_base", lambda org: "carteira")
    # Junto de org_escopo_base: _exigir_lista_propria pergunta o tamanho
    # da carteira, e sem esta troca o teste abre conexao de verdade.
    monkeypatch.setattr(ed, "tamanho_carteira", lambda org: 100)
    with pytest.raises(HTTPException) as e:
        asyncio.run(ed.whatsapp_marcar({"cnpj": "1", "status": "bloqueado"}, {"sub": "j"}, 2))
    assert e.value.status_code == 400


def test_marcar_chamado_e_desfazer(monkeypatch):
    visto = []
    monkeypatch.setattr(ed, "org_escopo_base", lambda org: "carteira")
    monkeypatch.setattr(ed, "tamanho_carteira", lambda org: 100)
    monkeypatch.setattr(ed, "marcar_whatsapp", lambda org, cnpj, st, por: visto.append((cnpj, st)))
    asyncio.run(ed.whatsapp_marcar({"cnpj": "12.345.678/0001-00", "status": "chamado"}, {"sub": "j"}, 2))
    asyncio.run(ed.whatsapp_marcar({"cnpj": "12345678000100", "status": None}, {"sub": "j"}, 2))
    assert visto == [("12345678000100", "chamado"), ("12345678000100", None)]


def test_lista_limita_o_tamanho_do_pedido(monkeypatch):
    pedido = {}
    monkeypatch.setattr(ed, "org_escopo_base", lambda org: "carteira")
    monkeypatch.setattr(ed, "tamanho_carteira", lambda org: 100)
    monkeypatch.setattr(ed, "contar_para_chamar", lambda org: {})
    monkeypatch.setattr(ed, "contar_por_site", lambda org: {})
    monkeypatch.setattr(ed, "listar_para_chamar", lambda org, n, eu="", site="todos": pedido.update(n=n, eu=eu) or [])
    asyncio.run(ed.whatsapp_lista(limite=9999, eu="  Jessica  ", current_user={"sub": "j"}, org_id=2))
    assert pedido == {"n": 100, "eu": "Jessica"}


def test_busca_por_telefone_usa_os_ultimos_oito_digitos(monkeypatch):
    """Quem escreve do proprio celular: (51) 98396703 no cadastro, 5551998396703 no WhatsApp."""
    visto = {}

    class Cur:
        def execute(self, sql, params):
            visto["sql"], visto["params"] = sql, params
        def fetchall(self):
            return []

    import contextlib

    @contextlib.contextmanager
    def cursor():
        yield Cur()

    monkeypatch.setattr(wa, "get_db_cursor", cursor)
    wa.buscar_contato(2, "+55 51 99839-6703")
    assert "%98396703" in visto["params"]


@pytest.mark.parametrize("termo", ["", "  ", "ab", "12", "123"])
def test_busca_curta_demais_nao_consulta_o_banco(monkeypatch, termo):
    monkeypatch.setattr(wa, "get_db_cursor", lambda: (_ for _ in ()).throw(AssertionError("nao devia consultar")))
    assert wa.buscar_contato(2, termo) == []


def test_rota_de_busca_exige_lista_de_trabalho(monkeypatch):
    monkeypatch.setattr(ed, "tamanho_carteira", lambda org: 0)
    with pytest.raises(HTTPException):
        asyncio.run(ed.contato_buscar(q="ana", current_user={"sub": "j"}, org_id=2))


# Filtro por site (e-mail de dominio da empresa)

from backend.dominios_email import classificar  # noqa: E402


@pytest.mark.parametrize("email,esperado", [
    ("ana@gmail.com", "provedor"),
    ("ana@ymail.com", "provedor"),            # provedor real, nao e' erro de digitacao
    ("ana@gamil.com", "erro_digitacao"),
    ("ana@2010hotmail.com", "erro_digitacao"),
    ("ana@educar.rs.gov.br", "instituicao"),
    ("ana@universo.univates.br", "instituicao"),
    ("ana@brturbo.com.br", "provedor_antigo"),
    ("contato@contmaxdigital.com", "contabilidade"),
    ("contato@escritoriosilva.com.br", "contabilidade"),
    ("contato@studiobela.com.br", "empresa"),
    ("", "vazio"),
    ("sem-arroba", "vazio"),
])
def test_classificacao_do_dominio_do_email(email, esperado):
    assert classificar(email) == esperado


def test_quem_ja_tem_site_recebe_oferta_de_melhoria_sem_afirmar_defeito():
    t = wa.mensagem("novo", "Ana", "Guaiba", "Jessica", com_site=True)
    assert "Se vocês já têm site" in t and "R$ 400" not in t
    assert "Vi que" not in t, "ninguem olhou o site dele: nao pode afirmar nada sobre ele"
    assert "Se não quiser receber mais mensagens" in t


def test_filtro_de_site_invalido_e_recusado(monkeypatch):
    monkeypatch.setattr(ed, "org_escopo_base", lambda org: "carteira")
    monkeypatch.setattr(ed, "tamanho_carteira", lambda org: 100)
    with pytest.raises(HTTPException) as e:
        asyncio.run(ed.whatsapp_lista(site="qualquer", current_user={"sub": "j"}, org_id=2))
    assert e.value.status_code == 400


def test_filtro_de_site_chega_na_listagem(monkeypatch):
    visto = {}
    monkeypatch.setattr(ed, "org_escopo_base", lambda org: "carteira")
    monkeypatch.setattr(ed, "tamanho_carteira", lambda org: 100)
    monkeypatch.setattr(ed, "contar_para_chamar", lambda org: {})
    monkeypatch.setattr(ed, "contar_por_site", lambda org: {"com": 1, "sem": 2, "outros": 3})
    monkeypatch.setattr(ed, "listar_para_chamar", lambda org, n, eu="", site="todos": visto.update(site=site) or [])
    r = asyncio.run(ed.whatsapp_lista(site="com", current_user={"sub": "j"}, org_id=2))
    assert visto["site"] == "com" and r["sites"] == {"com": 1, "sem": 2, "outros": 3}
