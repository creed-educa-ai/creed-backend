"""Testes de app/domains/links/router_members.py: o contrato HTTP das rotas de membros.

`TestClient` com `dependency_overrides`, como em `test_router.py` deste domínio. O
service é um dublê que devolve o membro ou levanta a exceção do service real: o que
se prova aqui é a tradução para o código HTTP e o que a guarda deixa passar. A regra
(quem pode, o que é 404) está provada em `test_service_members.py`.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.forms.schemas import PeriodStatus
from app.domains.links.dependencies import get_service as get_link_service
from app.domains.links.models import Link, LinkType, Roles
from app.domains.links.router_members import router
from app.domains.links.schemas import MemberPeriod
from app.domains.links.service import Member, MemberWithPeriod
from app.domains.users.dependencies import get_member_removal_service
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.enums import DepartmentType
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)

ORG_ID = uuid.UUID("8f14e45f-ceea-467e-adde-3f81905dbc1c")
LINK_ID = uuid.UUID("d40b7a55-b9cc-4b78-ae5d-ab325fd655e2")
URL = f"/api/v1/organizations/{ORG_ID}/members/{LINK_ID}"


class _FakeLinkService:
    """Dublê: guarda o que recebeu e devolve o membro, ou levanta `error`."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def update_member_department(
        self,
        organization_id: uuid.UUID,
        link_id: uuid.UUID,
        department: DepartmentType | None,
        *,
        role: str,
        own_organization_id: uuid.UUID,
    ) -> Member:
        self.calls.append(
            {
                "organization_id": organization_id,
                "link_id": link_id,
                "department": department,
                "role": role,
                "own_organization_id": own_organization_id,
            }
        )
        if self.error is not None:
            raise self.error
        link = Link(
            id=link_id,
            participant_id=uuid.uuid4(),
            organization_id=organization_id,
            department_id=uuid.uuid4() if department else None,
            type=LinkType.EMPREGO,
            role=Roles.RESPONDENTE,
            start_at=datetime(2026, 11, 1, tzinfo=UTC),
            end_at=None,
            created_at=datetime(2026, 11, 1, tzinfo=UTC),
            updated_at=datetime(2026, 11, 9, 14, tzinfo=UTC),
        )
        return Member(
            link=link, name="Ana Souza", email="ana@empresa.com.br", department=department
        )


class _FakeUserService:
    def __init__(self, access: UserAccess) -> None:
        self._access = access

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self._access


def _install_validate_token(monkeypatch: pytest.MonkeyPatch, roles: list[str]) -> None:
    async def _fake(_token: str) -> dict[str, Any]:
        return {
            "sub": "user-123",
            "email": "dev@creed.example.com",
            "realm_access": {"roles": roles},
        }

    monkeypatch.setattr("app.shared.authorization.validate_token", _fake)


def _client(
    monkeypatch: pytest.MonkeyPatch,
    link_service: object,
    role: str | None = "gestor",
) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_link_service] = lambda: link_service
    if role is not None:
        _install_validate_token(monkeypatch, [role])
        access = UserAccess(
            id=uuid.uuid4(),
            email="dev@creed.example.com",
            role=role,
            link_id=uuid.uuid4(),
            organization_id=ORG_ID,
        )
        app.dependency_overrides[get_user_service] = lambda: _FakeUserService(access)
    return TestClient(app)


AUTH = {"Authorization": "Bearer token-de-teste"}


def test_gestor_picks_a_department_and_gets_the_member_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link_service = _FakeLinkService()

    response = _client(monkeypatch, link_service).patch(
        URL, json={"department": "Marketing"}, headers=AUTH
    )

    assert response.status_code == 200
    assert response.json() == {
        "link_id": str(LINK_ID),
        "name": "Ana Souza",
        "email": "ana@empresa.com.br",
        "role": "respondente",
        "type": "emprego",
        "department": "Marketing",
        "updated_at": "2026-11-09T14:00:00Z",
    }
    # Papel e organização vêm do vínculo de quem pede, não do corpo.
    assert link_service.calls == [
        {
            "organization_id": ORG_ID,
            "link_id": LINK_ID,
            "department": DepartmentType.MARKETING,
            "role": "gestor",
            "own_organization_id": ORG_ID,
        }
    ]


