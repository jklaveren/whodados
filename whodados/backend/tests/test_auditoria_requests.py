"""Testes da auditoria automatica de requisicoes (sem banco).

O middleware existe pra garantir que rota nova nasca auditada sem ninguem
lembrar disso -- entao o que estes testes protegem e' exatamente isso: que ele
pegue o que muda, ignore o que so' le, e nunca derrube a requisicao.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.security.auditoria_requests import AuditoriaRequestsMiddleware, _recurso


@pytest.fixture
def app_e_registros(monkeypatch):
    """App minimo com o middleware, e uma lista no lugar do banco."""
    registros = []

    def falso_create_audit_log(**kw):
        registros.append(kw)
        return {"id": len(registros)}

    monkeypatch.setattr("backend.db.service.create_audit_log", falso_create_audit_log)

    app = FastAPI()
    app.add_middleware(AuditoriaRequestsMiddleware)

    @app.get("/api/v1/empresas")
    async def listar():
        return {"ok": True}

    @app.post("/api/v1/campanhas")
    async def criar():
        return {"id": 7}

    @app.delete("/api/v1/carteira/12345678000199")
    async def remover():
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    async def login():
        return {"token": "x"}

    @app.post("/api/v1/quebra")
    async def quebra():
        raise ValueError("erro de proposito")

    return app, registros


def test_recurso_extrai_tipo_e_id():
    assert _recurso("/api/v1/campanhas/12/executar") == ("campanhas", "12")
    assert _recurso("/api/v1/campanhas") == ("campanhas", None)
    # CNPJ e' so' digitos depois de limpo, entao serve de identificador.
    assert _recurso("/api/v1/carteira/12345678000199") == ("carteira", "12345678000199")
    assert _recurso("/") == ("desconhecido", None)


def test_leitura_nao_e_auditada(app_e_registros):
    """GET fica de fora de proposito: a tela de Empresas dispara varias
    leituras por mexida de filtro e afogaria a tabela."""
    app, registros = app_e_registros
    assert TestClient(app).get("/api/v1/empresas").status_code == 200
    assert registros == []


def test_escrita_e_auditada_com_autor_e_empresa(app_e_registros):
    app, registros = app_e_registros
    r = TestClient(app).post("/api/v1/campanhas", headers={"X-Org-Id": "3"})
    assert r.status_code == 200
    assert len(registros) == 1
    reg = registros[0]
    assert reg["action"] == "POST /api/v1/campanhas"
    assert reg["resource_type"] == "campanhas"
    assert reg["success"] is True
    assert reg["details"]["status"] == 200
    assert reg["details"]["organizacao_id"] == 3


def test_delete_guarda_o_identificador(app_e_registros):
    app, registros = app_e_registros
    TestClient(app).delete("/api/v1/carteira/12345678000199")
    assert registros[0]["resource_id"] == "12345678000199"
    assert registros[0]["action"].startswith("DELETE ")


def test_login_nao_duplica(app_e_registros):
    """log_login ja' cobre isso, com o detalhe que importa."""
    app, registros = app_e_registros
    TestClient(app).post("/api/v1/auth/login")
    assert registros == []


def test_falha_de_auditoria_nao_derruba_a_requisicao(app_e_registros, monkeypatch):
    """Auditoria e' best-effort: a resposta ja' esta' pronta quando ela roda."""
    app, registros = app_e_registros

    def explode(**kw):
        raise RuntimeError("banco fora do ar")

    monkeypatch.setattr("backend.db.service.create_audit_log", explode)
    r = TestClient(app).post("/api/v1/campanhas")
    assert r.status_code == 200
    assert registros == []


def test_erro_do_endpoint_e_registrado_como_insucesso(app_e_registros):
    """Tentativa que falhou e' o que mais interessa numa auditoria."""
    app, registros = app_e_registros
    cliente = TestClient(app, raise_server_exceptions=False)
    r = cliente.post("/api/v1/quebra")
    assert r.status_code == 500
    assert len(registros) == 1
    assert registros[0]["success"] is False
    assert registros[0]["details"]["status"] == 500
