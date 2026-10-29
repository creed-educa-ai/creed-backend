"""Testes do router de Department."""

import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.department.dependencies import get_service
from app.domains.department.models import Department, DepartmentType
from app.domains.department.router import router
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.exceptions import NotFoundError, ValidationError

TOKEN = {"Authorization": "Bearer valido"}


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def um_department() -> Department:
    return Department(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        type=DepartmentType.TECNOLOGIA_INFORMACAO,
    )


@pytest.fixture
def service_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture(autouse=True)
def limpar_overrides(app: FastAPI) -> Generator[None, None, None]:
    yield
    app.dependency_overrides.clear()


class _FakeUserService:
    def __init__(self, access: UserAccess) -> None:
        self._access = access

    async def get_active_user_access_by_email(
        self,
        email: str,
    ) -> UserAccess | None:
        return self._access


def autenticar_como(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    """Simula um token válido e um usuário ativo com o papel indicado."""
    email = "dev@creed.example.com"

    async def fake_validate_token(token: str) -> dict[str, Any]:
        return {
            "sub": "sub-dev",
            "email": email,
            "realm_access": {"roles": [role]},
        }

    monkeypatch.setattr(
        "app.shared.authorization.validate_token",
        fake_validate_token,
    )

    access = UserAccess(
        id=uuid.uuid4(),
        email=email,
        role=role,
        link_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
    )
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService(access)


class TestDepartmentRouter:
    def test_get_department_returns_200(
        self,
        app: FastAPI,
        client: TestClient,
        service_mock: AsyncMock,
        um_department: Department,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        service_mock.get_by_id.return_value = um_department
        app.dependency_overrides[get_service] = lambda: service_mock

        response = client.get(
            f"/department/{um_department.id}",
            headers=TOKEN,
        )

        assert response.status_code == 200
        assert response.json()["id"] == str(um_department.id)
        assert response.json()["organization_id"] == str(um_department.organization_id)
        service_mock.get_by_id.assert_awaited_once_with(um_department.id)

    def test_get_department_without_token_returns_401(
        self,
        app: FastAPI,
        client: TestClient,
        service_mock: AsyncMock,
    ) -> None:
        app.dependency_overrides[get_service] = lambda: service_mock

        response = client.get(f"/department/{uuid.uuid4()}")

        assert response.status_code == 401
        service_mock.get_by_id.assert_not_awaited()

    def test_get_department_not_found_returns_404(
        self,
        app: FastAPI,
        client: TestClient,
        service_mock: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        service_mock.get_by_id.side_effect = NotFoundError("Departamento não encontrado")
        app.dependency_overrides[get_service] = lambda: service_mock

        response = client.get(
            f"/department/{uuid.uuid4()}",
            headers=TOKEN,
        )

        assert response.status_code == 404

    def test_create_department_returns_201(
        self,
        app: FastAPI,
        client: TestClient,
        service_mock: AsyncMock,
        um_department: Department,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        service_mock.create.return_value = um_department
        app.dependency_overrides[get_service] = lambda: service_mock

        response = client.post(
            "/department",
            json={
                "organization_id": str(um_department.organization_id),
                "type": um_department.type.value,
            },
            headers=TOKEN,
        )

        assert response.status_code == 201
        assert response.json()["id"] == str(um_department.id)
        service_mock.create.assert_awaited_once()

    def test_create_department_with_unknown_organization_returns_422(
        self,
        app: FastAPI,
        client: TestClient,
        service_mock: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Prova só a tradução do router: `ValidationError` -> 422 com texto."""
        autenticar_como(app, monkeypatch, "admin")
        organization_id = uuid.uuid4()
        service_mock.create.side_effect = ValidationError(
            f"Organização {organization_id} não encontrada"
        )
        app.dependency_overrides[get_service] = lambda: service_mock

        response = client.post(
            "/department",
            json={
                "organization_id": str(organization_id),
                "type": DepartmentType.MARKETING.value,
            },
            headers=TOKEN,
        )

        assert response.status_code == 422
        assert response.json()["detail"] == (
            f"Organização {organization_id} não encontrada"
        )

    def test_create_department_without_token_returns_401(
        self,
        app: FastAPI,
        client: TestClient,
        service_mock: AsyncMock,
    ) -> None:
        app.dependency_overrides[get_service] = lambda: service_mock

        response = client.post(
            "/department",
            json={
                "organization_id": str(uuid.uuid4()),
                "type": DepartmentType.TECNOLOGIA_INFORMACAO.value,
            },
        )

        assert response.status_code == 401
        service_mock.create.assert_not_awaited()

    def test_create_department_with_non_admin_returns_403(
        self,
        app: FastAPI,
        client: TestClient,
        service_mock: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        autenticar_como(app, monkeypatch, "respondente")
        app.dependency_overrides[get_service] = lambda: service_mock

        response = client.post(
            "/department",
            json={
                "organization_id": str(uuid.uuid4()),
                "type": DepartmentType.TECNOLOGIA_INFORMACAO.value,
            },
            headers=TOKEN,
        )

        assert response.status_code == 403
        service_mock.create.assert_not_awaited()

    def test_create_department_with_invalid_type_returns_422(
        self,
        app: FastAPI,
        client: TestClient,
        service_mock: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        app.dependency_overrides[get_service] = lambda: service_mock

        response = client.post(
            "/department",
            json={
                "organization_id": str(uuid.uuid4()),
                "type": "invalid_type",
            },
            headers=TOKEN,
        )

        assert response.status_code == 422
        service_mock.create.assert_not_awaited()
