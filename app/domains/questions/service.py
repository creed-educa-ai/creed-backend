"""Regra de negocio do dominio questions (ADR-002, secao 2.2).

Esta camada nao conhece HTTP nem detalhes de ORM. A checagem de posicao
repetida acontece aqui, antes de gravar — mesmo padrao de
create_user_service checando e-mail antes de criar. Ela cobre o caso comum
sem round-trip extra de erro, mas nao fecha a corrida sozinha.

Quem fecha a corrida e a UniqueConstraint do banco: dois POSTs simultaneos
na mesma posicao podem os dois passarem pela checagem, e o segundo tem o
insert recusado. `repository.insert` devolve `None` nesse caso (nao pode
levantar erro de negocio — test_arquitetura.py o proibe), e e este service
que traduz `None` em ConflictError.
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
            raise self._conflito_de_posicao(request)

        question = Question(
            form_id=request.form_id,
            text=request.text,
            order_index=request.order_index,
            type=request.type,
            section=request.section,
            required=request.required,
            prisma=request.prisma,
        )
        created = await self.repository.insert(question)
        if created is None:
            raise self._conflito_de_posicao(request)
        return created

    async def list_for_form(
        self, form_id: uuid.UUID, section: QuestionSection | None = None
    ) -> list[Question]:
        return await self.repository.list_by_form(form_id, section)

    def _conflito_de_posicao(self, request: QuestionCreate) -> ConflictError:
        return ConflictError(
            f"Já existe pergunta na posição {request.order_index} "
            f"do formulário {request.form_id}"
        )
