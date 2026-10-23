"""WhoDados API Endpoints - Empresas (dados da Receita Federal) e metricas do dashboard.

A base de leads e' COMPARTILHADA entre as empresas (nao e' escopada por org) -- o
funil de filtros roda no servidor (server-side), entao o app trabalha a base
inteira sem baixar tudo para o navegador."""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from .auth import get_current_user, get_active_org, get_papel_ativo
try:
    from .security import log_access, AuditAction
    HAS_AUDIT = True
except ImportError:
    HAS_AUDIT = False
from .db import (
    org_escopo_base, contar_carteira_db,
    get_crm_by_cnpj,
    listar_empresas_db, contar_empresas_db, get_empresa_by_cnpj_db, get_metricas_db,
    salvar_filtro_empresas, obter_filtro_empresas, apagar_filtro_empresas,
)

router = APIRouter(prefix="/api/v1")


def _faixa_valor(v: Any) -> float:
    """Bucket determinístico pra visitante -- nunca o valor exato, mas
    ainda um numero (o frontend formata como moeda direto, sem saber que
    e' visitante)."""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    if v <= 0:
        return 0.0
    if v < 100_000:
        return 50_000.0
    if v < 500_000:
        return 300_000.0
    if v < 1_000_000:
        return 750_000.0
    return 1_500_000.0


def _mascarar_empresa(e: Dict) -> Dict:
    """Visitante ve a empresa (razao social, municipio, CNAE, potencial),
    mas nao o dado de contato nem os valores financeiros exatos -- pensado
    pra dar acesso a alguem de fora (ex.: recrutador) sem expor cliente
    real."""
    e = dict(e)
    cnpj = e.get("cnpj_completo") or ""
    if len(cnpj) > 8:
        e["cnpj_completo"] = cnpj[:8] + "*" * (len(cnpj) - 8)
    if "email" in e:
        e["email"] = None
    if "contato_fone" in e:
        e["contato_fone"] = None
    if "capital_social" in e:
        e["capital_social"] = _faixa_valor(e.get("capital_social"))
    if "divida_total" in e:
        e["divida_total"] = _faixa_valor(e.get("divida_total"))
    e["_visitante"] = True
    return e


@router.get("/empresas")
async def listar_empresas(
    cidade: Optional[List[str]] = Query(None),
    cnae: Optional[List[str]] = Query(None),
    porte: Optional[List[str]] = Query(None),
    busca: Optional[str] = None,
    divida_min: Optional[float] = None,
    divida_max: Optional[float] = None,
    capital_min: Optional[float] = None,
    capital_max: Optional[float] = None,
    fundacao_de: Optional[str] = None,
    fundacao_ate: Optional[str] = None,
    incluir_inativas: bool = False,
    potencial: Optional[List[str]] = Query(None),
    ordenar_por: str = "razao_social",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100000),
    current_user: Dict = Depends(get_current_user),
    papel: str = Depends(get_papel_ativo),
    org_id: int = Depends(get_active_org),
):
    """Uma pagina de empresas para o filtro atual (funil server-side).

    organizacao_id NAO e' opcional aqui: e' o que decide se a listagem sai da
    base da Receita ou da carteira propria da empresa. Sem ele, toda empresa
    cairia na base publica."""
    empresas = listar_empresas_db(
        cidade=cidade, cnae=cnae, porte=porte, busca=busca,
        divida_min=divida_min, divida_max=divida_max,
        capital_min=capital_min, capital_max=capital_max,
        fundacao_de=fundacao_de, fundacao_ate=fundacao_ate,
        incluir_inativas=incluir_inativas, potencial=potencial,
        ordenar_por=ordenar_por, limit=limit, offset=offset,
        organizacao_id=org_id,
    )
    if papel == "visitante":
        empresas = [_mascarar_empresa(e) for e in empresas]
    return empresas


@router.get("/empresas/count")
async def contar_empresas(
    cidade: Optional[List[str]] = Query(None),
    cnae: Optional[List[str]] = Query(None),
    porte: Optional[List[str]] = Query(None),
    busca: Optional[str] = None,
    divida_min: Optional[float] = None,
    divida_max: Optional[float] = None,
    capital_min: Optional[float] = None,
    capital_max: Optional[float] = None,
    fundacao_de: Optional[str] = None,
    fundacao_ate: Optional[str] = None,
    incluir_inativas: bool = False,
    potencial: Optional[List[str]] = Query(None),
    current_user: Dict = Depends(get_current_user),
    org_id: int = Depends(get_active_org),
):
    """Quantas empresas batem no filtro atual (para o contador do funil)."""
    total = contar_empresas_db(
        organizacao_id=org_id,
        cidade=cidade, cnae=cnae, porte=porte, busca=busca,
        divida_min=divida_min, divida_max=divida_max,
        capital_min=capital_min, capital_max=capital_max,
        fundacao_de=fundacao_de, fundacao_ate=fundacao_ate,
        incluir_inativas=incluir_inativas, potencial=potencial,
    )
    return {"total": total}


