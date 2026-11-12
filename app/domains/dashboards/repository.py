"""Acesso a dados do domínio de dashboards.

Esta camada NÃO contém regra de negócio: só queries e operações de persistência.
"""

import uuid

from sqlalchemy import ColumnElement, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.dashboards.models import Dashboard
from app.domains.forms.models import Form
from app.domains.links.models import Link
from app.domains.organizacoes.models import Organization
from app.domains.responses.models import FormResponse, FormResponseStatus


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

    async def get_form(self, form_id: uuid.UUID) -> Form | None:
        """Busca o formulário por ID."""
        result = await self.db.execute(select(Form).where(Form.id == form_id))
        return result.scalar_one_or_none()

    async def get_organization_name(self, organization_id: uuid.UUID) -> str | None:
        """Busca o nome da organização."""
        result = await self.db.execute(
            select(Organization.name).where(Organization.id == organization_id)
        )
        return result.scalar_one_or_none()

    async def count_organization_members(self, organization_id: uuid.UUID) -> int:
        """Conta o total de membros vinculados à organização."""
        result = await self.db.execute(
            select(func.count(Link.id)).where(Link.organization_id == organization_id)
        )
        return result.scalar() or 0

    async def get_submitted_form_response_ids(
        self, form_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """Busca todos os IDs de FormResponse finalizados para um formulário."""
        result = await self.db.execute(
            select(FormResponse.id).where(
                FormResponse.form_id == form_id,
                FormResponse.status == FormResponseStatus.SUBMITTED,
            )
        )
        return list(result.scalars().all())
