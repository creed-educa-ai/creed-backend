"""Testes do DashboardRepository.

Sem banco: a sessão é um dublê que simula as operações
de persistência e consulta do repository.
"""

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql

from app.domains.dashboards.models import Dashboard
from app.domains.dashboards.repository import DashboardRepository
from app.domains.forms.models import Form, FormStatus


class _SessaoFalsa:
    """Sessão falsa para testar o repository sem acessar o banco."""

    def __init__(
        self,
        resultado: Any = None,
        scalar_val: Any = None,
        scalars_val: list[Any] | None = None,
    ) -> None:
        self.resultado = resultado
        self.scalar_val = scalar_val
        self.scalars_val = scalars_val or []
        self.executados: list[Any] = []
        self.add = MagicMock()
        self.flush = AsyncMock()
        self.refresh = AsyncMock()

    async def execute(self, query: Any) -> MagicMock:
        self.executados.append(query)
        resultado = MagicMock()
        resultado.scalar_one_or_none.return_value = self.resultado
        resultado.scalar.return_value = self.scalar_val
        resultado.scalars.return_value.all.return_value = self.scalars_val
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


async def test_count_invited_respondents_filtra_vinculos_apos_fechamento() -> None:
    """O público do período exclui vínculos criados/iniciados após o fechamento."""
    sessao = _SessaoFalsa(scalar_val=5)
    repository = DashboardRepository(sessao)  # type: ignore[arg-type]

    org_id = uuid.uuid4()
    form = Form(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="Ciclo 2026.1",
        status=FormStatus.CLOSED,
        opens_at=datetime(2026, 10, 1, tzinfo=UTC),
        closes_at=datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC),
    )

    total = await repository.count_invited_respondents(form)
    assert total == 5

    assert len(sessao.executados) == 1
    query_str = str(
        sessao.executados[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}
        )
    )
    # Deve filtrar por organização, papel de respondente, e corte no fechamento
    assert "links.organization_id =" in query_str
    assert "links.role =" in query_str
    assert "links.created_at <=" in query_str
    assert "links.start_at <=" in query_str
    assert "links.end_at IS NULL OR links.end_at >=" in query_str


async def test_count_invited_respondents_com_publico_individual() -> None:
    """Quando o formulário tem link_id, restringe a contagem àquele vínculo específico."""
    sessao = _SessaoFalsa(scalar_val=1)
    repository = DashboardRepository(sessao)  # type: ignore[arg-type]

    link_especifico = uuid.uuid4()
    form = Form(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        name="Ciclo Individual",
        link_id=link_especifico,
        status=FormStatus.PUBLISHED,
        opens_at=datetime(2026, 11, 1, tzinfo=UTC),
        closes_at=datetime(2026, 11, 30, tzinfo=UTC),
    )

    total = await repository.count_invited_respondents(form)
    assert total == 1

    query_str = str(sessao.executados[0].compile(dialect=postgresql.dialect()))
    assert "links.id =" in query_str


async def test_count_invited_respondents_sem_fechamento_usa_momento_atual() -> None:
    """Formulário sem closes_at avalia vínculos ativos no momento da consulta."""
    sessao = _SessaoFalsa(scalar_val=8)
    repository = DashboardRepository(sessao)  # type: ignore[arg-type]

    form = Form(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        name="Demonstracao",
        status=FormStatus.PUBLISHED,
        opens_at=None,
        closes_at=None,
    )

    total = await repository.count_invited_respondents(form)
    assert total == 8

    query_str = str(sessao.executados[0].compile(dialect=postgresql.dialect()))
    assert "links.end_at IS NULL OR links.end_at > now()" in query_str


async def test_get_submitted_form_response_ids_aplica_mesma_regra_do_publico() -> None:
    """Concluídos aplicam a mesma regra de elegibilidade do público com JOIN em links."""
    resp_id = uuid.uuid4()
    sessao = _SessaoFalsa(scalars_val=[resp_id])
    repository = DashboardRepository(sessao)  # type: ignore[arg-type]

    form = Form(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        name="Ciclo Passado",
        status=FormStatus.CLOSED,
        opens_at=datetime(2026, 9, 1, tzinfo=UTC),
        closes_at=datetime(2026, 9, 30, tzinfo=UTC),
    )

    result = await repository.get_submitted_form_response_ids(form)
    assert result == [resp_id]

    query_str = str(sessao.executados[0].compile(dialect=postgresql.dialect()))
    # Deve dar JOIN em links e filtrar papel de respondente e período
    assert "JOIN links ON form_responses.vinculo_id = links.id" in query_str
    assert "form_responses.status =" in query_str
    assert "links.created_at <=" in query_str
    assert "links.start_at <=" in query_str
