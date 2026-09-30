"""Registro de todas as tabelas do backend (CREED-365).

O SQLAlchemy só conhece uma tabela depois que o `models.py` dela é importado. Uma
FK escrita como texto — `ForeignKey("documents.id")` — só resolve se `documents`
já estiver no `Base.metadata`; senão o flush quebra com `NoReferencedTableError`.
E o autogenerate do Alembic trata tabela que não conhece como tabela a apagar.

Importar este módulo carrega todos os models de uma vez. É o que fazem
`app/main.py`, `alembic/env.py` e os `scripts/`, em vez de cada um manter a
própria lista.

Domínio novo: uma linha aqui, em ordem alfabética. `tests/test_arquitetura.py`
reprova `models.py` de domínio que ficar de fora.
"""

from app.domains.dashboards import models as dashboards_models  # noqa: F401
from app.domains.documents import models as documents_models  # noqa: F401
from app.domains.forms import models as forms_models  # noqa: F401
from app.domains.organizacoes import models as organizacoes_models  # noqa: F401
from app.domains.participants import models as participants_models  # noqa: F401
from app.domains.prismas import models as prismas_models  # noqa: F401
from app.domains.prognosticos import models as prognosticos_models  # noqa: F401
from app.domains.questions import models as questions_models  # noqa: F401
from app.domains.relatorios import models as relatorios_models  # noqa: F401
from app.domains.responses import models as responses_models  # noqa: F401
from app.domains.users import models as users_models  # noqa: F401
