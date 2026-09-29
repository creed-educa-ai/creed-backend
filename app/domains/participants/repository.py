"""Acesso a dados do domínio participants.

Esta camada NÃO contém regra de negócio: só queries. Quem decide o que fazer com
um `None` é o service.

`create` devolve `None` quando a constraint única de `document_id` recusa a
gravação — o mesmo formato de `questions/repository.py`. Não é decisão de
negócio: é o banco fechando a corrida que a checagem do service não fecha.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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

    async def get_by_document_id(self, document_id: uuid.UUID) -> Participant | None:
        result = await self.db.execute(
            select(Participant).where(Participant.document_id == document_id)
        )
        return result.scalar_one_or_none()

    async def create(self, participant: Participant) -> Participant | None:
        """Cria um participante no banco.

        Devolve `None` se o documento foi ligado a outra pessoa entre a checagem
        do service e este `flush()` — dois cadastros simultâneos, sem lock,
        fechados pela constraint única.
        """
        self.db.add(participant)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            if "uq_participants_document_id" not in str(exc.orig):
                raise
            return None
        await self.db.refresh(participant)
        return participant
