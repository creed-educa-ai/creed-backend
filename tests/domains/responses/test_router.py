"""Testes de contrato HTTP do domínio responses."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.responses.dependencies import get_service
from app.domains.responses.router import router
from app.domains.responses.schemas import FormResponseCreate
from app.shared.exceptions import ConflictError


class _ConflictingService:
    async def create_form_response(
        self,
        form_id: uuid.UUID,
        vinculo_id: uuid.UUID,
    ) -> None:
        raise ConflictError(
            f"Já existe uma resposta para o formulário {form_id} e vínculo {vinculo_id}"
        )

    async def submit_form_response(self, form_response_id: uuid.UUID) -> None:
        raise ConflictError(f"FormResponse {form_response_id} já foi submetido")


@pytest.fixture
def client() -> TestClient:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    fastapi_app.dependency_overrides[get_service] = lambda: _ConflictingService()
    return TestClient(fastapi_app)


def test_create_existing_form_response_returns_documented_409(
    client: TestClient,
) -> None:
    data = FormResponseCreate(form_id=uuid.uuid4(), vinculo_id=uuid.uuid4())

    response = client.post("/form-responses", json=data.model_dump(mode="json"))

    assert response.status_code == 409
    assert response.json()["detail"].startswith("Já existe uma resposta")


def test_submit_already_submitted_form_response_returns_documented_409(
    client: TestClient,
) -> None:
    response = client.patch(f"/form-responses/{uuid.uuid4()}")

    assert response.status_code == 409
    assert response.json()["detail"].endswith("já foi submetido")
