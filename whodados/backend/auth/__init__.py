"""Auth Module."""
from .service import (
    autenticar_usuario, criar_access_token, decodificar_access_token,
    hash_senha, verificar_senha, criar_usuario
)
from .dependencies import (
    get_current_user, get_current_user_optional, require_admin, get_active_org,
    get_papel_ativo, require_org_admin,
)
from .password_reset import gerar_token_reset, validar_token_reset, redefinir_senha
__all__ = [
    "autenticar_usuario", "criar_access_token", "decodificar_access_token",
    "hash_senha", "verificar_senha", "criar_usuario",
    "get_current_user", "get_current_user_optional", "require_admin", "get_active_org",
    "get_papel_ativo", "require_org_admin",
    "gerar_token_reset", "validar_token_reset", "redefinir_senha",
]
