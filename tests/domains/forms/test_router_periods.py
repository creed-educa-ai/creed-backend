"""Testes de contrato de GET /organizations/{organization_id}/periods.

A guarda de papel roda de verdade; a regra de organização e de filtro é provada em
`test_service.py`. Aqui se prova o que chega ao service, o formato da saída e os
status.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.forms.dependencies import get_service
from app.domains.forms.models import Form, FormStatus
from app.domains.forms.router_periods import router
from app.domains.forms.schemas import PeriodRead, PeriodStatus
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.exceptions import ForbiddenError

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
