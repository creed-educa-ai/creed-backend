"""Testes de app/domains/dashboards/router.py."""

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.dashboards.dependencies import get_service as get_dashboard_service
from app.domains.dashboards.router import router
from app.domains.dashboards.schemas import (
    CompanyDashboardRead,
    CompanySummaryRead,
    ComparisonOptionsRead,
    CreedSummaryRead,
    HighlightRead,
    PeriodOptionRead,
    UserDashboardRead,
)
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.enums import DepartmentType, Dimension, Prisma
from app.shared.exceptions import ForbiddenError, NotFoundError, ValidationError

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


# ---------------------------------------------------------------------------
# GET /dashboards/me
# ---------------------------------------------------------------------------


def _user_dashboard(period: uuid.UUID) -> UserDashboardRead:
    return UserDashboardRead(
        organization_name="Empresa Exemplo",
        periods=[
            PeriodOptionRead(
                id=period,
                opens_at=datetime(2026, 10, 1, 12, tzinfo=UTC),
                closes_at=datetime(2026, 10, 15, 12, tzinfo=UTC),
            )
        ],
        period=period,
        scores=dict.fromkeys(Prisma, 62.5),
        dimensions=dict.fromkeys(Dimension, 62.5),
        comparison_options=ComparisonOptionsRead(
            periods=[period], departments=[], default_period=None
        ),
        comparisons=[],
        creed_summary=CreedSummaryRead(
            analiseTexto=[],
            recomendacaoTexto=[],
            prismas={},
            destaque=Prisma.SEGURANCA_PSICOLOGICA,
            oportunidade=Prisma.NEUROINOVACAO_PRISMA,
        ),
    )


def test_me_exige_autenticacao(client: TestClient) -> None:
    assert client.get("/dashboards/me").status_code == 401


def test_me_devolve_o_resultado_com_os_nomes_do_contrato(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "respondente")
    period = uuid.uuid4()
    service = AsyncMock()
    service.get_user_dashboard.return_value = _user_dashboard(period)
    app.dependency_overrides[get_dashboard_service] = lambda: service

    resp = client.get("/dashboards/me", params={"period": str(period)}, headers=TOKEN)

    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == str(period)
    assert data["scores"]["seguranca_psicologica"] == 62.5
    assert data["dimensions"]["S2"] == 62.5
    # Os nomes em português do contrato do front (decisão D5).
    assert data["creed_summary"]["analiseTexto"] == []
    assert data["creed_summary"]["destaque"] == "seguranca_psicologica"
    assert service.get_user_dashboard.await_args.kwargs["period"] == period


def test_me_sem_period_pede_o_mais_recente(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "respondente")
    service = AsyncMock()
    service.get_user_dashboard.return_value = _user_dashboard(uuid.uuid4())
    app.dependency_overrides[get_dashboard_service] = lambda: service

    client.get("/dashboards/me", headers=TOKEN)

    assert service.get_user_dashboard.await_args.kwargs["period"] is None


def test_me_sem_resultado_e_404(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "respondente")
    service = AsyncMock()
    service.get_user_dashboard.side_effect = NotFoundError("Você ainda não tem resultado")
    app.dependency_overrides[get_dashboard_service] = lambda: service

    resp = client.get("/dashboards/me", headers=TOKEN)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Você ainda não tem resultado"


def test_me_period_que_nao_e_uuid_e_422(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "respondente")
    app.dependency_overrides[get_dashboard_service] = lambda: AsyncMock()

    resp = client.get("/dashboards/me", params={"period": "2026/1"}, headers=TOKEN)

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /dashboards/company
# ---------------------------------------------------------------------------


def _company_dashboard(period: uuid.UUID) -> CompanyDashboardRead:
    destaque = HighlightRead(prisma=Prisma.SEGURANCA_PSICOLOGICA, valor=70)
    return CompanyDashboardRead(
        **_user_dashboard(period).model_dump(),
        department=None,
        member_id=None,
        departments=[DepartmentType.MARKETING],
        members=[],
        company_summary=CompanySummaryRead(
            concluidos=8,
            convidados=9,
            destaque=destaque,
            oportunidade=destaque,
            maisComum=destaque,
        ),
        alignment=None,
        department_matrix=[],
    )


def _servico_da_empresa(app: FastAPI, **comportamento: Any) -> AsyncMock:
    service = AsyncMock()
    service.get_company_dashboard.configure_mock(**comportamento)
    app.dependency_overrides[get_dashboard_service] = lambda: service
    return service


def test_empresa_exige_autenticacao(client: TestClient) -> None:
    assert client.get("/dashboards/company").status_code == 401


