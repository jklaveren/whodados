"""Painel inicial: o que ele mostra, e o que ele NAO deixa vazar.

Duas regras valem dinheiro aqui:

1. O numero da conta inteira nao pode chegar a quem nao e' admin global --
   dele se deduz por subtracao quanto a OUTRA empresa mandou hoje.
2. A tela abre a cada login, entao o tamanho da base nao pode sair de
   COUNT(*) na tabela de 1,68M.
"""
import pytest

from backend.db import service as svc


class _CursorFalso:
    """Devolve respostas na ordem em que as queries aparecem.

    Guarda o SQL de tudo que rodou, pra o teste poder afirmar o que NAO foi
    executado -- que aqui e' tao importante quanto o resultado.
    """

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.sqls = []
        self._atual = None

    def execute(self, sql, params=None):
        self.sqls.append(" ".join(sql.split()))
        self._atual = self.respostas.pop(0) if self.respostas else None

    def fetchone(self):
        if isinstance(self._atual, list):
            return self._atual[0] if self._atual else None
        return self._atual

    def fetchall(self):
        if isinstance(self._atual, list):
            return self._atual
        return [self._atual] if self._atual else []


@pytest.fixture
def cursor(monkeypatch):
    """Troca get_db_cursor por um cursor de mentira, montado por teste."""
    from contextlib import contextmanager

    caixa = {}

    def montar(respostas):
        cur = _CursorFalso(respostas)
        caixa["cur"] = cur

        @contextmanager
        def falso():
            yield cur

        monkeypatch.setattr(svc, "get_db_cursor", falso)
        return cur

    return montar


def _respostas_carteira():
    """Sequencia de uma empresa de carteira, na ordem de painel_inicio."""
    return [
        {"total": 33685, "com_email": 30480, "cidades": 476},  # base
        {"n": 1200},                                           # contatados
        [{"status": "novo", "n": 10}, {"status": "convertido", "n": 2}],
        {"hoje_org": 18, "hoje_conta": 250},                   # hoje
        [],                                                    # por_dia
        {"enviados": 100, "entregues": 90, "abertos": 30, "clicados": 5},
        {"existe": True},                                      # _tabela_existe lote_empresas
        {"n": 7},                                              # fila
        {"existe": True},                                      # _tabela_existe crm_atividades
        {"pendentes": 3, "atrasadas": 1},
    ]


def test_conta_inteira_nao_vaza_para_quem_nao_e_admin(cursor, monkeypatch):
    """O numero da conta e' o vazamento: hoje_conta - hoje_org = a outra."""
    monkeypatch.setattr(svc, "org_escopo_base", lambda _o: "carteira")
    cursor(_respostas_carteira())
    d = svc.painel_inicio(2, ver_conta_inteira=False)

    assert d["envios"]["hoje_org"] == 18, "o numero da propria empresa tem que aparecer"
    assert d["envios"]["hoje_conta"] is None, "numero da conta nao pode sair"
    assert d["envios"]["restante"] is None, "restante tambem entrega a conta por subtracao"


def test_admin_global_ve_a_conta(cursor, monkeypatch):
    monkeypatch.setattr(svc, "org_escopo_base", lambda _o: "carteira")
    cursor(_respostas_carteira())
    d = svc.painel_inicio(2, ver_conta_inteira=True)
    assert d["envios"]["hoje_conta"] == 250


def test_teto_atingido_e_booleano_para_todos(cursor, monkeypatch):
    """Sem este sinal a empresa veria o envio parar sem explicacao -- o erro
    disfarcado de estado normal que o projeto corrigiu em quatro telas."""
    monkeypatch.setattr(svc, "org_escopo_base", lambda _o: "carteira")
    monkeypatch.setattr(svc, "painel_inicio", svc.painel_inicio)
    from backend import config as cfg
    monkeypatch.setattr(cfg.settings, "EMAIL_LIMITE_DIARIO", 200)
    cursor(_respostas_carteira())   # hoje_conta = 250, acima de 200
    d = svc.painel_inicio(2, ver_conta_inteira=False)
    assert d["envios"]["teto_atingido"] is True
    assert d["envios"]["hoje_conta"] is None, "o aviso nao pode trazer o numero de volta"


