"""DB Service - WhoDados 2.0."""
from __future__ import annotations
import json
import re

from psycopg2.extras import Json
from typing import List, Dict, Optional, Any
from .filtros import (
    PORTE_NOME_SQL, cidades_normalizadas, clausula_cnae, codigos_porte,
    sem_acento_upper,
)
try:
    from .config import (get_db_cursor, get_tipos_dados_empresas, expr_numerica,
                         data_fundacao_is_date, normalizar_data_param)
except ImportError:
    from backend.db.config import (get_db_cursor, get_tipos_dados_empresas, expr_numerica,
                                   data_fundacao_is_date, normalizar_data_param)
try:
    from ..logger import get_logger
except ImportError:
    import logging
    get_logger = lambda x: logging.getLogger(x)
log = get_logger(__name__)

from ..titular import titular

try:
    from ..crypto_utils import encrypt_secret, decrypt_secret
except ImportError:  # fallback defensivo -- nunca deve ocorrer
    def encrypt_secret(x): return x
    def decrypt_secret(x): return x
try:
    from .cache import cached
except ImportError:
    from backend.db.cache import cached

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute("SELECT * FROM app_users WHERE username = %s", (username,))
        return cur.fetchone()

def create_user_record(username: str, password_hash: str, email: Optional[str] = None, is_admin: bool = False) -> Dict[str, Any]:
    with get_db_cursor() as cur:
        cur.execute("INSERT INTO app_users (username, password_hash, email, is_admin) VALUES (%s, %s, %s, %s) RETURNING *", (username, password_hash, email, is_admin))
        return cur.fetchone()


