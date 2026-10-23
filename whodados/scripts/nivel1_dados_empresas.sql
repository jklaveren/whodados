-- =================================================================
-- Nivel 1 aplicado direto na tabela dados_empresas
--
-- Estrategia:
--   Um UNICO ALTER TABLE agrupa TODOS os DROP COLUMN + ALTER COLUMN
--   TYPE. Assim o Postgres reescreve o heap uma unica vez -- o rewrite
--   ja compacta a tabela (sem tuplas mortas, sem colunas removidas,
--   sem folgas). Nao precisa de VACUUM FULL depois, ganha ~5x em
--   tempo comparado a rodar ALTER por ALTER com VACUUM no fim.
--
-- Robusto contra dois estados possiveis do banco:
--   (a) schema antigo -- so tem DIVIDA_TOTAL, sem DIVIDA_FEDERAL /
--       DIVIDA_PREVIDENCIARIA / DIVIDA_FGTS (aqui o script cria).
--   (b) schema novo -- as 4 colunas ja existem (sync_dividas_only.py
--       ja rodou; aqui o ADD COLUMN IF NOT EXISTS e no-op).
--
-- Bloqueio:
--   O ALTER TABLE toma AccessExclusiveLock na dados_empresas durante
--   todo o rewrite (esperado: ~1-3 min pra ~700k linhas). Backend ja
--   tem fallback pra tabela ausente -- UI segue funcionando.
--
-- Uso: Supabase Dashboard -> SQL Editor -> New query -> cola tudo -> Run.
-- =================================================================

-- ----------------------------------------------------------------
-- Passo 1: garantir que todas as colunas de divida existem
-- ----------------------------------------------------------------
-- ADD COLUMN IF NOT EXISTS com DEFAULT constante nao reescreve a tabela
-- no Postgres 11+ (metadado apenas). Se as colunas ja existem, e no-op.
ALTER TABLE dados_empresas
    ADD COLUMN IF NOT EXISTS "DIVIDA_FEDERAL"        NUMERIC(18,2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS "DIVIDA_PREVIDENCIARIA" NUMERIC(18,2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS "DIVIDA_FGTS"           NUMERIC(18,2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS "DIVIDA_TOTAL"          NUMERIC(18,2) DEFAULT 0;

-- ----------------------------------------------------------------
-- Passo 2: o ALTER unico -- drops + type changes numa reescrita so
-- ----------------------------------------------------------------
-- Cada USING trata os valores feios inline (NULLIF pra '', regex pra
-- YYYYMMDD invalido) -- entao nao precisa UPDATE de limpeza antes.
-- Se a coluna ja e do tipo alvo, o USING vira no-op simbolico e o
-- ALTER continua sem custo extra.
ALTER TABLE dados_empresas
    DROP COLUMN IF EXISTS "CONTATO_FONE",
    DROP COLUMN IF EXISTS "PORTE_NOME",

    ALTER COLUMN "CAPITAL_SOCIAL"        TYPE NUMERIC(18,2)
        USING NULLIF(REPLACE("CAPITAL_SOCIAL"::text, ',', '.'), '')::numeric,
    ALTER COLUMN "DIVIDA_FEDERAL"        TYPE NUMERIC(18,2)
        USING NULLIF(REPLACE("DIVIDA_FEDERAL"::text, ',', '.'), '')::numeric,
    ALTER COLUMN "DIVIDA_PREVIDENCIARIA" TYPE NUMERIC(18,2)
        USING NULLIF(REPLACE("DIVIDA_PREVIDENCIARIA"::text, ',', '.'), '')::numeric,
    ALTER COLUMN "DIVIDA_FGTS"           TYPE NUMERIC(18,2)
        USING NULLIF(REPLACE("DIVIDA_FGTS"::text, ',', '.'), '')::numeric,
    ALTER COLUMN "DIVIDA_TOTAL"          TYPE NUMERIC(18,2)
        USING NULLIF(REPLACE("DIVIDA_TOTAL"::text, ',', '.'), '')::numeric,

    ALTER COLUMN "DATA_FUNDACAO"         TYPE DATE
        USING CASE
            WHEN "DATA_FUNDACAO"::text ~ '^[0-9]{8}$'
                 AND "DATA_FUNDACAO"::text NOT LIKE '0000%'
              THEN to_date("DATA_FUNDACAO"::text, 'YYYYMMDD')
            ELSE NULL
        END,

    ALTER COLUMN "CNPJ_BASICO"    TYPE CHAR(8),
    ALTER COLUMN "CNPJ_COMPLETO"  TYPE CHAR(14),
    ALTER COLUMN "PORTE_EMPRESA"  TYPE CHAR(2);

-- ----------------------------------------------------------------
-- Confere o resultado (tamanho + tipos)
-- ----------------------------------------------------------------
SELECT
  pg_size_pretty(pg_total_relation_size('dados_empresas')) AS total,
  pg_size_pretty(pg_relation_size('dados_empresas')) AS heap,
  pg_size_pretty(pg_indexes_size('dados_empresas')) AS indices;

SELECT column_name, data_type, character_maximum_length
FROM information_schema.columns
WHERE table_name = 'dados_empresas'
ORDER BY ordinal_position;
