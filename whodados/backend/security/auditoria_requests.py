"""Auditoria automatica de toda requisicao que MUDA alguma coisa.

Design: middleware em vez de chamar log_access endpoint por endpoint. Sao 128
rotas e nascem rotas novas toda semana -- instrumentar na mao garante que
alguem vai esquecer a proxima, e justamente a que importa. E' o mesmo
raciocinio do VisitanteMiddleware (allowlist em vez de blocklist) e a mesma
ideia da regra unica de remetente: regra que vale pra tudo mora num ponto
por onde tudo passa, nao repetida em cada caminho.

O que entra: POST, PUT, PATCH, DELETE. GET fica de fora de proposito -- a tela
de Empresas dispara varias leituras a cada mexida de filtro, e afogar a tabela
em leitura tornaria a auditoria inutil justamente quando alguem precisar
procurar alguma coisa nela. Quem fez, quando, em que empresa e se deu certo
esta' nas escritas, que e' o que muda a vida de alguem.

NUNCA grava corpo de requisicao: por aqui passam senha, chave de API e token.
So' metodo, caminho, status, autor e empresa.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from ..logger import get_logger

log = get_logger(__name__)

_MUTACOES = ("POST", "PUT", "PATCH", "DELETE")

# Login ja' e' auditado por log_login, com o detalhe que importa (tentativa,
# credencial invalida, sucesso). Registrar de novo aqui so' duplicaria linha.
_IGNORADOS = ("/api/v1/auth/login", "/api/v1/auth/refresh")


def _identifica(request: Request) -> tuple[str | None, int | None]:
    """Autor e empresa ativa da requisicao, pelo token. Nunca levanta:
    auditoria que derruba requisicao e' pior que auditoria ausente."""
    usuario = None
    org = None
    try:
        cabecalho = request.headers.get("authorization", "")
        if cabecalho.lower().startswith("bearer "):
            from ..auth.service import decodificar_access_token
            payload = decodificar_access_token(cabecalho[7:])
            if payload:
                usuario = payload.get("sub")
    except Exception:
        pass
    try:
        bruto = request.headers.get("X-Org-Id")
        org = int(bruto) if bruto else None
    except (TypeError, ValueError):
        org = None
    return usuario, org


def _recurso(caminho: str) -> tuple[str, str | None]:
    """Quebra /api/v1/campanhas/12/executar em ("campanhas", "12").

    O id e' o primeiro segmento que parece identificador -- so' digitos, ou
    CNPJ. Sem isso a auditoria responderia "mexeu em campanhas" sem dizer em
    qual, que nao serve pra investigar nada.
    """
    partes = [p for p in caminho.split("/") if p]
    if len(partes) >= 3 and partes[0] == "api":
        partes = partes[2:]
    tipo = partes[0] if partes else "desconhecido"
    ident = None
    for p in partes[1:]:
        limpo = p.replace(".", "").replace("-", "").replace("/", "")
        if limpo.isdigit():
            ident = p
            break
    return tipo, ident


class AuditoriaRequestsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        metodo = request.method.upper()
        caminho = request.url.path
        if metodo not in _MUTACOES or caminho in _IGNORADOS or not caminho.startswith("/api/"):
            return await call_next(request)

        # O try cobre call_next porque o endpoint que ESTOURA e' o que mais
        # interessa numa auditoria. Sem ele a excecao sobe antes da escrita e
        # a requisicao que alguem vai procurar depois e' a unica que falta.
        try:
            resposta = await call_next(request)
        except Exception as erro:
            self._registra(request, metodo, caminho, status=500, detalhe=type(erro).__name__)
            raise
        self._registra(request, metodo, caminho, status=resposta.status_code)
        return resposta

    def _registra(self, request: Request, metodo: str, caminho: str,
                  status: int, detalhe: str | None = None) -> None:
        """Best-effort: falha de auditoria nunca vira erro pra quem chamou."""
        try:
            usuario, org = _identifica(request)
            tipo, ident = _recurso(caminho)
            detalhes = {"status": status, "organizacao_id": org}
            if detalhe:
                detalhes["excecao"] = detalhe
            from ..db.service import create_audit_log
            create_audit_log(
                action=f"{metodo} {caminho}",
                user_id=usuario,
                ip_address=(request.client.host if request.client else None),
                resource_type=tipo,
                resource_id=ident,
                details=detalhes,
                success=status < 400,
            )
        except Exception as e:
            log.warning(f"auditoria da requisicao {metodo} {caminho} falhou: {e}")
