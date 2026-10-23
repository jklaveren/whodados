"""Disparar: regras do endpoint. Sem banco e sem rede."""
import asyncio

import pytest
from fastapi import HTTPException

import backend.endpoints_disparo as ed


@pytest.fixture
def fila(monkeypatch):
    estado = {"reservou": None, "devolveu": [], "enviou": None, "status": None, "rodadas": 0}
    contatos = [{"cnpj_completo": f"{i:014d}", "email": f"a{i}@x.com"} for i in range(500)]

    monkeypatch.setattr(ed, "org_escopo_base", lambda org: "carteira")
    # Junto de org_escopo_base: _exigir_lista_propria pergunta o tamanho
    # da carteira, e sem esta troca o teste abre conexao de verdade.
    monkeypatch.setattr(ed, "tamanho_carteira", lambda org: 100)
    monkeypatch.setattr(ed, "get_template", lambda tid, organizacao_id=None: {"id": tid})
    monkeypatch.setattr(ed, "_remetente_valido", lambda u, org: u)
    monkeypatch.setattr(ed, "_smtp_efetivo", lambda org, rem: {"gmail_refresh_token": "conectado"})
    monkeypatch.setattr(ed, "_orcamento_email_hoje", lambda org=None: None)
    monkeypatch.setattr(ed, "campanha_de_disparo", lambda *a, **k: {"id": 77})

    def reservar(cid, org, n, status="reservado"):
        estado["reservou"] = n
        estado["status"] = status
        return contatos[:n]

    monkeypatch.setattr(ed, "reservar_proximos", reservar)
    monkeypatch.setattr(ed, "devolver_nao_enviados", lambda cid, cnpjs: estado["devolveu"].extend(cnpjs))

    monkeypatch.setattr(ed, "_janela_de_envio", lambda: {"aberta": True})
    monkeypatch.setattr(ed, "resumo_fila", lambda org: {"na_fila": 0, "proxima_rodada_em": None})
    estado["sorteou"] = []
    monkeypatch.setattr(ed, "sortear_modelos",
                        lambda cid, org, cnpjs, ids: estado["sorteou"].append((list(cnpjs), list(ids))) or {i: 0 for i in ids})

    def rodada(campanha):
        estado["rodadas"] += 1
        estado["enviou"] = campanha.get("remetente_username")
        return {"sucessos": 10, "erros": 0, "conferencia": {"bloqueados": 0}}

    monkeypatch.setattr(ed, "rodar_fila", rodada)
    return estado


def _enviar(**dados):
    base = {"quantidade": 20, "template_id": 6, "remetente": "ana"}
    base.update(dados)
    return asyncio.run(ed.enviar(base, {"sub": "ana"}, 2))


def test_envia_a_quantidade_pedida(fila):
    r = _enviar()
    assert fila["reservou"] == 20 and r["enfileirados"] == 20
    assert fila["status"] == "na_fila", "tem que entrar na fila, nao ser mandado de uma vez"
    assert fila["rodadas"] == 1, "so' a primeira rodada sai no clique; o resto no ritmo"
    assert r["enviados"] == 10


def test_um_engano_de_digitacao_nao_vira_disparo_gigante(fila):
    """2000 no lugar de 20 nao pode mandar 2000 de um dominio novo."""
    _enviar(quantidade=2000)
    assert fila["reservou"] == ed.MAX_POR_CLIQUE


def test_respeita_o_que_ainda_cabe_hoje(fila, monkeypatch):
    monkeypatch.setattr(ed, "_orcamento_email_hoje", lambda org=None: 7)
    _enviar(quantidade=20)
    assert fila["reservou"] == 7


def test_teto_do_dia_esgotado_recusa(fila, monkeypatch):
    monkeypatch.setattr(ed, "_orcamento_email_hoje", lambda org=None: 0)
    with pytest.raises(HTTPException) as e:
        _enviar()
    assert e.value.status_code == 429 and fila["reservou"] is None


@pytest.mark.parametrize("dados", [{"quantidade": 0}, {"quantidade": -3}, {"quantidade": "abc"}, {"template_id": None}])
def test_pedido_invalido_nao_reserva_ninguem(fila, dados):
    with pytest.raises(HTTPException) as e:
        _enviar(**dados)
    assert e.value.status_code == 400 and fila["reservou"] is None


