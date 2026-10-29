"""Testes do DashboardService.

O repository é simulado para testar as regras de negócio
sem acessar o banco de dados.
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.domains.dashboards.models import Dashboard
from app.domains.dashboards.repository import DashboardRepository
from app.domains.dashboards.schemas import DashboardCreate
from app.domains.dashboards.service import DashboardService
from app.shared.exceptions import NotFoundError


async def test_criar_dashboard() -> None:
    repository = AsyncMock(spec=DashboardRepository)
    repository.create.side_effect = lambda dashboard: dashboard
    service = DashboardService(repository)

    request = DashboardCreate(
        user_id=uuid.uuid4(),
        form_id=uuid.uuid4(),
        is_private=True,
    )

    resultado = await service.create(request)

    repository.create.assert_awaited_once()
    dashboard_enviado = repository.create.await_args.args[0]

    assert isinstance(dashboard_enviado, Dashboard)
    assert dashboard_enviado.user_id == request.user_id
    assert dashboard_enviado.form_id == request.form_id
    assert dashboard_enviado.is_private is True
    assert resultado is dashboard_enviado


async def test_dashboard_nao_encontrado_lanca_not_found_error() -> None:
    repository = AsyncMock(spec=DashboardRepository)
    repository.get_by_id.return_value = None
    service = DashboardService(repository)

    dashboard_id = uuid.uuid4()

    with pytest.raises(NotFoundError):
        await service.get(dashboard_id)

    repository.get_by_id.assert_awaited_once_with(dashboard_id)
