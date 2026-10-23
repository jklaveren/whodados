"""WhoDados Backend 2.0 - FastAPI Entry Point."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import os
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .logger import logger
from .db.config import ensure_tables_exist, check_database_health
from .db import seed_default_templates
from .endpoints import router as api_router


_SECRET_KEY_PADRAO = "change-me-in-production-use-strong-secret"


def secret_key_ok() -> bool:
    """A SECRET_KEY assina os tokens de login. Se ficar na padrao (ou curta),
    os tokens sao forjaveis. Consideramos OK quando foi trocada e tem tamanho
    razoavel."""
    sk = settings.SECRET_KEY or ""
    return sk != _SECRET_KEY_PADRAO and len(sk) >= 32


def _verificar_seguranca() -> None:
    """Alerta (bem visivel) sobre configuracoes de seguranca frageis. NAO derruba
    o app -- so grita no log -- pra nao trancar o acesso caso a env nao esteja
    setada; a Jessica confere no Render pelo /health (secret_key_ok / producao)."""
    if not secret_key_ok():
        logger.error(
            "!!! SEGURANCA: SECRET_KEY esta na padrao ou muito curta -- os tokens de "
            "login sao FORJAVEIS. Defina uma SECRET_KEY forte (>=32 chars) no Render."
        )
    if not settings.is_production:
        logger.warning(
            f"APP_ENV={settings.APP_ENV} (nao-producao). Em producao, defina "
            "APP_ENV=production no Render."
        )


# Relogio proprio da fila de envio. Depender so' do agendador do GitHub deixava
# a fila parada por horas (ele roda 3 vezes por dia, nao a cada 5 minutos).
# Enquanto o servidor esta' de pe', confere a fila a cada INTERVALO segundos;
# o agendador do GitHub e a tela aberta continuam como reforco e como
# despertador para o Render dormindo.
_INTERVALO_RELOGIO_S = 45


async def _relogio_da_fila() -> None:
    from .endpoints_campanhas import avancar_filas
    while True:
        await asyncio.sleep(_INTERVALO_RELOGIO_S)
        try:
            await asyncio.to_thread(avancar_filas)
        except Exception:
            logger.exception("Relogio da fila falhou (segue tentando)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"WhoDados API iniciando v{settings.APP_VERSION}")
    _verificar_seguranca()
    if settings.DATABASE_URL:
        try:
            ensure_tables_exist()
            logger.info("Tabelas verificadas")
            try:
                criados = seed_default_templates()
                if criados:
                    logger.info(f"{criados} templates padrao inseridos")
            except Exception as e:
                logger.error(f"Falha ao popular templates padrao: {e}")
        except Exception as e:
            logger.error(f"Falha ao inicializar banco: {e}")
    relogio = None
    if settings.DATABASE_URL and os.environ.get("RELOGIO_DA_FILA", "1") != "0":
        relogio = asyncio.create_task(_relogio_da_fila())
        logger.info("Relogio da fila ligado (%ss)", _INTERVALO_RELOGIO_S)
    yield
    if relogio:
        relogio.cancel()
    logger.info("WhoDados API encerrando")


app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)

# CORS (outermost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security middlewares (innermost)
try:
    from .security import (SecurityHeadersMiddleware, RateLimiterMiddleware,
                           VisitanteMiddleware, AuditoriaRequestsMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimiterMiddleware)
    app.add_middleware(VisitanteMiddleware)
    # Por ultimo = mais externo: ve o status final da resposta, inclusive
    # o 403 que o VisitanteMiddleware devolve. Auditar so' o que passou
    # pelos outros esconderia justamente a tentativa barrada.
    app.add_middleware(AuditoriaRequestsMiddleware)
    logger.info("Security middlewares loaded")
except ImportError as e:
    logger.warning(f"Security middlewares not available: {e}")

app.include_router(api_router)


def _diagnostico_email():
    """Qual transporte de e-mail esta ativo. Sem isto, falha de envio nao
    distingue credencial ausente de biblioteca faltando."""
    try:
        from .mailer import gmail_api
        return gmail_api.diagnostico()
    except Exception as e:
        return {"ativo": False, "erro": str(e)[:120]}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "versao": settings.APP_VERSION,
        "ambiente": settings.APP_ENV,
        "producao": settings.is_production,
        "secret_key_ok": secret_key_ok(),
        "banco_ok": check_database_health(),
        "email": _diagnostico_email(),
        # Render injeta o commit do build. Sem isto nao da pra saber, de
        # fora, se a versao no ar e a que acabou de subir.
        "commit": (os.environ.get("RENDER_GIT_COMMIT") or "")[:7] or None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/")
async def root():
    return {"msg": f"WhoDados API v{settings.APP_VERSION}", "docs": "/docs"}
