"""Regra de negocio do dominio questions (ADR-002, secao 2.2).

Esta camada nao conhece HTTP nem detalhes de ORM. A checagem de posicao
repetida acontece aqui, antes de gravar — mesmo padrao de
create_user_service checando e-mail antes de criar. A UniqueConstraint na
tabela fica so como rede de seguranca para gravacoes simultaneas.
"""

import uuid

from app.domains.questions.models import Question, QuestionSection
from app.domains.questions.repository import QuestionRepository
from app.domains.questions.schemas import QuestionCreate
from app.shared.exceptions import ConflictError


class QuestionService:
    def __init__(self, repository: QuestionRepository) -> None:
        self.repository = repository

    async def create(self, request: QuestionCreate) -> Question:
        already_exists = await self.repository.get_by_form_and_order(
            request.form_id, request.order_index
        )

        if already_exists is not None:
            raise ConflictError(
                f"Ja existe pergunta na posicao {request.order_index} "
                f"do formulario {request.form_id}"
            )

        question = Question(
            form_id=request.form_id,
            text=request.text,
            order_index=request.order_index,
            type=request.type,
            section=request.section,
            required=request.required,
            prisma=request.prisma,
        )
        return await self.repository.insert(question)

    async def list_for_form(
        self, form_id: uuid.UUID, section: QuestionSection | None = None
    ) -> list[Question]:
        return await self.repository.list_by_form(form_id, section)
