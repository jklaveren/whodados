"""Mailer Module."""
from .service import enviar_email, enviar_campanha, enviar_template_para_cnpjs, enviar_email_teste, notificar_tarefa_por_email, montar_email_para_cnpj
from .templates import TEMPLATES_PADRAO
from .validacao import validar_lote
from .smtp_config import (
    get_smtp_config, test_smtp_connection, test_email_send,
    get_smtp_presets, SMTP_PRESETS
)
__all__ = [
    "enviar_email", "enviar_campanha", "enviar_template_para_cnpjs", "enviar_email_teste", "notificar_tarefa_por_email", "montar_email_para_cnpj",
    "TEMPLATES_PADRAO", "validar_lote",
    "get_smtp_config", "test_smtp_connection", "test_email_send",
    "get_smtp_presets", "SMTP_PRESETS",
]
