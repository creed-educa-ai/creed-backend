"""Testes do DashboardRepository.

Sem banco: a sessão é um dublê que simula as operações
de persistência e consulta do repository.
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.domains.dashboards.models import Dashboard
from app.domains.dashboards.repository import DashboardRepository


class _SessaoFalsa:
    """Sessão falsa para testar o repository sem acessar o banco."""

    def __init__(self, resultado: Dashboard | None = None) -> None:
        self.resultado = resultado
        self.add = MagicMock()
        self.flush = AsyncMock()
        self.refresh = AsyncMock()

    async def execute(self, query: Any) -> MagicMock:
        resultado = MagicMock()
        resultado.scalar_one_or_none.return_value = self.resultado
        return resultado


async def test_criar_dashboard() -> None:
    sessao = _SessaoFalsa()
    repository = DashboardRepository(sessao)  # type: ignore[arg-type]

    dashboard = Dashboard(
        user_id=uuid.uuid4(),
        form_id=uuid.uuid4(),
        is_private=True,
    )

    resultado = await repository.create(dashboard)

    sessao.add.assert_called_once_with(dashboard)
    sessao.flush.assert_awaited_once()
    sessao.refresh.assert_awaited_once_with(dashboard)
    assert resultado is dashboard


async def test_buscar_dashboard_por_id() -> None:
    dashboard = Dashboard(
        user_id=uuid.uuid4(),
        form_id=uuid.uuid4(),
        is_private=True,
    )
    sessao = _SessaoFalsa(resultado=dashboard)
    repository = DashboardRepository(sessao)  # type: ignore[arg-type]

    resultado = await repository.get_by_id(dashboard.id)

    assert resultado is dashboard


async def test_buscar_dashboard_inexistente_devolve_none() -> None:
    sessao = _SessaoFalsa(resultado=None)
    repository = DashboardRepository(sessao)  # type: ignore[arg-type]

    resultado = await repository.get_by_id(uuid.uuid4())

    assert resultado is None