def test_null_removes_the_department(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _client(monkeypatch, _FakeLinkService()).patch(
        URL, json={"department": None}, headers=AUTH
    )

    assert response.status_code == 200
    assert response.json()["department"] is None


def test_without_authorization_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    link_service = _FakeLinkService()

    response = _client(monkeypatch, link_service, role=None).patch(
        URL, json={"department": "Marketing"}
    )

    assert response.status_code == 401
    assert link_service.calls == []


def test_respondente_returns_403_without_calling_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link_service = _FakeLinkService()

    response = _client(monkeypatch, link_service, role="respondente").patch(
        URL, json={"department": "Marketing"}, headers=AUTH
    )

    assert response.status_code == 403
    assert link_service.calls == []


def test_service_forbidden_becomes_403(monkeypatch: pytest.MonkeyPatch) -> None:
    # O gestor de outra organização passa pela guarda (é gestor) e é barrado
    # pelo service: o router só traduz.
    link_service = _FakeLinkService(
        ForbiddenError("Sem acesso aos membros desta organização")
    )

    response = _client(monkeypatch, link_service).patch(
        URL, json={"department": "Marketing"}, headers=AUTH
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Sem acesso aos membros desta organização"}


def test_service_not_found_becomes_404(monkeypatch: pytest.MonkeyPatch) -> None:
    link_service = _FakeLinkService(NotFoundError(f"Membro {LINK_ID} não encontrado"))

    response = _client(monkeypatch, link_service).patch(
        URL, json={"department": "Marketing"}, headers=AUTH
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"department": "Vendas"},
        {"department": "Recursos Humanos"},
        {"department": "Marketing", "role": "admin"},
    ],
    ids=["vazio", "fora-dos-cinco", "rotulo-com-espaco", "campo-a-mais"],
)
def test_invalid_body_returns_422_without_calling_the_service(
    monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]
) -> None:
    link_service = _FakeLinkService()

    response = _client(monkeypatch, link_service).patch(URL, json=body, headers=AUTH)

    assert response.status_code == 422
    assert link_service.calls == []


def test_link_id_not_uuid_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _client(monkeypatch, _FakeLinkService()).patch(
        f"/api/v1/organizations/{ORG_ID}/members/nao-e-uuid",
        json={"department": "Marketing"},
        headers=AUTH,
    )

    assert response.status_code == 422


LIST_URL = f"/api/v1/organizations/{ORG_ID}/members"


