"""Testes de app/domains/vinculos/router.py — contrato HTTP e a guarda `admin`.

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

from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.domains.vinculos.dependencies import get_service as get_vinculo_service
from app.domains.vinculos.models import Vinculo
from app.domains.vinculos.router import router
from app.domains.vinculos.schemas import VinculoCreate

VALID_BODY = {
    "participant_id": "e5c0e7fa-3e57-427a-8d7b-a4ab5fb6c339",
    "type": "emprego",
    "role": "gestor",
}


class _FakeVinculoService:
    """Dublê: monta o `Vinculo` do jeito que o repository faria no INSERT."""

    def __init__(self) -> None:
        self.chamadas: list[tuple[uuid.UUID, VinculoCreate]] = []

    async def create_vinculo_service(
        self, organization_id: uuid.UUID, request: VinculoCreate
    ) -> Vinculo:
        self.chamadas.append((organization_id, request))
        agora = datetime(2026, 9, 27, tzinfo=UTC)
        return Vinculo(
            id=uuid.uuid4(),
            organization_id=organization_id,
            participant_id=request.participant_id,
            setor_id=request.setor_id,
            type=request.type,
            role=request.role,
            start_at=agora,
            end_at=None,
            created_at=agora,
            updated_at=None,
        )


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
        vinculo_id=uuid.uuid4(),
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
def vinculo_service() -> _FakeVinculoService:
    return _FakeVinculoService()


@pytest.fixture
def app(vinculo_service: _FakeVinculoService) -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router, prefix="/api/v1")
    fastapi_app.dependency_overrides[get_vinculo_service] = lambda: vinculo_service
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
URL = f"/api/v1/organizacoes/{ORG_ID}/vinculos"


def test_admin_com_corpo_valido_cria_e_devolve_201(
    client: TestClient,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    vinculo_service: _FakeVinculoService,
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
    assert vinculo_service.chamadas[0][0] == uuid.UUID(ORG_ID)


def test_sem_setor_id_no_corpo_cria_com_setor_id_nulo(
    client: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _authorize_as(app, monkeypatch, "admin")

    response = client.post(
        URL, json=VALID_BODY, headers={"Authorization": "Bearer valid"}
    )

    assert response.status_code == 201
    assert response.json()["setor_id"] is None


def test_sem_authorization_retorna_401(client: TestClient) -> None:
    response = client.post(URL, json=VALID_BODY)

    assert response.status_code == 401


def test_papel_respondente_retorna_403(
    client: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _authorize_as(app, monkeypatch, "respondente")

    response = client.post(
        URL, json=VALID_BODY, headers={"Authorization": "Bearer valid"}
    )

    assert response.status_code == 403


def test_type_fora_do_enum_retorna_422(
    client: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _authorize_as(app, monkeypatch, "admin")

    response = client.post(
        URL,
        json={**VALID_BODY, "type": "inexistente"},
        headers={"Authorization": "Bearer valid"},
    )

    assert response.status_code == 422


def test_organization_id_na_url_que_nao_e_uuid_retorna_422(
    client: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _authorize_as(app, monkeypatch, "admin")

    response = client.post(
        "/api/v1/organizacoes/nao-e-um-uuid/vinculos",
        json=VALID_BODY,
        headers={"Authorization": "Bearer valid"},
    )

    assert response.status_code == 422