def test_janela_fechada_so_enfileira(fila, monkeypatch):
    """Fora do horario nao manda nada; a fila espera o agendador."""
    monkeypatch.setattr(ed, "_janela_de_envio", lambda: {"aberta": False, "motivo": "noite"})
    r = _enviar()
    assert fila["rodadas"] == 0 and r["enviados"] == 0
    assert r["janela_fechada"] is True and r["enfileirados"] == 20


def test_fila_em_andamento_nao_ganha_rodada_extra(fila, monkeypatch):
    """Clicar de novo no meio do intervalo nao pode furar o ritmo de 11-12 min."""
    from datetime import datetime, timedelta, timezone
    futuro = datetime.now(timezone.utc) + timedelta(minutes=8)
    monkeypatch.setattr(ed, "campanha_de_disparo", lambda *a, **k: {"id": 77, "proximo_lote_em": futuro})
    r = _enviar()
    assert fila["rodadas"] == 0 and r["enfileirados"] == 20


def test_empresa_sem_lista_de_trabalho_nao_usa_o_disparar(fila, monkeypatch):
    """O que libera o Disparar e' TER carteira, nao o escopo_base.

    A regra era escopo_base == 'carteira', e isso barrava a Alfa: ela pesquisa
    sobre a base inteira da Receita e tem uma lista recortada dali."""
    monkeypatch.setattr(ed, "tamanho_carteira", lambda org: 0)
    with pytest.raises(HTTPException) as e:
        _enviar()
    assert e.value.status_code == 400


def test_empresa_da_base_da_receita_com_lista_dispara(fila, monkeypatch):
    monkeypatch.setattr(ed, "org_escopo_base", lambda org: "receita")
    monkeypatch.setattr(ed, "tamanho_carteira", lambda org: 10737)
    assert _enviar()["enviados"] >= 0


def test_sem_contato_disponivel_avisa(fila, monkeypatch):
    monkeypatch.setattr(ed, "reservar_proximos", lambda cid, org, n, status="reservado": [])
    r = _enviar()
    assert r["enviados"] == 0 and r["mensagem"]


# Follow-up

def test_followup_usa_a_carteira_em_trabalho_e_a_campanha_propria(fila, monkeypatch):
    visto = {}
    monkeypatch.setattr(ed, "campanha_de_disparo",
                        lambda org, tpl, rem, por, prefixo="Disparo": visto.update(prefixo=prefixo) or {"id": 88})
    monkeypatch.setattr(ed, "reservar_followups",
                        lambda cid, org, n, dias, status="reservado": [{"cnpj_completo": "1"}] * min(n, 3))
    r = asyncio.run(ed.followup({"quantidade": 10, "template_id": 9, "remetente": "ana"},
                                {"sub": "ana"}, 2))
    assert visto["prefixo"] == "Follow-up", "o 2o toque precisa de registro proprio, senao conflita com o 1o"
    assert r["enfileirados"] == 3


def test_followup_tem_as_mesmas_travas_do_primeiro_contato(fila, monkeypatch):
    monkeypatch.setattr(ed, "_orcamento_email_hoje", lambda org=None: 0)
    with pytest.raises(HTTPException) as e:
        asyncio.run(ed.followup({"quantidade": 5, "template_id": 9}, {"sub": "j"}, 2))
    assert e.value.status_code == 429


def test_marcar_resposta_tira_do_followup(monkeypatch):
    visto = []
    monkeypatch.setattr(ed, "org_escopo_base", lambda org: "carteira")
    monkeypatch.setattr(ed, "tamanho_carteira", lambda org: 100)
    monkeypatch.setattr(ed, "marcar_situacao_contato", lambda org, cnpj, sit, por: visto.append((cnpj, sit)))
    asyncio.run(ed.situacao({"cnpj": "12.345.678/0001-00", "situacao": "respondeu"}, {"sub": "j"}, 2))
    assert visto == [("12345678000100", "respondeu")], "CNPJ com mascara tem que virar so' digitos"


@pytest.mark.parametrize("dados", [{"cnpj": "", "situacao": "respondeu"}, {"cnpj": "1", "situacao": "qualquer"}])
def test_situacao_invalida_e_recusada(monkeypatch, dados):
    monkeypatch.setattr(ed, "org_escopo_base", lambda org: "carteira")
    monkeypatch.setattr(ed, "tamanho_carteira", lambda org: 100)
    with pytest.raises(HTTPException) as e:
        asyncio.run(ed.situacao(dados, {"sub": "j"}, 2))
    assert e.value.status_code == 400


