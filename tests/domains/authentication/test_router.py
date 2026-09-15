"""Testes de app/domains/authentication/router.py — só contrato HTTP"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.authentication.dependencies import get_service
from app.domains.authentication.router import router
from app.domains.authentication.schemas import (
    LoginRequest,
    SessionResponse,
    UserSessionResponse,
)
from app.shared.authorization import AuthenticatedUser, current_user
from app.shared.exceptions import AuthenticationError

FAKE_SESSION = SessionResponse(
    access_token="access-fake",  # noqa: S106
    refresh_token="refresh-fake",  # noqa: S106
    expires_in=900,
    user=UserSessionResponse(id="user-123", email="dev@creed.example.com", role="admin"),
)


class _FakeService:
    def __init__(self, login_ok: bool = True, refresh_ok: bool = True) -> None:
        self.login_ok = login_ok
        self.refresh_ok = refresh_ok

    async def login(self, _data: LoginRequest) -> SessionResponse:
        if not self.login_ok:
            raise AuthenticationError("E-mail ou senha inválidos")
        return FAKE_SESSION

    async def refresh(self, _refresh_token: str) -> SessionResponse:
        if not self.refresh_ok:
            raise AuthenticationError("Sessão expirada, faça login novamente")
        return FAKE_SESSION


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _use_fake_service(app: FastAPI, fake_service: _FakeService) -> None:
    app.dependency_overrides[get_service] = lambda: fake_service


def test_login_with_valid_credentials_returns_200_in_the_contract_shape(
    app: FastAPI, client: TestClient
) -> None:
    _use_fake_service(app, _FakeService(login_ok=True))

    response = client.post(
        "/authentication/login",
        json={"email": "dev@creed.example.com", "password": "dev"},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "refresh_token", "expires_in", "user"}
    assert set(body["user"]) == {
        "id",
        "email",
        "role",
        "vinculo_id",
        "organization_id",
        "organization_name",
    }


def test_login_with_invalid_credentials_returns_401(
    app: FastAPI, client: TestClient
) -> None:
    _use_fake_service(app, _FakeService(login_ok=False))

    response = client.post(
        "/authentication/login",
        json={"email": "dev@creed.example.com", "password": "wrong"},
    )

    assert response.status_code == 401


def test_login_with_invalid_payload_returns_422_not_401(client: TestClient) -> None:
    response = client.post("/authentication/login", json={"email": "a"})

    assert response.status_code == 422


def test_renew_with_valid_refresh_token_returns_200(
    app: FastAPI, client: TestClient
) -> None:
    _use_fake_service(app, _FakeService(refresh_ok=True))

    response = client.post(
        "/authentication/renew", json={"refresh_token": "valid-refresh-token"}
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "access-fake"  # noqa: S105


def test_renew_with_expired_refresh_token_returns_401(
    app: FastAPI, client: TestClient
) -> None:
    _use_fake_service(app, _FakeService(refresh_ok=False))

    response = client.post(
        "/authentication/renew", json={"refresh_token": "expired-refresh-token"}
    )

    assert response.status_code == 401


def test_session_without_authorization_returns_401(client: TestClient) -> None:
    response = client.get("/authentication/session")

    assert response.status_code == 401


def test_session_with_authenticated_user_returns_200(
    app: FastAPI, client: TestClient
) -> None:
    app.dependency_overrides[current_user] = lambda: AuthenticatedUser(
        sub="user-123", email="dev@creed.example.com", roles=["admin"]
    )

    response = client.get(
        "/authentication/session", headers={"Authorization": "Bearer valid"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "user-123"
    assert body["role"] == "admin"
