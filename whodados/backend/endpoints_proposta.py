"""WhoDados API Endpoints - Propostas comerciais, uma por empresa.

Cada empresa tem as propostas dela e o desenho dela: as cores, a fonte e o
selo vem de `get_identidade(org)`, nao de HTML copiado de um modelo antigo.
A mesma proposta sai no marinho da Alfa ou no preto e verde da Beta sem
ninguem mexer em nada.

A geracao por IA e' OPCIONAL (`/proposta/gerar`): sem ANTHROPIC_API_KEY o
endpoint devolve 503 com a explicacao, e o resto da aba continua servindo --
da' para escrever a proposta a mao e o sistema formata, guarda e envia.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from .auth import get_current_user, get_active_org
from .db import (
    criar_proposta, listar_propostas, get_proposta, atualizar_proposta,
    deletar_proposta, STATUS_PROPOSTA, get_identidade,
)
from .agents import proposta_service
from .logger import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1")


def _html(conteudo: Dict[str, Any], org_id: int) -> str:
    return proposta_service.montar_html(conteudo, get_identidade(org_id))


@router.get("/proposta/campos")
async def proposta_campos(current_user: Dict = Depends(get_current_user)):
    """O que o formulario pergunta. Vem do backend para a tela e a geracao
    nunca sairem de sincronia."""
    return [{"chave": c, "rotulo": r} for c, r in proposta_service.CAMPOS]


@router.get("/propostas")
async def propostas_listar(current_user: Dict = Depends(get_current_user),
                           org_id: int = Depends(get_active_org)):
    return listar_propostas(org_id)


@router.get("/propostas/{proposta_id}")
async def proposta_abrir(proposta_id: int, current_user: Dict = Depends(get_current_user),
                         org_id: int = Depends(get_active_org)):
    p = get_proposta(proposta_id, org_id)
    if not p:
        raise HTTPException(status_code=404, detail="Proposta nao encontrada")
    linha = dict(p)
    linha["html"] = _html(linha.get("conteudo") or {}, org_id)
    linha["texto"] = proposta_service.montar_texto(linha.get("conteudo") or {})
    return linha


@router.post("/proposta/gerar")
async def proposta_gerar(data: Dict, current_user: Dict = Depends(get_current_user),
                         org_id: int = Depends(get_active_org)):
    """Transforma o formulario em proposta. Nao grava nada -- quem salva e' o
    POST /propostas, depois de a pessoa ler e ajustar."""
    try:
        conteudo = proposta_service.gerar(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        # Sem chave ou sem o pacote: a aba continua util sem a IA.
        log.warning(f"Geracao de proposta indisponivel: {e}")
        raise HTTPException(
            status_code=503,
            detail="A geracao automatica nao esta disponivel neste servidor. "
                   "Da' para escrever a proposta a mao que o sistema formata e guarda.")
    return {
        "conteudo": conteudo,
        "html": _html(conteudo, org_id),
        "texto": proposta_service.montar_texto(conteudo),
    }


@router.post("/proposta/previa")
async def proposta_previa(data: Dict, current_user: Dict = Depends(get_current_user),
                          org_id: int = Depends(get_active_org)):
    """Mostra como fica, sem IA e sem gravar -- e' o caminho de quem escreve
    a proposta a mao."""
    conteudo = data.get("conteudo") or {}
    return {"html": _html(conteudo, org_id),
            "texto": proposta_service.montar_texto(conteudo)}


@router.post("/propostas")
async def proposta_salvar(data: Dict, current_user: Dict = Depends(get_current_user),
                          org_id: int = Depends(get_active_org)):
    cliente = (data.get("cliente") or "").strip()
    if not cliente:
        raise HTTPException(status_code=400, detail="Diga para quem e' a proposta")
    conteudo = data.get("conteudo") or {}
    return criar_proposta(
        org_id, cliente, data.get("titulo") or conteudo.get("titulo"),
        data.get("campos") or {}, conteudo, criado_por=current_user.get("sub"),
    )


@router.put("/propostas/{proposta_id}")
async def proposta_atualizar(proposta_id: int, data: Dict,
                             current_user: Dict = Depends(get_current_user),
                             org_id: int = Depends(get_active_org)):
    status = data.get("status")
    if status is not None and status not in STATUS_PROPOSTA:
        raise HTTPException(status_code=400,
                            detail=f"Status invalido. Use um de: {', '.join(STATUS_PROPOSTA)}")
    p = atualizar_proposta(proposta_id, org_id, cliente=data.get("cliente"),
                           titulo=data.get("titulo"), status=status,
                           campos=data.get("campos"), conteudo=data.get("conteudo"))
    if not p:
        raise HTTPException(status_code=404, detail="Proposta nao encontrada")
    return p


@router.delete("/propostas/{proposta_id}")
async def proposta_remover(proposta_id: int, current_user: Dict = Depends(get_current_user),
                           org_id: int = Depends(get_active_org)):
    if not deletar_proposta(proposta_id, org_id):
        raise HTTPException(status_code=404, detail="Proposta nao encontrada")
    return {"ok": True}


@router.get("/proposta/identidade")
async def proposta_identidade(current_user: Dict = Depends(get_current_user),
                              org_id: int = Depends(get_active_org)):
    """Cores, fonte e selo da empresa ativa -- a tela usa para o preview."""
    return get_identidade(org_id)
