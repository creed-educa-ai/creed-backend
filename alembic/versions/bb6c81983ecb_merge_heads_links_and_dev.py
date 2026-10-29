"""merge heads links and dev

Revision ID: bb6c81983ecb
Revises: 22d4bc18cac6, b9fa0c109598
Create Date: 2026-09-29 00:05:32.290831

Migration de reconciliação, gerada por `alembic merge` (convenção do projeto —
`../../creed-ai-context/conventions/migrations.md`, regra 3): a branch de `links`
(CREED-32) nasceu de `49ef1d2c7b7e`, e enquanto ela estava aberta a `dev` recebeu
`answer`, `questions` e `documents`, que terminam em `22d4bc18cac6`. Não muda schema
nenhum — só une os dois grafos numa head só.

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
  [x] Autogenerate foi lido linha a linha? Não há autogenerate aqui — `alembic merge`
      não inspeciona `models.py`, só une o histórico. `upgrade`/`downgrade` vazios.
  [x] Renomeação virou drop+create? Não se aplica — nenhuma tabela é tocada.
  [x] Mudança destrutiva foi dividida em passos? Não se aplica — sem mudança de dado.
  [x] `alembic heads` conferido antes de abrir o PR? Head único: `bb6c81983ecb`.
"""

from collections.abc import Sequence

revision: str = "bb6c81983ecb"
down_revision: tuple[str, str] | None = ("22d4bc18cac6", "b9fa0c109598")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
