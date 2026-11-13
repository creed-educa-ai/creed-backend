"""Contrato HTTP com services e repositories reais, em schema descartável.

RUN_POSTGRES_TESTS=1 habilita estes testes; usa as variáveis POSTGRES_* normais.
Só a identidade autenticada é simulada. Nenhuma tabela existente é modificada.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models  # noqa: F401 — registra todas as FKs
from app.core.config import settings
from app.core.database import Base, get_db
from app.domains.documents.models import Document
from app.domains.forms.models import Form
from app.domains.forms.router_periods import router
from app.domains.links.models import Link, LinkType, Roles
from app.domains.organizacoes.models import Organization
from app.domains.participants.models import Participant
from app.domains.questions.models import Instrument
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.authorization import AuthenticatedUser, _identity_from_token
from app.shared.instrument import CREED_INSTRUMENT_ID

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_TESTS") != "1", reason="Requer PostgreSQL de teste"
)


@pytest.fixture
async def database():
    schema = f"test_periods_{uuid.uuid4().hex}"
    engine = create_async_engine(
        settings.database_url, connect_args={"server_settings": {"search_path": schema}}
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        organizations = [uuid.uuid4(), uuid.uuid4()]
        links = {}
        async with sessions.begin() as session:
            # Todo período aponta para o instrumento CREED, que a migration grava.
            session.add(Instrument(id=CREED_INSTRUMENT_ID, name="Inventário CREED"))
            for index, org in enumerate(organizations):
                document = Document(value=f"TEST-{org}")
                session.add(document)
                await session.flush()
                session.add(
                    Organization(
                        id=org,
                        name=f"Teste {index}",
                        address="Teste",
                        document_id=document.id,
                    )
                )
            participant = Participant(name="Mentorando de teste")
            session.add(participant)
            await session.flush()
            for name, org, kind, role in [
                ("mentee", organizations[0], LinkType.MENTORIA, Roles.RESPONDENTE),
                ("other_mentee", organizations[0], LinkType.MENTORIA, Roles.RESPONDENTE),
                ("foreign", organizations[1], LinkType.MENTORIA, Roles.RESPONDENTE),
                ("employee", organizations[0], LinkType.EMPREGO, Roles.RESPONDENTE),
                ("manager", organizations[0], LinkType.MENTORIA, Roles.GESTOR),
            ]:
                link = Link(
                    participant_id=participant.id,
                    organization_id=org,
                    type=kind,
                    role=role,
                )
                session.add(link)
                await session.flush()
                links[name] = link.id
        yield sessions, organizations, links
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


@pytest.fixture
async def api(database):
    sessions, organizations, links = database
    app = FastAPI()
    app.include_router(router)

    async def session_dependency():
        async with sessions.begin() as session:
            yield session

    app.dependency_overrides[get_db] = session_dependency

    def authenticate(role="gestor", organization=None):
        org = organization or organizations[0]
        access = UserAccess(
            id=uuid.uuid4(),
            email="teste@example.com",
            role=role,
            link_id=uuid.uuid4(),
            organization_id=org,
        )
        app.dependency_overrides[_identity_from_token] = lambda: AuthenticatedUser(
            sub=str(access.id), email=access.email, roles=[role]
        )
        app.dependency_overrides[get_user_service] = lambda: SimpleNamespace(
            get_active_user_access_by_email=AsyncMock(return_value=access)
        )

    authenticate()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, authenticate, organizations, links


def payload(start=3, end=8, link_id=None):
    # Base fixa por dia: chamadas distintas têm exatamente as mesmas fronteiras.
    base = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "opens_at": (base + timedelta(days=start)).isoformat(),
        "closes_at": (base + timedelta(days=end)).isoformat(),
        "link_id": str(link_id) if link_id else None,
    }


@pytest.mark.parametrize(
    ("role", "target", "recipient", "start", "end", "expected"),
    [
        ("gestor", "other", None, 3, 8, 403),
        ("gestor", "own", "mentee", 3, 8, 403),
        ("admin", "other", "foreign", 3, 8, 403),
        ("admin", "own", None, 3, 8, 403),
        ("respondente", "own", None, 3, 8, 403),
        ("gestor", "missing", None, 3, 8, 404),
        ("gestor", "own", None, 8, 3, 422),
        ("gestor", "own", None, 3, 3, 422),
        ("gestor", "own", None, -1, 8, 422),
        ("admin", "own", "foreign", 3, 8, 422),
        ("admin", "own", "missing", 3, 8, 422),
        ("admin", "own", "employee", 3, 8, 422),
        ("admin", "own", "manager", 3, 8, 422),
    ],
)
async def test_errors_leave_no_form(
    api, database, role, target, recipient, start, end, expected
):
    client, authenticate, organizations, links = api
    org = {"own": organizations[0], "other": organizations[1], "missing": uuid.uuid4()}[
        target
    ]
    authenticate(role, org if target == "missing" else organizations[0])
    link = uuid.uuid4() if recipient == "missing" else links.get(recipient)
    response = await client.post(
        f"/organizations/{org}/periods", json=payload(start, end, link)
    )
    assert response.status_code == expected, response.text
    async with database[0]() as session:
        assert await session.scalar(select(func.count()).select_from(Form)) == 0


async def test_audiences_coexist_and_form_is_persisted(api, database):
    client, authenticate, organizations, links = api
    url = f"/organizations/{organizations[0]}/periods"
    responses = [await client.post(url, json=payload())]
    authenticate("admin")
    for name in ("mentee", "other_mentee"):
        responses.append(await client.post(url, json=payload(link_id=links[name])))
    assert [r.status_code for r in responses] == [201, 201, 201]
    async with database[0]() as session:
        for response in responses:
            body = response.json()
            form = await session.get(Form, uuid.UUID(body["id"]))
            assert form is not None
            assert form.name == body["name"]
            assert form.name.startswith("Questionário ")
            assert form.organization_id == organizations[0]
            assert body["status"] == "draft"


@pytest.mark.parametrize("individual", [False, True])
@pytest.mark.parametrize(("start", "end"), [(1, 3), (8, 10), (4, 6), (1, 10), (3, 8)])
async def test_touching_or_overlapping_period_returns_409(api, individual, start, end):
    client, authenticate, organizations, links = api
    link = links["mentee"] if individual else None
    authenticate("admin" if individual else "gestor")
    url = f"/organizations/{organizations[0]}/periods"
    assert (await client.post(url, json=payload(link_id=link))).status_code == 201
    response = await client.post(url, json=payload(start, end, link))
    assert response.status_code == 409


@pytest.mark.parametrize("individual", [False, True])
async def test_concurrent_creation_only_persists_one_period(api, database, individual):
    client, authenticate, organizations, links = api
    authenticate("admin" if individual else "gestor")
    body = payload(link_id=links["mentee"] if individual else None)
    url = f"/organizations/{organizations[0]}/periods"
    responses = await asyncio.wait_for(
        asyncio.gather(*(client.post(url, json=body) for _ in range(5))), timeout=15
    )
    assert sorted(r.status_code for r in responses) == [201, 409, 409, 409, 409]
    async with database[0]() as session:
        assert await session.scalar(select(func.count()).select_from(Form)) == 1


async def test_disjoint_periods_are_allowed(api):
    client, _, organizations, _ = api
    url = f"/organizations/{organizations[0]}/periods"
    for start, end in [(3, 8), (9, 12)]:
        assert (await client.post(url, json=payload(start, end))).status_code == 201
