"""Cache em memoria para leituras pesadas (analytics + contagens).

Os agregados do dashboard varrem 1,68M de linhas; o mesmo filtro repetido
(navegar entre telas, 2 usuarios com o mesmo funil) nao precisa pagar esse
custo de novo. TTL curto (CACHE_TTL_SECONDS, padrao 300s): dado de
prospeccao tolera minutos de defasagem, e o ETL mensal invalida sozinho.

Limites de proposito: 512 entradas com despejo FIFO, so pra leituras
puras (nunca escrita). Single-processo -- mesma limitacao
ja documentada do cache em memoria; com 2 replicas cada uma tem o seu.
"""
from __future__ import annotations
import functools
import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

try:
    from ..config import settings
except ImportError:  # execucao fora do pacote
    from backend.config import settings

_MAX_ENTRADAS = 512
_cache: OrderedDict = OrderedDict()
_lock = threading.Lock()


def _ttl() -> float:
    try:
        return float(settings.CACHE_TTL_SECONDS)
    except Exception:
        return 300.0


def _chave(nome: str, args: tuple, kwargs: dict) -> str:
    try:
        bruto = json.dumps([nome, args, kwargs], sort_keys=True, default=str)
    except Exception:
        bruto = repr((nome, args, sorted(kwargs.items())))
    return nome + ":" + hashlib.sha256(bruto.encode()).hexdigest()[:32]


def cached(nome: str | None = None, ttl: float | None = None) -> Callable:
    """@cached("resumo") sobre funcoes puras de leitura.

    ttl em segundos sobrepoe o TTL global -- serve pro que so muda quando o
    ETL roda (opcoes de filtro), que nao precisa expirar a cada 5 min.
    """
    def decoradora(fn: Callable) -> Callable:
        chave_nome = nome or fn.__name__

        @functools.wraps(fn)
        def envelope(*args: Any, **kwargs: Any) -> Any:
            chave = _chave(chave_nome, args, kwargs)
            agora = time.monotonic()
            with _lock:
                hit = _cache.get(chave)
                if hit and agora - hit[0] < (ttl if ttl is not None else _ttl()):
                    _cache.move_to_end(chave)
                    return hit[1]
            valor = fn(*args, **kwargs)
            with _lock:
                _cache[chave] = (agora, valor)
                while len(_cache) > _MAX_ENTRADAS:
                    _cache.popitem(last=False)
            return valor

        envelope.cache_clear = limpar  # type: ignore[attr-defined]
        return envelope
    return decoradora


def limpar() -> None:
    with _lock:
        _cache.clear()
