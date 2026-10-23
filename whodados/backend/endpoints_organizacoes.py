"""WhoDados API Endpoints - Organizacoes (empresas do usuario).

Multi-tenant: cada usuario opera uma ou mais empresas (Alfa / Beta). Este
endpoint alimenta o seletor de empresa ativa no frontend. O isolamento em si
(qual empresa cada request opera) e' feito pela dependencia get_active_org via
header X-Org-Id."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from typing import Dict, List, Any
from .auth import get_current_user
from .db import (
    listar_organizacoes_do_usuario, get_org_logo,
    get_usuario_smtp_config, set_usuario_smtp_config, get_org_smtp_config,
)
from .auth import get_active_org

router = APIRouter(prefix="/api/v1")


@router.get("/organizacoes")
async def minhas_organizacoes(current_user: Dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Lista as empresas que o usuario logado pode operar."""
    return listar_organizacoes_do_usuario(current_user["sub"])


# E-mail individual: o remetente e' da pessoa, nao da empresa

@router.get("/meu-email")
async def meu_email(current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    """Config de e-mail do usuario logado nesta empresa, e o que a empresa
    oferece como padrao -- a tela mostra os dois pra ficar claro o que a
    pessoa esta' sobrescrevendo e o que esta' herdando."""
    meu = get_usuario_smtp_config(current_user["sub"], org_id) or {}
    empresa = get_org_smtp_config(org_id) or {}
    return {
        "email_from": meu.get("email_from"),
        "email_from_name": meu.get("email_from_name"),
        "assinatura_html": meu.get("assinatura_html"),
        "gmail_conta": meu.get("gmail_conta"),
        "gmail_conectado": bool(meu.get("gmail_conectado")),
        "smtp_host": meu.get("smtp_host"),
        "smtp_port": meu.get("smtp_port"),
        "smtp_username": meu.get("smtp_username"),
        "smtp_use_tls": meu.get("smtp_use_tls"),
        "tem_servidor_proprio": bool(meu.get("smtp_host")),
        "padrao_da_empresa": {
            "email_from": empresa.get("email_from"),
            "email_from_name": empresa.get("email_from_name"),
            "smtp_host": empresa.get("smtp_host"),
            "configurado": bool(empresa.get("configurado")),
        },
    }


@router.put("/meu-email")
async def salvar_meu_email(data: Dict, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    """Salva o e-mail individual. Campo em branco nao apaga -- pra voltar a
    usar o padrao da empresa existe o DELETE."""
    campos = {k: v for k, v in data.items() if k in (
        "smtp_host", "smtp_port", "smtp_username", "smtp_password",
        "smtp_use_tls", "email_from", "email_from_name", "assinatura_html",
    )}
    salvo = set_usuario_smtp_config(current_user["sub"], org_id, **campos)
    if salvo is None:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    return await meu_email(current_user, org_id)


@router.get("/organizacoes/{organizacao_id}/logo")
async def logo_organizacao(organizacao_id: int):
    """Endpoint publico (sem login) -- serve o logo da empresa para ser embutido
    na assinatura do e-mail, carregado pelo cliente de e-mail do destinatario."""
    row = get_org_logo(organizacao_id)
    if not row or not row.get("logo_data"):
        raise HTTPException(status_code=404, detail="Empresa sem logo")
    return Response(content=bytes(row["logo_data"]), media_type=row.get("logo_mime") or "image/png", headers={"Cache-Control": "public, max-age=300"})
