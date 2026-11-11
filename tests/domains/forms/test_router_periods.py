"""Testes de contrato de /organizations/{organization_id}/periods.

A guarda de papel roda de verdade; a regra de organização e de filtro é provada em
`test_service.py`. Aqui se prova o que chega ao service, o formato da saída e os
status.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.forms.dependencies import get_service
from app.domains.forms.models import Form, FormStatus
from app.domains.forms.router_periods import router
from app.domains.forms.schemas import PeriodCreate, PeriodRead, PeriodStatus
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)

ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TOKEN = {"Authorization": "Bearer valido"}
URL = f"/organizations/{ORGANIZATION_ID}/periods"


def um_periodo() -> PeriodRead:
    form = Form(
        id=uuid.uuid4(),
        name="Período de novembro",
        organization_id=ORGANIZATION_ID,
        status=FormStatus.DRAFT,
        opens_at=datetime(2026, 11, 1, tzinfo=UTC),
        closes_at=datetime(2026, 11, 30, tzinfo=UTC),
        link_id=None,
        created_at=datetime(2026, 10, 30, tzinfo=UTC),
    )
    return PeriodRead.de_form(form, PeriodStatus.OPEN)


class _FakeService:
    def __init__(self, *, recusar: Exception | None = None) -> None:
        self.recusar = recusar
        self.pedido: dict[str, Any] | None = None
        self.form_criado: Form | None = None

    async def create_period(
        self,
        target_organization_id: uuid.UUID,
        request: PeriodCreate,
        *,
        role: str,
        organization_id_user: uuid.UUID,
    ) -> Form:
        self.pedido = {
            "alvo": target_organization_id,
            "request": request,
            "role": role,
            "organization_id_user": organization_id_user,
        }
        if self.recusar is not None:
            raise self.recusar
        self.form_criado = Form(
            id=uuid.uuid4(),
            name=(
                f"Questionário {request.opens_at:%Y-%m-%d} a {request.closes_at:%Y-%m-%d}"
            ),
            organization_id=target_organization_id,
            status=FormStatus.DRAFT,
            opens_at=request.opens_at,
            closes_at=request.closes_at,
            link_id=request.link_id,
            created_at=datetime(2026, 10, 30, tzinfo=UTC),
        )
        return self.form_criado

    async def list_periods(
        self,
        target_organization_id: uuid.UUID,
        *,
        link_id: uuid.UUID | None,
        role: str,
        organization_id: uuid.UUID,
    ) -> list[PeriodRead]:
        self.pedido = {
            "alvo": target_organization_id,
            "link_id": link_id,
            "role": role,
            "organization_id": organization_id,
        }
        if self.recusar is not None:
            raise self.recusar
        return [um_periodo()]


class _FakeUserService:
    def __init__(self, access: UserAccess) -> None:
        self._access = access

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self._access


def montar(monkeypatch: pytest.MonkeyPatch, role: str, fake: _FakeService) -> TestClient:
    email = "dev@creed.example.com"

    async def _fake_validate_token(token: str) -> dict[str, Any]:
        return {"sub": "sub-dev", "email": email, "realm_access": {"roles": [role]}}

    monkeypatch.setattr("app.shared.authorization.validate_token", _fake_validate_token)
    access = UserAccess(
        id=uuid.uuid4(),
        email=email,
        role=role,
        link_id=uuid.uuid4(),
        organization_id=ORGANIZATION_ID,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService(access)
    app.dependency_overrides[get_service] = lambda: fake
    return TestClient(app)


def test_sem_token_devolve_401(monkeypatch: pytest.MonkeyPatch) -> None:
    assert montar(monkeypatch, "gestor", _FakeService()).get(URL).status_code == 401


def test_respondente_devolve_403_sem_chegar_ao_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeService()

    resposta = montar(monkeypatch, "respondente", fake).get(URL, headers=TOKEN)

    assert resposta.status_code == 403
    assert fake.pedido is None


def test_devolve_a_lista_com_a_situacao(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeService()

    resposta = montar(monkeypatch, "gestor", fake).get(URL, headers=TOKEN)

    assert resposta.status_code == 200
    assert resposta.json()[0]["period_status"] == "open"
    assert resposta.json()[0]["opens_at"].startswith("2026-11-01")
    assert fake.pedido == {
        "alvo": ORGANIZATION_ID,
        "link_id": None,
        "role": "gestor",
        "organization_id": ORGANIZATION_ID,
    }


def test_link_id_chega_ao_service(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeService()
    link_id = uuid.uuid4()

    montar(monkeypatch, "admin", fake).get(
        URL, headers=TOKEN, params={"link_id": str(link_id)}
    )

    assert fake.pedido is not None
    assert fake.pedido["link_id"] == link_id


def test_recusa_do_service_devolve_403(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeService(recusar=ForbiddenError("Sem acesso"))

    resposta = montar(monkeypatch, "gestor", fake).get(URL, headers=TOKEN)

    assert resposta.status_code == 403
    assert resposta.json() == {"detail": "Sem acesso"}


class TestCriarPeriodo:
    payload: ClassVar[dict[str, str]] = {
        "opens_at": "2030-01-01T00:00:00Z",
        "closes_at": "2030-02-01T00:00:00Z",
    }

    def test_gestor_cria_periodo_e_recebe_formread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _FakeService()
        client = montar(monkeypatch, "gestor", fake)

        response = client.post(URL, json=self.payload, headers=TOKEN)

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Questionário 2030-01-01 a 2030-02-01"
        assert body["link_id"] is None
        assert fake.pedido is not None
        assert fake.pedido["alvo"] == ORGANIZATION_ID

    def test_admin_envia_link_id_no_corpo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeService()
        client = montar(monkeypatch, "admin", fake)
        link_id = uuid.uuid4()

        response = client.post(
            URL,
            json={**self.payload, "link_id": str(link_id)},
            headers=TOKEN,
        )

        assert response.status_code == 201
        assert fake.pedido is not None
        assert fake.pedido["request"].link_id == link_id

    def test_respondente_devolve_403_sem_chamar_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _FakeService()

        response = montar(monkeypatch, "respondente", fake).post(
            URL, json=self.payload, headers=TOKEN
        )

        assert response.status_code == 403
        assert fake.pedido is None

    @pytest.mark.parametrize(
        ("erro", "status_esperado"),
        [
            (ForbiddenError("Sem acesso"), 403),
            (NotFoundError("Organização não encontrada"), 404),
            (ConflictError("Período sobreposto"), 409),
            (ValidationError("opens_at não pode estar no passado"), 422),
        ],
    )
    def test_traduz_erros_do_service(
        self,
        monkeypatch: pytest.MonkeyPatch,
        erro: Exception,
        status_esperado: int,
    ) -> None:
        fake = _FakeService(recusar=erro)

        response = montar(monkeypatch, "gestor", fake).post(
            URL, json=self.payload, headers=TOKEN
        )

        assert response.status_code == status_esperado

    def test_datas_invalidas_devolvem_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeService()
        payload = {
            "opens_at": "2030-02-01T00:00:00Z",
            "closes_at": "2030-01-01T00:00:00Z",
        }

        response = montar(monkeypatch, "gestor", fake).post(
            URL, json=payload, headers=TOKEN
        )

        assert response.status_code == 422
        assert fake.pedido is None
