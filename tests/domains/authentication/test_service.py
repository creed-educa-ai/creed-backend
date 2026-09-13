"""
Testes de app/domains/authentication/service.py,
com fakes no lugar do Keycloak e do UserService de users
"""

import uuid
from typing import Any

import pytest

from app.domains.authentication.schemas import LoginRequest
from app.domains.authentication.service import AuthenticationService
from app.domains.users.models import RecordStatus, User, UserRole
from app.domains.users.service import UserService
from app.external_services.keycloak import client as keycloak_client
from app.shared.exceptions import AuthenticationError

FAKE_TOKENS = {
    "access_token": "access-fake",
    "refresh_token": "refresh-fake",
    "expires_in": 900,
}
FAKE_CLAIMS = {
    "sub": "user-123",
    "email": "dev@creed.local",
    "realm_access": {"roles": ["admin"]},
}

ACTIVE_USER = User(
    id=uuid.uuid4(),
    keycloak_id=uuid.uuid4(),
    email="dev@creed.local",
    name="Dev CREED",
    status=RecordStatus.ACTIVE,
    role=UserRole.ADMIN,
)


class _FakeUserService(UserService):
    """Não chama `super().__init__()`: não precisa de repository nenhum."""

    def __init__(self, user: User | None) -> None:
        self._user = user

    async def get_active_user_by_email(self, email: str) -> User | None:
        return self._user


@pytest.fixture
def service() -> AuthenticationService:
    return AuthenticationService(_FakeUserService(ACTIVE_USER))


@pytest.fixture(autouse=True)
def _fake_validate_token(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(_token: str) -> dict[str, Any]:
        return FAKE_CLAIMS

    monkeypatch.setattr("app.domains.authentication.service.validate_token", _fake)


async def test_login_success_builds_session_from_database_user(
    service: AuthenticationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_login(_email: str, _password: str) -> dict[str, Any]:
        return FAKE_TOKENS

    monkeypatch.setattr(keycloak_client, "login", _fake_login)

    login_request = LoginRequest(email="dev@creed.local", password="dev")  # noqa: S106
    session = await service.login(login_request)

    assert session.access_token == "access-fake"  # noqa: S105
    assert session.refresh_token == "refresh-fake"  # noqa: S105
    assert session.expires_in == 900

    assert session.user.id == str(ACTIVE_USER.id)
    assert session.user.email == "dev@creed.local"
    assert session.user.role == "admin"


async def test_login_with_wrong_password_raises_authentication_error(
    service: AuthenticationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_login(_email: str, _password: str) -> dict[str, Any]:
        raise keycloak_client.InvalidCredentialsError("invalid_grant")

    monkeypatch.setattr(keycloak_client, "login", _fake_login)

    login_request = LoginRequest(email="dev@creed.local", password="wrong")  # noqa: S106
    with pytest.raises(AuthenticationError):
        await service.login(login_request)


async def test_login_with_unknown_email_returns_same_message_as_wrong_password(
    service: AuthenticationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_login(_email: str, _password: str) -> dict[str, Any]:
        raise keycloak_client.InvalidCredentialsError("invalid_grant")

    monkeypatch.setattr(keycloak_client, "login", _fake_login)

    wrong_password_request = LoginRequest(
        email="dev@creed.local",
        password="wrong",  # noqa: S106
    )
    unknown_email_request = LoginRequest(
        email="nobody@creed.local",
        password="any",  # noqa: S106
    )

    with pytest.raises(AuthenticationError) as wrong_password:
        await service.login(wrong_password_request)

    with pytest.raises(AuthenticationError) as unknown_email:
        await service.login(unknown_email_request)

    assert wrong_password.value.message == unknown_email.value.message


async def test_login_with_inactive_database_user_returns_same_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AuthenticationService(_FakeUserService(None))

    async def _fake_login(_email: str, _password: str) -> dict[str, Any]:
        return FAKE_TOKENS

    monkeypatch.setattr(keycloak_client, "login", _fake_login)

    login_request = LoginRequest(email="dev@creed.local", password="dev")  # noqa: S106
    with pytest.raises(AuthenticationError) as exc:
        await service.login(login_request)

    assert exc.value.message == "E-mail ou senha inválidos"


async def test_login_with_keycloak_down_raises_authentication_error(
    service: AuthenticationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_login(_email: str, _password: str) -> dict[str, Any]:
        raise keycloak_client.KeycloakUnavailableError("timeout")

    monkeypatch.setattr(keycloak_client, "login", _fake_login)

    login_request = LoginRequest(email="dev@creed.local", password="dev")  # noqa: S106
    with pytest.raises(AuthenticationError):
        await service.login(login_request)


async def test_refresh_success_returns_new_session(
    service: AuthenticationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_refresh(_refresh_token: str) -> dict[str, Any]:
        return {**FAKE_TOKENS, "access_token": "new-access"}

    monkeypatch.setattr(keycloak_client, "refresh", _fake_refresh)

    session = await service.refresh("old-refresh-token")

    assert session.access_token == "new-access"  # noqa: S105


async def test_refresh_with_invalid_token_raises_authentication_error(
    service: AuthenticationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_refresh(_refresh_token: str) -> dict[str, Any]:
        raise keycloak_client.InvalidCredentialsError("invalid_grant")

    monkeypatch.setattr(keycloak_client, "refresh", _fake_refresh)

    with pytest.raises(AuthenticationError):
        await service.refresh("invalid-refresh-token")


async def test_refresh_with_deactivated_database_user_raises_authentication_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sessão só renova se o usuário continuar ativo no banco."""
    service = AuthenticationService(_FakeUserService(None))

    async def _fake_refresh(_refresh_token: str) -> dict[str, Any]:
        return FAKE_TOKENS

    monkeypatch.setattr(keycloak_client, "refresh", _fake_refresh)

    with pytest.raises(AuthenticationError):
        await service.refresh("valid-refresh-token")
