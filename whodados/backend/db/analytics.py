"""Consultas de analytics -- agregacoes sobre dados_empresas / dados_socios.

Tudo agregado no Postgres (GROUP BY / JOIN), nao no cliente: os numeros
refletem a base inteira, nao so as primeiras N linhas carregadas na tela.

Reconstroi o que o app legado (LegadoStream) fazia em pandas:
Home (KPIs), Foco por Cidade, Radar de Setores, Mapa de Passivos e
Analise de Socios.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

try:
    from .config import get_db_cursor
except ImportError:  # execucao fora do pacote
    from backend.db.config import get_db_cursor
try:
    from .cache import cached
except ImportError:
    from backend.db.cache import cached
try:
    from ..logger import get_logger
except ImportError:  # pragma: no cover
    import logging
    get_logger = lambda x: logging.getLogger(x)  # noqa: E731

log = get_logger(__name__)

# Empresas cuja razao social indica falencia / recuperacao judicial / baixa.
# Mesma lista do legado (app_main.py::BLACK_LIST). Excluidas por padrao.
_REGEX_INATIVAS = r"RECUPERACAO|FALIDA|JUDICIAL|MASSA FALIDA|EM LIQUIDACAO|BAIXADA|INAPTA"

# FROM comum a todas as consultas: empresa + nome do municipio + descricao do CNAE.
_BASE_FROM = """
    FROM dados_empresas e
    LEFT JOIN municipios m ON m.cod_municipio = e."COD_MUNICIPIO"
    LEFT JOIN cnaes c ON c.codigo_cnae = e."CNAE_PRINCIPAL"
