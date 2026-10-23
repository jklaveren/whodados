"""Endpoint publico de descadastro de e-mail (LGPD/opt-out).

Sem login -- e' clicado direto do e-mail recebido. Qualquer campanha, de
qualquer empresa (Alfa ou Beta), injeta esse link automaticamente no
rodape (ver mailer/service.py) -- e' regra do negocio, nao depende do
autor do template lembrar de incluir."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from .mailer.descadastro import validar_assinatura
from .db import descadastrar_email

router = APIRouter(prefix="/api/v1")

_PAGINA = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Descadastro</title></head>
<body style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:80px auto;text-align:center;color:#3A4556;">
<h2 style="color:#112A52;">{titulo}</h2>
<p>{mensagem}</p>
</body></html>"""


@router.get("/descadastro", response_class=HTMLResponse)
async def descadastro(email: str = "", sig: str = ""):
    if not validar_assinatura(email, sig):
        return _PAGINA.format(titulo="Link invalido", mensagem="Este link de descadastro nao e' valido.")
    descadastrar_email(email, motivo="Solicitado pelo destinatario via link do e-mail")
    return _PAGINA.format(
        titulo="Descadastro confirmado",
        mensagem=f"O endereco {email} nao vai mais receber e-mails nossos.",
    )


@router.post("/descadastro")
async def descadastro_um_clique(email: str = "", sig: str = ""):
    """Descadastro de um clique, acionado pelo botao nativo do provedor.

    O par List-Unsubscribe + List-Unsubscribe-Post (RFC 8058) faz Gmail,
    Yahoo e Outlook desenharem "cancelar inscricao" ao lado do remetente --
    mas eles mandam POST, nao GET, e desistem do botao se o POST falhar. O
    provedor nao renderiza resposta: espera 200 e segue. Por isso devolve
    JSON e nao a pagina HTML do GET.

    Mesma assinatura HMAC do GET: sem ela qualquer um descadastraria qualquer
    endereco sabendo so' o e-mail.
    """
    if not validar_assinatura(email, sig):
        return {"ok": False, "erro": "assinatura invalida"}
    descadastrar_email(email, motivo="Um clique no botao do provedor (List-Unsubscribe)")
    return {"ok": True, "email": email}
