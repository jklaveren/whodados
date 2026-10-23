"""
Sincroniza os CSVs gerados pelo pipeline para o banco Postgres (Supabase).
LOCAL: whodados/scripts/sync_data_to_db.py

Uso:
    DATABASE_URL="<connection-string>" python whodados/scripts/sync_data_to_db.py
"""
import os
import sys
from pathlib import Path

# Adiciona a raiz do repo ao sys.path para encontrar database_config.py.
# parents[2] = raiz do repo (que contem whodados/).
_RAIZ = Path(__file__).resolve().parents[2]
for _caminho in (_RAIZ, _RAIZ / "analise-empresarial-streamlit"):
    if _caminho.exists() and str(_caminho) not in sys.path:
        sys.path.insert(0, str(_caminho))

import pandas as pd

from database_config import (
    EXPECTED_EMPRESA_COLUMNS,
    EXPECTED_SOCIO_COLUMNS,
    create_db_engine,
    criar_indices_dados,
    dtypes_empresas,
    dtypes_socios,
    ensure_app_tables,
    garantir_colunas_obrigatorias,
    get_data_table_names,
    registrar_metadata_pipeline,
    TABELA_CNAES,
    TABELA_MUNICIPIOS,
)
import json
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parents[1]
# WHODADOS_DATA_DIR aponta para onde o pipeline em levas gravou os CSVs
# que fica fora do repositorio.
DATA_DIR = (Path(os.environ["WHODADOS_DATA_DIR"]) if os.environ.get("WHODADOS_DATA_DIR")
            else BASE_DIR / "pipeline" / "out")

ARQ_EMPRESAS = DATA_DIR / "subset_rs_final_completo.csv"
ARQ_SOCIOS = DATA_DIR / "socios_rs.csv"
ARQ_MUNICIPIOS = DATA_DIR / "municipios.csv"
ARQ_CNAES = DATA_DIR / "cnaes.csv"
ARQ_METADATA = DATA_DIR / "metadata_pipeline.json"


def carregar_csvs():
    if not ARQ_EMPRESAS.exists() or not ARQ_SOCIOS.exists():
        faltantes = [str(p) for p in (ARQ_EMPRESAS, ARQ_SOCIOS) if not p.exists()]
        raise FileNotFoundError(
            "Arquivos de origem nao encontrados: "
            + ", ".join(faltantes)
            + ". Rode antes o pipeline (whodados/pipeline/pipeline.py)."
        )

    empresas = pd.read_csv(ARQ_EMPRESAS, sep=";", encoding="latin-1", dtype=str)
    socios = pd.read_csv(ARQ_SOCIOS, sep=";", encoding="utf-8", dtype=str)

    if empresas.empty:
        raise ValueError(f"'{ARQ_EMPRESAS.name}' esta vazio. Abortando.")
    if socios.empty:
        raise ValueError(f"'{ARQ_SOCIOS.name}' esta vazio. Abortando.")

    empresas = garantir_colunas_obrigatorias(empresas, EXPECTED_EMPRESA_COLUMNS)
    socios = garantir_colunas_obrigatorias(socios, EXPECTED_SOCIO_COLUMNS)

    # Converte tipos ANTES do to_sql pra que os dtypes SQL explicitos (NUMERIC,
    # DATE) recebam os valores certos e nao tudo como string.
    for col in ("CAPITAL_SOCIAL", "DIVIDA_FEDERAL", "DIVIDA_PREVIDENCIARIA",
                "DIVIDA_FGTS", "DIVIDA_TOTAL"):
        if col in empresas.columns:
            empresas[col] = pd.to_numeric(
                empresas[col].astype(str).str.replace(",", "."),
                errors="coerce",
            )
    if "DATA_FUNDACAO" in empresas.columns:
        # O pipeline em levas grava AAAA-MM-DD; o antigo gravava AAAAMMDD.
        # Com um formato so, todas as datas do outro virariam NULL em silencio.
        bruto = empresas["DATA_FUNDACAO"]
        data = pd.to_datetime(bruto, format="%Y-%m-%d", errors="coerce")
        data = data.fillna(pd.to_datetime(bruto, format="%Y%m%d", errors="coerce"))
        empresas["DATA_FUNDACAO"] = data.dt.date

    return empresas, socios


def _ler_dominio(caminho, renomear, colunas):
    """Le uma tabela codigo -> descricao. Aceita o formato do pipeline em
    levas (CODIGO;DESCRICAO, latin1) e o antigo (nomes proprios, utf-8)."""
    if not caminho.exists():
        print(f"[AVISO] '{caminho.name}' nao encontrado, pulando.")
        return None
    try:
        df = pd.read_csv(caminho, sep=";", encoding="utf-8", dtype=str)
    except UnicodeDecodeError:
        df = pd.read_csv(caminho, sep=";", encoding="latin-1", dtype=str)
    df = df.rename(columns=renomear)
    if df.empty or not set(colunas) <= set(df.columns):
        print(f"[AVISO] '{caminho.name}' vazio ou sem as colunas {colunas} "
              f"(tem {list(df.columns)}), pulando.")
        return None
    df = df[colunas].dropna(subset=[colunas[0]])
    return df.drop_duplicates(subset=[colunas[0]])


