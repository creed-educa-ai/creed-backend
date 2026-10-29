"""merge questions e answer

Revision ID: fcd941bc2da4
Revises: a54224f93adf, 40c65a5d6177
Create Date: 2026-09-28 09:33:08.303155

Migration de reconciliação, gerada por `alembic merge` (convenção do projeto —
`../../creed-ai-context/conventions/migrations.md`): a branch de `questions`
(CREED-351/353) e a de `answer` (mesclada em `dev` enquanto esta branch estava aberta)
nasceram do mesmo pai (`49ef1d2c7b7e`) e criaram duas heads. Não muda schema nenhum —
só une os dois grafos numa head só.

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
  [x] Autogenerate foi lido linha a linha? Não há autogenerate aqui — `alembic merge`
      não inspeciona `models.py`, só une o histórico. `upgrade`/`downgrade` vazios.
  [x] Renomeação virou drop+create? Não se aplica — nenhuma tabela é tocada.
  [x] Mudança destrutiva foi dividida em passos? Não se aplica — sem mudança de dado.
  [x] `alembic heads` conferido antes de abrir o PR? Head único: `fcd941bc2da4`.
"""

from collections.abc import Sequence

revision: str = "fcd941bc2da4"
# Merge point: alembic aceita tupla aqui, mas o template do projeto (script.py.mako)
# anota `down_revision` como `str | None` só — certo para migration normal, estreito
# demais para merge. Alargado para bater com o que `branch_labels`/`depends_on` abaixo
# já usam.
down_revision: str | Sequence[str] | None = ("a54224f93adf", "40c65a5d6177")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
