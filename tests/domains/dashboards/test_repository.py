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


def _sql(sessao: _SessaoFalsa) -> str:
    return str(sessao.executados[0].compile(dialect=postgresql.dialect()))


def _resultado_de_tuplas(linhas: list[tuple[Any, ...]]) -> _SessaoFalsa:
    sessao = _SessaoFalsa()

    async def execute(query: Any) -> MagicMock:
        sessao.executados.append(query)
        resultado = MagicMock()
        resultado.all.return_value = linhas
        return resultado

    sessao.execute = execute  # type: ignore[method-assign]
    return sessao


async def test_list_invited_links_filtra_vinculos_apos_fechamento() -> None:
    """O público do período exclui vínculos criados/iniciados após o fechamento."""
    link_id = uuid.uuid4()
    sessao = _resultado_de_tuplas([(link_id, None)])
    repository = DashboardRepository(sessao)  # type: ignore[arg-type]

    form = Form(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        name="Ciclo 2026.1",
        status=FormStatus.CLOSED,
        opens_at=datetime(2026, 10, 1, tzinfo=UTC),
        closes_at=datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC),
    )

    convidados = await repository.list_invited_links(form)

    assert [c.link_id for c in convidados] == [link_id]
    sql = _sql(sessao)
    # Organização, papel de respondente e corte no fechamento.
    assert "links.organization_id =" in sql
    # Respondentes e gestores: a gestora também responde.
    assert "links.role IN" in sql
    assert "links.created_at <=" in sql
    assert "links.start_at <=" in sql
    assert "links.end_at IS NULL OR links.end_at >=" in sql
    # O setor vem junto, para o recorte por setor.
    assert "LEFT OUTER JOIN departments" in sql


async def test_list_invited_links_com_publico_individual() -> None:
    """Quando o formulário tem link_id, o público é só aquele vínculo."""
    sessao = _resultado_de_tuplas([])
    repository = DashboardRepository(sessao)  # type: ignore[arg-type]

    form = Form(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        name="Ciclo Individual",
        link_id=uuid.uuid4(),
        status=FormStatus.PUBLISHED,
        opens_at=datetime(2026, 11, 1, tzinfo=UTC),
        closes_at=datetime(2026, 11, 30, tzinfo=UTC),
    )

    await repository.list_invited_links(form)

    assert "links.id =" in _sql(sessao)
