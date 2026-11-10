"""Regra de negócio do domínio links (ADR-002, secao 2.2).

Esta camada não conhece HTTP nem detalhes de ORM. Participante, organização e setor
são de outros domínios: a pergunta "ele existe?" vai ao service dono de cada um
(`ParticipantService`, `OrganizationService`, `DepartmentService`), nunca ao model.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.domains.department.service import DepartmentService
from app.domains.forms.service import pick_period
from app.domains.links.models import Link, LinkType, Roles
from app.domains.links.repository import LinkRepository
from app.domains.links.schemas import LinkCreate, MemberPeriod
from app.domains.organizacoes.service import OrganizationService
from app.domains.participants.service import ParticipantService
from app.shared.enums import DepartmentType
from app.shared.exceptions import ForbiddenError, NotFoundError, ValidationError


@dataclass
class Member:
    """Um vínculo visto com a pessoa: o que a tabela de membros mostra.

    `email` é `None` quando o vínculo não tem login (criado sem convite).
    """

    link: Link
    name: str
    email: str | None
    department: DepartmentType | None


@dataclass
class MemberWithPeriod:
    """Um membro na lista da organização, com o período que vale para ele."""

    member: Member
    period: MemberPeriod | None


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

    async def update_member_department(
        self,
        organization_id: uuid.UUID,
        link_id: uuid.UUID,
        department: DepartmentType | None,
        *,
        role: str,
        own_organization_id: uuid.UUID,
    ) -> Member:
        """Escolhe, troca ou tira (`None`) o setor de um membro da organização.

        `role` e `own_organization_id` são de quem pede. A ordem de conferência é
        acesso (403), depois vínculo (404): quem não pode mexer na organização
        recebe 403 mesmo para um vínculo que não existe, e a resposta não revela
        quais vínculos existem (mesma regra de `OrganizationService.get`).

        O setor da empresa é criado na hora se ela ainda não tem aquele tipo
        (`DepartmentService.get_or_create`). Não há conferência de organização
        inexistente: o vínculo só é achado se for dela, então organização
        inexistente já cai no 404.
        """
        self._check_can_manage_members(
            organization_id, role=role, own_organization_id=own_organization_id
        )

        found = await self.repository.get_member(organization_id, link_id)
        if found is None:
            raise NotFoundError(
                f"Membro {link_id} não encontrado na organização {organization_id}"
            )
        link, name, email, _old_department = found

        if department is None:
            link.department_id = None
        else:
            company_department = await self.departments.get_or_create(
                organization_id, department
            )
            link.department_id = company_department.id

        await self.repository.save(link)
        return Member(link=link, name=name, email=email, department=department)

    async def get_member_link(
        self, organization_id: uuid.UUID, link_id: uuid.UUID
    ) -> Link:
        """O vínculo, se for desta organização. Sem regra de acesso: quem chama já
        conferiu quem pede (a exclusão de membro, M-3).

        Vínculo inexistente e vínculo de outra organização são o mesmo 404, como em
        `update_member_department`.
        """
        link = await self.repository.get_by_id(link_id)
        if link is None or link.organization_id != organization_id:
            raise NotFoundError(
                f"Membro {link_id} não encontrado na organização {organization_id}"
            )
        return link

    async def validate_mentee_link(
        self, organization_id: uuid.UUID, link_id: uuid.UUID
    ) -> None:
        """Confere o destinatário de um período individual, após a autorização."""
        link = await self.get_member_link(organization_id, link_id)
        if link.type != LinkType.MENTORIA or link.role != Roles.RESPONDENTE:
            raise ValidationError("link_id deve ser um vínculo de mentorando")

    async def delete_link(self, link: Link) -> None:
        """Apaga o vínculo na exclusão de membro (M-3).

        Quem chama já apagou o que aponta para ele: o login, as respostas e os
        questionários individuais.
        """
        await self.repository.delete(link)

    async def participant_has_links(self, participant_id: uuid.UUID) -> bool:
        """Se a pessoa ainda tem vínculo com alguma organização."""
        return await self.repository.count_by_participant(participant_id) > 0

    async def list_members(
        self,
        organization_id: uuid.UUID,
        link_type: LinkType | None,
        *,
        role: str,
        own_organization_id: uuid.UUID,
    ) -> list[MemberWithPeriod]:
        """Os membros da organização, cada um com o período dele (CREED-697).

        `role` e `own_organization_id` são de quem pede. Acesso (403) antes de
        tudo, e organização inexistente é 404: só o `admin` chega a essa conferência.

        Depois de conferir a organização, são três consultas de dados, qualquer que
        seja o número de membros: os membros, os períodos da organização e as
        respostas enviadas. O período de cada um é
        escolhido aqui, por `pick_period` (P-068), e não numa consulta por pessoa.
        """
        self._check_can_manage_members(
            organization_id, role=role, own_organization_id=own_organization_id
        )
        if not await self.organizations.organization_exists(organization_id):
            raise NotFoundError(f"Organização {organization_id} não encontrada")

        rows = await self.repository.list_members(organization_id, link_type)
        periods = await self.repository.list_organization_periods(organization_id)
        submitted = await self.repository.list_submitted(organization_id)
        now = datetime.now(UTC)

        members: list[MemberWithPeriod] = []
        for link, name, email, department in rows:
            picked = pick_period(periods, link.id, now)
            period: MemberPeriod | None = None
            if picked is not None:
                period = MemberPeriod(
                    form_id=picked.form.id,
                    opens_at=picked.opens_at,
                    closes_at=picked.closes_at,
                    period_status=picked.status,
                    has_answered=(picked.form.id, link.id) in submitted,
                )
            member = Member(link=link, name=name, email=email, department=department)
            members.append(MemberWithPeriod(member=member, period=period))
        return members

    def _check_can_manage_members(
        self, organization_id: uuid.UUID, *, role: str, own_organization_id: uuid.UUID
    ) -> None:
        """🟡 Premissa P-066: o `admin` mexe nos membros de qualquer organização;
        o `gestor`, só nos da organização do próprio vínculo; o `respondente`, em
        nenhuma. Confirmar na próxima reunião.
        """
        if role == Roles.ADMIN.value:
            return
        if role == Roles.GESTOR.value and organization_id == own_organization_id:
            return
        raise ForbiddenError("Sem acesso aos membros desta organização")
