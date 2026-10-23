"""Gera o refresh token do Gmail para o envio da aplicacao.

Roda uma vez, na maquina de quem vai enviar. Abre o navegador, a pessoa
entra com a conta remetente e autoriza. O token resultante nao expira
enquanto nao for revogado.

Nao exige ser admin do Workspace: a autorizacao e' da propria conta.

Uso:
    pip install google-auth-oauthlib
    python scripts/autorizar_gmail.py caminho/para/client_secret.json
"""
from __future__ import annotations

import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("Falta a dependencia. Rode:\n    pip install google-auth-oauthlib")
    raise SystemExit(1)

ESCOPOS = ["https://www.googleapis.com/auth/gmail.send"]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    arquivo = sys.argv[1]

    flow = InstalledAppFlow.from_client_secrets_file(arquivo, ESCOPOS)
    # prompt="consent" forca o Google a devolver refresh_token: sem isso ele
    # so manda na primeira autorizacao daquela conta, e uma reexecucao viria
    # sem token.
    cred = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not cred.refresh_token:
        print("\nO Google nao devolveu refresh token. Revogue o acesso em")
        print("https://myaccount.google.com/permissions e rode de novo.")
        return 1

    print("\n" + "=" * 68)
    print("Copie para o Render (Environment):")
    print("=" * 68)
    print(f"GMAIL_OAUTH_CLIENT_ID={cred.client_id}")
    print(f"GMAIL_OAUTH_CLIENT_SECRET={cred.client_secret}")
    print(f"GMAIL_OAUTH_REFRESH_TOKEN={cred.refresh_token}")
    print("=" * 68)
    print("\nSao credenciais: nao commite e nao cole em chat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
