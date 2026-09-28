"""Acesso a dados do domínio de vinculos.

Esta camada NÃO contém regra de negócio: só queries e agregações.
Agregação pesada é empurrada para o Postgres, nunca feita em memória.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.vinculos.models import Vinculo


class VinculoRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def insert(self, vinculo: Vinculo) -> Vinculo:
        """Grava um vínculo no banco."""
        self.db.add(vinculo)
        await self.db.flush()
        await self.db.refresh(vinculo)
        return vinculo

    async def get_by_id(self, vinculo_id: uuid.UUID) -> Vinculo | None:
        result = await self.db.execute(select(Vinculo).where(Vinculo.id == vinculo_id))
        return result.scalar_one_or_none()
