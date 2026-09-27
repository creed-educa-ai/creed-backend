"""Regra de negócio do domínio forms

Esta camada não conhece HTTP nem detalhes de ORM. É onde a lógica vive,
isolada e testável.
"""

import uuid

from app.domains.forms.models import Form, FormStatus
from app.domains.forms.repository import FormRepository
from app.domains.forms.schemas import FormCreate
from app.shared.exceptions import NotFoundError


class FormService:
    def __init__(self, repository: FormRepository) -> None:
        self.repository = repository

    async def create(self, request: FormCreate) -> Form:
        form = Form(
            name=request.name,
            organization_id=request.organization_id,
            status=FormStatus.DRAFT,
        )
        return await self.repository.create(form)

    async def get(self, form_id: uuid.UUID) -> Form:
        form = await self.repository.get_by_id(form_id)

        if form is None:
            raise NotFoundError(f"Formulário {form_id} não encontrado")

        return form
