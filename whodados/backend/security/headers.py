"""Security Headers Middleware - WhoDados.

Adiciona headers de seguranca padrao em todas as respostas:
- HSTS, CSP, X-Frame-Options, X-Content-Type-Options, etc.
"""
from __future__ import annotations
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
try:
    from ..config import settings
except ImportError:
    import os
    class _S:
        APP_ENV = os.getenv("APP_ENV", "development")
    settings = _S()

# Politica de Content Security Policy
CSP_DIRECTIVE = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self'; "
    "connect-src 'self' https://*; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self';"
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": CSP_DIRECTIVE,
    # Remove header que revela tecnologia
    "Server": "WhoDados",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security headers em todas as respostas."""

    EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Não adiciona headers em caminhos isentos
        if request.url.path in self.EXEMPT_PATHS:
            return response

        for header, value in SECURITY_HEADERS.items():
            # HSTS apenas em producao
            if header == "Strict-Transport-Security" and settings.APP_ENV != "production":
                continue
            response.headers[header] = value

        # HSTS em producao
        if settings.APP_ENV == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        return response
