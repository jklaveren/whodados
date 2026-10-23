"""Web Push (PWA) -- dispara avisos no celular/navegador via VAPID.

Sem FCM/APNs e sem conta em provedor: o padrao Web Push fala direto com
o push service do navegador (Mozilla/Google/Apple). A privada VAPID fica
so no servidor (Render env VAPID_PRIVATE_KEY); a publica vai pro
frontend via GET /push/vapid-public-key.
"""
from __future__ import annotations
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

try:
    from .config import settings
except ImportError:  # execucao fora do pacote
    from backend.config import settings
try:
    from .logger import get_logger
except ImportError:  # pragma: no cover
    import logging
    get_logger = lambda x: logging.getLogger(x)  # noqa: E731

log = get_logger(__name__)


def gerar_vapid() -> Dict[str, str]:
    """Gera um par VAPID novo. Rode uma vez e guarde: a privada no Render
    (VAPID_PRIVATE_KEY), a publica no Render (VAPID_PUBLIC_KEY)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    chave = ec.generate_private_key(ec.SECP256R1())
    numeros = chave.private_numbers()
    privada = numeros.private_value.to_bytes(32, "big")
    publica = chave.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return {"public": b64(publica), "private": b64(privada)}


def push_configurado() -> bool:
    return bool(settings.push_enabled)


def enviar_push(subscription: Dict[str, Any], titulo: str, corpo: str = "",
                url: str = "/dashboard/notificacoes") -> bool:
    """Envia um push para UMA inscricao. Retorna False se a inscricao
    expirou (o chamador deve remove-la) ou se o push nao esta configurado."""
    if not push_configurado():
        return False
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        log.error("pywebpush nao instalado -- push desligado")
        return False
    info = {
        "endpoint": subscription["endpoint"],
        "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
    }
    payload = json.dumps({"title": titulo, "body": corpo or "", "url": url})
    try:
        webpush(
            subscription_info=info,
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_SUBJECT},
            timeout=15,
        )
        return True
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (404, 410):
            log.info(f"push expirado (HTTP {status}), removendo inscricao")
            try:
                from .db import remover_push_subscription
            except ImportError:
                from backend.db import remover_push_subscription
            remover_push_subscription(subscription["endpoint"])
        else:
            log.warning(f"falha ao enviar push: {type(e).__name__}: {e}")
        return False


def disparar_push(subscriptions: List[Dict[str, Any]], titulo: str, corpo: str = "",
                  url: str = "/dashboard/notificacoes",
                  max_workers: int = 10) -> Dict[str, int]:
    """Fan-out paralelo (a base de usuarios e pequena; 10 workers bastam e
    nao estouram o pool do banco, que nem e usado aqui)."""
    enviados = falhos = 0
    if not subscriptions:
        return {"enviados": 0, "falhos": 0}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        resultados = list(pool.map(
            lambda s: enviar_push(s, titulo, corpo, url), subscriptions
        ))
    for ok in resultados:
        enviados += 1 if ok else 0
        falhos += 0 if ok else 1
    return {"enviados": enviados, "falhos": falhos}
