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

Formulario e de outro dominio: a pergunta "ele existe?" vai ao `FormService`,
nunca ao model de `forms` (CREED-47). A regra de organizacao (P-033) tambem mora
la: aqui se pede a conferencia, sem repetir a comparacao.
"""

import uuid

from app.domains.forms.service import FormService
from app.domains.questions.models import Question, QuestionSection, QuestionType
from app.domains.questions.repository import QuestionRepository
from app.domains.questions.schemas import QuestionCreate
from app.shared.exceptions import ConflictError, NotFoundError, ValidationError


class QuestionService:
    def __init__(self, repository: QuestionRepository, forms: FormService) -> None:
        self.repository = repository
        self.forms = forms

    async def create(
        self, request: QuestionCreate, *, role: str, organization_id: uuid.UUID
    ) -> Question:
        """`role` e `organization_id` sao de quem pede, nao do formulario."""
        # O formulario veio no corpo: inexistente e 422, nao 404 (CREED-47, item 11).
        try:
            form = await self.forms.get(request.form_id)
        except NotFoundError as exc:
            raise ValidationError(exc.message) from exc

        self.forms.check_organization(
            form.organization_id, role=role, organization_id=organization_id
        )

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
        self,
        form_id: uuid.UUID,
        section: QuestionSection | None = None,
        *,
        role: str,
        organization_id: uuid.UUID,
    ) -> list[Question]:
        """Formulario inexistente levanta `NotFoundError` (404 no router), e de
        outra organizacao, `ForbiddenError` (403).

        Sem a primeira conferencia, "formulario inexistente" e "formulario ainda
        sem perguntas" devolviam o mesmo 200 com lista vazia.
        """
        await self.forms.get_for_user(form_id, role=role, organization_id=organization_id)
        return await self.repository.list_by_form(form_id, section)

    async def get(self, question_id: uuid.UUID) -> Question:
        """So "existe?", sem regra de acesso: e o que `responses` usa."""
        question = await self.repository.get_by_id(question_id)

        if question is None:
            raise NotFoundError(f"Pergunta {question_id} não encontrada")

        return question

    def is_descriptive(self, question: Question) -> bool:
        """Responde por `responses`, que nao pode importar `QuestionType`."""
        return question.type is QuestionType.DESCRIPTIVE

    def _conflito_de_posicao(self, request: QuestionCreate) -> ConflictError:
        return ConflictError(
            f"Já existe pergunta na posição {request.order_index} "
            f"do formulário {request.form_id}"
        )
