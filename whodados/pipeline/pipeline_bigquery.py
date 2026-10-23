"""Carga dos dados de CNPJ via BigQuery publico da Base dos Dados.

Alternativa ao download direto da Receita Federal: consulta os mesmos dados
ja' espelhados em `basedosdados.br_me_cnpj`. O download direto falha quando
roda de runner de nuvem, porque o IP de datacenter cai no anti-abuso da RF;
BigQuery e' chamada de API autenticada, entao o bloqueio por IP deixa de
pesar.

Variaveis de ambiente:
    BD_BILLING_PROJECT_ID           projeto GCP, so' para cobranca da consulta
    GOOGLE_APPLICATION_CREDENTIALS  caminho do JSON da service account, ou
    GCP_SERVICE_ACCOUNT_JSON        o JSON inteiro (uso em CI)
    DATABASE_URL                    destino da carga
    UF_ALVO                         padrao "RS"

A service account precisa do papel BigQuery Job User no projeto de cobranca;
os dados em si sao publicos.

    python pipeline_bigquery.py --check-schema   # lista as colunas reais
    python pipeline_bigquery.py                  # roda a carga
"""
import argparse
import os
import sys
from pathlib import Path

import pandas as pd

try:
    from google.cloud import bigquery
except ImportError:
    print("Instale as dependencias: pip install google-cloud-bigquery db-dtypes")
    sys.exit(1)

UF = os.environ.get("UF_ALVO", "RS").strip().upper()
BILLING_PROJECT = os.environ.get("BD_BILLING_PROJECT_ID", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
BASE_DIR = Path(os.environ.get("BASE_DIR", "./dados_bigquery"))
OUT = BASE_DIR / "out"
OUT.mkdir(parents=True, exist_ok=True)
ARQUIVO_FINAL = OUT / "subset_rs_final_completo.csv"

# Credenciais da service account: aceita um arquivo (uso local) ou o JSON
# inteiro numa env var (uso no CI, sem precisar de um step so pra gravar
# o arquivo antes de rodar o pipeline).
_cred_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "").strip()
if _cred_json and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    cred_path = Path(os.environ.get("RUNNER_TEMP") or os.environ.get("TEMP") or "/tmp") / "bd_service_account.json"
    cred_path.write_text(_cred_json, encoding="utf-8")
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(cred_path)


def _checar_config():
    faltando = []
    if not BILLING_PROJECT:
        faltando.append("BD_BILLING_PROJECT_ID")
    if not (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or _cred_json):
        faltando.append("GOOGLE_APPLICATION_CREDENTIALS ou GCP_SERVICE_ACCOUNT_JSON")
    if faltando:
        print(f"ERRO: defina {', '.join(faltando)} antes de rodar.")
        sys.exit(1)


_bq_client = None


def _client() -> "bigquery.Client":
    """Cliente do BigQuery autenticado via Application Default Credentials
    (GOOGLE_APPLICATION_CREDENTIALS) -- sem login interativo, funciona num
    runner sem tela como o GitHub Actions. `project` aqui e' so o projeto
    que paga pela consulta; os dados continuam vindo do projeto publico
    `basedosdados`, referenciado por nome completo em cada FROM."""
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=BILLING_PROJECT)
    return _bq_client


def _query(sql: str) -> pd.DataFrame:
    print(f"Consultando BigQuery...\n{sql}\n")
    return _client().query(sql).to_dataframe()


def checar_schema():
    """Lista as colunas reais das tabelas usadas -- roda isso ANTES da
    primeira carga de verdade pra confirmar que os nomes usados nos
    SELECTs abaixo batem com o schema atual do BigQuery."""
    tabelas = ["estabelecimentos", "empresas", "socios", "simples"]
    for tabela in tabelas:
        sql = f"""
        SELECT column_name, data_type
        FROM `basedosdados.br_me_cnpj.INFORMATION_SCHEMA.COLUMNS`
        WHERE table_name = '{tabela}'
        ORDER BY ordinal_position
        """
        df = _query(sql)
        print(f"=== br_me_cnpj.{tabela} ({len(df)} colunas) ===")
        print(df.to_string(index=False))
        print()