def test_desfazer_a_situacao_aceita_nulo(monkeypatch):
    visto = []
    monkeypatch.setattr(ed, "org_escopo_base", lambda org: "carteira")
    monkeypatch.setattr(ed, "tamanho_carteira", lambda org: 100)
    monkeypatch.setattr(ed, "marcar_situacao_contato", lambda org, cnpj, sit, por: visto.append(sit))
    asyncio.run(ed.situacao({"cnpj": "1", "situacao": None}, {"sub": "j"}, 2))
    assert visto == [None]


def test_a_tela_aberta_aciona_a_fila_da_propria_empresa(monkeypatch):
    visto = []
    monkeypatch.setattr(ed, "org_escopo_base", lambda org: "carteira")
    monkeypatch.setattr(ed, "tamanho_carteira", lambda org: 100)
    monkeypatch.setattr(ed, "avancar_filas", lambda org=None: visto.append(org) or [])
    monkeypatch.setattr(ed, "resumo_fila", lambda org: {"na_fila": 5, "proxima_rodada_em": None})
    r = asyncio.run(ed.fila_avancar({"sub": "j"}, 2))
    assert visto == [2] and r["na_fila"] == 5


def test_entregue_conta_quem_abriu_ou_clicou():
    """Abrir prova que chegou. O painel mostrava 13 abertos e 0 entregues porque
    so' o evento do Brevo (que saiu) preenchia 'entregue_em'."""
    import inspect
    from backend.db import service
    fonte = inspect.getsource(service)
    trecho = "FILTER (WHERE entregue_em IS NOT NULL OR aberto_em IS NOT NULL"
    assert fonte.count(trecho) == 2, "os dois paineis (inicio e envios) precisam da mesma regra"


def test_primeiro_contato_respeita_a_situacao_do_contato():
    """Quem foi mapeado como desinteresse comercial (ou respondeu, ou nao tem
    interesse) nao pode ser escolhido como primeiro contato."""
    from backend.db import service
    assert "desinteresse_comercial" in service.SITUACOES_CONTATO
    assert "FROM contato_situacao s" in service._SQL_DISPONIVEIS
    assert "contato_situacao" in service._SQL_FOLLOWUP


# Teste de modelos (varios modelos, um por lead, sorteio equilibrado)

def test_varios_modelos_sao_sorteados_entre_os_contatos(fila):
    r = _enviar(quantidade=20, template_ids=[6, 21, 22, 23, 24])
    cnpjs, ids = fila["sorteou"][0]
    assert ids == [6, 21, 22, 23, 24] and len(cnpjs) == 20
    assert "distribuicao" in r


def test_modelo_unico_continua_funcionando(fila):
    _enviar(quantidade=5, template_id=6, template_ids=None)
    assert fila["sorteou"][0][1] == [6]


def test_mais_de_cinco_modelos_e_recusado(fila):
    with pytest.raises(HTTPException) as e:
        _enviar(template_ids=[1, 2, 3, 4, 5, 6])
    assert e.value.status_code == 400 and fila["reservou"] is None


def test_modelo_repetido_conta_uma_vez(fila):
    _enviar(template_ids=[6, 6, 21])
    assert fila["sorteou"][0][1] == [6, 21]


def test_modelo_inexistente_nao_reserva_ninguem(fila, monkeypatch):
    monkeypatch.setattr(ed, "get_template", lambda tid, organizacao_id=None: None if tid == 99 else {"id": tid})
    with pytest.raises(HTTPException) as e:
        _enviar(template_ids=[6, 99])
    assert e.value.status_code == 404 and fila["reservou"] is None


def test_rota_de_resultado_por_modelo(monkeypatch):
    monkeypatch.setattr(ed, "org_escopo_base", lambda org: "carteira")
    monkeypatch.setattr(ed, "tamanho_carteira", lambda org: 100)
    monkeypatch.setattr(ed, "metricas_modelos", lambda org: {"desde": None, "modelos": [{"id": 6, "enviados": 3}]})
    assert asyncio.run(ed.modelos_resultado({"sub": "j"}, 2))["modelos"] == [{"id": 6, "enviados": 3}]


