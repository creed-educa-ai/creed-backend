"""
Testes de app/domains/authentication/service.py,
com fakes no lugar do Keycloak e do UserService de users
"""

import uuid
from typing import Any

import pytest

from app.domains.authentication.schemas import LoginRequest
from app.domains.authentication.service import AuthenticationService
from app.domains.links.service import LinkService
from app.domains.users.service import UserAccess, UserService
from app.external_services.keycloak import client as keycloak_client
from app.shared.authorization import AuthenticatedUser
from app.shared.exceptions import AuthenticationError, ServiceUnavailableError

FAKE_TOKENS = {
    "access_token": "access-fake",
    "refresh_token": "refresh-fake",
    "expires_in": 900,
}
FAKE_CLAIMS = {
    "sub": "user-123",
    "email": "dev@creed.example.com",
    "realm_access": {"roles": ["admin"]},
}

# `role`, `link_id` e `organization_id` são os do vínculo (CREED-32), não os
# de uma coluna de `User` — por isso o dublê devolve `UserAccess`, o mesmo tipo
# que `UserService.get_active_user_access_by_email` devolve de verdade.
ACTIVE_ACCESS = UserAccess(
    id=uuid.uuid4(),
    email="dev@creed.example.com",
    role="admin",
    link_id=uuid.uuid4(),
    organization_id=uuid.uuid4(),
)


class _FakeUserService(UserService):
    """Não chama `super().__init__()`: não precisa de repository nenhum."""

    def __init__(self, access: UserAccess | None) -> None:
        self._access = access
        self.password_resets: list[str] = []

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self._access

    async def send_password_reset_service(self, email: str) -> None:
        self.password_resets.append(email)


class _FakeLinkService(LinkService):
    """Só o nome da pessoa do vínculo. `name=None` é o vínculo que sumiu."""

    def __init__(self, name: str | None = "Maria Souza") -> None:
        self._name = name
        self.asked: list[uuid.UUID] = []

    async def get_person_name(self, link_id: uuid.UUID) -> str | None:
        self.asked.append(link_id)
        return self._name


@pytest.fixture
def service() -> AuthenticationService:
    return AuthenticationService(_FakeUserService(ACTIVE_ACCESS), _FakeLinkService())


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

    login_request = LoginRequest(email="dev@creed.example.com", password="dev")  # noqa: S106
    session = await service.login(login_request)

    assert session.access_token == "access-fake"  # noqa: S105
    assert session.refresh_token == "refresh-fake"  # noqa: S105
    assert session.expires_in == 900

    assert session.user.id == str(ACTIVE_ACCESS.id)
    assert session.user.email == "dev@creed.example.com"
    assert session.user.role == "admin"
    assert session.user.link_id == str(ACTIVE_ACCESS.link_id)
    assert session.user.organization_id == str(ACTIVE_ACCESS.organization_id)
    assert session.user.name == "Maria Souza"


async def test_login_reads_the_name_from_the_link_of_the_database_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    links = _FakeLinkService()
    service = AuthenticationService(_FakeUserService(ACTIVE_ACCESS), links)

    async def _fake_login(_email: str, _password: str) -> dict[str, Any]:
        return FAKE_TOKENS

    monkeypatch.setattr(keycloak_client, "login", _fake_login)

    await service.login(LoginRequest(email="dev@creed.example.com", password="dev"))  # noqa: S106

    assert links.asked == [ACTIVE_ACCESS.link_id]


