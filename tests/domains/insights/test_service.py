"""Testes dos services do domínio insights.

O repository é simulado para testar as regras de negócio
sem acessar o banco de dados.
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.domains.insights.models import Insight, InsightPrisma
from app.domains.insights.repository import (
    FormScope,
    InsightPrismaRepository,
    InsightRepository,
)
from app.domains.insights.service import InsightPrismaService, InsightService
from app.shared.enums import Prisma
from app.shared.exceptions import ConflictError, NotFoundError


def _um_insight(insight_id: uuid.UUID) -> Insight:
    return Insight(
        id=insight_id,
        form_response_id=uuid.uuid4(),
        content="texto da analise",
    )


async def test_associar_prisma_a_insight_existente() -> None:
    insight_id = uuid.uuid4()
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get_insight.return_value = _um_insight(insight_id)
    repository.get.return_value = None
    repository.insert.side_effect = lambda associacao: associacao
    service = InsightPrismaService(repository)

    resultado = await service.associate(insight_id, Prisma.SEGURANCA_PSICOLOGICA)

    repository.insert.assert_awaited_once()
    enviado = repository.insert.await_args.args[0]

    assert isinstance(enviado, InsightPrisma)
    assert enviado.insight_id == insight_id
    assert enviado.prisma == Prisma.SEGURANCA_PSICOLOGICA
    assert resultado is enviado


async def test_mesmo_insight_aceita_varios_prismas() -> None:
    """A relação é N:N: o insight pode encostar em mais de uma dimensão."""
    insight_id = uuid.uuid4()
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get_insight.return_value = _um_insight(insight_id)
    repository.get.return_value = None
    repository.insert.side_effect = lambda associacao: associacao
    service = InsightPrismaService(repository)

    await service.associate(insight_id, Prisma.SEGURANCA_PSICOLOGICA)
    await service.associate(insight_id, Prisma.LIDERANCA_ADAPTATIVA)

    assert repository.insert.await_count == 2


async def test_associacao_duplicada_lanca_conflict_error() -> None:
    insight_id = uuid.uuid4()
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get_insight.return_value = _um_insight(insight_id)
    repository.get.return_value = InsightPrisma(
        insight_id=insight_id, prisma=Prisma.CULTURA_EMPREENDEDORA
    )
    service = InsightPrismaService(repository)

    with pytest.raises(ConflictError):
        await service.associate(insight_id, Prisma.CULTURA_EMPREENDEDORA)

    repository.insert.assert_not_awaited()


async def test_associar_a_insight_inexistente_lanca_not_found_error() -> None:
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get_insight.return_value = None
    service = InsightPrismaService(repository)

    insight_id = uuid.uuid4()

    with pytest.raises(NotFoundError):
        await service.associate(insight_id, Prisma.NEUROINOVACAO_PRISMA)

    repository.get_insight.assert_awaited_once_with(insight_id)
    repository.insert.assert_not_awaited()


async def test_listar_prismas_de_um_insight() -> None:
    insight_id = uuid.uuid4()
    associacoes = [
        InsightPrisma(insight_id=insight_id, prisma=Prisma.SEGURANCA_PSICOLOGICA),
        InsightPrisma(insight_id=insight_id, prisma=Prisma.LIDERANCA_ADAPTATIVA),
    ]
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get_insight.return_value = _um_insight(insight_id)
    repository.list_by_insight.return_value = associacoes
    service = InsightPrismaService(repository)

    resultado = await service.list_prismas(insight_id)

    assert resultado == associacoes


async def test_listar_de_insight_inexistente_lanca_not_found_error() -> None:
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get_insight.return_value = None
    service = InsightPrismaService(repository)

    with pytest.raises(NotFoundError):
        await service.list_prismas(uuid.uuid4())


async def test_remover_associacao_existente() -> None:
    insight_id = uuid.uuid4()
    associacao = InsightPrisma(
        insight_id=insight_id, prisma=Prisma.ADAPTABILIDADE_COGNITIVA
    )
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get.return_value = associacao
    service = InsightPrismaService(repository)

    await service.dissociate(insight_id, Prisma.ADAPTABILIDADE_COGNITIVA)

    repository.delete.assert_awaited_once_with(associacao)


async def test_remover_associacao_inexistente_lanca_not_found_error() -> None:
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get.return_value = None
    service = InsightPrismaService(repository)

    with pytest.raises(NotFoundError):
        await service.dissociate(uuid.uuid4(), Prisma.SEGURANCA_PSICOLOGICA)

    repository.delete.assert_not_awaited()


async def test_colisao_no_flush_vira_conflict_error() -> None:
    """Quando o par foi gravado entre a checagem e o flush, o repository
    devolve `None` e é aqui que isso vira erro de domínio."""
    insight_id = uuid.uuid4()
    repository = AsyncMock(spec=InsightPrismaRepository)
    repository.get_insight.return_value = _um_insight(insight_id)
    repository.get.return_value = None
    repository.insert.return_value = None
    service = InsightPrismaService(repository)

    with pytest.raises(ConflictError):
        await service.associate(insight_id, Prisma.SEGURANCA_PSICOLOGICA)

    repository.insert.assert_awaited_once()


# --- InsightService: o pedido que o envio da resposta grava (CREED-802) --------


async def test_pedido_individual_leva_organizacao_e_periodo_da_resposta() -> None:
    resposta, organizacao, formulario = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    repository = AsyncMock(spec=InsightRepository)
    repository.get_form_scope.return_value = FormScope(organizacao, formulario)
    repository.create.side_effect = lambda insight: insight
    service = InsightService(repository)

    resultado = await service.request_individual(resposta)

    repository.get_form_scope.assert_awaited_once_with(resposta)
    enviado = repository.create.await_args.args[0]
    assert isinstance(enviado, Insight)
    assert enviado.organization_id == organizacao
    assert enviado.form_id == formulario
    assert enviado.form_response_id == resposta
    # Sem texto e sem estado escolhido aqui: o `pending` é o padrão do model.
    assert enviado.content is None
    assert resultado is enviado


async def test_pedido_de_resposta_inexistente_vira_not_found() -> None:
    repository = AsyncMock(spec=InsightRepository)
    repository.get_form_scope.return_value = None
    service = InsightService(repository)

    with pytest.raises(NotFoundError):
        await service.request_individual(uuid.uuid4())

    repository.create.assert_not_awaited()


async def test_resposta_que_ja_tem_insight_vira_conflict() -> None:
    """P-042: uma resposta, um insight. O repository devolve `None` na corrida."""
    repository = AsyncMock(spec=InsightRepository)
    repository.get_form_scope.return_value = FormScope(uuid.uuid4(), uuid.uuid4())
    repository.create.return_value = None
    service = InsightService(repository)

    with pytest.raises(ConflictError):
        await service.request_individual(uuid.uuid4())
