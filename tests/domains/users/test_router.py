"""Testes de app/domains/users/router.py — só contrato HTTP.

A regra do cadastro (e-mail repetido, vínculo inexistente ou já usado, o tudo ou nada
com o Keycloak) é provada em `test_service.py`. Aqui se prova o que o service não
enxerga: a guarda `admin` no cadastro e na remoção, a guarda `admin`/`gestor` no
reenvio de convite (e o papel e a organização que ela passa ao service), que cada
exceção vira o status certo, que o body sem `link_id` é recusado na borda, e a forma da
resposta. O recorte do gestor no reenvio é regra, e está em `test_service.py`.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.users.dependencies import get_service
from app.domains.users.models import User
from app.domains.users.router import router
from app.domains.users.schemas import UserCreate
from app.domains.users.service import CreatedUser, UserAccess
from app.shared.enums import RecordStatus
from app.shared.exceptions import ConflictError, NotFoundError, ServiceUnavailableError

LINK_ID = "3f9a2b1c-4d5e-4f6a-8b7c-9d0e1f2a3b4c"
ORGANIZATION_ID = "8f14e45f-ceea-467e-adde-3f81905dbc1c"
USER_ID = "d40b7a55-b9cc-4b78-ae5d-ab325fd655e2"
CALLER_ORGANIZATION_ID = uuid.UUID("0b6a4c2e-1d3f-4e5a-9b8c-7d6e5f4a3b2c")
TOKEN = {"Authorization": "Bearer valid"}
INVITATION_URL = f"/api/v1/users/{USER_ID}/invitation"

VALID_BODY = {
    "name": "Pessoa Exemplo",
    "email": "pessoa@exemplo.com",
    "link_id": LINK_ID,
}


class _FakeService:
    """Faz as vezes do `UserService` para a rota **e** para a guarda.

    A guarda `require_role` e a rota resolvem o mesmo `get_service`, então o dublê
    também responde `get_active_user_access_by_email`, com o papel do vínculo de quem
    está chamando (`caller_role`), na organização `CALLER_ORGANIZATION_ID`. `deleted`
    guarda os ids que chegaram à remoção, para conferir que a guarda barra antes,
    `received` os cadastros que chegaram ao service, e `resent` os reenvios de convite,
    com o papel e a organização de quem pediu.
    """

    def __init__(
        self, error: Exception | None = None, caller_role: str = "admin"
    ) -> None:
        self.error = error
        self.caller_role = caller_role
        self.deleted: list[uuid.UUID] = []
        self.received: list[UserCreate] = []
        self.resent: list[tuple[uuid.UUID, str, uuid.UUID]] = []

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return UserAccess(
            id=uuid.uuid4(),
            email=email,
            role=self.caller_role,
            link_id=uuid.uuid4(),
            organization_id=CALLER_ORGANIZATION_ID,
        )

    async def resend_invitation_service(
        self, user_id: uuid.UUID, *, role: str, own_organization_id: uuid.UUID
    ) -> None:
        if self.error is not None:
            raise self.error
        self.resent.append((user_id, role, own_organization_id))

    async def create_user_service(self, request: UserCreate) -> CreatedUser:
        self.received.append(request)
        if self.error is not None:
            raise self.error

        user = User(
            id=uuid.uuid4(),
            keycloak_id=uuid.uuid4(),
            name=request.name,
            email=request.email,
            status=RecordStatus.ACTIVE,
            link_id=request.link_id,
            created_at=datetime(2026, 9, 28, tzinfo=UTC),
        )
        return CreatedUser(
            user=user, role="gestor", organization_id=uuid.UUID(ORGANIZATION_ID)
        )

    async def delete_user_service(self, user_id: uuid.UUID) -> None:
        if self.error is not None:
            raise self.error
        self.deleted.append(user_id)


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router, prefix="/api/v1")
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _use(app: FastAPI, monkeypatch: pytest.MonkeyPatch, service: _FakeService) -> None:
    """Instala o dublê e faz o token de teste trazer o papel de quem chama."""

    async def _fake_validate_token(_token: str) -> dict[str, Any]:
        return {
            "sub": "sub-dev",
            "email": "dev@creed.example.com",
            "realm_access": {"roles": [service.caller_role]},
        }

    monkeypatch.setattr("app.shared.authorization.validate_token", _fake_validate_token)
    app.dependency_overrides[get_service] = lambda: service


def test_valid_body_returns_201_with_link_role_and_organization(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(app, monkeypatch, _FakeService())

    response = client.post("/api/v1/users", json=VALID_BODY, headers=TOKEN)

    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "gestor"
    assert body["link_id"] == LINK_ID
    assert body["organization_id"] == ORGANIZATION_ID
    assert "keycloak_id" not in body


def test_keycloak_id_in_the_body_is_ignored(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quem cria no Keycloak é o back: o campo antigo não chega ao service."""
    service = _FakeService()
    _use(app, monkeypatch, service)
    body = {**VALID_BODY, "keycloak_id": "e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339"}

    response = client.post("/api/v1/users", json=body, headers=TOKEN)

    assert response.status_code == 201
    (received,) = service.received
    assert "keycloak_id" not in received.model_dump()


