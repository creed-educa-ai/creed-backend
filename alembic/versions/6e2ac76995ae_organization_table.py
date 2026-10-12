"""organization_table

Revision ID: 6e2ac76995ae
Revises: d53324b9b5a2
Create Date: 2026-10-10 12:09:52.059252

Tabela da organização (CREED-38, subtarefa CREED-381). `document_id` aponta para
`documents`, é obrigatório (a tabela da CREED-381 marca `not null`) e é único: um
documento pertence a uma organização só ([C3]). A constraint tem nome explícito
(`uq_organizations_document_id`) porque o repository vai reconhecê-la no
IntegrityError.

`status` usa o tipo `recordstatus` que a migration do `user` (0b0ad39d779a) já
criou. Por isso `create_type=False`: sem ele, o CREATE TABLE tentaria criar o tipo
de novo e quebraria com "type already exists". Pelo mesmo motivo o `downgrade`
não apaga o tipo.

A FK de `links.organization_id` para esta tabela não entra aqui: `links` já tem
linhas, e ligar a FK pede decidir o que fazer com as que apontam para organização
inexistente. Fica para a próxima subtarefa da CREED-38.

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
  [x] Autogenerate foi lido linha a linha? Sim. Saiu a criação da tabela `insights`
      (e do índice dela), que veio de carona: o model existe em
      `app/domains/insights/models.py`, mas a migration é de outra tarefa. Trocado
      `sa.Enum` por `postgresql.ENUM(..., create_type=False)`.
  [x] Renomeação virou drop+create? Não há renomeação.
  [x] Mudança destrutiva foi dividida em passos? Não apaga dado: só cria tabela.
  [x] `alembic heads` conferido antes de abrir o PR? Head único.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6e2ac76995ae"
down_revision: str | None = "d53324b9b5a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
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
        sa.UniqueConstraint("document_id", name="uq_organizations_document_id"),
    )


def downgrade() -> None:
    op.drop_table("organizations")
