"""Regra de negócio do domínio participants (ADR-0004).

Esta camada não conhece HTTP nem detalhes de ORM. Documento é de outro domínio:
a pergunta "ele existe?" vai ao `DocumentService`, nunca ao model de `documents`.
"""

import uuid

from app.domains.documents.service import DocumentService
from app.domains.participants.models import Participant
from app.domains.participants.repository import ParticipantRepository
from app.domains.participants.schemas import ParticipantCreate
from app.shared.enums import RecordStatus
from app.shared.exceptions import ConflictError, NotFoundError, ValidationError


def _documento_em_uso(document_id: uuid.UUID | None) -> ConflictError:
    return ConflictError(f"O documento {document_id} já pertence a outro participante")


class ParticipantService:
    def __init__(
        self, repository: ParticipantRepository, documents: DocumentService
    ) -> None:
        self.repository = repository
        self.documents = documents

    async def create_participant(self, request: ParticipantCreate) -> Participant:
        # 🟡 Premissa P-014 — sem documento é válido; com documento, ele precisa
        # existir e não pode estar ligado a outra pessoa.
        if request.document_id is not None:
            if not await self.documents.document_exists(request.document_id):
                raise ValidationError(f"Documento {request.document_id} não encontrado")

            if await self.repository.get_by_document_id(request.document_id) is not None:
                raise _documento_em_uso(request.document_id)

        # Nenhuma rota muda o status nesta entrega: todo participante nasce ativo.
        participant = Participant(
            name=request.name,
            document_id=request.document_id,
            status=RecordStatus.ACTIVE,
        )
        created = await self.repository.create(participant)

        # `None`: outro cadastro ligou o mesmo documento entre a checagem acima e
        # a gravação. Para quem chamou, é o mesmo conflito.
        if created is None:
            raise _documento_em_uso(request.document_id)

        return created

    async def get_participant(self, participant_id: uuid.UUID) -> Participant:
        participant = await self.repository.get_by_id(participant_id)

        if participant is None:
            raise NotFoundError(f"Participante {participant_id} não encontrado")

        return participant