def test_empresa_repassa_os_filtros_e_devolve_o_contrato(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "gestor")
    period, member = uuid.uuid4(), uuid.uuid4()
    service = _servico_da_empresa(app, return_value=_company_dashboard(period))

    resp = client.get(
        "/dashboards/company",
        params={"period": str(period), "member_id": str(member)},
        headers=TOKEN,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["company_summary"]["maisComum"]["prisma"] == "seguranca_psicologica"
    # Sem título nem descrição: são do i18n do front (D2).
    assert set(data["company_summary"]["destaque"]) == {"prisma", "valor"}
    kwargs = service.get_company_dashboard.await_args.kwargs
    assert kwargs["period"] == period
    assert kwargs["member_id"] == member
    assert kwargs["department"] is None
    assert kwargs["organization_id"] is None


def test_empresa_setor_vai_pelo_valor_do_enum(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "gestor")
    service = _servico_da_empresa(app, return_value=_company_dashboard(uuid.uuid4()))

    client.get("/dashboards/company", params={"department": "Marketing"}, headers=TOKEN)

    kwargs = service.get_company_dashboard.await_args.kwargs
    assert kwargs["department"] is DepartmentType.MARKETING


def test_empresa_setor_fora_do_enum_e_422(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "gestor")
    _servico_da_empresa(app)

    resp = client.get(
        "/dashboards/company", params={"department": "Vendas"}, headers=TOKEN
    )

    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("erro", "codigo"),
    [
        (NotFoundError("Ainda não há resultados"), 404),
        (ForbiddenError("Sem acesso ao dashboard de outra organização"), 403),
        (ValidationError("A administradora precisa informar a organização"), 422),
    ],
)
def test_empresa_erros_do_service_viram_codigos_http(
    app: FastAPI,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    erro: Exception,
    codigo: int,
) -> None:
    autenticar_como(app, monkeypatch, "gestor")
    _servico_da_empresa(app, side_effect=erro)

    resp = client.get("/dashboards/company", headers=TOKEN)

    assert resp.status_code == codigo
    assert resp.json()["detail"] == str(erro.message)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# GET /dashboards/overview
# ---------------------------------------------------------------------------


def test_retrato_exige_o_tipo(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "admin")
    app.dependency_overrides[get_dashboard_service] = lambda: AsyncMock()

    assert client.get("/dashboards/overview", headers=TOKEN).status_code == 422
    assert (
        client.get(
            "/dashboards/overview", params={"kind": "setores"}, headers=TOKEN
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    ("erro", "codigo"),
    [
        (NotFoundError("Ainda não há resultados"), 404),
        (ForbiddenError("Só a administradora vê o retrato de todos"), 403),
    ],
)
def test_retrato_erros_viram_codigos_http(
    app: FastAPI,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    erro: Exception,
    codigo: int,
) -> None:
    autenticar_como(app, monkeypatch, "gestor")
    service = AsyncMock()
    service.get_overview.side_effect = erro
    app.dependency_overrides[get_dashboard_service] = lambda: service

    resp = client.get("/dashboards/overview", params={"kind": "companies"}, headers=TOKEN)

    assert resp.status_code == codigo
    assert service.get_overview.await_args.kwargs["kind"] == "companies"


def test_admin_ve_o_dashboard_de_um_mentorando(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    autenticar_como(app, monkeypatch, "admin")
    mentorando, period = uuid.uuid4(), uuid.uuid4()
    service = AsyncMock()
    service.get_member_dashboard.return_value = _user_dashboard(period).model_copy(
        update={"member_name": "Mentorando 1"}
    )
    app.dependency_overrides[get_dashboard_service] = lambda: service

    resp = client.get(
        f"/dashboards/members/{mentorando}",
        params={"period": str(period)},
        headers=TOKEN,
    )

    assert resp.status_code == 200
    assert resp.json()["member_name"] == "Mentorando 1"
    kwargs = service.get_member_dashboard.await_args.kwargs
    assert kwargs["member_id"] == mentorando
    assert kwargs["period"] == period


@pytest.mark.parametrize(
    ("erro", "codigo"),
    [(ForbiddenError("Só a administradora"), 403), (NotFoundError("Sem resultado"), 404)],
)
def test_dashboard_de_mentorando_traduz_os_erros(
    app: FastAPI,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    erro: Exception,
    codigo: int,
) -> None:
    autenticar_como(app, monkeypatch, "gestor")
    service = AsyncMock()
    service.get_member_dashboard.side_effect = erro
    app.dependency_overrides[get_dashboard_service] = lambda: service

    resp = client.get(f"/dashboards/members/{uuid.uuid4()}", headers=TOKEN)

    assert resp.status_code == codigo
