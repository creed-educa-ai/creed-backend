"""Testes do DashboardRepository.

Sem banco: a sessão é um dublê que simula as operações
de persistência e consulta do repository.
"""

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.domains.dashboards.models import Dashboard
from app.domains.dashboards.repository import DashboardRepository, InsightText
from app.domains.forms.models import Form, FormStatus
from app.domains.insights.models import InsightStatus


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
    # No ambiente do hook do mypy, o `dialect` do SQLAlchemy não tem tipo; no .venv,
    # tem. O `unused-ignore` deixa a mesma linha passar nos dois.
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call, unused-ignore]
    return str(sessao.executados[0].compile(dialect=dialect))


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


def _resultado_de_uma_linha(linha: tuple[Any, ...] | None) -> _SessaoFalsa:
    sessao = _SessaoFalsa()

    async def execute(query: Any) -> MagicMock:
        sessao.executados.append(query)
        resultado = MagicMock()
        resultado.one_or_none.return_value = linha
        return resultado

    sessao.execute = execute  # type: ignore[method-assign]
    return sessao


async def test_get_response_insight_le_a_resposta_enviada_do_vinculo_no_periodo() -> None:
    sessao = _resultado_de_uma_linha(None)
    repository = DashboardRepository(sessao)  # type: ignore[arg-type]

    await repository.get_response_insight(uuid.uuid4(), uuid.uuid4())

    sql = _sql(sessao)
    assert "JOIN form_responses ON form_responses.id = insights.form_response_id" in sql
    assert "form_responses.vinculo_id =" in sql
    assert "form_responses.form_id =" in sql
    # Resposta em andamento não tem insight que a tela mostre.
    assert "form_responses.status =" in sql


async def test_get_response_insight_sem_insight_devolve_none() -> None:
    repository = DashboardRepository(_resultado_de_uma_linha(None))  # type: ignore[arg-type]

    assert await repository.get_response_insight(uuid.uuid4(), uuid.uuid4()) is None


@pytest.mark.parametrize(
    ("gravado", "visto"),
    [
        (InsightStatus.PENDING, "pending"),
        # O pedido que já foi ao N8N aparece como em preparo.
        (InsightStatus.DISPATCHED, "pending"),
        (InsightStatus.DONE, "done"),
        (InsightStatus.FAILED, "failed"),
    ],
)
async def test_get_response_insight_mostra_o_estado_que_a_tela_conhece(
    gravado: InsightStatus, visto: str
) -> None:
    pronto_em = datetime(2026, 10, 8, 13, 30, tzinfo=UTC)
    conteudo = {"analise": ["Um", "Dois"]}
    repository = DashboardRepository(
        _resultado_de_uma_linha((gravado, conteudo, pronto_em))  # type: ignore[arg-type]
    )

    insight = await repository.get_response_insight(uuid.uuid4(), uuid.uuid4())

    assert insight == InsightText(visto, conteudo, pronto_em)  # type: ignore[arg-type]
