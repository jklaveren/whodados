"""
Sincroniza SOMENTE as colunas de divida (DIVIDA_FEDERAL, DIVIDA_PREVIDENCIARIA,
DIVIDA_FGTS, DIVIDA_TOTAL) em dados_empresas no Supabase, a partir do
aux_dividas_pgfn.csv gerado por pipeline_pgfn.py.

Serve pra desacoplar: se o estagio 1 do pipeline (download da Receita
Federal) travar, esse script destrava atualizar as dividas ainda hoje --
sem esperar o RF nem re-baixar o subset de empresas.

USO:
    # 1. Rode local o lado PGFN do pipeline:
    cd whodados/pipeline
    python pipeline_pgfn.py download-pgfn
    python pipeline_pgfn.py process-pgfn

    # 2. Aponte pro Supabase e sincronize so as dividas:
    export DATABASE_URL="postgresql://..."
    cd ../..
    python whodados/scripts/sync_dividas_only.py

O que ele faz no banco:
- Cria uma STAGING TABLE temporaria (unlogged) com as dividas do CSV.
- Faz UPDATE ... FROM stage WHERE CNPJ_BASICO = ... nas 4 colunas
  DIVIDA_* de dados_empresas. Nao mexe em nenhuma outra coluna, nao dropa
  tabela, nao roda replace.
- Se dados_empresas nao existir ainda (pipeline nunca rodou por inteiro),
  aborta com mensagem explicando -- este script atualiza, nao popula do
  zero.

LOCAL: whodados/scripts/sync_dividas_only.py
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

BASE_DIR = Path(__file__).resolve().parents[1]
ARQ_DIVIDAS = BASE_DIR / "pipeline" / "out" / "aux_dividas_pgfn.csv"

COLUNAS_DIVIDA = ("DIVIDA_FEDERAL", "DIVIDA_PREVIDENCIARIA", "DIVIDA_FGTS", "DIVIDA_TOTAL")


def _conectar():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("ERRO: DATABASE_URL nao configurada. Exporte a connection string do Supabase.", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(url)


def _carregar_csv() -> pd.DataFrame:
    if not ARQ_DIVIDAS.exists():
        print(
            f"ERRO: {ARQ_DIVIDAS} nao encontrado. Rode antes:\n"
            "  cd whodados/pipeline\n"
            "  python pipeline_pgfn.py download-pgfn\n"
            "  python pipeline_pgfn.py process-pgfn",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pd.read_csv(ARQ_DIVIDAS, sep=";", encoding="utf-8", dtype=str)
    faltando = [c for c in ("CNPJ_BASICO", *COLUNAS_DIVIDA) if c not in df.columns]
    if faltando:
        print(f"ERRO: {ARQ_DIVIDAS.name} sem as colunas esperadas: {faltando}", file=sys.stderr)
        sys.exit(1)

    for col in COLUNAS_DIVIDA:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["CNPJ_BASICO"] = df["CNPJ_BASICO"].astype(str).str.zfill(8)
    df = df[df["CNPJ_BASICO"].str.len() == 8]
    return df[["CNPJ_BASICO", *COLUNAS_DIVIDA]]


def _tabela_existe(cur, nome: str) -> bool:
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
        (nome,),
    )
    return bool(cur.fetchone()[0])


def _colunas_existem(cur, tabela: str, colunas: tuple[str, ...]) -> list[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (tabela,),
    )
    existentes = {r[0] for r in cur.fetchall()}
    return [c for c in colunas if c not in existentes]


def _cnpjs_existentes(cur) -> set[str]:
    """Le todos os CNPJ_BASICO de dados_empresas. Usado pra filtrar o CSV
    da PGFN (Brasil inteiro, ~6.7M linhas) pra apenas os CNPJs que a
    gente tem no subset (RS, ~700k). Corta 90% do volume que vai pra
    staging -- evita SSL timeout durante o UPDATE massivo, principal
    motivo do sync anterior ter caido no meio."""
    cur.execute('SELECT DISTINCT "CNPJ_BASICO" FROM dados_empresas')
    return {r[0].strip() for r in cur.fetchall() if r[0]}


def main() -> None:
    df = _carregar_csv()
    print(f"OK CSV lido: {len(df)} linhas (Brasil inteiro).")

    conn = _conectar()
    try:
        with conn.cursor() as cur:
            if not _tabela_existe(cur, "dados_empresas"):
                print(
                    "ERRO: tabela 'dados_empresas' nao existe no banco. Este script atualiza\n"
                    "so as colunas de divida -- ele nao popula empresas do zero. Rode o\n"
                    "pipeline inteiro (whodados-etl.yml) uma vez pra criar a tabela.",
                    file=sys.stderr,
                )
                sys.exit(1)

            faltando = _colunas_existem(cur, "dados_empresas", COLUNAS_DIVIDA)
            if faltando:
                # Adiciona as colunas caso a tabela seja de uma versao antiga
                # (so tinha DIVIDA_TOTAL). Aditivo, nao destrutivo.
                for col in faltando:
                    cur.execute(
                        f'ALTER TABLE dados_empresas ADD COLUMN IF NOT EXISTS "{col}" NUMERIC DEFAULT 0'
                    )
                print(f"OK Colunas adicionadas em dados_empresas: {faltando}")

            # FILTRO NA ORIGEM: le os CNPJ_BASICO ja presentes na tabela
            # e mantem no DataFrame apenas as dividas dessas empresas.
            # Sem isso: subiria ~6.7M linhas de dividas do Brasil pra
            # staging so pra usar ~10% no UPDATE final. Com isso: subimos
            # so os ~700k que interessam. Corta 90% de I/O e memoria de
            # trabalho -- evita o SSL timeout do Supabase.
            cnpjs_rs = _cnpjs_existentes(cur)
            print(f"OK dados_empresas tem {len(cnpjs_rs)} CNPJs (subset RS).")
            df = df[df["CNPJ_BASICO"].isin(cnpjs_rs)]
            print(f"OK CSV filtrado: {len(df)} linhas relevantes ao subset RS.")

            # Staging table temporaria (some junto com a conexao).
            cur.execute(
                """
                CREATE TEMP TABLE stage_dividas (
                    "CNPJ_BASICO" VARCHAR(8) PRIMARY KEY,
                    "DIVIDA_FEDERAL" NUMERIC,
                    "DIVIDA_PREVIDENCIARIA" NUMERIC,
                    "DIVIDA_FGTS" NUMERIC,
                    "DIVIDA_TOTAL" NUMERIC
                ) ON COMMIT DROP
                """
            )

            registros = list(
                df[["CNPJ_BASICO", *COLUNAS_DIVIDA]].itertuples(index=False, name=None)
            )
            execute_values(
                cur,
                'INSERT INTO stage_dividas ("CNPJ_BASICO", "DIVIDA_FEDERAL", '
                '"DIVIDA_PREVIDENCIARIA", "DIVIDA_FGTS", "DIVIDA_TOTAL") VALUES %s',
                registros,
                page_size=5000,
            )
            print(f"OK Staging carregada: {len(registros)} linhas.")

            # UPDATE atomico com LEFT JOIN + COALESCE: empresa que aparece
            # no stage recebe os valores da PGFN; a que nao aparece
            # (fora do trimestre atual) e ZERADA. Um unico UPDATE em vez
            # de dois -- metade do WAL, metade da chance de timeout.
            cur.execute(
                """
                UPDATE dados_empresas e SET
                    "DIVIDA_FEDERAL"        = COALESCE(s."DIVIDA_FEDERAL", 0),
                    "DIVIDA_PREVIDENCIARIA" = COALESCE(s."DIVIDA_PREVIDENCIARIA", 0),
                    "DIVIDA_FGTS"           = COALESCE(s."DIVIDA_FGTS", 0),
                    "DIVIDA_TOTAL"          = COALESCE(s."DIVIDA_TOTAL", 0)
                FROM (
                    SELECT e2."CNPJ_BASICO",
                           s2."DIVIDA_FEDERAL",
                           s2."DIVIDA_PREVIDENCIARIA",
                           s2."DIVIDA_FGTS",
                           s2."DIVIDA_TOTAL"
                    FROM dados_empresas e2
                    LEFT JOIN stage_dividas s2
                        ON e2."CNPJ_BASICO" = s2."CNPJ_BASICO"
                ) s
                WHERE e."CNPJ_BASICO" = s."CNPJ_BASICO"
                """
            )
            afetadas = cur.rowcount
            print(f"OK dados_empresas atualizada: {afetadas} linhas.")

            cur.execute(
                'SELECT COUNT(*) FROM dados_empresas WHERE "DIVIDA_TOTAL" > 0'
            )
            with_debt = cur.fetchone()[0]
            cur.execute('SELECT COALESCE(SUM("DIVIDA_TOTAL"), 0) FROM dados_empresas')
            total = cur.fetchone()[0]
            print(f"   Empresas com divida > 0: {with_debt}")
            print(f"   Divida total agregada: R$ {float(total):,.2f}")

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
