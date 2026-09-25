"""une heads documents e form_responses

Revision ID: fa325a57c783
Revises: 49ef1d2c7b7e, 8545e11bd790
Create Date: 2026-09-25 11:33:41.246825

Migration de merge (migrations.md, regra 3): `documents` (8545e11bd790) e
`form_responses` (49ef1d2c7b7e) nasceram em paralelo a partir de 0b0ad39d779a.
Não altera o schema — só junta as duas pontas numa head única.

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
  [x] Autogenerate foi lido linha a linha? (não há autogenerate: upgrade/downgrade vazios)
  [x] Renomeação virou drop+create? (não se aplica)
  [x] Mudança destrutiva foi dividida em passos (adicionar -> migrar -> remover)? (não se aplica)
  [x] `alembic heads` conferido antes de abrir o PR?
"""

from collections.abc import Sequence

revision: str = "fa325a57c783"
down_revision: str | Sequence[str] | None = ("49ef1d2c7b7e", "8545e11bd790")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
