"""Testes do router de Sector."""

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.sector.dependencies import get_service
from app.domains.sector.models import Sector, SectorType
from app.domains.sector.router import router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def um_sector() -> Sector:
    return Sector(
        id=uuid.uuid4(),
        type=SectorType.TECHNOLOGY,
    )


class TestSectorRouter:
    def test_get_sector(
        self,
        app: FastAPI,
        client: TestClient,
        um_sector: Sector,
    ) -> None:
        service = AsyncMock()
        service.get_by_id.return_value = um_sector

        app.dependency_overrides[get_service] = lambda: service

        response = client.get(f"/sectors/{um_sector.id}")

        assert response.status_code == 200
        assert response.json()["id"] == str(um_sector.id)
        service.get_by_id.assert_awaited_once_with(um_sector.id)

        app.dependency_overrides.clear()

    def test_get_sector_not_found(
        self,
        app: FastAPI,
        client: TestClient,
    ) -> None:
        service = AsyncMock()
        service.get_by_id.return_value = None

        app.dependency_overrides[get_service] = lambda: service

        sector_id = uuid.uuid4()
        response = client.get(f"/sectors/{sector_id}")

        assert response.status_code == 404

        app.dependency_overrides.clear()
