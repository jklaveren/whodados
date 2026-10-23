"""MEI nao tem socio na Receita: a pessoa esta' no nome empresarial.

Os tres formatos abaixo sao os que existem na leva de beleza do Beta. Antes,
so' o primeiro virava saudacao, {{nome_socio}} saia vazio nos tres e o CPF do
segundo ia parar dentro do e-mail como parte do nome da empresa.
"""
import pytest

from backend.mailer import service as mailer
from backend.titular import titular

CNPJ_NA_FRENTE = "12.345.678 ANA CLARA DOS SANTOS"
CPF_NO_FIM = "BEATRIZ LIMA DE SOUZA 12345678900"
SO_O_NOME = "CARLA MENDES DA SILVA"


@pytest.mark.parametrize("razao,esperado", [
    (CNPJ_NA_FRENTE, "ANA CLARA DOS SANTOS"),
    (CPF_NO_FIM, "BEATRIZ LIMA DE SOUZA"),
    (SO_O_NOME, "CARLA MENDES DA SILVA"),
])
def test_titular_dos_tres_formatos(razao, esperado):
    assert titular(razao, "MEI") == esperado


def test_empresa_comum_nao_vira_socia_de_si_mesma():
    assert titular("PADARIA CENTRAL LTDA", "ME") == ""
    assert titular("PADARIA CENTRAL", None) == "", "sem documento e sem porte MEI nao da' pra afirmar"


def _montar(razao):
    tpl = {"assunto": "{{saudacao}}", "corpo_texto": "",
           "corpo_html": "[{{nome_socio}}] [{{empresa}}]"}
    dados = {"razao_social": razao, "porte_nome": "MEI", "municipio": "GUAIBA",
             "cnae_principal": "9602501", "cnae_descricao": "Cabeleireiros"}
    return mailer.montar_email_para_cnpj(tpl, "12345678000100", "x@y.com", dados)


@pytest.mark.parametrize("razao,primeiro,inteiro", [
    (CNPJ_NA_FRENTE, "Ana", "Ana Clara dos Santos"),
    (CPF_NO_FIM, "Beatriz", "Beatriz Lima de Souza"),
    (SO_O_NOME, "Carla", "Carla Mendes da Silva"),
])
def test_email_do_mei_fala_com_a_pessoa(razao, primeiro, inteiro):
    e = _montar(razao)
    assert e["assunto"] == primeiro
    assert e["variaveis"]["nome_socio"] == inteiro


def test_documento_nao_vai_no_corpo_do_email():
    corpo = _montar(CPF_NO_FIM)["corpo_html"]
    assert "12345678900" not in corpo
    assert "12.345.678" not in _montar(CNPJ_NA_FRENTE)["corpo_html"]


def test_socio_da_receita_continua_valendo():
    """Quando ha' socio de verdade, ele vence o nome empresarial."""
    tpl = {"assunto": "{{saudacao}}", "corpo_html": "", "corpo_texto": ""}
    e = mailer.montar_email_para_cnpj(tpl, "1", "x@y.com", {
        "razao_social": "PADARIA CENTRAL LTDA", "nome_socio": "JOAO PEREIRA",
        "cnae_principal": "", "cnae_descricao": ""})
    assert e["assunto"] == "Joao"
