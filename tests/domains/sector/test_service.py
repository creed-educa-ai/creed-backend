"""Testes do service de Sector."""

import uuid

import pytest

from app.domains.sector.models import Sector, SectorType
from app.domains.sector.service import SectorService


class FakeSectorRepository:
    def __init__(self) -> None:
        self.sector: Sector | None = None

    async def get_by_id(self, sector_id: uuid.UUID) -> Sector | None:
        if self.sector and self.sector.id == sector_id:
            return self.sector
        return None

    async def create(self, sector: Sector) -> Sector:
        self.sector = sector
        return sector


@pytest.fixture
def um_sector() -> Sector:
    return Sector(
        id=uuid.uuid4(),
        type=SectorType.TECHNOLOGY,
    )


@pytest.fixture
def repository() -> FakeSectorRepository:
    return FakeSectorRepository()


@pytest.fixture
def service(repository: FakeSectorRepository) -> SectorService:
    return SectorService(repository)  # type: ignore[arg-type]


class TestSectorService:
    @pytest.mark.asyncio
    async def test_get_by_id(
        self,
        service: SectorService,
        repository: FakeSectorRepository,
        um_sector: Sector,
    ) -> None:
        repository.sector = um_sector

        result = await service.get_by_id(um_sector.id)

        assert result == um_sector

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(
        self,
        service: SectorService,
    ) -> None:
        result = await service.get_by_id(uuid.uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_create(
        self,
        service: SectorService,
        um_sector: Sector,
    ) -> None:
        result = await service.create(um_sector)

        assert result == um_sector
