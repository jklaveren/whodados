"""
CLI para o dono do sistema criar/atualizar usuários com acesso à API.

LOCAL: whodados/scripts/criar_usuario.py

Uso:
    python whodados/scripts/criar_usuario.py joao
    python whodados/scripts/criar_usuario.py admin --admin
"""
import argparse
import getpass
import sys
from pathlib import Path

# Adiciona a raiz do projeto ao sys.path (e a subpasta aninhada por compatibilidade).
_RAIZ = Path(__file__).resolve().parents[2]
for _caminho in (_RAIZ, _RAIZ / "analise-empresarial-streamlit"):
    if _caminho.exists() and str(_caminho) not in sys.path:
        sys.path.insert(0, str(_caminho))

from auth_service import criar_ou_atualizar_usuario


def main():
    parser = argparse.ArgumentParser(description="Cria ou atualiza um usuário com acesso à API/app.")
    parser.add_argument("username", help="Nome de usuário (login)")
    parser.add_argument("--admin", action="store_true", help="Concede privilégios de administrador")
    args = parser.parse_args()

    senha = getpass.getpass("Senha: ")
    confirmacao = getpass.getpass("Confirme a senha: ")
    if senha != confirmacao:
        print("❌ As senhas não coincidem.", file=sys.stderr)
        sys.exit(1)
    if len(senha) < 8:
        print("❌ Use uma senha com pelo menos 8 caracteres.", file=sys.stderr)
        sys.exit(1)

    criar_ou_atualizar_usuario(args.username, senha, is_admin=args.admin)
    print(f"✅ Usuário '{args.username}' criado/atualizado (admin={args.admin}).")


if __name__ == "__main__":
    main()
