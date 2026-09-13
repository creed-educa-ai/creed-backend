"""create user table

Revision ID: 0b0ad39d779a
Revises:
Create Date: 2026-09-12 22:38:01.073127

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
  [ ] Autogenerate foi lido linha a linha?
  [ ] Renomeação virou drop+create? (perde dados — corrigir para op.alter_column)
  [ ] Mudança destrutiva foi dividida em passos (adicionar -> migrar -> remover)?
  [ ] `alembic heads` conferido antes de abrir o PR?
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0b0ad39d779a"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("keycloak_id", sa.UUID(), nullable=False),
        sa.Column("nome", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "INACTIVE", name="recordstatus"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.Enum("ADMIN", "GESTOR", "RESPONDENTE", name="userrole"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("keycloak_id"),
    )


def downgrade() -> None:
    op.drop_table("user")
