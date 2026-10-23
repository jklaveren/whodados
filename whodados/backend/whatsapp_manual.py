"""WhatsApp manual: a equipe chama cada contato pelo proprio aparelho.

Nao ha' envio automatico: o sistema so' escolhe quem chamar, monta o link
(wa.me) com a mensagem pronta e guarda quem ja' foi chamado. Disparo em massa
por numero comum leva a conta a ser denunciada e banida, e a API oficial cobra
por conversa -- por isso a pessoa aperta o enviar.

O telefone da Receita vem sem o 9 do celular ((51) 98396703). Celular e'
numero de 8 digitos comecando em 6 a 9 (a Receita guarda assim) ou de 9 digitos
comecando em 9; fixo comeca em 2 a 5 e fica de fora."""
import re
from typing import Dict, List, Optional

from .db.service import get_db_cursor
from .dominios_email import CONHECIDOS, classificar, dominio_de
from .mailer.service import _saudacao, _titulo

STATUS_WHATSAPP = ("chamado", "sem_whatsapp")

# Ordem de chamada: quem abriu o e-mail, quem recebeu e nao abriu, quem nao tem
# e-mail (so' o WhatsApp alcanca) e, por ultimo, quem ainda nao recebeu nada.
GRUPOS = ("abriu", "email", "sem_email", "novo")

_SQL_CHAMAR = r"""
    FROM (SELECT c.*, regexp_replace(COALESCE(c.contato_fone, ''), '\D', '', 'g') AS d,
                 EXISTS (SELECT 1 FROM emails_enviados e WHERE e.organizacao_id = c.organizacao_id
                          AND e.cnpj = c.cnpj_completo AND e.aberto_em IS NOT NULL) AS abriu,
                 EXISTS (SELECT 1 FROM emails_enviados e WHERE e.organizacao_id = c.organizacao_id
                          AND e.cnpj = c.cnpj_completo AND e.status = 'enviado') AS recebeu
            FROM empresas_carteira c WHERE c.organizacao_id = %s) c
    WHERE ((length(d) = 10 AND substr(d, 3, 1) ~ '[6-9]') OR (length(d) = 11 AND substr(d, 3, 1) = '9'))
      AND substr(d, 1, 2) ~ '^[1-9][1-9]$'
      AND NOT COALESCE(c.email_compartilhado, FALSE)
      AND NOT (COALESCE(c.email, '') <> '' AND c.email ~* '(contab|contador|escritorio|fiscal|despachante|assessoria)')
      AND NOT EXISTS (SELECT 1 FROM emails_descadastrados x WHERE x.email = LOWER(TRIM(c.email)))
      AND NOT EXISTS (SELECT 1 FROM contato_situacao s
                       WHERE s.organizacao_id = c.organizacao_id AND s.cnpj = c.cnpj_completo)
      AND NOT EXISTS (SELECT 1 FROM contato_whatsapp w
                       WHERE w.organizacao_id = c.organizacao_id AND w.cnpj = c.cnpj_completo)
"""

_SQL_GRUPO = """CASE WHEN c.abriu THEN 'abriu'
                     WHEN c.recebeu THEN 'email'
                     WHEN COALESCE(c.email, '') NOT LIKE '%%@%%' THEN 'sem_email'
                     ELSE 'novo' END"""


def celular_br(fone: Optional[str]) -> Optional[str]:
    """Telefone da carteira -> 55DD9XXXXXXXX, ou None se nao for celular."""
    d = re.sub(r"\D", "", fone or "")
    if len(d) in (12, 13) and d.startswith("55"):
        d = d[2:]
    if not re.match(r"^[1-9][1-9]", d):
        return None
    if len(d) == 10 and d[2] in "6789":
        d = d[:2] + "9" + d[2:]
    if len(d) == 11 and d[2] == "9":
        return "55" + d
    return None


