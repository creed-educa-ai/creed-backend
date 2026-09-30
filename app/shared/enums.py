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
