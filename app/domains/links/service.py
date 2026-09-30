"""Regra de negócio do domínio links (ADR-002, secao 2.2).

Esta camada não conhece HTTP nem detalhes de ORM.
"""

import uuid

from app.domains.links.models import Link
from app.domains.links.repository import LinkRepository
from app.domains.links.schemas import LinkCreate


class LinkService:
    def __init__(self, repository: LinkRepository) -> None:
        self.repository = repository

    async def create_link_service(
        self, organization_id: uuid.UUID, request: LinkCreate
    ) -> Link:
        """Monta e grava o vínculo.

        Sem conflito para checar: o `.dbml` não define unicidade no vínculo, e não
        há tabela de organização ou de participante para consultar (spec, "Abordagem
        técnica", item 6). O service só monta a entidade e delega ao repository.
        """
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
