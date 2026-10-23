"""
database_config.py -- Configuracao e schema para sincronizar os dados
extraidos da Receita Federal / PGFN (whodados/pipeline/pipeline.py) com o
Postgres (Supabase).

Define o schema de destino e o mapeamento de colunas da carga. Usado por
whodados/scripts/sync_data_to_db.py. A automacao via GitHub
Actions foi removida em 2026-09.

As tabelas de DADOS criadas aqui (dados_empresas, dados_socios, municipios)
sao distintas das tabelas da APLICACAO (crm, campanhas, notificacoes, etc.),
que sao criadas pelo backend FastAPI na inicializacao
(whodados/backend/db/config.py::ensure_tables_exist).
"""
from __future__ import annotations
import os

TABELA_EMPRESAS = "dados_empresas"
TABELA_SOCIOS = "dados_socios"
TABELA_MUNICIPIOS = "municipios"
TABELA_CNAES = "cnaes"
TABELA_METADATA = "pipeline_metadata"


def get_data_table_names() -> dict:
    """Nomes das tabelas de dados no Postgres."""
    return {"empresas": TABELA_EMPRESAS, "socios": TABELA_SOCIOS}


# Colunas produzidas por whodados/pipeline/pipeline.py::gerar_master()
# (arquivo out/subset_rs_final_completo.csv)
#
# NOTA: CONTATO_FONE e PORTE_NOME (que existiam antes) foram removidos --
# ambos eram derivados de outras colunas (DDD+TELEFONE e PORTE_EMPRESA) e
# so inflavam a tabela sem carregar informacao nova. O backend deriva os
# dois on-the-fly nos SELECTs (ver service.py / analytics.py).
EXPECTED_EMPRESA_COLUMNS = [
    "CNPJ_BASICO", "CNPJ_COMPLETO", "RAZAO_SOCIAL", "NOME_FANTASIA",
    "DATA_FUNDACAO", "CNAE_PRINCIPAL", "LOGRADOURO", "NUMERO", "COMPLEMENTO",
    "BAIRRO", "CEP", "COD_MUNICIPIO", "DDD", "TELEFONE", "TELEFONE_2", "EMAIL",
    "CAPITAL_SOCIAL", "PORTE_EMPRESA",
    "CNAE_SECUNDARIA", "NATUREZA_JURIDICA", "QUALIF_RESPONSAVEL",
    "OPCAO_SIMPLES", "OPCAO_MEI",
    "DIVIDA_FEDERAL", "DIVIDA_PREVIDENCIARIA", "DIVIDA_FGTS", "DIVIDA_TOTAL",
]

# Colunas produzidas por whodados/pipeline/pipeline.py::filtrar_socios()
# (arquivo out/socios_rs.csv)
EXPECTED_SOCIO_COLUMNS = [
    "CNPJ_BASICO", "IDENTIFICADOR_SOCIO", "NOME_SOCIO",
    "CPF_CNPJ_SOCIO", "QUALIF_SOCIO", "DATA_ENTRADA", "FAIXA_ETARIA",
]


