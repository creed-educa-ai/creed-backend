"""form migration

Revision ID: d9f1ff5bf65d
Revises: 49ef1d2c7b7e
Create Date: 2026-09-28 12:55:27.515767

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
  [ ] Autogenerate foi lido linha a linha?
  [ ] Renomeação virou drop+create? (perde dados — corrigir para op.alter_column)
  [ ] Mudança destrutiva foi dividida em passos (adicionar -> migrar -> remover)?
  [ ] `alembic heads` conferido antes de abrir o PR?
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d9f1ff5bf65d"
down_revision: str | None = "49ef1d2c7b7e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        op.f("uq_form_responses_form_id_vinculo_id"),
        table_name="form_responses",
    )
    op.create_unique_constraint(
        "uq_form_responses_form_id_vinculo_id",
        "form_responses",
        ["form_id", "vinculo_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_form_responses_form_id_vinculo_id",
        "form_responses",
        type_="unique",
    )
    op.create_index(
        op.f("uq_form_responses_form_id_vinculo_id"),
        "form_responses",
        ["form_id", "vinculo_id"],
        unique=True,
    )
