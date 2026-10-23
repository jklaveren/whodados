"""Titular de firma individual (MEI / empresario individual).

Firma individual nao tem quadro societario na Receita: a pessoa esta' no
proprio nome empresarial, junto de um documento. Na leva de MEIs do Beta
aparecem os tres formatos:

    12.345.678 ANA CLARA DOS SANTOS                 (CNPJ na frente)
    BEATRIZ LIMA DE SOUZA 12345678900     (CPF no fim)
    CARLA MENDES DA SILVA                  (so' o nome)

Quem procurava socio so' em dados_socios nao achava ninguem nessas empresas,
e o documento ia junto no nome da empresa dentro do e-mail.
"""
from __future__ import annotations

import re
from typing import Optional

_CNPJ_NA_FRENTE = re.compile(r"^\s*\d{2}[\.\s]?\d{3}[\.\s]?\d{3}[\s/-]*\d{0,4}[\s-]*\d{0,2}\s+")
_CPF_NO_FIM = re.compile(r"\s+\d{3}\.?\d{3}\.?\d{3}-?\d{2}\s*$")
_TEM_DIGITO = re.compile(r"\d")


def sem_documento(razao_social: Optional[str]) -> str:
    """Nome empresarial sem o CNPJ da frente nem o CPF do fim."""
    texto = (razao_social or "").strip()
    texto = _CNPJ_NA_FRENTE.sub("", texto)
    return _CPF_NO_FIM.sub("", texto).strip()


def titular(razao_social: Optional[str], porte: Optional[str] = None) -> str:
    """Nome da pessoa por tras da firma individual, ou "" se nao for uma.

    O documento colado no nome e' o sinal seguro. Nome sem documento so'
    conta como pessoa quando o porte diz MEI -- senao "PADARIA CENTRAL"
    viraria socio de si mesma.
    """
    texto = (razao_social or "").strip()
    if not texto:
        return ""
    limpo = sem_documento(texto)
    if limpo and limpo != texto:
        return limpo
    if (porte or "").strip().upper() == "MEI" and not _TEM_DIGITO.search(texto):
        return texto
    return ""
