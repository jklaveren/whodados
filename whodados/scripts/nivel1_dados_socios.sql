-- =================================================================
-- Nivel 1 aplicado direto na tabela dados_socios
--
-- Estrategia:
--   Um UNICO ALTER TABLE agrupa TODOS os ALTER COLUMN TYPE, uma
--   reescrita so, que ja compacta a tabela. Sem VACUUM FULL depois.
--
-- Bloqueio:
--   AccessExclusiveLock em dados_socios durante o rewrite (~1-3 min
--   pra ~1.5M linhas). Backend cai no fallback se a query nessa
--   tabela falhar (get_socios_by_cnpj retorna [] em erro), entao a
--   UI segue funcionando.
--
-- Uso: Supabase Dashboard -> SQL Editor -> New query -> cola tudo -> Run.
--   Recomendado rodar DEPOIS de nivel1_dados_empresas.sql (nao ha
--   dependencia rigida, mas facilita reverter uma sem afetar a outra).
-- =================================================================

ALTER TABLE dados_socios
    ALTER COLUMN "CNPJ_BASICO"          TYPE CHAR(8),
    ALTER COLUMN "IDENTIFICADOR_SOCIO"  TYPE CHAR(1);

-- Confere o resultado
SELECT
  pg_size_pretty(pg_total_relation_size('dados_socios')) AS total,
  pg_size_pretty(pg_relation_size('dados_socios')) AS heap,
  pg_size_pretty(pg_indexes_size('dados_socios')) AS indices;

SELECT column_name, data_type, character_maximum_length
FROM information_schema.columns
WHERE table_name = 'dados_socios'
ORDER BY ordinal_position;
