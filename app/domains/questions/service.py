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
from app.domains.questions.models import (
    Question,
    QuestionOption,
    QuestionSection,
    QuestionType,
)
from app.domains.questions.repository import (
    QuestionOptionRepository,
    QuestionRepository,
)
from app.domains.questions.schemas import QuestionCreate, QuestionOptionCreate
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
            dimensao=request.dimensao,
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

    async def list_required(self, form_id: uuid.UUID) -> list[Question]:
        """As perguntas que o envio de uma resposta exige, em ordem de posicao.

        Descritivas e objetivas: com as alternativas da CREED-37, a objetiva pode
        ser respondida, e a obrigatoria passa a contar (fecha o D2 da CREED-47).
        """
        return await self.repository.list_required(form_id)

    def is_descriptive(self, question: Question) -> bool:
        """Responde por `responses`, que nao pode importar `QuestionType`."""
        return question.type is QuestionType.DESCRIPTIVE

    def _conflito_de_posicao(self, request: QuestionCreate) -> ConflictError:
        return ConflictError(
            f"Já existe pergunta na posição {request.order_index} "
            f"do formulário {request.form_id}"
        )


class QuestionOptionService:
    def __init__(
        self,
        repository: QuestionOptionRepository,
        questions: QuestionService,
        forms: FormService,
    ) -> None:
        self.repository = repository
        self.questions = questions
        self.forms = forms

    async def create(
        self,
        question_id: uuid.UUID,
        request: QuestionOptionCreate,
        *,
        role: str,
        organization_id: uuid.UUID,
    ) -> QuestionOption:
        """Cadastra uma alternativa numa pergunta objetiva.

        Pergunta inexistente levanta `NotFoundError`, e de formulário de outra
        organização, `ForbiddenError`. `role` e `organization_id` são de quem pede.

        Premissa: alternativa só faz sentido em pergunta objetiva; a descritiva é
        recusada.
        """
        question = await self.questions.get(question_id)

        await self.forms.get_for_user(
            question.form_id, role=role, organization_id=organization_id
        )

        if self.questions.is_descriptive(question):
            raise ValidationError(
                f"Pergunta {question_id} é descritiva e não aceita alternativas"
            )

        already_exists = await self.repository.get_by_question_and_order(
            question_id, request.order_index
        )

        if already_exists is not None:
            raise self._position_conflict(question_id, request)

        option = QuestionOption(
            question_id=question_id,
            label=request.label,
            value=request.value,
            order_index=request.order_index,
        )
        created = await self.repository.insert(option)
        if created is None:
            raise self._position_conflict(question_id, request)
        return created

    async def get(self, option_id: uuid.UUID) -> QuestionOption:
        """Só "existe?", sem regra de acesso: é o que `responses` usa para
        conferir a alternativa marcada numa resposta objetiva."""
        option = await self.repository.get_by_id(option_id)

        if option is None:
            raise NotFoundError(f"Alternativa {option_id} não encontrada")

        return option

    def _position_conflict(
        self, question_id: uuid.UUID, request: QuestionOptionCreate
    ) -> ConflictError:
        return ConflictError(
            f"Já existe alternativa na posição {request.order_index} "
            f"da pergunta {question_id}"
        )
