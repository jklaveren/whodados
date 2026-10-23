"""Evals golden dos agentes Claude (cartao 3b).

Exige citação/fonte em todo item (fonte_url obrigatória) — o mesmo padrão
de `agentes-vitrine/evals`. Roda SEM API key: o cliente Anthropic é trocado
por um fake que devolve blocos tool_use prontos.
"""
import backend.agents.enriquecimento_service as svc


class _FakeMessages:
    def __init__(self, blocos):
        self._blocos = blocos

    def create(self, **kwargs):
        assert kwargs["tools"], "agente deve declarar tools (busca + registro)"
        return type("Resp", (), {"content": self._blocos})()


class _FakeCliente:
    def __init__(self, blocos):
        self.messages = _FakeMessages(blocos)


def _tool_use(itens):
    return [type("Bloco", (), {
        "type": "tool_use",
        "name": "registrar_contatos_encontrados",
        "input": {"itens": itens},
    })()]


GOLDEN = [
    {
        "nome": "item com fonte passa",
        "blocos": lambda: _tool_use([{
            "tipo_alvo": "empresa", "nome_alvo": "Advocacia Exemplo",
            "campo": "site", "valor": "https://advocacia-exemplo.com.br",
            "fonte_url": "https://advocacia-exemplo.com.br/contato"}]),
        "espera_min": 1,
    },
    {
        "nome": "item sem fonte é descartado",
        "blocos": lambda: _tool_use([
            {"tipo_alvo": "socio", "nome_alvo": "Fulano",
             "campo": "email", "valor": "fulano@x.com", "fonte_url": ""},
            {"tipo_alvo": "empresa", "nome_alvo": "Advocacia Exemplo",
             "campo": "site", "valor": "https://advocacia-exemplo.com.br",
             "fonte_url": "https://advocacia-exemplo.com.br"}]),
        "espera_min": 1,
    },
    {
        "nome": "nada confiável retorna vazio",
        "blocos": lambda: _tool_use([]),
        "espera_min": 0,
    },
    {
        "nome": "sem tool_use retorna vazio",
        "blocos": lambda: [type("Bloco", (), {"type": "text", "text": "nada"})()],
        "espera_min": 0,
    },
    {
        "nome": "multiplos itens todos com fonte",
        "blocos": lambda: _tool_use([
            {"tipo_alvo": "empresa", "nome_alvo": "Acme",
             "campo": "telefone", "valor": "+55 11 3000-0000",
             "fonte_url": "https://acme.example/contato"},
            {"tipo_alvo": "socio", "nome_alvo": "Ciclana",
             "campo": "linkedin", "valor": "https://linkedin.com/in/ciclana",
             "fonte_url": "https://acme.example/equipe"}]),
        "espera_min": 2,
    },
]


def _rodar(monkeypatch, blocos):
    monkeypatch.setattr(svc, "_cliente", lambda: _FakeCliente(blocos))
    return svc.enriquecer_empresa("Empresa Teste", "São Leopoldo", ["Socio Teste"])


def test_golden_citacao_obrigatoria(monkeypatch):
    for caso in GOLDEN:
        itens = _rodar(monkeypatch, caso["blocos"]())
        assert len(itens) >= caso["espera_min"], f"caso '{caso['nome']}' retornou pouco"
        for item in itens:
            assert item.get("fonte_url"), f"caso '{caso['nome']}': item sem fonte_url: {item}"
            for chave in ("tipo_alvo", "nome_alvo", "campo", "valor"):
                assert item.get(chave), f"caso '{caso['nome']}': sem {chave}: {item}"