def test_without_token_returns_401(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cadastrar acesso amarra um login a um papel e a uma organização (P-008)."""
    _use(app, monkeypatch, _FakeService())

    response = client.post("/api/v1/users", json=VALID_BODY)

    assert response.status_code == 401


def test_respondente_role_returns_403(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(app, monkeypatch, _FakeService(caller_role="respondente"))

    response = client.post("/api/v1/users", json=VALID_BODY, headers=TOKEN)

    assert response.status_code == 403


def test_without_link_id_returns_422(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(app, monkeypatch, _FakeService())
    body = {k: v for k, v in VALID_BODY.items() if k != "link_id"}

    response = client.post("/api/v1/users", json=body, headers=TOKEN)

    assert response.status_code == 422


def test_unknown_link_returns_404(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(
        app,
        monkeypatch,
        _FakeService(NotFoundError(f"Vínculo {LINK_ID} não encontrado")),
    )

    response = client.post("/api/v1/users", json=VALID_BODY, headers=TOKEN)

    assert response.status_code == 404
    assert LINK_ID in response.json()["detail"]


def test_link_already_used_returns_409(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(
        app,
        monkeypatch,
        _FakeService(ConflictError(f"Vínculo {LINK_ID} já está em uso")),
    )

    response = client.post("/api/v1/users", json=VALID_BODY, headers=TOKEN)

    assert response.status_code == 409
    assert LINK_ID in response.json()["detail"]


def test_keycloak_or_smtp_down_returns_503(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(
        app,
        monkeypatch,
        _FakeService(ServiceUnavailableError("Não foi possível criar o acesso agora.")),
    )

    response = client.post("/api/v1/users", json=VALID_BODY, headers=TOKEN)

    assert response.status_code == 503
    assert response.json()["detail"] == "Não foi possível criar o acesso agora."


def test_delete_with_admin_returns_204(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _FakeService()
    _use(app, monkeypatch, service)

    response = client.delete(f"/api/v1/users/{USER_ID}", headers=TOKEN)

    assert response.status_code == 204
    assert service.deleted == [uuid.UUID(USER_ID)]


def test_delete_without_token_returns_401_and_keeps_the_user(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A remoção é definitiva: sem token, a chamada não pode chegar ao service."""
    service = _FakeService()
    _use(app, monkeypatch, service)

    response = client.delete(f"/api/v1/users/{USER_ID}")

    assert response.status_code == 401
    assert service.deleted == []


def test_delete_with_respondente_role_returns_403_and_keeps_the_user(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _FakeService(caller_role="respondente")
    _use(app, monkeypatch, service)

    response = client.delete(f"/api/v1/users/{USER_ID}", headers=TOKEN)

    assert response.status_code == 403
    assert service.deleted == []


def test_delete_with_keycloak_down_returns_503(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(
        app,
        monkeypatch,
        _FakeService(ServiceUnavailableError("Não foi possível remover o acesso agora.")),
    )

    response = client.delete(f"/api/v1/users/{USER_ID}", headers=TOKEN)

    assert response.status_code == 503
    assert response.json()["detail"] == "Não foi possível remover o acesso agora."


@pytest.mark.parametrize("caller_role", ["admin", "gestor"])
def test_resend_invitation_returns_204_and_passes_who_asks_to_the_service(
    app: FastAPI,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caller_role: str,
) -> None:
    """O recorte do gestor é do service: a rota só passa papel e organização dele."""
    service = _FakeService(caller_role=caller_role)
    _use(app, monkeypatch, service)

    response = client.post(INVITATION_URL, headers=TOKEN)

    assert response.status_code == 204
    assert response.content == b""
    assert service.resent == [(uuid.UUID(USER_ID), caller_role, CALLER_ORGANIZATION_ID)]


def test_resend_invitation_without_token_returns_401(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _FakeService()
    _use(app, monkeypatch, service)

    response = client.post(INVITATION_URL)

    assert response.status_code == 401
    assert service.resent == []


def test_resend_invitation_with_respondente_role_returns_403(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🟡 Premissa P-045 — o respondente não convida, e por isso não reenvia."""
    service = _FakeService(caller_role="respondente")
    _use(app, monkeypatch, service)

    response = client.post(INVITATION_URL, headers=TOKEN)

    assert response.status_code == 403
    assert service.resent == []


def test_resend_invitation_to_unknown_or_other_organization_user_returns_404(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(
        app,
        monkeypatch,
        _FakeService(NotFoundError(f"Usuário {USER_ID} não encontrado"), "gestor"),
    )

    response = client.post(INVITATION_URL, headers=TOKEN)

    assert response.status_code == 404
    assert response.json()["detail"] == f"Usuário {USER_ID} não encontrado"


def test_resend_invitation_with_keycloak_or_smtp_down_returns_503(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(
        app,
        monkeypatch,
        _FakeService(ServiceUnavailableError("Não foi possível reenviar o convite.")),
    )

    response = client.post(INVITATION_URL, headers=TOKEN)

    assert response.status_code == 503
    assert response.json()["detail"] == "Não foi possível reenviar o convite."


def test_resend_invitation_with_invalid_user_id_returns_422(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _FakeService()
    _use(app, monkeypatch, service)

    response = client.post("/api/v1/users/nao-e-uuid/invitation", headers=TOKEN)

    assert response.status_code == 422
    assert service.resent == []
