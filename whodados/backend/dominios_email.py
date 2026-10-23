"""Que tipo de dominio e' o do e-mail de um contato.

A Receita guarda o e-mail do contador, do empregador ou um e-mail digitado errado, entao "dominio
proprio" nao quer dizer "tem site". Esta classificacao e' a mesma da analise de sites
e do filtro 'com site' do WhatsApp.

  provedor         gmail.com, hotmail.com... (nao tem site proprio)
  erro_digitacao   gamil.com, gmai.com, 2010hotmail.com... (nao chega ao dono)
  instituicao      .gov.br, .edu.br, universidades
  provedor_antigo  brturbo, ibest... (caixas de provedores que acabaram)
  contabilidade    escritorio de contabilidade (o e-mail da Receita costuma ser o do contador)
  empresa          dominio proprio: candidato a ter site
  vazio            contato sem e-mail
"""
import re
from typing import Optional

PROVEDORES = ["gmail.com", "hotmail.com", "outlook.com", "yahoo.com.br", "yahoo.com", "live.com", "icloud.com",
              "bol.com.br", "uol.com.br", "terra.com.br", "ig.com.br", "msn.com", "hotmail.com.br", "outlook.com.br",
              "globo.com", "oi.com.br", "me.com", "protonmail.com", "gmail.com.br"]
# Outros provedores REAIS: nao sao erro de ninguem.
OUTROS_REAIS = ["ymail.com", "mail.com", "rocketmail.com", "aol.com", "gmx.com", "gmx.net", "zoho.com", "yandex.com",
                "proton.me", "pm.me", "hey.com", "fastmail.com", "tutanota.com", "email.com", "inbox.com"]
CONHECIDOS = set(PROVEDORES) | set(OUTROS_REAIS)

INSTITUICOES = ("univates", "ulbra", "ucs.br", "faccat", "unochapeco", "unisinos", "feevale", "unisc", "ufrgs",
                "pucrs", "unipampa", "ufsm", "senac", "senai", "sebrae")
LEGADOS = ("brturbo.com.br", "ibest.com.br", "net11.com.br", "tca.com.br", "sinos.net", "viavale.com.br",
           "zipmail.com.br", "pop.com.br", "via-rs.net", "vetorial.com.br", "ig.com", "bol.com")


def distancia(a: str, b: str) -> int:
    """Levenshtein simples (dominios sao curtos)."""
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        atual = [i]
        for j, cb in enumerate(b, 1):
            atual.append(min(anterior[j] + 1, atual[j - 1] + 1, anterior[j - 1] + (ca != cb)))
        anterior = atual
    return anterior[-1]


def correcao(dominio: str) -> Optional[str]:
    """Provedor conhecido a ate' 2 letras de distancia, ou o nome do provedor colado a lixo
    (2010hotmail.com, 10gmail.com). None se o dominio nao parece erro de digitacao."""
    if dominio in CONHECIDOS:
        return None
    for p in ("gmail", "hotmail", "outlook", "yahoo"):
        if p in dominio.split(".")[0]:
            return p + (".com.br" if p == "yahoo" else ".com")
    melhor = min(PROVEDORES, key=lambda p: distancia(dominio, p))
    return melhor if distancia(dominio, melhor) <= 2 else None


def classificar(email: Optional[str]) -> str:
    email = (email or "").strip().lower()
    if "@" not in email:
        return "vazio"
    d = email.rsplit("@", 1)[1]
    if d in CONHECIDOS:
        return "provedor"
    if correcao(d):
        return "erro_digitacao"
    if d.endswith((".gov.br", ".edu.br", ".mil.br", ".jus.br", ".leg.br")) or any(x in d for x in INSTITUICOES):
        return "instituicao"
    if d in LEGADOS:
        return "provedor_antigo"
    rotulo = d.split(".")[0]
    if rotulo.startswith("cont") or re.search(r"contab|fiscal|assessor|escritor|despach|consult", rotulo):
        return "contabilidade"
    return "empresa"


def dominio_de(email: Optional[str]) -> str:
    email = (email or "").strip().lower()
    return email.rsplit("@", 1)[1] if "@" in email else ""