@router.get("/empresas/{cnpj}")
async def get_empresa(
    request: Request, cnpj: str, current_user: Dict = Depends(get_current_user),
    org_id: int = Depends(get_active_org), papel: str = Depends(get_papel_ativo),
):
    empresa = get_empresa_by_cnpj_db(cnpj, organizacao_id=org_id)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa nao encontrada")
    if papel == "visitante":
        # Sem CRM: notas/motivo de descarte sao informacao interna de
        # negocio, nao dado publico da empresa -- visitante nao ve.
        empresa = _mascarar_empresa(empresa)
        empresa["crm"] = None
        return empresa
    crm = get_crm_by_cnpj(cnpj, org_id)
    empresa["crm"] = crm
    if HAS_AUDIT:
        log_access(request, AuditAction.EMPRESA_VIEW, user=current_user.get("sub"), resource_type="empresa", resource_id=cnpj)
    return empresa


@router.get("/dashboard/metricas")
async def metricas(
    current_user: Dict = Depends(get_current_user),
    org_id: int = Depends(get_active_org),
):
    # Empresa que prospecta sobre carteira propria nao tem numero da Receita
    # pra mostrar -- o painel dela se apoia na carteira, nao na base publica.
    if org_escopo_base(org_id) == "carteira":
        return {"escopo_base": "carteira", "total_empresas": contar_carteira_db(org_id)}
    return get_metricas_db()


@router.post("/empresas/{cnpj}/enviar-email")
async def enviar_email_para_empresa(
    cnpj: str, data: Dict,
    current_user: Dict = Depends(get_current_user),
    org_id: int = Depends(get_active_org),
) -> Dict[str, Any]:
    """Envia UM e-mail para UMA empresa, fora de campanha.

    Passa pela mesma montagem das campanhas (assinatura, rodape de
    descadastro, rastreamento) e respeita opt-out, entao o envio avulso nao
    e' um caminho paralelo sem as regras do negocio.
    """
    from .db import create_email_enviado, update_email_enviado, get_template, email_esta_descadastrado
    from .mailer import montar_email_para_cnpj, enviar_email
    from .mailer.rastreamento import injetar as injetar_rastreamento
    from .mailer.service import _smtp_efetivo

    template_id = data.get("template_id")
    if not template_id:
        raise HTTPException(status_code=400, detail="Escolha um template")

    empresa = get_empresa_by_cnpj_db(cnpj, organizacao_id=org_id)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa nao encontrada")

    destino = (data.get("email") or empresa.get("email") or "").strip()
    if not destino or "@" not in destino:
        raise HTTPException(status_code=400, detail="Esta empresa nao tem e-mail cadastrado")
    if email_esta_descadastrado(destino):
        raise HTTPException(status_code=400, detail="Este endereco pediu descadastro (LGPD)")

    template = get_template(int(template_id), organizacao_id=org_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template nao encontrado")

    remetente = current_user.get("sub")
    montado = montar_email_para_cnpj(template, cnpj, destino, empresa, org_id, remetente)

    registro = create_email_enviado(None, cnpj, destino, montado["assunto"])
    email_id = registro.get("id") if registro else None
    corpo = injetar_rastreamento(montado["corpo_html"], email_id)

    r = enviar_email(destino, montado["assunto"], corpo, montado["corpo_texto"],
                     smtp=_smtp_efetivo(org_id, remetente),
                     unsubscribe_url=montado.get("unsubscribe_url") or None)
    if email_id:
        update_email_enviado(email_id, "enviado" if r.get("sucesso") else "erro",
                             erro=r.get("erro"), message_id=r.get("message_id"))
    if not r.get("sucesso"):
        raise HTTPException(status_code=502, detail=r.get("erro") or "Falha no envio")
    return {"ok": True, "para": destino, "assunto": montado["assunto"],
            "simulado": bool(r.get("simulado"))}


# Filtro fixado do painel (ponto de retorno)

class FiltroSalvoBody(BaseModel):
    """Filtros do painel como o frontend os monta. Dict solto de proposito:
    o painel ganha criterio novo com frequencia e nao vale versionar um
    schema aqui a cada um -- quem le de volta ignora chave que nao conhece."""
    filtros: Dict[str, Any] = Field(default_factory=dict)


@router.get("/empresas/filtro-salvo")
async def ler_filtro_salvo(current_user: Dict = Depends(get_current_user),
                           org_id: int = Depends(get_active_org)):
    """Pesquisa fixada da pessoa nesta empresa. 'filtros' vem null quando
    nunca salvou -- a tela cai no cache local do navegador nesse caso."""
    reg = obter_filtro_empresas(current_user["sub"], org_id)
    if not reg:
        return {"filtros": None, "atualizado_em": None}
    return {
        "filtros": reg.get("filtros") or {},
        "atualizado_em": reg["atualizado_em"].isoformat() if reg.get("atualizado_em") else None,
    }


@router.put("/empresas/filtro-salvo")
async def gravar_filtro_salvo(body: FiltroSalvoBody,
                              current_user: Dict = Depends(get_current_user),
                              org_id: int = Depends(get_active_org)):
    """Fixa a pesquisa atual, sobrescrevendo a anterior (um slot so')."""
    reg = salvar_filtro_empresas(current_user["sub"], org_id, body.filtros)
    return {
        "filtros": reg.get("filtros") or {},
        "atualizado_em": reg["atualizado_em"].isoformat() if reg.get("atualizado_em") else None,
    }


@router.delete("/empresas/filtro-salvo")
async def remover_filtro_salvo(current_user: Dict = Depends(get_current_user),
                               org_id: int = Depends(get_active_org)):
    """Solta o ponto de retorno."""
    return {"removido": apagar_filtro_empresas(current_user["sub"], org_id)}
