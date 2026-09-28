"""une heads documents e answer

Revision ID: 00e64ebcc7be
Revises: fa325a57c783, 40c65a5d6177
Create Date: 2026-09-28 17:35:42.231852

Migration de merge (migrations.md, regra 3): a ponta de `documents`
(fa325a57c783, que já unia documents e form_responses) e `answer`
(40c65a5d6177, que entrou na dev pelo PR #20) nasceram em paralelo a partir de
49ef1d2c7b7e. Não altera o schema — só junta as duas pontas numa head única.

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
  [x] Autogenerate foi lido linha a linha? (não há autogenerate: upgrade/downgrade vazios)
  [x] Renomeação virou drop+create? (não se aplica)
  [x] Mudança destrutiva foi dividida em passos (adicionar -> migrar -> remover)? (não se aplica)
  [x] `alembic heads` conferido antes de abrir o PR?
"""

from collections.abc import Sequence

revision: str = "00e64ebcc7be"
down_revision: str | Sequence[str] | None = ("fa325a57c783", "40c65a5d6177")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