def mensagem(grupo: str, nome: str, cidade: str, eu: str, com_site: bool = False) -> str:
    """Texto curto, de pessoa, com a saida de opt-out. Cita o e-mail so' para
    quem recebeu um. Quem ja' tem site recebe oferta de MELHORIA, nao de site novo
    (sem afirmar defeito nenhum: ninguem olhou o site dele ainda)."""
    ola = f"Oi, {nome}, tudo bem?" if nome else "Oi, tudo bem?"
    quem = f"Aqui é {eu}, da Beta." if eu else "Aqui é da Beta."
    saida = "Se não quiser receber mais mensagens, é só me avisar."
    if com_site:
        return (f"{ola} {quem} A gente cuida de sites para quem trabalha com beleza. Se vocês já têm site, "
                f"posso dar uma olhada no que dá para melhorar (mais rápido, bom no celular, com botão de "
                f"WhatsApp para o cliente chamar direto), sem compromisso. Posso te mostrar? {saida}")
    if grupo in ("abriu", "email"):
        return (f"{ola} {quem} Te mandei um e-mail sobre um site simples, com botão de WhatsApp, "
                f"para o seu trabalho. Posso te mostrar como ficaria? {saida}")
    onde = f" em {cidade}" if cidade else ""
    return (f"{ola} {quem} A gente faz sites simples para quem trabalha com beleza{onde}: seus serviços, "
            f"seus preços e um botão para o cliente chamar direto no seu WhatsApp, a partir de R$ 400,00 "
            f"em até 12x de R$ 33,33 sem juros. Posso te mostrar como ficaria no seu caso? {saida}")


def contar_para_chamar(organizacao_id: int) -> Dict[str, int]:
    with get_db_cursor() as cur:
        cur.execute(f"SELECT {_SQL_GRUPO} AS g, COUNT(*) AS n " + _SQL_CHAMAR + " GROUP BY 1", (organizacao_id,))
        achados = {r["g"]: int(r["n"]) for r in cur.fetchall()}
    return {g: achados.get(g, 0) for g in GRUPOS}


_DOM = "lower(split_part(COALESCE(c.email, ''), '@', 2))"
FILTROS_SITE = ("todos", "com", "sem")


def _filtro_site_sql(site: str):
    """Condicao SQL do filtro. 'com': e-mail de dominio que nao e' de provedor (a classificacao fina,
    sem erro de digitacao/instituicao, e' refeita em Python). 'sem': sem e-mail ou e-mail de provedor."""
    if site == "com":
        return f" AND COALESCE(c.email, '') LIKE '%%@%%' AND {_DOM} <> ALL(%s)", [sorted(CONHECIDOS)]
    if site == "sem":
        return f" AND (COALESCE(c.email, '') NOT LIKE '%%@%%' OR {_DOM} = ANY(%s))", [sorted(CONHECIDOS)]
    return "", []


def contar_por_site(organizacao_id: int) -> Dict[str, int]:
    """Quantos da lista tem e-mail de dominio da empresa (provavel site) e quantos nao."""
    with get_db_cursor() as cur:
        cur.execute(f"SELECT {_DOM} AS dom, COUNT(*) AS n " + _SQL_CHAMAR + " GROUP BY 1", (organizacao_id,))
        linhas = [(r["dom"], int(r["n"])) for r in cur.fetchall()]
    total = {"com": 0, "sem": 0, "outros": 0}
    for dom, n in linhas:
        tipo = classificar(f"x@{dom}" if dom else "")
        total["com" if tipo == "empresa" else "sem" if tipo in ("provedor", "vazio") else "outros"] += n
    return total


def listar_para_chamar(organizacao_id: int, limite: int = 30, eu: str = "", site: str = "todos") -> List[Dict]:
    """Os proximos a chamar, na ordem de prioridade, ja' com numero e texto."""
    extra, params_extra = _filtro_site_sql(site if site in FILTROS_SITE else "todos")
    # No filtro 'com' a classificacao fina descarta alguns depois do SQL: busca mais e corta no fim.
    buscar = int(limite) * (12 if site == "com" else 1)
    with get_db_cursor() as cur:
        cur.execute(
            f"""SELECT c.cnpj_completo, c.razao_social, c.nome_fantasia, c.municipio, c.contato_fone,
                       c.email, c.data_fundacao, {_SQL_GRUPO} AS grupo """ + _SQL_CHAMAR + extra +
            """ ORDER BY CASE WHEN c.abriu THEN 0 WHEN c.recebeu THEN 1
                              WHEN COALESCE(c.email, '') NOT LIKE '%%@%%' THEN 2 ELSE 3 END,
                          c.data_fundacao DESC NULLS LAST, c.cnpj_completo
                 LIMIT %s""",
            [organizacao_id] + params_extra + [buscar])
        linhas = [dict(r) for r in cur.fetchall()]
    saida = []
    for r in linhas:
        numero = celular_br(r["contato_fone"])
        if not numero:
            continue
        tem_site = classificar(r["email"]) == "empresa"
        if site == "com" and not tem_site:
            continue
        if len(saida) >= int(limite):
            break
        nome = _saudacao(None, r["razao_social"], r["nome_fantasia"])
        cidade = _titulo(r["municipio"] or "")
        saida.append({
            "cnpj_completo": r["cnpj_completo"],
            "nome": nome or r["nome_fantasia"] or r["razao_social"],
            "empresa": r["nome_fantasia"] or r["razao_social"],
            "cidade": cidade,
            "numero": numero,
            "grupo": r["grupo"],
            "tem_site": tem_site,
            "site_url": f"https://{dominio_de(r['email'])}" if tem_site else "",
            "texto": mensagem(r["grupo"], nome, cidade, eu, com_site=tem_site),
        })
    return saida


