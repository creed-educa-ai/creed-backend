"""Acesso a dados do domínio de insights.

Esta camada NÃO contém regra de negócio: só queries e operações de persistência.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.insights.models import Insight, InsightPrisma
from app.shared.enums import Prisma


class InsightPrismaRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_insight(self, insight_id: uuid.UUID) -> Insight | None:
        """Busca o insight que a associação referencia."""
        result = await self.db.execute(select(Insight).where(Insight.id == insight_id))
        return result.scalar_one_or_none()

    async def get(self, insight_id: uuid.UUID, prisma: Prisma) -> InsightPrisma | None:
        """Busca uma associação pelo par que a identifica."""
        result = await self.db.execute(
            select(InsightPrisma).where(
                InsightPrisma.insight_id == insight_id,
                InsightPrisma.prisma == prisma,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_insight(self, insight_id: uuid.UUID) -> list[InsightPrisma]:
        """Lista os prismas associados a um insight."""
        result = await self.db.execute(
            select(InsightPrisma).where(InsightPrisma.insight_id == insight_id)
        )
        return list(result.scalars().all())

    async def insert(self, associacao: InsightPrisma) -> InsightPrisma | None:
        """Grava a associação.

        Devolve `None` se o par foi gravado entre a checagem do service e
        este `flush()` — corrida sem lock, fechada pela chave primária
        composta.
        """
        self.db.add(associacao)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            if "insight_prismas_pkey" not in str(exc.orig):
                raise
            return None
        await self.db.refresh(associacao)
        return associacao

    async def delete(self, associacao: InsightPrisma) -> None:
        """Remove a associação."""
        await self.db.delete(associacao)
        await self.db.flush()
