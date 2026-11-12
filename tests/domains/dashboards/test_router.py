"""Testes de app/domains/dashboards/router.py."""

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.dashboards.dependencies import get_service as get_dashboard_service
from app.domains.dashboards.router import router
from app.domains.dashboards.schemas import CompanySummaryRead, MetricCardRead
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.enums import Prisma
from app.shared.exceptions import ForbiddenError, NotFoundError

ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TOKEN = {"Authorization": "Bearer valido"}


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


def test_get_company_dashboard_requires_authentication(client: TestClient) -> None:
    resp = client.get(f"/dashboards/company/{uuid.uuid4()}")
    assert resp.status_code == 401


def test_get_company_dashboard_returns_200_and_payload(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "gestor")
    form_id = uuid.uuid4()

    destaque = MetricCardRead(
        rotulo="Destaque",
        titulo="Segurança Psicológica",
        valor=85.0,
        descricao="Ambiente de confiança",
        prisma=Prisma.SEGURANCA_PSICOLOGICA,
    )
    oportunidade = MetricCardRead(
        rotulo="Oportunidade",
        titulo="Liderança Adaptativa",
        valor=65.0,
        descricao="Espaço para melhoria",
        prisma=Prisma.LIDERANCA_ADAPTATIVA,
    )
    mais_comum = MetricCardRead(
        rotulo="Mais Comum",
        titulo="Cultura Empreendedora",
        valor=75.0,
        descricao="Comportamento padrão",
        prisma=Prisma.CULTURA_EMPREENDEDORA,
    )

    fake_service = AsyncMock()
    fake_service.calculate_company_summary.return_value = CompanySummaryRead(
        form_id=form_id,
        organization_id=ORGANIZATION_ID,
        nome_empresa="Acme Corp",
        concluidos=10,
        convidados=12,
        taxa_conclusao=83,
        destaque=destaque,
        oportunidade=oportunidade,
        mais_comum=mais_comum,
        scores={p.value: 3.5 for p in Prisma},
        scores_100={p.value: 70.0 for p in Prisma},
    )
    app.dependency_overrides[get_dashboard_service] = lambda: fake_service

    response = client.get(f"/dashboards/company/{form_id}", headers=TOKEN)
    assert response.status_code == 200
    data = response.json()
    assert data["nome_empresa"] == "Acme Corp"
    assert data["taxa_conclusao"] == 83
    assert data["destaque"]["rotulo"] == "Destaque"
    assert data["destaque"]["prisma"] == Prisma.SEGURANCA_PSICOLOGICA.value


def test_get_company_dashboard_returns_404_when_missing(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "gestor")
    fake_service = AsyncMock()
    fake_service.calculate_company_summary.side_effect = NotFoundError(
        "Formulário não encontrado"
    )
    app.dependency_overrides[get_dashboard_service] = lambda: fake_service

    response = client.get(f"/dashboards/company/{uuid.uuid4()}", headers=TOKEN)
    assert response.status_code == 404


def test_get_company_dashboard_returns_403_when_forbidden(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "gestor")
    fake_service = AsyncMock()
    fake_service.calculate_company_summary.side_effect = ForbiddenError(
        "Sem acesso ao dashboard de outra organização"
    )
    app.dependency_overrides[get_dashboard_service] = lambda: fake_service

    response = client.get(f"/dashboards/company/{uuid.uuid4()}", headers=TOKEN)
    assert response.status_code == 403


def test_get_company_dashboard_returns_403_for_respondent_on_empty_form(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domains.dashboards.service import DashboardService

    autenticar_como(app, monkeypatch, "respondente", organization_id=ORGANIZATION_ID)
    fake_repo = AsyncMock()
    # Mesmo com o formulário sem submissões, o respondente é barrado com 403
    real_service = DashboardService(fake_repo, AsyncMock())
    app.dependency_overrides[get_dashboard_service] = lambda: real_service

    response = client.get(f"/dashboards/company/{uuid.uuid4()}", headers=TOKEN)
    assert response.status_code == 403
    assert "Apenas administradores e gestores" in response.json()["detail"]
