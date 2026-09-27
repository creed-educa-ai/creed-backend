"""Testes de app/domains/forms/router.py"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.forms.dependencies import get_service
from app.domains.forms.models import Form, FormStatus
from app.domains.forms.router import router
from app.domains.forms.schemas import FormCreate
from app.shared.exceptions import NotFoundError

FAKE_FORM = Form(
    id=uuid.uuid4(),
    name="Plasticidade Humana",
    organization_id=uuid.uuid4(),
    status=FormStatus.DRAFT,
    created_at=datetime(2026, 9, 13, tzinfo=UTC),
)

CHAVES_DA_SAIDA = {"id", "name", "organization_id", "status", "created_at"}


class _FakeService:
    def __init__(self, form: Form | None = FAKE_FORM) -> None:
        self.form = form

    async def create(self, _dados: FormCreate) -> Form:
        return FAKE_FORM

    async def get(self, form_id: uuid.UUID) -> Form:
        if self.form is None:
            raise NotFoundError(f"Formulário {form_id} não encontrado")
        return self.form


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _use_fake_service(app: FastAPI, fake_service: _FakeService) -> None:
    app.dependency_overrides[get_service] = lambda: fake_service


def test_create_with_valid_payload_returns_201_in_the_contract_shape(
    app: FastAPI, client: TestClient
) -> None:
    _use_fake_service(app, _FakeService())

    response = client.post(
        "/forms",
        json={
            "name": "Instrumento piloto",
            "organization_id": "00000000-0000-0000-0000-000000000001",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == CHAVES_DA_SAIDA
    assert body["status"] == "draft"


def test_create_without_name_returns_422(client: TestClient) -> None:
    response = client.post(
        "/forms",
        json={"organization_id": "00000000-0000-0000-0000-000000000001"},
    )

    assert response.status_code == 422


def test_create_with_empty_name_returns_422(client: TestClient) -> None:
    response = client.post(
        "/forms",
        json={"name": "", "organization_id": "00000000-0000-0000-0000-000000000001"},
    )

    assert response.status_code == 422


def test_create_with_organization_id_not_uuid_returns_422(client: TestClient) -> None:
    response = client.post(
        "/forms",
        json={"name": "Instrumento piloto", "organization_id": "não-é-um-uuid"},
    )

    assert response.status_code == 422


def test_get_with_existing_id_returns_200_in_the_contract_shape(
    app: FastAPI, client: TestClient
) -> None:
    _use_fake_service(app, _FakeService(form=FAKE_FORM))

    response = client.get(f"/forms/{FAKE_FORM.id}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == CHAVES_DA_SAIDA


def test_get_with_unknown_id_returns_404(app: FastAPI, client: TestClient) -> None:
    _use_fake_service(app, _FakeService(form=None))

    response = client.get(f"/forms/{uuid.uuid4()}")

    assert response.status_code == 404
