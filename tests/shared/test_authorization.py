"""Testes de app/shared/authorization.py"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.models import RecordStatus, User, UserRole
from app.domains.users.service import UserAccess, UserService
from app.domains.vinculos.models import Roles, VincType, Vinculo
from app.external_services.keycloak.token import InvalidTokenError
from app.shared.authorization import CurrentUserDep, require_role


class _FakeUserService:
    def __init__(self, access: UserAccess | None) -> None:
        self._access = access

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self._access


def _build_access(role: str, email: str = "dev@creed.example.com") -> UserAccess:
    """Um `UserAccess` — o papel aqui é o do vínculo, nunca o de `user.role`."""
    return UserAccess(
        id=uuid.uuid4(),
        email=email,
        role=role,
        vinculo_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
    )


def _install_access(app: FastAPI, access: UserAccess | None) -> None:
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService(access)


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
            "email": "dev@creed.example.com",
            "realm_access": {"roles": ["admin"]},
        },
    )
    _install_access(app, _build_access("admin"))

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
    _install_access(app, _build_access("respondente", email="x@x.com"))

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
    _install_access(app, _build_access("admin", email="x@x.com"))

    response = client.get("/admin", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 200


def test_insufficient_role_does_not_query_the_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    calls = {"count": 0}

    class _SpyService:
        async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
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


def test_role_mismatch_between_token_and_vinculo_returns_401_and_logs_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    app: FastAPI,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Claim diz `admin`, o vínculo diz `respondente` — 401, mesmo com token válido.

    É o teste que prova que a coluna `user.role` deixou de ser lida: o dublê
    (`UserAccess`) nem carrega essa coluna, só o papel do vínculo. Não há como
    a guarda "acertar por acidente" lendo a coluna, porque ela não está aqui.
    """
    _install_validate_token(
        monkeypatch,
        lambda _token: {
            "sub": "user-123",
            "email": "dev@creed.example.com",
            "realm_access": {"roles": ["admin"]},
        },
    )
    _install_access(app, _build_access("respondente"))

    with caplog.at_level("ERROR"):
        response = client.get("/authenticated", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 401
    assert "Divergência" in caplog.text


class _OneUserRepository:
    def __init__(self, user: User) -> None:
        self._user = user

    async def get_user_by_email(self, email: str) -> User | None:
        return self._user if self._user.email == email else None


class _OneVinculoService:
    def __init__(self, vinculo: Vinculo) -> None:
        self._vinculo = vinculo

    async def get_vinculo_by_id_service(self, vinculo_id: uuid.UUID) -> Vinculo | None:
        return self._vinculo if self._vinculo.id == vinculo_id else None


def test_column_says_admin_but_vinculo_says_gestor_returns_401(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    app: FastAPI,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A prova de que `user.role` deixou de ser lida (critério da task 5).

    O `UserService` aqui é o de verdade, só com o banco trocado por dublês. A
    coluna diz `admin`, igual ao claim; o vínculo diz `gestor`. Se alguém
    voltar a ler a coluna em qualquer ponto do caminho, a rota responde 200.
    """
    vinculo = Vinculo(
        id=uuid.uuid4(),
        participant_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        type=VincType.EMPREGO,
        role=Roles.GESTOR,
    )
    user = User(
        id=uuid.uuid4(),
        keycloak_id=uuid.uuid4(),
        name="Dev CREED",
        email="dev@creed.example.com",
        status=RecordStatus.ACTIVE,
        role=UserRole.ADMIN,
        vinculo_id=vinculo.id,
    )
    service = UserService(
        _OneUserRepository(user),  # type: ignore[arg-type]
        _OneVinculoService(vinculo),  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_user_service] = lambda: service
    _install_validate_token(
        monkeypatch,
        lambda _token: {
            "sub": "user-123",
            "email": "dev@creed.example.com",
            "realm_access": {"roles": ["admin"]},
        },
    )

    with caplog.at_level("ERROR"):
        response = client.get("/admin", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 401
    assert "Divergência" in caplog.text


def test_user_without_an_active_account_returns_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    _install_validate_token(
        monkeypatch,
        lambda _token: {
            "sub": "user-123",
            "email": "dev@creed.example.com",
            "realm_access": {"roles": ["admin"]},
        },
    )
    _install_access(app, None)

    response = client.get("/authenticated", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 401


def test_user_without_vinculo_returns_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    """P-008: usuário sem vínculo é usuário sem acesso, mesmo com token válido.

    `UserService.get_active_user_access_by_email` já devolve `None` para esse
    caso (task 4) — aqui só se confirma que a guarda trata `None` como 401.
    """
    _install_validate_token(
        monkeypatch,
        lambda _token: {
            "sub": "user-123",
            "email": "dev@creed.example.com",
            "realm_access": {"roles": ["admin"]},
        },
    )
    _install_access(app, None)

    response = client.get("/admin", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 401