async def test_login_without_the_link_person_returns_same_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vínculo que sumiu entre a consulta do usuário e a do nome: sem sessão, com a
    mesma mensagem de e-mail ou senha errados."""
    service = AuthenticationService(
        _FakeUserService(ACTIVE_ACCESS), _FakeLinkService(name=None)
    )

    async def _fake_login(_email: str, _password: str) -> dict[str, Any]:
        return FAKE_TOKENS

    monkeypatch.setattr(keycloak_client, "login", _fake_login)

    with pytest.raises(AuthenticationError) as exc:
        await service.login(
            LoginRequest(email="dev@creed.example.com", password="dev")  # noqa: S106
        )

    assert exc.value.message == "E-mail ou senha inválidos"


async def test_login_with_wrong_password_raises_authentication_error(
    service: AuthenticationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_login(_email: str, _password: str) -> dict[str, Any]:
        raise keycloak_client.InvalidCredentialsError("invalid_grant")

    monkeypatch.setattr(keycloak_client, "login", _fake_login)

    login_request = LoginRequest(email="dev@creed.example.com", password="wrong")  # noqa: S106
    with pytest.raises(AuthenticationError):
        await service.login(login_request)


async def test_login_with_unknown_email_returns_same_message_as_wrong_password(
    service: AuthenticationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_login(_email: str, _password: str) -> dict[str, Any]:
        raise keycloak_client.InvalidCredentialsError("invalid_grant")

    monkeypatch.setattr(keycloak_client, "login", _fake_login)

    wrong_password_request = LoginRequest(
        email="dev@creed.example.com",
        password="wrong",  # noqa: S106
    )
    unknown_email_request = LoginRequest(
        email="nobody@creed.example.com",
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
    service = AuthenticationService(_FakeUserService(None), _FakeLinkService())

    async def _fake_login(_email: str, _password: str) -> dict[str, Any]:
        return FAKE_TOKENS

    monkeypatch.setattr(keycloak_client, "login", _fake_login)

    login_request = LoginRequest(email="dev@creed.example.com", password="dev")  # noqa: S106
    with pytest.raises(AuthenticationError) as exc:
        await service.login(login_request)

    assert exc.value.message == "E-mail ou senha inválidos"


async def test_login_with_keycloak_down_raises_service_unavailable(
    service: AuthenticationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keycloak fora do ar não é senha errada: a pessoa não deve trocar a senha."""

    async def _fake_login(_email: str, _password: str) -> dict[str, Any]:
        raise keycloak_client.KeycloakUnavailableError("timeout")

    monkeypatch.setattr(keycloak_client, "login", _fake_login)

    login_request = LoginRequest(email="dev@creed.example.com", password="dev")  # noqa: S106
    with pytest.raises(ServiceUnavailableError):
        await service.login(login_request)


async def test_refresh_success_returns_new_session(
    service: AuthenticationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_refresh(_refresh_token: str) -> dict[str, Any]:
        return {**FAKE_TOKENS, "access_token": "new-access"}

    monkeypatch.setattr(keycloak_client, "refresh", _fake_refresh)

    session = await service.refresh("old-refresh-token")

    assert session.user.name == "Maria Souza"

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
    service = AuthenticationService(_FakeUserService(None), _FakeLinkService())

    async def _fake_refresh(_refresh_token: str) -> dict[str, Any]:
        return FAKE_TOKENS

    monkeypatch.setattr(keycloak_client, "refresh", _fake_refresh)

    with pytest.raises(AuthenticationError):
        await service.refresh("valid-refresh-token")


async def test_refresh_with_keycloak_down_raises_service_unavailable(
    service: AuthenticationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_refresh(_refresh_token: str) -> dict[str, Any]:
        raise keycloak_client.KeycloakUnavailableError("timeout")

    monkeypatch.setattr(keycloak_client, "refresh", _fake_refresh)

    with pytest.raises(ServiceUnavailableError):
        await service.refresh("valid-refresh-token")


async def test_password_reset_delegates_the_typed_email_to_users() -> None:
    """Quem decide se há acesso, e compara em minúsculas, é o `UserService`."""
    users = _FakeUserService(ACTIVE_ACCESS)

    await AuthenticationService(users, _FakeLinkService()).request_password_reset(
        "Pessoa@exemplo.com"
    )

    assert users.password_resets == ["Pessoa@exemplo.com"]


LINK_ID = "3f9a2b1c-4d5e-4f6a-8b7c-9d0e1f2a3b4c"
ORGANIZATION_ID = "8f14e45f-ceea-467e-adde-3f81905dbc1c"


def _checked_user() -> AuthenticatedUser:
    """Quem já passou pela guarda: vínculo e organização preenchidos."""
    return AuthenticatedUser(
        sub="user-123",
        email="dev@creed.example.com",
        roles=["respondente"],
        link_id=LINK_ID,
        organization_id=ORGANIZATION_ID,
    )


async def test_get_session_returns_the_identity_with_the_link_person_name() -> None:
    links = _FakeLinkService()
    service = AuthenticationService(_FakeUserService(ACTIVE_ACCESS), links)

    session = await service.get_session(_checked_user())

    assert session.id == "user-123"
    assert session.email == "dev@creed.example.com"
    assert session.role == "respondente"
    assert session.link_id == LINK_ID
    assert session.organization_id == ORGANIZATION_ID
    assert session.name == "Maria Souza"
    assert links.asked == [uuid.UUID(LINK_ID)]


async def test_get_session_without_the_link_person_raises_authentication_error() -> None:
    service = AuthenticationService(
        _FakeUserService(ACTIVE_ACCESS), _FakeLinkService(name=None)
    )

    with pytest.raises(AuthenticationError):
        await service.get_session(_checked_user())
