"""consolida as mudanças de banco da sprint 5

Revision ID: 30d91f60d820
Revises: b54ed78ef041
Create Date: 2026-11-16 18:07:08.483127

Consolidação da sprint 5 (ADR-0009). O que entra, com o PR que pediu na seção "Banco":

- a tabela `insights` vira a fila da esteira de IA (ADR-0010), pedida no #78:
  - `organization_id` e `form_id`, obrigatórios, com FK;
  - `form_response_id` passa a ser nulável (nulo = insight da empresa) e único; o
    índice comum sai, porque o `unique` já cria o dele;
  - `status`, no tipo novo `insightstatus`, `attempts`, `next_attempt_at`,
    `dispatched_at`, `last_error`, `model_id`, `prompt_version` e `completed_at`;
  - `content` deixa de ser texto obrigatório e vira `jsonb` nulável;
  - o `CHECK` `ck_insights_done_has_content`, o índice único parcial
    `uq_insights_organization_pending_per_form` e os índices da fila e do dashboard.

Os PRs #75, #76, #77 e #79 a #84 não mudaram `models.py`.

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
[x] Autogenerate foi lido linha a linha. Ajustes à mão:
    - A subida confere que `insights` está vazia: `organization_id` e `form_id` são
      NOT NULL sem padrão, e não há de onde tirá-los. A tabela está vazia em todos
      os ambientes desde a consolidação da sprint 4, que apagou as respostas.
    - O tipo `insightstatus` é criado antes do `add_column`, que não o cria.
    - `content`: text → jsonb com `USING content::jsonb` (o Postgres não converte
      sem `USING`), e o caminho inverso na descida.
    - O `CHECK` `ck_insights_done_has_content` foi escrito à mão: o autogenerate
      deste repo não o detectou, ao contrário do que o #78 registrou. O
      `alembic check` também não compara CHECK, então nada acusaria a falta.
    - A descida também exige a tabela vazia (um pedido `pending` tem `content`
      nulo, que não volta para text NOT NULL) e apaga o tipo `insightstatus` no fim.
[x] Renomeação virou drop+create? Não: só colunas novas e mudança de tipo.
[x] Mudança destrutiva foi dividida em passos? Não há dado a migrar: a tabela está
    vazia, e a subida recusa seguir se não estiver.
[x] `alembic heads` conferido antes de abrir o PR.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "30d91f60d820"
down_revision: str | None = "b54ed78ef041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# O banco grava o NOME do membro de `InsightStatus`, como o `Enum(InsightStatus)` do
# model. `create_type=False`: o tipo é criado à parte, antes da coluna.
INSIGHT_STATUS = postgresql.ENUM(
    "PENDING", "DISPATCHED", "DONE", "FAILED", name="insightstatus", create_type=False
)


def _require_empty_insights(direction: str) -> None:
    """Para a migration com uma mensagem clara se `insights` tiver linhas."""
    rows: int = (
        op.get_bind().execute(sa.text("SELECT count(*) FROM insights")).scalar_one()
    )
    if rows:
        raise RuntimeError(
            f"A {direction} da consolidação da sprint 5 exige a tabela `insights` "
            f"vazia, e ela tem {rows} linha(s). Apague os insights de teste "
            "(e os `insight_prismas` deles) antes de rodar de novo."
        )


def upgrade() -> None:
    _require_empty_insights("subida")

    INSIGHT_STATUS.create(op.get_bind(), checkfirst=True)

    op.add_column("insights", sa.Column("organization_id", sa.UUID(), nullable=False))
    op.add_column("insights", sa.Column("form_id", sa.UUID(), nullable=False))
    op.add_column(
        "insights",
        sa.Column("status", INSIGHT_STATUS, server_default="PENDING", nullable=False),
    )
    op.add_column(
        "insights",
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "insights",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "insights", sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("insights", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("insights", sa.Column("model_id", sa.Text(), nullable=True))
    op.add_column("insights", sa.Column("prompt_version", sa.Text(), nullable=True))
    op.add_column(
        "insights", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.alter_column(
        "insights", "form_response_id", existing_type=sa.UUID(), nullable=True
    )
    op.alter_column(
        "insights",
        "content",
        existing_type=sa.TEXT(),
        type_=postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
        nullable=True,
        postgresql_using="content::jsonb",
    )

    op.create_check_constraint(
        "ck_insights_done_has_content",
        "insights",
        "(status = 'DONE') = (content IS NOT NULL)",
    )
    op.drop_index(op.f("ix_insights_form_response_id"), table_name="insights")
    op.create_unique_constraint(
        "uq_insights_form_response_id", "insights", ["form_response_id"]
    )
    op.create_index(
        "uq_insights_organization_pending_per_form",
        "insights",
        ["organization_id", "form_id"],
        unique=True,
        postgresql_where=sa.text("form_response_id IS NULL AND status = 'PENDING'"),
    )
    op.create_index(
        "ix_insights_status_next_attempt_at",
        "insights",
        ["status", "next_attempt_at"],
        unique=False,
    )
    op.create_index(
        "ix_insights_organization_id_form_id_created_at",
        "insights",
        ["organization_id", "form_id", "created_at"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_insights_organization_id_organizations",
        "insights",
        "organizations",
        ["organization_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_insights_form_id_form", "insights", "form", ["form_id"], ["id"]
    )


def downgrade() -> None:
    _require_empty_insights("descida")

    op.drop_constraint("fk_insights_form_id_form", "insights", type_="foreignkey")
    op.drop_constraint(
        "fk_insights_organization_id_organizations", "insights", type_="foreignkey"
    )
    op.drop_index("ix_insights_organization_id_form_id_created_at", table_name="insights")
    op.drop_index("ix_insights_status_next_attempt_at", table_name="insights")
    op.drop_index(
        "uq_insights_organization_pending_per_form",
        table_name="insights",
        postgresql_where=sa.text("form_response_id IS NULL AND status = 'PENDING'"),
    )
    op.drop_constraint("uq_insights_form_response_id", "insights", type_="unique")
    op.create_index(
        op.f("ix_insights_form_response_id"),
        "insights",
        ["form_response_id"],
        unique=False,
    )
    op.drop_constraint("ck_insights_done_has_content", "insights", type_="check")

    op.alter_column(
        "insights",
        "content",
        existing_type=postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
        type_=sa.TEXT(),
        nullable=False,
        postgresql_using="content::text",
    )
    op.alter_column(
        "insights", "form_response_id", existing_type=sa.UUID(), nullable=False
    )
    op.drop_column("insights", "completed_at")
    op.drop_column("insights", "prompt_version")
    op.drop_column("insights", "model_id")
    op.drop_column("insights", "last_error")
    op.drop_column("insights", "dispatched_at")
    op.drop_column("insights", "next_attempt_at")
    op.drop_column("insights", "attempts")
    op.drop_column("insights", "status")
    op.drop_column("insights", "form_id")
    op.drop_column("insights", "organization_id")

    # O `drop_column` não apaga o tipo, e a próxima subida esbarraria nele.
    INSIGHT_STATUS.drop(op.get_bind(), checkfirst=True)