def dtypes_empresas() -> dict:
    """Tipos SQL explicitos pro to_sql do pandas gravar cada coluna com o
    tipo certo em vez de tudo como TEXT ilimitado.

    Ganho principal: DIVIDA_* e CAPITAL_SOCIAL como NUMERIC (bytes fixos)
    em vez de TEXT (strlen). DATA_FUNDACAO como DATE (4 bytes vs 8 chars).
    Codigos com tamanho fixo ganham validacao (evita string monstro por bug).
    """
    from sqlalchemy import types as t
    return {
        "CNPJ_BASICO":           t.CHAR(8),
        "CNPJ_COMPLETO":         t.CHAR(14),
        "RAZAO_SOCIAL":          t.String(300),
        "NOME_FANTASIA":         t.String(300),
        "DATA_FUNDACAO":         t.Date(),
        "CNAE_PRINCIPAL":        t.String(10),
        "LOGRADOURO":            t.String(300),
        "NUMERO":                t.String(20),
        "COMPLEMENTO":           t.String(200),
        "BAIRRO":                t.String(200),
        "CEP":                   t.String(10),
        "COD_MUNICIPIO":         t.String(10),
        "DDD":                   t.String(4),
        "TELEFONE":              t.String(30),
        "TELEFONE_2":            t.String(30),
        "EMAIL":                 t.String(255),
        "CAPITAL_SOCIAL":        t.Numeric(18, 2),
        "PORTE_EMPRESA":         t.CHAR(2),
        # Lista separada por virgula -- uma empresa costuma ter varias.
        "CNAE_SECUNDARIA":       t.Text(),
        "NATUREZA_JURIDICA":     t.String(10),
        "QUALIF_RESPONSAVEL":    t.String(4),
        "OPCAO_SIMPLES":         t.CHAR(1),
        "OPCAO_MEI":             t.CHAR(1),
        "DIVIDA_FEDERAL":        t.Numeric(18, 2),
        "DIVIDA_PREVIDENCIARIA": t.Numeric(18, 2),
        "DIVIDA_FGTS":           t.Numeric(18, 2),
        "DIVIDA_TOTAL":          t.Numeric(18, 2),
    }


def dtypes_socios() -> dict:
    """Tipos SQL explicitos pra dados_socios."""
    from sqlalchemy import types as t
    return {
        "CNPJ_BASICO":         t.CHAR(8),
        "IDENTIFICADOR_SOCIO": t.CHAR(1),
        "NOME_SOCIO":          t.String(200),
        "CPF_CNPJ_SOCIO":      t.String(20),
        "QUALIF_SOCIO":        t.String(4),
        "DATA_ENTRADA":        t.String(8),
        # Codigo de faixa etaria da RF. A traducao (faixa -> anos) fica na
        # aplicacao; aqui guardamos o codigo como veio.
        "FAIXA_ETARIA":        t.CHAR(1),
    }


def garantir_colunas_obrigatorias(df, colunas_esperadas):
    """Garante que o DataFrame tenha exatamente as colunas esperadas: cria
    como vazias (None) as que faltarem e mantem apenas as que estao na lista,
    na ordem esperada. Protege a sincronizacao contra mudancas de schema no
    CSV gerado pelo pipeline."""
    for col in colunas_esperadas:
        if col not in df.columns:
            df[col] = None
    return df[colunas_esperadas]


def create_db_engine():
    """Engine SQLAlchemy usado pelo pandas.DataFrame.to_sql() no script de
    sincronizacao. Requer a variavel de ambiente DATABASE_URL."""
    from sqlalchemy import create_engine

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL nao configurada. Defina a variavel de ambiente "
            "(no GitHub: Settings > Secrets and variables > Actions > "
            "Variables > SUPABASE_CONNECTION_STRING) antes de rodar a "
            "sincronizacao."
        )
    return create_engine(database_url, pool_pre_ping=True)


