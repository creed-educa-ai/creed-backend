"""merge heads questions e documents

Revision ID: 22d4bc18cac6
Revises: 00e64ebcc7be, fcd941bc2da4
Create Date: 2026-09-28 20:48:16.615730

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
  [ ] Autogenerate foi lido linha a linha?
  [ ] Renomeação virou drop+create? (perde dados — corrigir para op.alter_column)
  [ ] Mudança destrutiva foi dividida em passos (adicionar -> migrar -> remover)?
  [ ] `alembic heads` conferido antes de abrir o PR?
"""

from collections.abc import Sequence

revision: str = "22d4bc18cac6"
down_revision: tuple[str, str] | None = ("00e64ebcc7be", "fcd941bc2da4")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
