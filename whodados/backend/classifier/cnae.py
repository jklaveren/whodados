"""Categorizador de CNAE por macro-categoria.

Classifica codigos CNAE em 4 categorias principais para selecao
automatica de templates de e-mail:
  - tecnologia  (secao J: informacao e comunicacao)
  - comercio    (secoes G: comercio; reparacao)
  - industria   (secoes C: industrias; F: construcao)
  - servicos    (demais secoes)

Tambem expoe o mapa CNAE -> categoria e helpers para os templates.
"""

CATEGORIAS = ["tecnologia", "comercio", "industria", "servicos", "todos"]

# Mapeamento por secao CNAE 2.0 -> categoria
# Secoes: A=Agro, B=Extrativa, C=Industria, D=Eletricidade, E=Agua,
# F=Construcao, G=Comercio, H=Transporte, I=Alojamento/Alimentacao,
# J=Informacao/Comunicacao, K=Financeiro, L=Imobiliario, M=Profissionais,
# N=Administrativos, O=Administracao Publica, P=Educacao, Q=Saude,
# R=Artes/Lazer, S=Outros, U=Organismos
SECAO_PARA_CATEGORIA = {
    "A": "servicos",
    "B": "industria",
    "C": "industria",
    "D": "industria",
    "E": "industria",
    "F": "industria",
    "G": "comercio",
    "H": "servicos",
    "I": "servicos",
    "J": "tecnologia",
    "K": "servicos",
    "L": "servicos",
    "M": "servicos",
    "N": "servicos",
    "O": "servicos",
    "P": "servicos",
    "Q": "servicos",
    "R": "servicos",
    "S": "servicos",
    "T": "servicos",
    "U": "servicos",
}


def classificar_cnae(cnae: str) -> str:
    """Classifica um codigo CNAE (string ou numero) em uma das 4 categorias.

    Aceita formatos: '6201-1/00', '6201-1', '62.11-0', '6201100', '62'.
    Usa os 2 primeiros digitos para classificar a secao CNAE 2.0:
      - Industria (C): 10-33
      - Construcao/Energia: 35-43
      - Comercio (G): 45-47
      - Tecnologia (J): 58-63
      - Demais: servicos
    """
    if not cnae:
        return "servicos"
    s = str(cnae).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return "servicos"

    if len(digits) >= 2:
        d2 = int(digits[:2])

        # Industria (C): 10-33
        if 10 <= d2 <= 33:
            return "industria"
        # Construcao/Energia (D-E): 35-43
        if 35 <= d2 <= 43:
            return "industria"
        # Comercio (G): 45-47
        if 45 <= d2 <= 47:
            return "comercio"
        # Tecnologia/Informacao (J): 58-63
        if 58 <= d2 <= 63:
            return "tecnologia"
        # Demais: servicos
        return "servicos"

    return "servicos"


def categorias_disponiveis() -> list:
    """Retorna lista de categorias suportadas (para exibir no dropdown)."""
    return [
        {"key": "tecnologia", "label": "Tecnologia / TI", "icon": "💻"},
        {"key": "comercio", "label": "Comercio / Varejo", "icon": "🛒"},
        {"key": "industria", "label": "Industria / Fabril", "icon": "🏭"},
        {"key": "servicos", "label": "Servicos em Geral", "icon": "🏢"},
        {"key": "todos", "label": "Padrao (todas)", "icon": "🌐"},
    ]