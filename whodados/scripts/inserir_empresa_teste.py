"""Insere (ou atualiza) UMA empresa em dados_empresas, para testar campanha
com um destinatario real e controlado.

ATENCAO -- a linha nao sobrevive ao ETL: sync_data_to_db.py usa
to_sql(if_exists="replace"), que derruba e recria dados_empresas a cada
carga. Rode este script de novo depois de cada ETL.

Uso:
    set DATABASE_URL=postgresql://...
    python scripts/inserir_empresa_teste.py ^
        --cnpj 50552952000196 ^
        --razao "JESSICA VAN KLAVEREN ME" ^
        --email voce@dominio.com ^
        --municipio "PORTO ALEGRE" --cnae 6201501

    python scripts/inserir_empresa_teste.py --remover --cnpj 50552952000196
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import psycopg2


def _cod_municipio(cur, nome: str) -> str | None:
    """Codigo do municipio pelo nome, do jeito que a base guarda (a listagem
    filtra por codigo, nao por nome -- ver _mapa_municipios)."""
    if not nome:
        return None
    cur.execute(
        "SELECT cod_municipio FROM municipios WHERE UPPER(nome_municipio) = UPPER(%s) LIMIT 1",
        (nome.strip(),),
    )
    row = cur.fetchone()
    return row[0] if row else None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cnpj", required=True, help="14 digitos, com ou sem pontuacao")
    p.add_argument("--razao", help="razao social")
    p.add_argument("--email", help="e-mail que vai receber a campanha")
    p.add_argument("--fantasia", default="")
    p.add_argument("--municipio", default="", help="nome; resolvido para codigo")
    p.add_argument("--cnae", default="", help="CNAE principal, 7 digitos")
    p.add_argument("--telefone", default="")
    p.add_argument("--capital", default="0")
    p.add_argument("--porte", default="01", help="codigo de porte da RF")
    p.add_argument("--remover", action="store_true", help="apaga em vez de inserir")
    args = p.parse_args()

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERRO: defina DATABASE_URL no ambiente.", file=sys.stderr)
        return 2

    cnpj = re.sub(r"\D", "", args.cnpj)
    if len(cnpj) != 14:
        print(f"ERRO: CNPJ precisa ter 14 digitos (recebi {len(cnpj)}).", file=sys.stderr)
        return 2
    basico = cnpj[:8]

    if not args.remover and not (args.razao and args.email):
        print("ERRO: --razao e --email sao obrigatorios ao inserir.", file=sys.stderr)
        return 2

    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            if args.remover:
                cur.execute('DELETE FROM dados_empresas WHERE "CNPJ_COMPLETO" = %s', (cnpj,))
                print(f"removidas {cur.rowcount} linha(s) de dados_empresas.")
                conn.commit()
                return 0

            cod_mun = _cod_municipio(cur, args.municipio)
            if args.municipio and not cod_mun:
                print(f"AVISO: municipio {args.municipio!r} nao encontrado; "
                      f"a empresa ficara sem municipio (e fora do filtro de cidade).")

            # Mesma chave que a listagem usa. Reinserir sobrescreve, entao
            # rodar duas vezes nao cria duplicata.
            cur.execute('DELETE FROM dados_empresas WHERE "CNPJ_COMPLETO" = %s', (cnpj,))
            cur.execute(
                '''INSERT INTO dados_empresas
                     ("CNPJ_BASICO", "CNPJ_COMPLETO", "RAZAO_SOCIAL", "NOME_FANTASIA",
                      "CNAE_PRINCIPAL", "COD_MUNICIPIO", "EMAIL", "TELEFONE",
                      "CAPITAL_SOCIAL", "PORTE_EMPRESA", "DIVIDA_TOTAL")
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)''',
                (basico, cnpj, args.razao, args.fantasia, args.cnae, cod_mun,
                 args.email, args.telefone, args.capital, args.porte),
            )
            conn.commit()

        print(f"OK: {args.razao} ({cnpj}) inserida com e-mail {args.email}.")
        if args.cnae.startswith("69"):
            print("AVISO: CNAE 69 esta excluido da prospeccao "
                  "(CNAE_DIVISOES_EXCLUIDAS) -- esta empresa NAO vai aparecer "
                  "nos filtros. Use outro CNAE para testar.")
        print("Lembre: o proximo ETL recria dados_empresas e apaga esta linha.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
