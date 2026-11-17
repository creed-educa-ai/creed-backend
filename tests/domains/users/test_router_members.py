"""Testes de app/domains/users/router_members.py — só contrato HTTP.

A guarda `require_role("admin", "gestor")` roda de verdade: só o `validate_token` do
Keycloak e o `UserService` que ela consulta são dublês, como no `autenticar_como` de
`tests/domains/participants/test_router.py`. O `MemberService` também é dublê: a
regra de quem convida quem e o tudo ou nada estão em `test_member_service.py`. Aqui
se prova o que o service não enxerga: 401 e 403 na borda, o que a rota passa ao
service (papel e organização de quem pede), cada exceção no status certo, o corpo
recusado com 422 e a forma da resposta.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.users.dependencies import get_member_service
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.models import User
from app.domains.users.router_members import router
from app.domains.users.schemas import MemberInvite
from app.domains.users.service import CreatedUser, UserAccess
from app.shared.enums import LinkType, RecordStatus, Roles
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)

TOKEN = {"Authorization": "Bearer token-de-teste"}
ORGANIZATION_ID = "8f14e45f-ceea-467e-adde-3f81905dbc1c"
CALLER_ORGANIZATION_ID = uuid.UUID("0b6a4c2e-1d3f-4e5a-9b8c-7d6e5f4a3b2c")
URL = f"/api/v1/organizations/{ORGANIZATION_ID}/members"
VALID_BODY = {"name": "Pessoa Exemplo", "email": "pessoa@exemplo.com", "role": "gestor"}


class _FakeMemberService:
    """Guarda o que chegou e devolve o acesso criado, ou levanta `error`."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def invite_member_service(
        self,
        organization_id: uuid.UUID,
        request: MemberInvite,
        *,
        role: str,
        own_organization_id: uuid.UUID,
    ) -> CreatedUser:
        self.calls.append(
            {
                "organization_id": organization_id,
                "request": request,
                "role": role,
                "own_organization_id": own_organization_id,
            }
        )
        if self.error is not None:
            raise self.error

        user = User(
            id=uuid.uuid4(),
            keycloak_id=uuid.uuid4(),
            name=request.name,
            email=request.email.lower(),
            status=RecordStatus.ACTIVE,
            link_id=uuid.uuid4(),
            created_at=datetime(2026, 10, 28, tzinfo=UTC),
        )
        return CreatedUser(
            user=user, role=request.role.value, organization_id=organization_id
        )


class _FakeUserService:
    """O que a guarda consulta: o vínculo de quem chama."""

    def __init__(self, access: UserAccess) -> None:
        self._access = access

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self._access


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router, prefix="/api/v1")
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _use(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    service: _FakeMemberService,
    caller_role: str = "admin",
) -> None:
    """Instala o dublê e faz o token de teste valer como quem chama."""
    email = "dev@creed.example.com"

    async def _fake_validate_token(_token: str) -> dict[str, Any]:
        return {
            "sub": "sub-dev",
            "email": email,
            "realm_access": {"roles": [caller_role]},
        }

    monkeypatch.setattr("app.shared.authorization.validate_token", _fake_validate_token)
    access = UserAccess(
        id=uuid.uuid4(),
        email=email,
        role=caller_role,
        link_id=uuid.uuid4(),
        organization_id=CALLER_ORGANIZATION_ID,
    )
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService(access)
    app.dependency_overrides[get_member_service] = lambda: service


@pytest.mark.parametrize("caller_role", ["admin", "gestor"])
def test_convite_valido_devolve_201_com_o_acesso_criado(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch, caller_role: str
) -> None:
    _use(app, monkeypatch, _FakeMemberService(), caller_role)

    response = client.post(URL, json=VALID_BODY, headers=TOKEN)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Pessoa Exemplo"
    assert body["email"] == "pessoa@exemplo.com"
    assert body["role"] == "gestor"
    assert body["organization_id"] == ORGANIZATION_ID
    assert body["status"] == "active"
    assert "keycloak_id" not in body