def buscar_contato(organizacao_id: int, termo: str, limite: int = 10) -> List[Dict]:
    """Acha um contato da carteira por telefone, CNPJ, nome ou e-mail, com a situacao dele.

    Serve para registrar a resposta de quem escreveu por conta propria (WhatsApp, e-mail) e nao
    esta em nenhuma lista na tela: o numero de onde a pessoa escreve costuma ser o do cadastro."""
    termo = (termo or "").strip()
    digitos = re.sub(r"\D", "", termo)
    condicoes, params = [], []
    if len(digitos) >= 8:
        condicoes.append(r"regexp_replace(COALESCE(c.contato_fone, ''), '\D', '', 'g') LIKE %s")
        params.append("%" + digitos[-8:])
        condicoes.append("c.cnpj_completo LIKE %s")
        params.append(digitos + "%")
    if len(termo) >= 3 and re.search(r"[A-Za-z@]", termo):
        for col in ("c.nome_fantasia", "c.razao_social", "c.email"):
            condicoes.append(f"{col} ILIKE %s")
            params.append("%" + termo + "%")
    if not condicoes:
        return []
    with get_db_cursor() as cur:
        cur.execute(
            """SELECT c.cnpj_completo, c.razao_social, c.nome_fantasia, c.municipio, c.contato_fone, c.email,
                      s.situacao AS situacao, w.status AS whatsapp
                 FROM empresas_carteira c
                 LEFT JOIN contato_situacao s ON s.organizacao_id = c.organizacao_id AND s.cnpj = c.cnpj_completo
                 LEFT JOIN contato_whatsapp w ON w.organizacao_id = c.organizacao_id AND w.cnpj = c.cnpj_completo
                WHERE c.organizacao_id = %s AND (""" + " OR ".join(condicoes) + """)
                ORDER BY c.nome_fantasia NULLS LAST, c.cnpj_completo LIMIT %s""",
            [organizacao_id] + params + [int(limite)])
        linhas = [dict(r) for r in cur.fetchall()]
    return [{
        "cnpj_completo": r["cnpj_completo"],
        "nome": _saudacao(None, r["razao_social"], r["nome_fantasia"]) or r["razao_social"],
        "empresa": r["nome_fantasia"] or r["razao_social"],
        "cidade": _titulo(r["municipio"] or ""),
        "fone": r["contato_fone"] or "",
        "email": r["email"] or "",
        "situacao": r["situacao"],
        "whatsapp": r["whatsapp"],
    } for r in linhas]


def marcar_whatsapp(organizacao_id: int, cnpj: str, status: Optional[str], por: str) -> bool:
    """chamado / sem_whatsapp tiram o contato da lista. None desfaz."""
    if status is not None and status not in STATUS_WHATSAPP:
        return False
    with get_db_cursor() as cur:
        if status is None:
            cur.execute("DELETE FROM contato_whatsapp WHERE organizacao_id = %s AND cnpj = %s",
                        (organizacao_id, cnpj))
        else:
            cur.execute(
                """INSERT INTO contato_whatsapp (organizacao_id, cnpj, status, por)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (organizacao_id, cnpj)
                   DO UPDATE SET status = EXCLUDED.status, por = EXCLUDED.por, atualizado_em = NOW()""",
                (organizacao_id, cnpj, status, por))
    return True
