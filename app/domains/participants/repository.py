"""Acesso a dados do domínio participants.

Esta camada NÃO contém regra de negócio: só queries. Quem decide o que fazer com
um `None` é o service.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.participants.models import Participant


class ParticipantRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, participant_id: uuid.UUID) -> Participant | None:
        result = await self.db.execute(
            select(Participant).where(Participant.id == participant_id)
        )
        return result.scalar_one_or_none()

    async def create(self, participant: Participant) -> Participant:
        """Cria um participante no banco."""
        self.db.add(participant)
        await self.db.flush()
        await self.db.refresh(participant)
        return participant