def test_penetracao_sobre_a_base(cursor, monkeypatch):
    monkeypatch.setattr(svc, "org_escopo_base", lambda _o: "carteira")
    cursor(_respostas_carteira())
    d = svc.painel_inicio(2)
    # 1200 / 33685 = 3,56%
    assert d["alcance"]["contatados"] == 1200
    assert d["alcance"]["penetracao_pct"] == pytest.approx(3.56, abs=0.01)


def test_base_sem_total_nao_inventa_penetracao(cursor, monkeypatch):
    """Sem denominador, a conta nao existe -- e None a tela sabe nao exibir.
    Zero seria um numero errado."""
    monkeypatch.setattr(svc, "org_escopo_base", lambda _o: "carteira")
    r = _respostas_carteira()
    r[0] = {"total": 0, "com_email": 0, "cidades": 0}
    cursor(r)
    d = svc.painel_inicio(2)
    assert d["alcance"]["penetracao_pct"] is None


def test_base_receita_nao_faz_count_na_tabela_de_168M(cursor, monkeypatch):
    """A regra que protege o login: o tamanho da base vem do metadata do ETL
    ou da estimativa do planner, nunca de COUNT(*)."""
    monkeypatch.setattr(svc, "org_escopo_base", lambda _o: "receita")
    cur = cursor([
        {"existe": True},                      # _tabela_existe pipeline_metadata
        {"valor": "1680000"},                  # total_empresas_sincronizadas
        {"n": 500},                            # contatados
        [],                                    # crm
        {"hoje_org": 0, "hoje_conta": 0},
        [],
        {"enviados": 0},
        {"existe": False},                     # sem lote_empresas
        {"existe": False},                     # sem crm_atividades
    ])
    d = svc.painel_inicio(1)

    assert d["base"]["total"] == 1680000
    assert d["base"]["estimado"] is False, "o metadata do ETL e' exato"
    assert d["base"]["com_email"] is None, "saber isso exigiria varrer a base"
    assert not any("COUNT(*) FROM dados_empresas" in s.upper().replace("COUNT (", "COUNT(")
                   for s in cur.sqls), "nenhum COUNT(*) em dados_empresas"


def test_base_receita_cai_para_estimativa_e_avisa(cursor, monkeypatch):
    monkeypatch.setattr(svc, "org_escopo_base", lambda _o: "receita")
    cursor([
        {"existe": False},          # sem pipeline_metadata
        {"n": 1680000},             # reltuples
        {"n": 0},                   # contatados
        [],
        {"hoje_org": 0, "hoje_conta": 0},
        [],
        {"enviados": 0},
        {"existe": False},
        {"existe": False},
    ])
    d = svc.painel_inicio(1)
    assert d["base"]["total"] == 1680000
    assert d["base"]["estimado"] is True, "a tela precisa dizer que e' estimativa"


def test_divida_nao_entra_no_painel(cursor, monkeypatch):
    """Divida nao e' criterio de prioridade neste produto, e esta e' a tela
    que define a prioridade de quem abre o sistema."""
    monkeypatch.setattr(svc, "org_escopo_base", lambda _o: "carteira")
    cur = cursor(_respostas_carteira())
    d = svc.painel_inicio(2)
    assert not any("divida" in s.lower() for s in cur.sqls), "nenhuma query de divida"
    assert "divida" not in str(d).lower()


def test_falha_no_banco_devolve_vazio_e_nao_derruba_o_login(monkeypatch):
    """A tela abre depois de todo login: erro aqui nao pode virar 500."""
    from contextlib import contextmanager

    monkeypatch.setattr(svc, "org_escopo_base", lambda _o: "carteira")

    @contextmanager
    def explode():
        raise RuntimeError("banco fora")
        yield  # pragma: no cover

    monkeypatch.setattr(svc, "get_db_cursor", explode)
    d = svc.painel_inicio(2)
    assert d["base"]["total"] is None, "ausente, nao zero"
    assert d["envios"]["hoje_conta"] is None
    assert d["atualizado_em"] is None, "sem dado nao ha hora de atualizacao"