def extrair_empresas(uf: str) -> pd.DataFrame:
    """Matrizes ativas no estado alvo, com dados de empresa e Simples/MEI.
    identificador_matriz_filial='1' e situacao_cadastral='02' seguem o
    mesmo criterio (so matriz, so ativa) do pipeline_levas.py atual."""
    sql = f"""
    SELECT
        est.cnpj_basico AS CNPJ_BASICO,
        CONCAT(est.cnpj_basico, est.cnpj_ordem, est.cnpj_dv) AS CNPJ_COMPLETO,
        emp.razao_social AS RAZAO_SOCIAL,
        est.nome_fantasia AS NOME_FANTASIA,
        est.data_inicio_atividade AS DATA_FUNDACAO,
        est.cnae_fiscal_principal AS CNAE_PRINCIPAL,
        est.cnae_fiscal_secundaria AS CNAE_SECUNDARIA,
        est.logradouro AS LOGRADOURO,
        est.numero AS NUMERO,
        est.complemento AS COMPLEMENTO,
        est.bairro AS BAIRRO,
        est.cep AS CEP,
        est.id_municipio AS COD_MUNICIPIO,
        est.ddd1 AS DDD,
        est.telefone1 AS TELEFONE,
        CONCAT(COALESCE(est.ddd2, ''), COALESCE(est.telefone2, '')) AS TELEFONE_2,
        est.email AS EMAIL,
        emp.capital_social AS CAPITAL_SOCIAL,
        emp.porte_empresa AS PORTE_EMPRESA,
        emp.natureza_juridica AS NATUREZA_JURIDICA,
        emp.qualificacao_responsavel AS QUALIF_RESPONSAVEL,
        sim.opcao_simples AS OPCAO_SIMPLES,
        sim.opcao_mei AS OPCAO_MEI
    FROM `basedosdados.br_me_cnpj.estabelecimentos` AS est
    JOIN `basedosdados.br_me_cnpj.empresas` AS emp USING (cnpj_basico)
    LEFT JOIN `basedosdados.br_me_cnpj.simples` AS sim USING (cnpj_basico)
    WHERE est.sigla_uf = '{uf}'
      AND est.identificador_matriz_filial = '1'
      AND est.situacao_cadastral = '02'
    """
    return _query(sql)


def extrair_socios(uf: str) -> pd.DataFrame:
    sql = f"""
    SELECT DISTINCT
        soc.cnpj_basico AS CNPJ_BASICO,
        soc.identificador_socio AS IDENTIFICADOR_SOCIO,
        soc.nome_socio AS NOME_SOCIO,
        soc.cnpj_cpf_socio AS CPF_CNPJ_SOCIO,
        soc.qualificacao_socio AS QUALIF_SOCIO,
        soc.data_entrada_sociedade AS DATA_ENTRADA,
        soc.faixa_etaria AS FAIXA_ETARIA
    FROM `basedosdados.br_me_cnpj.socios` AS soc
    JOIN `basedosdados.br_me_cnpj.estabelecimentos` AS est USING (cnpj_basico)
    WHERE est.sigla_uf = '{uf}' AND est.identificador_matriz_filial = '1'
    """
    return _query(sql)


