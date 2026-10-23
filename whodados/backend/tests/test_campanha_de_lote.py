"""Disparo de campanha ligada a lote. Sem banco e sem rede.

Tres coisas que passaram sem teste e custaram um dia:
1. o motor passava `remetente` para uma funcao que nao o aceitava -- todo
   envio de campanha dava erro 500 ("Failed to fetch" na tela);
2. "20 por lote" mandava o bloco inteiro (~300): o limite do warm-up so'
   existia no caminho por filtro;
3. terminar o primeiro bloco marcava a campanha toda como concluida.
"""
import inspect

import pytest

import backend.endpoints_campanhas as ec
from backend.mailer import service as mailer


def test_enviar_campanha_aceita_o_remetente():
    """O contrato entre o motor de campanha e o mailer."""
    assert "remetente" in inspect.signature(mailer.enviar_campanha).parameters


def test_enviar_campanha_repassa_o_remetente(monkeypatch):
    visto = {}
    monkeypatch.setattr(mailer, "enviar_template_para_cnpjs",
                        lambda *a, **k: visto.update(k) or {"sucessos": 0, "erros": 0})
    mailer.enviar_campanha(1, {}, [], {}, {}, organizacao_id=2, remetente="nicolas")
    assert visto["remetente"] == "nicolas"


@pytest.fixture
def lote(monkeypatch):
    """Lote com 1 bloco de 300 empresas e um segundo bloco ainda pendente."""
    estado = {"bloco_fechado": [], "marcados": [], "status": []}
    empresas = [{"cnpj": f"{i:014d}", "email": f"a{i}@x.com", "telefone": "", "razao_social": f"E{i}"}
                for i in range(300)]
    blocos = iter([{"bloco": 1, "canal": "email", "template_id": None}])

    monkeypatch.setattr(ec, "proximo_bloco_pendente",
                        lambda lid, canal: {"bloco": 1, "canal": "email", "template_id": None}
                        if not estado["bloco_fechado"] else {"bloco": 2, "canal": "email", "template_id": None})
    monkeypatch.setattr(ec, "cnpjs_do_bloco", lambda lid, canal, bloco: empresas)
    monkeypatch.setattr(ec, "cnpjs_ja_contatados_campanha", lambda cid: set())
    monkeypatch.setattr(ec, "cnpjs_contatados_org", lambda org, desde_dias=None: set())
    monkeypatch.setattr(ec, "marcar_empresas_do_lote", lambda lid, cnpjs: estado["marcados"].extend(cnpjs))
    monkeypatch.setattr(ec, "atualizar_status_bloco",
                        lambda lid, canal, bloco, st: estado["bloco_fechado"].append(bloco))
    monkeypatch.setattr(ec, "update_campanha_status", lambda cid, st, **k: estado["status"].append(st))
    monkeypatch.setattr(ec, "create_notificacao", lambda *a, **k: None)
    monkeypatch.setattr(ec, "complementar_empresas_do_lote", lambda org, linhas: linhas)
    monkeypatch.setattr(ec, "_enviar_lote_email",
                        lambda cid, lista, camp, org, remetente=None: {"sucessos": len(lista), "erros": 0})
    return estado


def _campanha(**extra):
    base = {"id": 9, "nome": "t", "lote_id": 38, "canal": "email", "template_id": 6,
            "tamanho_lote": 20, "status": "rascunho"}
    base.update(extra)
    return base


def test_tamanho_do_lote_vale_para_campanha_de_lote(lote):
    r = ec._executar_um_lote(_campanha(), {"sub": "j"}, 2, max_envios=300)
    assert r["sucessos"] == 20, "mandou o bloco inteiro em vez de 20"
    assert len(lote["marcados"]) == 20


def test_bloco_parcial_nao_e_dado_como_enviado(lote):
    """Os outros 280 ainda nao foram contatados: o bloco continua pendente."""
    ec._executar_um_lote(_campanha(), {"sub": "j"}, 2, max_envios=300)
    assert lote["bloco_fechado"] == []
    assert lote["status"][-1] == "em_andamento"


def test_teto_do_dia_tambem_nao_fecha_o_bloco(lote):
    ec._executar_um_lote(_campanha(tamanho_lote=None), {"sub": "j"}, 2, max_envios=7)
    assert len(lote["marcados"]) == 7
    assert lote["bloco_fechado"] == []


def test_bloco_completo_fecha_mas_a_campanha_segue_se_ha_outro(lote):
    ec._executar_um_lote(_campanha(tamanho_lote=None), {"sub": "j"}, 2, max_envios=300)
    assert lote["bloco_fechado"] == [1]
    assert lote["status"][-1] == "em_andamento", "ainda ha' o bloco 2"


