"""Testes de app/domains/users/router.py — só contrato HTTP.

A regra do cadastro (e-mail repetido, vínculo inexistente ou já usado) é provada em
`test_service.py`. Aqui se prova o que o service não enxerga: que cada exceção vira o
status certo, que o body sem `link_id` é recusado na borda, e a forma da resposta.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.users.dependencies import get_service
from app.domains.users.models import RecordStatus, User
from app.domains.users.router import router
from app.domains.users.schemas import UserCreate
from app.domains.users.service import CreatedUser
from app.shared.exceptions import ConflictError, NotFoundError

LINK_ID = "3f9a2b1c-4d5e-4f6a-8b7c-9d0e1f2a3b4c"
ORGANIZATION_ID = "8f14e45f-ceea-467e-adde-3f81905dbc1c"

VALID_BODY = {
    "name": "Pessoa Exemplo",
    "email": "pessoa@exemplo.com",
    "keycloak_id": "e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339",
    "link_id": LINK_ID,
}


class _FakeService:
    """Devolve o `CreatedUser` que o service devolveria, ou levanta o erro pedido."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def create_user_service(self, request: UserCreate) -> CreatedUser:
        if self.error is not None:
            raise self.error

        user = User(
            id=uuid.uuid4(),
            keycloak_id=request.keycloak_id,
            name=request.name,
            email=request.email,
            status=RecordStatus.ACTIVE,
            link_id=request.link_id,
            created_at=datetime(2026, 9, 28, tzinfo=UTC),
        )
        return CreatedUser(
            user=user, role="gestor", organization_id=uuid.UUID(ORGANIZATION_ID)
        )


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router, prefix="/api/v1")
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _use(app: FastAPI, service: _FakeService) -> None:
    app.dependency_overrides[get_service] = lambda: service


def test_valid_body_returns_201_with_link_role_and_organization(
    app: FastAPI, client: TestClient
) -> None:
    _use(app, _FakeService())

    response = client.post("/api/v1/users", json=VALID_BODY)

    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "gestor"
    assert body["link_id"] == LINK_ID
    assert body["organization_id"] == ORGANIZATION_ID
    assert "keycloak_id" not in body


def test_without_link_id_returns_422(app: FastAPI, client: TestClient) -> None:
    _use(app, _FakeService())
    body = {k: v for k, v in VALID_BODY.items() if k != "link_id"}

    response = client.post("/api/v1/users", json=body)

    assert response.status_code == 422


def test_unknown_link_returns_404(app: FastAPI, client: TestClient) -> None:
    _use(app, _FakeService(NotFoundError(f"Vínculo {LINK_ID} não encontrado")))

    response = client.post("/api/v1/users", json=VALID_BODY)

    assert response.status_code == 404
    assert LINK_ID in response.json()["detail"]


def test_link_already_used_returns_409(app: FastAPI, client: TestClient) -> None:
    _use(app, _FakeService(ConflictError(f"Vínculo {LINK_ID} já está em uso")))

    response = client.post("/api/v1/users", json=VALID_BODY)

    assert response.status_code == 409
    assert LINK_ID in response.json()["detail"]
