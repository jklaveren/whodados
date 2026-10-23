"""Middleware do papel 'visitante' -- nega tudo por padrao, libera so' o que
esta na allowlist. Pensado pra dar acesso a alguem de fora (ex.: recrutador
avaliando o produto numa entrevista) sem expor dado real de cliente nem
telas de trabalho (CRM, campanhas, WhatsApp, configuracoes).

Design: "default deny" em vez de ir bloqueando tela por tela -- com o app
crescendo endpoint novo toda hora, uma lista de bloqueio ia inevitavelmente
esquecer alguma rota nova e vazar dado. Allowlist inverte o risco: uma rota
nova fica bloqueada pro visitante ate alguem decidir liberar explicitamente.
"""
from __future__ import annotations
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Prefixos de rota que um visitante pode acessar (sempre GET -- nenhum
# POST/PUT/PATCH/DELETE e' liberado pra esse papel, nem dentro da allowlist).
_PERMITIDO_VISITANTE = (
    "/api/v1/empresas",
    "/api/v1/analytics",
    "/api/v1/nlp",
    "/api/v1/dashboard",
    "/api/v1/organizacoes",
    "/api/v1/auth/me",
)
_SEMPRE_PERMITIDO = ("/health", "/docs", "/openapi.json", "/redoc", "/api/v1/auth/login")


class VisitanteMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in _SEMPRE_PERMITIDO or not path.startswith("/api/v1"):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return await call_next(request)  # sem token: deixa as dependencias normais barrarem com 401

        token = auth_header[7:]
        try:
            from ..auth.service import decodificar_access_token
            payload = decodificar_access_token(token)
        except Exception:
            payload = None
        if not payload or payload.get("is_admin"):
            return await call_next(request)  # token invalido (401 adiante) ou Operador Global

        try:
            from ..db.service import get_papel_usuario_org, listar_organizacoes_do_usuario
            org_id = request.headers.get("X-Org-Id")
            username = payload.get("sub")
            if org_id:
                papel = get_papel_usuario_org(username, int(org_id))
            else:
                orgs = listar_organizacoes_do_usuario(username)
                papel = orgs[0]["papel"] if orgs else None
        except Exception:
            papel = None  # DB fora do ar: nao bloqueia por causa disso, endpoint real vai lidar

        if papel != "visitante":
            return await call_next(request)

        if request.method != "GET" or not path.startswith(_PERMITIDO_VISITANTE):
            return JSONResponse(
                status_code=403,
                content={"detail": "Acesso de visitante e' restrito a leitura de Empresas/dashboard."},
            )
        return await call_next(request)
