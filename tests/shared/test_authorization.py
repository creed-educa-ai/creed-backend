"""Testes de app/shared/authorization.py"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.domains.links.models import Link, LinkType, Roles
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.models import User
from app.domains.users.service import UserAccess, UserService
from app.external_services.keycloak.token import InvalidTokenError
from app.shared.authorization import CurrentUserDep, require_role
from app.shared.enums import RecordStatus


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
        link_id=uuid.uuid4(),
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


def test_role_mismatch_between_token_and_link_returns_401_and_logs_error(
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


def test_token_with_two_roles_is_judged_by_the_link_role(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    """Token com `admin` e `gestor`, vínculo `gestor`: a rota admin responde 403.

    O papel do vínculo está entre os do token, então não há divergência (401). Mas
    quem decide a rota é o vínculo, não o `admin` a mais no realm, que é
    configurado à mão (review da CREED-32).
    """
    _install_validate_token(
        monkeypatch,
        lambda _token: {
            "sub": "user-123",
            "email": "dev@creed.example.com",
            "realm_access": {"roles": ["admin", "gestor"]},
        },
    )
    _install_access(app, _build_access("gestor"))

    response = client.get("/admin", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 403


def test_token_with_two_roles_passes_when_the_link_has_the_route_role(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    """O par do teste acima: token com dois papéis não é recusado por si só."""
    _install_validate_token(
        monkeypatch,
        lambda _token: {
            "sub": "user-123",
            "email": "dev@creed.example.com",
            "realm_access": {"roles": ["admin", "gestor"]},
        },
    )
    _install_access(app, _build_access("admin"))

    response = client.get("/admin", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 200


class _OneUserRepository:
    def __init__(self, user: User) -> None:
        self._user = user

    async def get_user_by_email(self, email: str) -> User | None:
        return self._user if self._user.email == email else None


class _OneLinkService:
    def __init__(self, link: Link) -> None:
        self._link = link

    async def get_link_by_id_service(self, link_id: uuid.UUID) -> Link | None:
        return self._link if self._link.id == link_id else None


def test_real_user_service_claim_admin_but_link_says_gestor_returns_401(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    app: FastAPI,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """O papel chega à guarda pelo `UserService` de verdade, vindo do vínculo.

    Só o banco é trocado por dublês. O claim diz `admin` e o vínculo diz
    `gestor`: se o caminho entre o `User` e a guarda deixar de passar pelo
    vínculo, a rota responde 200.
    """
    link = Link(
        id=uuid.uuid4(),
        participant_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        type=LinkType.EMPREGO,
        role=Roles.GESTOR,
    )
    user = User(
        id=uuid.uuid4(),
        keycloak_id=uuid.uuid4(),
        name="Dev CREED",
        email="dev@creed.example.com",
        status=RecordStatus.ACTIVE,
        link_id=link.id,
    )
    service = UserService(
        _OneUserRepository(user),  # type: ignore[arg-type]
        _OneLinkService(link),  # type: ignore[arg-type]
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


def test_user_without_link_returns_401(
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
