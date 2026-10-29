"""merge heads links and participants

Revision ID: 87beb54d929a
Revises: d0b345d47e55, bb6c81983ecb
Create Date: 2026-09-29 23:13:12.357629

Migration de reconciliação, gerada por `alembic merge` (convenção do projeto —
`../../creed-ai-context/conventions/migrations.md`, regra 3): a branch de `links`
(CREED-32) terminava em `bb6c81983ecb`, e a `dev` recebeu `forms`, `participants` e a
troca do índice único de `form_responses`, que terminam em `d0b345d47e55`. Não muda
schema nenhum — só une os dois grafos numa head só.

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
  [x] Autogenerate foi lido linha a linha? Não há autogenerate aqui — `alembic merge`
      não inspeciona `models.py`, só une o histórico. `upgrade`/`downgrade` vazios.
  [x] Renomeação virou drop+create? Não se aplica — nenhuma tabela é tocada.
  [x] Mudança destrutiva foi dividida em passos? Não se aplica — sem mudança de dado.
  [x] `alembic heads` conferido antes de abrir o PR? Head único: `87beb54d929a`.
"""

from collections.abc import Sequence

revision: str = "87beb54d929a"
down_revision: tuple[str, str] | None = ("d0b345d47e55", "bb6c81983ecb")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
