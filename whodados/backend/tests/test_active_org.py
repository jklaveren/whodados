"""Testes da dependencia get_active_org (empresa ativa + validacao de acesso)."""
import pytest
from types import SimpleNamespace
from fastapi import HTTPException
from backend.auth import dependencies as dep


def _get(method="GET"):
    return SimpleNamespace(method=method)


def test_header_com_acesso(monkeypatch):
    monkeypatch.setattr("backend.db.service.usuario_tem_acesso_org", lambda u, o: True)
    assert dep.get_active_org(_get(), {"sub": "jeh"}, x_org_id=2) == 2


def test_header_sem_acesso_bloqueia(monkeypatch):
    monkeypatch.setattr("backend.db.service.usuario_tem_acesso_org", lambda u, o: False)
    with pytest.raises(HTTPException) as exc:
        dep.get_active_org(_get(), {"sub": "jeh"}, x_org_id=99)
    assert exc.value.status_code == 403


def test_sem_header_uma_empresa_leitura_retorna_ela(monkeypatch):
    monkeypatch.setattr("backend.db.service.listar_organizacoes_do_usuario", lambda u: [{"id": 1}])
    assert dep.get_active_org(_get("GET"), {"sub": "jeh"}, x_org_id=None) == 1


def test_sem_header_varias_empresas_exige_header_400(monkeypatch):
    # Adivinhar a primeira empresa gravava tarefa/notificacao na empresa
    # errada (Alfa) quando o header nao chegava -- por isso agora e' 400.
    monkeypatch.setattr(
        "backend.db.service.listar_organizacoes_do_usuario", lambda u: [{"id": 1}, {"id": 2}]
    )
    with pytest.raises(HTTPException) as exc:
        dep.get_active_org(_get("GET"), {"sub": "jeh"}, x_org_id=None)
    assert exc.value.status_code == 400


def test_sem_header_escrita_mesmo_uma_empresa_400(monkeypatch):
    monkeypatch.setattr("backend.db.service.listar_organizacoes_do_usuario", lambda u: [{"id": 1}])
    with pytest.raises(HTTPException) as exc:
        dep.get_active_org(_get("POST"), {"sub": "jeh"}, x_org_id=None)
    assert exc.value.status_code == 400


def test_sem_empresa_bloqueia(monkeypatch):
    monkeypatch.setattr("backend.db.service.listar_organizacoes_do_usuario", lambda u: [])
    with pytest.raises(HTTPException) as exc:
        dep.get_active_org(_get(), {"sub": "jeh"}, x_org_id=None)
    assert exc.value.status_code == 403
