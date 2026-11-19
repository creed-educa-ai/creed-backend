"""guarda o aceite do termo de consentimento

Revision ID: 859457af6647
Revises: 30d91f60d820
Create Date: 2026-11-17 21:40:00.000000

Consolidação complementar da sprint 5 (ADR-0009). O que entra, com o PR que pediu
na seção "Banco":

- `user.terms_accepted_at`, `timestamptz` nulável: quando a pessoa aceitou o termo
  de consentimento. Nulo = ainda não aceitou.

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
[x] Autogenerate foi lido linha a linha. Sem ajuste à mão: é uma coluna nova.
[x] Renomeação virou drop+create? Não: só coluna nova.
[x] Mudança destrutiva foi dividida em passos? Não há: a coluna é nulável e sem
    padrão, então as linhas que já existem ficam com nulo e veem o termo uma vez.
[x] `alembic heads` conferido antes de abrir o PR.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "859457af6647"
down_revision: str | None = "30d91f60d820"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user", "terms_accepted_at")
