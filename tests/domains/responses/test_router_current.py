"""Testes de contrato de GET /forms/current.

A guarda roda de verdade, como em `test_router.py`. A composição da resposta é
provada em `test_service.py`; aqui se prova que o vínculo vem do login, o formato
da saída e o 404.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.forms.models import Form, FormStatus
from app.domains.responses.dependencies import get_service
from app.domains.responses.router_current import router
from app.domains.responses.schemas import CurrentFormRead
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.main import app as aplicacao
from app.shared.exceptions import NotFoundError

ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
LINK_ID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
TOKEN = {"Authorization": "Bearer valido"}


def um_form() -> Form:
    return Form(
        id=uuid.uuid4(),
        name="Plasticidade Humana",
        organization_id=ORGANIZATION_ID,
        status=FormStatus.DRAFT,
        opens_at=datetime(2026, 11, 1, tzinfo=UTC),
        closes_at=datetime(2026, 11, 30, tzinfo=UTC),
        link_id=None,
        created_at=datetime(2026, 10, 30, tzinfo=UTC),
    )


class _FakeService:
    def __init__(self, atual: CurrentFormRead | None) -> None:
        self.atual = atual
        self.quem_pediu: tuple[uuid.UUID, uuid.UUID] | None = None

    async def get_current(
        self, *, link_id: uuid.UUID, organization_id: uuid.UUID
    ) -> CurrentFormRead:
        self.quem_pediu = (link_id, organization_id)
        if self.atual is None:
            raise NotFoundError("Nenhum questionário disponível no momento")
        return self.atual


class _FakeUserService:
    def __init__(self, access: UserAccess) -> None:
        self._access = access

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self._access


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    email = "dev@creed.example.com"

    async def _fake_validate_token(token: str) -> dict[str, Any]:
        return {
            "sub": "sub-dev",
            "email": email,
            "realm_access": {"roles": ["respondente"]},
        }

    monkeypatch.setattr("app.shared.authorization.validate_token", _fake_validate_token)
    access = UserAccess(
        id=uuid.uuid4(),
        email=email,
        role="respondente",
        link_id=LINK_ID,
        organization_id=ORGANIZATION_ID,
    )
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    fastapi_app.dependency_overrides[get_user_service] = lambda: _FakeUserService(access)
    return fastapi_app


def test_sem_token_devolve_401(app: FastAPI) -> None:
    app.dependency_overrides[get_service] = lambda: _FakeService(None)

    assert TestClient(app).get("/forms/current").status_code == 401


def test_devolve_form_e_resposta_nula_com_o_vinculo_do_login(app: FastAPI) -> None:
    form = um_form()
    fake = _FakeService(CurrentFormRead.de_models(form, None))
    app.dependency_overrides[get_service] = lambda: fake

    resposta = TestClient(app, headers=TOKEN).get("/forms/current")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert set(corpo) == {"form", "form_response"}
    assert corpo["form"]["id"] == str(form.id)
    assert corpo["form_response"] is None
    assert fake.quem_pediu == (LINK_ID, ORGANIZATION_ID)


def test_sem_questionario_devolve_404(app: FastAPI) -> None:
    app.dependency_overrides[get_service] = lambda: _FakeService(None)

    resposta = TestClient(app, headers=TOKEN).get("/forms/current")

    assert resposta.status_code == 404
    assert resposta.json() == {"detail": "Nenhum questionário disponível no momento"}


def test_current_vem_antes_da_rota_com_form_id() -> None:
    """Na ordem inversa, `/forms/{form_id}` capturaria "current" e daria 422."""
    caminhos = list(aplicacao.openapi()["paths"])

    assert caminhos.index("/api/v1/forms/current") < caminhos.index(
        "/api/v1/forms/{form_id}"
    )
