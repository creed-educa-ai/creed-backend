"""merge form table and form responses migrations

Revision ID: f8eddd2c6655
Revises: 045eca33fb4c, 0f7193652978
Create Date: 2026-09-29 18:08:03.069302

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
  [ ] Autogenerate foi lido linha a linha?
  [ ] Renomeação virou drop+create? (perde dados — corrigir para op.alter_column)
  [ ] Mudança destrutiva foi dividida em passos (adicionar -> migrar -> remover)?
  [ ] `alembic heads` conferido antes de abrir o PR?
"""

from collections.abc import Sequence

revision: str = "f8eddd2c6655"
down_revision = ("045eca33fb4c", "0f7193652978")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
