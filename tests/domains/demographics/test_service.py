"""Testes das regras de gravação e leitura do perfil demográfico."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.domains.demographics.models import Demographic, Ethnicity, Religion
from app.domains.demographics.schemas import DemographicCreate
from app.domains.demographics.service import DemographicService
from app.shared.exceptions import NotFoundError


class FakeDemographicRepository:
    def __init__(self) -> None:
        self.demographic: Demographic | None = None
        self.ethnicities: list[Ethnicity] = []
        self.religions: list[Religion] = []

    async def get_by_participant_id(
        self, participant_id: uuid.UUID
    ) -> Demographic | None:
        if self.demographic is None or self.demographic.participant_id != participant_id:
            return None
        return self.demographic

    async def save(self, demographic: Demographic) -> Demographic:
        if demographic.id is None:
            demographic.id = uuid.uuid4()
            demographic.created_at = datetime(2026, 11, 4, tzinfo=UTC)
            demographic.updated_at = None
        self.demographic = demographic
        return demographic

    async def replace_options(
        self,
        demographic_id: uuid.UUID,
        *,
        ethnicities: list[Ethnicity],
        religions: list[Religion],
    ) -> None:
        self.ethnicities = list(ethnicities)
        self.religions = list(religions)

    async def get_ethnicities(self, demographic_id: uuid.UUID) -> list[Ethnicity]:
        return list(self.ethnicities)

    async def get_religions(self, demographic_id: uuid.UUID) -> list[Religion]:
        return list(self.religions)


class FakeLinkService:
    def __init__(self, link_id: uuid.UUID, participant_id: uuid.UUID) -> None:
        self.link_id = link_id
        self.participant_id = participant_id

    async def get_link_by_id_service(self, link_id: uuid.UUID) -> object | None:
        if link_id != self.link_id:
            return None
        return SimpleNamespace(participant_id=self.participant_id)


def service(
    repository: FakeDemographicRepository,
    link_id: uuid.UUID,
    participant_id: uuid.UUID,
) -> DemographicService:
    return DemographicService(
        repository,  # type: ignore[arg-type]
        FakeLinkService(link_id, participant_id),  # type: ignore[arg-type]
    )


async def test_first_save_creates_the_profile_for_the_links_participant() -> None:
    repository = FakeDemographicRepository()
    link_id = uuid.uuid4()
    participant_id = uuid.uuid4()

    profile = await service(repository, link_id, participant_id).save_my_profile(
        link_id,
        DemographicCreate(
            gender="feminino",
            ethnicities=["europeia"],
            religions=["sem_religiao"],
            perspective="Minha família influenciou minhas escolhas.",
        ),
    )

    assert profile.demographic.participant_id == participant_id
    assert profile.demographic.perspective == "Minha família influenciou minhas escolhas."
    assert profile.ethnicities == [Ethnicity.EUROPEIA]
    assert profile.religions == [Religion.SEM_RELIGIAO]


async def test_second_save_replaces_scalars_and_all_options() -> None:
    repository = FakeDemographicRepository()
    link_id = uuid.uuid4()
    demographic_service = service(repository, link_id, uuid.uuid4())
    await demographic_service.save_my_profile(
        link_id,
        DemographicCreate(ethnicities=["europeia", "asiatica"], religions=["crista"]),
    )

    profile = await demographic_service.save_my_profile(
        link_id,
        DemographicCreate(ethnicities=["asiatica"], religions=[]),
    )

    assert profile.ethnicities == [Ethnicity.ASIATICA]
    assert profile.religions == []


async def test_empty_save_clears_a_filled_profile_but_keeps_it_existing() -> None:
    repository = FakeDemographicRepository()
    link_id = uuid.uuid4()
    demographic_service = service(repository, link_id, uuid.uuid4())
    await demographic_service.save_my_profile(
        link_id,
        DemographicCreate(
            nationality="brasileira",
            brazil_state="RS",
            perspective="Resposta anterior",
            ethnicities=["europeia"],
        ),
    )

    saved = await demographic_service.save_my_profile(link_id, DemographicCreate())
    loaded = await demographic_service.get_my_profile(link_id)

    assert saved.demographic.nationality is None
    assert saved.demographic.brazil_state is None
    assert saved.demographic.perspective is None
    assert loaded.ethnicities == []
    assert loaded.religions == []


async def test_get_without_profile_raises_not_found() -> None:
    link_id = uuid.uuid4()

    with pytest.raises(NotFoundError, match="Perfil demográfico"):
        await service(FakeDemographicRepository(), link_id, uuid.uuid4()).get_my_profile(
            link_id
        )
