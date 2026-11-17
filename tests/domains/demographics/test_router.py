"""Testes HTTP das rotas do perfil demográfico da pessoa autenticada."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.demographics.dependencies import get_service
from app.domains.demographics.models import Demographic, Ethnicity
from app.domains.demographics.router import router
from app.domains.demographics.schemas import DemographicCreate
from app.domains.demographics.service import DemographicProfile
from app.domains.users.dependencies import get_service as get_user_service
from app.domains.users.service import UserAccess
from app.shared.exceptions import NotFoundError

TOKEN = {"Authorization": "Bearer token-de-teste"}


class FakeDemographicService:
    def __init__(self) -> None:
        self.profile: DemographicProfile | None = None

    async def get_my_profile(self, link_id: uuid.UUID) -> DemographicProfile:
        if self.profile is None:
            raise NotFoundError("Perfil demográfico não encontrado")
        return self.profile

    async def save_my_profile(
        self, link_id: uuid.UUID, request: DemographicCreate
    ) -> DemographicProfile:
        participant_id = (
            self.profile.demographic.participant_id
            if self.profile is not None
            else uuid.uuid4()
        )
        demographic = Demographic(
            id=self.profile.demographic.id if self.profile is not None else uuid.uuid4(),
            participant_id=participant_id,
            gender=request.gender,
            age_range=request.age_range,
            nationality=request.nationality,
            brazil_state=request.brazil_state,
            portugal_region=request.portugal_region,
            other_nationality=request.other_nationality,
            perspective=request.perspective,
            created_at=datetime(2026, 11, 4, tzinfo=UTC),
            updated_at=None,
        )
        self.profile = DemographicProfile(
            demographic=demographic,
            ethnicities=list(request.ethnicities),
            religions=list(request.religions),
        )
        return self.profile


class FakeUserService:
    def __init__(self, access: UserAccess) -> None:
        self.access = access

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        return self.access


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    service = FakeDemographicService()
    fastapi_app.dependency_overrides[get_service] = lambda: service

    async def fake_validate_token(_token: str) -> dict[str, Any]:
        return {
            "sub": "sub-dev",
            "email": "dev@creed.example.com",
            "realm_access": {"roles": ["respondente"]},
        }

    monkeypatch.setattr("app.shared.authorization.validate_token", fake_validate_token)
    access = UserAccess(
        id=uuid.uuid4(),
        email="dev@creed.example.com",
        role="respondente",
        link_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
    )
    fastapi_app.dependency_overrides[get_user_service] = lambda: FakeUserService(access)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_put_creates_and_get_returns_the_same_profile(client: TestClient) -> None:
    payload = {
        "gender": "feminino",
        "ethnicities": ["europeia"],
        "religions": ["sem_religiao"],
        "perspective": "Minha família influenciou minhas escolhas.",
    }

    saved = client.put("/demographics/me", json=payload, headers=TOKEN)
    loaded = client.get("/demographics/me", headers=TOKEN)

    assert saved.status_code == 200
    assert loaded.status_code == 200
    assert loaded.json() == saved.json()
    assert loaded.json()["perspective"] == payload["perspective"]


def test_second_put_replaces_options_and_empty_put_clears_everything(
    client: TestClient,
) -> None:
    client.put(
        "/demographics/me",
        json={
            "nationality": "brasileira",
            "brazil_state": "RS",
            "ethnicities": ["europeia", "asiatica"],
            "religions": ["crista"],
            "perspective": "Resposta",
        },
        headers=TOKEN,
    )
    replaced = client.put(
        "/demographics/me",
        json={"ethnicities": ["asiatica"]},
        headers=TOKEN,
    )
    cleared = client.put("/demographics/me", json={}, headers=TOKEN)

    assert replaced.json()["ethnicities"] == [Ethnicity.ASIATICA.value]
    assert replaced.json()["religions"] == []
    assert cleared.status_code == 200
    assert cleared.json()["ethnicities"] == []
    assert cleared.json()["religions"] == []
    assert cleared.json()["nationality"] is None
    assert cleared.json()["perspective"] is None


def test_get_before_onboarding_returns_404(client: TestClient) -> None:
    response = client.get("/demographics/me", headers=TOKEN)

    assert response.status_code == 404


def test_without_login_returns_401(client: TestClient) -> None:
    assert client.get("/demographics/me").status_code == 401
    assert client.put("/demographics/me", json={}).status_code == 401


def test_incompatible_nationality_returns_422(client: TestClient) -> None:
    response = client.put(
        "/demographics/me",
        json={"nationality": "portuguesa", "brazil_state": "RS"},
        headers=TOKEN,
    )

    assert response.status_code == 422


def test_perspective_above_2000_characters_returns_422(client: TestClient) -> None:
    response = client.put(
        "/demographics/me", json={"perspective": "a" * 2001}, headers=TOKEN
    )

    assert response.status_code == 422
