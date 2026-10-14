"""Regra de negócio do domínio insights.

Esta camada não conhece HTTP nem detalhes de ORM.
"""

import uuid

from app.domains.insights.models import InsightPrisma, Prisma
from app.domains.insights.repository import InsightPrismaRepository
from app.shared.exceptions import ConflictError, NotFoundError


class InsightPrismaService:
    def __init__(self, repository: InsightPrismaRepository) -> None:
        self.repository = repository

    async def associate(self, insight_id: uuid.UUID, prisma: Prisma) -> InsightPrisma:
        """Associa um prisma a um insight.

        Um insight pode ter vários prismas, mas não o mesmo duas vezes.
        """
        insight = await self.repository.get_insight(insight_id)
        if insight is None:
            raise NotFoundError(f"Insight {insight_id} não encontrado")

        existente = await self.repository.get(insight_id, prisma)
        if existente is not None:
            raise ConflictError(
                f"O insight {insight_id} já está associado ao prisma {prisma.value}"
            )

        associacao = InsightPrisma(insight_id=insight_id, prisma=prisma)
        return await self.repository.insert(associacao)

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
