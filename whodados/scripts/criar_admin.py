"""CLI para criar usuario admin no WhoDados 2.0."""
import sys
import getpass
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAIZ))

from backend.config import settings
from backend.logger import logger
from backend.db.config import ensure_tables, init_pool
from backend.auth import criar_usuario

def main():
    print("WhoDados - Criar Usuario Admin")
    print("="*40)
    
    if not settings.DATABASE_URL:
        print("ERRO: DATABASE_URL nao configurado!")
        print("Configure o arquivo backend/.env primeiro.")
        return
    
    try:
        init_pool()
        ensure_tables()
    except Exception as e:
        print(f"Erro ao conectar banco: {e}")
        return
    
    username = input("Username: ").strip()
    if not username:
        print("Username e obrigatorio.")
        return
    
    password = getpass.getpass("Senha: ").strip()
    confirm = getpass.getpass("Confirme a senha: ").strip()
    if password != confirm:
        print("As senhas nao coincidem.")
        return
    if len(password) < 8:
        print("Senha precisa ter minimo 8 caracteres.")
        return
    
    email = input("Email (opcional): ").strip() or None
    is_admin = input("Admin? (s/N): ").lower().startswith("s")
    
    try:
        user = criar_usuario(username, password, email, is_admin=is_admin)
        print(f"\nUsuario criado com sucesso!")
        print(f"Username: {user['username']}")
        print(f"Admin: {user.get('is_admin', False)}")
    except ValueError as e:
        print(f"\nErro: {e}")
    except Exception as e:
        print(f"\nErro: {e}")
        logger.error(e)

if __name__ == "__main__":
    main()