"""


def _colunas_empresas(cur) -> dict:
    """{COLUNA: tipo} reais de dados_empresas (o ETL legado pode nao ter
    criado DIVIDA_TOTAL ainda -- nesse caso tratamos divida como 0).
    O tipo decide a expressao: NUMERIC usa a coluna direto (usa indice),
    TEXT usa o cast defensivo legado."""
    cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = 'dados_empresas'"
    )
    return {r["column_name"]: r["data_type"] for r in cur.fetchall()}


def _expr_divida(cols: dict) -> str:
    if "DIVIDA_TOTAL" in cols:
        if cols.get("DIVIDA_TOTAL") == "numeric":
            return 'COALESCE(e."DIVIDA_TOTAL", 0)'
        return 'COALESCE(NULLIF(e."DIVIDA_TOTAL"::text, \'\')::numeric, 0)'
    for alt in ("DIVIDA_FEDERAL", "DIVIDA_PREVIDENCIARIA", "DIVIDA_FGTS", "DIVIDA"):
        if alt in cols:
            if cols.get(alt) == "numeric":
                return f'COALESCE(e."{alt}", 0)'
            return f'COALESCE(NULLIF(e."{alt}"::text, \'\')::numeric, 0)'
    return "0::numeric"


def _expr_capital(cols: dict) -> str:
    if "CAPITAL_SOCIAL" in cols:
        if cols.get("CAPITAL_SOCIAL") == "numeric":
            return 'COALESCE(e."CAPITAL_SOCIAL", 0)'
        return 'COALESCE(NULLIF(e."CAPITAL_SOCIAL"::text, \'\')::numeric, 0)'
    return "0::numeric"


def _tem_divida(cols: set) -> bool:
    return "DIVIDA_TOTAL" in cols

# PORTE_NOME nao existe mais na tabela -- e derivado do PORTE_EMPRESA (codigo).
# Fonte unica (codigos RF) em db/filtros.py, compartilhada com service.py.
from .filtros import PORTE_NOME_SQL as _PORTE_NOME_SQL  # noqa: E402
from .filtros import PORTES_DISPONIVEIS  # noqa: E402
from .filtros import cidades_normalizadas, clausula_cnae, codigos_porte  # noqa: E402


def _tabela_existe(cur, nome: str) -> bool:
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_name = %s) AS existe",
        (nome,),
    )
    row = cur.fetchone()
    return bool(row and row["existe"])


def _filtros_sql(
    cidades: Optional[List[str]] = None,
    cnaes: Optional[List[str]] = None,
    portes: Optional[List[str]] = None,
    divida_min: Optional[float] = None,
    divida_max: Optional[float] = None,
    capital_min: Optional[float] = None,
    capital_max: Optional[float] = None,
    incluir_inativas: bool = False,
    div_expr: str = "0::numeric",
    cap_expr: str = "0::numeric",
    tem_divida: bool = False,
) -> tuple[str, list]:
    """Monta o trecho ' AND ...' compartilhado por todas as agregacoes.

    Espelha os filtros da sidebar do legado: cidade, CNAE, porte, faixa de
    passivo, faixa de capital social e o toggle de falencia/recuperacao."""
    cond: List[str] = []
    params: list = []

    if cidades:
        # Mesma razao da listagem (ver _mapa_municipios em service.py): o
        # filtro pelo nome via JOIN faz o planejador subestimar as linhas.
        from .service import codigos_municipio
        cond.append('e."COD_MUNICIPIO" = ANY(%s)')
        params.append(codigos_municipio(list(cidades)) or ["__nenhum__"])
    if cnaes:
        sql_cnae, p_cnae = clausula_cnae(list(cnaes))
        cond.append(sql_cnae)
        params.extend(p_cnae)
    if portes:
        # Frontend manda nomes ('ME', 'EPP', ...); a tabela guarda so o
        # codigo. Traduz de volta.
        codigos = codigos_porte(list(portes))
        cond.append('e."PORTE_EMPRESA" = ANY(%s)')
        params.append(codigos or ["__nenhum__"])
    if tem_divida:
        if divida_min is not None:
            cond.append(f"{div_expr} >= %s")
            params.append(divida_min)
        if divida_max is not None:
            cond.append(f"{div_expr} <= %s")
            params.append(divida_max)
    if capital_min is not None:
        cond.append(f"{cap_expr} >= %s")
        params.append(capital_min)
    if capital_max is not None:
        cond.append(f"{cap_expr} <= %s")
        params.append(capital_max)
    if not incluir_inativas:
        cond.append('COALESCE(e."RAZAO_SOCIAL", \'\') !~* %s')
        params.append(_REGEX_INATIVAS)
    # Mesma exclusao comercial da listagem (CNAE_DIVISOES_EXCLUIDAS em
    # service.py): sem isto o grafico conta empresa que a tabela nao mostra.
    from .service import CNAE_DIVISOES_EXCLUIDAS
    if CNAE_DIVISOES_EXCLUIDAS:
        cond.append('LEFT(COALESCE(e."CNAE_PRINCIPAL", \'\'), 2) <> ALL(%s)')
        params.append(list(CNAE_DIVISOES_EXCLUIDAS))

    return ((" AND " + " AND ".join(cond)) if cond else ""), params


def _vazio(cur) -> bool:
    return not _tabela_existe(cur, "dados_empresas")


# KPIs (Home)

@cached("analytics_resumo")
def analytics_resumo(**filtros) -> Dict[str, Any]:
    """Indicadores-chave da base filtrada (equivale aos 8 KPIs da Home)."""
    zero = {
        "total_empresas": 0, "divida_total": 0.0, "capital_total": 0.0,
        "divida_media": 0.0, "capital_medio": 0.0, "qtd_cidades": 0,
        "qtd_setores": 0, "qtd_com_divida": 0, "qtd_inativas": 0,
        "tem_dados_divida": False,
    }
    try:
        with get_db_cursor() as cur:
            if _vazio(cur):
                return zero
            cols = _colunas_empresas(cur)
            div_expr = _expr_divida(cols)
            cap_expr = _expr_capital(cols)
            tem_div = _tem_divida(cols)
            where, params = _filtros_sql(
                **filtros, div_expr=div_expr, cap_expr=cap_expr, tem_divida=tem_div
            )
            # qtd_inativas ignora o proprio toggle (como sempre foi): conta as
            # excluidas pelos OUTROS filtros, nao pelas ja excluidas.
            where_sem_toggle, params_sem_toggle = _filtros_sql(
                **{**filtros, "incluir_inativas": True},
                div_expr=div_expr, cap_expr=cap_expr, tem_divida=tem_div,
            )
            if not filtros.get("cidades"):
                # Caso dominante (tela abrindo ou funil sem cidade): nenhuma
                # clausula precisa de JOIN -- roda tudo sobre dados_empresas,
                # e as distintas viram semi-joins sondando os indices das
                # tabelas de dominio (milhares de probes em vez de ordenar
                # 1,68M duas vezes).
                where_e2 = where.replace('e."', 'e2."')
                where_st_e2 = where_sem_toggle.replace('e."', 'e2."')
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*) AS total_empresas,
                        COALESCE(SUM({div_expr}), 0) AS divida_total,
                        COALESCE(SUM({cap_expr}), 0) AS capital_total,
                        COALESCE(AVG({div_expr}), 0) AS divida_media,
                        COALESCE(AVG({cap_expr}), 0) AS capital_medio,
                        COUNT(*) FILTER (WHERE {div_expr} > 0) AS qtd_com_divida,
                        COUNT(*) FILTER (WHERE COALESCE(e."RAZAO_SOCIAL", '') ~* %s
                                         {where_st_e2}) AS qtd_inativas,
                        (SELECT COUNT(*) FROM municipios m
                          WHERE EXISTS (SELECT 1 FROM dados_empresas e2
                                        WHERE e2."COD_MUNICIPIO" = m.cod_municipio
                                        {where_e2})) AS qtd_cidades,
                        (SELECT COUNT(*) FROM cnaes c
                          WHERE EXISTS (SELECT 1 FROM dados_empresas e2
                                        WHERE e2."CNAE_PRINCIPAL" = c.codigo_cnae
                                        {where_e2})) AS qtd_setores
                    FROM dados_empresas e
                    WHERE 1=1 {where}
                    """,
                    [_REGEX_INATIVAS, *params_sem_toggle, *params, *params,
                     *params],
                )
            else:
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*) AS total_empresas,
                        COALESCE(SUM({div_expr}), 0) AS divida_total,
                        COALESCE(SUM({cap_expr}), 0) AS capital_total,
                        COALESCE(AVG({div_expr}), 0) AS divida_media,
                        COALESCE(AVG({cap_expr}), 0) AS capital_medio,
                        COUNT(DISTINCT e."COD_MUNICIPIO") AS qtd_cidades,
                        COUNT(DISTINCT e."CNAE_PRINCIPAL") AS qtd_setores,
                        COUNT(*) FILTER (WHERE {div_expr} > 0) AS qtd_com_divida,
                        COUNT(*) FILTER (WHERE COALESCE(e."RAZAO_SOCIAL", '') ~* %s
                                         {where_sem_toggle}) AS qtd_inativas
                    {_BASE_FROM}
                    WHERE 1=1 {where}
                    """,
                    # Ordem = ordem dos %s no SQL acima: o regex e o
                    # where_sem_toggle estao DENTRO do FILTER, que vem antes
                    # do WHERE final. Invertido, o regex recebia a lista de
                    # cidades ("~* ARRAY[...]") e o resumo por cidade caia no
                    # except devolvendo tudo zerado.
                    [_REGEX_INATIVAS, *params_sem_toggle, *params],
                )
            row = cur.fetchone() or {}
            inativas = (row or {}).get("qtd_inativas", 0)

            return {
                "total_empresas": int(row.get("total_empresas") or 0),
                "divida_total": float(row.get("divida_total") or 0),
                "capital_total": float(row.get("capital_total") or 0),
                "divida_media": float(row.get("divida_media") or 0),
                "capital_medio": float(row.get("capital_medio") or 0),
                "qtd_cidades": int(row.get("qtd_cidades") or 0),
                "qtd_setores": int(row.get("qtd_setores") or 0),
                "qtd_com_divida": int(row.get("qtd_com_divida") or 0),
                "qtd_inativas": int(inativas or 0),
                # Front usa p/ decidir se mostra graficos de divida ou o aviso
                # "dados de passivo ainda nao sincronizados".
                "tem_dados_divida": bool(tem_div),
            }
    except Exception as e:
        log.warning(f"analytics_resumo falhou: {e}")
        return zero


# Foco por Cidade

@cached("analytics_por_cidade")
def analytics_por_cidade(limite: int = 20, **filtros) -> List[Dict[str, Any]]:
    try:
        with get_db_cursor() as cur:
            if _vazio(cur):
                return []
            cols = _colunas_empresas(cur)
            div_expr = _expr_divida(cols)
            cap_expr = _expr_capital(cols)
            tem_div = _tem_divida(cols)
            # Ranking util mesmo sem DIVIDA_TOTAL: ordena por capital quando
            # nao ha passivo, e por qtd como ultimo recurso.
            ordem = "qtd" if _expr_divida(cols) == "0::numeric" else "divida_total"
            where, params = _filtros_sql(
                **filtros, div_expr=div_expr, cap_expr=cap_expr, tem_divida=tem_div
            )
            cur.execute(
                f"""
                SELECT
                    COALESCE(m.nome_municipio, 'Nao mapeado') AS cidade,
                    COUNT(*) AS qtd,
                    COALESCE(SUM({cap_expr}), 0) AS capital_total,
                    COALESCE(SUM({div_expr}), 0) AS divida_total
                {_BASE_FROM}
                WHERE 1=1 {where}
                GROUP BY cidade
                -- O grafico "Empresas por cidade" plota qtd (nao divida/capital) --
                -- o Top N precisa ser selecionado pelo mesmo criterio, senao uma
                -- cidade com poucas empresas mas divida/capital concentrado (ex.:
                -- 1 empresa gigante) entra no lugar de cidades com mais empresas.
                ORDER BY qtd DESC
                LIMIT %s
                """,
                [*params, limite],
            )
            return [
                {
                    "cidade": r["cidade"],
                    "qtd": int(r["qtd"]),
                    "capital_total": float(r["capital_total"]),
                    "divida_total": float(r["divida_total"]),
                }
                for r in cur.fetchall()
            ]
    except Exception as e:
        log.warning(f"analytics_por_cidade falhou: {e}")
        return []


# Radar de Setores

@cached("analytics_por_setor")
def analytics_por_setor(limite: int = 20, **filtros) -> List[Dict[str, Any]]:
    try:
        with get_db_cursor() as cur:
            if _vazio(cur):
                return []
            cols = _colunas_empresas(cur)
            div_expr = _expr_divida(cols)
            cap_expr = _expr_capital(cols)
            tem_div = _tem_divida(cols)
            where, params = _filtros_sql(
                **filtros, div_expr=div_expr, cap_expr=cap_expr, tem_divida=tem_div
            )
            cur.execute(
                f"""
                SELECT
                    e."CNAE_PRINCIPAL" AS cnae,
                    COALESCE(MAX(c.descricao_cnae), 'Outras atividades') AS descricao,
                    COUNT(*) AS qtd,
                    COALESCE(SUM({cap_expr}), 0) AS capital_total,
                    COALESCE(SUM({div_expr}), 0) AS divida_total,
                    COALESCE(AVG({div_expr}), 0) AS divida_media
                {_BASE_FROM}
                WHERE 1=1 {where}
                GROUP BY e."CNAE_PRINCIPAL"
                -- Mesmo raciocinio do analytics_por_cidade: "Empresas por setor"
                -- plota qtd, entao o Top N tem que vir por qtd. Antes vinha por
                -- capital_total, e um setor pequeno com 1 empresa gigante (ex.:
                -- Yara Fertilizantes, R$ 10,6 bi de capital em 59 empresas do
                -- setor) aparecia no lugar de setores com dezenas de milhares
                -- de empresas.
                ORDER BY qtd DESC
                LIMIT %s
                """,
                [*params, limite],
            )
            return [
                {
                    "cnae": r["cnae"],
                    "descricao": r["descricao"],
                    "qtd": int(r["qtd"]),
                    "capital_total": float(r["capital_total"]),
                    "divida_total": float(r["divida_total"]),
                    "divida_media": float(r["divida_media"]),
                }
                for r in cur.fetchall()
            ]
    except Exception as e:
        log.warning(f"analytics_por_setor falhou: {e}")
        return []


@cached("analytics_por_porte")
def analytics_por_porte(**filtros) -> List[Dict[str, Any]]:
    try:
        with get_db_cursor() as cur:
            if _vazio(cur):
                return []
            cols = _colunas_empresas(cur)
            div_expr = _expr_divida(cols)
            cap_expr = _expr_capital(cols)
            where, params = _filtros_sql(
                **filtros, div_expr=div_expr, cap_expr=cap_expr,
                tem_divida=_tem_divida(cols),
            )
            cur.execute(
                f"""
                SELECT ({_PORTE_NOME_SQL}) AS porte,
                       COUNT(*) AS qtd
                {_BASE_FROM}
                WHERE 1=1 {where}
                GROUP BY porte
                ORDER BY qtd DESC
                """,
                params,
            )
            return [{"porte": r["porte"], "qtd": int(r["qtd"])} for r in cur.fetchall()]
    except Exception as e:
        log.warning(f"analytics_por_porte falhou: {e}")
        return []


# Top empresas (rankings)

@cached("analytics_top_empresas")
def analytics_top_empresas(
    ordenar_por: str = "divida", limite: int = 10, **filtros
) -> List[Dict[str, Any]]:
    """Maiores empresas por 'divida' ou 'capital' (rankings da Home / Passivos).

    Sem coluna DIVIDA_TOTAL, o ranking de divida degrada para capital
    (return_capital=True no payload) em vez de falhar."""
    try:
        with get_db_cursor() as cur:
            if _vazio(cur):
                return []
            cols = _colunas_empresas(cur)
            div_expr = _expr_divida(cols)
            cap_expr = _expr_capital(cols)
            tem_div = _tem_divida(cols)
            pediu_divida = ordenar_por != "capital"
            usar_divida = pediu_divida and tem_div
            coluna = div_expr if usar_divida else cap_expr
            # Ordenacao usa a coluna NUA ( nao COALESCE() ): com NUMERIC o
            # indice cobre ORDER BY direto. O truque que garante o plano:
            # top-10 CNPJs primeiro (sobeio indice, ms) e so depois os JOINs
            # pros 10 -- sem isso o planner prefere varredura paralela + sort
            # (13s) ao inves do indice.
            if cols.get("DIVIDA_TOTAL" if usar_divida else "CAPITAL_SOCIAL") == "numeric":
                col_ord = "DIVIDA_TOTAL" if usar_divida else "CAPITAL_SOCIAL"
            else:
                col_ord = None  # legado TEXT: sem indice util, ordena expressao
            where, params = _filtros_sql(
                **filtros, div_expr=div_expr, cap_expr=cap_expr, tem_divida=tem_div
            )
            if col_ord is not None:
                # O WHERE do funil usa os aliases e./m.; dentro da
                # subconsulta a base e t. (ep. nao existe mais). O JOIN com
                # municipios so entra se o filtro de cidade o exigir.
                where_t = where.replace('e."', 't."')
                join_m = ('LEFT JOIN municipios m ON m.cod_municipio = '
                          't."COD_MUNICIPIO"') if "m." in where else ""
                # Sem paralelismo aqui: com workers o planner prefere
                # varredura paralela + sort (13s) ao indice (ms). Serial, o
                # backward scan ganha no custo e e escolhido. So nesta
                # transacao (SET LOCAL), nao global.
                cur.execute("SET LOCAL max_parallel_workers_per_gather = 0")
                cur.execute(
                    f"""
                    SELECT
                        e."CNPJ_COMPLETO" AS cnpj_completo,
                        e."RAZAO_SOCIAL" AS razao_social,
                        COALESCE(m.nome_municipio, '') AS municipio,
                        e."CNAE_PRINCIPAL" AS cnae_principal,
                        COALESCE(c.descricao_cnae, '') AS cnae_descricao,
                        ({_PORTE_NOME_SQL}) AS porte_nome,
                        {cap_expr} AS capital_social,
                        {div_expr} AS divida_total
                    FROM (
                        SELECT t."CNPJ_COMPLETO" FROM dados_empresas t
                        {join_m}
                        WHERE 1=1 {where_t}
                        ORDER BY t."{col_ord}" DESC
                        LIMIT %s
                    ) top
                    JOIN dados_empresas e ON e."CNPJ_COMPLETO" = top."CNPJ_COMPLETO"
                    LEFT JOIN municipios m ON m.cod_municipio = e."COD_MUNICIPIO"
                    LEFT JOIN cnaes c ON c.codigo_cnae = e."CNAE_PRINCIPAL"
                    ORDER BY e."{col_ord}" DESC
                    """,
                    [*params, limite],
                )
            else:
                cur.execute(
                    f"""
                    SELECT
                        e."CNPJ_COMPLETO" AS cnpj_completo,
                        e."RAZAO_SOCIAL" AS razao_social,
                        COALESCE(m.nome_municipio, '') AS municipio,
                        e."CNAE_PRINCIPAL" AS cnae_principal,
                        COALESCE(c.descricao_cnae, '') AS cnae_descricao,
                        ({_PORTE_NOME_SQL}) AS porte_nome,
                        {cap_expr} AS capital_social,
                        {div_expr} AS divida_total
                    {_BASE_FROM}
                    WHERE 1=1 {where}
                    ORDER BY {coluna} DESC
                    LIMIT %s
                    """,
                    [*params, limite],
                )
            return [
                {
                    "cnpj_completo": r["cnpj_completo"],
                    "razao_social": r["razao_social"],
                    "municipio": r["municipio"],
                    "cnae_principal": r["cnae_principal"],
                    "cnae_descricao": r["cnae_descricao"],
                    "porte_nome": r["porte_nome"],
                    "capital_social": float(r["capital_social"]),
                    "divida_total": float(r["divida_total"]),
                    # Front usa p/ mostrar aviso honesto ("sem PGFN: ranking por
                    # capital") em vez de fingir que ha passivo.
                    "sem_divida": not tem_div,
                    "ordenado_por": "divida" if usar_divida else "capital",
                }
                for r in cur.fetchall()
            ]
    except Exception as e:
        log.warning(f"analytics_top_empresas falhou: {e}")
        return []


# Analise de Socios

def analytics_socios_ranking(limite: int = 50, **filtros) -> List[Dict[str, Any]]:
    """Ranking de socios pelo passivo acumulado das empresas em que constam
    (join dados_socios x dados_empresas por CNPJ_BASICO). Os filtros valem
    para o lado das empresas. Sem DIVIDA_TOTAL, ordena por capital/qtd."""
    try:
        with get_db_cursor() as cur:
            if _vazio(cur) or not _tabela_existe(cur, "dados_socios"):
                return []
            cols = _colunas_empresas(cur)
            div_expr = _expr_divida(cols)
            cap_expr = _expr_capital(cols)
            tem_div = _tem_divida(cols)
            ordem = "divida_total" if tem_div else "capital_total"
            where, params = _filtros_sql(
                **filtros, div_expr=div_expr, cap_expr=cap_expr, tem_divida=tem_div
            )
            cur.execute(
                f"""
                SELECT
                    s."NOME_SOCIO" AS nome_socio,
                    COUNT(DISTINCT e."CNPJ_BASICO") AS qtd_empresas,
                    COALESCE(SUM({div_expr}), 0) AS divida_total,
                    COALESCE(SUM({cap_expr}), 0) AS capital_total
                FROM dados_socios s
                JOIN dados_empresas e ON e."CNPJ_BASICO" = s."CNPJ_BASICO"
                LEFT JOIN municipios m ON m.cod_municipio = e."COD_MUNICIPIO"
                LEFT JOIN cnaes c ON c.codigo_cnae = e."CNAE_PRINCIPAL"
                WHERE COALESCE(s."NOME_SOCIO", '') <> '' {where}
                GROUP BY s."NOME_SOCIO"
                ORDER BY {ordem} DESC
                LIMIT %s
                """,
                [*params, limite],
            )
            return [
                {
                    "nome_socio": r["nome_socio"],
                    "qtd_empresas": int(r["qtd_empresas"]),
                    "divida_total": float(r["divida_total"]),
                    "capital_total": float(r["capital_total"]),
                }
                for r in cur.fetchall()
            ]
    except Exception as e:
        log.warning(f"analytics_socios_ranking falhou: {e}")
        return []


def analytics_socio_detalhe(nome_socio: str) -> List[Dict[str, Any]]:
    """Empresas vinculadas a um socio (drill-down da Analise de Socios)."""
    if not nome_socio:
        return []
    try:
        with get_db_cursor() as cur:
            if _vazio(cur) or not _tabela_existe(cur, "dados_socios"):
                return []
            cols = _colunas_empresas(cur)
            div_expr = _expr_divida(cols)
            cap_expr = _expr_capital(cols)
            tem_div = _tem_divida(cols)
            ordem = "divida_total" if tem_div else "capital_social"
            cur.execute(
                f"""
                SELECT DISTINCT
                    e."CNPJ_COMPLETO" AS cnpj_completo,
                    e."RAZAO_SOCIAL" AS razao_social,
                    COALESCE(m.nome_municipio, '') AS municipio,
                    e."CNAE_PRINCIPAL" AS cnae_principal,
                    COALESCE(c.descricao_cnae, '') AS cnae_descricao,
                    {cap_expr} AS capital_social,
                    {div_expr} AS divida_total
                FROM dados_socios s
                JOIN dados_empresas e ON e."CNPJ_BASICO" = s."CNPJ_BASICO"
                LEFT JOIN municipios m ON m.cod_municipio = e."COD_MUNICIPIO"
                LEFT JOIN cnaes c ON c.codigo_cnae = e."CNAE_PRINCIPAL"
                WHERE s."NOME_SOCIO" = %s
                ORDER BY {ordem} DESC
                """,
                (nome_socio,),
            )
            return [
                {
                    "cnpj_completo": r["cnpj_completo"],
                    "razao_social": r["razao_social"],
                    "municipio": r["municipio"],
                    "cnae_principal": r["cnae_principal"],
                    "cnae_descricao": r["cnae_descricao"],
                    "capital_social": float(r["capital_social"]),
                    "divida_total": float(r["divida_total"]),
                }
                for r in cur.fetchall()
            ]
    except Exception as e:
        log.warning(f"analytics_socio_detalhe falhou: {e}")
        return []


# Opcoes de filtro

# Muda so quando o ETL roda (mensal): 6h em vez dos 5 min do padrao.
@cached("analytics_opcoes_filtro", ttl=6 * 3600)
def analytics_opcoes_filtro() -> Dict[str, Any]:
    """Valores distintos para popular os multiselects da tela (cidades,
    portes) e a lista de CNAEs com descricao."""
    vazio = {"cidades": [], "portes": [], "cnaes": []}
    # Import local: service importa deste modulo, entao no topo daria ciclo.
    from .service import CNAE_DIVISOES_EXCLUIDAS
    try:
        with get_db_cursor() as cur:
            if _vazio(cur):
                return vazio

            cidades: List[str] = []
            if _tabela_existe(cur, "municipios"):
                # So municipio COM empresa na base. A tabela municipios e a
                # lista da Receita inteira (5.572); a carga e de um estado
                # so, entao listar tudo oferecia cidade que nunca retorna
                # resultado.
                cur.execute(
                    """SELECT m.nome_municipio
                         FROM municipios m
                        WHERE m.nome_municipio <> ''
                          AND EXISTS (SELECT 1 FROM dados_empresas e
                                       WHERE e."COD_MUNICIPIO" = m.cod_municipio
                                         AND LEFT(COALESCE(e."CNAE_PRINCIPAL", ''), 2) <> ALL(%s))
                        GROUP BY m.nome_municipio
                        ORDER BY m.nome_municipio""",
                    (list(CNAE_DIVISOES_EXCLUIDAS),),
                )
                cidades = [r["nome_municipio"] for r in cur.fetchall()]

            portes = list(PORTES_DISPONIVEIS)

            cnaes: List[str] = []
            if _tabela_existe(cur, "cnaes"):
                cur.execute(
                    """
                    SELECT e."CNAE_PRINCIPAL" AS cnae,
                           COALESCE(MAX(c.descricao_cnae), '') AS descricao,
                           COUNT(*) AS qtd
                    FROM dados_empresas e
                    LEFT JOIN cnaes c ON c.codigo_cnae = e."CNAE_PRINCIPAL"
                    WHERE LEFT(COALESCE(e."CNAE_PRINCIPAL", ''), 2) <> ALL(%s)
                    GROUP BY e."CNAE_PRINCIPAL"
                    ORDER BY qtd DESC
                    """,
                    (list(CNAE_DIVISOES_EXCLUIDAS),),
                )
                cnaes = [
                    {"codigo": r["cnae"], "descricao": r["descricao"], "qtd": int(r["qtd"])}
                    for r in cur.fetchall()
                ]

            return {"cidades": cidades, "portes": portes, "cnaes": cnaes}
    except Exception as e:
        log.warning(f"analytics_opcoes_filtro falhou: {e}")
        return vazio
