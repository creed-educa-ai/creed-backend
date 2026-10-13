"""Regras de negócio do domínio de sectors."""

import uuid

from app.domains.sector.models import Sector
from app.domains.sector.repository import SectorRepository


class SectorService:
    def __init__(self, repository: SectorRepository) -> None:
        self.repository = repository

    async def get_by_id(self, sector_id: uuid.UUID) -> Sector | None:
        """Busca um setor pelo identificador."""
        return await self.repository.get_by_id(sector_id)

    async def create(self, sector: Sector) -> Sector:
        """Cria um setor."""
        return await self.repository.create(sector)