def salvar_enriquecimento(cnpj: str, itens: List[Dict[str, Any]], coletado_por: str,
                          organizacao_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Grava os itens encontrados pelo agente de enriquecimento. Cada item
    precisa ter fonte_url -- nao gravamos nada sem proveniencia registrada."""
    salvos: List[Dict[str, Any]] = []
    with get_db_cursor() as cur:
        for item in itens:
            if not item.get("fonte_url"):
                continue
            cur.execute(
                """INSERT INTO enriquecimento_contatos
                   (cnpj, tipo_alvo, nome_alvo, campo, valor, fonte_url, fonte_titulo, coletado_por, organizacao_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                (
                    cnpj,
                    item.get("tipo_alvo", "empresa"),
                    item.get("nome_alvo"),
                    item.get("campo"),
                    item.get("valor"),
                    item.get("fonte_url"),
                    item.get("fonte_titulo"),
                    coletado_por,
                    organizacao_id,
                ),
            )
            salvos.append(cur.fetchone())
    return salvos

def listar_enriquecimento(cnpj: str, organizacao_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """So retorna itens ainda nao removidos (removido_em IS NULL), e so' os da
    empresa informada -- contato levantado pela Alfa nao e' da Beta. Linhas
    antigas (organizacao_id NULL, de antes desta separacao) seguem visiveis
    pra nao sumir com o que ja' tinha sido pesquisado."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT * FROM enriquecimento_contatos
               WHERE cnpj = %s AND removido_em IS NULL
                 AND (%s::int IS NULL OR organizacao_id = %s OR organizacao_id IS NULL)
               ORDER BY coletado_em DESC""",
            (cnpj, organizacao_id, organizacao_id),
        )
        return cur.fetchall()

def remover_enriquecimento(cnpj: str, organizacao_id: Optional[int] = None) -> int:
    """Direito de exclusao (LGPD): apaga o dado pessoal coletado (valor,
    fonte) mas mantem a linha com removido_em preenchido, como registro de
    auditoria de que a remocao aconteceu -- sem guardar o dado em si."""
    with get_db_cursor() as cur:
        cur.execute(
            """UPDATE enriquecimento_contatos
               SET valor = NULL, fonte_url = NULL, fonte_titulo = NULL, removido_em = NOW()
               WHERE cnpj = %s AND removido_em IS NULL
                 AND (%s::int IS NULL OR organizacao_id = %s OR organizacao_id IS NULL)
               RETURNING id""",
            (cnpj, organizacao_id, organizacao_id),
        )
        return len(cur.fetchall())

def get_crm_by_cnpj(cnpj: str, organizacao_id: int) -> Optional[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute("SELECT * FROM crm WHERE cnpj = %s AND organizacao_id = %s", (cnpj, organizacao_id))
        return cur.fetchone()

def get_crm_all(organizacao_id: int) -> List[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute("SELECT * FROM crm WHERE organizacao_id = %s ORDER BY data_atualizacao DESC", (organizacao_id,))
        return cur.fetchall()

def create_or_update_crm(cnpj: str, organizacao_id: int, status: Optional[str] = None, notas: Optional[str] = None, criado_por: Optional[str] = None,
                         classificacao: Optional[str] = None, motivo: Optional[str] = None, parceiro: Optional[bool] = None) -> Dict[str, Any]:
    with get_db_cursor() as cur:
        cur.execute(
            """INSERT INTO crm (cnpj, organizacao_id, status, notas, criado_por,
                               classificacao, motivo, parceiro, data_atualizacao)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
               ON CONFLICT (organizacao_id, cnpj) DO UPDATE
                   SET status = COALESCE(EXCLUDED.status, crm.status),
                       notas = COALESCE(EXCLUDED.notas, crm.notas),
                       classificacao = COALESCE(EXCLUDED.classificacao, crm.classificacao),
                       motivo = COALESCE(EXCLUDED.motivo, crm.motivo),
                       parceiro = COALESCE(EXCLUDED.parceiro, crm.parceiro, FALSE),
                       data_atualizacao = NOW()
               RETURNING *""",
            (cnpj, organizacao_id, status, notas, criado_por, classificacao, motivo, parceiro),
        )
        return cur.fetchone()


# CLASSIFICACAO DE PERFIL DA BASE (ideal / possivel / fora do perfil)
_BLACKLIST_CLASSIFICACAO = r"RECUPERACAO|FALIDA|JUDICIAL|MASSA FALIDA|EM LIQUIDACAO|BAIXADA|INAPTA"

# Divisao CNAE 69 fora da base de prospeccao, por decisao comercial: 691
# (advocacia, cartorios, auxiliares da justica) e' concorrente; 692
# (contabilidade, auditoria) ja' foi trabalhado por outro canal.
# Aplicado na query, nao no ETL: vale na hora e e' reversivel sem recarregar
# 1,68M linhas.
CNAE_DIVISOES_EXCLUIDAS = ("69",)


def classificar_empresa(empresa: Dict[str, Any]) -> Dict[str, Any]:
    """Aplica as regras de classificacao em UMA empresa (provinda de dados_empresas).
    Retorna {'classificacao': str, 'motivo': str}."""
    import re as _re
    from datetime import datetime

    razao = (empresa.get("razao_social") or "").upper()
    nome = (empresa.get("nome_fantasia") or "").upper()

    # 1) Eliminatoria: situacao juridica ruim
    situacao = f"{razao} {nome}"
    if _re.search(_BLACKLIST_CLASSIFICACAO, situacao):
        return {"classificacao": "fora_perfil", "motivo": "Situacao juridica desfavoravel (falencia/recuperacao/baixada)"}

    # 2) Eliminatoria: sem contato (sem email E sem telefone)
    email = (empresa.get("email") or "").strip()
    fone = (empresa.get("contato_fone") or "").strip()
    tem_email = bool(email)
    tem_fone = bool(_re.sub(r"\D", "", fone))
    if not tem_email and not tem_fone:
        return {"classificacao": "fora_perfil", "motivo": "Sem dados de contato (e-mail e telefone)"}

    # 3) Eliminatoria: capital social zerado ou sem dados
    capital = 0.0
    try:
        capital = float(empresa.get("capital_social") or 0)
    except (TypeError, ValueError):
        capital = 0.0
    if capital <= 0:
        return {"classificacao": "fora_perfil", "motivo": "Capital social zerado ou sem dados"}

    # 4) Idade (DATA_FUNDACAO vem YYYYMMDD como texto)
    anos = 0.0
    fundacao = (empresa.get("data_fundacao") or "").strip()
    if len(fundacao) >= 8 and fundacao.isdigit():
        try:
            d = datetime(int(fundacao[0:4]), int(fundacao[4:6]), int(fundacao[6:8]))
            anos = (datetime.utcnow() - d).days / 365.25
        except ValueError:
            anos = 0.0

    # 5) PERFIL IDEAL: 3+ anos, capital >= 100k, email E telefone
    if anos >= 3 and capital >= 100000 and tem_email and tem_fone:
        return {"classificacao": "perfil_ideal", "motivo": "Empresa ativa, 3+ anos, capital >= R$100k e contato completo"}

    # 6) PERFIL POSSIVEL: nao atingiu o ideal, mas tem pelo menos um contato
    if tem_email or tem_fone:
        return {"classificacao": "perfil_possivel", "motivo": "Perfil intermediario (faltam criterios do ideal)"}

    return {"classificacao": "fora_perfil", "motivo": "Nao atende ao perfil prospectavel"}


def classificar_base(organizacao_id: int, limite: int = None) -> Dict[str, Any]:
    """Percorre dados_empresas, aplica a classificacao em lote e grava na tabela
    crm (cria registro se ainda nao existir; atualiza classificacao/motivo).
    NAO muda status nem notas existentes. Retorna contadores."""
    try:
        with get_db_cursor() as cur:
            if not _tabela_existe(cur, "dados_empresas"):
                return {"ok": False, "erro": "Tabela de empresas ainda nao existe", "totais": {}}
            cur.execute(
                """
                SELECT
                    e."CNPJ_COMPLETO" AS cnpj_completo,
                    e."RAZAO_SOCIAL" AS razao_social,
                    e."NOME_FANTASIA" AS nome_fantasia,
                    e."DATA_FUNDACAO" AS data_fundacao,
                    COALESCE(NULLIF(e."CAPITAL_SOCIAL"::text, '')::numeric, 0) AS capital_social,
                    e."EMAIL" AS email,
                    e."CONTATO_FONE" AS contato_fone
                FROM dados_empresas e
                """
            )
            linhas = cur.fetchall()

        selecionadas = linhas[:limite] if limite and limite > 0 else linhas
        totais = {"perfil_ideal": 0, "perfil_possivel": 0, "fora_perfil": 0}
        for emp in selecionadas:
            r = classificar_empresa(emp)
            if isinstance(r, dict) and r.get("classificacao"):
                totais[r["classificacao"]] = totais.get(r["classificacao"], 0) + 1
                _upsert_classificacao(emp["cnpj_completo"], organizacao_id, r["classificacao"], r.get("motivo", ""))

        return {"ok": True, "processadas": len(selecionadas), "totais": totais}
    except Exception as e:
        log.warning(f"classificar_base falhou: {e}")
        return {"ok": False, "erro": str(e), "totais": {}}


def _upsert_classificacao(cnpj: str, organizacao_id: int, classificacao: str, motivo: str) -> bool:
    """INSERT ... ON CONFLICT mantendo status/notas existentes. Usado em lote."""
    try:
        with get_db_cursor() as cur:
            cur.execute(
                """INSERT INTO crm (cnpj, organizacao_id, classificacao, motivo, data_atualizacao)
                   VALUES (%s, %s, %s, %s, NOW())
                   ON CONFLICT (organizacao_id, cnpj) DO UPDATE
                       SET classificacao = EXCLUDED.classificacao,
                           motivo = EXCLUDED.motivo,
                           data_atualizacao = NOW()""",
                (cnpj, organizacao_id, classificacao, motivo),
            )
        return True
    except Exception as e:
        log.warning(f"_upsert_classificacao falhou para {cnpj}: {e}")
        return False


def listar_crm_classificados(organizacao_id: int, filtro: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lista registros do CRM com classificacao, resolvendo dados da empresa base.
    Filtro opcional: perfil_ideal / perfil_possivel / fora_perfil / parceiro / sem_classificacao."""
    permite = {"perfil_ideal", "perfil_possivel", "fora_perfil", "parceiro", "sem_classificacao"}
    try:
        with get_db_cursor() as cur:
            base_sql = f"""
                SELECT c.cnpj, c.classificacao, c.motivo, c.status, c.parceiro,
                       c.data_atualizacao, c.notas,
                       COALESCE(e."RAZAO_SOCIAL", e."NOME_FANTASIA", '') AS razao_social,
                       COALESCE(NULLIF(e."CAPITAL_SOCIAL"::text, '')::numeric, 0) AS capital_social,
                       COALESCE(e."EMAIL", '') AS email, ({CONTATO_FONE_SQL}) AS contato_fone,
                       COALESCE(m.nome_municipio, '') AS municipio
                FROM crm c
                LEFT JOIN dados_empresas e ON e."CNPJ_COMPLETO" = c.cnpj
                LEFT JOIN municipios m ON m.cod_municipio = e."COD_MUNICIPIO"
                WHERE c.organizacao_id = %s
            """
            params: list = [organizacao_id]
            if filtro == "sem_classificacao":
                base_sql += " AND (c.classificacao IS NULL OR c.classificacao = '')"
            elif filtro in permite:
                base_sql += " AND c.classificacao = %s"
                params.append(filtro)
            base_sql += " ORDER BY c.data_atualizacao DESC NULLS LAST LIMIT 1000"
            cur.execute(base_sql, params)
            return cur.fetchall()
    except Exception as e:
        log.warning(f"listar_crm_classificados falhou: {e}")
        return []


def estatisticas_classificacao(organizacao_id: int) -> Dict[str, Any]:
    """Contadores por classificacao (para a aba Classificacao)."""
    try:
        with get_db_cursor() as cur:
            cur.execute(
                """SELECT classificacao, COUNT(*) AS total FROM crm
                   WHERE organizacao_id = %s AND classificacao IS NOT NULL
                   GROUP BY classificacao""",
                (organizacao_id,),
            )
            linhas = cur.fetchall()
            total_crm = 0
            cur.execute("SELECT COUNT(*) AS total FROM crm WHERE organizacao_id = %s", (organizacao_id,))
            r = cur.fetchone()
            total_crm = int(r["total"]) if r and r.get("total") else 0
        resultado = {"perfil_ideal": 0, "perfil_possivel": 0, "fora_perfil": 0, "parceiro": 0,
                     "sem_classificacao": 0, "total_crm": total_crm}
        for r in linhas:
            chave = r["classificacao"] or "sem_classificacao"
            if chave in resultado:
                resultado[chave] = int(r["total"])
        return resultado
    except Exception as e:
        log.warning(f"estatisticas_classificacao falhou: {e}")
        return {"perfil_ideal": 0, "perfil_possivel": 0, "fora_perfil": 0, "parceiro": 0,
                "sem_classificacao": 0, "total_crm": 0}

# Colunas do template retornadas nas listagens (NUNCA inclui imagem_data -- ela e' pesada
# e so' e' buscada de fato pelo endpoint /templates/{id}/imagem).
_TEMPLATE_COLS = "id, nome, assunto, corpo_html, corpo_texto, categoria_cnae, criado_por, created_at, updated_at, tem_imagem"

def _com_imagem_url(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Adiciona o campo calculado imagem_url quando o template tem um card/imagem salvo."""
    if not row:
        return row
    if row.get("tem_imagem"):
        try:
            from ..config import settings
        except ImportError:
            from config import settings
        row["imagem_url"] = f"{settings.API_PUBLIC_URL}/api/v1/templates/{row['id']}/imagem"
    else:
        row["imagem_url"] = None
    return row

def create_template(nome: str, assunto: str, corpo_html: str, corpo_texto: Optional[str] = None, criado_por: Optional[str] = None, categoria_cnae: Optional[str] = "todos", organizacao_id: Optional[int] = None) -> Dict[str, Any]:
    with get_db_cursor() as cur:
        cur.execute(f"INSERT INTO email_templates (nome, assunto, corpo_html, corpo_texto, criado_por, categoria_cnae, organizacao_id) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {_TEMPLATE_COLS}", (nome, assunto, corpo_html, corpo_texto, criado_por, categoria_cnae or "todos", organizacao_id))
        return _com_imagem_url(cur.fetchone())

def update_template(template_id: int, nome: Optional[str] = None, assunto: Optional[str] = None, corpo_html: Optional[str] = None, corpo_texto: Optional[str] = None, categoria_cnae: Optional[str] = None, organizacao_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    org_sql = " AND organizacao_id = %s" if organizacao_id is not None else ""
    with get_db_cursor() as cur:
        fields = []
        params = []
        if nome is not None: fields.append("nome = %s"); params.append(nome)
        if assunto is not None: fields.append("assunto = %s"); params.append(assunto)
        if corpo_html is not None: fields.append("corpo_html = %s"); params.append(corpo_html)
        if corpo_texto is not None: fields.append("corpo_texto = %s"); params.append(corpo_texto)
        if categoria_cnae is not None: fields.append("categoria_cnae = %s"); params.append(categoria_cnae)
        if not fields:
            sel_params = [template_id] + ([organizacao_id] if organizacao_id is not None else [])
            cur.execute(f"SELECT {_TEMPLATE_COLS} FROM email_templates WHERE id = %s{org_sql}", sel_params)
            return _com_imagem_url(cur.fetchone())
        fields.append("updated_at = NOW()")
        params.append(template_id)
        if organizacao_id is not None:
            params.append(organizacao_id)
        sql = "UPDATE email_templates SET " + ", ".join(fields) + f" WHERE id = %s{org_sql} RETURNING {_TEMPLATE_COLS}"
        cur.execute(sql, params)
        return _com_imagem_url(cur.fetchone())

def get_template(template_id: int, organizacao_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    with get_db_cursor() as cur:
        if organizacao_id is not None:
            cur.execute(f"SELECT {_TEMPLATE_COLS} FROM email_templates WHERE id = %s AND organizacao_id = %s", (template_id, organizacao_id))
        else:
            cur.execute(f"SELECT {_TEMPLATE_COLS} FROM email_templates WHERE id = %s", (template_id,))
        return _com_imagem_url(cur.fetchone())

def get_all_templates(organizacao_id: Optional[int] = None) -> List[Dict[str, Any]]:
    with get_db_cursor() as cur:
        if organizacao_id is not None:
            cur.execute(f"SELECT {_TEMPLATE_COLS} FROM email_templates WHERE organizacao_id = %s ORDER BY created_at DESC", (organizacao_id,))
        else:
            cur.execute(f"SELECT {_TEMPLATE_COLS} FROM email_templates ORDER BY created_at DESC")
        return [_com_imagem_url(r) for r in cur.fetchall()]

def delete_template(template_id: int, organizacao_id: Optional[int] = None) -> bool:
    with get_db_cursor() as cur:
        if organizacao_id is not None:
            cur.execute("DELETE FROM email_templates WHERE id = %s AND organizacao_id = %s", (template_id, organizacao_id))
        else:
            cur.execute("DELETE FROM email_templates WHERE id = %s", (template_id,))
        return cur.rowcount > 0

def get_templates_by_categoria(categoria_cnae: str, organizacao_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Retorna templates filtrados por categoria (e por empresa, se informada).
    Se categoria = 'todos', traz todos (da empresa)."""
    org_sql = " AND organizacao_id = %s" if organizacao_id is not None else ""
    with get_db_cursor() as cur:
        if categoria_cnae == "todos":
            params = [organizacao_id] if organizacao_id is not None else []
            cur.execute(f"SELECT {_TEMPLATE_COLS} FROM email_templates WHERE categoria_cnae = 'todos'{org_sql} ORDER BY created_at DESC", params)
        else:
            # Pega templates da categoria especifica + templates 'todos' (fallback)
            params = [categoria_cnae] + ([organizacao_id] if organizacao_id is not None else [])
            cur.execute(f"SELECT {_TEMPLATE_COLS} FROM email_templates WHERE categoria_cnae IN (%s, 'todos'){org_sql} ORDER BY categoria_cnae DESC, created_at DESC", params)
        return [_com_imagem_url(r) for r in cur.fetchall()]

def set_template_imagem(template_id: int, imagem_bytes: bytes, mime: str, organizacao_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Salva/substitui o card (imagem) de um template. Facilmente re-chamavel para trocar a imagem."""
    org_sql = " AND organizacao_id = %s" if organizacao_id is not None else ""
    params = [imagem_bytes, mime, template_id] + ([organizacao_id] if organizacao_id is not None else [])
    with get_db_cursor() as cur:
        cur.execute(
            f"UPDATE email_templates SET imagem_data = %s, imagem_mime = %s, tem_imagem = TRUE, updated_at = NOW() WHERE id = %s{org_sql} RETURNING {_TEMPLATE_COLS}",
            params,
        )
        return _com_imagem_url(cur.fetchone())

def get_template_imagem(template_id: int) -> Optional[Dict[str, Any]]:
    """Le os bytes crus da imagem -- usado apenas pelo endpoint publico que serve a imagem."""
    with get_db_cursor() as cur:
        cur.execute("SELECT imagem_data, imagem_mime FROM email_templates WHERE id = %s AND tem_imagem = TRUE", (template_id,))
        return cur.fetchone()

def clear_template_imagem(template_id: int, organizacao_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    org_sql = " AND organizacao_id = %s" if organizacao_id is not None else ""
    params = [template_id] + ([organizacao_id] if organizacao_id is not None else [])
    with get_db_cursor() as cur:
        cur.execute(
            f"UPDATE email_templates SET imagem_data = NULL, imagem_mime = NULL, tem_imagem = FALSE, updated_at = NOW() WHERE id = %s{org_sql} RETURNING {_TEMPLATE_COLS}",
            params,
        )
        return _com_imagem_url(cur.fetchone())
def create_campanha(
    nome: str, template_id: Optional[int], filtros: Dict, created_by: Optional[str] = None,
    eh_sequencia: bool = False, agendada_para: Optional[str] = None, organizacao_id: Optional[int] = None,
    canal: str = "email", mensagem: Optional[str] = None, tamanho_lote: Optional[int] = None,
    repetir_ate: Optional[str] = None, remetente_username: Optional[str] = None,
) -> Dict[str, Any]:
    status = "agendada" if agendada_para else "rascunho"
    with get_db_cursor() as cur:
        cur.execute(
            """INSERT INTO campanhas
               (nome, template_id, filtros, status, created_by, eh_sequencia, agendada_para, organizacao_id, canal, mensagem, tamanho_lote, repetir_ate, remetente_username)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
            (nome, template_id, json.dumps(filtros or {}), status, created_by, eh_sequencia, agendada_para,
             organizacao_id, canal, mensagem, tamanho_lote, repetir_ate, remetente_username),
        )
        row = cur.fetchone()
        if row and row.get("filtros") and isinstance(row["filtros"], str):
            try: row["filtros"] = json.loads(row["filtros"])
            except: pass
        return row

def get_campanha(campanha_id: int, organizacao_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    with get_db_cursor() as cur:
        if organizacao_id is not None:
            cur.execute("SELECT * FROM campanhas WHERE id = %s AND organizacao_id = %s", (campanha_id, organizacao_id))
        else:
            cur.execute("SELECT * FROM campanhas WHERE id = %s", (campanha_id,))
        row = cur.fetchone()
        if row and row.get("filtros") and isinstance(row["filtros"], str):
            try: row["filtros"] = json.loads(row["filtros"])
            except: pass
        return row

def get_all_campanhas(organizacao_id: Optional[int] = None) -> List[Dict[str, Any]]:
    with get_db_cursor() as cur:
        if organizacao_id is not None:
            cur.execute("SELECT * FROM campanhas WHERE organizacao_id = %s ORDER BY created_at DESC", (organizacao_id,))
        else:
            cur.execute("SELECT * FROM campanhas ORDER BY created_at DESC")
        rows = cur.fetchall()
        for r in rows:
            if r and r.get("filtros") and isinstance(r["filtros"], str):
                try: r["filtros"] = json.loads(r["filtros"])
                except: pass
        return rows

def update_campanha_status(campanha_id: int, status: str, **kwargs) -> Optional[Dict[str, Any]]:
    sets = [f"{k} = %s" for k in kwargs.keys()]
    sets.append("status = %s")
    vals = list(kwargs.values()) + [status, campanha_id]
    with get_db_cursor() as cur:
        cur.execute(f"UPDATE campanhas SET {', '.join(sets)} WHERE id = %s RETURNING *", vals)
        row = cur.fetchone()
        if row and row.get("filtros") and isinstance(row["filtros"], str):
            try: row["filtros"] = json.loads(row["filtros"])
            except: pass
        return row

def create_email_enviado(campaign_id: Optional[int], cnpj: str, email_destino: str, assunto: Optional[str] = None, sequencia_passo: int = 0,
                         template_id: Optional[int] = None) -> Dict[str, Any]:
    # A empresa (organizacao_id) e' herdada da campanha via subquery, entao o
    # motor de envio (mailer) nao precisa saber a empresa -- fica sempre
    # consistente com a campanha a que o email pertence.
    with get_db_cursor() as cur:
        cur.execute(
            """INSERT INTO emails_enviados
                 (campaign_id, cnpj, email_destino, assunto, sequencia_passo, organizacao_id, template_id)
               VALUES (%s, %s, %s, %s, %s, (SELECT organizacao_id FROM campanhas WHERE id = %s), %s)
               RETURNING *""",
            (campaign_id, cnpj, email_destino, assunto, sequencia_passo, campaign_id, template_id),
        )
        return cur.fetchone()

def update_email_enviado(email_id: int, status: str, erro: Optional[str] = None,
                         message_id: Optional[str] = None) -> None:
    """message_id: o Message-ID do SMTP. E' a chave que liga este registro aos
    eventos do webhook do provedor (entrega, abertura, clique, bounce)."""
    with get_db_cursor() as cur:
        cur.execute(
            """UPDATE emails_enviados
                  SET status = %s,
                      erro = COALESCE(%s, erro),
                      message_id = COALESCE(%s, message_id),
                      enviado_em = NOW()
                WHERE id = %s""",
            (status, erro, message_id, email_id),
        )


def get_emails_enviados_by_campanha(campaign_id: int) -> List[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute("SELECT * FROM emails_enviados WHERE campaign_id = %s ORDER BY criado_em DESC", (campaign_id,))
        return cur.fetchall()
def create_notificacao(tipo: str, titulo: str, mensagem: Optional[str] = None, cnpj: Optional[str] = None, user_id: Optional[str] = None, organizacao_id: Optional[int] = None) -> Dict[str, Any]:
    with get_db_cursor() as cur:
        cur.execute("INSERT INTO notificacoes (tipo, titulo, mensagem, cnpj, user_id, organizacao_id) VALUES (%s, %s, %s, %s, %s, %s) RETURNING *", (tipo, titulo, mensagem, cnpj, user_id, organizacao_id))
        return cur.fetchone()

def get_notificacoes(user_id: Optional[str] = None, lidas: Optional[bool] = None, limit: int = 100, organizacao_id: Optional[int] = None) -> List[Dict[str, Any]]:
    with get_db_cursor() as cur:
        # o nome da empresa vem junto: ver "Nova tarefa X" sem saber em qual
        # empresa ela caiu foi exatamente o que escondeu um registro criado
        # na empresa errada.
        sql = ("SELECT n.*, o.nome AS organizacao_nome FROM notificacoes n "
               "LEFT JOIN organizacoes o ON o.id = n.organizacao_id WHERE 1=1")
        params = []
        if organizacao_id is not None:
            sql += " AND n.organizacao_id = %s"
            params.append(organizacao_id)
        if user_id:
            sql += " AND (n.user_id = %s OR n.user_id IS NULL)"
            params.append(user_id)
        if lidas is not None:
            sql += " AND n.lida = %s"
            params.append(lidas)
        sql += " ORDER BY n.created_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        return cur.fetchall()

def contar_notificacoes_nao_lidas(user_id: Optional[str] = None, organizacao_id: Optional[int] = None) -> int:
    """So' o numero, pro badge do menu -- puxar a lista inteira a cada
    poucos segundos so' pra contar sairia caro."""
    sql = "SELECT COUNT(*)::int AS n FROM notificacoes WHERE lida = FALSE"
    params: List[Any] = []
    if organizacao_id is not None:
        sql += " AND organizacao_id = %s"
        params.append(organizacao_id)
    if user_id:
        sql += " AND (user_id = %s OR user_id IS NULL)"
        params.append(user_id)
    with get_db_cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row["n"] if row else 0


def mark_notificacao_lida(notificacao_id: int, user_id: Optional[str] = None,
                          organizacao_id: Optional[int] = None) -> bool:
    """Marca como lida. Filtra por usuario e empresa: antes bastava o id pra
    marcar lida a notificacao de outra pessoa (ou de outra empresa)."""
    sql = "UPDATE notificacoes SET lida = TRUE WHERE id = %s"
    params: List[Any] = [notificacao_id]
    if organizacao_id is not None:
        sql += " AND organizacao_id = %s"
        params.append(organizacao_id)
    if user_id:
        sql += " AND (user_id = %s OR user_id IS NULL)"
        params.append(user_id)
    with get_db_cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount > 0


# PUSH SUBSCRIPTIONS (PWA / Web Push)

def salvar_push_subscription(username: str, organizacao_id: Optional[int], endpoint: str,
                             p256dh: str, auth: str, user_agent: Optional[str] = None) -> Dict[str, Any]:
    """Registra (ou atualiza) o navegador/celular que ativou avisos push.
    Mesmo endpoint reinscrito (ex.: trocou de empresa ativa) atualiza o
    dono/org em vez de duplicar -- UNIQUE(endpoint)."""
    with get_db_cursor() as cur:
        cur.execute(
            """INSERT INTO push_subscriptions (username, organizacao_id, endpoint, p256dh, auth, user_agent)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (endpoint) DO UPDATE SET
                   username = EXCLUDED.username,
                   organizacao_id = EXCLUDED.organizacao_id,
                   p256dh = EXCLUDED.p256dh,
                   auth = EXCLUDED.auth,
                   user_agent = EXCLUDED.user_agent,
                   criado_em = NOW()
               RETURNING *""",
            (username, organizacao_id, endpoint, p256dh, auth, user_agent),
        )
        return cur.fetchone()


def remover_push_subscription(endpoint: str, username: Optional[str] = None) -> bool:
    """Desativa avisos de um aparelho. Com username, so remove o proprio
    (ninguem desliga o push de outra pessoa)."""
    sql = "DELETE FROM push_subscriptions WHERE endpoint = %s"
    params: List[Any] = [endpoint]
    if username:
        sql += " AND username = %s"
        params.append(username)
    with get_db_cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount > 0


def listar_push_subscriptions(organizacao_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Inscricoes alvo de um disparo: da empresa (broadcast por empresa) ou
    todas (broadcast global). So aparelhos ainda com usuario ativo."""
    sql = ("SELECT s.* FROM push_subscriptions s "
           "JOIN app_users u ON u.username = s.username AND u.is_active = TRUE WHERE 1=1")
    params: List[Any] = []
    if organizacao_id is not None:
        sql += " AND s.organizacao_id = %s"
        params.append(organizacao_id)
    with get_db_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def listar_todas_organizacoes_ids() -> List[int]:
    """IDs das empresas ativas -- broadcast global grava um aviso (sino) por empresa."""
    with get_db_cursor() as cur:
        cur.execute("SELECT id FROM organizacoes WHERE ativo = TRUE ORDER BY id")
        return [r["id"] for r in cur.fetchall()]


# MONITOR DE EMAILS (FOLLOW-UP)

def get_emails_for_monitor(
    campaign_id=None,
    dias_sla: int = 7,
    sla_verde_dias: Optional[int] = None,
    sla_amarelo_dias: Optional[int] = None,
    limit: int = 200,
    offset: int = 0,
    organizacao_id: Optional[int] = None,
):
    """
    Retorna e-mails enviados com cálculo de status de semáforo para follow-up.

    Status do semáforo (prazos configuraveis via app_config -- ver
    get_sla_config/set_sla_config -- padrao 2/5 dias se nunca configurado):
      - verde:    aberto_em IS NOT NULL (há resposta/interação)
                  OU dentro do prazo "verde"
      - amarelo:  passou do prazo "verde" mas ainda dentro do "amarelo",
                  sem aberto_em (atenção)
      - vermelho: passou do prazo "amarelo", sem aberto_em (follow-up urgente)
      - cinza:    status != 'enviado' (pendente, erro, etc.)
    """
    if sla_verde_dias is None or sla_amarelo_dias is None:
        sla = get_sla_config()
        sla_verde_dias = sla_verde_dias if sla_verde_dias is not None else sla["sla_verde_dias"]
        sla_amarelo_dias = sla_amarelo_dias if sla_amarelo_dias is not None else sla["sla_amarelo_dias"]

    with get_db_cursor() as cur:
        params: List[Any] = [sla_verde_dias, sla_amarelo_dias]
        where_org = "AND e.organizacao_id = %s" if organizacao_id is not None else ""
        where_campaign = ""
        if campaign_id:
            where_campaign = "AND e.campaign_id = %s"

        sql = f"""
            SELECT
                e.id,
                e.campaign_id,
                e.cnpj,
                e.email_destino,
                e.assunto,
                e.status,
                e.erro,
                e.sequencia_passo,
                e.enviado_em,
                e.aberto_em,
                e.criado_em,
                c.nome as campanha_nome,
                COALESCE(
                    GREATEST(EXTRACT(EPOCH FROM (NOW() - e.enviado_em)) / 86400.0, 0),
                    0
                ) as dias_desde_envio,
                CASE
                    WHEN e.enviado_em IS NULL THEN 'cinza'
                    WHEN e.aberto_em IS NOT NULL THEN 'verde'
                    WHEN GREATEST(EXTRACT(EPOCH FROM (NOW() - e.enviado_em)) / 86400.0, 0) <= %s THEN 'verde'
                    WHEN GREATEST(EXTRACT(EPOCH FROM (NOW() - e.enviado_em)) / 86400.0, 0) <= %s THEN 'amarelo'
                    ELSE 'vermelho'
                END as semaforo_status,
                emp.razao_social,
                emp.nome_fantasia
            FROM emails_enviados e
            LEFT JOIN campanhas c ON c.id = e.campaign_id
            LEFT JOIN dados_empresas emp ON emp.cnpj_completo = e.cnpj
            WHERE e.enviado_em IS NOT NULL
            {where_org}
            {where_campaign}
            ORDER BY e.enviado_em DESC
            LIMIT %s OFFSET %s
        """
        if organizacao_id is not None:
            params.append(organizacao_id)
        if campaign_id:
            params.append(campaign_id)
        params.extend([limit, offset])
        cur.execute(sql, params)
        rows = cur.fetchall()
        return rows


def get_monitor_stats(dias_sla: int = 7, sla_verde_dias: Optional[int] = None, sla_amarelo_dias: Optional[int] = None, organizacao_id: Optional[int] = None):
    """Retorna estatísticas agregadas para o dashboard de monitoramento.
    Prazos configuraveis -- ver get_sla_config/set_sla_config."""
    if sla_verde_dias is None or sla_amarelo_dias is None:
        sla = get_sla_config()
        sla_verde_dias = sla_verde_dias if sla_verde_dias is not None else sla["sla_verde_dias"]
        sla_amarelo_dias = sla_amarelo_dias if sla_amarelo_dias is not None else sla["sla_amarelo_dias"]

    where_org = "WHERE organizacao_id = %(org)s" if organizacao_id is not None else ""
    with get_db_cursor() as cur:
        sql = f"""
            SELECT
                COUNT(*) FILTER (WHERE status = 'enviado') as total_enviados,
                COUNT(*) FILTER (
                    WHERE (aberto_em IS NOT NULL)
                       OR (enviado_em IS NOT NULL AND EXTRACT(EPOCH FROM (NOW() - enviado_em)) / 86400.0 <= %(verde)s)
                ) as verde,
                COUNT(*) FILTER (
                    WHERE enviado_em IS NOT NULL
                      AND aberto_em IS NULL
                      AND EXTRACT(EPOCH FROM (NOW() - enviado_em)) / 86400.0 > %(verde)s
                      AND EXTRACT(EPOCH FROM (NOW() - enviado_em)) / 86400.0 <= %(amarelo)s
                ) as amarelo,
                COUNT(*) FILTER (
                    WHERE enviado_em IS NOT NULL
                      AND aberto_em IS NULL
                      AND EXTRACT(EPOCH FROM (NOW() - enviado_em)) / 86400.0 > %(amarelo)s
                ) as vermelho,
                COUNT(*) FILTER (WHERE status != 'enviado') as cinza
            FROM emails_enviados
            {where_org}
        """
        cur.execute(sql, {"verde": sla_verde_dias, "amarelo": sla_amarelo_dias, "org": organizacao_id})
        row = cur.fetchone()
        return dict(row) if row else {"total_enviados": 0, "verde": 0, "amarelo": 0, "vermelho": 0, "cinza": 0}


def get_emails_vermelhos_para_followup(limite: int = 50, organizacao_id: Optional[int] = None):
    """Retorna os e-mails mais críticos (vermelho) para disparo de follow-up."""
    where_org = "AND e.organizacao_id = %s" if organizacao_id is not None else ""
    params = ([organizacao_id] if organizacao_id is not None else []) + [limite]
    with get_db_cursor() as cur:
        sql = f"""
            SELECT
                e.*,
                c.nome as campanha_nome,
                GREATEST(EXTRACT(EPOCH FROM (NOW() - e.enviado_em)) / 86400.0, 0) as dias_desde_envio,
                emp.razao_social,
                emp.nome_fantasia
            FROM emails_enviados e
            LEFT JOIN campanhas c ON c.id = e.campaign_id
            LEFT JOIN dados_empresas emp ON emp.cnpj_completo = e.cnpj
            WHERE e.enviado_em IS NOT NULL
              AND e.aberto_em IS NULL
              AND GREATEST(EXTRACT(EPOCH FROM (NOW() - e.enviado_em)) / 86400.0, 0) > 5
              {where_org}
            ORDER BY e.enviado_em ASC
            LIMIT %s
        """
        cur.execute(sql, params)
        return cur.fetchall()


def marcar_email_clicado(email_id: int, link: Optional[str] = None) -> bool:
    """Registra clique. Marca abertura junto: quem clicou leu."""
    with get_db_cursor() as cur:
        cur.execute(
            """UPDATE emails_enviados
                  SET clicado_em = COALESCE(clicado_em, NOW()),
                      aberto_em  = COALESCE(aberto_em, NOW()),
                      cliques    = COALESCE(cliques, 0) + 1,
                      ultimo_link = COALESCE(%s, ultimo_link)
                WHERE id = %s""",
            (link, email_id),
        )
        return cur.rowcount > 0


def marcar_email_aberto(email_id: int) -> bool:
    """Marca o e-mail como aberto (usado por pixel de tracking)."""
    with get_db_cursor() as cur:
        cur.execute(
            "UPDATE emails_enviados SET aberto_em = NOW() WHERE id = %s AND aberto_em IS NULL",
            (email_id,),
        )
        return cur.rowcount > 0



def create_audit_log(action: str, user_id: Optional[str] = None, ip_address: Optional[str] = None, resource_type: Optional[str] = None, resource_id: Optional[str] = None, details: Optional[dict] = None, success: bool = True) -> Optional[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute(
            "INSERT INTO audit_log (action, user_id, ip_address, resource_type, resource_id, details, success) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (action, user_id, ip_address, resource_type, resource_id, json.dumps(details or {}), success)
        )
        return cur.fetchone()


def record_login_attempt(username: str, ip_address: Optional[str] = None, success: bool = True) -> None:
    with get_db_cursor() as cur:
        cur.execute(
            "INSERT INTO login_attempts (username, ip_address, success) VALUES (%s, %s, %s)",
            (username, ip_address, success)
        )


def is_account_locked(username: str, max_attempts: int = 5, lockout_minutes: int = 15) -> bool:
    with get_db_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) as cnt FROM login_attempts WHERE username = %s AND success = FALSE AND attempted_at > NOW() - INTERVAL '%s minutes'",
            (username, lockout_minutes)
        )
        row = cur.fetchone()
        return (row and row.get("cnt", 0) >= max_attempts)


def get_audit_logs(user_id: Optional[str] = None, action: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    with get_db_cursor() as cur:
        sql = "SELECT * FROM audit_log WHERE 1=1"
        params = []
        if user_id:
            sql += " AND user_id = %s"
            params.append(user_id)
        if action:
            sql += " AND action = %s"
            params.append(action)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        return cur.fetchall()


# PASSWORD RESET

def create_password_reset_token(user_id: int, token_hash: str, expires_at) -> Dict[str, Any]:
    """Cria token de recuperacao de senha."""
    with get_db_cursor() as cur:
        cur.execute(
            "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES (%s, %s, %s) RETURNING *",
            (user_id, token_hash, expires_at)
        )
        return cur.fetchone()


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Busca usuario pelo e-mail."""
    with get_db_cursor() as cur:
        cur.execute("SELECT * FROM app_users WHERE email = %s", (email,))
        return cur.fetchone()


def get_user_by_username_or_email(username_or_email: str) -> Optional[Dict[str, Any]]:
    """Busca usuario pelo username ou e-mail."""
    with get_db_cursor() as cur:
        cur.execute(
            "SELECT * FROM app_users WHERE username = %s OR email = %s",
            (username_or_email, username_or_email)
        )
        return cur.fetchone()


def get_password_reset_token(token_hash: str) -> Optional[Dict[str, Any]]:
    """Busca token de recuperacao pelo hash."""
    with get_db_cursor() as cur:
        cur.execute(
            "SELECT * FROM password_reset_tokens WHERE token_hash = %s AND used = FALSE AND expires_at > NOW()",
            (token_hash,)
        )
        return cur.fetchone()


def mark_password_reset_token_used(token_id: int) -> bool:
    """Marca token de recuperacao como usado."""
    with get_db_cursor() as cur:
        cur.execute(
            "UPDATE password_reset_tokens SET used = TRUE WHERE id = %s",
            (token_id,)
        )
        return cur.rowcount > 0


def update_user_password(user_id: int, password_hash: str) -> bool:
    """Atualiza senha do usuario."""
    with get_db_cursor() as cur:
        cur.execute(
            "UPDATE app_users SET password_hash = %s, updated_at = NOW() WHERE id = %s",
            (password_hash, user_id)
        )
        return cur.rowcount > 0


# EMPRESAS (DADOS DA RECEITA FEDERAL)
# As tabelas dados_empresas / dados_socios / municipios sao populadas pelo
# pipeline de ETL (whodados/pipeline/pipeline.py + scripts/sync_data_to_db.py,
# rodado pelo GitHub Action .github/workflows/whodados-etl.yml). Enquanto o
# pipeline nao tiver rodado ainda, essas tabelas nao existem -- as funcoes
# abaixo detectam isso e retornam vazio/zero em vez de lancar erro, para o
# resto da aplicacao nunca quebrar por falta desses dados.


# Expressoes SQL que derivam PORTE_NOME e CONTATO_FONE on-the-fly (as duas
# colunas foram removidas da tabela: eram redundantes -- PORTE_NOME e um
# mapeamento fixo do PORTE_EMPRESA, e CONTATO_FONE e so DDD + TELEFONE
# concatenado. Manter derivado economiza ~30MB no Postgres e preserva a
# API que o frontend consome (porte_nome e contato_fone continuam saindo
# nos SELECTs, so mudou como sao produzidos).
# PORTE_NOME_SQL / PORTE_NOME_TO_CODE vivem em db/filtros.py (codigos RF).
CONTATO_FONE_SQL = (
    "'(' || COALESCE(e.\"DDD\", '') || ') ' || COALESCE(e.\"TELEFONE\", '')"
)

# Score de potencial / empresas_potencial: REMOVIDOS em 2026-09 (tabela
# dropada em prod: score nunca calibrado ao ICP, 209 MB). Se um dia voltar,
# recalibrar a formula antes de repovoar -- ver CHECKPOINT_2026-09-19.md.

# CONFIGURACOES DA APLICACAO (app_config)

_SLA_PADRAO = {"sla_verde_dias": 2, "sla_amarelo_dias": 5}


def get_app_config() -> Dict[str, str]:
    """Le todos os pares chave-valor de app_config. Retorna vazio (sem
    quebrar) se a tabela ainda nao existir."""
    try:
        with get_db_cursor() as cur:
            if not _tabela_existe(cur, "app_config"):
                return {}
            cur.execute("SELECT chave, valor FROM app_config")
            return {r["chave"]: r["valor"] for r in cur.fetchall()}
    except Exception as e:
        log.warning(f"get_app_config falhou, retornando vazio: {e}")
        return {}


def set_app_config(chave: str, valor: str) -> None:
    with get_db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO app_config (chave, valor, atualizado_em)
            VALUES (%s, %s, NOW())
            ON CONFLICT (chave) DO UPDATE
                SET valor = EXCLUDED.valor, atualizado_em = NOW()
            """,
            (chave, valor),
        )


def get_sla_config() -> Dict[str, int]:
    """Prazos (em dias) que definem o semaforo do Monitor de e-mails.
    Le de app_config; usa os padroes (2/5 dias) se nao estiver configurado
    ou se os valores gravados forem invalidos."""
    cfg = get_app_config()
    resultado = dict(_SLA_PADRAO)
    for chave, padrao in _SLA_PADRAO.items():
        valor = cfg.get(chave)
        if valor is not None:
            try:
                resultado[chave] = int(valor)
            except (TypeError, ValueError):
                pass
    return resultado


def set_sla_config(sla_verde_dias: int, sla_amarelo_dias: int) -> None:
    """Grava os prazos do semaforo. Validacao basica: verde tem que ser
    menor que amarelo, os dois positivos -- senao o semaforo fica sem
    sentido (ex: tudo cai direto em vermelho)."""
    if sla_verde_dias < 1 or sla_amarelo_dias < 1:
        raise ValueError("Os prazos precisam ser maiores que zero")
    if sla_verde_dias >= sla_amarelo_dias:
        raise ValueError("O prazo 'verde' precisa ser menor que o prazo 'amarelo'")
    set_app_config("sla_verde_dias", str(sla_verde_dias))
    set_app_config("sla_amarelo_dias", str(sla_amarelo_dias))


# GESTAO DE USUARIOS

def list_all_users() -> List[Dict[str, Any]]:
    """Lista todos os usuarios do sistema (sem o hash de senha)."""
    with get_db_cursor() as cur:
        cur.execute(
            "SELECT id, username, email, is_admin, is_active, created_at "
            "FROM app_users ORDER BY created_at ASC"
        )
        return cur.fetchall()


def update_user_flags(user_id: int, is_admin: Optional[bool] = None, is_active: Optional[bool] = None) -> bool:
    """Atualiza is_admin e/ou is_active de um usuario. So altera os campos
    passados (None = nao muda)."""
    campos = []
    valores: List[Any] = []
    if is_admin is not None:
        campos.append("is_admin = %s")
        valores.append(is_admin)
    if is_active is not None:
        campos.append("is_active = %s")
        valores.append(is_active)
    if not campos:
        return False
    campos.append("updated_at = NOW()")
    valores.append(user_id)
    with get_db_cursor() as cur:
        cur.execute(f"UPDATE app_users SET {', '.join(campos)} WHERE id = %s", valores)
        return cur.rowcount > 0


# MULTI-EMPRESA (ORGANIZACOES)
# Multi-empresa: Base de leads e
# compartilhada; o CONTROLE (crm, campanhas, templates, monitor, notificacoes,
# remetente) e isolado por organizacao. O acesso e por usuario.

def listar_organizacoes_do_usuario(username: str) -> List[Dict[str, Any]]:
    """Empresas que o usuario pode operar (para o seletor de empresa ativa),
    com o papel dele em cada uma (admin/membro/visitante)."""
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT o.id, o.nome, o.slug, o.ativo,
                   COALESCE(o.escopo_base, 'receita') AS escopo_base, uo.papel,
                   -- O menu decide por TER lista, nao pelo escopo: a Alfa
                   -- pesquisa na base da Receita e tem carteira recortada.
                   EXISTS (SELECT 1 FROM empresas_carteira c
                            WHERE c.organizacao_id = o.id) AS tem_carteira
            FROM organizacoes o
            JOIN usuario_organizacoes uo ON uo.organizacao_id = o.id
            JOIN app_users u ON u.id = uo.user_id
            WHERE u.username = %s AND o.ativo = TRUE
            ORDER BY o.id
            """,
            (username,),
        )
        return cur.fetchall()


def get_papel_usuario_org(username: str, organizacao_id: int) -> Optional[str]:
    """Papel do usuario NESSA organizacao (admin/membro/visitante), ou None
    se ele nao tiver vinculo com ela."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT uo.papel FROM usuario_organizacoes uo
               JOIN app_users u ON u.id = uo.user_id
               WHERE u.username = %s AND uo.organizacao_id = %s""",
            (username, organizacao_id),
        )
        row = cur.fetchone()
        return row["papel"] if row else None


def definir_papel_usuario_org(user_id: int, organizacao_id: int, papel: str) -> bool:
    """Muda o papel de um usuario numa empresa onde ele ja tem acesso.
    Nao cria o vinculo -- so' atualiza um que ja existe (use
    definir_acesso_usuario_orgs pra dar acesso primeiro)."""
    if papel not in ("admin", "membro", "visitante"):
        return False
    with get_db_cursor() as cur:
        cur.execute(
            "UPDATE usuario_organizacoes SET papel = %s WHERE user_id = %s AND organizacao_id = %s",
            (papel, user_id, organizacao_id),
        )
        return cur.rowcount > 0


def usuario_tem_acesso_org(username: str, organizacao_id: int) -> bool:
    """True se o usuario esta vinculado aquela empresa."""
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM usuario_organizacoes uo
            JOIN app_users u ON u.id = uo.user_id
            WHERE u.username = %s AND uo.organizacao_id = %s
            """,
            (username, organizacao_id),
        )
        return cur.fetchone() is not None


def criar_organizacao(nome: str, slug: Optional[str] = None) -> Dict[str, Any]:
    """Cria uma empresa (organizacao). Slug e' derivado do nome quando nao
    informado -- e' o identificador estavel, o nome pode mudar depois."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Nome e' obrigatorio")
    if not slug:
        slug = re.sub(r"[^a-z0-9]+", "-", nome.lower()).strip("-")[:60] or "empresa"
    with get_db_cursor() as cur:
        cur.execute(
            "INSERT INTO organizacoes (nome, slug) VALUES (%s, %s) "
            "ON CONFLICT (slug) DO NOTHING RETURNING id, nome, slug, ativo",
            (nome, slug),
        )
        row = cur.fetchone()
        if row:
            return row
        cur.execute("SELECT id, nome, slug, ativo FROM organizacoes WHERE slug = %s", (slug,))
        return cur.fetchone()


def renomear_organizacao(organizacao_id: int, nome: str) -> bool:
    """Muda so' o nome exibido. O slug continua o mesmo de proposito: e' o
    que amarra os dados (CRM, campanhas) a empresa."""
    nome = (nome or "").strip()
    if not nome:
        return False
    with get_db_cursor() as cur:
        cur.execute("UPDATE organizacoes SET nome = %s WHERE id = %s", (nome, organizacao_id))
        return cur.rowcount > 0


def listar_todas_organizacoes() -> List[Dict[str, Any]]:
    """Todas as empresas (uso administrativo), com a fonte de prospeccao."""
    with get_db_cursor() as cur:
        cur.execute("SELECT id, nome, slug, ativo, COALESCE(escopo_base, 'receita') AS escopo_base, "
                    "       email_limite_diario "
                    "FROM organizacoes ORDER BY id")
        return cur.fetchall()


ESCOPOS_BASE = ("receita", "carteira")


def definir_escopo_base(organizacao_id: int, escopo: str) -> bool:
    """Troca a FONTE de prospeccao da empresa.

    'receita' le a base publica da Receita Federal; 'carteira' le so' a lista
    propria (empresas_carteira). As telas sao as mesmas -- o que muda e' de
    onde vem o dado, resolvido em listar_empresas_db/contar_empresas_db.

    Vira decisao de contrato, entao quem chama e' rota de admin GLOBAL: virar
    a chave troca o que a empresa inteira enxerga. Empresa que passa pra
    carteira com a lista ainda vazia ve a base zerada ate' importar a
    planilha -- por isso a tela avisa antes de confirmar."""
    escopo = (escopo or "").strip().lower()
    if escopo not in ESCOPOS_BASE:
        raise ValueError("Fonte invalida: use 'receita' ou 'carteira'")
    with get_db_cursor() as cur:
        cur.execute("UPDATE organizacoes SET escopo_base = %s WHERE id = %s", (escopo, organizacao_id))
        return cur.rowcount > 0


def definir_acesso_usuario_orgs(user_id: int, organizacao_ids: List[int]) -> None:
    """Define exatamente a quais empresas um usuario tem acesso (substitui as
    anteriores). Lista vazia = sem acesso a nenhuma."""
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM usuario_organizacoes WHERE user_id = %s", (user_id,))
        for org_id in organizacao_ids or []:
            cur.execute(
                "INSERT INTO usuario_organizacoes (user_id, organizacao_id) "
                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, org_id),
            )


def get_orgs_do_user_id(user_id: int) -> List[int]:
    """IDs das empresas de um usuario (por id) -- usado ao listar usuarios."""
    with get_db_cursor() as cur:
        cur.execute(
            "SELECT organizacao_id FROM usuario_organizacoes WHERE user_id = %s ORDER BY organizacao_id",
            (user_id,),
        )
        return [r["organizacao_id"] for r in cur.fetchall()]


# Config de e-mail (SMTP + assinatura) por empresa

# Usado quando a empresa ainda nao definiu a identidade dela.
IDENTIDADE_PADRAO = {
    "cor_principal": "#1F2A44",
    "cor_texto": "#3A4556",
    "cor_fundo": "#F1F3F6",
    "fonte": "Arial,Helvetica,sans-serif",
    "selo": "",
}


# PROPOSTAS

STATUS_PROPOSTA = ("rascunho", "enviada", "aceita", "recusada")


def criar_proposta(organizacao_id: int, cliente: str, titulo: Optional[str],
                   campos: Dict[str, Any], conteudo: Dict[str, Any],
                   criado_por: Optional[str] = None) -> Dict[str, Any]:
    with get_db_cursor() as cur:
        cur.execute(
            """INSERT INTO propostas (organizacao_id, cliente, titulo, campos, conteudo, criado_por)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
            (organizacao_id, cliente.strip(), (titulo or "").strip() or None,
             Json(campos), Json(conteudo), criado_por),
        )
        return cur.fetchone()


def listar_propostas(organizacao_id: int, limite: int = 100) -> List[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT id, cliente, titulo, status, criado_por, criado_em, atualizado_em
                 FROM propostas WHERE organizacao_id = %s
                ORDER BY criado_em DESC LIMIT %s""",
            (organizacao_id, limite),
        )
        return cur.fetchall()


def get_proposta(proposta_id: int, organizacao_id: int) -> Optional[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute("SELECT * FROM propostas WHERE id = %s AND organizacao_id = %s",
                    (proposta_id, organizacao_id))
        return cur.fetchone()


def atualizar_proposta(proposta_id: int, organizacao_id: int,
                       **campos) -> Optional[Dict[str, Any]]:
    sets, valores = [], []
    for col in ("cliente", "titulo", "status"):
        if campos.get(col) is not None:
            sets.append(f"{col} = %s")
            valores.append(campos[col])
    for col in ("campos", "conteudo"):
        if campos.get(col) is not None:
            sets.append(f"{col} = %s")
            valores.append(Json(campos[col]))
    if not sets:
        return get_proposta(proposta_id, organizacao_id)
    with get_db_cursor() as cur:
        cur.execute(
            f"UPDATE propostas SET {', '.join(sets)}, atualizado_em = NOW() "
            "WHERE id = %s AND organizacao_id = %s RETURNING *",
            valores + [proposta_id, organizacao_id],
        )
        return cur.fetchone()


def deletar_proposta(proposta_id: int, organizacao_id: int) -> bool:
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM propostas WHERE id = %s AND organizacao_id = %s",
                    (proposta_id, organizacao_id))
        return cur.rowcount > 0


def get_identidade(organizacao_id: int) -> Dict[str, Any]:
    """Cores, fonte e selo da empresa -- o que veste proposta e e-mail.

    Fica em org_smtp_config porque e' a mesma linha que ja' guarda assinatura
    e logo: identidade visual da empresa num lugar so'."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT cor_principal, cor_texto, cor_fundo, fonte, selo,
                      (logo_data IS NOT NULL) AS tem_logo
                 FROM org_smtp_config WHERE organizacao_id = %s""",
            (organizacao_id,),
        )
        row = cur.fetchone()
    base = dict(IDENTIDADE_PADRAO, tem_logo=False)
    if row:
        base.update({k: v for k, v in dict(row).items() if v not in (None, "")})
        base["tem_logo"] = bool(row["tem_logo"])
    base["organizacao_id"] = organizacao_id
    return base


def set_identidade(organizacao_id: int, **campos) -> Dict[str, Any]:
    permitidos = ("cor_principal", "cor_texto", "cor_fundo", "fonte", "selo")
    sets, valores = [], []
    for col in permitidos:
        if campos.get(col) is not None:
            sets.append(f"{col} = %s")
            valores.append(campos[col])
    if sets:
        with get_db_cursor() as cur:
            cur.execute(
                "INSERT INTO org_smtp_config (organizacao_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (organizacao_id,),
            )
            cur.execute(
                f"UPDATE org_smtp_config SET {', '.join(sets)}, updated_at = NOW() "
                "WHERE organizacao_id = %s",
                valores + [organizacao_id],
            )
    return get_identidade(organizacao_id)


def get_org_smtp_config(organizacao_id: int, incluir_password: bool = False) -> Optional[Dict[str, Any]]:
    """Config de e-mail da empresa. Por padrao NAO retorna a senha (write-only);
    o mailer chama com incluir_password=True para poder enviar. Retorna None se
    a empresa nao tiver config."""
    with get_db_cursor() as cur:
        cur.execute("SELECT * FROM org_smtp_config WHERE organizacao_id = %s", (organizacao_id,))
        row = cur.fetchone()
    if not row:
        return None
    dados = dict(row)
    # "Configurada" significa TEM COMO ENVIAR. Quem envia e' a Gmail API,
    # que nao usa host nem usuario -- basta o remetente. Exigir host e
    # usuario aqui marcaria como nao configurada justamente a empresa
    # preenchida do jeito certo.
    dados["configurado"] = bool(dados.get("email_from"))
    # Servidor proprio e' outra coisa: so' importa se algum dia o envio
    # cair pro SMTP. A tela mostra os dois separados.
    dados["smtp_proprio"] = bool(dados.get("smtp_host") and dados.get("smtp_username"))
    dados["tem_logo"] = bool(dados.get("logo_data"))
    dados.pop("logo_data", None)  # bytes crus nunca vao no JSON
    _segredos_de_envio(dados, incluir_password)
    return dados


def _segredos_de_envio(dados: Dict[str, Any], incluir: bool) -> None:
    """Senha SMTP e autorizacao do Gmail so' saem daqui para o mailer. Um
    lugar so' para as duas tabelas: o SELECT * traz a coluna nova sozinho, e
    esquecer de tirar numa delas mandaria a autorizacao no JSON da tela."""
    dados["gmail_conectado"] = bool(dados.get("gmail_refresh_token"))
    for campo in ("smtp_password", "gmail_refresh_token"):
        if incluir:
            dados[campo] = decrypt_secret(dados.get(campo))
        else:
            dados.pop(campo, None)


def get_usuario_smtp_config(username: str, organizacao_id: int,
                            incluir_password: bool = False) -> Optional[Dict[str, Any]]:
    """Config de e-mail INDIVIDUAL do usuario nesta empresa. Campo nao
    preenchido volta None de proposito -- quem resolve a mistura com a
    config da empresa e' o mailer."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT c.* FROM usuario_smtp_config c
               JOIN app_users u ON u.id = c.user_id
               WHERE u.username = %s AND c.organizacao_id = %s""",
            (username, organizacao_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    dados = dict(row)
    _segredos_de_envio(dados, incluir_password)
    dados["configurado"] = bool(dados.get("email_from") or dados.get("smtp_host"))
    return dados


def set_usuario_smtp_config(username: str, organizacao_id: int, **campos) -> Optional[Dict[str, Any]]:
    """Cria/atualiza o e-mail individual. So altera o que foi passado
    (None = mantem). Senha vazia nao sobrescreve a que ja' existe."""
    permitidos = ("smtp_host", "smtp_port", "smtp_username", "smtp_use_tls",
                  "email_from", "email_from_name", "assinatura_html")
    with get_db_cursor() as cur:
        cur.execute("SELECT id FROM app_users WHERE username = %s", (username,))
        user = cur.fetchone()
        if not user:
            return None
        cur.execute(
            """INSERT INTO usuario_smtp_config (user_id, organizacao_id) VALUES (%s, %s)
               ON CONFLICT (user_id, organizacao_id) DO NOTHING""",
            (user["id"], organizacao_id),
        )
        sets, valores = [], []
        for col in permitidos:
            if campos.get(col) is not None:
                sets.append(f"{col} = %s")
                valores.append(campos[col])
        senha = campos.get("smtp_password")
        if senha:
            sets.append("smtp_password = %s")
            valores.append(encrypt_secret(senha))
        if not sets:
            return get_usuario_smtp_config(username, organizacao_id)
        sets.append("updated_at = NOW()")
        valores += [user["id"], organizacao_id]
        cur.execute(
            f"UPDATE usuario_smtp_config SET {', '.join(sets)} WHERE user_id = %s AND organizacao_id = %s",
            valores,
        )
    return get_usuario_smtp_config(username, organizacao_id)


def set_org_smtp_config(organizacao_id: int, smtp_host=None, smtp_port=None, smtp_username=None,
                        smtp_password=None, smtp_use_tls=None, email_from=None,
                        email_from_name=None, assinatura_html=None) -> Dict[str, Any]:
    """Cria/atualiza a config de e-mail da empresa. So altera os campos passados
    (None = mantem). Senha vazia/None nao sobrescreve a existente."""
    with get_db_cursor() as cur:
        cur.execute("INSERT INTO org_smtp_config (organizacao_id) VALUES (%s) ON CONFLICT (organizacao_id) DO NOTHING", (organizacao_id,))
        campos, valores = [], []
        for col, val in [
            ("smtp_host", smtp_host), ("smtp_port", smtp_port), ("smtp_username", smtp_username),
            ("smtp_use_tls", smtp_use_tls), ("email_from", email_from),
            ("email_from_name", email_from_name), ("assinatura_html", assinatura_html),
        ]:
            if val is not None:
                campos.append(f"{col} = %s"); valores.append(val)
        if smtp_password:  # so troca a senha se veio uma nova nao-vazia (cifrada em repouso)
            campos.append("smtp_password = %s"); valores.append(encrypt_secret(smtp_password))
        if campos:
            campos.append("updated_at = NOW()")
            valores.append(organizacao_id)
            cur.execute(f"UPDATE org_smtp_config SET {', '.join(campos)} WHERE organizacao_id = %s", valores)
    return get_org_smtp_config(organizacao_id)


def _tabela_da_conexao(cur, organizacao_id: int, username: Optional[str]):
    """Onde mora a conexao do Gmail: na config da pessoa ou na da empresa.
    Devolve (tabela, filtro, valores) ja' com a linha garantida, ou None se a
    pessoa nao existir."""
    if not username:
        cur.execute("INSERT INTO org_smtp_config (organizacao_id) VALUES (%s) "
                    "ON CONFLICT (organizacao_id) DO NOTHING", (organizacao_id,))
        return "org_smtp_config", "organizacao_id = %s", [organizacao_id]
    cur.execute("SELECT id FROM app_users WHERE username = %s", (username,))
    user = cur.fetchone()
    if not user:
        return None
    cur.execute("INSERT INTO usuario_smtp_config (user_id, organizacao_id) VALUES (%s, %s) "
                "ON CONFLICT (user_id, organizacao_id) DO NOTHING", (user["id"], organizacao_id))
    return "usuario_smtp_config", "user_id = %s AND organizacao_id = %s", [user["id"], organizacao_id]


def set_gmail_conexao(organizacao_id: int, conta: str, refresh_token: str,
                      username: Optional[str] = None) -> bool:
    """Guarda a conta do Gmail conectada: da pessoa (username) ou o padrao da
    empresa. Remetente em branco passa a ser a propria conta -- quem conecta
    espera sair enviando; quem ja' tinha remetente (um alias) mantem o seu."""
    with get_db_cursor() as cur:
        alvo = _tabela_da_conexao(cur, organizacao_id, username)
        if not alvo:
            return False
        tabela, filtro, valores = alvo
        cur.execute(
            f"""UPDATE {tabela} SET gmail_conta = %s, gmail_refresh_token = %s,
                    email_from = COALESCE(NULLIF(email_from, ''), NULLIF(%s, '')),
                    updated_at = NOW()
                WHERE {filtro}""",
            [conta, encrypt_secret(refresh_token), conta] + valores,
        )
    return True


def obter_gmail_refresh_token(organizacao_id: int, username: Optional[str] = None) -> Optional[str]:
    """Token guardado (decifrado) da conexao, para revogar no Google ao desconectar."""
    with get_db_cursor() as cur:
        alvo = _tabela_da_conexao(cur, organizacao_id, username)
        if not alvo:
            return None
        tabela, filtro, valores = alvo
        cur.execute(f"SELECT gmail_refresh_token FROM {tabela} WHERE {filtro}", valores)
        linha = cur.fetchone()
    return decrypt_secret(linha["gmail_refresh_token"]) if linha and linha["gmail_refresh_token"] else None


def remover_gmail_conexao(organizacao_id: int, username: Optional[str] = None) -> None:
    with get_db_cursor() as cur:
        alvo = _tabela_da_conexao(cur, organizacao_id, username)
        if not alvo:
            return
        tabela, filtro, valores = alvo
        cur.execute(f"UPDATE {tabela} SET gmail_conta = NULL, gmail_refresh_token = NULL, "
                    f"updated_at = NOW() WHERE {filtro}", valores)


def set_org_logo(organizacao_id: int, logo_bytes: bytes, mime: str) -> None:
    with get_db_cursor() as cur:
        cur.execute("INSERT INTO org_smtp_config (organizacao_id) VALUES (%s) ON CONFLICT (organizacao_id) DO NOTHING", (organizacao_id,))
        cur.execute("UPDATE org_smtp_config SET logo_data = %s, logo_mime = %s, updated_at = NOW() WHERE organizacao_id = %s", (logo_bytes, mime, organizacao_id))


def get_org_logo(organizacao_id: int) -> Optional[Dict[str, Any]]:
    """Bytes crus do logo -- usado pelo endpoint publico que serve o logo no e-mail."""
    with get_db_cursor() as cur:
        cur.execute("SELECT logo_data, logo_mime FROM org_smtp_config WHERE organizacao_id = %s", (organizacao_id,))
        return cur.fetchone()


def delete_user(user_id: int) -> bool:
    """Exclui um usuario. Os vinculos usuario_organizacoes caem por CASCADE."""
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM app_users WHERE id = %s", (user_id,))
        return cur.rowcount > 0


def update_user_email(user_id: int, email: Optional[str]) -> bool:
    """Atualiza o e-mail de um usuario (None/vazio limpa)."""
    with get_db_cursor() as cur:
        cur.execute("UPDATE app_users SET email = %s, updated_at = NOW() WHERE id = %s", (email or None, user_id))
        return cur.rowcount > 0


def _tabela_existe(cur, nome_tabela: str) -> bool:
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s) AS existe",
        (nome_tabela,),
    )
    row = cur.fetchone()
    return bool(row and row.get("existe"))


# Regex (case-insensitive) das situacoes "problematicas" -- mesmo criterio do
# Legado (toggle "Permitir Falencia / Rec. Judicial"). Quando incluir_inativas
# e False, essas empresas sao excluidas.
_BLACKLIST_REGEX = r"RECUPERACAO|FALIDA|JUDICIAL|MASSA FALIDA|EM LIQUIDACAO|BAIXADA|INAPTA"


def _norm_lista(v) -> List[str]:
    """Aceita None, str ou lista -> lista de strings nao-vazias (o endpoint manda
    lista para multiselect; campanhas antigas podem mandar uma string)."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    return [str(x) for x in v if x is not None and str(x) != ""]


# Cache do mapa nome do municipio -> codigos. O filtro de cidade precisa
# virar COD_MUNICIPIO antes do WHERE: filtrando pelo JOIN, o planejador
# estima as linhas dividindo pelos 5.572 municipios do Brasil (da 135 onde
# Porto Alegre tem 152 mil), escolhe o plano errado e a listagem por cidade
# leva 14s em vez de 0,2s. A tabela tem 5.572 linhas e muda uma vez por mes.
_MUNICIPIOS_CACHE: Dict[str, List[str]] = {}
_MUNICIPIOS_CACHE_TS: float = 0.0
_MUNICIPIOS_TTL = 3600.0


def _mapa_municipios() -> Dict[str, List[str]]:
    global _MUNICIPIOS_CACHE, _MUNICIPIOS_CACHE_TS
    import time as _time
    if _MUNICIPIOS_CACHE and (_time.time() - _MUNICIPIOS_CACHE_TS) < _MUNICIPIOS_TTL:
        return _MUNICIPIOS_CACHE
    mapa: Dict[str, List[str]] = {}
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT nome_municipio, cod_municipio FROM municipios "
                        "WHERE cod_municipio IS NOT NULL AND nome_municipio <> ''")
            for row in cur.fetchall():
                mapa.setdefault(sem_acento_upper(row["nome_municipio"]), []).append(row["cod_municipio"])
    except Exception as e:
        log.warning(f"_mapa_municipios falhou: {e}")
        return _MUNICIPIOS_CACHE
    _MUNICIPIOS_CACHE, _MUNICIPIOS_CACHE_TS = mapa, _time.time()
    return mapa


def codigos_municipio(nomes) -> List[str]:
    """Nomes de cidade -> COD_MUNICIPIO. Nome desconhecido some da lista."""
    mapa = _mapa_municipios()
    codigos: List[str] = []
    for nome in cidades_normalizadas(_norm_lista(nomes)):
        for cod in mapa.get(nome, []):
            if cod not in codigos:
                codigos.append(cod)
    return codigos


def _where_empresas(
    cidade=None, cnae=None, porte=None, busca=None,
    divida_min=None, divida_max=None, capital_min=None, capital_max=None,
    fundacao_de=None, fundacao_ate=None, incluir_inativas: bool = True,
    contato=None, potencial=None, categoria=None,
):
    """Monta o WHERE (e os params) compartilhado pela listagem e pela contagem,
    a partir dos filtros do funil (cidade, CNAE, porte, faixas de passivo/capital,
    data de fundacao, blacklist RJ). Assume os aliases e (dados_empresas) e m
    (municipios) na query."""
    import re as _re
    clauses: List[str] = []
    params: List[Any] = []
    # Tipo real das colunas (NUMERIC/DATE no prod pos-nivel1, TEXT no legado):
    # define se o filtro usa a coluna direto (usa indice) ou o cast defensivo.
    tipos = get_tipos_dados_empresas()
    div_expr = expr_numerica("DIVIDA_TOTAL", tipos)
    cap_expr = expr_numerica("CAPITAL_SOCIAL", tipos)
    fundacao_e_date = data_fundacao_is_date(tipos)
    if _norm_lista(cidade):
        # Cidade vira codigo (ver _mapa_municipios). Nome que nao existe =
        # zero resultado, nao base inteira.
        cods = codigos_municipio(cidade)
        clauses.append('e."COD_MUNICIPIO" = ANY(%s)'); params.append(cods or ["__nenhum__"])
    cnaes = _norm_lista(cnae)
    if cnaes:
        sql_cnae, p_cnae = clausula_cnae(cnaes)
        clauses.append(sql_cnae); params.extend(p_cnae)
    portes = _norm_lista(porte)
    if portes:
        # Frontend manda nomes ("ME", "EPP", "MICRO"...) mas a tabela guarda
        # so o codigo RF. Porte desconhecido = zero resultado (nao ignora).
        codigos = codigos_porte(portes)
        clauses.append('e."PORTE_EMPRESA" = ANY(%s)'); params.append(codigos or ["__nenhum__"])
    if busca:
        clauses.append('(e."RAZAO_SOCIAL" ILIKE %s OR e."NOME_FANTASIA" ILIKE %s)')
        params.extend([f"%{busca}%", f"%{busca}%"])
    if divida_min is not None:
        clauses.append(f'{div_expr} >= %s'); params.append(divida_min)
    if divida_max is not None:
        clauses.append(f'{div_expr} <= %s'); params.append(divida_max)
    if capital_min is not None:
        clauses.append(f'{cap_expr} >= %s'); params.append(capital_min)
    if capital_max is not None:
        clauses.append(f'{cap_expr} <= %s'); params.append(capital_max)
    # DATA_FUNDACAO e DATE no prod (compara como data) ou texto YYYYMMDD
    # no legado (comparacao lexicografica = cronologica).
    if fundacao_de:
        if fundacao_e_date:
            clauses.append('e."DATA_FUNDACAO" >= %s::date'); params.append(normalizar_data_param(fundacao_de))
        else:
            clauses.append('e."DATA_FUNDACAO" >= %s'); params.append(_re.sub(r"\D", "", str(fundacao_de)))
    if fundacao_ate:
        if fundacao_e_date:
            clauses.append('e."DATA_FUNDACAO" <= %s::date'); params.append(normalizar_data_param(fundacao_ate))
        else:
            clauses.append('e."DATA_FUNDACAO" <= %s'); params.append(_re.sub(r"\D", "", str(fundacao_ate)))
    if not incluir_inativas:
        clauses.append('COALESCE(e."RAZAO_SOCIAL", \'\') !~* %s'); params.append(_BLACKLIST_REGEX)
    if CNAE_DIVISOES_EXCLUIDAS:
        clauses.append('LEFT(COALESCE(e."CNAE_PRINCIPAL", \'\'), 2) <> ALL(%s)')
        params.append(list(CNAE_DIVISOES_EXCLUIDAS))
    # Filtro de contato: com_email / so_telefone (sem e-mail, com fone) / sem_contato.
    if contato:
        tem_email = 'TRIM(COALESCE(e."EMAIL", \'\')) <> \'\''
        tem_fone = 'TRIM(COALESCE(e."TELEFONE", \'\')) <> \'\''
        if contato == "com_email":
            clauses.append(tem_email)
        elif contato == "so_telefone":
            clauses.append(f"(NOT ({tem_email}) AND {tem_fone})")
        elif contato == "sem_contato":
            clauses.append(f"(NOT ({tem_email}) AND NOT ({tem_fone}))")
    # Filtros de potencial/categoria (tabela empresas_potencial) foram
    # REMOVIDOS em 2026-09 (tabela dropada: score nunca calibrado, 209 MB).
    # Os parametros potencial/categoria seguem aceitos e ignorados pra nao
    # quebrar campanhas/lotes antigos que os tenham salvos nos filtros.
    _ = (potencial, categoria)
    where = (" AND " + " AND ".join(clauses)) if clauses else ""
    return where, params


# CARTEIRA PROPRIA DA EMPRESA
#
# Empresa com escopo_base='carteira' (ex.: Gama) prospecta sobre a lista
# dela, nao sobre a base da Receita. As telas sao as mesmas -- Empresas,
# Clientes, Campanhas: o que muda e' de onde as linhas vem. As funcoes abaixo
# devolvem exatamente as mesmas colunas de listar_empresas_db pra tela nao
# precisar saber qual das duas fontes respondeu.

_CARTEIRA_SELECT = """
    c.cnpj_completo,
    COALESCE(c.razao_social, '') AS razao_social,
    COALESCE(c.nome_fantasia, '') AS nome_fantasia,
    COALESCE(c.municipio, '') AS municipio,
    COALESCE(c.cnae_principal, '') AS cnae_principal,
    COALESCE(c.cnae_descricao, '') AS cnae_descricao,
    COALESCE(c.capital_social, 0) AS capital_social,
    COALESCE(c.divida_total, 0) AS divida_total,
    COALESCE(c.porte_nome, '') AS porte_nome,
    NULL::date AS data_fundacao,
    COALESCE(c.email, '') AS email,
    COALESCE(c.contato_fone, '') AS contato_fone,
    COALESCE(c.categoria, 'sem categoria') AS categoria_cnae,
    0 AS potencial_score,
    'medio' AS potencial_tier
"""


def max_por_clique_org(organizacao_id: Optional[int], padrao: int) -> int:
    """Teto por clique DESTA empresa. Sem valor proprio, usa o padrao."""
    if organizacao_id is None:
        return padrao
    with get_db_cursor() as cur:
        cur.execute("SELECT max_por_clique FROM organizacoes WHERE id = %s", (organizacao_id,))
        row = cur.fetchone()
    valor = row["max_por_clique"] if row else None
    return int(valor) if valor else padrao


def dias_followup_org(organizacao_id: Optional[int]) -> int:
    """Dias ate' o follow-up DESTA empresa. Sem valor proprio, usa o padrao."""
    if organizacao_id is None:
        return DIAS_FOLLOWUP
    with get_db_cursor() as cur:
        cur.execute("SELECT dias_followup FROM organizacoes WHERE id = %s", (organizacao_id,))
        row = cur.fetchone()
    valor = row["dias_followup"] if row else None
    return int(valor) if valor else DIAS_FOLLOWUP


def tamanho_carteira(organizacao_id: int) -> int:
    """Quantos contatos a empresa tem na lista de trabalho. E' o que diz se o
    Disparar faz sentido pra ela."""
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM empresas_carteira WHERE organizacao_id = %s",
                    (organizacao_id,))
        row = cur.fetchone()
        return int(row["n"]) if row else 0


def org_escopo_base(organizacao_id: Optional[int]) -> str:
    """'receita' (base publica) ou 'carteira' (lista propria da empresa)."""
    if organizacao_id is None:
        return "receita"
    with get_db_cursor() as cur:
        cur.execute("SELECT COALESCE(escopo_base, 'receita') AS e FROM organizacoes WHERE id = %s", (organizacao_id,))
        row = cur.fetchone()
        return row["e"] if row else "receita"


def _where_carteira(organizacao_id: int, cidade=None, busca=None, categoria=None, cnae=None, porte=None):
    clauses = ["c.organizacao_id = %s"]
    params: List[Any] = [organizacao_id]
    cidades = _norm_lista(cidade)
    if cidades:
        clauses.append("c.municipio = ANY(%s)"); params.append(cidades)
    categorias = _norm_lista(categoria)
    if categorias:
        clauses.append("c.categoria = ANY(%s)"); params.append(categorias)
    cnaes = _norm_lista(cnae)
    if cnaes:
        clauses.append("c.cnae_principal = ANY(%s)"); params.append(cnaes)
    portes = _norm_lista(porte)
    if portes:
        clauses.append("c.porte_nome = ANY(%s)"); params.append(portes)
    if busca:
        termo = f"%{busca.strip().upper()}%"
        clauses.append("(UPPER(c.razao_social) LIKE %s OR UPPER(COALESCE(c.nome_fantasia,'')) LIKE %s OR c.cnpj_completo LIKE %s)")
        params += [termo, termo, termo.replace("%", "") + "%"]
    return " AND ".join(clauses), params


def listar_carteira_db(organizacao_id: int, cidade=None, busca=None, categoria=None,
                       cnae=None, porte=None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    where, params = _where_carteira(organizacao_id, cidade, busca, categoria, cnae, porte)
    with get_db_cursor() as cur:
        cur.execute(
            f"SELECT {_CARTEIRA_SELECT} FROM empresas_carteira c WHERE {where} "
            f"ORDER BY c.razao_social LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        return cur.fetchall()


def contar_carteira_db(organizacao_id: int, cidade=None, busca=None, categoria=None,
                       cnae=None, porte=None) -> int:
    where, params = _where_carteira(organizacao_id, cidade, busca, categoria, cnae, porte)
    with get_db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM empresas_carteira c WHERE {where}", params)
        row = cur.fetchone()
        return int(row["total"]) if row else 0


def get_carteira_by_cnpj(organizacao_id: int, cnpj: str) -> Dict[str, Any]:
    cnpj_limpo = re.sub(r"\D", "", cnpj or "")
    if not cnpj_limpo:
        return {}
    with get_db_cursor() as cur:
        cur.execute(
            f"SELECT {_CARTEIRA_SELECT}, c.cnpj_completo AS cnpj_basico, "
            f"COALESCE(c.observacao, '') AS observacao, COALESCE(c.origem, '') AS origem "
            f"FROM empresas_carteira c WHERE c.organizacao_id = %s AND c.cnpj_completo = %s",
            (organizacao_id, cnpj_limpo),
        )
        row = cur.fetchone()
    if not row:
        return {}
    resultado = dict(row)
    # A carteira nao tem quadro societario. Em firma individual (os MEIs) o
    # titular esta' no nome empresarial -- sem isto a tela mostrava a empresa
    # sem ninguem responsavel.
    pessoa = titular(resultado.get("razao_social"), resultado.get("porte_nome"))
    resultado["socios"] = ([{"nome_socio": pessoa, "cpf_cnpj_socio": None,
                             "qualif_socio": "Titular (firma individual)"}]
                           if pessoa else [])
    # Historico de abordagem: qual modelo recebeu e o que aconteceu. E' o que
    # permite, depois, medir qual abordagem traz retorno.
    try:
        resultado["abordagens"] = abordagens_do_contato(organizacao_id, cnpj_limpo)
        with get_db_cursor() as cur:
            cur.execute("SELECT situacao FROM contato_situacao WHERE organizacao_id = %s AND cnpj = %s",
                        (organizacao_id, cnpj_limpo))
            sit = cur.fetchone()
        resultado["situacao_contato"] = sit["situacao"] if sit else None
    except Exception as e:  # historico e' extra: nunca derruba a ficha
        log.warning(f"abordagens do contato falhou: {e}")
        resultado["abordagens"], resultado["situacao_contato"] = [], None
    return resultado


def categorias_da_carteira(organizacao_id: int) -> List[Dict[str, Any]]:
    """Categorias existentes na carteira da empresa, com a contagem -- e' o
    filtro que a tela oferece no lugar do CNAE da Receita."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT COALESCE(categoria, 'sem categoria') AS categoria, COUNT(*)::int AS total
               FROM empresas_carteira WHERE organizacao_id = %s
               GROUP BY 1 ORDER BY 2 DESC""",
            (organizacao_id,),
        )
        return cur.fetchall()


def salvar_na_carteira(organizacao_id: int, empresa: Dict[str, Any], criado_por: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Insere ou atualiza uma empresa da carteira. A chave e' (empresa, CNPJ),
    entao recarregar a mesma planilha atualiza em vez de duplicar."""
    cnpj = re.sub(r"\D", "", str(empresa.get("cnpj_completo") or empresa.get("cnpj") or ""))
    # 14 digitos e nem todos iguais: "00000000000000" passava como valido e
    # entrava na carteira como uma empresa de verdade.
    if len(cnpj) != 14 or len(set(cnpj)) == 1:
        return None
    campos = {
        "razao_social": empresa.get("razao_social"),
        "nome_fantasia": empresa.get("nome_fantasia"),
        "municipio": (empresa.get("municipio") or "").upper() or None,
        "uf": (empresa.get("uf") or "").upper()[:2] or None,
        "email": empresa.get("email"),
        "contato_fone": empresa.get("contato_fone") or empresa.get("telefone"),
        "cnae_principal": empresa.get("cnae_principal"),
        "cnae_descricao": empresa.get("cnae_descricao"),
        "porte_nome": empresa.get("porte_nome"),
        "capital_social": empresa.get("capital_social"),
        "divida_total": empresa.get("divida_total"),
        "categoria": empresa.get("categoria"),
        "situacao": empresa.get("situacao"),
        "origem": empresa.get("origem") or "importacao",
        "observacao": empresa.get("observacao"),
    }
    cols = ", ".join(campos)
    marks = ", ".join(["%s"] * len(campos))
    # COALESCE no update: coluna que veio vazia na recarga nao apaga o que ja'
    # estava preenchido (e-mail conseguido a mao, por exemplo).
    updates = ", ".join(f"{k} = COALESCE(EXCLUDED.{k}, empresas_carteira.{k})" for k in campos)
    with get_db_cursor() as cur:
        cur.execute(
            f"""INSERT INTO empresas_carteira (organizacao_id, cnpj_completo, criado_por, {cols})
                VALUES (%s, %s, %s, {marks})
                ON CONFLICT (organizacao_id, cnpj_completo) DO UPDATE SET {updates}
                RETURNING id, cnpj_completo, razao_social, categoria""",
            [organizacao_id, cnpj, criado_por] + list(campos.values()),
        )
        return cur.fetchone()


def remover_da_carteira(organizacao_id: int, cnpj: str) -> bool:
    with get_db_cursor() as cur:
        cur.execute(
            "DELETE FROM empresas_carteira WHERE organizacao_id = %s AND cnpj_completo = %s",
            (organizacao_id, re.sub(r"\D", "", cnpj or "")),
        )
        return cur.rowcount > 0


def listar_empresas_db(
    cidade=None, cnae=None, porte=None, busca: Optional[str] = None,
    divida_min=None, divida_max=None, capital_min=None, capital_max=None,
    fundacao_de: Optional[str] = None, fundacao_ate: Optional[str] = None,
    incluir_inativas: bool = True, contato=None, potencial=None, categoria=None,
    ordenar_por: str = "razao_social",
    limit: int = 100, offset: int = 0,
    organizacao_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Lista empresas com o funil de filtros (server-side).

    A fonte depende da empresa: escopo_base='carteira' le' a lista propria
    dela, o padrao le' dados_empresas (Receita Federal). As colunas de saida
    sao as mesmas nos dois casos.
    Retorna [] se a tabela ainda nao existir (ETL nunca rodou) ou em caso de erro."""
    if organizacao_id is not None and org_escopo_base(organizacao_id) == "carteira":
        return listar_carteira_db(organizacao_id, cidade=cidade, busca=busca,
                                  categoria=categoria, cnae=cnae, porte=porte,
                                  limit=limit, offset=offset)
    try:
        with get_db_cursor() as cur:
            if not _tabela_existe(cur, "dados_empresas"):
                return []
            where, params = _where_empresas(
                cidade, cnae, porte, busca, divida_min, divida_max,
                capital_min, capital_max, fundacao_de, fundacao_ate, incluir_inativas,
                contato, potencial, categoria,
            )
            # ordenar_por=potencial removido junto com empresas_potencial:
            # tudo ordena por razao social (o parametro segue aceito e ignorado).
            order_sql = 'e."RAZAO_SOCIAL"'
            tipos = get_tipos_dados_empresas()
            cap_expr = expr_numerica("CAPITAL_SOCIAL", tipos)
            div_expr = expr_numerica("DIVIDA_TOTAL", tipos)
            sql = f"""
                SELECT
                    e."CNPJ_COMPLETO" AS cnpj_completo,
                    e."RAZAO_SOCIAL" AS razao_social,
                    e."NOME_FANTASIA" AS nome_fantasia,
                    COALESCE(m.nome_municipio, '') AS municipio,
                    e."CNAE_PRINCIPAL" AS cnae_principal,
                    COALESCE(c.descricao_cnae, '') AS cnae_descricao,
                    {cap_expr} AS capital_social,
                    {div_expr} AS divida_total,
                    ({PORTE_NOME_SQL}) AS porte_nome,
                    e."DATA_FUNDACAO" AS data_fundacao,
                    e."EMAIL" AS email,
                    ({CONTATO_FONE_SQL}) AS contato_fone,
                    NULL AS potencial_score,
                    NULL AS potencial_tier
                FROM dados_empresas e
                LEFT JOIN municipios m ON m.cod_municipio = e."COD_MUNICIPIO"
                LEFT JOIN cnaes c ON c.codigo_cnae = e."CNAE_PRINCIPAL"
                WHERE 1=1 {where}
                ORDER BY {order_sql} LIMIT %s OFFSET %s
            """
            cur.execute(sql, params + [limit, offset])
            return cur.fetchall()
    except Exception as e:
        log.warning(f"listar_empresas_db falhou, retornando lista vazia: {e}")
        return []


@cached("contar_empresas_db")
def contar_empresas_db(
    cidade=None, cnae=None, porte=None, busca: Optional[str] = None,
    divida_min=None, divida_max=None, capital_min=None, capital_max=None,
    fundacao_de: Optional[str] = None, fundacao_ate: Optional[str] = None,
    incluir_inativas: bool = True, potencial=None, categoria=None,
    organizacao_id: Optional[int] = None,
) -> int:
    """Conta quantas empresas batem no filtro atual (para o contador do funil,
    sem trazer as linhas). Retorna 0 se a tabela nao existir ou em caso de erro."""
    if organizacao_id is not None and org_escopo_base(organizacao_id) == "carteira":
        return contar_carteira_db(organizacao_id, cidade=cidade, busca=busca,
                                  categoria=categoria, cnae=cnae, porte=porte)
    try:
        with get_db_cursor() as cur:
            if not _tabela_existe(cur, "dados_empresas"):
                return 0
            where, params = _where_empresas(
                cidade, cnae, porte, busca, divida_min, divida_max,
                capital_min, capital_max, fundacao_de, fundacao_ate, incluir_inativas,
                potencial=potencial, categoria=categoria,
            )
            sql = f"""
                SELECT COUNT(*) AS total
                FROM dados_empresas e
                LEFT JOIN municipios m ON m.cod_municipio = e."COD_MUNICIPIO"
                WHERE 1=1 {where}
            """
            cur.execute(sql, params)
            row = cur.fetchone()
            return int(row["total"]) if row and row.get("total") is not None else 0
    except Exception as e:
        log.warning(f"contar_empresas_db falhou, retornando 0: {e}")
        return 0


def get_empresa_by_cnpj_db(cnpj: str, organizacao_id: Optional[int] = None) -> Dict[str, Any]:
    """Busca uma empresa por CNPJ, com municipio e socios resolvidos.
    Empresa de escopo 'carteira' busca na lista propria dela.
    Retorna {} se nao encontrada, tabela ausente, ou erro."""
    cnpj_limpo = re.sub(r"\D", "", cnpj or "")
    if not cnpj_limpo:
        return {}
    if organizacao_id is not None and org_escopo_base(organizacao_id) == "carteira":
        return get_carteira_by_cnpj(organizacao_id, cnpj_limpo)
    try:
        with get_db_cursor() as cur:
            if not _tabela_existe(cur, "dados_empresas"):
                return {}
            tipos = get_tipos_dados_empresas()
            cap_expr = expr_numerica("CAPITAL_SOCIAL", tipos)
            div_expr = expr_numerica("DIVIDA_TOTAL", tipos)
            cur.execute(
                f"""
                SELECT
                    e."CNPJ_COMPLETO" AS cnpj_completo,
                    e."CNPJ_BASICO" AS cnpj_basico,
                    e."RAZAO_SOCIAL" AS razao_social,
                    e."NOME_FANTASIA" AS nome_fantasia,
                    COALESCE(m.nome_municipio, '') AS municipio,
                    e."CNAE_PRINCIPAL" AS cnae_principal,
                    COALESCE(c.descricao_cnae, '') AS cnae_descricao,
                    {cap_expr} AS capital_social,
                    {div_expr} AS divida_total,
                    ({PORTE_NOME_SQL}) AS porte_nome,
                    e."DATA_FUNDACAO" AS data_fundacao,
                    ({CONTATO_FONE_SQL}) AS contato_fone,
                    NULL AS potencial_score,
                    NULL AS potencial_tier
                FROM dados_empresas e
                LEFT JOIN municipios m ON m.cod_municipio = e."COD_MUNICIPIO"
                LEFT JOIN cnaes c ON c.codigo_cnae = e."CNAE_PRINCIPAL"
                WHERE e."CNPJ_COMPLETO" = %s
                LIMIT 1
                """,
                (cnpj_limpo,),
            )
            row = cur.fetchone()
            if not row:
                return {}
            socios: List[Dict[str, Any]] = []
            if _tabela_existe(cur, "dados_socios"):
                cur.execute(
                    """
                    SELECT
                        "NOME_SOCIO" AS nome_socio,
                        "CPF_CNPJ_SOCIO" AS cpf_cnpj_socio,
                        "QUALIF_SOCIO" AS qualif_socio
                    FROM dados_socios
                    WHERE "CNPJ_BASICO" = %s
                    """,
                    (row.get("cnpj_basico"),),
                )
                socios = cur.fetchall()
            resultado = dict(row)
            resultado["socios"] = socios
            return resultado
    except Exception as e:
        log.warning(f"get_empresa_by_cnpj_db falhou, retornando vazio: {e}")
        return {}


def get_metricas_db() -> Dict[str, Any]:
    """Estatisticas agregadas de dados_empresas. Retorna zeros se a tabela
    ainda nao existir ou em caso de erro."""
    vazio = {
        "total_empresas": 0, "por_cidade": {}, "por_porte": {},
        "capital_total": 0.0, "divida_total": 0.0, "top_cnaes": {},
    }
    try:
        with get_db_cursor() as cur:
            if not _tabela_existe(cur, "dados_empresas"):
                return vazio
            cur.execute('SELECT COUNT(*) AS total FROM dados_empresas')
            total = cur.fetchone()["total"]

            cur.execute("""
                SELECT COALESCE(m.nome_municipio, 'Sem municipio') AS cidade, COUNT(*) AS qtd
                FROM dados_empresas e
                LEFT JOIN municipios m ON m.cod_municipio = e."COD_MUNICIPIO"
                GROUP BY cidade ORDER BY qtd DESC LIMIT 10
            """)
            por_cidade = {r["cidade"]: r["qtd"] for r in cur.fetchall()}

            cur.execute(f'SELECT ({PORTE_NOME_SQL}) AS porte, COUNT(*) AS qtd FROM dados_empresas e GROUP BY porte')
            por_porte = {(r["porte"] or "Nao informado"): r["qtd"] for r in cur.fetchall()}

            cur.execute('SELECT COALESCE(SUM("CAPITAL_SOCIAL"::numeric), 0) AS total FROM dados_empresas')
            capital_total = float(cur.fetchone()["total"])

            cur.execute('SELECT COALESCE(SUM("DIVIDA_TOTAL"::numeric), 0) AS total FROM dados_empresas')
            divida_total = float(cur.fetchone()["total"])

            cur.execute("""
                SELECT "CNAE_PRINCIPAL" AS cnae, COUNT(*) AS qtd
                FROM dados_empresas GROUP BY cnae ORDER BY qtd DESC LIMIT 10
            """)
            top_cnaes = {r["cnae"]: r["qtd"] for r in cur.fetchall()}

            return {
                "total_empresas": total, "por_cidade": por_cidade, "por_porte": por_porte,
                "capital_total": capital_total, "divida_total": divida_total, "top_cnaes": top_cnaes,
            }
    except Exception as e:
        log.warning(f"get_metricas_db falhou, retornando zeros: {e}")
        return vazio

def get_pipeline_metadata() -> Dict[str, Any]:
    """Le a tabela pipeline_metadata (mes RF, trimestre PGFN, ultima
    sincronizacao, contagens) gravada por scripts/sync_data_to_db.py apos
    cada rodada do ETL. Usado pela aba "Sobre" em Configuracoes. Retorna
    dict vazio (sem quebrar) se a tabela nao existir ou o ETL nunca rodou."""
    try:
        with get_db_cursor() as cur:
            if not _tabela_existe(cur, "pipeline_metadata"):
                return {}
            cur.execute("SELECT chave, valor, atualizado_em FROM pipeline_metadata")
            linhas = cur.fetchall()
            return {
                r["chave"]: {"valor": r["valor"], "atualizado_em": r["atualizado_em"]}
                for r in linhas
            }
    except Exception as e:
        log.warning(f"get_pipeline_metadata falhou, retornando vazio: {e}")
        return {}


def seed_default_templates() -> int:
    """Popula a tabela email_templates com os modelos padrao (backend/mailer/templates.py::TEMPLATES_PADRAO),
    apenas se a tabela ainda estiver vazia. Idempotente -- seguro de chamar em todo startup."""
    try:
        from ..mailer.templates import TEMPLATES_PADRAO
    except ImportError:
        from mailer.templates import TEMPLATES_PADRAO
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM email_templates")
        row = cur.fetchone()
        if row and row.get("cnt", 0) > 0:
            return 0
        criados = 0
        for dados in TEMPLATES_PADRAO.values():
            cur.execute(
                f"INSERT INTO email_templates (nome, assunto, corpo_html, corpo_texto, criado_por, categoria_cnae) VALUES (%s, %s, %s, %s, %s, %s)",
                (dados["nome"], dados["assunto"], dados["corpo_html"], dados["corpo_texto"], "sistema", "todos"),
            )
            criados += 1
        return criados


def buscar_empresas_rapido(termo: str, limite: int = 10) -> List[Dict[str, Any]]:
    """Busca por nome ou CNPJ, so' o que precisa pra montar um autocomplete
    (cnpj + nome + cidade). Limite baixo e sem contagem total de proposito --
    e' pra escolher uma empresa numa lista curta, nao pra navegar a base."""
    termo = (termo or "").strip()
    if len(termo) < 3:
        return []
    so_digitos = re.sub(r"\D", "", termo)
    try:
        with get_db_cursor() as cur:
            if so_digitos and len(so_digitos) >= 6:
                cur.execute(
                    """SELECT e."CNPJ_COMPLETO" AS cnpj_completo, e."RAZAO_SOCIAL" AS razao_social,
                              COALESCE(m.nome_municipio, '') AS municipio
                       FROM dados_empresas e
                       LEFT JOIN municipios m ON m.cod_municipio = e."COD_MUNICIPIO"
                       WHERE e."CNPJ_COMPLETO" LIKE %s LIMIT %s""",
                    (so_digitos + "%", limite),
                )
            else:
                cur.execute(
                    """SELECT e."CNPJ_COMPLETO" AS cnpj_completo, e."RAZAO_SOCIAL" AS razao_social,
                              COALESCE(m.nome_municipio, '') AS municipio
                       FROM dados_empresas e
                       LEFT JOIN municipios m ON m.cod_municipio = e."COD_MUNICIPIO"
                       WHERE e."RAZAO_SOCIAL" LIKE %s LIMIT %s""",
                    (termo.upper() + "%", limite),
                )
            return cur.fetchall()
    except Exception as e:
        log.warning(f"buscar_empresas_rapido falhou: {e}")
        return []


def buscar_socios_principais(cnpjs_basicos: List[str]) -> Dict[str, str]:
    """CNPJ_BASICO -> nome do socio 'responsavel' de cada empresa (pra
    personalizar campanha com o nome de uma pessoa, nao so' da empresa).
    Prioridade por qualificacao (codigos da Receita Federal): Socio-
    Administrador > Titular > Administrador > Presidente > Diretor > Socio
    comum > qualquer outra. Uma empresa pode ter varios socios com a mesma
    qualificacao -- pega um so' (o primeiro por ordem alfabetica, so' pra
    ser deterministico entre chamadas)."""
    if not cnpjs_basicos:
        return {}
    with get_db_cursor() as cur:
        cur.execute(
            """
            WITH ranked AS (
                SELECT "CNPJ_BASICO", "NOME_SOCIO",
                       ROW_NUMBER() OVER (
                           PARTITION BY "CNPJ_BASICO"
                           ORDER BY CASE "QUALIF_SOCIO"
                               WHEN '49' THEN 1
                               WHEN '65' THEN 2
                               WHEN '05' THEN 3
                               WHEN '16' THEN 4
                               WHEN '10' THEN 5
                               WHEN '22' THEN 6
                               ELSE 9
                           END, "NOME_SOCIO"
                       ) AS rn
                FROM dados_socios
                WHERE "CNPJ_BASICO" = ANY(%s) AND COALESCE("NOME_SOCIO", '') <> ''
                  -- So pessoa fisica: socio PJ traria o nome de outra empresa.
                  AND "IDENTIFICADOR_SOCIO" = '2'
            )
            SELECT "CNPJ_BASICO", "NOME_SOCIO" FROM ranked WHERE rn = 1
            """,
            (cnpjs_basicos,),
        )
        return {r["CNPJ_BASICO"]: r["NOME_SOCIO"] for r in cur.fetchall()}


# DESCADASTRO DE E-MAIL (LGPD/opt-out)
# Global (nao por empresa): pedido de "nao me mande mais e-mail" vale pra
# qualquer organizacao que tentar mandar pra esse endereco.

def email_esta_descadastrado(email: str) -> bool:
    if not email:
        return False
    with get_db_cursor() as cur:
        cur.execute("SELECT 1 FROM emails_descadastrados WHERE email = %s", (email.strip().lower(),))
        return cur.fetchone() is not None


def descadastrar_email(email: str, cnpj: Optional[str] = None, motivo: Optional[str] = None) -> bool:
    with get_db_cursor() as cur:
        cur.execute(
            """INSERT INTO emails_descadastrados (email, cnpj, motivo)
               VALUES (%s, %s, %s) ON CONFLICT (email) DO NOTHING""",
            (email.strip().lower(), cnpj, motivo),
        )
        return True


# CRM: ATIVIDADES/TAREFAS

def listar_usuarios_da_org(organizacao_id: int) -> List[Dict[str, Any]]:
    """Usuarios que podem ser responsaveis por uma atividade (membros da
    mesma organizacao ativa -- ex.: os socios da SVYP)."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT u.id, u.username, u.email
               FROM app_users u
               JOIN usuario_organizacoes uo ON uo.user_id = u.id
               WHERE uo.organizacao_id = %s AND u.is_active = TRUE
               ORDER BY u.username""",
            (organizacao_id,),
        )
        return cur.fetchall()


def criar_atividade_crm(
    cnpj: str, organizacao_id: int, titulo: str, criado_por: Optional[str] = None,
    tipo: str = "tarefa", descricao: Optional[str] = None,
    responsavel_user_id: Optional[int] = None, prazo: Optional[str] = None,
) -> Dict[str, Any]:
    with get_db_cursor() as cur:
        cur.execute(
            """INSERT INTO crm_atividades
               (organizacao_id, cnpj, titulo, tipo, descricao, responsavel_user_id, prazo, criado_por)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
            (organizacao_id, cnpj, titulo, tipo, descricao, responsavel_user_id, prazo, criado_por),
        )
        return cur.fetchone()


# Semaforo das atividades -- mesma ideia do monitor de e-mails (verde/amarelo/
# vermelho), mas medindo o prazo da tarefa em vez do tempo sem resposta:
#   cinza    = concluida
#   vermelho = venceu (ou, sem prazo, esta' aberta ha' mais de 14 dias)
#   amarelo  = vence hoje ou amanha (ou aberta ha' mais de 7 dias sem prazo)
#   verde    = no prazo
ATIVIDADE_SEMAFORO_SQL = """
    CASE
        WHEN a.status = 'concluida' THEN 'cinza'
        WHEN a.prazo IS NOT NULL AND a.prazo < CURRENT_DATE THEN 'vermelho'
        WHEN a.prazo IS NOT NULL AND a.prazo <= CURRENT_DATE + 1 THEN 'amarelo'
        WHEN a.prazo IS NOT NULL THEN 'verde'
        WHEN a.criado_em < NOW() - INTERVAL '14 days' THEN 'vermelho'
        WHEN a.criado_em < NOW() - INTERVAL '7 days' THEN 'amarelo'
        ELSE 'verde'
    END AS semaforo"""

# Tempo decorrido: dias em aberto e dias ate'/desde o prazo (negativo = atrasada)
ATIVIDADE_TEMPO_SQL = """
    FLOOR(EXTRACT(EPOCH FROM (COALESCE(a.concluido_em, NOW()) - a.criado_em)) / 86400.0)::int AS dias_aberta,
    CASE WHEN a.prazo IS NULL THEN NULL ELSE (a.prazo - CURRENT_DATE) END AS dias_para_prazo"""


def listar_todas_atividades(organizacao_id: int) -> List[Dict[str, Any]]:
    """Todas as atividades da organizacao, com nome da empresa resolvido --
    base do board tipo Trello (visao agregada, nao so' por empresa)."""
    with get_db_cursor() as cur:
        cur.execute(
            f"""SELECT a.*, u.username AS responsavel_username,
                      COALESCE(e."RAZAO_SOCIAL", e."NOME_FANTASIA", a.cnpj) AS razao_social,
                      {ATIVIDADE_SEMAFORO_SQL}, {ATIVIDADE_TEMPO_SQL},
                      (SELECT COUNT(*) FROM crm_atividade_historico h WHERE h.atividade_id = a.id)::int AS n_historico,
                      (SELECT COUNT(*) FROM crm_atividade_anexos x WHERE x.atividade_id = a.id)::int AS n_anexos
               FROM crm_atividades a
               LEFT JOIN app_users u ON u.id = a.responsavel_user_id
               LEFT JOIN dados_empresas e ON e."CNPJ_COMPLETO" = a.cnpj
               WHERE a.organizacao_id = %s
               ORDER BY a.prazo ASC NULLS LAST, a.criado_em ASC""",
            (organizacao_id,),
        )
        return cur.fetchall()


# Colunas do anexo SEM o conteudo -- listar anexo nunca deve arrastar os
# bytes do arquivo junto (uma tarefa com 5 PDFs viraria uma resposta de MBs).
_ANEXO_COLS = "id, atividade_id, nome, mime, tamanho, enviado_por, criado_em"


# GASTOS (despesas por empresa)

_GASTO_COLS = ("id, organizacao_id, descricao, valor, data, categoria, forma_pagamento, "
               "observacao, criado_por, criado_em, removido_em, removido_por")


def criar_gasto(
    organizacao_id: int, descricao: str, valor: float, data: Optional[str] = None,
    categoria: str = "outros", forma_pagamento: Optional[str] = None,
    observacao: Optional[str] = None, criado_por: Optional[str] = None,
) -> Dict[str, Any]:
    with get_db_cursor() as cur:
        cur.execute(
            f"""INSERT INTO gastos (organizacao_id, descricao, valor, data, categoria,
                                    forma_pagamento, observacao, criado_por)
                VALUES (%s,%s,%s,COALESCE(%s::date, CURRENT_DATE),%s,%s,%s,%s)
                RETURNING {_GASTO_COLS}""",
            (organizacao_id, descricao, valor, data or None, categoria,
             forma_pagamento, observacao, criado_por),
        )
        return cur.fetchone()


def listar_gastos(
    organizacao_id: int, de: Optional[str] = None, ate: Optional[str] = None,
    categoria: Optional[str] = None, incluir_removidos: bool = False,
) -> List[Dict[str, Any]]:
    where = ["organizacao_id = %s"]
    params: List[Any] = [organizacao_id]
    if not incluir_removidos:
        where.append("removido_em IS NULL")
    if de:
        where.append("data >= %s::date"); params.append(de)
    if ate:
        where.append("data <= %s::date"); params.append(ate)
    if categoria:
        where.append("categoria = %s"); params.append(categoria)
    with get_db_cursor() as cur:
        cur.execute(
            f"SELECT {_GASTO_COLS} FROM gastos WHERE {' AND '.join(where)} "
            "ORDER BY data DESC, id DESC",
            params,
        )
        return cur.fetchall()


def resumo_gastos(organizacao_id: int, de: Optional[str] = None, ate: Optional[str] = None) -> Dict[str, Any]:
    """Total do periodo e quebra por categoria -- o que a tela mostra em cima."""
    where = ["organizacao_id = %s", "removido_em IS NULL"]
    params: List[Any] = [organizacao_id]
    if de:
        where.append("data >= %s::date"); params.append(de)
    if ate:
        where.append("data <= %s::date"); params.append(ate)
    cond = " AND ".join(where)
    with get_db_cursor() as cur:
        cur.execute(f"SELECT COALESCE(SUM(valor),0) AS total, COUNT(*)::int AS n FROM gastos WHERE {cond}", params)
        topo = cur.fetchone()
        cur.execute(
            f"SELECT categoria, COALESCE(SUM(valor),0) AS total, COUNT(*)::int AS n "
            f"FROM gastos WHERE {cond} GROUP BY categoria ORDER BY total DESC",
            params,
        )
        return {
            "total": float(topo["total"] or 0),
            "quantidade": topo["n"],
            "por_categoria": [
                {"categoria": r["categoria"], "total": float(r["total"]), "quantidade": r["n"]}
                for r in cur.fetchall()
            ],
        }


def remover_gasto(gasto_id: int, organizacao_id: int, removido_por: Optional[str] = None) -> bool:
    """Exclusao logica: o registro continua no banco, so' sai da lista e do
    total. Gasto lancado errado se corrige restaurando ou lancando de novo --
    nao sumindo com o rastro."""
    with get_db_cursor() as cur:
        cur.execute(
            "UPDATE gastos SET removido_em = NOW(), removido_por = %s "
            "WHERE id = %s AND organizacao_id = %s AND removido_em IS NULL",
            (removido_por, gasto_id, organizacao_id),
        )
        return cur.rowcount > 0


def restaurar_gasto(gasto_id: int, organizacao_id: int) -> bool:
    with get_db_cursor() as cur:
        cur.execute(
            "UPDATE gastos SET removido_em = NULL, removido_por = NULL "
            "WHERE id = %s AND organizacao_id = %s",
            (gasto_id, organizacao_id),
        )
        return cur.rowcount > 0


def atualizar_gasto(gasto_id: int, organizacao_id: int, campos: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    permitidos = ("descricao", "valor", "data", "categoria", "forma_pagamento", "observacao")
    sets, params = [], []
    for campo in permitidos:
        if campo in campos:
            sets.append(f"{campo} = %s")
            params.append(campos[campo])
    if not sets:
        return None
    params += [gasto_id, organizacao_id]
    with get_db_cursor() as cur:
        cur.execute(
            f"UPDATE gastos SET {', '.join(sets)} WHERE id = %s AND organizacao_id = %s "
            f"RETURNING {_GASTO_COLS}",
            params,
        )
        return cur.fetchone()


def salvar_anexo_atividade(
    atividade_id: int, organizacao_id: int, nome: str, mime: Optional[str],
    conteudo: bytes, enviado_por: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Anexa um arquivo a uma atividade. Devolve None se a atividade nao for
    da organizacao -- a checagem e' aqui e nao no endpoint pra nao existir
    caminho que grave anexo em tarefa de outra empresa."""
    with get_db_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM crm_atividades WHERE id = %s AND organizacao_id = %s",
            (atividade_id, organizacao_id),
        )
        if not cur.fetchone():
            return None
        cur.execute(
            f"""INSERT INTO crm_atividade_anexos (atividade_id, nome, mime, tamanho, conteudo, enviado_por)
                VALUES (%s,%s,%s,%s,%s,%s) RETURNING {_ANEXO_COLS}""",
            (atividade_id, nome, mime, len(conteudo), conteudo, enviado_por),
        )
        return cur.fetchone()


def listar_anexos_atividade(atividade_id: int, organizacao_id: int) -> List[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute(
            f"""SELECT {', '.join('a.' + c for c in _ANEXO_COLS.split(', '))}
                FROM crm_atividade_anexos a
                JOIN crm_atividades t ON t.id = a.atividade_id
                WHERE a.atividade_id = %s AND t.organizacao_id = %s
                ORDER BY a.criado_em ASC""",
            (atividade_id, organizacao_id),
        )
        return cur.fetchall()


def get_anexo_atividade(anexo_id: int, organizacao_id: int) -> Optional[Dict[str, Any]]:
    """Bytes do anexo, ja' filtrado pela organizacao -- e' o que serve o
    download/visualizacao."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT a.nome, a.mime, a.conteudo
               FROM crm_atividade_anexos a
               JOIN crm_atividades t ON t.id = a.atividade_id
               WHERE a.id = %s AND t.organizacao_id = %s""",
            (anexo_id, organizacao_id),
        )
        return cur.fetchone()


def deletar_anexo_atividade(anexo_id: int, organizacao_id: int) -> Optional[Dict[str, Any]]:
    """Remove o anexo e devolve {atividade_id, nome} pra registrar no historico."""
    with get_db_cursor() as cur:
        cur.execute(
            """DELETE FROM crm_atividade_anexos a
               USING crm_atividades t
               WHERE a.id = %s AND t.id = a.atividade_id AND t.organizacao_id = %s
               RETURNING a.atividade_id, a.nome""",
            (anexo_id, organizacao_id),
        )
        return cur.fetchone()


def contar_anexos_por_atividade(organizacao_id: int) -> Dict[int, int]:
    """atividade_id -> quantidade de anexos, pra badge no card sem uma
    consulta por card."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT a.atividade_id, COUNT(*)::int AS n
               FROM crm_atividade_anexos a
               JOIN crm_atividades t ON t.id = a.atividade_id
               WHERE t.organizacao_id = %s
               GROUP BY a.atividade_id""",
            (organizacao_id,),
        )
        return {r["atividade_id"]: r["n"] for r in cur.fetchall()}


def atribuir_atividade(atividade_id: int, organizacao_id: int, responsavel_user_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """Troca o responsavel. Devolve {de, para} com os usernames pra registrar
    no historico -- quem passou a tarefa pra quem fica no acompanhamento.
    None quando a atividade nao e' da organizacao."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT u.username AS anterior FROM crm_atividades a
               LEFT JOIN app_users u ON u.id = a.responsavel_user_id
               WHERE a.id = %s AND a.organizacao_id = %s""",
            (atividade_id, organizacao_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(
            "UPDATE crm_atividades SET responsavel_user_id = %s WHERE id = %s AND organizacao_id = %s",
            (responsavel_user_id, atividade_id, organizacao_id),
        )
        novo = None
        if responsavel_user_id:
            cur.execute("SELECT username, email FROM app_users WHERE id = %s", (responsavel_user_id,))
            novo = cur.fetchone()
        return {
            "de": row["anterior"],
            "para": novo["username"] if novo else None,
            "email": novo["email"] if novo else None,
        }


def registrar_historico_atividade(
    atividade_id: int, tipo: str, autor: str,
    texto: Optional[str] = None, de: Optional[str] = None, para: Optional[str] = None,
) -> Dict[str, Any]:
    """Uma linha do acompanhamento. tipo: 'comentario' | 'status' | 'prazo'."""
    with get_db_cursor() as cur:
        cur.execute(
            """INSERT INTO crm_atividade_historico (atividade_id, tipo, texto, de, para, autor)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
            (atividade_id, tipo, texto, de, para, autor),
        )
        return cur.fetchone()


def listar_historico_atividade(atividade_id: int, organizacao_id: int) -> List[Dict[str, Any]]:
    """Historico em ordem cronologica. Passa pela organizacao de proposito --
    ninguem le' o acompanhamento de uma tarefa de outra empresa."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT h.* FROM crm_atividade_historico h
               JOIN crm_atividades a ON a.id = h.atividade_id
               WHERE h.atividade_id = %s AND a.organizacao_id = %s
               ORDER BY h.criado_em ASC""",
            (atividade_id, organizacao_id),
        )
        return cur.fetchall()


def atualizar_prazo_atividade(atividade_id: int, organizacao_id: int, prazo: Optional[str]) -> Optional[str]:
    """Troca o prazo e devolve o prazo ANTERIOR (pra registrar no historico).
    Devolve None quando a atividade nao e' da organizacao."""
    with get_db_cursor() as cur:
        cur.execute(
            "SELECT prazo FROM crm_atividades WHERE id = %s AND organizacao_id = %s",
            (atividade_id, organizacao_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        anterior = row["prazo"].isoformat() if row["prazo"] else ""
        cur.execute(
            "UPDATE crm_atividades SET prazo = %s WHERE id = %s AND organizacao_id = %s",
            (prazo or None, atividade_id, organizacao_id),
        )
        return anterior


def get_status_atividade(atividade_id: int, organizacao_id: int) -> Optional[str]:
    with get_db_cursor() as cur:
        cur.execute(
            "SELECT status FROM crm_atividades WHERE id = %s AND organizacao_id = %s",
            (atividade_id, organizacao_id),
        )
        row = cur.fetchone()
        return row["status"] if row else None


def mover_atividade_crm(atividade_id: int, organizacao_id: int, status: str) -> bool:
    if status not in ("pendente", "em_andamento", "concluida"):
        return False
    with get_db_cursor() as cur:
        cur.execute(
            """UPDATE crm_atividades SET status = %s,
                   concluido_em = CASE WHEN %s = 'concluida' THEN NOW() ELSE NULL END
               WHERE id = %s AND organizacao_id = %s""",
            (status, status, atividade_id, organizacao_id),
        )
        return cur.rowcount > 0


def listar_atividades_crm(cnpj: str, organizacao_id: int) -> List[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute(
            f"""SELECT a.*, u.username AS responsavel_username,
                      {ATIVIDADE_SEMAFORO_SQL}, {ATIVIDADE_TEMPO_SQL},
                      (SELECT COUNT(*) FROM crm_atividade_historico h WHERE h.atividade_id = a.id)::int AS n_historico,
                      (SELECT COUNT(*) FROM crm_atividade_anexos x WHERE x.atividade_id = a.id)::int AS n_anexos
               FROM crm_atividades a
               LEFT JOIN app_users u ON u.id = a.responsavel_user_id
               WHERE a.cnpj = %s AND a.organizacao_id = %s
               ORDER BY (a.status = 'concluida'), a.prazo NULLS LAST, a.criado_em DESC""",
            (cnpj, organizacao_id),
        )
        return cur.fetchall()


def contar_atividades_pendentes(organizacao_id: int) -> Dict[str, int]:
    """CNPJ -> quantidade de atividades pendentes, pra badge nos cards do
    Kanban sem precisar de uma consulta por card."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT cnpj, COUNT(*) AS n FROM crm_atividades
               WHERE organizacao_id = %s AND status = 'pendente'
               GROUP BY cnpj""",
            (organizacao_id,),
        )
        return {r["cnpj"]: r["n"] for r in cur.fetchall()}


def concluir_atividade_crm(atividade_id: int, organizacao_id: int) -> bool:
    with get_db_cursor() as cur:
        cur.execute(
            """UPDATE crm_atividades SET status = 'concluida', concluido_em = NOW()
               WHERE id = %s AND organizacao_id = %s""",
            (atividade_id, organizacao_id),
        )
        return cur.rowcount > 0


def deletar_atividade_crm(atividade_id: int, organizacao_id: int) -> bool:
    with get_db_cursor() as cur:
        cur.execute(
            "DELETE FROM crm_atividades WHERE id = %s AND organizacao_id = %s",
            (atividade_id, organizacao_id),
        )
        return cur.rowcount > 0


# CAMPANHAS EM LOTE (envio diario ate um limite)

# LISTA DE ENVIO DA CAMPANHA
#
# A campanha pode ter destinatarios montados a mao em vez de sair de um
# filtro sobre a base. E' o caminho pra quem quer escolher pra quem vai
# (planilha do cliente, selecao na tela, um e-mail digitado na hora).

def adicionar_destinatarios(campanha_id: int, itens: List[Dict[str, Any]]) -> Dict[str, int]:
    """Adiciona e-mails na lista da campanha. Repetido nao duplica (a chave e'
    campanha + e-mail), entao da' pra ir somando de varias origens."""
    adicionados, invalidos, repetidos = 0, 0, 0
    with get_db_cursor() as cur:
        for item in itens:
            email = (item.get("email") or "").strip().lower()
            if "@" not in email or "." not in email.split("@")[-1]:
                invalidos += 1
                continue
            cnpj = re.sub(r"\D", "", str(item.get("cnpj") or "")) or None
            cur.execute(
                """INSERT INTO campanha_destinatarios
                   (campanha_id, email, cnpj, razao_social, municipio, nome_socio, origem)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (campanha_id, email) DO NOTHING
                   RETURNING id""",
                (campanha_id, email, cnpj, item.get("razao_social"), item.get("municipio"),
                 item.get("nome_socio"), item.get("origem") or "manual"),
            )
            if cur.fetchone():
                adicionados += 1
            else:
                repetidos += 1
    return {"adicionados": adicionados, "invalidos": invalidos, "repetidos": repetidos}


def listar_destinatarios(campanha_id: int, limit: int = 1000, offset: int = 0) -> List[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT * FROM campanha_destinatarios WHERE campanha_id = %s
               ORDER BY razao_social NULLS LAST, email LIMIT %s OFFSET %s""",
            (campanha_id, limit, offset),
        )
        return cur.fetchall()


def contar_destinatarios(campanha_id: int) -> int:
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM campanha_destinatarios WHERE campanha_id = %s", (campanha_id,))
        row = cur.fetchone()
        return int(row["n"]) if row else 0


def remover_destinatario(campanha_id: int, destinatario_id: int) -> bool:
    with get_db_cursor() as cur:
        cur.execute(
            "DELETE FROM campanha_destinatarios WHERE id = %s AND campanha_id = %s",
            (destinatario_id, campanha_id),
        )
        return cur.rowcount > 0


def limpar_destinatarios(campanha_id: int) -> int:
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM campanha_destinatarios WHERE campanha_id = %s", (campanha_id,))
        return cur.rowcount


def cnpjs_ja_contatados_campanha(campanha_id: int) -> set:
    """CNPJs que essa campanha ja contatou (em qualquer lote anterior).
    Usado pra calcular quem ainda falta no proximo lote."""
    with get_db_cursor() as cur:
        cur.execute("SELECT cnpj FROM campanha_envios WHERE campanha_id = %s", (campanha_id,))
        return {r["cnpj"] for r in cur.fetchall()}


def registrar_envio_campanha(campanha_id: int, cnpj: str, canal: str, status: str = "enviado") -> None:
    with get_db_cursor() as cur:
        cur.execute(
            """INSERT INTO campanha_envios (campanha_id, cnpj, canal, status)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (campanha_id, cnpj) DO UPDATE SET status = EXCLUDED.status""",
            (campanha_id, cnpj, canal, status),
        )


def contar_envios_campanha(campanha_id: int) -> int:
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM campanha_envios WHERE campanha_id = %s", (campanha_id,))
        row = cur.fetchone()
        return int(row["n"]) if row else 0


def contar_emails_enviados_hoje() -> int:
    """E-mails enviados hoje na conta inteira (UTC, como o provedor conta)."""
    try:
        with get_db_cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) AS n FROM emails_enviados
                   WHERE status = 'enviado' AND enviado_em IS NOT NULL
                     AND (enviado_em AT TIME ZONE 'UTC')::date
                         = (NOW() AT TIME ZONE 'UTC')::date"""
            )
            row = cur.fetchone()
            return int(row["n"]) if row else 0
    except Exception as e:
        # Falha na contagem nao pode liberar envio ilimitado.
        log.warning(f"contar_emails_enviados_hoje falhou: {e}")
        return 10**9


def contar_emails_enviados_hoje_org(organizacao_id: int) -> int:
    """E-mails enviados hoje POR ESTA empresa (UTC, como o provedor conta)."""
    try:
        with get_db_cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) AS n FROM emails_enviados
                   WHERE organizacao_id = %s
                     AND status = 'enviado' AND enviado_em IS NOT NULL
                     AND (enviado_em AT TIME ZONE 'UTC')::date
                         = (NOW() AT TIME ZONE 'UTC')::date""",
                (organizacao_id,))
            row = cur.fetchone()
            return int(row["n"]) if row else 0
    except Exception as e:
        # Mesma politica da contagem da conta: falhar pra mais, nunca liberar.
        log.warning(f"contar_emails_enviados_hoje_org falhou: {e}")
        return 10**9


def limite_diario_org(organizacao_id: int) -> Optional[int]:
    """Teto diario proprio da empresa, ou None se ela nao tiver um."""
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT email_limite_diario FROM organizacoes WHERE id = %s",
                        (organizacao_id,))
            row = cur.fetchone()
            if not row:
                return None
            v = row.get("email_limite_diario")
            return int(v) if v not in (None, "") and int(v) > 0 else None
    except Exception as e:
        # Aqui o seguro e' o oposto: sem saber o teto, nao se INVENTA um
        # limite que pararia a operacao. O teto da conta continua valendo.
        log.warning(f"limite_diario_org falhou: {e}")
        return None


def definir_limite_diario_org(organizacao_id: int, limite: Optional[int]) -> bool:
    """Define (ou remove, com None) o teto diario proprio da empresa."""
    with get_db_cursor() as cur:
        cur.execute("UPDATE organizacoes SET email_limite_diario = %s WHERE id = %s",
                    (int(limite) if limite and int(limite) > 0 else None, organizacao_id))
        return cur.rowcount > 0


def cnpjs_contatados_org(organizacao_id: int, desde_dias: Optional[int] = None) -> set:
    """CNPJs contatados por qualquer campanha da empresa.

    desde_dias limita a janela (permite recontato apos N dias); None = nunca.
    """
    sql = """SELECT ce.cnpj FROM campanha_envios ce
             JOIN campanhas c ON c.id = ce.campanha_id
             WHERE c.organizacao_id = %s AND ce.status = 'enviado'"""
    params: List[Any] = [organizacao_id]
    if desde_dias is not None:
        sql += " AND ce.criado_em >= NOW() - (%s || ' days')::interval"
        params.append(int(desde_dias))
    try:
        with get_db_cursor() as cur:
            cur.execute(sql, params)
            return {r["cnpj"] for r in cur.fetchall()}
    except Exception as e:
        log.warning(f"cnpjs_contatados_org falhou: {e}")
        raise


# Disparo direto da lista propria ("Disparar")
#
# Ninguem SAI da carteira: o contato muda de situacao.
#
#   disponivel  -> ainda nao foi contatado
#   reservado   -> separado para um envio em curso (dura minutos; evita que
#                  dois cliques ou duas pessoas peguem os mesmos contatos)
#   enviado     -> EM TRABALHO: ja' recebeu o 1o e-mail e e' daqui que sai o
#                  publico do follow-up
#   fora        -> pediu para sair, ou o texto montado foi barrado
#
# 'reservado' esquecido (servidor caiu no meio) volta para disponivel depois
# de _MINUTOS_RESERVA.

_MINUTOS_RESERVA = 15
_STATUS_FORA = ("bloqueado_conferencia", "descadastrado")
# 'adiado': saiu da fila de primeiros contatos por um tempo (ex.: recebeu o
# modelo errado e vai receber o certo daqui a alguns dias).
_DIAS_ADIADO = 5

# No cadastro da Receita o e-mail do MEI costuma ser o do CONTADOR. A mensagem
# fala com o dono do salao e chegaria a um escritorio, que nao responde. Regra
# estreita de proposito: "consultoria" e "gestao" pegariam salao de verdade.
_RX_CONTADOR = "(contab|contador|escritorio|fiscal|despachante|assessoria)"

_SQL_DISPONIVEIS = f"""
    FROM empresas_carteira c
    WHERE c.organizacao_id = %s
      AND COALESCE(c.email, '') LIKE '%%@%%'
      AND c.email !~* '{_RX_CONTADOR}'
      AND NOT COALESCE(c.email_compartilhado, FALSE)
      AND NOT EXISTS (SELECT 1 FROM emails_descadastrados d WHERE d.email = LOWER(TRIM(c.email)))
      AND NOT EXISTS (SELECT 1 FROM contato_situacao s
                       WHERE s.organizacao_id = c.organizacao_id AND s.cnpj = c.cnpj_completo)
      AND NOT EXISTS (SELECT 1 FROM contato_whatsapp w
                       WHERE w.organizacao_id = c.organizacao_id AND w.cnpj = c.cnpj_completo
                         AND w.status = 'chamado')
      AND NOT EXISTS (
          SELECT 1 FROM campanha_envios ce JOIN campanhas ca ON ca.id = ce.campanha_id
           WHERE ca.organizacao_id = c.organizacao_id AND ce.cnpj = c.cnpj_completo
             AND (ce.status = 'enviado'
                  OR (ca.nome LIKE 'Disparo -%%'
                      AND (ce.status IN {_STATUS_FORA} OR ce.status = 'na_fila'
                           OR (ce.status = 'adiado'
                               AND ce.criado_em > NOW() - INTERVAL '{_DIAS_ADIADO} days')
                           OR (ce.status = 'reservado'
                               AND ce.criado_em > NOW() - INTERVAL '{_MINUTOS_RESERVA} minutes')))))
"""


def resumo_disparo(organizacao_id: int) -> Dict[str, int]:
    """As tres carteiras da tela Disparar. Quem ja' foi contatado por outra
    campanha da empresa (fora do Disparar) tambem conta como em trabalho."""
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE COALESCE(email,'') LIKE '%%@%%') AS com_email "
                    "FROM empresas_carteira WHERE organizacao_id = %s", (organizacao_id,))
        base = cur.fetchone()
        cur.execute("SELECT COUNT(DISTINCT ce.cnpj) AS n FROM campanha_envios ce "
                    "JOIN campanhas ca ON ca.id = ce.campanha_id "
                    "WHERE ca.organizacao_id = %s AND ce.status = 'enviado'", (organizacao_id,))
        em_trabalho = cur.fetchone()
        cur.execute("SELECT COUNT(DISTINCT ce.cnpj) AS n FROM campanha_envios ce "
                    "JOIN campanhas ca ON ca.id = ce.campanha_id "
                    f"WHERE ca.organizacao_id = %s AND ca.nome LIKE 'Disparo -%%' AND ce.status IN {_STATUS_FORA}",
                    (organizacao_id,))
        fora = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS n " + _SQL_DISPONIVEIS, (organizacao_id,))
        disponiveis = cur.fetchone()
    na_lista, com_email = int(base["n"]), int(base["com_email"])
    with get_db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM empresas_carteira WHERE organizacao_id = %s "
                    f"AND COALESCE(email, '') LIKE '%%@%%' AND email ~* '{_RX_CONTADOR}'", (organizacao_id,))
        contabilidade = int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) AS n FROM contato_situacao WHERE organizacao_id = %s "
                    "AND situacao = 'desinteresse_comercial'", (organizacao_id,))
        desinteresse = int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) AS n FROM empresas_carteira WHERE organizacao_id = %s "
                    "AND COALESCE(email, '') LIKE '%%@%%' AND COALESCE(email_compartilhado, FALSE)", (organizacao_id,))
        compartilhado = int(cur.fetchone()["n"])
    return {"na_lista": na_lista, "sem_email": na_lista - com_email, "contabilidade": contabilidade,
            "desinteresse": desinteresse, "compartilhado": compartilhado,
            "disponiveis": int(disponiveis["n"]), "em_trabalho": int(em_trabalho["n"]),
            "fora": int(fora["n"])}


def campanha_de_disparo(organizacao_id: int, template_id: int, remetente: Optional[str],
                        criado_por: str, prefixo: str = "Disparo") -> Dict[str, Any]:
    """Campanha de apoio do disparo: uma por empresa + modelo + remetente,
    reaproveitada a cada clique. E' ela que guarda o registro de quem foi
    contatado; o usuario nao precisa saber que existe."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT * FROM campanhas
                WHERE organizacao_id = %s AND template_id = %s AND canal = 'email'
                  AND nome LIKE %s
                  AND COALESCE(remetente_username, '') = COALESCE(%s, '')
                ORDER BY id LIMIT 1""", (organizacao_id, template_id, f"{prefixo} -%", remetente))
        existente = cur.fetchone()
    if existente:
        return dict(existente)
    tpl = get_template(template_id, organizacao_id=organizacao_id) or {}
    nova = create_campanha(
        nome=f"{prefixo} - {tpl.get('nome') or template_id}", template_id=template_id, filtros={},
        created_by=criado_por, organizacao_id=organizacao_id, canal="email",
        remetente_username=remetente)
    update_campanha_status(nova["id"], "em_andamento")
    return nova


def reservar_proximos(campanha_id: int, organizacao_id: int, quantidade: int,
                      status: str = "reservado") -> List[Dict[str, Any]]:
    """Separa os proximos N disponiveis NUMA operacao so'. O par (campanha,
    cnpj) e' unico: numa corrida entre dois cliques, quem perde volta sem a
    linha em vez de duplicar o contato."""
    with get_db_cursor() as cur:
        cur.execute(
            f"""WITH escolhidos AS (
                    SELECT c.cnpj_completo, c.razao_social, c.nome_fantasia, c.email, c.contato_fone,
                           c.municipio, c.cnae_principal, c.cnae_descricao, c.porte_nome
                    {_SQL_DISPONIVEIS}
                    ORDER BY c.data_fundacao DESC NULLS LAST, c.cnpj_completo LIMIT %s
                ), reservados AS (
                    INSERT INTO campanha_envios (campanha_id, cnpj, canal, status)
                    SELECT %s, cnpj_completo, 'email', %s FROM escolhidos
                    ON CONFLICT (campanha_id, cnpj) DO UPDATE
                        SET status = EXCLUDED.status, criado_em = NOW()
                        WHERE campanha_envios.status NOT IN ('enviado', 'reservado', 'na_fila', 'bloqueado_conferencia', 'descadastrado')
                           OR (campanha_envios.status = 'reservado'
                               AND campanha_envios.criado_em <= NOW() - INTERVAL '{_MINUTOS_RESERVA} minutes')
                    RETURNING cnpj
                )
                SELECT e.* FROM escolhidos e JOIN reservados r ON r.cnpj = e.cnpj_completo
                ORDER BY e.cnpj_completo""",
            (organizacao_id, int(quantidade), campanha_id, status))
        return [dict(r) for r in cur.fetchall()]


# Follow-up: quem esta 'em trabalho' ha' N dias e nao respondeu

DIAS_FOLLOWUP = 5   # 2 toques no maximo: o 1o e-mail e um follow-up.
# desinteresse_comercial: contato mapeado como sem perfil de compra; sai do envio sem
# nunca ter sido abordado. E' marca de MAPEAMENTO (em lote), nao de resposta.
SITUACOES_CONTATO = ("respondeu", "sem_interesse", "desinteresse_comercial")

_SQL_FOLLOWUP = f"""
    FROM (SELECT DISTINCT ON (ce.cnpj) ce.cnpj, ce.criado_em AS enviado_em, ca.organizacao_id
            FROM campanha_envios ce JOIN campanhas ca ON ca.id = ce.campanha_id
           WHERE ca.organizacao_id = %s AND ce.status = 'enviado'
             AND ca.nome NOT LIKE 'Follow-up -%%'
           ORDER BY ce.cnpj, ce.criado_em) p
    JOIN empresas_carteira c ON c.organizacao_id = p.organizacao_id AND c.cnpj_completo = p.cnpj
    WHERE p.enviado_em <= NOW() - (%s || ' days')::interval
      AND COALESCE(c.email, '') LIKE '%%@%%'
      -- Mesma regra do primeiro contato (_SQL_DISPONIVEIS): e-mail de contador
      -- ou caixa dividida por varias empresas nao fala com a dona do salao. O
      -- follow-up nao checava isso, entao um contato barrado no 1o contato
      -- voltava pelo 2o -- a mesma regra valendo so' na metade dos caminhos.
      AND c.email !~* '{_RX_CONTADOR}'
      AND NOT COALESCE(c.email_compartilhado, FALSE)
      AND NOT EXISTS (SELECT 1 FROM emails_descadastrados d WHERE d.email = LOWER(TRIM(c.email)))
      AND NOT EXISTS (SELECT 1 FROM contato_situacao s
                       WHERE s.organizacao_id = p.organizacao_id AND s.cnpj = p.cnpj)
      AND NOT EXISTS (SELECT 1 FROM contato_whatsapp w
                       WHERE w.organizacao_id = p.organizacao_id AND w.cnpj = p.cnpj
                         AND w.status = 'chamado')
      AND NOT EXISTS (
          SELECT 1 FROM campanha_envios f JOIN campanhas fa ON fa.id = f.campanha_id
           WHERE fa.organizacao_id = p.organizacao_id AND fa.nome LIKE 'Follow-up -%%'
             AND f.cnpj = p.cnpj
             AND (f.status IN ('enviado', 'na_fila')
                  OR (f.status = 'reservado'
                      AND f.criado_em > NOW() - INTERVAL '{_MINUTOS_RESERVA} minutes')))
"""


def contar_followups_devidos(organizacao_id: int, dias: int = DIAS_FOLLOWUP) -> int:
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n " + _SQL_FOLLOWUP, (organizacao_id, str(int(dias))))
        return int(cur.fetchone()["n"])


def listar_followups_devidos(organizacao_id: int, dias: int = DIAS_FOLLOWUP,
                             limite: int = 50) -> List[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute(
            "SELECT c.cnpj_completo, c.razao_social, c.nome_fantasia, c.email, c.municipio, "
            "p.enviado_em, (NOW()::date - p.enviado_em::date) AS dias " + _SQL_FOLLOWUP +
            " ORDER BY p.enviado_em, c.cnpj_completo LIMIT %s",
            (organizacao_id, str(int(dias)), int(limite)))
        return [dict(r) for r in cur.fetchall()]


def reservar_followups(campanha_id: int, organizacao_id: int, quantidade: int,
                       dias: int = DIAS_FOLLOWUP, status: str = "reservado") -> List[Dict[str, Any]]:
    """Mesma ideia de reservar_proximos, sobre a carteira 'em trabalho'."""
    with get_db_cursor() as cur:
        cur.execute(
            f"""WITH escolhidos AS (
                    SELECT c.cnpj_completo, c.razao_social, c.nome_fantasia, c.email, c.contato_fone,
                           c.municipio, c.cnae_principal, c.cnae_descricao, c.porte_nome
                    {_SQL_FOLLOWUP}
                    ORDER BY p.enviado_em, c.cnpj_completo LIMIT %s
                ), reservados AS (
                    INSERT INTO campanha_envios (campanha_id, cnpj, canal, status)
                    SELECT %s, cnpj_completo, 'email', %s FROM escolhidos
                    ON CONFLICT (campanha_id, cnpj) DO UPDATE
                        SET status = EXCLUDED.status, criado_em = NOW()
                        WHERE campanha_envios.status NOT IN ('enviado', 'reservado', 'na_fila', 'bloqueado_conferencia', 'descadastrado')
                           OR (campanha_envios.status = 'reservado'
                               AND campanha_envios.criado_em <= NOW() - INTERVAL '{_MINUTOS_RESERVA} minutes')
                    RETURNING cnpj
                )
                SELECT e.* FROM escolhidos e JOIN reservados r ON r.cnpj = e.cnpj_completo
                ORDER BY e.cnpj_completo""",
            (organizacao_id, str(int(dias)), int(quantidade), campanha_id, status))
        return [dict(r) for r in cur.fetchall()]


# Fila com ritmo
#
# "Enviar 40" nao manda 40: entram na fila ('na_fila') e saem 10 por rodada,
# uma rodada a cada ~11-12 minutos (o agendador bate a cada poucos minutos e
# cada campanha so' solta a proxima quando proximo_lote_em chega). Dominio novo
# que despeja dezenas de e-mails de uma vez e' o jeito mais rapido de cair no
# spam; o ritmo e' parte do envio, nao um enfeite.

_PREFIXOS_FILA = ("Disparo -%", "Follow-up -%")


def puxar_da_fila(campanha_id: int, quantidade: int) -> List[Dict[str, Any]]:
    """Pega ate' N da fila desta campanha e os marca 'reservado' na mesma
    operacao. SKIP LOCKED: duas rodadas sobrepostas nao pegam o mesmo contato."""
    with get_db_cursor() as cur:
        cur.execute(
            """WITH pegos AS (
                   UPDATE campanha_envios SET status = 'reservado', criado_em = NOW()
                    WHERE id IN (SELECT id FROM campanha_envios
                                  WHERE campanha_id = %s AND status = 'na_fila'
                                  ORDER BY cnpj LIMIT %s FOR UPDATE SKIP LOCKED)
                RETURNING cnpj, template_id)
               SELECT c.cnpj_completo, c.razao_social, c.nome_fantasia, c.email, c.contato_fone,
                      c.municipio, c.cnae_principal, c.cnae_descricao, c.porte_nome, p.template_id
                 FROM pegos p JOIN campanhas ca ON ca.id = %s
                 JOIN empresas_carteira c ON c.organizacao_id = ca.organizacao_id AND c.cnpj_completo = p.cnpj
                ORDER BY c.cnpj_completo""", (campanha_id, int(quantidade), campanha_id))
        return [dict(r) for r in cur.fetchall()]


def marcar_emails_compartilhados(organizacao_id: int) -> int:
    """Marca os contatos cujo e-mail aparece em mais de um contato da carteira.

    No cadastro da Receita o e-mail do MEI costuma ser o do contador ou de um
    servico de abertura de empresa (um unico endereco chegou a estar em 294 MEIs).
    A mensagem fala com o dono do salao e cairia num intermediario, varias vezes,
    com saudacoes diferentes. Roda depois de toda importacao. Devolve quantos
    contatos ficaram marcados."""
    with get_db_cursor() as cur:
        cur.execute(
            """WITH d AS (SELECT LOWER(TRIM(email)) AS em FROM empresas_carteira
                           WHERE organizacao_id = %s AND COALESCE(email, '') <> ''
                           GROUP BY 1 HAVING COUNT(*) > 1)
               UPDATE empresas_carteira c
                  SET email_compartilhado = (LOWER(TRIM(c.email)) IN (SELECT em FROM d))
                WHERE c.organizacao_id = %s""", (organizacao_id, organizacao_id))
        cur.execute("SELECT COUNT(*) AS n FROM empresas_carteira WHERE organizacao_id = %s "
                    "AND email_compartilhado", (organizacao_id,))
        return int(cur.fetchone()["n"])


def distribuir_equilibrado(contagem: Dict[int, int], n: int) -> List[int]:
    """Escolhe o modelo de n contatos: cada um vai para o que tem MENOS envios
    ate' agora (empate sorteado). Funcao pura, para o equilibrio ser testavel."""
    import random
    contagem = dict(contagem)
    escolhas = []
    for _ in range(n):
        menor = min(contagem.values())
        t = random.choice([k for k, v in contagem.items() if v == menor])
        contagem[t] += 1
        escolhas.append(t)
    return escolhas


def sortear_modelos(campanha_id: int, organizacao_id: int, cnpjs: List[str],
                    template_ids: List[int]) -> Dict[int, int]:
    """Sorteia o modelo de cada contato, de forma EQUILIBRADA.

    Cada lead recebe um unico modelo de primeiro contato (quem ja' recebeu
    um sai dos disponiveis, entao nunca ha' dois). O pedido e' dividido em
    partes IGUAIS entre os modelos (a sobra de um pedido que nao divide por
    igual vai para modelos sorteados).

    So' o pedido conta, nao o historico: modelos de um teste precisam rodar
    NO MESMO PERIODO. Fazer o que tem menos envios "alcancar" os outros poria
    um modelo para tras (outro dia, outra reputacao do dominio) e a comparacao
    mediria a epoca, nao a abordagem.
    Devolve {template_id: quantos neste pedido}."""
    import random
    ids = [int(t) for t in template_ids]
    if not cnpjs or not ids:
        return {}
    contagem = {t: 0 for t in ids}
    with get_db_cursor() as cur:
        ordem = list(cnpjs)
        random.shuffle(ordem)
        escolhas = distribuir_equilibrado(contagem, len(ordem))
        neste = {t: escolhas.count(t) for t in ids}
        cur.execute(
            """UPDATE campanha_envios SET template_id = m.t
                 FROM unnest(%s::text[], %s::int[]) AS m(c, t)
                WHERE campanha_envios.campanha_id = %s AND campanha_envios.cnpj = m.c""",
            (ordem, escolhas, campanha_id))
    return neste


def metricas_modelos(organizacao_id: int) -> Dict[str, Any]:
    """Resultado por modelo de PRIMEIRO contato, so' do periodo em que os modelos
    rodaram JUNTOS: comeca no primeiro envio de um modelo diferente do primeiro
    modelo usado. Antes disso o modelo original rodava sozinho, e compara-lo com
    os novos mediria a epoca, nao a abordagem.

    'Respondeu' e' marcacao manual (o sistema nao le a caixa de resposta); 'abriu'
    pode incluir o pre-carregamento de imagem do Gmail. Follow-up fica de fora."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT MIN(e.enviado_em) AS desde FROM emails_enviados e
                 JOIN email_templates t ON t.id = e.template_id
                 JOIN campanhas ca ON ca.id = e.campaign_id
                WHERE e.organizacao_id = %s AND e.status = 'enviado'
                  AND ca.nome NOT LIKE 'Follow-up -%%' AND t.nome NOT ILIKE '%%follow%%'
                  AND e.template_id <> (
                      SELECT e2.template_id FROM emails_enviados e2
                        JOIN email_templates t2 ON t2.id = e2.template_id
                       WHERE e2.organizacao_id = %s AND e2.status = 'enviado'
                         AND t2.nome NOT ILIKE '%%follow%%'
                       ORDER BY e2.id LIMIT 1)""", (organizacao_id, organizacao_id))
        desde = cur.fetchone()["desde"]
        cur.execute(
            """SELECT t.id, t.nome,
                      COUNT(*) AS enviados,
                      COUNT(*) FILTER (WHERE e.entregue_em IS NOT NULL OR e.aberto_em IS NOT NULL
                                          OR e.clicado_em IS NOT NULL) AS entregues,
                      COUNT(*) FILTER (WHERE e.aberto_em IS NOT NULL) AS abertos,
                      COUNT(*) FILTER (WHERE e.clicado_em IS NOT NULL) AS clicados,
                      COUNT(*) FILTER (WHERE s.situacao = 'respondeu') AS respondeu,
                      COUNT(*) FILTER (WHERE s.situacao = 'sem_interesse') AS sem_interesse
                 FROM emails_enviados e
                 JOIN email_templates t ON t.id = e.template_id
                 JOIN campanhas ca ON ca.id = e.campaign_id
                 LEFT JOIN contato_situacao s
                        ON s.organizacao_id = e.organizacao_id AND s.cnpj = e.cnpj
                WHERE e.organizacao_id = %s AND e.status = 'enviado'
                  AND ca.nome NOT LIKE 'Follow-up -%%'
                  -- o modelo de follow-up mandado por engano como 1o contato (20 envios
                  -- de 14/10) nao entra: contamina a comparacao entre abordagens
                  AND t.nome NOT ILIKE '%%follow%%'
                  AND (%s::timestamptz IS NULL OR e.enviado_em >= %s::timestamptz)
                GROUP BY t.id, t.nome ORDER BY t.nome""", (organizacao_id, desde, desde))
        return {"desde": desde, "modelos": [dict(r) for r in cur.fetchall()]}


def abordagens_do_contato(organizacao_id: int, cnpj: str) -> List[Dict[str, Any]]:
    """O que este lead ja' recebeu: modelo, toque, quando e o que aconteceu."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT t.nome AS modelo, e.assunto, e.enviado_em, e.aberto_em, e.clicado_em,
                      (ca.nome LIKE 'Follow-up -%%') AS followup
                 FROM emails_enviados e
                 LEFT JOIN email_templates t ON t.id = e.template_id
                 LEFT JOIN campanhas ca ON ca.id = e.campaign_id
                WHERE e.organizacao_id = %s AND e.cnpj = %s AND e.status = 'enviado'
                ORDER BY e.id""", (organizacao_id, cnpj))
        return [dict(r) for r in cur.fetchall()]


def devolver_para_fila(campanha_id: int, cnpjs: List[str]) -> None:
    """Rodada que falhou por inteiro: quem estava 'reservado' volta para a fila."""
    if not cnpjs:
        return
    with get_db_cursor() as cur:
        cur.execute("UPDATE campanha_envios SET status = 'na_fila' "
                    "WHERE campanha_id = %s AND cnpj = ANY(%s) AND status = 'reservado'",
                    (campanha_id, cnpjs))


def campanhas_com_fila(organizacao_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Campanhas de Disparar/Follow-up com gente na fila e a hora de soltar a
    proxima rodada. Com organizacao_id, so' as daquela empresa."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT ca.* FROM campanhas ca
                WHERE (ca.nome LIKE %s OR ca.nome LIKE %s)
                  AND (%s::int IS NULL OR ca.organizacao_id = %s::int)
                  AND EXISTS (SELECT 1 FROM campanha_envios ce
                               WHERE ce.campanha_id = ca.id AND ce.status = 'na_fila')
                  AND (ca.proximo_lote_em IS NULL OR ca.proximo_lote_em <= NOW())
                ORDER BY ca.id""", _PREFIXOS_FILA + (organizacao_id, organizacao_id))
        return [dict(r) for r in cur.fetchall()]


def assumir_rodada(campanha_id: int, minutos: float) -> bool:
    """Reivindica a rodada desta campanha de forma ATOMICA: so' quem vence o
    UPDATE manda. O agendador do GitHub, o laco interno e a tela aberta podem
    bater ao mesmo tempo -- sem isto cada um mandaria 10 e a fila andaria 3x
    mais rapido que o prometido. Ao vencer, ja' marca a proxima para daqui a
    `minutos`."""
    with get_db_cursor() as cur:
        cur.execute(
            """UPDATE campanhas SET proximo_lote_em = NOW() + (%s || ' minutes')::interval
                WHERE id = %s AND (proximo_lote_em IS NULL OR proximo_lote_em <= NOW())
            RETURNING id""", (str(round(float(minutos), 2)), campanha_id))
        return cur.fetchone() is not None


def agendar_proximo_lote(campanha_id: int, minutos: float) -> None:
    with get_db_cursor() as cur:
        cur.execute("UPDATE campanhas SET proximo_lote_em = NOW() + (%s || ' minutes')::interval WHERE id = %s",
                    (str(round(float(minutos), 2)), campanha_id))


def resumo_fila(organizacao_id: int) -> Dict[str, Any]:
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) AS n, MIN(ca.proximo_lote_em) AS proxima
                 FROM campanha_envios ce JOIN campanhas ca ON ca.id = ce.campanha_id
                WHERE ca.organizacao_id = %s AND ce.status = 'na_fila'
                  AND (ca.nome LIKE %s OR ca.nome LIKE %s)""", (organizacao_id,) + _PREFIXOS_FILA)
        r = cur.fetchone()
    return {"na_fila": int(r["n"]), "proxima_rodada_em": r["proxima"]}


def cancelar_fila(organizacao_id: int) -> int:
    """Quem ainda nao saiu volta para disponivel (ou para devido, no follow-up)."""
    with get_db_cursor() as cur:
        cur.execute(
            """UPDATE campanha_envios SET status = 'nao_enviado'
                WHERE status = 'na_fila' AND campanha_id IN (
                      SELECT id FROM campanhas WHERE organizacao_id = %s
                         AND (nome LIKE %s OR nome LIKE %s))""", (organizacao_id,) + _PREFIXOS_FILA)
        return cur.rowcount


def marcar_situacao_contato(organizacao_id: int, cnpj: str, situacao: Optional[str], por: str) -> bool:
    """respondeu / sem_interesse tiram o contato do follow-up. None desfaz."""
    if situacao is not None and situacao not in SITUACOES_CONTATO:
        return False
    with get_db_cursor() as cur:
        if situacao is None:
            cur.execute("DELETE FROM contato_situacao WHERE organizacao_id = %s AND cnpj = %s",
                        (organizacao_id, cnpj))
        else:
            cur.execute(
                """INSERT INTO contato_situacao (organizacao_id, cnpj, situacao, por)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (organizacao_id, cnpj)
                   DO UPDATE SET situacao = EXCLUDED.situacao, por = EXCLUDED.por, atualizado_em = NOW()""",
                (organizacao_id, cnpj, situacao, por))
    return True


def devolver_nao_enviados(campanha_id: int, cnpjs: List[str]) -> None:
    """O que foi reservado e nao saiu volta para os disponiveis."""
    if not cnpjs:
        return
    with get_db_cursor() as cur:
        cur.execute("UPDATE campanha_envios SET status = 'nao_enviado' "
                    "WHERE campanha_id = %s AND cnpj = ANY(%s) AND status = 'reservado'",
                    (campanha_id, cnpjs))


def historico_disparo(organizacao_id: int, limite: int = 50) -> List[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT email_destino, assunto, status, erro, COALESCE(enviado_em, criado_em) AS quando
                 FROM emails_enviados WHERE organizacao_id = %s
                ORDER BY id DESC LIMIT %s""", (organizacao_id, int(limite)))
        return [dict(r) for r in cur.fetchall()]


def remetentes_da_empresa(organizacao_id: int) -> List[Dict[str, Any]]:
    """Quem pode assinar um disparo desta empresa: tem remetente configurado."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT u.username, c.email_from, c.email_from_name,
                      (c.gmail_refresh_token IS NOT NULL) AS gmail_proprio
                 FROM usuario_smtp_config c JOIN app_users u ON u.id = c.user_id
                WHERE c.organizacao_id = %s AND COALESCE(c.email_from, '') <> ''
                ORDER BY u.username""", (organizacao_id,))
        return [dict(r) for r in cur.fetchall()]


def definir_remetente_campanha(campanha_id: int, organizacao_id: int,
                               username: Optional[str]) -> bool:
    """Define de quem sai o e-mail desta campanha. None volta ao padrao.

    O username tem que ter acesso a ESTA empresa. Sem essa checagem uma
    campanha poderia sair assinada por alguem de outro cliente. A validacao
    mora aqui, no unico ponto que grava o campo, e nao em cada endpoint que
    chama.
    """
    if username:
        if not usuario_tem_acesso_org(username, organizacao_id):
            return False
    with get_db_cursor() as cur:
        cur.execute(
            "UPDATE campanhas SET remetente_username = %s "
            "WHERE id = %s AND organizacao_id = %s",
            (username or None, campanha_id, organizacao_id))
        return cur.rowcount > 0


def listar_campanhas_pendentes() -> List[Dict[str, Any]]:
    """Campanhas em lote que ainda tem lote pra mandar hoje: status
    'agendada' (primeiro lote) ou 'em_andamento' (proximos lotes), com
    repetir_ate ainda no futuro (ou sem data-limite) e que ainda nao
    rodaram hoje. 'pausada' fica de fora de proposito. Usada pelo cron
    diario (GitHub Actions)."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT * FROM campanhas
               WHERE status IN ('agendada', 'em_andamento')
                 AND tamanho_lote IS NOT NULL
                 AND (repetir_ate IS NULL OR repetir_ate >= CURRENT_DATE)
                 -- Antes era '::date < CURRENT_DATE' (uma rodada por dia).
                 -- O envio agora e' em rodadas curtas ao longo do dia.
                 AND (ultimo_lote_em IS NULL
                      OR ultimo_lote_em < NOW() - INTERVAL '9 minutes')
               ORDER BY id"""
        )
        rows = cur.fetchall()
        for r in rows:
            if r and r.get("filtros") and isinstance(r["filtros"], str):
                try: r["filtros"] = json.loads(r["filtros"])
                except: pass
        return rows


# LOTES DE LEADS

def create_lote_db(organizacao_id: int, nome: str, filtros: Dict, total_encontrado: int, criado_por: Optional[str]) -> Dict[str, Any]:
    with get_db_cursor() as cur:
        cur.execute(
            """INSERT INTO lotes_leads (organizacao_id, nome, filtros, total_encontrado, criado_por)
               VALUES (%s, %s, %s, %s, %s) RETURNING *""",
            (organizacao_id, nome, json.dumps(filtros or {}), total_encontrado, criado_por)
        )
        row = cur.fetchone()
        if row and row.get("filtros") and isinstance(row["filtros"], str):
            try: row["filtros"] = json.loads(row["filtros"])
            except: pass
        return row

def get_lote_db(lote_id: int, organizacao_id: int) -> Optional[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute("SELECT * FROM lotes_leads WHERE id = %s AND organizacao_id = %s", (lote_id, organizacao_id))
        row = cur.fetchone()
        if row and row.get("filtros") and isinstance(row["filtros"], str):
            try: row["filtros"] = json.loads(row["filtros"])
            except: pass
        return row

def listar_lotes_db(organizacao_id: int) -> List[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute("SELECT * FROM lotes_leads WHERE organizacao_id = %s ORDER BY created_at DESC", (organizacao_id,))
        rows = cur.fetchall()
        for r in rows:
            if r and r.get("filtros") and isinstance(r["filtros"], str):
                try: r["filtros"] = json.loads(r["filtros"])
                except: pass
        return rows

def delete_lote_db(lote_id: int, organizacao_id: int) -> bool:
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM lotes_leads WHERE id = %s AND organizacao_id = %s", (lote_id, organizacao_id))
        return cur.rowcount > 0


# COMPOSICAO DO LOTE

def materializar_lote(lote_id: int, empresas: List[Dict[str, Any]],
                      tamanho_bloco: int = 300) -> Dict[str, int]:
    """Fixa quem esta no lote e separa por canal.

    Sem e-mail mas com telefone vai para 'whatsapp'; sem nenhum contato fica
    registrado como 'sem_contato' em vez de sumir. O canal e-mail e fatiado
    em blocos do tamanho do envio diario, cada um com template proprio.
    """
    por_canal: Dict[str, List[Dict[str, Any]]] = {"email": [], "whatsapp": [], "sem_contato": []}
    vistos = set()
    for e in empresas:
        cnpj = (e.get("cnpj_completo") or "").strip()
        if not cnpj or cnpj in vistos:
            continue
        vistos.add(cnpj)
        email = (e.get("email") or "").strip()
        fone = re.sub(r"\D", "", e.get("contato_fone") or e.get("telefone") or "")
        canal = "email" if "@" in email else ("whatsapp" if len(fone) >= 10 else "sem_contato")
        por_canal[canal].append({
            "cnpj": cnpj, "email": email or None, "telefone": fone or None,
            "razao_social": (e.get("razao_social") or "")[:300],
        })

    linhas, blocos = [], []
    for canal, itens in por_canal.items():
        passo = tamanho_bloco if canal == "email" else max(len(itens), 1)
        for i, item in enumerate(itens):
            n = (i // passo) + 1
            linhas.append((lote_id, item["cnpj"], item["email"], item["telefone"],
                           item["razao_social"], canal, n))
        for n in range(1, (len(itens) - 1) // passo + 2 if itens else 1):
            blocos.append((lote_id, canal, n))

    with get_db_cursor() as cur:
        cur.execute("DELETE FROM lote_empresas WHERE lote_id = %s", (lote_id,))
        cur.execute("DELETE FROM lote_blocos WHERE lote_id = %s", (lote_id,))
        if linhas:
            cur.executemany(
                """INSERT INTO lote_empresas
                     (lote_id, cnpj, email, telefone, razao_social, canal, bloco)
                   VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", linhas)
        if blocos:
            cur.executemany(
                "INSERT INTO lote_blocos (lote_id, canal, bloco) VALUES (%s,%s,%s) "
                "ON CONFLICT DO NOTHING", blocos)

    return {c: len(v) for c, v in por_canal.items()}


def get_composicao_lote(lote_id: int) -> Dict[str, Any]:
    """Resumo por canal e blocos, para a tela de lotes."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT canal, COUNT(*)::int n,
                      COUNT(*) FILTER (WHERE status = 'enviado')::int enviados
                 FROM lote_empresas WHERE lote_id = %s GROUP BY canal""", (lote_id,))
        canais = {r["canal"]: {"total": r["n"], "enviados": r["enviados"]} for r in cur.fetchall()}
        cur.execute(
            """SELECT b.canal, b.bloco, b.template_id, b.status, b.campanha_id,
                      (SELECT COUNT(*) FROM lote_empresas le
                        WHERE le.lote_id = b.lote_id AND le.canal = b.canal
                          AND le.bloco = b.bloco)::int AS empresas
                 FROM lote_blocos b WHERE b.lote_id = %s
                ORDER BY b.canal, b.bloco""", (lote_id,))
        return {"canais": canais, "blocos": cur.fetchall()}


def definir_template_bloco(lote_id: int, canal: str, bloco: int,
                           template_id: Optional[int]) -> bool:
    with get_db_cursor() as cur:
        cur.execute(
            """UPDATE lote_blocos SET template_id = %s
                WHERE lote_id = %s AND canal = %s AND bloco = %s""",
            (template_id, lote_id, canal, bloco))
        return cur.rowcount > 0


def cnpjs_do_bloco(lote_id: int, canal: str, bloco: int,
                   apenas_pendentes: bool = True) -> List[Dict[str, Any]]:
    sql = """SELECT cnpj, email, telefone, razao_social FROM lote_empresas
              WHERE lote_id = %s AND canal = %s AND bloco = %s"""
    if apenas_pendentes:
        sql += " AND status = 'pendente'"
    with get_db_cursor() as cur:
        cur.execute(sql + " ORDER BY cnpj", (lote_id, canal, bloco))
        return cur.fetchall()


_CAMPOS_DA_EMPRESA = ("nome_fantasia", "municipio", "cnae_principal", "cnae_descricao", "porte_nome")


def mesclar_dados_do_lote(linha: Dict[str, Any], extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Linha do lote por cima dos dados completos da empresa. O que o lote
    guarda (e-mail, telefone, razao social) vale; o resto vem da fonte."""
    saida = {k: (extra or {}).get(k) for k in _CAMPOS_DA_EMPRESA}
    saida.update({k: v for k, v in linha.items() if v not in (None, "")})
    return saida


def complementar_empresas_do_lote(organizacao_id: int, linhas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """O lote guarda so' cnpj, e-mail, telefone e razao social. Sem cidade nem
    atividade o e-mail saia com 'em ?' no assunto e '{{cnae_descricao}}'
    vazio no corpo -- a personalizacao do template depende desses campos."""
    cnpjs = [l["cnpj_completo"] for l in linhas if l.get("cnpj_completo")]
    if not cnpjs:
        return linhas
    por_cnpj: Dict[str, Dict[str, Any]] = {}
    if org_escopo_base(organizacao_id) == "carteira":
        with get_db_cursor() as cur:
            cur.execute(
                f"SELECT cnpj_completo, {', '.join(_CAMPOS_DA_EMPRESA)} FROM empresas_carteira "
                "WHERE organizacao_id = %s AND cnpj_completo = ANY(%s)", (organizacao_id, cnpjs))
            por_cnpj = {r["cnpj_completo"]: r for r in cur.fetchall()}
    else:
        for c in cnpjs:
            d = get_empresa_by_cnpj_db(c, organizacao_id)
            if d:
                por_cnpj[c] = d
    return [mesclar_dados_do_lote(l, por_cnpj.get(l.get("cnpj_completo"))) for l in linhas]


def proximo_bloco_pendente(lote_id: int, canal: str = "email") -> Optional[Dict[str, Any]]:
    """Primeiro bloco do lote que ainda tem empresa pendente."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT b.canal, b.bloco, b.template_id,
                      (SELECT COUNT(*) FROM lote_empresas le
                        WHERE le.lote_id = b.lote_id AND le.canal = b.canal
                          AND le.bloco = b.bloco AND le.status = 'pendente')::int AS pendentes
                 FROM lote_blocos b
                WHERE b.lote_id = %s AND b.canal = %s
                ORDER BY b.bloco""", (lote_id, canal))
        for r in cur.fetchall():
            if r["pendentes"]:
                return r
        return None


def marcar_empresas_do_lote(lote_id: int, cnpjs: List[str], status: str = "enviado") -> int:
    if not cnpjs:
        return 0
    with get_db_cursor() as cur:
        cur.execute(
            """UPDATE lote_empresas SET status = %s, enviado_em = NOW()
                WHERE lote_id = %s AND cnpj = ANY(%s)""", (status, lote_id, list(cnpjs)))
        return cur.rowcount


def atualizar_status_bloco(lote_id: int, canal: str, bloco: int, status: str) -> None:
    with get_db_cursor() as cur:
        cur.execute(
            "UPDATE lote_blocos SET status = %s WHERE lote_id = %s AND canal = %s AND bloco = %s",
            (status, lote_id, canal, bloco))


def vincular_campanha_ao_lote(campanha_id: int, lote_id: Optional[int]) -> None:
    """lote_id None devolve a campanha ao filtro salvo."""
    with get_db_cursor() as cur:
        cur.execute("UPDATE campanhas SET lote_id = %s WHERE id = %s", (lote_id, campanha_id))


# PAINEL DE ENVIOS

def painel_envios(organizacao_id: int, dias: int = 30) -> Dict[str, Any]:
    """Fila, volume e engajamento numa consulta so'.

    Existe porque a informacao estava repartida entre Lotes (o que falta),
    Campanhas (o que rodou) e Monitor (quem abriu) -- e nenhuma das tres
    respondia "o que sai hoje e o que aconteceu com o que ja saiu".
    """
    vazio = {"fila": [], "resumo": {}, "engajamento": {}, "por_dia": []}
    try:
        with get_db_cursor() as cur:
            cur.execute(
                """SELECT l.id lote_id, l.nome lote, b.canal, b.bloco, b.status,
                          b.template_id, t.nome template,
                          (SELECT COUNT(*) FROM lote_empresas le
                            WHERE le.lote_id = b.lote_id AND le.canal = b.canal
                              AND le.bloco = b.bloco)::int total,
                          (SELECT COUNT(*) FROM lote_empresas le
                            WHERE le.lote_id = b.lote_id AND le.canal = b.canal
                              AND le.bloco = b.bloco AND le.status = 'pendente')::int pendentes,
                          c.id campanha_id, c.nome campanha, c.status campanha_status
                     FROM lote_blocos b
                     JOIN lotes_leads l ON l.id = b.lote_id
                     LEFT JOIN email_templates t ON t.id = b.template_id
                     LEFT JOIN campanhas c ON c.lote_id = l.id
                    WHERE l.organizacao_id = %s
                    ORDER BY l.created_at DESC, b.canal, b.bloco""",
                (organizacao_id,))
            fila = cur.fetchall()

            cur.execute(
                """SELECT COUNT(*)::int enviados,
                          COUNT(*) FILTER (WHERE entregue_em IS NOT NULL OR aberto_em IS NOT NULL
                                            OR clicado_em IS NOT NULL)::int entregues,
                          COUNT(*) FILTER (WHERE aberto_em IS NOT NULL)::int abertos,
                          COUNT(*) FILTER (WHERE clicado_em IS NOT NULL)::int clicados,
                          COUNT(*) FILTER (WHERE bounce_em IS NOT NULL)::int bounces,
                          COUNT(*) FILTER (WHERE status = 'bloqueado_conferencia')::int bloqueados
                     FROM emails_enviados
                    WHERE organizacao_id = %s
                      AND criado_em >= NOW() - (%s || ' days')::interval""",
                (organizacao_id, dias))
            eng = cur.fetchone() or {}

            cur.execute(
                """SELECT enviado_em::date dia, COUNT(*)::int n
                     FROM emails_enviados
                    WHERE organizacao_id = %s AND enviado_em IS NOT NULL
                      AND enviado_em >= NOW() - (%s || ' days')::interval
                    GROUP BY dia ORDER BY dia""",
                (organizacao_id, dias))
            por_dia = [{"dia": r["dia"].isoformat(), "n": r["n"]} for r in cur.fetchall()]

        pendentes = sum(f["pendentes"] for f in fila)
        return {
            "fila": fila,
            "resumo": {
                "blocos_pendentes": sum(1 for f in fila if f["pendentes"]),
                "empresas_na_fila": pendentes,
                "dias_para_esvaziar": (pendentes + 299) // 300 if pendentes else 0,
            },
            "engajamento": dict(eng),
            "por_dia": por_dia,
        }
    except Exception as e:
        log.warning(f"painel_envios falhou: {e}")
        return vazio


# Painel inicial (a tela que abre depois de escolher a empresa)

def _total_base_receita(cur):
    """Tamanho da base publica SEM varrer 1,68M de linhas.

    Esta tela esta no caminho critico de todo login, entao ela nao pode pagar
    o preco de get_metricas_db (6 varreduras completas, duas delas com SUM).
    Ordem das fontes, da melhor pra pior:

    1. `pipeline_metadata.total_empresas_sincronizadas` -- numero exato que o
       proprio ETL gravou ao carregar a base. De graca.
    2. `pg_class.reltuples` -- estimativa que o planner ja mantem. Tambem de
       graca, mas aproximada (e -1 em tabela que nunca passou por ANALYZE).

    Nunca COUNT(*). Se as duas falharem devolve None e a tela mostra "--":
    numero ausente e' melhor que numero caro, e muito melhor que inventado.
    """
    try:
        if _tabela_existe(cur, "pipeline_metadata"):
            cur.execute(
                "SELECT valor FROM pipeline_metadata "
                "WHERE chave = 'total_empresas_sincronizadas'"
            )
            row = cur.fetchone()
            if row and row.get("valor"):
                return {"total": int(float(row["valor"])), "estimado": False}
    except (ValueError, TypeError):
        pass  # metadata com valor nao numerico: cai pra estimativa
    try:
        cur.execute(
            "SELECT reltuples::bigint AS n FROM pg_class WHERE relname = 'dados_empresas'"
        )
        row = cur.fetchone()
        if row and row.get("n") and int(row["n"]) > 0:
            return {"total": int(row["n"]), "estimado": True}
    except Exception:
        pass
    return {"total": None, "estimado": False}


def painel_inicio(organizacao_id: int, dias: int = 14,
                  ver_conta_inteira: bool = False) -> Dict[str, Any]:
    """Tudo que a tela inicial mostra, numa chamada so'.

    Uma chamada e nao oito porque a tela abre depois de CADA escolha de
    empresa: oito requisicoes em paralelo no cold start do Render rendem oito
    chances de ver meio painel montado.

    Os numeros operacionais (CRM, envios, atividades) sao exatos -- vivem em
    tabelas pequenas e com indice por organizacao. O tamanho da base e'
    estimado quando a fonte e' a Receita; ver _total_base_receita.

    Passivo/divida NAO entra aqui de proposito. A tela inicial e' o que define
    a prioridade de quem abre o sistema, e divida nao e' criterio de
    prioridade neste produto -- quem precisa do numero o ve na ficha da
    empresa.
    """
    from datetime import datetime, timezone

    escopo = org_escopo_base(organizacao_id)
    vazio = {
        "escopo_base": escopo,
        "base": {"total": None, "estimado": False, "com_email": None, "cidades": None},
        "alcance": {"contatados": 0, "penetracao_pct": None},
        "crm": {}, "crm_total": 0,
        "envios": {"hoje_org": 0, "hoje_conta": None, "limite": 0, "restante": None,
                   "teto_atingido": False, "fila_pendente": 0, "por_dia": []},
        "engajamento": {},
        "atividades": {"pendentes": 0, "atrasadas": 0},
        "atualizado_em": None,
    }
    try:
        from ..config import settings
        limite_diario = int(getattr(settings, "EMAIL_LIMITE_DIARIO", 0) or 0)
    except Exception:
        limite_diario = 0

    try:
        with get_db_cursor() as cur:
            # Tamanho da fonte de prospeccao desta empresa
            if escopo == "carteira":
                # Carteira tem indice por org e fica na casa das dezenas de
                # milhar: contar exato aqui e' barato.
                cur.execute(
                    """SELECT COUNT(*)::int total,
                              COUNT(*) FILTER (WHERE COALESCE(email, '') <> '')::int com_email,
                              COUNT(DISTINCT NULLIF(municipio, ''))::int cidades
                         FROM empresas_carteira WHERE organizacao_id = %s""",
                    (organizacao_id,))
                r = cur.fetchone() or {}
                base = {"total": int(r.get("total") or 0), "estimado": False,
                        "com_email": int(r.get("com_email") or 0),
                        "cidades": int(r.get("cidades") or 0)}
            else:
                base = _total_base_receita(cur)
                # com_email/cidades exigiriam varrer a base inteira. A tela
                # omite o que nao da' pra saber barato em vez de exibir 0.
                base.update({"com_email": None, "cidades": None})

            # Alcance: quantos CNPJs desta empresa ja receberam algo
            # DISTINCT cnpj e nao COUNT(*): o mesmo CNPJ recebe varios passos
            # de sequencia, e "contatados" conta empresa, nao mensagem.
            cur.execute(
                """SELECT COUNT(DISTINCT cnpj)::int n FROM emails_enviados
                    WHERE organizacao_id = %s AND enviado_em IS NOT NULL""",
                (organizacao_id,))
            contatados = int((cur.fetchone() or {}).get("n") or 0)
            total_base = base.get("total")
            penetracao = (round(contatados / total_base * 100, 2)
                          if total_base and total_base > 0 else None)

            # Funil do CRM
            cur.execute(
                """SELECT COALESCE(NULLIF(status, ''), 'novo') AS status, COUNT(*)::int n
                     FROM crm WHERE organizacao_id = %s GROUP BY 1""",
                (organizacao_id,))
            crm = {r["status"]: r["n"] for r in cur.fetchall()}

            # Envios de hoje
            # O progresso e' da empresa, mas o teto diario e' da CONTA inteira
            # (uma caixa de Gmail autorizada, compartilhada entre as empresas).
            #
            # O numero da conta NAO volta para quem nao e' admin global:
            # por subtracao ele revela quanto a OUTRA empresa enviou hoje, e
            # volume de prospeccao de um cliente nao e' dado do outro. Volta
            # `teto_atingido`, um booleano -- sem ele a empresa veria o envio
            # parar sem explicacao.
            cur.execute(
                """SELECT COUNT(*) FILTER (WHERE organizacao_id = %s)::int hoje_org,
                          COUNT(*)::int hoje_conta
                     FROM emails_enviados
                    WHERE enviado_em >= CURRENT_DATE""",
                (organizacao_id,))
            h = cur.fetchone() or {}
            hoje_org = int(h.get("hoje_org") or 0)
            hoje_conta = int(h.get("hoje_conta") or 0)
            teto_atingido = bool(limite_diario and hoje_conta >= limite_diario)

            cur.execute(
                """SELECT enviado_em::date dia, COUNT(*)::int n
                     FROM emails_enviados
                    WHERE organizacao_id = %s AND enviado_em IS NOT NULL
                      AND enviado_em >= CURRENT_DATE - (%s || ' days')::interval
                    GROUP BY dia ORDER BY dia""",
                (organizacao_id, dias))
            por_dia = [{"dia": r["dia"].isoformat(), "n": r["n"]} for r in cur.fetchall()]

            # Engajamento da janela
            cur.execute(
                """SELECT COUNT(*)::int enviados,
                          COUNT(*) FILTER (WHERE entregue_em IS NOT NULL OR aberto_em IS NOT NULL
                                            OR clicado_em IS NOT NULL)::int entregues,
                          COUNT(*) FILTER (WHERE aberto_em IS NOT NULL)::int abertos,
                          COUNT(*) FILTER (WHERE clicado_em IS NOT NULL)::int clicados
                     FROM emails_enviados
                    WHERE organizacao_id = %s
                      AND criado_em >= NOW() - (%s || ' days')::interval""",
                (organizacao_id, dias))
            eng = dict(cur.fetchone() or {})

            # Fila que ainda nao saiu
            fila_pendente = 0
            if _tabela_existe(cur, "lote_empresas"):
                cur.execute(
                    """SELECT COUNT(*)::int n FROM lote_empresas le
                         JOIN lotes_leads l ON l.id = le.lote_id
                        WHERE l.organizacao_id = %s AND le.status = 'pendente'""",
                    (organizacao_id,))
                fila_pendente = int((cur.fetchone() or {}).get("n") or 0)

            # Atividades
            atividades = {"pendentes": 0, "atrasadas": 0}
            if _tabela_existe(cur, "crm_atividades"):
                cur.execute(
                    """SELECT COUNT(*) FILTER (WHERE status <> 'concluida')::int pendentes,
                              COUNT(*) FILTER (WHERE status <> 'concluida'
                                               AND prazo IS NOT NULL
                                               AND prazo < CURRENT_DATE)::int atrasadas
                         FROM crm_atividades WHERE organizacao_id = %s""",
                    (organizacao_id,))
                atividades = dict(cur.fetchone() or atividades)

        return {
            "escopo_base": escopo,
            "base": base,
            "alcance": {"contatados": contatados, "penetracao_pct": penetracao},
            "crm": crm,
            "crm_total": sum(crm.values()),
            "envios": {
                "hoje_org": hoje_org,
                # None, e nao 0, quando a pessoa nao pode ver: zero seria
                # um numero errado, None a tela sabe nao exibir.
                "hoje_conta": hoje_conta if ver_conta_inteira else None,
                "limite": limite_diario,
                "restante": (max(0, limite_diario - hoje_conta)
                             if (limite_diario and ver_conta_inteira) else None),
                "teto_atingido": teto_atingido,
                "fila_pendente": fila_pendente,
                "por_dia": por_dia,
            },
            "engajamento": eng,
            "atividades": atividades,
            "atualizado_em": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        log.warning(f"painel_inicio falhou: {e}")
        return vazio


# Filtro fixado do painel de Empresas

def salvar_filtro_empresas(username: str, organizacao_id: int, filtros: Dict[str, Any]) -> Dict[str, Any]:
    """Fixa a pesquisa atual da pessoa nesta empresa.

    Um slot so' por (usuario, organizacao): salvar de novo sobrescreve o
    anterior -- e' ponto de retorno, nao historico. Devolve o registro
    gravado (com atualizado_em) porque a tela mostra quando foi o ultimo
    save."""
    with get_db_cursor() as cur:
        cur.execute(
            """INSERT INTO filtro_salvo (username, organizacao_id, filtros, atualizado_em)
               VALUES (%s, %s, %s::jsonb, NOW())
               ON CONFLICT (username, organizacao_id) DO UPDATE SET
                   filtros = EXCLUDED.filtros,
                   atualizado_em = NOW()
               RETURNING username, organizacao_id, filtros, atualizado_em""",
            (username, organizacao_id, json.dumps(filtros or {})),
        )
        return cur.fetchone()


def obter_filtro_empresas(username: str, organizacao_id: int) -> Optional[Dict[str, Any]]:
    """Filtro fixado da pessoa nesta empresa, ou None se nunca salvou."""
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT filtros, atualizado_em FROM filtro_salvo
               WHERE username = %s AND organizacao_id = %s""",
            (username, organizacao_id),
        )
        return cur.fetchone()


def apagar_filtro_empresas(username: str, organizacao_id: int) -> bool:
    """Solta o filtro fixado (a tela volta a abrir sem ponto de retorno)."""
    with get_db_cursor() as cur:
        cur.execute(
            "DELETE FROM filtro_salvo WHERE username = %s AND organizacao_id = %s",
            (username, organizacao_id),
        )
        return cur.rowcount > 0
