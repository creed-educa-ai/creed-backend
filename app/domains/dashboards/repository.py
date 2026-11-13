"""Acesso a dados do domínio de dashboards.

Esta camada NÃO contém regra de negócio: só queries e operações de persistência.

Domínio de leitura (ADR-0004, item 4): lê por join `form`, `form_responses`,
`answer`, `questions`, `question_options`, `links`, `departments` e
`organizations`, e só escreve na própria tabela `dashboards`.
"""

import uuid
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import ColumnElement, Integer, cast, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.dashboards.models import Dashboard
from app.domains.department.models import Department
from app.domains.forms.models import Form
from app.domains.links.models import Link
from app.domains.organizacoes.models import Organization, OrganizationStatus
from app.domains.participants.models import Participant
from app.domains.questions.models import Question, QuestionOption
from app.domains.responses.models import Answer, FormResponse, FormResponseStatus
from app.shared.enums import DepartmentType, Dimension, LinkType, Roles

# As alternativas da escala (P-040). Valor fora daqui não entra na média, e o
# filtro vem antes do CAST para um valor estranho não derrubar a consulta.
_LIKERT = ("1", "2", "3", "4", "5")


class InvitedLink(NamedTuple):
    """Um vínculo do público de um período, com o setor dele."""

    link_id: uuid.UUID
    department: DepartmentType | None


class DimensionAverage(NamedTuple):
    """A média de 1 a 5 de uma pessoa numa dimensão, num período."""

    form_id: uuid.UUID
    link_id: uuid.UUID
    department: DepartmentType | None
    dimension: Dimension
    average: float


class DashboardRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, dashboard_id: uuid.UUID) -> Dashboard | None:
        """Busca um dashboard pelo seu identificador."""
        result = await self.db.execute(
            select(Dashboard).where(Dashboard.id == dashboard_id)
        )
        return result.scalar_one_or_none()

    async def create(self, dashboard: Dashboard) -> Dashboard:
        """Cria um dashboard no banco."""
        self.db.add(dashboard)
        await self.db.flush()
        await self.db.refresh(dashboard)
        return dashboard

    async def delete_by_form_responses_or_user(
        self, form_response_ids: list[uuid.UUID], user_id: uuid.UUID | None
    ) -> None:
        """Apaga os dashboards destas respostas e os deste login, se houver.

        `form_id` aponta para `form_responses`, apesar do nome.
        """
        if not form_response_ids and user_id is None:
            return
        condition: ColumnElement[bool] = Dashboard.form_id.in_(form_response_ids)
        if user_id is not None:
            condition = or_(condition, Dashboard.user_id == user_id)
        await self.db.execute(delete(Dashboard).where(condition))

    async def get_organization_name(self, organization_id: uuid.UUID) -> str | None:
        """Busca o nome da organização."""
        result = await self.db.execute(
            select(Organization.name).where(Organization.id == organization_id)
        )
        return result.scalar_one_or_none()

    def _eligible_link_conditions(self, form: Form) -> list[ColumnElement[bool]]:
        """Condições de elegibilidade dos vínculos para o período do formulário.

        Alinha o público do formulário de modo consistente entre convidados e
        concluídos:
        - Mesma organização do formulário
        - Papel de respondente ou gestor: a gestora também responde o
          questionário da própria empresa, e a resposta dela conta. A admin não:
          o vínculo dela é o da CREED.
        - Se o formulário tiver público individual (form.link_id), apenas aquele vínculo
        - Se o formulário tiver data de fechamento (form.closes_at):
            - Vínculo não pode ter sido criado/iniciado após o fechamento
            - Vínculo não pode ter sido encerrado antes da abertura do período
        - Se o formulário não tiver data de fechamento:
            - Vínculo ativo no momento da consulta (end_at nulo ou futuro)
        """
        conditions: list[ColumnElement[bool]] = [
            Link.organization_id == form.organization_id,
            Link.role.in_((Roles.RESPONDENTE, Roles.GESTOR)),
        ]
        if form.link_id is not None:
            conditions.append(Link.id == form.link_id)

        if form.closes_at is not None:
            # Vínculos criados ou iniciados após o fechamento pertencem a ciclos futuros
            conditions.append(Link.created_at <= form.closes_at)
            conditions.append(Link.start_at <= form.closes_at)
            if form.opens_at is not None:
                conditions.append(
                    or_(Link.end_at.is_(None), Link.end_at >= form.opens_at)
                )
            else:
                conditions.append(
                    or_(Link.end_at.is_(None), Link.end_at >= form.closes_at)
                )
        else:
            conditions.append(or_(Link.end_at.is_(None), Link.end_at > func.now()))
            if form.opens_at is not None:
                conditions.append(
                    or_(Link.end_at.is_(None), Link.end_at >= form.opens_at)
                )

        return conditions

    async def list_answered_forms(self, link_id: uuid.UUID) -> list[Form]:
        """Os períodos em que o vínculo tem resposta enviada, do mais recente ao mais
        antigo. Formulário sem datas não é período e fica de fora."""
        result = await self.db.execute(
            select(Form)
            .join(FormResponse, FormResponse.form_id == Form.id)
            .where(
                FormResponse.vinculo_id == link_id,
                FormResponse.status == FormResponseStatus.SUBMITTED,
                Form.opens_at.is_not(None),
            )
            .order_by(Form.opens_at.desc())
        )
        return list(result.scalars().all())

    async def list_dimension_averages(
        self, form_ids: list[uuid.UUID], *, link_id: uuid.UUID | None = None
    ) -> list[DimensionAverage]:
        """Uma linha por resposta enviada e dimensão, com a média já feita no banco.

        Uma consulta para todos os períodos pedidos: o service recorta e compara
        em memória. Com `link_id`, só as respostas daquele vínculo.
        """
        if not form_ids:
            return []

        conditions = [
            FormResponse.form_id.in_(form_ids),
            FormResponse.status == FormResponseStatus.SUBMITTED,
            Question.dimensao.is_not(None),
            QuestionOption.value.in_(_LIKERT),
        ]
        if link_id is not None:
            conditions.append(FormResponse.vinculo_id == link_id)

        result = await self.db.execute(
            select(
                FormResponse.form_id,
                FormResponse.vinculo_id,
                Department.type,
                Question.dimensao,
                func.avg(cast(QuestionOption.value, Integer)),
            )
            .join(Link, Link.id == FormResponse.vinculo_id)
            .outerjoin(Department, Department.id == Link.department_id)
            .join(Answer, Answer.form_response_id == FormResponse.id)
            .join(QuestionOption, QuestionOption.id == Answer.option_id)
            .join(Question, Question.id == Answer.question_id)
            .where(*conditions)
            .group_by(
                FormResponse.form_id,
                FormResponse.vinculo_id,
                Department.type,
                Question.dimensao,
            )
        )
        return [
            DimensionAverage(form_id, link, department, dimension, float(average))
            for form_id, link, department, dimension, average in result.all()
        ]

    async def list_company_forms(
        self, organization_id: uuid.UUID, now: datetime
    ) -> list[Form]:
        """Os períodos "para todos" da organização que já abriram, do mais recente ao
        mais antigo. Agendado ainda não tem resultado; individual é de uma pessoa."""
        result = await self.db.execute(
            select(Form)
            .where(
                Form.organization_id == organization_id,
                Form.link_id.is_(None),
                Form.opens_at.is_not(None),
                Form.opens_at <= now,
            )
            .order_by(Form.opens_at.desc())
        )
        return list(result.scalars().all())

    async def list_invited_links(self, form: Form) -> list[InvitedLink]:
        """O público do período (`_eligible_link_conditions`), com o setor de cada um.

        É a mesma regra para os convidados e para quem entra nas médias: assim os
        concluídos nunca passam dos convidados.
        """
        result = await self.db.execute(
            select(Link.id, Department.type)
            .outerjoin(Department, Department.id == Link.department_id)
            .where(*self._eligible_link_conditions(form))
        )
        return [InvitedLink(link_id, department) for link_id, department in result.all()]

    async def list_departments(self, organization_id: uuid.UUID) -> list[DepartmentType]:
        """Os setores cadastrados na organização, na ordem do enum."""
        result = await self.db.execute(
            select(Department.type).where(Department.organization_id == organization_id)
        )
        cadastrados = set(result.scalars().all())
        return [tipo for tipo in DepartmentType if tipo in cadastrados]

    async def link_in_organization(
        self, link_id: uuid.UUID, organization_id: uuid.UUID
    ) -> bool:
        """Se o vínculo é desta organização."""
        result = await self.db.execute(
            select(Link.id).where(
                Link.id == link_id, Link.organization_id == organization_id
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_member_names(self, link_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        """O nome da pessoa de cada vínculo."""
        if not link_ids:
            return {}
        result = await self.db.execute(
            select(Link.id, Participant.name)
            .join(Participant, Participant.id == Link.participant_id)
            .where(Link.id.in_(link_ids))
        )
        return dict(result.tuples().all())

    async def list_companies(self, exclude_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
        """As empresas ativas, menos a da CREED (`exclude_id`), em ordem de nome."""
        result = await self.db.execute(
            select(Organization.id, Organization.name)
            .where(
                Organization.status == OrganizationStatus.ACTIVE,
                Organization.id != exclude_id,
            )
            .order_by(Organization.name)
        )
        return list(result.tuples().all())

    async def list_opened_forms(
        self, organization_ids: list[uuid.UUID], now: datetime
    ) -> list[Form]:
        """Todos os períodos destas organizações que já abriram: os "para todos" e
        os individuais. É o que o retrato atual percorre."""
        if not organization_ids:
            return []
        result = await self.db.execute(
            select(Form).where(
                Form.organization_id.in_(organization_ids),
                Form.opens_at.is_not(None),
                Form.opens_at <= now,
            )
        )
        return list(result.scalars().all())

    async def list_link_ids(
        self, organization_id: uuid.UUID, link_type: LinkType
    ) -> list[uuid.UUID]:
        """Os vínculos de um tipo na organização (os mentorandos, na da CREED)."""
        result = await self.db.execute(
            select(Link.id).where(
                Link.organization_id == organization_id, Link.type == link_type
            )
        )
        return list(result.scalars().all())
