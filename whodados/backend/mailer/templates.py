"""Email Templates - WhoDados."""
from __future__ import annotations
from pathlib import Path
from typing import Dict

TEMPLATES_DIR = Path(__file__).parent / "templates"

DEFAULT_TEMPLATES: Dict[str, Dict[str, str]] = {
    "password_reset": {
        "assunto": "WhoDados - Recuperacao de Senha",
        "html": """<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
<div style="background:white;padding:30px;border-radius:8px">
<h2 style="color:#4f46e5">WhoDados - Recuperacao de Senha</h2>
<p>Ola, <strong>{{username}}</strong></p>
<p>Clique no botao para redefinir sua senha:</p>
<p><a href="{{reset_url}}" style="background:#4f46e5;color:white;padding:12px 24px;text-decoration:none;border-radius:6px">Redefinir Senha</a></p>
<p style="word-break:break-all;font-size:12px;color:#666">{{reset_url}}</p>
<p><strong>Expira em {{expire_minutes}} minutos.</strong></p>
<p style="color:#999;font-size:12px">Se nao foi voce, ignore.</p>
</div></body></html>""",
        "texto": """WhoDados - Recuperacao de Senha

Ola {{username}},

Acesse: {{reset_url}}

Expira em {{expire_minutes}} minutos.

Se nao foi voce, ignore.

---
WhoDados""",
    },
    "password_reset_success": {
        "assunto": "WhoDados - Senha Redefinida",
        "html": """<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
<div style="background:white;padding:30px;border-radius:8px">
<h2 style="color:#10b981">Senha Redefinida</h2>
<p>Ola, <strong>{{username}}</strong></p>
<p>Sua senha foi redefinida em {{data}}.</p>
</div></body></html>""",
        "texto": """WhoDados - Senha Redefinida

Ola {{username}},

Sua senha foi redefinida em {{data}}.

---
WhoDados""",
    },
    "welcome": {
        "assunto": "Bem-vindo ao WhoDados",
        "html": """<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
<div style="background:white;padding:30px;border-radius:8px">
<h2 style="color:#4f46e5">Bem-vindo ao WhoDados!</h2>
<p>Ola, <strong>{{username}}</strong></p>
<p>Sua conta foi criada com sucesso.</p>
<p><a href="{{login_url}}">Acessar conta</a></p>
</div></body></html>""",
        "texto": """WhoDados - Bem-vindo!

Ola {{username}},

Sua conta foi criada.

Acesse: {{login_url}}

---
WhoDados""",
    },
    "test": {
        "assunto": "WhoDados - Email de Teste",
        "html": """<html><body><h2>Email de Teste</h2><p>Configuracao SMTP funcionando!</p><p>{{timestamp}}</p></body></html>""",
        "texto": """WhoDados - Email de Teste

Configuracao SMTP funcionando!

{{timestamp}}

---
WhoDados""",
    },
}

def _render(t: str, v: Dict[str, str]) -> str:
    r = t
    for k, val in v.items():
        r = r.replace("{{" + k + "}}", str(val))
    return r

def get_template(name: str) -> Dict[str, str]:
    if name not in DEFAULT_TEMPLATES:
        return {"assunto": "", "html": "", "texto": ""}
    d = DEFAULT_TEMPLATES[name]
    base = TEMPLATES_DIR / name
    return {
        "assunto": (base.with_suffix(".subject")).read_text(encoding="utf-8").strip() if base.with_suffix(".subject").exists() else d["assunto"],
        "html": (base.with_suffix(".html")).read_text(encoding="utf-8") if base.with_suffix(".html").exists() else d["html"],
        "texto": (base.with_suffix(".txt")).read_text(encoding="utf-8") if base.with_suffix(".txt").exists() else d["texto"],
    }

def render_template(name: str, vars: Dict[str, str]) -> Dict[str, str]:
    t = get_template(name)
    return {"assunto": _render(t["assunto"], vars), "html": _render(t["html"], vars), "texto": _render(t["texto"], vars)}

def save_template(name: str, assunto: str, html: str, texto: str) -> bool:
    if name not in DEFAULT_TEMPLATES:
        return False
    try:
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        base = TEMPLATES_DIR / name
        base.with_suffix(".subject").write_text(assunto, encoding="utf-8")
        base.with_suffix(".html").write_text(html, encoding="utf-8")
        base.with_suffix(".txt").write_text(texto, encoding="utf-8")
        return True
    except Exception:
        return False

def list_templates() -> list:
    return [
        {"name": "password_reset", "label": "Recuperacao de Senha", "vars": ["username", "reset_url", "expire_minutes"]},
        {"name": "password_reset_success", "label": "Senha Redefinida", "vars": ["username", "data"]},
        {"name": "welcome", "label": "Boas-vindas", "vars": ["username", "login_url"]},
        {"name": "test", "label": "Email de Teste", "vars": ["timestamp"]},
    ]
"""Templates Padrao - WhoDados."""
from typing import Dict

TEMPLATES_PADRAO: Dict[str, Dict[str, str]] = {
    "introducao": {
        "nome": "Introducao B2B",
        "assunto": "Oportunidade de Negocio - {{empresa}}",
        "corpo_texto": "Prezado(a),\n\nGostaríamos de apresentar uma oportunidade de parceria para {{empresa}}.\n\nSomos especialistas em inteligencia comercial B2B e podemos ajudar sua empresa a identificar novas oportunidades de mercado.\n\nEstamos à disposicao para uma conversa breve.\n\nAtenciosamente,\nWhoDados Team",
        "corpo_html": "<p>Prezado(a),</p><p>Gostaríamos de apresentar uma oportunidade de parceria para <strong>{{empresa}}</strong>.</p><p>Somos especialistas em inteligencia comercial B2B e podemos ajudar sua empresa a identificar novas oportunidades de mercado.</p><p>Estamos à disposicao para uma conversa breve de 15 minutos.</p><p>Atenciosamente,<br/><strong>WhoDados Team</strong></p>",
    },
    "followup": {
        "nome": "Follow-up Pro",
        "assunto": "Seguindo conversa - {{empresa}}",
        "corpo_texto": "Ola,\n\nNao tivemos retorno sobre nossa ultima mensagem. Gostaria de agendar uma conversa rapida?\n\nWhoDados",
        "corpo_html": "<p>Ola,</p><p>Nao tivemos retorno sobre nossa ultima mensagem. Gostaria de agendar uma conversa rapida de 15 minutos?</p><p>WhoDados</p>",
    },
    "demo": {
        "nome": "Demo Request",
        "assunto": "Demo Gratuita - WhoDados Intelligence",
        "corpo_texto": "Ola,\n\nQue tal uma demo gratuita da plataforma WhoDados?\n\nWhoDados",
        "corpo_html": "<p>Ola,</p><p>Que tal uma <strong>demo gratuita</strong> da plataforma WhoDados?</p><p>Nossa plataforma ajuda empresas B2B a identificar oportunidades comerciais usando dados reais do mercado.</p><p>WhoDados</p>",
    },
}