def test_disparo_manual_usa_o_teto_da_empresa(monkeypatch):
    """So' o teto da conta deixava o warm-up de uma empresa furar o proprio limite."""
    pedido = {}
    monkeypatch.setattr(ec, "get_campanha", lambda cid, organizacao_id=None: _campanha())
    monkeypatch.setattr(ec, "_orcamento_email_hoje", lambda org=None: pedido.setdefault("org", org) or 20)
    monkeypatch.setattr(ec, "_executar_um_lote", lambda *a, **k: {"sucessos": 0, "erros": 0})
    import asyncio
    asyncio.run(ec.executar_campanha(9, {"sub": "j"}, 2))
    assert pedido["org"] == 2


def test_dados_da_empresa_completam_a_linha_do_lote():
    """O lote guarda so' cnpj/e-mail/telefone/razao social. Sem cidade o
    assunto saia 'seu negocio aparece no Google em ?' para o cliente."""
    from backend.db.service import mesclar_dados_do_lote

    linha = {"cnpj_completo": "1", "email": "a@x.com", "contato_fone": "", "razao_social": "ANA"}
    fonte = {"municipio": "Guaiba", "cnae_descricao": "Cabeleireiros",
             "nome_fantasia": None, "porte_nome": "MEI", "cnae_principal": "9602501"}
    r = mesclar_dados_do_lote(linha, fonte)
    assert r["municipio"] == "Guaiba" and r["cnae_descricao"] == "Cabeleireiros"
    assert r["email"] == "a@x.com", "o que o lote guarda nao pode ser apagado"
    assert mesclar_dados_do_lote(linha, None)["razao_social"] == "ANA", "fonte ausente nao pode derrubar o envio"


# Ritmo da fila (Disparar / Follow-up)

@pytest.fixture
def rodada(monkeypatch):
    estado = {"puxou": None, "agendou": [], "assumiu": [], "devolveu": [], "enviou": None, "vence": True}
    monkeypatch.setattr(ec, "_orcamento_email_hoje", lambda org=None: None)
    monkeypatch.setattr(ec, "assumir_rodada",
                        lambda cid, minutos: estado["assumiu"].append(minutos) or estado["vence"])
    monkeypatch.setattr(ec, "puxar_da_fila",
                        lambda cid, n: estado.update(puxou=n) or [{"cnpj_completo": str(i)} for i in range(n)])
    monkeypatch.setattr(ec, "agendar_proximo_lote", lambda cid, minutos: estado["agendou"].append(minutos))
    monkeypatch.setattr(ec, "devolver_para_fila", lambda cid, cnpjs: estado["devolveu"].extend(cnpjs))
    monkeypatch.setattr(ec, "_enviar_lote_email",
                        lambda cid, lista, camp, org, remetente=None:
                        estado.update(enviou=remetente) or {"sucessos": len(lista), "erros": 0})
    return estado


_FILA = {"id": 5, "organizacao_id": 2, "remetente_username": "jessica", "template_id": 6}


def test_rodada_manda_dez_e_agenda_a_proxima_entre_11_e_12_minutos(rodada):
    r = ec.rodar_fila(dict(_FILA))
    assert rodada["puxou"] == 10 and r["sucessos"] == 10
    assert len(rodada["assumiu"]) == 1
    assert 11.0 <= rodada["assumiu"][0] <= 12.0, "o intervalo pedido foi de 11 a 12 minutos"


def test_intervalo_varia_entre_rodadas(rodada):
    for _ in range(30):
        ec.rodar_fila(dict(_FILA))
    assert len(set(round(m, 3) for m in rodada["assumiu"])) > 5, "intervalo fixo e' padrao facil de reconhecer"


def test_rodada_respeita_o_que_cabe_no_dia(rodada, monkeypatch):
    monkeypatch.setattr(ec, "_orcamento_email_hoje", lambda org=None: 4)
    ec.rodar_fila(dict(_FILA))
    assert rodada["puxou"] == 4


def test_teto_do_dia_esgotado_nao_manda_e_tenta_depois(rodada, monkeypatch):
    monkeypatch.setattr(ec, "_orcamento_email_hoje", lambda org=None: 0)
    r = ec.rodar_fila(dict(_FILA))
    assert rodada["puxou"] is None and r["adiado_por_limite"] is True
    assert rodada["agendou"] == [30]


def test_rodada_usa_o_remetente_da_campanha(rodada):
    ec.rodar_fila(dict(_FILA))
    assert rodada["enviou"] == "jessica"


def test_rodada_que_falha_devolve_todos_para_a_fila(rodada, monkeypatch):
    def quebra(*a, **k):
        raise RuntimeError("gmail fora do ar")

    monkeypatch.setattr(ec, "_enviar_lote_email", quebra)
    r = ec.rodar_fila(dict(_FILA))
    assert len(rodada["devolveu"]) == 10, "ninguem foi contatado: todos voltam"
    assert r["sucessos"] == 0 and r["erro"]
    assert rodada["agendou"] == [15], "tenta de novo mais tarde, sem martelar"