def extrair_dividas(uf: str) -> pd.DataFrame:
    """PLACEHOLDER -- dataset_id/table_id da Divida Ativa da União (PGFN)
    na Base dos Dados nao foi confirmado ainda (a busca achou o dataset
    "Dividas Ativa da Uniao" no site, mas nao o caminho basedosdados.XXX.YYY
    exato). Antes de usar em producao:
      1. Abra https://basedosdados.org/dataset/ebde2dae-5c45-40f1-aef2-81ca81cb7438
         logado, e copie o "dataset_id"/"table_id" mostrados no botao
         "Acessar dados" (BigQuery).
      2. Ajuste FROM/colunas abaixo pra bater com o que estiver la.
      3. Rode extrair_dividas('RS') sozinho num teste e confira o resultado
         antes de plugar no restante do pipeline.
    Ate isso ser feito, esta funcao retorna vazio e DIVIDA_* fica zerada
    (mesmo comportamento de quando DATABASE_URL falta hoje: nao trava o
    pipeline, so nao preenche a divida)."""
    print("[AVISO] extrair_dividas: dataset da PGFN ainda nao confirmado -- retornando vazio.")
    return pd.DataFrame(columns=["CNPJ_BASICO", "DIVIDA_FEDERAL", "DIVIDA_PREVIDENCIARIA", "DIVIDA_FGTS"])


def montar_master(uf: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    empresas = extrair_empresas(uf)
    print(f"✅ {len(empresas):,} matrizes ativas em {uf}")

    dividas = extrair_dividas(uf)
    if not dividas.empty:
        empresas = empresas.merge(dividas, on="CNPJ_BASICO", how="left")
    for col in ["DIVIDA_FEDERAL", "DIVIDA_PREVIDENCIARIA", "DIVIDA_FGTS"]:
        if col not in empresas.columns:
            empresas[col] = 0.0
        empresas[col] = pd.to_numeric(empresas[col], errors="coerce").fillna(0.0)
    empresas["DIVIDA_TOTAL"] = (
        empresas["DIVIDA_FEDERAL"] + empresas["DIVIDA_PREVIDENCIARIA"] + empresas["DIVIDA_FGTS"]
    )

    empresas["CAPITAL_SOCIAL"] = pd.to_numeric(empresas["CAPITAL_SOCIAL"], errors="coerce").fillna(0.0)
    empresas["DATA_FUNDACAO"] = pd.to_datetime(empresas["DATA_FUNDACAO"], errors="coerce")

    socios = extrair_socios(uf)
    print(f"✅ {len(socios):,} socios")

    return empresas, socios


def carregar_supabase(master: pd.DataFrame, socios: pd.DataFrame):
    if not DATABASE_URL:
        print("\n⚠️  DATABASE_URL não definida — dados ficaram só em CSV.")
        return
    print(f"\n{'='*70}\nCarregando no Supabase\n{'='*70}")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from database_config import criar_indices_dados, dtypes_empresas, dtypes_socios
    from sqlalchemy import create_engine

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    master.to_sql("dados_empresas", engine, if_exists="replace", index=False,
                  chunksize=5000, method="multi", dtype=dtypes_empresas())
    print(f"✅ dados_empresas: {len(master):,} linhas")

    if not socios.empty:
        socios.to_sql("dados_socios", engine, if_exists="replace", index=False,
                      chunksize=5000, method="multi", dtype=dtypes_socios())
        print(f"✅ dados_socios: {len(socios):,} linhas")

    criar_indices_dados()
    print("✅ indices recriados")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-schema", action="store_true",
                        help="So lista as colunas reais das tabelas no BigQuery, nao carrega nada.")
    args = parser.parse_args()

    _checar_config()

    if args.check_schema:
        checar_schema()
        return

    master, socios = montar_master(UF)
    master.to_csv(ARQUIVO_FINAL, sep=";", index=False, encoding="latin1")
    print(f"✅ {len(master):,} empresas consolidadas -> {ARQUIVO_FINAL}")

    carregar_supabase(master, socios)

    print(f"\n{'='*70}\n✅ CONCLUÍDO (via Base dos Dados / BigQuery)\n{'='*70}")
    print(f"  UF .................... {UF}")
    print(f"  Matrizes ativas ....... {len(master):,}")
    print(f"  DIVIDA_TOTAL .......... R$ {master['DIVIDA_TOTAL'].sum():,.2f}")
    print(f"  Arquivo ............... {ARQUIVO_FINAL}")


if __name__ == "__main__":
    main()
