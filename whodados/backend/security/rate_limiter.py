"""Rate Limiter Middleware - WhoDados.

Limitacao de requisicoes por IP e por usuario autenticado.
Implementacao em memoria com cleanup periodico.
Para producao no Supabase, considere usar Redis.
"""
from __future__ import annotations
import time
import threading
from typing import Dict, Tuple, Optional
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
try:
    from ..config import settings
except ImportError:
    import os
    class _S:
        RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
        RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
        RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    settings = _S()

_redis_fallback = False

try:
    import redis
    _redis_client = redis.Redis.from_url(
        os.getenv("REDIS_URL", ""),
        decode_responses=True
    ) if os.getenv("REDIS_URL") else None
except Exception:
    _redis_client = None

if not _redis_client:
    _redis_fallback = True
    _store: Dict[str, list] = defaultdict(list)
    _lock = threading.Lock()
    _last_cleanup = time.time()

    def _cleanup():
        global _last_cleanup
        now = time.time()
        if now - _last_cleanup < 60:
            return
        with _lock:
            _last_cleanup = now
            cutoff = now - settings.RATE_LIMIT_WINDOW_SECONDS * 2
            for key in list(_store.keys()):
                _store[key] = [t for t in _store[key] if t > cutoff]
                if not _store[key]:
                    del _store[key]

    def _check_inmemory(key: str, limit: int, window: int) -> Tuple[bool, int]:
        _cleanup()
        now = time.time()
        with _lock:
            times = _store[key]
            cutoff = now - window
            times = [t for t in times if t > cutoff]
            _store[key] = times
            remaining = max(0, limit - len(times))
            if len(times) >= limit:
                return False, remaining
            times.append(now)
            return True, remaining

    def _get_inmemory(key: str, limit: int, window: int) -> Tuple[bool, int]:
        _cleanup()
        now = time.time()
        with _lock:
            times = _store.get(key, [])
            cutoff = now - window
            times = [t for t in times if t > cutoff]
            remaining = max(0, limit - len(times))
            return len(times) < limit, remaining


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Middleware de rate limiting por IP.

    Limita requisicoes simultaneas por IP de origem.
    Usa Redis se configurado, caso contrario usa store em memoria.
    """

    # Rotas isentas de rate limiting
    EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/"}

    # Rotas mais liberais (leituras)
    GENEROUS_PATHS = {
        "/api/v1/empresas": 120,
        "/api/v1/crm": 60,
        "/api/v1/dashboard": 60,
    }

    # Limite padrao
    DEFAULT_LIMIT = settings.RATE_LIMIT_REQUESTS
    WINDOW = settings.RATE_LIMIT_WINDOW_SECONDS

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        if request.client:
            return request.client.host
        return "unknown"

    def _check_redis(self, key: str, limit: int, window: int) -> Tuple[bool, int]:
        pipe = _redis_client.pipeline()
        now = time.time()
        window_key = f"rl:{key}"
        pipe.zremrangebyscore(window_key, 0, now - window)
        pipe.zcard(window_key)
        pipe.zadd(window_key, {str(now): now})
        pipe.expire(window_key, window + 1)
        results = pipe.execute()
        count = results[1]
        remaining = max(0, limit - count - 1)
        return count < limit, remaining

    def _get_limit_for_path(self, path: str) -> int:
        for prefix, limit in self.GENEROUS_PATHS.items():
            if path.startswith(prefix):
                return limit
        return self.DEFAULT_LIMIT

    async def dispatch(self, request: Request, call_next):
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        ip = self._get_client_ip(request)
        key = f"ip:{ip}"
        limit = self._get_limit_for_path(request.url.path)
        window = self.WINDOW

        if _redis_client:
            allowed, remaining = self._check_redis(key, limit, window)
        else:
            allowed, remaining = _check_inmemory(key, limit, window)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Muitas requisicoes. Tente novamente em alguns minutos.",
                    "error": "rate_limit_exceeded",
                    "retry_after": window,
                },
                headers={
                    "Retry-After": str(window),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                }
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
