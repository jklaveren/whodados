"""Testes da cifragem de segredos e da checagem de SECRET_KEY."""
from backend.crypto_utils import encrypt_secret, decrypt_secret
import backend.main as m


def test_crypto_roundtrip():
    assert decrypt_secret(encrypt_secret("segredo123")) == "segredo123"


def test_crypto_tolera_texto_puro_legado():
    # Valores antigos (sem prefixo enc:) sao devolvidos como estao.
    assert decrypt_secret("senha-antiga-em-texto") == "senha-antiga-em-texto"


def test_crypto_vazio():
    assert encrypt_secret(None) is None
    assert encrypt_secret("") == ""
    assert decrypt_secret(None) is None


def test_secret_key_padrao_reprova(monkeypatch):
    monkeypatch.setattr(m.settings, "SECRET_KEY", "change-me-in-production-use-strong-secret")
    assert m.secret_key_ok() is False


def test_secret_key_curta_reprova(monkeypatch):
    monkeypatch.setattr(m.settings, "SECRET_KEY", "curta")
    assert m.secret_key_ok() is False


def test_secret_key_forte_aprova(monkeypatch):
    monkeypatch.setattr(m.settings, "SECRET_KEY", "u" * 40)
    assert m.secret_key_ok() is True
