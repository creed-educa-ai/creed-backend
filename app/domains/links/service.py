"""Regra de negócio do domínio links (ADR-002, secao 2.2).

Esta camada não conhece HTTP nem detalhes de ORM. Participante, organização e setor
são de outros domínios: a pergunta "ele existe?" vai ao service dono de cada um
(`ParticipantService`, `OrganizationService`, `DepartmentService`), nunca ao model.
"""

import uuid

from app.domains.department.service import DepartmentService
from app.domains.links.models import Link
from app.domains.links.repository import LinkRepository
from app.domains.links.schemas import LinkCreate
from app.domains.organizacoes.service import OrganizationService
from app.domains.participants.service import ParticipantService
from app.shared.exceptions import NotFoundError, ValidationError


class LinkService:
    def __init__(
        self,
        repository: LinkRepository,
        participants: ParticipantService,
        organizations: OrganizationService,
        departments: DepartmentService,
    ) -> None:
        self.repository = repository
        self.participants = participants
        self.organizations = organizations
        self.departments = departments

    async def create_link_service(
        self, organization_id: uuid.UUID, request: LinkCreate
    ) -> Link:
        """Monta e grava o vínculo, na ordem de conferência: organização (404),
        participante (422), setor (422).

        A organização veio no endereço: inexistente é `NotFoundError` (404). O
        participante e o setor vieram no corpo: inexistentes são `ValidationError`
        (422), e não `NotFoundError` (spec da CREED-47, item 11). O setor, quando
        vem, precisa ser da mesma organização do vínculo.

        Sem conflito para checar: o `.dbml` não define unicidade no vínculo.
        """
        if not await self.organizations.organization_exists(organization_id):
            raise NotFoundError(f"Organização {organization_id} não encontrada")

        try:
            await self.participants.get_participant(request.participant_id)
        except NotFoundError as exc:
            raise ValidationError(exc.message) from exc

        if request.department_id is not None:
            await self._check_department(request.department_id, organization_id)

        link = Link(
            organization_id=organization_id,
            participant_id=request.participant_id,
            department_id=request.department_id,
            type=request.type,
            role=request.role,
        )
        return await self.repository.insert(link)

    async def _check_department(
        self, department_id: uuid.UUID, organization_id: uuid.UUID
    ) -> None:
        try:
            department = await self.departments.get_by_id(department_id)
        except NotFoundError as exc:
            raise ValidationError(exc.message) from exc

        if department.organization_id != organization_id:
            raise ValidationError(
                f"Departamento {department_id} não é da organização {organization_id}"
            )

    async def get_link_by_id_service(self, link_id: uuid.UUID) -> Link | None:
        """Lê um vínculo pelo id, ou `None` se não existir.

        Não levanta `NotFoundError`: quem chama decide o que a ausência significa
        (404 no cadastro de usuário, 401 no login — task 4 e 5).
        """
        return await self.repository.get_by_id(link_id)
