"""Guarda de regressao do isolamento multi-tenant.

O maior risco do multi-tenant e' esquecer o filtro por empresa em alguma funcao
de controle -- o que faria a Alfa enxergar dados da Beta. Estes testes falham se
alguem remover o parametro organizacao_id de uma funcao de controle, ou a
dependencia get_active_org de um endpoint de controle.
"""
import inspect
from backend.db import service

# Funcoes de CONTROLE (isoladas por empresa) -- todas devem aceitar organizacao_id.
FUNCS_CONTROLE = [
    "get_crm_by_cnpj", "get_crm_all", "create_or_update_crm",
    "get_all_templates", "create_template", "get_template",
    "get_templates_by_categoria", "delete_template",
    "get_all_campanhas", "create_campanha", "get_campanha",
    "get_notificacoes", "create_notificacao",
    "get_emails_for_monitor", "get_monitor_stats", "get_emails_vermelhos_para_followup",
]


def test_funcoes_de_controle_recebem_organizacao_id():
    for nome in FUNCS_CONTROLE:
        fn = getattr(service, nome)
        params = inspect.signature(fn).parameters
        assert "organizacao_id" in params, f"{nome} perdeu o parametro organizacao_id (risco de vazamento entre empresas)"


def test_endpoints_de_controle_usam_get_active_org():
    """Cada router de controle deve depender de get_active_org em pelo menos
    um handler (o que injeta e valida a empresa ativa)."""
    from backend import endpoints_crm, endpoints_templates, endpoints_campanhas, endpoints_monitor, endpoints_notificacoes
    for mod in (endpoints_crm, endpoints_templates, endpoints_campanhas, endpoints_monitor, endpoints_notificacoes):
        src = inspect.getsource(mod)
        assert "get_active_org" in src, f"{mod.__name__} nao usa get_active_org (empresa ativa)"