def test_email_compartilhado_fica_fora_do_primeiro_contato():
    """Um endereco chegou a estar em 294 MEIs (servico de abertura de empresa): a
    mesma caixa receberia 294 e-mails, cada um com um nome diferente."""
    from backend.db import service
    assert "email_compartilhado" in service._SQL_DISPONIVEIS
    assert callable(service.marcar_emails_compartilhados)


def test_importar_planilha_remarca_os_emails_compartilhados():
    import inspect
    import backend.endpoints_carteira as carteira
    assert "marcar_emails_compartilhados(org_id)" in inspect.getsource(carteira.carteira_importar)


def test_primeiro_contato_sai_dos_mais_recentes_para_os_mais_antigos():
    """Quem abriu o CNPJ ha' pouco e' quem mais precisa de um site: a fila comeca por eles."""
    import inspect
    from backend.db import service
    fonte = inspect.getsource(service.reservar_proximos)
    assert "ORDER BY c.data_fundacao DESC NULLS LAST" in fonte


# Cada pessoa envia pela propria caixa

def test_membro_nao_envia_pela_caixa_de_um_colega(fila):
    """Conectar o Gmail autoriza a PESSOA. Antes, qualquer membro da empresa podia
    assinar (e enviar) pelo Gmail de outro."""
    with pytest.raises(HTTPException) as e:
        _enviar(remetente="nicolas")
    assert e.value.status_code == 403 and fila["reservou"] is None


def _capturar_remetente(monkeypatch):
    """A campanha de apoio nasce com o remetente escolhido: e' dela que sai o envio."""
    visto = []
    monkeypatch.setattr(ed, "campanha_de_disparo",
                        lambda org, tpl, rem, por, prefixo="Disparo": visto.append(rem) or {"id": 77})
    return visto


def test_membro_envia_pela_propria_caixa(fila, monkeypatch):
    visto = _capturar_remetente(monkeypatch)
    r = _enviar(remetente="ana")
    assert r["enviados"] == 10 and visto == ["ana"]


def test_sem_remetente_usa_a_propria_caixa(fila, monkeypatch):
    visto = _capturar_remetente(monkeypatch)
    _enviar(remetente=None)
    assert visto == ["ana"]


def test_administrador_pode_assinar_por_outro(fila, monkeypatch):
    visto = _capturar_remetente(monkeypatch)
    r = asyncio.run(ed.enviar({"quantidade": 5, "template_id": 6, "remetente": "nicolas"},
                              {"sub": "ana", "is_admin": True}, 2))
    assert r["enviados"] == 10 and visto == ["nicolas"]


def test_lista_de_remetentes_do_membro_e_so_a_dele(monkeypatch):
    monkeypatch.setattr(ed, "org_escopo_base", lambda org: "carteira")
    monkeypatch.setattr(ed, "tamanho_carteira", lambda org: 100)
    for nome in ("resumo_disparo", "resumo_fila"):
        monkeypatch.setattr(ed, nome, lambda org: {"na_fila": 0, "proxima_rodada_em": None})
    # dias e' por empresa agora, entao a contagem recebe (org, dias)
    monkeypatch.setattr(ed, "contar_followups_devidos", lambda org, dias=None: 0)
    monkeypatch.setattr(ed, "_orcamento_email_hoje", lambda org=None: None)
    todos = [{"username": "ana"}, {"username": "nicolas"}, {"username": "lari"}]
    monkeypatch.setattr(ed, "remetentes_da_empresa", lambda org: todos)
    membro = asyncio.run(ed.resumo({"sub": "nicolas"}, 2))
    admin = asyncio.run(ed.resumo({"sub": "ana", "is_admin": True}, 2))
    assert [r["username"] for r in membro["remetentes"]] == ["nicolas"]
    assert len(admin["remetentes"]) == 3


def test_quem_nao_conectou_o_gmail_nao_dispara_e_nao_reserva_ninguem(fila, monkeypatch):
    """Sem conta conectada nao ha' de onde enviar: recusa antes de reservar, senao a fila
    queimaria os contatos em erro."""
    monkeypatch.setattr(ed, "_smtp_efetivo", lambda org, rem: {"gmail_refresh_token": "", "host": ""})
    with pytest.raises(HTTPException) as e:
        _enviar(remetente="ana")
    assert e.value.status_code == 400 and "nao conectou o Gmail" in e.value.detail
    assert fila["reservou"] is None
