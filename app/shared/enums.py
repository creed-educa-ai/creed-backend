"""Enums usados por mais de um domínio.

Cada enum daqui é **um tipo só no banco**. Duplicar a classe num domínio faria
duas classes Python para o mesmo tipo do Postgres, e a primeira que mudasse
sozinha desalinharia a outra.
"""

import enum


class RecordStatus(enum.Enum):
    """Status de um registro (contrato-api.md: `status`).

    Tipo `recordstatus` no banco, compartilhado por `user` e `participants`.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"


class Dimension(enum.Enum):
    """
    As sete dimensões da Matriz CREED.
    Compartilhado por `questions` (cada pergunta objetiva pertence a uma
    dimensão) e `prismas` (os prismas são médias de dimensões).
    """

    S2 = "S2"  # Vivência e Competências Empreendedoras - questões 16-24 (9 itens)
    S4 = "S4"  # Multiculturalismo na Educação - 25-30 (6)
    S5A = "S5A"  # Metodologias de Inovação - 31-37 (7)
    S5B = "S5B"  # Aprendizagem e Metacognição - 38-45 (8)
    S6 = "S6"  # Ensino Culturalmente Responsivo - 46-51 (6)
    S7 = "S7"  # Competências Culturais, Responsivas e Empreendedoras - 52-57 (6)
    S8 = "S8"  # Inovação e Impacto Social - 58-64 (7)


class Prisma(enum.Enum):
    """Os cinco prismas de análise do produto.

    Tipo `prisma` no banco, compartilhado por `questions` e `insights`. Os
    valores vêm do material do produto sobre a composição dos prismas
    (SP, LA, CE, AC, NP).
    """

    SEGURANCA_PSICOLOGICA = "seguranca_psicologica"
    LIDERANCA_ADAPTATIVA = "lideranca_adaptativa"
    CULTURA_EMPREENDEDORA = "cultura_empreendedora"
    ADAPTABILIDADE_COGNITIVA = "adaptabilidade_cognitiva"
    NEUROINOVACAO_PRISMA = "neuroinovacao_prisma"
