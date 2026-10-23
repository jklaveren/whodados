"""WhoDados API Endpoints - Carteira propria da empresa.

Empresa com escopo_base='carteira' prospecta sobre a lista dela, nao sobre a
base da Receita Federal. As telas sao as mesmas (Empresas, Clientes,
Campanhas) -- o que muda e' a fonte, resolvida em db/service.py.

Aqui ficam as operacoes que so' fazem sentido na carteira: carregar a lista,
ver/editar as categorias e tirar uma empresa dela.
"""
import csv
import io
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from .auth import get_current_user, get_active_org, require_org_admin
from .db import (
    marcar_emails_compartilhados,
    org_escopo_base, tamanho_carteira, categorias_da_carteira, salvar_na_carteira, remover_da_carteira,
    contar_carteira_db,
)

router = APIRouter(prefix="/api/v1")

_IMPORT_MAX_BYTES = 5 * 1024 * 1024
_IMPORT_MAX_LINHAS = 5000

# Nome da coluna na planilha -> campo da carteira. Aceita as variacoes que
# aparecem em export de CRM e planilha feita a mao, pra ninguem ter que
# renomear cabecalho antes de subir.
_COLUNAS = {
    "cnpj": "cnpj_completo", "cnpj_completo": "cnpj_completo",
    "razao_social": "razao_social", "razão social": "razao_social",
    "razao social": "razao_social", "nome": "razao_social", "empresa": "razao_social",
    "nome_fantasia": "nome_fantasia", "nome fantasia": "nome_fantasia", "fantasia": "nome_fantasia",
    "municipio": "municipio", "município": "municipio", "cidade": "municipio",
    "uf": "uf", "estado": "uf",
    "email": "email", "e-mail": "email",
    "telefone": "contato_fone", "fone": "contato_fone", "celular": "contato_fone",
    "whatsapp": "contato_fone", "contato_fone": "contato_fone",
    "cnae": "cnae_principal", "cnae_principal": "cnae_principal",
    "cnae_descricao": "cnae_descricao", "atividade": "cnae_descricao",
    "porte": "porte_nome", "porte_nome": "porte_nome",
    "capital_social": "capital_social", "capital": "capital_social",
    "divida": "divida_total", "divida_total": "divida_total",
    "categoria": "categoria", "segmento": "categoria", "tipo": "categoria",
    "situacao": "situacao", "situação": "situacao", "status": "situacao",
    "observacao": "observacao", "observação": "observacao", "obs": "observacao",
}

_NUMERICOS = {"capital_social", "divida_total"}


def _so_carteira(org_id: int) -> None:
    """Pergunta B: a empresa opera sobre lista de trabalho?

    Nao e' o mesmo que escopo_base. A Alfa pesquisa na base da Receita
    (escopo 'receita') E tem carteira -- o recorte de engenharia tirado de
    la'. Pelo criterio antigo ela nao conseguia nem carregar a propria lista.

    Carteira vazia continua barrada, com o texto dizendo o que fazer."""
    if not tamanho_carteira(org_id):
        raise HTTPException(
            status_code=400,
            detail="Esta empresa ainda nao tem lista de trabalho. Importe a carteira para comecar.",
        )


def _numero(bruto: str) -> Optional[float]:
    """Aceita '1.234,56' (planilha BR) e '1234.56'."""
    texto = (bruto or "").strip()
    if not texto:
        return None
    texto = texto.replace("R$", "").strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _linhas_do_csv(conteudo: bytes) -> List[Dict[str, str]]:
    """Le CSV em UTF-8 ou Latin-1 (Excel brasileiro salva em Latin-1), com
    separador detectado -- ; e' o padrao do Excel em portugues."""
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            texto = conteudo.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(status_code=400, detail="Nao consegui ler o arquivo (codificacao)")

    amostra = texto[:4096]
    separador = ";" if amostra.count(";") > amostra.count(",") else ","
    return list(csv.DictReader(io.StringIO(texto), delimiter=separador))


