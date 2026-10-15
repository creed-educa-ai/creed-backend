"""Regra de negócio do domínio insights.

Esta camada não conhece HTTP nem detalhes de ORM.
"""

import uuid

from app.domains.insights.models import InsightPrisma
from app.domains.insights.repository import InsightPrismaRepository
from app.shared.enums import Prisma
from app.shared.exceptions import ConflictError, NotFoundError


class InsightPrismaService:
    def __init__(self, repository: InsightPrismaRepository) -> None:
        self.repository = repository

    async def associate(self, insight_id: uuid.UUID, prisma: Prisma) -> InsightPrisma:
        """Associa um prisma a um insight.

        Um insight pode ter vários prismas, mas não o mesmo duas vezes. A
        checagem prévia cobre o caso comum; quem fecha a corrida de duas
        chamadas simultâneas é a chave primária composta, e o `None` que o
        repository devolve nesse caso é traduzido aqui.
        """
        insight = await self.repository.get_insight(insight_id)
        if insight is None:
            raise NotFoundError(f"Insight {insight_id} não encontrado")

        existente = await self.repository.get(insight_id, prisma)
        if existente is not None:
            raise self._conflito_de_associacao(insight_id, prisma)

        associacao = InsightPrisma(insight_id=insight_id, prisma=prisma)
        criada = await self.repository.insert(associacao)

        if criada is None:
            raise self._conflito_de_associacao(insight_id, prisma)

        return criada

    def _conflito_de_associacao(
        self, insight_id: uuid.UUID, prisma: Prisma
    ) -> ConflictError:
        return ConflictError(
            f"O insight {insight_id} já está associado ao prisma {prisma.value}"
        )

    async def list_prismas(self, insight_id: uuid.UUID) -> list[InsightPrisma]:
        """Lista os prismas de um insight."""
        insight = await self.repository.get_insight(insight_id)
        if insight is None:
            raise NotFoundError(f"Insight {insight_id} não encontrado")

        return await self.repository.list_by_insight(insight_id)

    async def dissociate(self, insight_id: uuid.UUID, prisma: Prisma) -> None:
        """Remove a associação entre um insight e um prisma."""
        associacao = await self.repository.get(insight_id, prisma)

        if associacao is None:
            raise NotFoundError(
                f"O insight {insight_id} não está associado ao prisma {prisma.value}"
            )

        await self.repository.delete(associacao)
