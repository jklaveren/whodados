"""A campanha tem que disparar exatamente pro conjunto do lote.

Regressao: _selecionar_lote so repassava cidade/cnae/porte/busca/divida_min.
Um lote com capital minimo ou data de fundacao virava campanha pra um
conjunto maior do que o lote mostrava na tela.
"""
import backend.endpoints_campanhas as ec


FILTROS_LOTE = {
    "cidade": ["PORTO ALEGRE"],
    "cnae": ["4711301"],
    "porte": ["EPP"],
    "busca": "padaria",
    "divida_min": 1000,
    "divida_max": 90000,
    "capital_min": 100000,
    "capital_max": 500000,
    "fundacao_de": "2020-01-01",
    "fundacao_ate": "2024-12-31",
    "incluir_inativas": False,
    "contato": "com_email",
}


def test_selecionar_lote_repassa_todos_os_filtros(monkeypatch):
    recebido = {}

    def fake_listar(**kwargs):
        recebido.update(kwargs)
        return []

    monkeypatch.setattr(ec, "listar_empresas_db", fake_listar)
    monkeypatch.setattr(ec, "cnpjs_ja_contatados_campanha", lambda _id: set())
    # Supressao global e escopo da base entraram DEPOIS deste teste e nao
    # eram trocados aqui -- a selecao abria conexao de verdade no meio de um
    # teste unitario, e passava porque a maquina alcancava a producao.
    monkeypatch.setattr(ec, "cnpjs_contatados_org", lambda _org, desde_dias=None: set())
    monkeypatch.setattr(ec, "org_escopo_base", lambda _org: "receita")

    ec._selecionar_lote({"id": 1, "filtros": dict(FILTROS_LOTE), "tamanho_lote": 100}, org_id=1)

    for chave, valor in FILTROS_LOTE.items():
        assert recebido.get(chave) == valor, f"filtro '{chave}' nao chegou na selecao"


def test_selecionar_lote_sem_filtros_nao_quebra(monkeypatch):
    monkeypatch.setattr(ec, "listar_empresas_db", lambda **k: [])
    monkeypatch.setattr(ec, "cnpjs_ja_contatados_campanha", lambda _id: set())
    monkeypatch.setattr(ec, "cnpjs_contatados_org", lambda _org, desde_dias=None: set())
    monkeypatch.setattr(ec, "org_escopo_base", lambda _org: "receita")
    sel = ec._selecionar_lote({"id": 1, "filtros": None, "tamanho_lote": None}, org_id=1)
    assert sel["pendentes"] == 0