def test_passa_ao_service_o_papel_e_a_organizacao_de_quem_pede(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O recorte do gestor (P-045, P-033) é do service: a rota só entrega quem pede."""
    service = _FakeMemberService()
    _use(app, monkeypatch, service, caller_role="gestor")

    client.post(URL, json=VALID_BODY, headers=TOKEN)

    (call,) = service.calls
    assert call["organization_id"] == uuid.UUID(ORGANIZATION_ID)
    assert call["role"] == "gestor"
    assert call["own_organization_id"] == CALLER_ORGANIZATION_ID
    assert call["request"].role is Roles.GESTOR


def test_sem_type_chega_ao_service_como_emprego(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🟡 P-047."""
    service = _FakeMemberService()
    _use(app, monkeypatch, service)

    client.post(URL, json=VALID_BODY, headers=TOKEN)

    assert service.calls[0]["request"].type is LinkType.EMPREGO


def test_type_mentoria_chega_ao_service(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _FakeMemberService()
    _use(app, monkeypatch, service)

    response = client.post(URL, json={**VALID_BODY, "type": "mentoria"}, headers=TOKEN)

    assert response.status_code == 201
    assert service.calls[0]["request"].type is LinkType.MENTORIA


def test_sem_token_devolve_401(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _FakeMemberService()
    _use(app, monkeypatch, service)

    response = client.post(URL, json=VALID_BODY)

    assert response.status_code == 401
    assert service.calls == []


def test_respondente_devolve_403_sem_chegar_ao_service(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🟡 P-045: o respondente não convida."""
    service = _FakeMemberService()
    _use(app, monkeypatch, service, caller_role="respondente")

    response = client.post(URL, json=VALID_BODY, headers=TOKEN)

    assert response.status_code == 403
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (ForbiddenError("Sem acesso a organização de outro vínculo"), 403),
        (ForbiddenError("Só o admin convida com o papel admin"), 403),
        (NotFoundError(f"Organização {ORGANIZATION_ID} não encontrada"), 404),
        (ConflictError("Já existe usuário com o e-mail pessoa@exemplo.com"), 409),
        (ConflictError("Já existe acesso com o e-mail pessoa@exemplo.com"), 409),
        (
            ServiceUnavailableError(
                "Não foi possível criar o acesso agora. Tente de novo."
            ),
            503,
        ),
    ],
    ids=[
        "organizacao_alheia",
        "gestor_convidando_admin",
        "organizacao_inexistente",
        "email_no_banco",
        "email_no_keycloak",
        "keycloak_ou_smtp_fora",
    ],
)
def test_erro_do_service_vira_o_status_certo_com_a_mensagem(
    app: FastAPI,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status_code: int,
) -> None:
    _use(app, monkeypatch, _FakeMemberService(error), caller_role="gestor")

    response = client.post(URL, json=VALID_BODY, headers=TOKEN)

    assert response.status_code == status_code
    assert response.json() == {"detail": str(error)}


@pytest.mark.parametrize(
    "body",
    [
        {k: v for k, v in VALID_BODY.items() if k != "name"},
        {**VALID_BODY, "role": "superadmin"},
        {**VALID_BODY, "type": "estagio"},
        {**VALID_BODY, "name": "Pessoa\nExemplo"},
        {**VALID_BODY, "email": "nao-e-email"},
    ],
    ids=["sem_nome", "papel_invalido", "tipo_invalido", "nome_com_controle", "email"],
)
def test_corpo_invalido_devolve_422_sem_chegar_ao_service(
    app: FastAPI,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, str],
) -> None:
    service = _FakeMemberService()
    _use(app, monkeypatch, service)

    response = client.post(URL, json=body, headers=TOKEN)

    assert response.status_code == 422
    assert service.calls == []


def test_organization_id_que_nao_e_uuid_devolve_422(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(app, monkeypatch, _FakeMemberService())

    response = client.post(
        "/api/v1/organizations/nao-e-uuid/members", json=VALID_BODY, headers=TOKEN
    )

    assert response.status_code == 422
