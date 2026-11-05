"""Regras do perfil demográfico da pessoa autenticada."""

import uuid
from dataclasses import dataclass

from app.domains.demographics.models import Demographic, Ethnicity, Religion
from app.domains.demographics.repository import DemographicRepository
from app.domains.demographics.schemas import DemographicCreate
from app.domains.links.service import LinkService
from app.shared.exceptions import NotFoundError


@dataclass
class DemographicProfile:
    demographic: Demographic
    ethnicities: list[Ethnicity]
    religions: list[Religion]


class DemographicService:
    def __init__(self, repository: DemographicRepository, links: LinkService) -> None:
        self.repository = repository
        self.links = links

    async def get_my_profile(self, link_id: uuid.UUID) -> DemographicProfile:
        participant_id = await self._participant_id(link_id)
        demographic = await self.repository.get_by_participant_id(participant_id)
        if demographic is None:
            raise NotFoundError("Perfil demográfico não encontrado")
        return await self._profile(demographic)

    async def save_my_profile(
        self, link_id: uuid.UUID, request: DemographicCreate
    ) -> DemographicProfile:
        participant_id = await self._participant_id(link_id)
        demographic = await self.repository.get_by_participant_id(participant_id)
        if demographic is None:
            demographic = Demographic(participant_id=participant_id)

        demographic.gender = request.gender
        demographic.age_range = request.age_range
        demographic.nationality = request.nationality
        demographic.brazil_state = request.brazil_state
        demographic.portugal_region = request.portugal_region
        demographic.other_nationality = request.other_nationality
        demographic.perspective = request.perspective

        demographic = await self.repository.save(demographic)
        await self.repository.replace_options(
            demographic.id,
            ethnicities=request.ethnicities,
            religions=request.religions,
        )
        return DemographicProfile(
            demographic=demographic,
            ethnicities=list(request.ethnicities),
            religions=list(request.religions),
        )

    async def _participant_id(self, link_id: uuid.UUID) -> uuid.UUID:
        link = await self.links.get_link_by_id_service(link_id)
        if link is None:
            raise NotFoundError(f"Vínculo {link_id} não encontrado")
        return link.participant_id

    async def _profile(self, demographic: Demographic) -> DemographicProfile:
        return DemographicProfile(
            demographic=demographic,
            ethnicities=await self.repository.get_ethnicities(demographic.id),
            religions=await self.repository.get_religions(demographic.id),
        )
