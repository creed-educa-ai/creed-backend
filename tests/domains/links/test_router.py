"""Testes de app/domains/links/router.py — contrato HTTP e a guarda `admin`.

`TestClient` com `dependency_overrides`, como em `tests/domains/authentication/
test_router.py`. Para a guarda, o `validate_token` falso e o dublê de `UserService`
seguem `tests/shared/test_authorization.py` — já no formato pós-task-5, com o papel
vindo de `UserAccess` (do vínculo), não de `user.role`.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.links.dependencies import get_service as get_link_service
from app.domains.links.models import Link
from app.domains.links.router import router
from app.domains.links.schemas import LinkCreate
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.exceptions import ValidationError

VALID_BODY = {
    "participant_id": "e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339",
    "type": "emprego",
    "role": "gestor",
}


class _FakeLinkService:
    """Dublê: monta o `Link` do jeito que o repository faria no INSERT."""

    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, LinkCreate]] = []

    async def create_link_service(
        self, organization_id: uuid.UUID, request: LinkCreate
    ) -> Link:
        self.calls.append((organization_id, request))
        now = datetime(2026, 9, 27, tzinfo=UTC)
        return Link(
            id=uuid.uuid4(),
            organization_id=organization_id,
            participant_id=request.participant_id,
            department_id=request.department_id,
            type=request.type,
            role=request.role,
            start_at=now,
            end_at=None,
            created_at=now,
            updated_at=None,
        )


class _UnknownParticipantLinkService:
    """Dublê que recusa como o service real recusa um participante inexistente."""

    async def create_link_service(
        self, organization_id: uuid.UUID, request: LinkCreate
    ) -> Link:
        raise ValidationError(f"Participante {request.participant_id} não encontrado")


class _FakeUserService:
    def __init__(self, access: UserAccess | None) -> None:
        self._access = access

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self._access


def _build_access(role: str) -> UserAccess:
    return UserAccess(
        id=uuid.uuid4(),
        email="dev@creed.example.com",
        role=role,
        link_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
    )


def _install_validate_token(monkeypatch: pytest.MonkeyPatch, roles: list[str]) -> None:
    async def _fake(_token: str) -> dict[str, Any]:
        return {
            "sub": "user-123",
            "email": "dev@creed.example.com",
            "realm_access": {"roles": roles},
        }

    monkeypatch.setattr("app.shared.authorization.validate_token", _fake)


@pytest.fixture
def link_service() -> _FakeLinkService:
    return _FakeLinkService()


@pytest.fixture
def app(link_service: _FakeLinkService) -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router, prefix="/api/v1")
    fastapi_app.dependency_overrides[get_link_service] = lambda: link_service
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _authorize_as(app: FastAPI, monkeypatch: pytest.MonkeyPatch, role: str) -> None:
    _install_validate_token(monkeypatch, [role])
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService(
        _build_access(role)
    )


ORG_ID = "8f14e45f-ceea-467e-adde-3f81905dbc1c"
URL = f"/api/v1/organizations/{ORG_ID}/links"


def test_admin_with_valid_body_creates_and_returns_201(
    client: TestClient,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    link_service: _FakeLinkService,
) -> None:
    _authorize_as(app, monkeypatch, "admin")

    response = client.post(
        URL, json=VALID_BODY, headers={"Authorization": "Bearer valid"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["organization_id"] == ORG_ID
    assert body["participant_id"] == VALID_BODY["participant_id"]
    assert body["type"] == "emprego"
    assert body["role"] == "gestor"
    assert link_service.calls[0][0] == uuid.UUID(ORG_ID)


def test_without_department_id_in_body_creates_with_null_department_id(
    client: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _authorize_as(app, monkeypatch, "admin")

    response = client.post(
        URL, json=VALID_BODY, headers={"Authorization": "Bearer valid"}
    )

    assert response.status_code == 201
    assert response.json()["department_id"] is None


def test_without_authorization_returns_401(client: TestClient) -> None:
    response = client.post(URL, json=VALID_BODY)

    assert response.status_code == 401


def test_respondente_role_returns_403(
    client: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _authorize_as(app, monkeypatch, "respondente")

    response = client.post(
        URL, json=VALID_BODY, headers={"Authorization": "Bearer valid"}
    )

    assert response.status_code == 403


def test_type_outside_enum_returns_422(
    client: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _authorize_as(app, monkeypatch, "admin")

    response = client.post(
        URL,
        json={**VALID_BODY, "type": "inexistente"},
        headers={"Authorization": "Bearer valid"},
    )

    assert response.status_code == 422


def test_organization_id_in_url_not_uuid_returns_422(
    client: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _authorize_as(app, monkeypatch, "admin")

    response = client.post(
        "/api/v1/organizations/nao-e-um-uuid/links",
        json=VALID_BODY,
        headers={"Authorization": "Bearer valid"},
    )

    assert response.status_code == 422


def test_unknown_participant_returns_422_with_text_detail(
    client: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prova só a tradução do router: `ValidationError` -> 422.

    A regra (o participante precisa existir) é provada em `test_service.py`.
    """
    _authorize_as(app, monkeypatch, "admin")
    app.dependency_overrides[get_link_service] = _UnknownParticipantLinkService

    response = client.post(
        URL, json=VALID_BODY, headers={"Authorization": "Bearer valid"}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        f"Participante {VALID_BODY['participant_id']} não encontrado"
    )
