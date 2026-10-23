"""Auth Dependencies."""
from fastapi import Request, Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from typing import Dict, Optional

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> Dict:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token nao fornecido", headers={"WWW-Authenticate": "Bearer"})
    from .service import decodificar_access_token
    payload = decodificar_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido ou expirado", headers={"WWW-Authenticate": "Bearer"})
    return payload

def get_current_user_optional(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[Dict]:
    if not token:
        return None
    from .service import decodificar_access_token
    return decodificar_access_token(token)

def require_admin(current_user: Dict = Depends(get_current_user)) -> Dict:
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito a administradores")
    return current_user


# Metodos que gravam. Pra estes, adivinhar a empresa e' pior que falhar: o
# registro nasce na empresa errada e ninguem percebe na hora.
_METODOS_ESCRITA = {"POST", "PUT", "PATCH", "DELETE"}


def get_active_org(
    request: Request,
    current_user: Dict = Depends(get_current_user),
    x_org_id: Optional[int] = Header(None, alias="X-Org-Id"),
) -> int:
    """Empresa (organizacao) ativa da requisicao. O frontend manda o header
    'X-Org-Id'; validamos que o usuario tem acesso a ela. Levanta 403 se o
    usuario nao tiver acesso aquela empresa (ou nenhuma). Centraliza a
    checagem de isolamento entre empresas -- todo endpoint de controle
    depende disto.

    Sem o header, so' cai na primeira empresa do usuario em LEITURA, e ainda
    assim so' quando ele tem uma empresa so' (nao ha' o que escolher errado).
    Em escrita, ou com varias empresas, devolve 400 em vez de adivinhar:
    esse chute silencioso gravava tarefa e notificacao na primeira empresa
    da lista (a Alfa) quando o header nao chegava."""
    from ..db.service import listar_organizacoes_do_usuario, usuario_tem_acesso_org
    username = current_user["sub"]
    if x_org_id is not None:
        if not usuario_tem_acesso_org(username, x_org_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem acesso a esta empresa")
        return x_org_id

    orgs = listar_organizacoes_do_usuario(username)
    if not orgs:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario sem empresa vinculada")
    if len(orgs) == 1 and request.method not in _METODOS_ESCRITA:
        return orgs[0]["id"]
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Empresa nao informada na requisicao (X-Org-Id). Recarregue a pagina e selecione a empresa.",
    )



def get_papel_ativo(
    current_user: Dict = Depends(get_current_user),
    org_id: int = Depends(get_active_org),
) -> str:
    """Papel do usuario na empresa ativa: 'admin' | 'membro' | 'visitante'.
    Operador Global (is_admin=True) e' tratado como 'admin' em qualquer
    empresa, mesmo sem vinculo explicito em usuario_organizacoes."""
    if current_user.get("is_admin"):
        return "admin"
    from ..db.service import get_papel_usuario_org
    return get_papel_usuario_org(current_user["sub"], org_id) or "membro"


def require_org_admin(
    current_user: Dict = Depends(get_current_user),
    papel: str = Depends(get_papel_ativo),
) -> Dict:
    """Admin DA EMPRESA ATIVA (ou Operador Global). Ao contrario de
    require_admin (global, mexe em qualquer empresa), este so' libera quem
    administra especificamente a organizacao da requisicao atual."""
    if papel != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito ao admin desta empresa")
    return current_user
