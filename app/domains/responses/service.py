"""Regra de negócio do domínio responses.

Esta camada não conhece HTTP nem detalhes de ORM. É onde ficam
as regras próprias da entidade FormResponse.
"""

import uuid
from datetime import UTC, datetime

from app.domains.responses.models import (
    FormResponse,
    FormResponseStatus,
)
from app.domains.responses.repository import FormResponseRepository
from app.shared.exceptions import ConflictError, NotFoundError


class FormResponseService:
    def __init__(self, repository: FormResponseRepository) -> None:
        self.repository = repository

    async def create_form_response(
        self,
        form_id: uuid.UUID,
        vinculo_id: uuid.UUID,
    ) -> FormResponse:
        existing = await self.repository.get_by_form_and_vinculo(
            form_id,
            vinculo_id,
        )

        if existing is not None:
            raise ConflictError(
                f"Já existe uma resposta para o formulário {form_id} "
                f"e vínculo {vinculo_id}"
            )

        form_response = FormResponse(
            form_id=form_id,
            vinculo_id=vinculo_id,
            status=FormResponseStatus.IN_PROGRESS,
        )

        return await self.repository.create(form_response)

    async def submit_form_response(
        self,
        form_response_id: uuid.UUID,
    ) -> FormResponse:
        form_response = await self.repository.get_by_id(form_response_id)

        if form_response is None:
            raise NotFoundError(f"FormResponse {form_response_id} não encontrado")

        if form_response.status is not FormResponseStatus.IN_PROGRESS:
            raise ConflictError(f"FormResponse {form_response_id} já foi submetido")

        form_response.status = FormResponseStatus.SUBMITTED
        form_response.submitted_at = datetime.now(UTC)

        return form_response
