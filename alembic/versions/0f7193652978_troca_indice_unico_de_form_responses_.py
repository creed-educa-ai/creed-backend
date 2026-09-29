"""troca indice unico de form_responses por unique constraint

Revision ID: 0f7193652978
Revises: 22d4bc18cac6
Create Date: 2026-09-25 12:34:58.384780

A 49ef1d2c7b7e criou a unicidade (form_id, vinculo_id) como índice único, mas o
model declara UniqueConstraint — o padrão do projeto (`user`, `documents`). A
divergência fazia todo autogenerate propor esta troca. Mesmo nome, mesmas
colunas: a regra "uma resposta por vínculo e formulário" não muda.

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
  [x] Autogenerate foi lido linha a linha? Só as duas operações da troca; ordem
      conferida (o índice sai antes porque a constraint reusa o nome).
  [x] Renomeação virou drop+create? Não há renomeação de coluna ou tabela.
  [x] Mudança destrutiva foi dividida em passos? Não apaga dado: o índice que sai
      é recriado como constraint na mesma transação.
  [x] `alembic heads` conferido antes de abrir o PR? Head único.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0f7193652978"
down_revision: str | None = "22d4bc18cac6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_form_responses_form_id_vinculo_id", table_name="form_responses")
    op.create_unique_constraint(
        "uq_form_responses_form_id_vinculo_id",
        "form_responses",
        ["form_id", "vinculo_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_form_responses_form_id_vinculo_id", "form_responses", type_="unique"
    )
    op.create_index(
        "uq_form_responses_form_id_vinculo_id",
        "form_responses",
        ["form_id", "vinculo_id"],
        unique=True,
    )
