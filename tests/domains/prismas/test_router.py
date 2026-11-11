"""Testes de app/domains/prismas/router.py."""

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.prismas.dependencies import get_service as get_prisma_service
from app.domains.prismas.router import router
from app.domains.prismas.schemas import FormResponsePrismasRead
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.enums import Dimension, Prisma
from app.shared.exceptions import ForbiddenError, NotFoundError, ValidationError

ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TOKEN = {"Authorization": "Bearer valido"}


class _FakeUserService:
    def __init__(self, access: UserAccess) -> None:
        self._access = access

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self._access


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def autenticar_como(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    organization_id: uuid.UUID = ORGANIZATION_ID,
) -> uuid.UUID:
    email = "dev@creed.example.com"
    link_id = uuid.uuid4()

    async def _fake_validate_token(token: str) -> dict[str, Any]:
        return {"sub": "sub-dev", "email": email, "realm_access": {"roles": [role]}}

    monkeypatch.setattr("app.shared.authorization.validate_token", _fake_validate_token)
    access = UserAccess(
        id=uuid.uuid4(),
        email=email,
        role=role,
        link_id=link_id,
        organization_id=organization_id,
    )
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService(access)
    return link_id


def test_get_prismas_requires_authentication(client: TestClient) -> None:
    resp = client.get(f"/prismas/responses/{uuid.uuid4()}")
    assert resp.status_code == 401


def test_get_prismas_returns_200_and_payload(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    link_id = autenticar_como(app, monkeypatch, "respondente")
    resp_id = uuid.uuid4()
    form_id = uuid.uuid4()

    fake_service = AsyncMock()
    fake_service.calculate_for_form_response.return_value = FormResponsePrismasRead(
        form_response_id=resp_id,
        form_id=form_id,
        vinculo_id=link_id,
        scores={p.value: 4.0 for p in Prisma},
        scores_100={p.value: 80.0 for p in Prisma},
        dimensions={d.value: 4.0 for d in Dimension},
    )
    app.dependency_overrides[get_prisma_service] = lambda: fake_service

    response = client.get(f"/prismas/responses/{resp_id}", headers=TOKEN)
    assert response.status_code == 200
    data = response.json()
    assert data["form_response_id"] == str(resp_id)
    assert data["scores"][Prisma.SEGURANCA_PSICOLOGICA.value] == 4.0
    assert data["scores_100"][Prisma.SEGURANCA_PSICOLOGICA.value] == 80.0


def test_get_prismas_returns_404_when_missing(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "respondente")
    fake_service = AsyncMock()
    fake_service.calculate_for_form_response.side_effect = NotFoundError(
        "Resposta não encontrada"
    )
    app.dependency_overrides[get_prisma_service] = lambda: fake_service

    response = client.get(f"/prismas/responses/{uuid.uuid4()}", headers=TOKEN)
    assert response.status_code == 404


def test_get_prismas_returns_403_when_forbidden(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "respondente")
    fake_service = AsyncMock()
    fake_service.calculate_for_form_response.side_effect = ForbiddenError(
        "Sem acesso a resposta de outro respondente"
    )
    app.dependency_overrides[get_prisma_service] = lambda: fake_service

    response = client.get(f"/prismas/responses/{uuid.uuid4()}", headers=TOKEN)
    assert response.status_code == 403


def test_get_prismas_returns_422_when_validation_fails(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "respondente")
    fake_service = AsyncMock()
    fake_service.calculate_for_form_response.side_effect = ValidationError(
        "O formulário precisa estar finalizado para calcular os prismas"
    )
    app.dependency_overrides[get_prisma_service] = lambda: fake_service

    response = client.get(f"/prismas/responses/{uuid.uuid4()}", headers=TOKEN)
    assert response.status_code == 422
