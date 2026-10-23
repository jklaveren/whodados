"""Admin Endpoints - WhoDados."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from typing import Dict, Any
from .auth import get_current_user, get_active_org
from .mailer import (
    get_smtp_config, test_smtp_connection, test_email_send,
    get_smtp_presets
)
from typing import List, Optional
from .db import (
    get_pipeline_metadata, get_sla_config, set_sla_config,
    list_all_users, update_user_flags, delete_user, update_user_email,
    listar_todas_organizacoes, get_orgs_do_user_id, definir_acesso_usuario_orgs,
    criar_organizacao, renomear_organizacao, definir_escopo_base,
    definir_limite_diario_org,
    get_org_smtp_config, set_org_smtp_config, set_org_logo,
)
from .auth import criar_usuario, hash_senha
from .db.service import update_user_password
from .logger import get_logger
logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/admin")


def require_admin(current_user: Dict = Depends(get_current_user)) -> Dict:
    if not current_user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return current_user


@router.get("/smtp/config")
async def get_smtp_status(current_user: Dict = Depends(require_admin)) -> Dict[str, Any]:
    """Retorna configuracao atual de SMTP (sem a senha)."""
    return get_smtp_config()


@router.get("/smtp/presets")
async def list_presets(current_user: Dict = Depends(require_admin)) -> Dict[str, Any]:
    """Lista provedores SMTP pre-configurados."""
    return {"presets": get_smtp_presets()}


@router.post("/smtp/test-connection")
async def test_connection(data: Dict, current_user: Dict = Depends(require_admin)) -> Dict[str, Any]:
    """Testa conexao SMTP com os parametros fornecidos."""
    host = data.get("host", "").strip()
    port = data.get("port", 587)
    username = data.get("username", "").strip()
    password = data.get("password", "")
    use_tls = data.get("use_tls", True)

    if not host or not username or not password:
        raise HTTPException(status_code=400, detail="Host, username e password sao obrigatorios")

    logger.info(f"Testando conexao SMTP para {username}@{host}:{port}")
    return test_smtp_connection(host, port, username, password, use_tls)


@router.post("/smtp/test-send")
async def send_test_email(data: Dict, current_user: Dict = Depends(require_admin), org_id: int = Depends(get_active_org)) -> Dict[str, Any]:
    """Envia e-mail de teste usando a configuracao atual."""
    para = data.get("para", "").strip()
    if not para or "@" not in para:
        raise HTTPException(status_code=400, detail="Email invalido")

    logger.info(f"Enviando e-mail de teste para {para} (org {org_id})")
    return test_email_send(para, organizacao_id=org_id)


@router.get("/sistema/status")
async def get_sistema_status(current_user: Dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Informacoes sobre a ultima atualizacao dos dados (Receita Federal /
    PGFN), pra tela "Sobre" em Configuracoes. Qualquer usuario logado pode
    ver -- nao e informacao sensivel, so status. Retorna tudo vazio/None se
    o pipeline de ETL nunca rodou ainda."""
    meta = get_pipeline_metadata()

    def valor(chave: str):
        item = meta.get(chave)
        return item["valor"] if item else None

    return {
        "mes_referencia_rf": valor("mes_referencia_rf"),
        "trimestre_pgfn": valor("trimestre_pgfn"),
        "gerado_em": valor("gerado_em"),
        "ultima_sincronizacao": valor("ultima_sincronizacao"),
        "total_matrizes": valor("total_matrizes"),
        "total_empresas_sincronizadas": valor("total_empresas_sincronizadas"),
        "total_socios_sincronizados": valor("total_socios_sincronizados"),
        "pipeline_ja_rodou": bool(meta),
    }


@router.get("/sla")
async def get_sla(current_user: Dict = Depends(get_current_user)) -> Dict[str, int]:
    """Prazos (em dias) que definem o semaforo do Monitor de e-mails.
    Qualquer usuario logado pode ver -- e so exibido na tela, nao e sensivel."""
    return get_sla_config()