def test_rodada_que_outro_relogio_ja_levou_nao_manda_nada(rodada):
    """O laco interno, o GitHub e a tela aberta batem juntos: so' um leva a
    rodada. Sem isto cada um mandaria 10 e a fila andaria 3x mais rapido."""
    rodada["vence"] = False
    r = ec.rodar_fila(dict(_FILA))
    assert r.get("pulou") is True and rodada["puxou"] is None


def test_avancar_filas_nao_roda_fora_do_horario(monkeypatch):
    monkeypatch.setattr(ec, "_janela_de_envio", lambda: {"aberta": False})
    monkeypatch.setattr(ec, "campanhas_com_fila", lambda org=None: pytest.fail("nao devia nem consultar"))
    assert ec.avancar_filas() == []


def test_avancar_filas_por_empresa_e_resiliente(monkeypatch):
    vistos = []
    monkeypatch.setattr(ec, "_janela_de_envio", lambda: {"aberta": True})
    monkeypatch.setattr(ec, "campanhas_com_fila",
                        lambda org=None: vistos.append(org) or [{"id": 1, "nome": "a"}, {"id": 2, "nome": "b"}])

    def rodar(c):
        if c["id"] == 1:
            raise RuntimeError("quebrou")
        return {"sucessos": 10, "erros": 0}

    monkeypatch.setattr(ec, "rodar_fila", rodar)
    r = ec.avancar_filas(2)
    assert vistos == [2], "a tela filtra pela empresa dela"
    assert r[0]["erro"] and r[1]["sucessos"] == 10, "uma fila quebrada nao pode parar as outras"


# Teste de modelos: cada contato sai com o modelo sorteado

def test_a_rodada_envia_cada_contato_com_o_modelo_sorteado(rodada, monkeypatch):
    chamadas = []
    monkeypatch.setattr(ec, "puxar_da_fila", lambda cid, n: [
        {"cnpj_completo": "1", "template_id": 21}, {"cnpj_completo": "2", "template_id": 22},
        {"cnpj_completo": "3", "template_id": 21}, {"cnpj_completo": "4", "template_id": None}])
    monkeypatch.setattr(ec, "_enviar_lote_email",
                        lambda cid, lista, camp, org, remetente=None:
                        chamadas.append((camp["template_id"], [e["cnpj_completo"] for e in lista]))
                        or {"sucessos": len(lista), "erros": 0, "conferencia": {"bloqueados": 0, "total": len(lista)}})
    r = ec.rodar_fila(dict(_FILA))
    por_modelo = {t: c for t, c in chamadas}
    assert por_modelo[21] == ["1", "3"] and por_modelo[22] == ["2"]
    assert por_modelo[6] == ["4"], "contato antigo, sem sorteio, segue no modelo da propria campanha"
    assert r["sucessos"] == 4


def test_cidade_vazia_barra_so_se_o_modelo_cita_a_cidade():
    from backend.mailer.validacao import _checar_item
    base = {"saudacao": "Ana", "email": "a@x.com", "assunto": "Oi", "corpo_texto": "oi", "corpo_html": "<p>oi</p>"}
    regras = lambda **k: {a["regra"] for a in _checar_item({**base, **k}, set())}
    assert "cidade_vazia" in regras(exige_cidade=True, cidade="")
    assert "cidade_vazia" not in regras(exige_cidade=True, cidade="Pelotas")
    assert "cidade_vazia" not in regras(exige_cidade=False, cidade="")


def test_distribuicao_equilibrada_entre_cinco_modelos():
    from backend.db.service import distribuir_equilibrado
    escolhas = distribuir_equilibrado({1: 0, 2: 0, 3: 0, 4: 0, 5: 0}, 50)
    assert all(escolhas.count(t) == 10 for t in range(1, 6)), "cada modelo recebe a mesma quantidade"


def test_distribuicao_compensa_quem_ja_recebeu_mais():
    from backend.db.service import distribuir_equilibrado
    escolhas = distribuir_equilibrado({1: 10, 2: 0, 3: 0}, 10)
    assert escolhas.count(1) == 0 and escolhas.count(2) == 5 and escolhas.count(3) == 5


def test_distribuicao_nunca_deixa_um_modelo_muito_a_frente():
    from backend.db.service import distribuir_equilibrado
    for n in (1, 7, 13, 99):
        escolhas = distribuir_equilibrado({1: 0, 2: 0, 3: 0, 4: 0, 5: 0}, n)
        cont = [escolhas.count(t) for t in range(1, 6)]
        assert max(cont) - min(cont) <= 1, (n, cont)
