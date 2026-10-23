"""Config module - WhoDados 2.0."""
import os
from functools import lru_cache
from pathlib import Path
from typing import List

# Carrega variaveis de um .env local (desenvolvimento). Em produção (Render/Vercel)
# as variaveis ja vem setadas de verdade pela plataforma, entao isso e um no-op seguro:
# se nao houver .env, load_dotenv simplesmente nao encontra nada e segue.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

class Settings:
    APP_NAME = os.getenv("APP_NAME", "WhoDados API")
    APP_VERSION = os.getenv("APP_VERSION", "2.0.0")
    APP_ENV = os.getenv("APP_ENV", "development")
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
    DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-use-strong-secret")
    ALGORITHM = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
    BCRYPT_ROUNDS = int(os.getenv("BCRYPT_ROUNDS", "12"))
    REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
    RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
    RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
    RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    LOGIN_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
    LOGIN_LOCKOUT_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15"))
    AUDIT_ENABLED = os.getenv("AUDIT_ENABLED", "true").lower() == "true"
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "300"))
    DATA_SOURCE = os.getenv("DATA_SOURCE", "database")
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    EMAIL_FROM = os.getenv("EMAIL_FROM", "noreply@whodados.com")
    EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "WhoDados")
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
    # URL publica desta API (usada para montar a URL da imagem/card do template nos emails)
    API_PUBLIC_URL = os.getenv("API_PUBLIC_URL", "http://localhost:8000")
    PASSWORD_RESET_EXPIRE_MINUTES = int(os.getenv("PASSWORD_RESET_EXPIRE_MINUTES", "60"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = os.getenv("LOG_FORMAT", "text")
    # Segredo compartilhado com o cron externo (GitHub Actions) que avanca
    # os lotes diarios de campanha -- sem isso definido, o endpoint de cron
    # fica desligado (nunca aceita chamada sem o header certo).
    CRON_SECRET = os.getenv("CRON_SECRET", "")
    # Teto de e-mails por dia: politica nossa, nao limite do provedor. A
    # Gmail API da' 500/dia (2000 no Workspace), entao da' pra subir --
    # revisar antes de assumir que 300 e' um teto tecnico. (contados na
    # conta inteira). O cron corta o lote no que ainda cabe hoje; 0 desliga
    # a checagem.
    EMAIL_LIMITE_DIARIO = int(os.getenv("EMAIL_LIMITE_DIARIO", "300"))
    # Ritmo de envio. Disparar o lote inteiro de uma vez tem cara de robo e
    # e' o que faz provedor limitar a conta: manda-se pouco, varias vezes,
    # so' em horario comercial.
    ENVIO_POR_RODADA = int(os.getenv("ENVIO_POR_RODADA", "10"))
    ENVIO_JANELA_INICIO = os.getenv("ENVIO_JANELA_INICIO", "07:00")
    ENVIO_JANELA_FIM = os.getenv("ENVIO_JANELA_FIM", "19:30")
    ENVIO_TIMEZONE = os.getenv("ENVIO_TIMEZONE", "America/Sao_Paulo")
    # 1=segunda ... 7=domingo (ISO). Padrao: dias uteis.
    ENVIO_DIAS_SEMANA = os.getenv("ENVIO_DIAS_SEMANA", "1,2,3,4,5")
    # Vazio = webhook desligado, devolve 403.
    # Web Push (PWA): par de chaves VAPID. A publica vai pro frontend via
    # GET /push/vapid-public-key; a privada NUNCA sai do servidor (Render env).
    # Gerar com: python -c "from backend.push import gerar_vapid; print(gerar_vapid())"
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:contato@whodados.com")

    @property
    def push_enabled(self) -> bool:
        return bool(self.VAPID_PUBLIC_KEY and self.VAPID_PRIVATE_KEY)

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

@lru_cache(maxsize=1)
def get_settings():
    return Settings()

settings = get_settings()