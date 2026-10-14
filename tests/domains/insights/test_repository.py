"""Testes do InsightPrismaRepository.

Sem banco: a sessão é um dublê que simula as operações
de persistência e consulta do repository.
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.domains.insights.models import InsightPrisma, Prisma
from app.domains.insights.repository import InsightPrismaRepository


class _SessaoFalsa:
    """Sessão falsa para testar o repository sem acessar o banco."""

    def __init__(
        self,
        resultado: object | None = None,
        lista: list[InsightPrisma] | None = None,
    ) -> None:
        self.resultado = resultado
        self.lista = lista or []
        self.add = MagicMock()
        self.flush = AsyncMock()
        self.refresh = AsyncMock()
        self.delete = AsyncMock()

    async def execute(self, query: Any) -> MagicMock:
        resultado = MagicMock()
        resultado.scalar_one_or_none.return_value = self.resultado
        resultado.scalars.return_value.all.return_value = self.lista
        return resultado


async def test_inserir_associacao() -> None:
    sessao = _SessaoFalsa()
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    associacao = InsightPrisma(
        insight_id=uuid.uuid4(), prisma=Prisma.SEGURANCA_PSICOLOGICA
    )

    resultado = await repository.insert(associacao)

    sessao.add.assert_called_once_with(associacao)
    sessao.flush.assert_awaited_once()
    sessao.refresh.assert_awaited_once_with(associacao)
    assert resultado is associacao


async def test_buscar_associacao_pelo_par() -> None:
    associacao = InsightPrisma(
        insight_id=uuid.uuid4(), prisma=Prisma.LIDERANCA_ADAPTATIVA
    )
    sessao = _SessaoFalsa(resultado=associacao)
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    resultado = await repository.get(associacao.insight_id, Prisma.LIDERANCA_ADAPTATIVA)

    assert resultado is associacao


async def test_buscar_associacao_inexistente_devolve_none() -> None:
    """A camada de banco não decide: devolve nada e deixa a regra decidir."""
    sessao = _SessaoFalsa(resultado=None)
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    resultado = await repository.get(uuid.uuid4(), Prisma.CULTURA_EMPREENDEDORA)

    assert resultado is None


async def test_listar_prismas_de_um_insight() -> None:
    insight_id = uuid.uuid4()
    associacoes = [
        InsightPrisma(insight_id=insight_id, prisma=Prisma.SEGURANCA_PSICOLOGICA),
        InsightPrisma(insight_id=insight_id, prisma=Prisma.NEUROINOVACAO_PRISMA),
    ]
    sessao = _SessaoFalsa(lista=associacoes)
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    resultado = await repository.list_by_insight(insight_id)

    assert resultado == associacoes


async def test_listar_de_insight_sem_prismas_devolve_lista_vazia() -> None:
    sessao = _SessaoFalsa(lista=[])
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    resultado = await repository.list_by_insight(uuid.uuid4())

    assert resultado == []


async def test_remover_associacao() -> None:
    sessao = _SessaoFalsa()
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    associacao = InsightPrisma(
        insight_id=uuid.uuid4(), prisma=Prisma.ADAPTABILIDADE_COGNITIVA
    )

    await repository.delete(associacao)

    sessao.delete.assert_awaited_once_with(associacao)
    sessao.flush.assert_awaited_once()