def ensure_app_tables() -> None:
    """Garante que a tabela de lookup de municipios (e a de metadata do
    pipeline) existam antes da sincronizacao. Nao falha se DATABASE_URL
    nao estiver configurada -- quem chama (sync_data_to_db.py) ja trata
    essa ausencia."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        return
    import psycopg2

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABELA_MUNICIPIOS} (
                    cod_municipio VARCHAR(10) PRIMARY KEY,
                    nome_municipio VARCHAR(200) NOT NULL
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABELA_CNAES} (
                    codigo_cnae VARCHAR(10) PRIMARY KEY,
                    descricao_cnae VARCHAR(300) NOT NULL
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABELA_METADATA} (
                    chave VARCHAR(100) PRIMARY KEY,
                    valor TEXT,
                    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
                """
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def registrar_metadata_pipeline(dados: dict) -> None:
    """Grava/atualiza pares chave-valor na tabela de metadata do pipeline
    (mes RF, trimestre PGFN, data da ultima sincronizacao, contagens, etc.)
    -- usado pela tela "Sobre" no frontend. Nao falha o processo de
    sincronizacao caso a gravacao de metadata de algum problema; so avisa."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        return
    import psycopg2

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            for chave, valor in dados.items():
                cur.execute(
                    f"""
                    INSERT INTO {TABELA_METADATA} (chave, valor, atualizado_em)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (chave) DO UPDATE
                        SET valor = EXCLUDED.valor, atualizado_em = NOW()
                    """,
                    (chave, str(valor) if valor is not None else None),
                )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[AVISO] Falha ao gravar metadata do pipeline: {e}")
    finally:
        conn.close()


def criar_indices_dados() -> None:
    """Cria indices nas tabelas de dados depois de recarregadas (to_sql com
    if_exists="replace" recria a tabela do zero a cada sincronizacao, entao
    os indices precisam ser recriados depois, nao antes)."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        return
    import psycopg2

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f'''CREATE INDEX IF NOT EXISTS idx_dados_empresas_cnpj_completo '''
                f'''ON {TABELA_EMPRESAS} ("CNPJ_COMPLETO")'''
            )
            # Indices de faixa (range) do funil + ranking top-dividas.
            # Criados aqui porque o sync usa to_sql replace (recria a tabela
            # do zero e derruba os indices a cada carga) -- tudo que nao
            # estiver nesta funcao SOME no proximo ETL.
            cur.execute(
                f'''CREATE INDEX IF NOT EXISTS idx_dados_empresas_divida_total '''
                f'''ON {TABELA_EMPRESAS} ("DIVIDA_TOTAL")'''
            )
            cur.execute(
                f'''CREATE INDEX IF NOT EXISTS idx_dados_empresas_capital_social '''
                f'''ON {TABELA_EMPRESAS} ("CAPITAL_SOCIAL")'''
            )
            # Tabelas de dominio: sem indice, o LEFT JOIN de toda listagem
            # varre municipios/cnaes inteiros por linha retornada.
            cur.execute(
                f'''CREATE UNIQUE INDEX IF NOT EXISTS idx_municipios_cod '''
                f'''ON {TABELA_MUNICIPIOS} (cod_municipio)'''
            )
            cur.execute(
                f'''CREATE UNIQUE INDEX IF NOT EXISTS idx_cnaes_codigo '''
                f'''ON {TABELA_CNAES} (codigo_cnae)'''
            )
            # Usados pelos endpoints de analytics (GROUP BY / JOIN por setor
            # e por municipio) e pelo filtro de listagem de empresas.
            # Ordenacao padrao da listagem (ORDER BY RAZAO_SOCIAL). Sem ele a
            # primeira pagina vira sort de 750 mil linhas: 10s em vez de 0,1s.
            cur.execute(
                f'''CREATE INDEX IF NOT EXISTS idx_dados_empresas_razao_social '''
                f'''ON {TABELA_EMPRESAS} ("RAZAO_SOCIAL")'''
            )
            cur.execute(
                f'''CREATE INDEX IF NOT EXISTS idx_dados_empresas_cnae '''
                f'''ON {TABELA_EMPRESAS} ("CNAE_PRINCIPAL")'''
            )
            # Cidade + ordenacao numa tacada: a listagem filtrada por cidade
            # ordena por RAZAO_SOCIAL, e sem o indice composto o banco le
            # todas as linhas da cidade pra devolver 100 (14s em Porto Alegre).
            cur.execute(
                f'''CREATE INDEX IF NOT EXISTS idx_dados_empresas_municipio_razao '''
                f'''ON {TABELA_EMPRESAS} ("COD_MUNICIPIO", "RAZAO_SOCIAL")'''
            )
            cur.execute(
                f'''CREATE INDEX IF NOT EXISTS idx_dados_socios_cnpj_basico '''
                f'''ON {TABELA_SOCIOS} ("CNPJ_BASICO")'''
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
