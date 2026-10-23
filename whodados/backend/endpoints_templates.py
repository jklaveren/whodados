"""WhoDados API Endpoints - Templates de e-mail (CRUD + imagem/card).

Isolado por empresa (multi-tenant): cada empresa tem seus proprios templates.
O endpoint publico de imagem (obter_imagem_template) e a excecao -- ele e'
carregado pelo cliente de e-mail do destinatario, sem login nem empresa."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from typing import Dict, Optional
from .auth import get_current_user, get_active_org
from .db import (
    create_template, get_template, get_all_templates,
    update_template, delete_template, get_templates_by_categoria,
    set_template_imagem, get_template_imagem, clear_template_imagem,
    get_empresa_by_cnpj_db, listar_empresas_db, buscar_socios_principais,
)
from .mailer import enviar_email_teste, montar_email_para_cnpj

router = APIRouter(prefix="/api/v1")


@router.get("/templates")
async def listar_templates(categoria: Optional[str] = None, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    if categoria and categoria != "todos":
        return get_templates_by_categoria(categoria, organizacao_id=org_id)
    return get_all_templates(organizacao_id=org_id)


@router.post("/templates")
async def criar_template(data: Dict, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    return create_template(
        data.get("nome"), data.get("assunto"), data.get("corpo_html"),
        data.get("corpo_texto"),
        criado_por=current_user.get("sub"),
        categoria_cnae=data.get("categoria_cnae", "todos"),
        organizacao_id=org_id,
    )


@router.get("/templates/{template_id}")
async def get_template_by_id(template_id: int, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    t = get_template(template_id, organizacao_id=org_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template nao encontrado")
    return t


@router.put("/templates/{template_id}")
async def atualizar_template(template_id: int, data: Dict, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    t = get_template(template_id, organizacao_id=org_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template nao encontrado")
    return update_template(
        template_id,
        nome=data.get("nome"),
        assunto=data.get("assunto"),
        corpo_html=data.get("corpo_html"),
        corpo_texto=data.get("corpo_texto"),
        categoria_cnae=data.get("categoria_cnae"),
        organizacao_id=org_id,
    )


@router.delete("/templates/{template_id}")
async def deletar_template(template_id: int, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    t = get_template(template_id, organizacao_id=org_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template nao encontrado")
    if not delete_template(template_id, organizacao_id=org_id):
        raise HTTPException(status_code=400, detail="Erro ao deletar template")
    return {"ok": True}


@router.post("/templates/{template_id}/test-send")
async def enviar_teste(template_id: int, data: Dict, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    """Envia UM e-mail de teste deste template (valores de exemplo) para um
    endereco, usando o remetente/assinatura da empresa ativa."""
    para = (data.get("para") or "").strip()
    if not para or "@" not in para:
        raise HTTPException(status_code=400, detail="Informe um e-mail valido")
    t = get_template(template_id, organizacao_id=org_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template nao encontrado")
    # Opcional: se vier um CNPJ, puxa os dados REAIS da empresa para a
    # personalizacao ({{empresa}}, {{cidade}}, {{cnae_descricao}}...). Senao,
    # usa valores de exemplo.
    dados_empresa = None
    cnpj = (data.get("cnpj") or "").strip()
    if cnpj:
        dados_empresa = get_empresa_by_cnpj_db(cnpj, organizacao_id=org_id) or None
        if not dados_empresa:
            raise HTTPException(status_code=404, detail="Empresa (CNPJ) nao encontrada na base.")
    else:
        # Sem CNPJ, uma empresa da base DESTA empresa: o teste mostra o e-mail
        # com nome e cidade de verdade, e nao os dados de exemplo.
        amostra = listar_empresas_db(limit=1, offset=0, organizacao_id=org_id)
        dados_empresa = amostra[0] if amostra else None
    return enviar_email_teste(para, dict(t), organizacao_id=org_id, dados_empresa=dados_empresa,
                              remetente=current_user.get("sub"))


# Card/imagem do template (usada no corpo do email via {{imagem}})

_IMAGEM_MAX_BYTES = 3 * 1024 * 1024  # 3 MB
_IMAGEM_TIPOS_OK = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}


@router.post("/templates/{template_id}/preview")
async def preview_template(
    template_id: int, data: Dict = None,
    current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org),
):
    """Mostra o e-mail EXATAMENTE como vai sair: variaveis ja' substituidas
    com dados de uma empresa real, assinatura da empresa e rodape de
    descadastro (LGPD) incluidos.

    Usa montar_email_para_cnpj -- a mesma funcao do envio -- justamente pra
    o que aparece aqui nao ser uma aproximacao do que o destinatario recebe.
    Sem 'cnpj' no corpo, pega uma empresa da base pra servir de amostra.
    """
    data = data or {}
    template = get_template(template_id, organizacao_id=org_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template nao encontrado")

    cnpj = (data.get("cnpj") or "").strip()
    empresa = get_empresa_by_cnpj_db(cnpj, organizacao_id=org_id) if cnpj else None
    if not empresa:
        # Amostra tirada da fonte DESTA empresa (carteira propria ou Receita),
        # pro preview ter nome, cidade e CNAE de verdade sem mostrar empresa
        # de uma base que ela nao acessa.
        amostra = listar_empresas_db(limit=1, offset=0, organizacao_id=org_id)
        empresa = amostra[0] if amostra else None
    if not empresa:
        raise HTTPException(status_code=400, detail="Sem empresa de amostra para o preview")

    cnpj = empresa.get("cnpj_completo") or cnpj
    socios = buscar_socios_principais([cnpj[:8]]) if cnpj else {}
    dados = {
        "razao_social": empresa.get("razao_social", ""),
        "nome_fantasia": empresa.get("nome_fantasia", ""),
        "municipio": empresa.get("municipio", ""),
        "cnae_principal": empresa.get("cnae_principal", ""),
        "cnae_descricao": empresa.get("cnae_descricao", ""),
        "porte_nome": empresa.get("porte_nome", ""),
        "nome_socio": socios.get(cnpj[:8], ""),
    }
    email_dest = (empresa.get("email") or "").strip() or f"contato@{cnpj[:8]}.com.br"
    montado = montar_email_para_cnpj(template, cnpj, email_dest, dados, organizacao_id=org_id,
                                     remetente=current_user.get("sub"))
    montado["destinatario"] = email_dest
    montado["empresa"] = empresa.get("razao_social") or cnpj
    montado["cnpj"] = cnpj
    return montado


@router.post("/templates/{template_id}/imagem")
async def enviar_imagem_template(template_id: int, arquivo: UploadFile = File(...), current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    t = get_template(template_id, organizacao_id=org_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template nao encontrado")
    if arquivo.content_type not in _IMAGEM_TIPOS_OK:
        raise HTTPException(status_code=400, detail="Formato de imagem nao suportado (use PNG, JPG, WEBP ou GIF)")
    conteudo = await arquivo.read()
    if len(conteudo) > _IMAGEM_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Imagem muito grande (limite de 3 MB)")
    return set_template_imagem(template_id, conteudo, arquivo.content_type, organizacao_id=org_id)


@router.get("/templates/{template_id}/imagem")
async def obter_imagem_template(template_id: int):
    """Endpoint publico (sem autenticacao nem empresa) -- e' o que carrega a imagem
    quando o email e' aberto no cliente de email do destinatario, ou na
    pre-visualizacao do template no dashboard."""
    row = get_template_imagem(template_id)
    if not row or not row.get("imagem_data"):
        raise HTTPException(status_code=404, detail="Este template nao tem imagem")
    return Response(content=bytes(row["imagem_data"]), media_type=row.get("imagem_mime") or "image/png", headers={"Cache-Control": "public, max-age=300"})


@router.delete("/templates/{template_id}/imagem")
async def remover_imagem_template(template_id: int, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    t = get_template(template_id, organizacao_id=org_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template nao encontrado")
    return clear_template_imagem(template_id, organizacao_id=org_id)
