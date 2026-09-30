"""Regra de negócio do domínio links (ADR-002, secao 2.2).

Esta camada não conhece HTTP nem detalhes de ORM. Participante é de outro domínio:
a pergunta "ele existe?" vai ao `ParticipantService`, nunca ao model de
`participants`.
"""

import uuid

from app.domains.links.models import Link
from app.domains.links.repository import LinkRepository
from app.domains.links.schemas import LinkCreate
from app.domains.participants.service import ParticipantService
from app.shared.exceptions import NotFoundError, ValidationError


class LinkService:
    def __init__(
        self, repository: LinkRepository, participants: ParticipantService
    ) -> None:
        self.repository = repository
        self.participants = participants

    async def create_link_service(
        self, organization_id: uuid.UUID, request: LinkCreate
    ) -> Link:
        """Monta e grava o vínculo.

        O participante precisa existir. Participante inexistente é `ValidationError`
        (422), e não `NotFoundError`: o id veio no corpo, não no endereço (spec da
        CREED-47, item 11). A organização ainda não é conferida: `Organization` não
        tem tabela (CREED-38).

        Sem conflito para checar: o `.dbml` não define unicidade no vínculo.
        """
        try:
            await self.participants.get_participant(request.participant_id)
        except NotFoundError as exc:
            raise ValidationError(exc.message) from exc

        link = Link(
            organization_id=organization_id,
            participant_id=request.participant_id,
            department_id=request.department_id,
            type=request.type,
            role=request.role,
        )
        return await self.repository.insert(link)

    async def get_link_by_id_service(self, link_id: uuid.UUID) -> Link | None:
        """Lê um vínculo pelo id, ou `None` se não existir.

        Não levanta `NotFoundError`: quem chama decide o que a ausência significa
        (404 no cadastro de usuário, 401 no login — task 4 e 5).
        """
        return await self.repository.get_by_id(link_id)
