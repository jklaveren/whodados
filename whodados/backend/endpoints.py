"""Agrega todos os routers da API WhoDados num unico router.

Cada dominio vive em seu proprio arquivo endpoints_<dominio>.py; aqui eles
sao apenas montados na ordem. Todos usam o mesmo prefixo /api/v1 (exceto os
que definem o proprio prefixo, como admin e analytics)."""
from fastapi import APIRouter
from .endpoints_auth import router as auth_router
from .endpoints_organizacoes import router as organizacoes_router
from .endpoints_empresas import router as empresas_router
from .endpoints_painel import router as painel_router
from .endpoints_crm import router as crm_router
from .endpoints_templates import router as templates_router
from .endpoints_campanhas import router as campanhas_router
from .endpoints_notificacoes import router as notificacoes_router
from .endpoints_monitor import router as monitor_router
from .endpoints_admin import router as admin_router
from .endpoints_gastos import router as gastos_router
from .endpoints_carteira import router as carteira_router
from .endpoints_proposta import router as proposta_router
from .endpoints_nlp import router as nlp_router
from .endpoints_enriquecimento import router as enriquecimento_router
from .endpoints_analytics import router as analytics_router
from .endpoints_descadastro import router as descadastro_router
from .endpoints_lotes import router as lotes_router
from .endpoints_push import router as push_router
from .endpoints_tracking import router as tracking_router
from .endpoints_envios import router as envios_router
from .endpoints_gmail import router as gmail_router
from .endpoints_disparo import router as disparo_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(organizacoes_router)
router.include_router(empresas_router)
router.include_router(painel_router)
router.include_router(crm_router)
router.include_router(templates_router)
router.include_router(campanhas_router)
router.include_router(notificacoes_router)
router.include_router(monitor_router)
router.include_router(admin_router)
router.include_router(gastos_router)
router.include_router(carteira_router)
router.include_router(proposta_router)
router.include_router(nlp_router)
router.include_router(enriquecimento_router)
router.include_router(analytics_router)
router.include_router(descadastro_router)
router.include_router(lotes_router)
router.include_router(push_router)
router.include_router(tracking_router)
router.include_router(envios_router)
router.include_router(gmail_router)
router.include_router(disparo_router)
