"""Regra de negócio do domínio form_responses.

Esta camada não conhece HTTP nem detalhes de ORM. É onde ficam
as regras próprias da entidade FormResponse.
"""

import uuid
from datetime import UTC, datetime

from app.domains.respostas.models import (
    FormResponse,
    FormResponseStatus,
)
from app.domains.respostas.repository import FormResponseRepository
from app.shared.exceptions import NotFoundError


class FormResponseService:
    def __init__(self, repository: FormResponseRepository) -> None:
        self.repository = repository

    async def create_form_response(
        self,
        form_id: uuid.UUID,
        vinculo_id: uuid.UUID,
    ) -> FormResponse:
        form_response = FormResponse(
            form_id=form_id,
            vinculo_id=vinculo_id,
            status=FormResponseStatus.IN_PROGRESS,
        )

        return await self.repository.create(form_response)

    async def submit_form_response(self, form_response_id: uuid.UUID) -> FormResponse:
        form_response = await self.repository.get_by_id(form_response_id)
        if form_response is None:
            raise NotFoundError(f"FormResponse {form_response_id} não encontrado")

        form_response.status = FormResponseStatus.SUBMITTED
        form_response.submitted_at = datetime.now(UTC)

        return form_response
