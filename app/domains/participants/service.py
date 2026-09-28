"""Regra de negócio do domínio participants (ADR-0004).

Esta camada não conhece HTTP nem detalhes de ORM.
"""

import uuid

from app.domains.participants.models import Participant
from app.domains.participants.repository import ParticipantRepository
from app.domains.participants.schemas import ParticipantCreate
from app.shared.enums import RecordStatus
from app.shared.exceptions import NotFoundError


class ParticipantService:
    def __init__(self, repository: ParticipantRepository) -> None:
        self.repository = repository

    async def create_participant(self, request: ParticipantCreate) -> Participant:
        # Nenhuma rota muda o status nesta entrega: todo participante nasce ativo.
        participant = Participant(name=request.name, status=RecordStatus.ACTIVE)
        return await self.repository.create(participant)

    async def get_participant(self, participant_id: uuid.UUID) -> Participant:
        participant = await self.repository.get_by_id(participant_id)

        if participant is None:
            raise NotFoundError(f"Participante {participant_id} não encontrado")

        return participant