@router.get("/carteira/categorias")
async def carteira_categorias(current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    """Categorias da carteira com a contagem -- e' o filtro que substitui o
    CNAE quando a empresa nao prospecta sobre a base da Receita."""
    return categorias_da_carteira(org_id)


@router.get("/carteira/resumo")
async def carteira_resumo(current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org)):
    return {
        # escopo_base responde "de onde vem a pesquisa"; tem_carteira responde
        # "ha' lista de trabalho". A tela precisa das duas, separadas.
        "escopo_base": org_escopo_base(org_id),
        "tem_carteira": tamanho_carteira(org_id) > 0,
        "total": contar_carteira_db(org_id),
        "categorias": categorias_da_carteira(org_id),
    }


@router.post("/carteira/importar")
async def carteira_importar(
    arquivo: UploadFile = File(...),
    current_user: Dict = Depends(require_org_admin), org_id: int = Depends(get_active_org),
):
    """Carrega a carteira a partir de um CSV.

    Unica coluna obrigatoria e' o CNPJ; o resto entra se vier. Recarregar a
    mesma planilha ATUALIZA as empresas em vez de duplicar (a chave e'
    empresa + CNPJ), e coluna vazia na recarga nao apaga o que ja' estava
    preenchido -- quem completou um e-mail a mao nao perde o trabalho.
    """
    _so_carteira(org_id)
    conteudo = await arquivo.read()
    if len(conteudo) > _IMPORT_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Arquivo muito grande (limite de 5 MB)")

    linhas = _linhas_do_csv(conteudo)
    if not linhas:
        raise HTTPException(status_code=400, detail="Planilha vazia")
    if len(linhas) > _IMPORT_MAX_LINHAS:
        raise HTTPException(status_code=400, detail=f"Limite de {_IMPORT_MAX_LINHAS} linhas por carga")

    salvos, ignorados = 0, []
    for numero_linha, linha in enumerate(linhas, start=2):
        empresa: Dict[str, object] = {}
        for coluna, valor in (linha or {}).items():
            campo = _COLUNAS.get((coluna or "").strip().lower())
            if not campo:
                continue
            valor = (valor or "").strip()
            if not valor:
                continue
            empresa[campo] = _numero(valor) if campo in _NUMERICOS else valor
        empresa["origem"] = "planilha"
        if not empresa.get("cnpj_completo"):
            ignorados.append({"linha": numero_linha, "motivo": "sem CNPJ"})
            continue
        if salvar_na_carteira(org_id, empresa, criado_por=current_user.get("sub")):
            salvos += 1
        else:
            ignorados.append({"linha": numero_linha, "motivo": "CNPJ invalido"})

    # Importou contato novo: remarca quem divide o e-mail com outro (contador,
    # servico de abertura de empresa). Se falhar, a importacao nao pode falhar.
    try:
        marcar_emails_compartilhados(org_id)
    except Exception:
        pass

    return {
        "salvos": salvos,
        "ignorados": ignorados[:20],
        "total_ignorados": len(ignorados),
        "total_na_carteira": contar_carteira_db(org_id),
        "categorias": categorias_da_carteira(org_id),
    }


@router.post("/carteira")
async def carteira_adicionar(
    data: Dict, current_user: Dict = Depends(get_current_user), org_id: int = Depends(get_active_org),
):
    """Adiciona/atualiza uma empresa da carteira na mao (sem planilha)."""
    _so_carteira(org_id)
    salvo = salvar_na_carteira(org_id, {**data, "origem": data.get("origem") or "manual"},
                               criado_por=current_user.get("sub"))
    if not salvo:
        raise HTTPException(status_code=400, detail="CNPJ e' obrigatorio")
    return salvo


@router.delete("/carteira/{cnpj}")
async def carteira_remover(
    cnpj: str, current_user: Dict = Depends(require_org_admin), org_id: int = Depends(get_active_org),
):
    if not remover_da_carteira(org_id, cnpj):
        raise HTTPException(status_code=404, detail="Empresa nao esta na carteira")
    return {"ok": True}
