"""Deixa a suite rodar onde o psycopg2 nao carrega.

A suite e' toda de teste unitario: nenhum teste abre conexao -- todos trocam
a funcao de banco por `monkeypatch`. Mesmo assim, importar qualquer coisa de
`backend.db` puxa `db/config.py`, que faz `import psycopg2` no topo do
modulo, e aí a coleta morre antes do primeiro teste.

Nesta maquina o `_psycopg.*.pyd` nao e' assinado e o Smart App Control esta em
modo de bloqueio (`VerifiedAndReputablePolicyState=1`), entao o import falha
mesmo com o Python do venv -- o diagnostico antigo de que "era o Python do
sistema" ficou desatualizado quando a politica saiu do modo de avaliacao.

O substituto entra SO' se o psycopg2 real nao carregar, e falha alto se
alguem tentar de fato abrir conexao: teste que precise de banco quebra com a
mensagem certa em vez de passar contra um banco de mentira. Em CI, onde o
psycopg2 instala normalmente, este arquivo nao faz nada.
"""
import sys
import types


def _psycopg2_real_carrega() -> bool:
    try:
        import psycopg2  # noqa: F401
        return True
    except Exception:
        return False


def _instalar_substituto() -> None:
    def _recusa(*_a, **_k):
        raise RuntimeError(
            "psycopg2 substituto: este teste tentou abrir conexao de verdade. "
            "A suite e' unitaria -- troque a funcao de banco com monkeypatch."
        )

    psycopg2 = types.ModuleType("psycopg2")
    psycopg2.connect = _recusa
    psycopg2.__version__ = "0.0.0-substituto"

    # psycopg2.extras.RealDictCursor e' usado como cursor_factory; nunca
    # chamado sem conexao, entao um marcador basta.
    extras = types.ModuleType("psycopg2.extras")
    extras.RealDictCursor = type("RealDictCursor", (), {})
    extras.execute_values = _recusa
    extras.Json = type("Json", (), {"__init__": lambda self, v=None: None})

    extensions = types.ModuleType("psycopg2.extensions")
    extensions.ISOLATION_LEVEL_AUTOCOMMIT = 0
    extensions.connection = type("connection", (), {})
    extensions.cursor = type("cursor", (), {})

    pool = types.ModuleType("psycopg2.pool")
    pool.SimpleConnectionPool = _recusa
    pool.ThreadedConnectionPool = _recusa

    # As excecoes precisam ser classes de verdade: o codigo faz
    # `except psycopg2.Error` / `except psycopg2.OperationalError`.
    class Error(Exception):
        pass

    for nome in ("Error", "DatabaseError", "OperationalError", "IntegrityError",
                 "InterfaceError", "ProgrammingError", "DataError",
                 "InternalError", "NotSupportedError"):
        setattr(psycopg2, nome, Error if nome == "Error" else type(nome, (Error,), {}))

    psycopg2.extras = extras
    psycopg2.extensions = extensions
    psycopg2.pool = pool
    for nome, mod in (("psycopg2", psycopg2), ("psycopg2.extras", extras),
                      ("psycopg2.extensions", extensions), ("psycopg2.pool", pool)):
        sys.modules.setdefault(nome, mod)


if not _psycopg2_real_carrega():
    _instalar_substituto()
