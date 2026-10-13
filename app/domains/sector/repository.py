"""Acesso a dados do domínio de sectors.

Esta camada NÃO contém regra de negócio: só queries e persistência.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.sector.models import Sector


class SectorRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, sector_id: uuid.UUID) -> Sector | None:
        """Busca um setor pelo identificador."""
        result = await self.db.execute(select(Sector).where(Sector.id == sector_id))
        return result.scalar_one_or_none()

    async def create(self, sector: Sector) -> Sector:
        """Cria um setor no banco."""
        self.db.add(sector)
        await self.db.flush()
        await self.db.refresh(sector)
        return sector
