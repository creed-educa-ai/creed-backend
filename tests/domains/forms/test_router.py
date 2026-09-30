"""Testes de app/domains/forms/router.py

A guarda roda de verdade: só o `validate_token` e o `UserService` são dublês, como
em `tests/domains/participants/test_router.py`. A regra de organização (P-033) é
provada em `test_service.py`; aqui se prova a guarda de papel e a tradução do
`ForbiddenError` em 403.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.forms.dependencies import get_service
from app.domains.forms.models import Form, FormStatus
from app.domains.forms.router import router
from app.domains.forms.schemas import FormCreate
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.exceptions import ForbiddenError, NotFoundError

ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

FAKE_FORM = Form(
    id=uuid.uuid4(),
    name="Plasticidade Humana",
    organization_id=ORGANIZATION_ID,
    status=FormStatus.DRAFT,
    created_at=datetime(2026, 9, 13, tzinfo=UTC),
)

CHAVES_DA_SAIDA = {"id", "name", "organization_id", "status", "created_at"}
TOKEN = {"Authorization": "Bearer valido"}


class _FakeService:
    """Dublê: devolve o que for configurado, sem reimplementar a regra.

    `proibido=True` faz as duas operações levantarem `ForbiddenError`, como o
    service real faz para outra organização.
    """

    def __init__(self, form: Form | None = FAKE_FORM, *, proibido: bool = False) -> None:
        self.form = form
        self.proibido = proibido
        self.quem_pediu: tuple[str, uuid.UUID] | None = None

    async def create(
        self, dados: FormCreate, *, role: str, organization_id: uuid.UUID
    ) -> Form:
        self.quem_pediu = (role, organization_id)
        if self.proibido:
            raise ForbiddenError("Sem acesso a formulário de outra organização")
        return Form(
            id=FAKE_FORM.id,
            name=dados.name,
            organization_id=dados.organization_id,
            status=FormStatus.DRAFT,
            created_at=FAKE_FORM.created_at,
        )

    async def get_for_user(
        self, form_id: uuid.UUID, *, role: str, organization_id: uuid.UUID
    ) -> Form:
        self.quem_pediu = (role, organization_id)
        if self.form is None:
            raise NotFoundError(f"Formulário {form_id} não encontrado")
        if self.proibido:
            raise ForbiddenError("Sem acesso a formulário de outra organização")
        return self.form


class _FakeUserService:
    def __init__(self, access: UserAccess) -> None:
        self._access = access

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self._access


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def autenticar_como(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    organization_id: uuid.UUID = ORGANIZATION_ID,
) -> None:
    """Faz o token de teste valer como um usuário ativo com o papel indicado."""
    email = "dev@creed.example.com"

    async def _fake_validate_token(token: str) -> dict[str, Any]:
        return {"sub": "sub-dev", "email": email, "realm_access": {"roles": [role]}}

    monkeypatch.setattr("app.shared.authorization.validate_token", _fake_validate_token)
    access = UserAccess(
        id=uuid.uuid4(),
        email=email,
        role=role,
        link_id=uuid.uuid4(),
        organization_id=organization_id,
    )
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService(access)


def _use_fake_service(app: FastAPI, fake_service: _FakeService) -> None:
    app.dependency_overrides[get_service] = lambda: fake_service


PAYLOAD = {"name": "Instrumento piloto", "organization_id": str(ORGANIZATION_ID)}


class TestSemToken:
    def test_criar_devolve_401(self, app: FastAPI, client: TestClient) -> None:
        _use_fake_service(app, _FakeService())

        assert client.post("/forms", json=PAYLOAD).status_code == 401

    def test_consultar_devolve_401(self, app: FastAPI, client: TestClient) -> None:
        _use_fake_service(app, _FakeService())

        assert client.get(f"/forms/{FAKE_FORM.id}").status_code == 401


class TestCriar:
    def test_gestor_com_payload_valido_devolve_201_no_formato_do_contrato(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "gestor")
        service = _FakeService()
        _use_fake_service(app, service)

        response = client.post("/forms", json=PAYLOAD, headers=TOKEN)

        assert response.status_code == 201
        body = response.json()
        assert set(body) == CHAVES_DA_SAIDA
        assert body["name"] == PAYLOAD["name"]
        assert body["status"] == "draft"
        assert service.quem_pediu == ("gestor", ORGANIZATION_ID)

    def test_respondente_devolve_403_pela_guarda(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "respondente")
        service = _FakeService()
        _use_fake_service(app, service)

        response = client.post("/forms", json=PAYLOAD, headers=TOKEN)

        assert response.status_code == 403
        assert service.quem_pediu is None

    def test_organizacao_alheia_devolve_403_pelo_service(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "gestor")
        _use_fake_service(app, _FakeService(proibido=True))

        response = client.post("/forms", json=PAYLOAD, headers=TOKEN)

        assert response.status_code == 403
        assert response.json()["detail"] == (
            "Sem acesso a formulário de outra organização"
        )

    @pytest.mark.parametrize(
        "payload",
        [
            {"organization_id": str(ORGANIZATION_ID)},
            {"name": "", "organization_id": str(ORGANIZATION_ID)},
            {"name": "Instrumento piloto", "organization_id": "não-é-um-uuid"},
        ],
        ids=["sem_nome", "nome_vazio", "organization_id_nao_uuid"],
    )
    def test_payload_invalido_devolve_422(
        self,
        app: FastAPI,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        payload: dict[str, str],
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        _use_fake_service(app, _FakeService())

        response = client.post("/forms", json=payload, headers=TOKEN)

        assert response.status_code == 422


class TestConsultar:
    def test_respondente_da_organizacao_devolve_200_no_formato_do_contrato(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "respondente")
        service = _FakeService(form=FAKE_FORM)
        _use_fake_service(app, service)

        response = client.get(f"/forms/{FAKE_FORM.id}", headers=TOKEN)

        assert response.status_code == 200
        assert set(response.json()) == CHAVES_DA_SAIDA
        assert service.quem_pediu == ("respondente", ORGANIZATION_ID)

    def test_organizacao_alheia_devolve_403(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "gestor")
        _use_fake_service(app, _FakeService(proibido=True))

        response = client.get(f"/forms/{FAKE_FORM.id}", headers=TOKEN)

        assert response.status_code == 403

    def test_id_desconhecido_devolve_404(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "admin")
        _use_fake_service(app, _FakeService(form=None))

        response = client.get(f"/forms/{uuid.uuid4()}", headers=TOKEN)

        assert response.status_code == 404