@router.put("/sla")
async def update_sla(data: Dict, current_user: Dict = Depends(require_admin)) -> Dict[str, Any]:
    """Atualiza os prazos do semaforo. So admin pode mudar -- afeta todo mundo."""
    try:
        verde = int(data.get("sla_verde_dias"))
        amarelo = int(data.get("sla_amarelo_dias"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="sla_verde_dias e sla_amarelo_dias precisam ser numeros inteiros")
    try:
        set_sla_config(verde, amarelo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info(f"SLA do monitor atualizado por {current_user.get('sub')}: verde={verde}, amarelo={amarelo}")
    return get_sla_config()


# EMPRESAS (ORGANIZACOES)

@router.post("/organizacoes")
async def admin_criar_organizacao(data: Dict, current_user: Dict = Depends(require_admin)) -> Dict[str, Any]:
    """Cria uma empresa nova. O nome pode ser trocado depois; o slug fica."""
    try:
        return criar_organizacao(data.get("nome", ""), data.get("slug"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/organizacoes/{organizacao_id}")
async def admin_atualizar_organizacao(organizacao_id: int, data: Dict, current_user: Dict = Depends(require_admin)) -> Dict[str, Any]:
    """Nome e/ou fonte de prospeccao. Os dois sao opcionais, mas um tem que
    vir -- assim a tela manda so' o campo que mexeu, e quem ja' chamava com
    {"nome": ...} continua funcionando.

    require_admin e' o admin GLOBAL de proposito: a fonte e' decisao de
    contrato, nao preferencia de uso da empresa."""
    mexeu = False
    if "nome" in data:
        if not renomear_organizacao(organizacao_id, data.get("nome", "")):
            raise HTTPException(status_code=400, detail="Nome invalido ou empresa nao encontrada")
        mexeu = True
    if "escopo_base" in data:
        try:
            if not definir_escopo_base(organizacao_id, data.get("escopo_base", "")):
                raise HTTPException(status_code=404, detail="Empresa nao encontrada")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        logger.info(f"Fonte da empresa {organizacao_id} trocada para "
                    f"{data.get('escopo_base')} por {current_user.get('sub')}")
        mexeu = True
    if "email_limite_diario" in data:
        # Teto diario desta empresa. Admin GLOBAL, pelo mesmo motivo da fonte:
        # a cota sai de uma conta de provedor compartilhada entre os clientes,
        # entao quem divide o bolo nao pode ser quem come um pedaco.
        bruto = data.get("email_limite_diario")
        try:
            limite = None if bruto in (None, "", 0, "0") else int(bruto)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="email_limite_diario precisa ser inteiro ou vazio")
        if limite is not None and limite < 0:
            raise HTTPException(status_code=400, detail="email_limite_diario nao pode ser negativo")
        if not definir_limite_diario_org(organizacao_id, limite):
            raise HTTPException(status_code=404, detail="Empresa nao encontrada")
        logger.info(f"Teto diario da empresa {organizacao_id} = {limite} "
                    f"por {current_user.get('sub')}")
        mexeu = True
    if not mexeu:
        raise HTTPException(
            status_code=400,
            detail="Nada para atualizar (envie 'nome', 'escopo_base' e/ou 'email_limite_diario')")
    return {"ok": True}


@router.get("/organizacoes")
async def admin_listar_organizacoes(current_user: Dict = Depends(require_admin)) -> List[Dict[str, Any]]:
    """Lista todas as empresas (para gestao de acesso e config de e-mail)."""
    return listar_todas_organizacoes()


@router.get("/organizacoes/{organizacao_id}/smtp")
async def admin_get_org_smtp(organizacao_id: int, current_user: Dict = Depends(require_admin)) -> Dict[str, Any]:
    """Config de e-mail (SMTP + assinatura) da empresa, sem a senha."""
    cfg = get_org_smtp_config(organizacao_id)
    return cfg or {"organizacao_id": organizacao_id, "configurado": False, "tem_logo": False}


@router.put("/organizacoes/{organizacao_id}/smtp")
async def admin_set_org_smtp(organizacao_id: int, data: Dict, current_user: Dict = Depends(require_admin)) -> Dict[str, Any]:
    """Cria/atualiza a config de e-mail da empresa (remetente, SMTP, assinatura).
    Senha vazia mantem a atual."""
    cfg = set_org_smtp_config(
        organizacao_id,
        smtp_host=(data.get("smtp_host") or "").strip() or None,
        smtp_port=data.get("smtp_port"),
        smtp_username=(data.get("smtp_username") or "").strip() or None,
        smtp_password=data.get("smtp_password") or None,
        smtp_use_tls=data.get("smtp_use_tls"),
        email_from=(data.get("email_from") or "").strip() or None,
        email_from_name=(data.get("email_from_name") or "").strip() or None,
        assinatura_html=data.get("assinatura_html"),
    )
    logger.info(f"Config de e-mail da empresa {organizacao_id} atualizada por {current_user.get('sub')}")
    return cfg


_LOGO_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
_LOGO_TIPOS_OK = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}


@router.post("/organizacoes/{organizacao_id}/logo")
async def admin_upload_org_logo(organizacao_id: int, arquivo: UploadFile = File(...), current_user: Dict = Depends(require_admin)) -> Dict[str, Any]:
    """Envia/substitui o logo da empresa (usado na assinatura de e-mail via {{logo}})."""
    if arquivo.content_type not in _LOGO_TIPOS_OK:
        raise HTTPException(status_code=400, detail="Formato invalido (use PNG, JPG, WEBP ou GIF)")
    conteudo = await arquivo.read()
    if len(conteudo) > _LOGO_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Logo muito grande (limite de 2 MB)")
    set_org_logo(organizacao_id, conteudo, arquivo.content_type)
    return {"sucesso": True, "tem_logo": True}


def _serializar_usuario(u: Dict) -> Dict[str, Any]:
    return {
        "id": u["id"],
        "username": u["username"],
        "email": u.get("email"),
        "is_admin": bool(u.get("is_admin")),
        "is_active": bool(u.get("is_active", True)),
        "created_at": u["created_at"].isoformat() if u.get("created_at") else None,
        "organizacao_ids": get_orgs_do_user_id(u["id"]),
    }


@router.get("/usuarios")
async def listar_usuarios(current_user: Dict = Depends(require_admin)) -> List[Dict[str, Any]]:
    """Lista todos os usuarios do sistema, com as empresas de cada um. So admin."""
    return [_serializar_usuario(u) for u in list_all_users()]


@router.post("/usuarios")
async def criar_novo_usuario(data: Dict, current_user: Dict = Depends(require_admin)) -> Dict[str, Any]:
    """Cria um novo usuario e ja define suas empresas. So admin."""
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    email = (data.get("email") or "").strip() or None
    is_admin = bool(data.get("is_admin", False))
    organizacao_ids = data.get("organizacao_ids") or []
    if not username or len(password) < 8:
        raise HTTPException(status_code=400, detail="Usuario obrigatorio e senha precisa ter ao menos 8 caracteres")
    try:
        user = criar_usuario(username, password, email, is_admin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if user and user.get("id") and organizacao_ids:
        definir_acesso_usuario_orgs(user["id"], [int(o) for o in organizacao_ids])
    logger.info(f"Usuario '{username}' criado por {current_user.get('sub')} (empresas: {organizacao_ids})")
    return user


@router.put("/usuarios/{user_id}/organizacoes")
async def definir_empresas_usuario(user_id: int, data: Dict, current_user: Dict = Depends(require_admin)) -> Dict[str, Any]:
    """Define a quais empresas um usuario tem acesso (substitui as anteriores)."""
    alvo = next((u for u in list_all_users() if u["id"] == user_id), None)
    if not alvo:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    ids = [int(o) for o in (data.get("organizacao_ids") or [])]
    definir_acesso_usuario_orgs(user_id, ids)
    logger.info(f"Empresas do usuario '{alvo['username']}' definidas por {current_user.get('sub')}: {ids}")
    return {"sucesso": True, "organizacao_ids": get_orgs_do_user_id(user_id)}


@router.patch("/usuarios/{user_id}")
async def atualizar_usuario(user_id: int, data: Dict, current_user: Dict = Depends(require_admin)) -> Dict[str, Any]:
    """Ativa/desativa ou promove/remove admin de um usuario. So admin.
    Um admin nao pode remover o proprio acesso de admin nem se desativar
    (evita o sistema ficar sem nenhum admin por acidente)."""
    usuarios = list_all_users()
    alvo = next((u for u in usuarios if u["id"] == user_id), None)
    if not alvo:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")

    is_admin = data.get("is_admin")
    is_active = data.get("is_active")
    email = data.get("email")  # pode vir para editar; None = nao mexe

    if alvo["username"] == current_user.get("sub"):
        if is_admin is False:
            raise HTTPException(status_code=400, detail="Voce nao pode remover seu proprio acesso de admin")
        if is_active is False:
            raise HTTPException(status_code=400, detail="Voce nao pode desativar sua propria conta")

    mudou = False
    if is_admin is not None or is_active is not None:
        mudou = update_user_flags(
            user_id,
            is_admin=bool(is_admin) if is_admin is not None else None,
            is_active=bool(is_active) if is_active is not None else None,
        ) or mudou
    if email is not None:
        mudou = update_user_email(user_id, (email or "").strip() or None) or mudou
    if not mudou:
        raise HTTPException(status_code=400, detail="Nada para atualizar")
    logger.info(f"Usuario '{alvo['username']}' atualizado por {current_user.get('sub')}: {data}")
    atualizado = next(u for u in list_all_users() if u["id"] == user_id)
    return _serializar_usuario(atualizado)


@router.delete("/usuarios/{user_id}")
async def excluir_usuario(user_id: int, current_user: Dict = Depends(require_admin)) -> Dict[str, Any]:
    """Exclui um usuario. Nao permite excluir a si mesmo (evita ficar sem admin)."""
    alvo = next((u for u in list_all_users() if u["id"] == user_id), None)
    if not alvo:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    if alvo["username"] == current_user.get("sub"):
        raise HTTPException(status_code=400, detail="Voce nao pode excluir a propria conta")
    if not delete_user(user_id):
        raise HTTPException(status_code=400, detail="Falha ao excluir usuario")
    logger.info(f"Usuario '{alvo['username']}' excluido por {current_user.get('sub')}")
    return {"sucesso": True, "message": f"Usuario '{alvo['username']}' excluido."}


@router.post("/usuarios/{user_id}/redefinir-senha")
async def admin_redefinir_senha(user_id: int, data: Dict, current_user: Dict = Depends(require_admin)) -> Dict[str, Any]:
    """Admin redefine a senha de outro usuario direto (sem precisar saber a
    senha antiga) -- util quando alguem da equipe esquece a senha."""
    nova_senha = data.get("nova_senha") or ""
    if len(nova_senha) < 8:
        raise HTTPException(status_code=400, detail="A nova senha precisa ter ao menos 8 caracteres")
    usuarios = list_all_users()
    alvo = next((u for u in usuarios if u["id"] == user_id), None)
    if not alvo:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    update_user_password(user_id, hash_senha(nova_senha))
    logger.info(f"Senha do usuario '{alvo['username']}' redefinida por {current_user.get('sub')}")
    return {"sucesso": True, "message": f"Senha de '{alvo['username']}' redefinida."}
