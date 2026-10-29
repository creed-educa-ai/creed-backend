"""une heads participants e form

Revision ID: d0b345d47e55
Revises: f7e122daf2c9, f8eddd2c6655
Create Date: 2026-09-29 19:10:00.000000

Migration de merge (migrations.md, regra 3): a ponta de `participants`
(f7e122daf2c9, CREED-36) e a ponta de `form` (f8eddd2c6655, CREED-33) entraram
em paralelo; as duas já passam pela 0f7193652978. Não altera o schema — só
junta as duas pontas numa head única.

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
  [x] Autogenerate foi lido linha a linha? (não há autogenerate: upgrade/downgrade vazios)
  [x] Renomeação virou drop+create? (não se aplica)
  [x] Mudança destrutiva foi dividida em passos (adicionar -> migrar -> remover)? (não se aplica)
  [x] `alembic heads` conferido antes de abrir o PR?
"""

from collections.abc import Sequence

revision: str = "d0b345d47e55"
down_revision: str | Sequence[str] | None = ("f7e122daf2c9", "f8eddd2c6655")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
