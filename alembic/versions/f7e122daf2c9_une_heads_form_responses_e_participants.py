"""une heads form_responses e participants

Revision ID: f7e122daf2c9
Revises: 0f7193652978, 9b1560fe0917
Create Date: 2026-09-29 12:40:42.612916

Migration de merge (migrations.md, regra 3): a unique constraint de
`form_responses` (0f7193652978, CREED-344) e a tabela `participants`
(9b1560fe0917, CREED-36) nasceram em paralelo a partir de 22d4bc18cac6.
Não altera o schema — só junta as duas pontas numa head única.

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
  [x] Autogenerate foi lido linha a linha? (não há autogenerate: upgrade/downgrade vazios)
  [x] Renomeação virou drop+create? (não se aplica)
  [x] Mudança destrutiva foi dividida em passos (adicionar -> migrar -> remover)? (não se aplica)
  [x] `alembic heads` conferido antes de abrir o PR?
"""

from collections.abc import Sequence

revision: str = "f7e122daf2c9"
down_revision: str | Sequence[str] | None = ("0f7193652978", "9b1560fe0917")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
