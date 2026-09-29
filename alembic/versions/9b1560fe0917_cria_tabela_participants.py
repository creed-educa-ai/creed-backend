"""cria tabela participants

Revision ID: 9b1560fe0917
Revises: 22d4bc18cac6
Create Date: 2026-09-29 07:13:42.875487

Tabela da pessoa (CREED-36). `document_id` aponta para `documents` e é único:
um documento pertence a uma pessoa só ([C3]). A constraint tem nome explícito
(`uq_participants_document_id`) porque o repository a reconhece no
IntegrityError.

`status` usa o tipo `recordstatus` que a migration do `user` (0b0ad39d779a) já
criou. Por isso `create_type=False`: sem ele, o CREATE TABLE tentaria criar o tipo
de novo e quebraria com "type already exists". Pelo mesmo motivo o `downgrade`
não apaga o tipo — quem apaga é o `downgrade` do `user`, que roda depois deste.

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
  [x] Autogenerate foi lido linha a linha? Sim. Saíram a troca de índice por
      constraint em `form_responses`, que veio de carona e é da CREED-344 (PR #27),
      e a criação do tipo `recordstatus`.
  [x] Renomeação virou drop+create? Não há renomeação.
  [x] Mudança destrutiva foi dividida em passos? Não apaga dado: só cria tabela.
  [x] `alembic heads` conferido antes de abrir o PR? Head único.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9b1560fe0917"
down_revision: str | None = "22d4bc18cac6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "participants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("ACTIVE", "INACTIVE", name="recordstatus", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_participants_document_id"),
    )


def downgrade() -> None:
    op.drop_table("participants")
