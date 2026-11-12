"""Regra de negócio do domínio dashboards.

Esta camada não conhece HTTP nem detalhes de ORM.
"""

import uuid

from app.domains.dashboards.models import Dashboard
from app.domains.dashboards.repository import DashboardRepository
from app.domains.dashboards.schemas import DashboardCreate
from app.shared.exceptions import NotFoundError


class DashboardService:
    def __init__(self, repository: DashboardRepository) -> None:
        self.repository = repository

    async def create(self, request: DashboardCreate) -> Dashboard:
        """Cria um novo dashboard."""
        dashboard = Dashboard(
            user_id=request.user_id,
            form_id=request.form_id,
            is_private=request.is_private,
        )
        return await self.repository.create(dashboard)

    async def get(self, dashboard_id: uuid.UUID) -> Dashboard:
        """Busca um dashboard pelo identificador."""
        dashboard = await self.repository.get_by_id(dashboard_id)

        if dashboard is None:
            raise NotFoundError(f"Dashboard {dashboard_id} não encontrado")

        return dashboard

    async def delete_for_member_removal(
        self, form_response_ids: list[uuid.UUID], user_id: uuid.UUID | None
    ) -> None:
        """Apaga os dashboards que impediriam a exclusão de membro (M-3).

        Os das respostas que saem e os do login que sai: as duas colunas são chave
        estrangeira, e o banco recusaria apagar a resposta ou o login primeiro.
        """
        await self.repository.delete_by_form_responses_or_user(form_response_ids, user_id)
