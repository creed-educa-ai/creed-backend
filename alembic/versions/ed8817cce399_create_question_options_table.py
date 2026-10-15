"""create question options table

Revision ID: ed8817cce399
Revises: d53324b9b5a2
Create Date: 2026-10-14 23:03:59.203376

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
[x] Autogenerate foi lido linha a linha — removidos os create_table/create_index de
    `dashboards` e `insights` (e os drop correspondentes no downgrade): o autogenerate
    os incluiu porque os models existem em `dev` mas as migrations deles ainda não,
    então não são desta migration (a CREED-37 só cria `question_options`).
[x] Renomeação virou drop+create? — não houve renomeação; tabela nova.
[x] Mudança destrutiva foi dividida em passos — não há alteração destrutiva;
    `question_options` nasce vazia.
[x] `alembic heads` conferido antes de abrir o PR — uma única head.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ed8817cce399"
down_revision: str | None = "d53324b9b5a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "question_options",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("question_id", sa.UUID(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.id"],
            name="fk_question_options_question_id_questions",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_id",
            "order_index",
            name="uq_question_options_question_id_order_index",
        ),
    )
    op.create_index(
        op.f("ix_question_options_question_id"),
        "question_options",
        ["question_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_question_options_question_id"), table_name="question_options")
    op.drop_table("question_options")
