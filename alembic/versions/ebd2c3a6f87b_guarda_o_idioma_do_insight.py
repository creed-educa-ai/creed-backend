"""guarda o idioma do insight

Revision ID: ebd2c3a6f87b
Revises: 859457af6647
Create Date: 2026-11-18 15:51:35.964019

Consolidação complementar da sprint 5 (ADR-0009). O que entra, com o PR que pediu
na seção "Banco" (#90):

- `insights.language`, `varchar(5)` `NOT NULL` com padrão `'pt-BR'`: o idioma da
  tela no envio da resposta, em que o insight é escrito;
- o `CHECK` `ck_insights_language`, que só aceita `pt-BR`, `en` e `es`.

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
[x] Autogenerate foi lido linha a linha. Ajustes à mão:
    - o `server_default` vai no `add_column`, e não só no model: `insights` já tem
      linhas, e é ele que as preenche (todo insight escrito até aqui é em pt-BR);
    - o `CHECK` foi escrito à mão: o autogenerate deste repo não o detecta, e o
      `alembic check` também não compara CHECK.
[x] Renomeação virou drop+create? Não: só coluna nova.
[x] Mudança destrutiva foi dividida em passos? Não há: a coluna nasce com padrão,
    então não há dado a migrar.
[x] `alembic heads` conferido: um head só, este.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ebd2c3a6f87b"
down_revision: str | None = "859457af6647"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "insights",
        sa.Column(
            "language", sa.String(length=5), server_default="pt-BR", nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_insights_language", "insights", "language IN ('pt-BR', 'en', 'es')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_insights_language", "insights", type_="check")
    op.drop_column("insights", "language")
