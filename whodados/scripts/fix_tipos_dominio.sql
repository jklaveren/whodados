-- =================================================================
-- Corrige tipo de coluna nas tabelas de dominio (municipios, cnaes)
-- =================================================================
-- ACHADO: uma consulta comum (empresas de uma cidade + porte) leva
-- 25-30 SEGUNDOS no banco de producao. Causa raiz: dados_empresas."COD_MUNICIPIO"
-- e' varchar(10), mas municipios.cod_municipio e' text (idem
-- cnaes.codigo_cnae vs dados_empresas."CNAE_PRINCIPAL"). O JOIN entre tipos
-- diferentes forca um cast (::text) que impede o planner do Postgres de
-- usar as estatisticas da coluna direito -- ele estima 17 linhas quando na
-- verdade sao 219 mil, e escolhe um plano catastroficamente ruim (nested
-- loop com bitmap heap scan "lossy").
--
-- Bug introduzido por mim mesmo hoje: ao popular cnaes/municipios (que
-- tinham ficado vazios), usei pandas.to_sql(...) sem dtype= explicito, e o
-- pandas por padrao cria colunas de texto como TEXT plano em vez de
-- VARCHAR(10) como o resto do schema usa.
--
-- Como rodar (psql, ou SQL Editor do Supabase):
--   psql "$DATABASE_URL" -f whodados/scripts/fix_tipos_dominio.sql
--
-- Seguro: tabelas pequenas (~5.6 mil e ~1.4 mil linhas), ALTER TYPE e
-- instantaneo nesse tamanho. Nao mexe em dados_empresas (1,68 milhao de
-- linhas), so nas duas tabelas de lookup.
-- =================================================================

ALTER TABLE municipios ALTER COLUMN cod_municipio TYPE varchar(10);
ALTER TABLE cnaes ALTER COLUMN codigo_cnae TYPE varchar(10);

-- Atualiza as estatisticas do planner com os tipos corretos.
ANALYZE dados_empresas;
ANALYZE municipios;
ANALYZE cnaes;

-- Para conferir que melhorou, rode antes/depois:
-- EXPLAIN ANALYZE
--   SELECT COUNT(*) FROM dados_empresas e
--   LEFT JOIN municipios m ON m.cod_municipio = e."COD_MUNICIPIO"
--   WHERE m.nome_municipio = 'PORTO ALEGRE' AND e."PORTE_EMPRESA" = ANY('{01}');
-- Antes: ~25-30s. Esperado depois: menos de 1s.
