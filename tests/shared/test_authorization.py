"""Testes de app/shared/authorization.py"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.models import RecordStatus, User, UserRole
from app.external_services.keycloak.token import InvalidTokenError
from app.shared.authorization import CurrentUserDep, require_role


class _FakeUserService:
    def __init__(self, user: User | None) -> None:
        self._user = user

    async def get_active_user_by_email(self, email: str) -> User | None:
        return self._user


def _build_user(role: UserRole, email: str = "dev@creed.local") -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        hash_password="irrelevant-hash",  # noqa: S106
        status=RecordStatus.ACTIVE,
        role=role,
    )


def _install_user(app: FastAPI, user: User | None) -> None:
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService(user)


def _install_validate_token(
    monkeypatch: pytest.MonkeyPatch,
    result: Callable[[str], dict[str, Any]] | Exception,
) -> None:
    async def _fake(token: str) -> dict[str, Any]:
        if isinstance(result, Exception):
            raise result
        return result(token)

    monkeypatch.setattr("app.shared.authorization.validate_token", _fake)


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()

    @fastapi_app.get("/public")
    def public() -> dict[str, str]:
        return {"ok": "yes"}

    @fastapi_app.get("/authenticated")
    def authenticated(user: CurrentUserDep) -> dict[str, str]:
        return {"sub": user.sub}

    @fastapi_app.get("/admin", dependencies=[Depends(require_role("admin"))])
    def admin_only() -> dict[str, str]:
        return {"ok": "admin"}

    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_public_route_does_not_require_a_token(client: TestClient) -> None:
    response = client.get("/public")
    assert response.status_code == 200


def test_authenticated_route_without_authorization_header_returns_401(
    client: TestClient,
) -> None:
    response = client.get("/authenticated")
    assert response.status_code == 401


def test_authenticated_route_with_header_missing_bearer_returns_401(
    client: TestClient,
) -> None:
    response = client.get("/authenticated", headers={"Authorization": "Token abc"})
    assert response.status_code == 401


def test_authenticated_route_with_invalid_token_returns_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_validate_token(monkeypatch, InvalidTokenError("invalid signature"))

    response = client.get("/authenticated", headers={"Authorization": "Bearer garbage"})

    assert response.status_code == 401


def test_authenticated_route_with_valid_token_returns_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    _install_validate_token(
        monkeypatch,
        lambda _token: {
            "sub": "user-123",
            "email": "dev@creed.local",
            "realm_access": {"roles": ["admin"]},
        },
    )
    _install_user(app, _build_user(UserRole.ADMIN))

    response = client.get("/authenticated", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 200


def test_route_with_insufficient_role_returns_403_not_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    _install_validate_token(
        monkeypatch,
        lambda _token: {
            "sub": "user-123",
            "email": "x@x.com",
            "realm_access": {"roles": ["respondente"]},
        },
    )
    _install_user(app, _build_user(UserRole.RESPONDENTE, email="x@x.com"))

    response = client.get("/admin", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 403


def test_route_without_any_token_returns_401_not_403(client: TestClient) -> None:
    response = client.get("/admin")
    assert response.status_code == 401


def test_route_with_correct_role_returns_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    _install_validate_token(
        monkeypatch,
        lambda _token: {
            "sub": "user-123",
            "email": "x@x.com",
            "realm_access": {"roles": ["admin"]},
        },
    )
    _install_user(app, _build_user(UserRole.ADMIN, email="x@x.com"))

    response = client.get("/admin", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 200


def test_insufficient_role_does_not_query_the_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    calls = {"count": 0}

    class _SpyService:
        async def get_active_user_by_email(self, email: str) -> User | None:
            calls["count"] += 1
            return None

    app.dependency_overrides[get_user_service] = _SpyService
    _install_validate_token(
        monkeypatch,
        lambda _token: {
            "sub": "user-123",
            "email": "x@x.com",
            "realm_access": {"roles": ["respondente"]},
        },
    )

    response = client.get("/admin", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 403
    assert calls["count"] == 0


def test_role_mismatch_between_token_and_database_returns_401_and_logs_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    app: FastAPI,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _install_validate_token(
        monkeypatch,
        lambda _token: {
            "sub": "user-123",
            "email": "dev@creed.local",
            "realm_access": {"roles": ["admin"]},
        },
    )
    _install_user(app, _build_user(UserRole.RESPONDENTE))

    with caplog.at_level("ERROR"):
        response = client.get("/authenticated", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 401
    assert "Divergência" in caplog.text


def test_user_without_an_active_account_returns_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    _install_validate_token(
        monkeypatch,
        lambda _token: {
            "sub": "user-123",
            "email": "dev@creed.local",
            "realm_access": {"roles": ["admin"]},
        },
    )
    _install_user(app, None)

    response = client.get("/authenticated", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 401
