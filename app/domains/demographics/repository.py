"""Acesso a dados do perfil demográfico."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.demographics.models import (
    Demographic,
    DemographicEthnicity,
    DemographicReligion,
    Ethnicity,
    Religion,
)


class DemographicRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_participant_id(
        self, participant_id: uuid.UUID
    ) -> Demographic | None:
        result = await self.db.execute(
            select(Demographic).where(Demographic.participant_id == participant_id)
        )
        return result.scalar_one_or_none()

    async def save(self, demographic: Demographic) -> Demographic:
        self.db.add(demographic)
        await self.db.flush()
        await self.db.refresh(demographic)
        return demographic

    async def replace_options(
        self,
        demographic_id: uuid.UUID,
        *,
        ethnicities: list[Ethnicity],
        religions: list[Religion],
    ) -> None:
        await self.db.execute(
            delete(DemographicEthnicity).where(
                DemographicEthnicity.demographic_id == demographic_id
            )
        )
        await self.db.execute(
            delete(DemographicReligion).where(
                DemographicReligion.demographic_id == demographic_id
            )
        )
        self.db.add_all(
            [
                DemographicEthnicity(demographic_id=demographic_id, ethnicity=ethnicity)
                for ethnicity in ethnicities
            ]
        )
        self.db.add_all(
            [
                DemographicReligion(demographic_id=demographic_id, religion=religion)
                for religion in religions
            ]
        )
        await self.db.flush()

    async def get_ethnicities(self, demographic_id: uuid.UUID) -> list[Ethnicity]:
        result = await self.db.execute(
            select(DemographicEthnicity.ethnicity).where(
                DemographicEthnicity.demographic_id == demographic_id
            )
        )
        return list(result.scalars().all())

    async def get_religions(self, demographic_id: uuid.UUID) -> list[Religion]:
        result = await self.db.execute(
            select(DemographicReligion.religion).where(
                DemographicReligion.demographic_id == demographic_id
            )
        )
        return list(result.scalars().all())
