"""Testes do construtor de filtros do funil de empresas (sem banco)."""
import pytest

from backend.db.service import _where_empresas, _norm_lista, CNAE_DIVISOES_EXCLUIDAS


@pytest.fixture(autouse=True)
def _municipios_fake(monkeypatch):
    """Cidade vira COD_MUNICIPIO via tabela municipios; aqui sem banco."""
    monkeypatch.setattr(
        "backend.db.service._mapa_municipios",
        lambda: {"PORTO ALEGRE": ["8801"], "CANOAS": ["8803"], "SAO LEOPOLDO": ["8825"]},
    )


def test_norm_lista():
    assert _norm_lista(None) == []
    assert _norm_lista("") == []
    assert _norm_lista("PoA") == ["PoA"]
    assert _norm_lista(["A", "B", ""]) == ["A", "B"]


def test_where_sem_filtro_aplica_so_a_exclusao_comercial():
    """Sem filtro nenhum o WHERE NAO e' vazio.

    A exclusao de divisoes de CNAE vale sempre: e' regra comercial da base
    (setores que a operacao nao prospecta), nao selecao de quem usa a tela.
    A versao antiga deste teste esperava "" e ficou vermelha no dia em que a
    exclusao entrou -- suite vermelha por teste velho ensina a ignorar
    vermelho, entao ele passa a afirmar o comportamento real."""
    where, params = _where_empresas()
    if CNAE_DIVISOES_EXCLUIDAS:
        assert "CNAE_PRINCIPAL" in where
        assert "<> ALL(%s)" in where
        assert params == [list(CNAE_DIVISOES_EXCLUIDAS)]
    else:
        assert where == ""
        assert params == []


def test_where_cidade_e_cnae():
    where, params = _where_empresas(cidade=["Porto Alegre", "Canoas"], cnae=["0111301"])
    assert '"COD_MUNICIPIO" = ANY(%s)' in where
    assert 'e."CNAE_PRINCIPAL" = ANY(%s)' in where
    # O nome digitado vira codigo de municipio antes do WHERE.
    assert ["8801", "8803"] in params
    assert ["0111301"] in params


def test_where_cidade_sem_acento():
    _, params = _where_empresas(cidade=["São Leopoldo"])
    assert ["8825"] in params


def test_where_cidade_inexistente_nao_devolve_base_toda():
    _, params = _where_empresas(cidade=["Cidade Que Nao Existe"])
    assert ["__nenhum__"] in params


def test_where_cnae_prefixo_vira_faixa():
    # Base guarda so CNAE de 7 digitos: '47113' tem que casar 4711301/4711302.
    where, params = _where_empresas(cnae=["47113", "4711-3/01"])
    assert "BETWEEN %s AND %s" in where
    assert "4711300" in params and "4711399" in params
    assert ["4711301"] in params


def test_where_cnae_invalido_nao_devolve_base_toda():
    where, _ = _where_empresas(cnae=["comercio"])
    assert "FALSE" in where


def test_where_porte_codigos_rf():
    # RF: 01=micro, 03=EPP, 05=demais (nao existe '02' na base).
    _, params = _where_empresas(porte=["MICRO", "EPP", "DEMAIS"])
    assert ["01", "03", "05"] in params
    _, params = _where_empresas(porte=["ME", "PEQUENO", "MEDIO E GRANDE"])
    assert ["01", "03", "05"] in params


def test_where_porte_desconhecido_nao_ignora():
    where, params = _where_empresas(porte=["XYZ"])
    assert '"PORTE_EMPRESA" = ANY(%s)' in where
    assert ["__nenhum__"] in params


def test_where_faixas():
    where, params = _where_empresas(divida_min=1000, capital_max=50000)
    assert '"DIVIDA_TOTAL"' in where
    assert '"CAPITAL_SOCIAL"' in where
    assert 1000 in params
    assert 50000 in params


def test_where_blacklist_rj():
    where, params = _where_empresas(incluir_inativas=False)
    assert "!~*" in where  # exclui Falencia/Rec. Judicial
    # incluir_inativas=True (padrao) nao filtra
    where2, _ = _where_empresas(incluir_inativas=True)
    assert "!~*" not in where2


def test_where_fundacao_normaliza_data(monkeypatch):
    # Schema legado (TEXT): compara YYYYMMDD sem formatacao.
    monkeypatch.setattr("backend.db.service.get_tipos_dados_empresas", lambda: {})
    where, params = _where_empresas(fundacao_de="2020-01-15", fundacao_ate="2023-12-31")
    assert '"DATA_FUNDACAO"' in where
    assert "20200115" in params
    assert "20231231" in params


def test_where_fundacao_date_usa_cast(monkeypatch):
    # Prod pos-nivel1 (DATE): compara como data.
    monkeypatch.setattr(
        "backend.db.service.get_tipos_dados_empresas",
        lambda: {"DATA_FUNDACAO": "date", "DIVIDA_TOTAL": "numeric", "CAPITAL_SOCIAL": "numeric"},
    )
    where, params = _where_empresas(fundacao_de="2020-01-15", fundacao_ate="20231231")
    assert "::date" in where
    assert "2020-01-15" in params
    assert "2023-12-31" in params


def test_where_faixas_usam_coluna_direta_quando_numeric(monkeypatch):
    monkeypatch.setattr(
        "backend.db.service.get_tipos_dados_empresas",
        lambda: {"DIVIDA_TOTAL": "numeric", "CAPITAL_SOCIAL": "numeric"},
    )
    where, _ = _where_empresas(divida_min=1000, capital_max=50000)
    assert "::text" not in where
    assert "DIVIDA_TOTAL" in where and "CAPITAL_SOCIAL" in where
