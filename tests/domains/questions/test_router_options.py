"""Testes de app/domains/questions/router_options.py — contrato HTTP e guarda.

Mesmo desenho de tests/domains/questions/test_router.py: a guarda roda de
verdade (so o `validate_token` e o `UserService` sao dubles) e o service de
alternativas e trocado por um duble em memoria.

O duble nao reimplementa regra: so devolve ou levanta o que o teste pedir. A regra
(pergunta descritiva, posicao ocupada, acesso) e provada em test_service.py; aqui o
que se prova e a traducao de cada erro em codigo HTTP, que e trabalho do router.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.questions.dependencies import get_option_service
from app.domains.questions.models import QuestionOption
from app.domains.questions.router_options import router
from app.domains.questions.schemas import QuestionOptionCreate
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)

ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
QUESTION_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
TOKEN = {"Authorization": "Bearer valido"}


class _FakeQuestionOptionService:
    """Duble da service: devolve uma alternativa ou levanta o erro configurado."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.asked: tuple[uuid.UUID, str, uuid.UUID] | None = None

    async def create(
        self,
        question_id: uuid.UUID,
        request: QuestionOptionCreate,
        *,
        role: str,
        organization_id: uuid.UUID,
    ) -> QuestionOption:
        self.asked = (question_id, role, organization_id)
        if self.error is not None:
            raise self.error
        return QuestionOption(
            id=uuid.uuid4(),
            question_id=question_id,
            label=request.label,
            value=request.value,
            order_index=request.order_index,
            created_at=datetime(2026, 10, 14, tzinfo=UTC),
        )


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    return fastapi_app


class _FakeUserService:
    def __init__(self, access: UserAccess) -> None:
        self._access = access

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self._access


def autenticar_como(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    organization_id: uuid.UUID = ORGANIZATION_ID,
) -> None:
    """Faz o token de teste valer como um usuario ativo com o papel indicado."""
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


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Entra como `admin`, com o token em toda requisicao."""
    autenticar_como(app, monkeypatch, "admin")
    return TestClient(app, headers=TOKEN)


def _use_fake_service(app: FastAPI, fake_service: _FakeQuestionOptionService) -> None:
    app.dependency_overrides[get_option_service] = lambda: fake_service


def _url(question_id: uuid.UUID | str = QUESTION_ID) -> str:
    return f"/questions/{question_id}/options"


def _payload(**fields: object) -> dict[str, object]:
    default: dict[str, object] = {"label": "Sim", "value": "sim", "order_index": 0}
    return {**default, **fields}


class TestCreateQuestionOption:
    def test_valid_body_returns_201_with_the_full_body(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(app, _FakeQuestionOptionService())

        response = client.post(_url(), json=_payload())

        assert response.status_code == 201
        body = response.json()
        assert set(body) == {
            "id",
            "question_id",
            "label",
            "value",
            "order_index",
            "created_at",
        }
        assert body["question_id"] == str(QUESTION_ID)
        assert (body["label"], body["value"], body["order_index"]) == ("Sim", "sim", 0)

    def test_passes_question_role_and_organization_to_the_service(
        self, app: FastAPI, client: TestClient
    ) -> None:
        service = _FakeQuestionOptionService()
        _use_fake_service(app, service)

        client.post(_url(), json=_payload())

        assert service.asked == (QUESTION_ID, "admin", ORGANIZATION_ID)

    def test_unknown_question_returns_404(self, app: FastAPI, client: TestClient) -> None:
        message = f"Pergunta {QUESTION_ID} não encontrada"
        _use_fake_service(app, _FakeQuestionOptionService(NotFoundError(message)))

        response = client.post(_url(), json=_payload())

        assert response.status_code == 404
        assert response.json()["detail"] == message

    def test_question_from_another_organization_returns_403(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(
            app,
            _FakeQuestionOptionService(
                ForbiddenError("Sem acesso a formulário de outra organização")
            ),
        )

        response = client.post(_url(), json=_payload())

        assert response.status_code == 403

    def test_descriptive_question_returns_422_with_text_detail(
        self, app: FastAPI, client: TestClient
    ) -> None:
        message = f"Pergunta {QUESTION_ID} é descritiva e não aceita alternativas"
        _use_fake_service(app, _FakeQuestionOptionService(ValidationError(message)))

        response = client.post(_url(), json=_payload())

        assert response.status_code == 422
        assert response.json()["detail"] == message

    def test_occupied_position_returns_409(
        self, app: FastAPI, client: TestClient
    ) -> None:
        _use_fake_service(
            app,
            _FakeQuestionOptionService(
                ConflictError("Já existe alternativa na posição 0")
            ),
        )

        response = client.post(_url(), json=_payload())

        assert response.status_code == 409

    @pytest.mark.parametrize(
        "fields",
        [{"label": ""}, {"value": ""}, {"order_index": -1}, {"order_index": "x"}],
    )
    def test_invalid_body_returns_422_without_calling_the_service(
        self, app: FastAPI, client: TestClient, fields: dict[str, object]
    ) -> None:
        service = _FakeQuestionOptionService()
        _use_fake_service(app, service)

        response = client.post(_url(), json=_payload(**fields))

        assert response.status_code == 422
        assert service.asked is None

    def test_missing_label_returns_422(self, app: FastAPI, client: TestClient) -> None:
        _use_fake_service(app, _FakeQuestionOptionService())
        payload = _payload()
        del payload["label"]

        response = client.post(_url(), json=payload)

        assert response.status_code == 422

    def test_question_id_that_is_not_a_uuid_returns_422(
        self, app: FastAPI, client: TestClient
    ) -> None:
        service = _FakeQuestionOptionService()
        _use_fake_service(app, service)

        response = client.post(_url("nao-e-uuid"), json=_payload())

        assert response.status_code == 422
        assert service.asked is None


class TestGuard:
    def test_without_token_returns_401(self, app: FastAPI) -> None:
        _use_fake_service(app, _FakeQuestionOptionService())

        response = TestClient(app).post(_url(), json=_payload())

        assert response.status_code == 401

    def test_respondent_returns_403_from_the_guard_without_calling_the_service(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "respondente")
        service = _FakeQuestionOptionService()
        _use_fake_service(app, service)

        response = client.post(_url(), json=_payload())

        assert response.status_code == 403
        assert service.asked is None

    def test_manager_is_allowed_and_the_service_receives_the_role(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        autenticar_como(app, monkeypatch, "gestor")
        service = _FakeQuestionOptionService()
        _use_fake_service(app, service)

        response = client.post(_url(), json=_payload())

        assert response.status_code == 201
        assert service.asked == (QUESTION_ID, "gestor", ORGANIZATION_ID)