def carregar_municipios():
    return _ler_dominio(
        ARQ_MUNICIPIOS,
        {"CODIGO": "cod_municipio", "DESCRICAO": "nome_municipio",
         "COD_MUNICIPIO": "cod_municipio", "NOME_MUNICIPIO": "nome_municipio"},
        ["cod_municipio", "nome_municipio"],
    )


def carregar_cnaes():
    return _ler_dominio(
        ARQ_CNAES,
        {"CODIGO": "codigo_cnae", "DESCRICAO": "descricao_cnae",
         "CODIGO_CNAE": "codigo_cnae", "DESCRICAO_CNAE": "descricao_cnae"},
        ["codigo_cnae", "descricao_cnae"],
    )


def main():
    ensure_app_tables()
    engine = create_db_engine()
    tabelas = get_data_table_names()

    try:
        empresas, socios = carregar_csvs()
    except (FileNotFoundError, ValueError) as erro:
        print(f"Sincronizacao abortada: {erro}", file=sys.stderr)
        sys.exit(1)

    # dtype=... define o tipo SQL de cada coluna (NUMERIC, DATE, VARCHAR(N))
    # em vez de tudo TEXT ilimitado. Reduz espaco no disco do Postgres e
    # deixa queries analiticas (SUM, GROUP BY numerico) mais rapidas.
    empresas.to_sql(
        tabelas["empresas"], engine, if_exists="replace", index=False,
        chunksize=5000, dtype=dtypes_empresas(),
    )
    socios.to_sql(
        tabelas["socios"], engine, if_exists="replace", index=False,
        chunksize=5000, dtype=dtypes_socios(),
    )
    print(f"OK Tabela de empresas atualizada: {tabelas['empresas']} ({len(empresas)} linhas)")
    print(f"OK Tabela de socios atualizada: {tabelas['socios']} ({len(socios)} linhas)")

    # dtype= explicito e obrigatorio aqui: sem isso o pandas cria as colunas
    # de codigo como TEXT plano, enquanto dados_empresas usa VARCHAR(10)
    # (dtypes_empresas). O JOIN entre tipos diferentes forca um cast que
    # quebra a estimativa de selectividade do Postgres -- uma consulta de
    # ~1s vira 25-30s (bug real encontrado em producao em 15/09/2026, ver
    # whodados/scripts/fix_tipos_dominio.sql para o reparo do banco atual).
    from sqlalchemy import types as _t

    municipios = carregar_municipios()
    if municipios is not None:
        municipios.to_sql(TABELA_MUNICIPIOS, engine, if_exists="replace", index=False,
                          chunksize=5000, dtype={"cod_municipio": _t.String(10),
                                                  "nome_municipio": _t.String(200)})
        print(f"OK Tabela de municipios atualizada: {TABELA_MUNICIPIOS} ({len(municipios)} linhas)")

    cnaes = carregar_cnaes()
    if cnaes is not None:
        cnaes.to_sql(TABELA_CNAES, engine, if_exists="replace", index=False,
                     chunksize=5000, dtype={"codigo_cnae": _t.String(10),
                                            "descricao_cnae": _t.String(300)})
        print(f"OK Tabela de cnaes atualizada: {TABELA_CNAES} ({len(cnaes)} linhas)")

    criar_indices_dados()
    print("OK Indices recriados.")

    registrar_metadata_sincronizacao(len(empresas), len(socios))


def registrar_metadata_sincronizacao(total_empresas: int, total_socios: int) -> None:
    """Combina o metadata gravado pelo pipeline (mes RF, trimestre PGFN,
    quando foi gerado) com o resultado desta sincronizacao e grava tudo na
    tabela pipeline_metadata -- e o que a tela "Sobre" no frontend le."""
    dados = {
        "ultima_sincronizacao": datetime.now(timezone.utc).isoformat(),
        "total_empresas_sincronizadas": total_empresas,
        "total_socios_sincronizados": total_socios,
    }
    if ARQ_METADATA.exists():
        try:
            with open(ARQ_METADATA, "r", encoding="utf-8") as f:
                meta_pipeline = json.load(f)
            dados.update(meta_pipeline)
        except Exception as e:
            print(f"[AVISO] Nao foi possivel ler '{ARQ_METADATA.name}': {e}")
    else:
        print(f"[AVISO] '{ARQ_METADATA.name}' nao encontrado -- pipeline pode ter rodado "
              f"antes dessa funcionalidade existir. Seguindo sem mes/trimestre de referencia.")

    registrar_metadata_pipeline(dados)
    print(f"OK Metadata da sincronizacao registrado: {dados}")


if __name__ == "__main__":
    main()
