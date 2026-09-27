"""Regra de negócio do domínio responses.

Esta camada não conhece HTTP nem detalhes de ORM. É onde ficam
as regras próprias das entidades FormResponse e Answer.
"""

import uuid
from datetime import UTC, datetime

from app.domains.responses.models import Answer, FormResponse, FormResponseStatus
from app.domains.responses.repository import AnswerRepository, FormResponseRepository
from app.domains.responses.schemas import AnswerCreate
from app.shared.exceptions import ConflictError, NotFoundError, ValidationError


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


class AnswerService:
    def __init__(self, repository: AnswerRepository) -> None:
        self.repository = repository

    async def record(self, dados: AnswerCreate) -> Answer:
        """Uma resposta válida tem uma das duas formas preenchida: a
        alternativa marcada, se a pergunta era objetiva, ou o texto
        escrito, se era descritiva."""
        texto = dados.value.strip() if dados.value else ""

        tem_opcao = dados.option_id is not None
        tem_texto = bool(texto)

        if tem_opcao == tem_texto:
            raise ValidationError(
                "A resposta precisa ter exatamente uma forma preenchida: "
                "a alternativa marcada ou o texto escrito"
            )

        answer = Answer(
            question_id=dados.question_id,
            option_id=dados.option_id,
            value=texto or None,
        )

        return await self.repository.insert(answer)

    async def get(self, answer_id: uuid.UUID) -> Answer:
        answer = await self.repository.get_by_id(answer_id)

        if answer is None:
            raise NotFoundError(f"Answer {answer_id} não encontrado")

        return answer
