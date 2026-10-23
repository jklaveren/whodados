"""Testes do push (PWA) e do broadcast por empresa/global."""
import uuid

import pytest
from fastapi import HTTPException

from backend.db import salvar_push_subscription, remover_push_subscription
from backend.db.config import ensure_push_tables
from backend.endpoints_push import resolver_alvos_broadcast
from backend import push as push_mod


def _endpoint_fake() -> str:
    return f"https://push.test/{uuid.uuid4()}"


@pytest.fixture(scope="module")
def tabela_push():
    """Garante a tabela de subscriptions -- precisa de banco de verdade.

    Deixou de ser autouse: a maior parte deste arquivo testa
    `resolver_alvos_broadcast`, que e' funcao pura. Com a fixture em todo o
    modulo, um ambiente sem banco derrubava tambem os testes que nao
    precisavam dele, e o arquivo inteiro aparecia como erro.

    Sem banco alcancavel os dois testes de ida-e-volta sao PULADOS, com o
    motivo a vista -- nao silenciados nem passados em falso. Em CI com
    Postgres eles rodam.
    """
    try:
        ensure_push_tables()
    except Exception as e:
        pytest.skip(f"precisa de banco: {type(e).__name__}")


# Alvos do broadcast (puro, sem banco)

def test_broadcast_minha_empresa_admin_ok():
    assert resolver_alvos_broadcast("minha_empresa", False, "admin", 2, [1, 2, 3]) == [2]


def test_broadcast_minha_empresa_global_ok():
    assert resolver_alvos_broadcast("minha_empresa", True, "membro", 1, [1, 2]) == [1]


def test_broadcast_minha_empresa_membro_bloqueia():
    with pytest.raises(HTTPException) as exc:
        resolver_alvos_broadcast("minha_empresa", False, "membro", 1, [1])
    assert exc.value.status_code == 403


def test_broadcast_todas_global_ok():
    assert resolver_alvos_broadcast("todas", True, "membro", 1, [1, 2, 3]) == [1, 2, 3]


def test_broadcast_todas_nao_global_bloqueia():
    with pytest.raises(HTTPException) as exc:
        resolver_alvos_broadcast("todas", False, "admin", 1, [1, 2])
    assert exc.value.status_code == 403


def test_broadcast_todas_sem_empresas_400():
    with pytest.raises(HTTPException) as exc:
        resolver_alvos_broadcast("todas", True, "admin", 1, [])
    assert exc.value.status_code == 400


# Inscricoes (banco; endpoint unico por rodada, limpo no fim)

def test_subscribe_unsubscribe_roundtrip(tabela_push):
    endpoint = _endpoint_fake()
    try:
        row = salvar_push_subscription("test_push_user", 1, endpoint, "p256dh-x", "auth-x", "pytest")
        assert row is not None
        assert row["endpoint"] == endpoint
        # Reinscrever atualiza em vez de duplicar
        row2 = salvar_push_subscription("test_push_user", 2, endpoint, "p256dh-y", "auth-y", "pytest")
        assert row2["id"] == row["id"]
        assert row2["organizacao_id"] == 2
        assert remover_push_subscription(endpoint, username="test_push_user") is True
        assert remover_push_subscription(endpoint, username="test_push_user") is False
    finally:
        remover_push_subscription(endpoint)


def test_unsubscribe_nao_remove_de_outro(tabela_push):
    endpoint = _endpoint_fake()
    try:
        salvar_push_subscription("dono_a", 1, endpoint, "p", "a", None)
        assert remover_push_subscription(endpoint, username="dono_b") is False
    finally:
        remover_push_subscription(endpoint)


# Remetente (sem rede: sem VAPID no ambiente de teste)

def test_enviar_push_sem_configuracao_retorna_false():
    if push_mod.push_configurado():
        pytest.skip("VAPID configurado neste ambiente; teste vale so sem chaves")
    assert push_mod.enviar_push({"endpoint": "x", "p256dh": "y", "auth": "z"}, "t") is False


def test_disparar_push_vazio():
    assert push_mod.disparar_push([], "t") == {"enviados": 0, "falhos": 0}