class _FakeListService:
    """Dublê da lista: guarda o que recebeu e devolve `members`, ou levanta `error`."""

    def __init__(
        self,
        members: list[MemberWithPeriod] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.members = list(members or [])
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def list_members(
        self,
        organization_id: uuid.UUID,
        link_type: LinkType | None,
        *,
        role: str,
        own_organization_id: uuid.UUID,
    ) -> list[MemberWithPeriod]:
        self.calls.append(
            {
                "organization_id": organization_id,
                "link_type": link_type,
                "role": role,
                "own_organization_id": own_organization_id,
            }
        )
        if self.error is not None:
            raise self.error
        return self.members


def _mentee(period: MemberPeriod | None) -> MemberWithPeriod:
    link = Link(
        id=LINK_ID,
        participant_id=uuid.uuid4(),
        organization_id=ORG_ID,
        department_id=None,
        type=LinkType.MENTORIA,
        role=Roles.RESPONDENTE,
        start_at=datetime(2026, 11, 1, tzinfo=UTC),
        end_at=None,
        created_at=datetime(2026, 11, 1, tzinfo=UTC),
        updated_at=None,
    )
    member = Member(link=link, name="Ana Souza", email=None, department=None)
    return MemberWithPeriod(member=member, period=period)


def test_list_returns_members_with_their_period(monkeypatch: pytest.MonkeyPatch) -> None:
    period = MemberPeriod(
        form_id=uuid.UUID("5b1f0a7e-4c2d-4f7a-9d3e-2a6b8c0d1e2f"),
        opens_at=datetime(2026, 11, 1, tzinfo=UTC),
        closes_at=datetime(2026, 11, 30, tzinfo=UTC),
        period_status=PeriodStatus.OPEN,
        has_answered=True,
    )
    service = _FakeListService([_mentee(period), _mentee(None)])

    response = _client(monkeypatch, service).get(LIST_URL, headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body[0] == {
        "link_id": str(LINK_ID),
        "name": "Ana Souza",
        "email": None,
        "role": "respondente",
        "type": "mentoria",
        "department": None,
        "updated_at": None,
        "period": {
            "form_id": "5b1f0a7e-4c2d-4f7a-9d3e-2a6b8c0d1e2f",
            "opens_at": "2026-11-01T00:00:00Z",
            "closes_at": "2026-11-30T00:00:00Z",
            "period_status": "open",
            "has_answered": True,
        },
    }
    assert body[1]["period"] is None
    # Sem `?type=`, o service recebe `None`; papel e organização vêm do login.
    assert service.calls == [
        {
            "organization_id": ORG_ID,
            "link_type": None,
            "role": "gestor",
            "own_organization_id": ORG_ID,
        }
    ]


def test_type_query_reaches_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _FakeListService()

    response = _client(monkeypatch, service).get(
        LIST_URL, params={"type": "mentoria"}, headers=AUTH
    )

    assert response.status_code == 200
    assert service.calls[0]["link_type"] is LinkType.MENTORIA


def test_empty_organization_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _client(monkeypatch, _FakeListService()).get(LIST_URL, headers=AUTH)

    assert response.status_code == 200
    assert response.json() == []


def test_list_without_authorization_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _FakeListService()

    response = _client(monkeypatch, service, role=None).get(LIST_URL)

    assert response.status_code == 401
    assert service.calls == []


def test_list_as_respondente_returns_403_without_calling_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeListService()

    response = _client(monkeypatch, service, role="respondente").get(
        LIST_URL, headers=AUTH
    )

    assert response.status_code == 403
    assert service.calls == []


def test_list_service_forbidden_becomes_403(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _FakeListService(
        error=ForbiddenError("Sem acesso aos membros desta organização")
    )

    response = _client(monkeypatch, service).get(LIST_URL, headers=AUTH)

    assert response.status_code == 403


def test_list_unknown_organization_becomes_404(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _FakeListService(
        error=NotFoundError(f"Organização {ORG_ID} não encontrada")
    )

    response = _client(monkeypatch, service).get(LIST_URL, headers=AUTH)

    assert response.status_code == 404


def test_invalid_type_returns_422_without_calling_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeListService()

    response = _client(monkeypatch, service).get(
        LIST_URL, params={"type": "vendedor"}, headers=AUTH
    )

    assert response.status_code == 422
    assert service.calls == []


# --- Exclusão de membro (M-3) ------------------------------------------------

OWN_LINK_ID = uuid.UUID("3f2b8c1e-7a4d-4e9b-9c0a-5d6e7f8a9b0c")


class _FakeRemovalService:
    """Dublê do `MemberRemovalService`: guarda o que recebeu, ou levanta `error`."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def remove_member(
        self,
        organization_id: uuid.UUID,
        link_id: uuid.UUID,
        *,
        own_organization_id: uuid.UUID,
        own_link_id: uuid.UUID,
    ) -> None:
        self.calls.append(
            {
                "organization_id": organization_id,
                "link_id": link_id,
                "own_organization_id": own_organization_id,
                "own_link_id": own_link_id,
            }
        )
        if self.error is not None:
            raise self.error


def _delete_client(
    monkeypatch: pytest.MonkeyPatch,
    removal_service: _FakeRemovalService,
    role: str | None = "gestor",
) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_member_removal_service] = lambda: removal_service
    if role is not None:
        _install_validate_token(monkeypatch, [role])
        access = UserAccess(
            id=uuid.uuid4(),
            email="dev@creed.example.com",
            role=role,
            link_id=OWN_LINK_ID,
            organization_id=ORG_ID,
        )
        app.dependency_overrides[get_user_service] = lambda: _FakeUserService(access)
    return TestClient(app)


@pytest.mark.parametrize("role", ["gestor", "admin"])
def test_delete_returns_204_without_body(
    monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    service = _FakeRemovalService()

    response = _delete_client(monkeypatch, service, role=role).delete(URL, headers=AUTH)

    assert response.status_code == 204
    assert response.content == b""
    # A organização e o vínculo de quem pede vêm da sessão, não do endereço.
    assert service.calls == [
        {
            "organization_id": ORG_ID,
            "link_id": LINK_ID,
            "own_organization_id": ORG_ID,
            "own_link_id": OWN_LINK_ID,
        }
    ]


def test_delete_without_authorization_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeRemovalService()

    response = _delete_client(monkeypatch, service, role=None).delete(URL)

    assert response.status_code == 401
    assert service.calls == []


def test_delete_as_respondente_returns_403_without_calling_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeRemovalService()

    response = _delete_client(monkeypatch, service, role="respondente").delete(
        URL, headers=AUTH
    )

    assert response.status_code == 403
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ForbiddenError("Sem acesso aos membros desta organização"), 403),
        (NotFoundError(f"Membro {LINK_ID} não encontrado"), 404),
        (ConflictError("Não é possível excluir o próprio acesso"), 409),
        (ServiceUnavailableError("Não foi possível remover o acesso agora."), 503),
    ],
)
def test_delete_translates_service_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected_status: int
) -> None:
    service = _FakeRemovalService(error=error)

    response = _delete_client(monkeypatch, service).delete(URL, headers=AUTH)

    assert response.status_code == expected_status
    assert response.json() == {"detail": str(error)}


def test_delete_link_id_not_uuid_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _FakeRemovalService()

    response = _delete_client(monkeypatch, service).delete(
        f"/api/v1/organizations/{ORG_ID}/members/nao-e-uuid", headers=AUTH
    )

    assert response.status_code == 422
    assert service.calls == []
