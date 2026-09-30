"""Regra de negócio do domínio responses.

Esta camada não conhece HTTP nem detalhes de ORM. É onde ficam
as regras próprias das entidades FormResponse e Answer. Formulário é de
outro domínio: a pergunta "ele existe?" e a conferência de organização vão ao
`FormService` (CREED-47). Pergunta também: "existe?" e "é descritiva?" vão ao
`QuestionService`.
"""

import uuid
from datetime import UTC, datetime

from app.domains.forms.service import FormService
from app.domains.questions.service import QuestionService
from app.domains.responses.models import Answer, FormResponse, FormResponseStatus
from app.domains.responses.repository import AnswerRepository, FormResponseRepository
from app.domains.responses.schemas import AnswerCreate
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)


async def _own_form_response(
    repository: FormResponseRepository,
    form_response_id: uuid.UUID,
    *,
    link_id: uuid.UUID,
) -> FormResponse:
    """A resposta de formulário, se for do vínculo logado: 404 antes de 403.

    Enviar, gravar e ler respostas conferem o dono do mesmo jeito (P-031).
    """
    form_response = await repository.get_by_id(form_response_id)

    if form_response is None:
        raise NotFoundError(f"FormResponse {form_response_id} não encontrado")

    if form_response.vinculo_id != link_id:
        raise ForbiddenError(f"FormResponse {form_response_id} pertence a outro vínculo")

    return form_response


def _check_in_progress(form_response: FormResponse) -> None:
    if form_response.status is not FormResponseStatus.IN_PROGRESS:
        raise ConflictError(f"FormResponse {form_response.id} já foi submetido")


class FormResponseService:
    def __init__(
        self,
        repository: FormResponseRepository,
        forms: FormService,
        questions: QuestionService,
        answers: AnswerRepository,
    ) -> None:
        self.repository = repository
        self.forms = forms
        self.questions = questions
        self.answers = answers

    async def create_form_response(
        self,
        form_id: uuid.UUID,
        *,
        link_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> FormResponse:
        """`link_id` e `organization_id` são do vínculo de quem está logado.

        🟡 Premissa P-031 — qualquer papel responde, sempre com o próprio vínculo,
        e só formulário da própria organização (inclusive o `admin`).
        Confirmar na próxima reunião.

        🟡 Premissa P-030 — o status do formulário não é conferido: um formulário
        em `draft` pode ser respondido enquanto não houver transição de status.
        """
        # O formulário veio no corpo: inexistente é 422, não 404 (CREED-47, item 11).
        try:
            form = await self.forms.get(form_id)
        except NotFoundError as exc:
            raise ValidationError(exc.message) from exc

        self.forms.check_same_organization(
            form.organization_id, organization_id=organization_id
        )

        existing = await self.repository.get_by_form_and_vinculo(form_id, link_id)

        if existing is not None:
            raise ConflictError(
                f"Já existe uma resposta para o formulário {form_id} e vínculo {link_id}"
            )

        form_response = FormResponse(
            form_id=form_id,
            vinculo_id=link_id,
            status=FormResponseStatus.IN_PROGRESS,
        )

        return await self.repository.create(form_response)

    async def submit_form_response(
        self,
        form_response_id: uuid.UUID,
        *,
        link_id: uuid.UUID,
    ) -> FormResponse:
        """Só o dono envia, e só com as descritivas obrigatórias respondidas.

        Ordem: existe (404), é do dono (403), em andamento (409), obrigatórias
        (422). A obrigatória objetiva não conta até a CREED-37 (D2): ver
        `QuestionService.list_required_descriptive`.
        """
        form_response = await _own_form_response(
            self.repository, form_response_id, link_id=link_id
        )
        _check_in_progress(form_response)

        required = await self.questions.list_required_descriptive(form_response.form_id)
        answers = await self.answers.list_by_form_response(form_response_id)
        answered = {answer.question_id for answer in answers}
        missing = [question for question in required if question.id not in answered]

        if missing:
            listed = ", ".join(
                f"posição {question.order_index} ({question.id})" for question in missing
            )
            raise ValidationError(f"Perguntas obrigatórias sem resposta: {listed}")

        form_response.status = FormResponseStatus.SUBMITTED
        form_response.submitted_at = datetime.now(UTC)

        return form_response


class AnswerService:
    def __init__(
        self,
        answers: AnswerRepository,
        form_responses: FormResponseRepository,
        questions: QuestionService,
    ) -> None:
        self.answers = answers
        self.form_responses = form_responses
        self.questions = questions

    async def record(
        self, form_response_id: uuid.UUID, dados: AnswerCreate, *, link_id: uuid.UUID
    ) -> Answer:
        """Grava a resposta de uma pergunta descritiva, na ordem de conferência da
        spec: 404, 403, 409, 422 (pergunta), 422 (objetiva), 422 (texto), 409.

        Objetiva é recusada até as alternativas existirem (CREED-47, D2).

        🟡 Premissa P-032 — uma resposta por pergunta em cada resposta de
        formulário; gravar de novo é `ConflictError`, e não há edição. Confirmar na
        próxima reunião. Não há `unique` no banco para isso, de propósito (a
        objetiva talvez aceite várias alternativas): dois POST simultâneos na mesma
        pergunta passam os dois.
        """
        form_response = await _own_form_response(
            self.form_responses, form_response_id, link_id=link_id
        )
        _check_in_progress(form_response)

        # A pergunta veio no corpo: inexistente é 422, não 404 (CREED-47, item 11).
        try:
            question = await self.questions.get(dados.question_id)
        except NotFoundError as exc:
            raise ValidationError(exc.message) from exc

        if question.form_id != form_response.form_id:
            raise ValidationError(
                f"Pergunta {dados.question_id} não é do formulário desta resposta"
            )

        if not self.questions.is_descriptive(question):
            raise ValidationError(
                "Respostas a perguntas objetivas chegam com as alternativas (CREED-37)"
            )

        if dados.option_id is not None:
            raise ValidationError("Pergunta descritiva não aceita alternativa marcada")

        texto = dados.value.strip() if dados.value else ""
        if not texto:
            raise ValidationError("A resposta descritiva precisa de texto")

        already_answered = await self.answers.get_by_form_response_and_question(
            form_response_id, dados.question_id
        )
        if already_answered is not None:
            raise ConflictError(
                f"A pergunta {dados.question_id} já foi respondida nesta resposta"
            )

        answer = Answer(
            form_response_id=form_response_id,
            question_id=dados.question_id,
            value=texto,
        )

        return await self.answers.insert(answer)

    async def list_for_form_response(
        self, form_response_id: uuid.UUID, *, link_id: uuid.UUID
    ) -> list[Answer]:
        """Só o dono lê, em ordem de gravação. Serve também depois do envio."""
        await _own_form_response(self.form_responses, form_response_id, link_id=link_id)
        return await self.answers.list_by_form_response(form_response_id)

    async def get(self, answer_id: uuid.UUID) -> Answer:
        answer = await self.answers.get_by_id(answer_id)

        if answer is None:
            raise NotFoundError(f"Answer {answer_id} não encontrado")

        return answer
