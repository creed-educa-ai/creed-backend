"""Testes do service do domínio responses.

Sem banco e sem HTTP: o repository é substituído por um dublê em memória
(ADR-002). O que se prova aqui é a regra de negócio, não o mapeamento SQL.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.domains.responses.models import Answer, FormResponse, FormResponseStatus
from app.domains.responses.schemas import AnswerCreate
from app.domains.responses.service import AnswerService, FormResponseService
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)

ORG_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
ORG_B = uuid.UUID("00000000-0000-0000-0000-00000000000b")


class FakeFormResponseRepository:
    """Dublê do repository: guarda em lista, não decide nada."""

    def __init__(self, existentes: list[FormResponse] | None = None) -> None:
        self.itens: list[FormResponse] = list(existentes or [])

    async def get_by_id(self, form_response_id: uuid.UUID) -> FormResponse | None:
        return next((fr for fr in self.itens if fr.id == form_response_id), None)

    async def get_by_form_and_vinculo(
        self,
        form_id: uuid.UUID,
        vinculo_id: uuid.UUID,
    ) -> FormResponse | None:
        return next(
            (
                fr
                for fr in self.itens
                if fr.form_id == form_id and fr.vinculo_id == vinculo_id
            ),
            None,
        )

    async def create(self, form_response: FormResponse) -> FormResponse:
        self.itens.append(form_response)
        return form_response


def um_form_response(**campos: object) -> FormResponse:
    """FormResponse montado à mão.

    Todo campo vai explícito: `default` e `server_default` só são aplicados
    no INSERT, então um FormResponse que nunca passou pela sessão tem `None`
    neles.
    """
    padrao: dict[str, object] = {
        "id": uuid.uuid4(),
        "form_id": uuid.uuid4(),
        "vinculo_id": uuid.uuid4(),
        "status": FormResponseStatus.IN_PROGRESS,
        "started_at": datetime(2026, 9, 19, tzinfo=UTC),
        "submitted_at": None,
    }
    return FormResponse(**{**padrao, **campos})


class FakeFormService:
    """Dublê do `FormService`: formulários conhecidos, cada um da sua organização.

    Formulário fora de `formularios` levanta `NotFoundError`, como o service real
    faz para um id que não está no banco. Só existe `check_same_organization`: se
    o service chamasse a `check_organization`, que libera o `admin`, o teste
    quebraria. A regra em si é provada em tests/domains/forms.
    """

    def __init__(self, formularios: dict[uuid.UUID, uuid.UUID] | None = None) -> None:
        self.formularios = formularios or {}

    async def get(self, form_id: uuid.UUID) -> SimpleNamespace:
        if form_id not in self.formularios:
            raise NotFoundError(f"Formulário {form_id} não encontrado")
        return SimpleNamespace(id=form_id, organization_id=self.formularios[form_id])

    def check_same_organization(
        self, form_organization_id: uuid.UUID, *, organization_id: uuid.UUID
    ) -> None:
        if form_organization_id != organization_id:
            raise ForbiddenError("Sem acesso a formulário de outra organização")


def servico(
    repository: FakeFormResponseRepository, forms: FakeFormService | None = None
) -> FormResponseService:
    return FormResponseService(
        repository,  # type: ignore[arg-type]
        forms or FakeFormService(),  # type: ignore[arg-type]
    )


class TestSubmitFormResponse:
    async def test_marca_como_submitted_e_registra_data(self) -> None:
        form_response = um_form_response()
        repository = FakeFormResponseRepository([form_response])

        antes = datetime.now(UTC)
        resultado = await servico(repository).submit_form_response(
            form_response.id, link_id=form_response.vinculo_id
        )
        depois = datetime.now(UTC)

        assert resultado.status == FormResponseStatus.SUBMITTED
        assert resultado.submitted_at is not None
        assert antes <= resultado.submitted_at <= depois

    async def test_inexistente_vira_not_found(self) -> None:
        repository = FakeFormResponseRepository()

        with pytest.raises(NotFoundError):
            await servico(repository).submit_form_response(
                uuid.uuid4(), link_id=uuid.uuid4()
            )

    async def test_de_outro_vinculo_vira_forbidden_sem_submeter(self) -> None:
        form_response = um_form_response()
        repository = FakeFormResponseRepository([form_response])

        with pytest.raises(ForbiddenError):
            await servico(repository).submit_form_response(
                form_response.id, link_id=uuid.uuid4()
            )

        assert form_response.status is FormResponseStatus.IN_PROGRESS
        assert form_response.submitted_at is None

    async def test_de_outro_vinculo_ja_submetida_vira_forbidden_antes_do_conflito(
        self,
    ) -> None:
        """403 antes de 409: quem não é dono não descobre o estado da resposta."""
        form_response = um_form_response(status=FormResponseStatus.SUBMITTED)
        repository = FakeFormResponseRepository([form_response])

        with pytest.raises(ForbiddenError):
            await servico(repository).submit_form_response(
                form_response.id, link_id=uuid.uuid4()
            )

    async def test_do_dono_ja_submetida_vira_conflict(self) -> None:
        form_response = um_form_response(status=FormResponseStatus.SUBMITTED)
        repository = FakeFormResponseRepository([form_response])

        with pytest.raises(ConflictError):
            await servico(repository).submit_form_response(
                form_response.id, link_id=form_response.vinculo_id
            )


class TestCreateFormResponse:
    async def test_nasce_em_progresso_com_o_vinculo_do_login(self) -> None:
        repository = FakeFormResponseRepository()
        form_id, link_id = uuid.uuid4(), uuid.uuid4()
        forms = FakeFormService({form_id: ORG_A})

        resultado = await servico(repository, forms).create_form_response(
            form_id, link_id=link_id, organization_id=ORG_A
        )

        assert resultado.form_id == form_id
        assert resultado.vinculo_id == link_id
        assert resultado.status == FormResponseStatus.IN_PROGRESS
        assert resultado.submitted_at is None

    async def test_formulario_inexistente_vira_validation_error_sem_gravar(
        self,
    ) -> None:
        """O formulário veio no corpo: inexistente é 422, não 404 (CREED-47)."""
        repository = FakeFormResponseRepository()
        form_id = uuid.uuid4()

        with pytest.raises(ValidationError, match=str(form_id)):
            await servico(repository).create_form_response(
                form_id, link_id=uuid.uuid4(), organization_id=ORG_A
            )

        assert repository.itens == []

    async def test_formulario_de_outra_organizacao_vira_forbidden_sem_gravar(
        self,
    ) -> None:
        """Vale para qualquer papel: o service nem recebe o papel (P-031)."""
        repository = FakeFormResponseRepository()
        form_id = uuid.uuid4()
        forms = FakeFormService({form_id: ORG_B})

        with pytest.raises(ForbiddenError):
            await servico(repository, forms).create_form_response(
                form_id, link_id=uuid.uuid4(), organization_id=ORG_A
            )

        assert repository.itens == []

    async def test_segunda_resposta_do_mesmo_vinculo_vira_conflict(self) -> None:
        form_id, link_id = uuid.uuid4(), uuid.uuid4()
        repository = FakeFormResponseRepository(
            [um_form_response(form_id=form_id, vinculo_id=link_id)]
        )
        forms = FakeFormService({form_id: ORG_A})

        with pytest.raises(ConflictError):
            await servico(repository, forms).create_form_response(
                form_id, link_id=link_id, organization_id=ORG_A
            )


class FakeAnswerRepository:
    """Dublê do repository: guarda em lista, não decide nada, não toca no banco."""

    def __init__(self, existentes: list[Answer] | None = None) -> None:
        self.itens: list[Answer] = list(existentes or [])

    async def get_by_id(self, answer_id: uuid.UUID) -> Answer | None:
        return next((a for a in self.itens if a.id == answer_id), None)

    async def get_by_form_response_and_question(
        self, form_response_id: uuid.UUID, question_id: uuid.UUID
    ) -> Answer | None:
        return next(
            (
                a
                for a in self.itens
                if a.form_response_id == form_response_id and a.question_id == question_id
            ),
            None,
        )

    async def list_by_form_response(self, form_response_id: uuid.UUID) -> list[Answer]:
        """Filtra na ordem da lista: a ordenação real (`created_at`) é do banco."""
        return [a for a in self.itens if a.form_response_id == form_response_id]

    async def insert(self, answer: Answer) -> Answer:
        """O id e o created_at seriam preenchidos pelo banco."""
        answer.id = uuid.uuid4()
        answer.created_at = datetime.now(UTC)
        self.itens.append(answer)
        return answer


def uma_pergunta(form_id: uuid.UUID, *, descritiva: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), form_id=form_id, descritiva=descritiva)


class FakeQuestionService:
    """Dublê do `QuestionService`: "existe?" e "é descritiva?", sem regra própria."""

    def __init__(self, perguntas: list[SimpleNamespace]) -> None:
        self.perguntas = {p.id: p for p in perguntas}

    async def get(self, question_id: uuid.UUID) -> SimpleNamespace:
        if question_id not in self.perguntas:
            raise NotFoundError(f"Pergunta {question_id} não encontrada")
        return self.perguntas[question_id]

    def is_descriptive(self, question: SimpleNamespace) -> bool:
        return bool(question.descritiva)


class Cenario:
    """Uma resposta de formulário em andamento do vínculo `link_id`, com uma
    pergunta descritiva e uma objetiva do mesmo formulário, e uma descritiva de
    outro formulário."""

    def __init__(self, **campos_da_resposta: object) -> None:
        self.link_id = uuid.uuid4()
        self.form_response = um_form_response(
            vinculo_id=self.link_id, **campos_da_resposta
        )
        self.descritiva = uma_pergunta(self.form_response.form_id)
        self.objetiva = uma_pergunta(self.form_response.form_id, descritiva=False)
        self.de_outro_formulario = uma_pergunta(uuid.uuid4())
        self.answers = FakeAnswerRepository()
        questions = FakeQuestionService(
            [self.descritiva, self.objetiva, self.de_outro_formulario]
        )
        self.service = AnswerService(
            self.answers,  # type: ignore[arg-type]
            FakeFormResponseRepository([self.form_response]),  # type: ignore[arg-type]
            questions,  # type: ignore[arg-type]
        )

    async def gravar(
        self,
        dados: AnswerCreate,
        *,
        form_response_id: uuid.UUID | None = None,
        link_id: uuid.UUID | None = None,
    ) -> Answer:
        return await self.service.record(
            form_response_id or self.form_response.id,
            dados,
            link_id=link_id or self.link_id,
        )


class TestRecordAnswer:
    """Um teste por conferência, na ordem da spec: 404, 403, 409, 422 x 4, 409."""

    async def test_grava_o_texto_da_descritiva_na_resposta_de_formulario(self) -> None:
        cenario = Cenario()

        resultado = await cenario.gravar(
            AnswerCreate(question_id=cenario.descritiva.id, value="  minha resposta  ")
        )

        assert resultado.form_response_id == cenario.form_response.id
        assert resultado.question_id == cenario.descritiva.id
        assert resultado.value == "minha resposta"
        assert resultado.option_id is None
        assert cenario.answers.itens == [resultado]

    async def test_resposta_de_formulario_inexistente_vira_not_found(self) -> None:
        cenario = Cenario()

        with pytest.raises(NotFoundError):
            await cenario.gravar(
                AnswerCreate(question_id=cenario.descritiva.id, value="texto"),
                form_response_id=uuid.uuid4(),
            )

    async def test_de_outro_vinculo_vira_forbidden_sem_gravar(self) -> None:
        cenario = Cenario()

        with pytest.raises(ForbiddenError):
            await cenario.gravar(
                AnswerCreate(question_id=cenario.descritiva.id, value="texto"),
                link_id=uuid.uuid4(),
            )

        assert cenario.answers.itens == []

    async def test_resposta_ja_submetida_vira_conflict(self) -> None:
        cenario = Cenario(status=FormResponseStatus.SUBMITTED)

        with pytest.raises(ConflictError, match="já foi submetido"):
            await cenario.gravar(
                AnswerCreate(question_id=cenario.descritiva.id, value="texto")
            )

    async def test_pergunta_inexistente_vira_validation_error(self) -> None:
        cenario = Cenario()
        question_id = uuid.uuid4()

        with pytest.raises(ValidationError, match=str(question_id)):
            await cenario.gravar(AnswerCreate(question_id=question_id, value="texto"))

    async def test_pergunta_de_outro_formulario_vira_validation_error(self) -> None:
        cenario = Cenario()

        with pytest.raises(ValidationError, match="não é do formulário"):
            await cenario.gravar(
                AnswerCreate(question_id=cenario.de_outro_formulario.id, value="texto")
            )

        assert cenario.answers.itens == []

    async def test_pergunta_objetiva_vira_validation_error(self) -> None:
        """D2: objetiva só com as alternativas da CREED-37."""
        cenario = Cenario()

        with pytest.raises(ValidationError, match="CREED-37"):
            await cenario.gravar(
                AnswerCreate(question_id=cenario.objetiva.id, option_id=uuid.uuid4())
            )

        assert cenario.answers.itens == []

    async def test_alternativa_marcada_na_descritiva_vira_validation_error(
        self,
    ) -> None:
        """Mesmo sem texto: `option_id` sozinho numa descritiva é recusado."""
        cenario = Cenario()

        with pytest.raises(ValidationError, match="alternativa"):
            await cenario.gravar(
                AnswerCreate(question_id=cenario.descritiva.id, option_id=uuid.uuid4())
            )

    @pytest.mark.parametrize("value", [None, "", "   "])
    async def test_sem_texto_vira_validation_error(self, value: str | None) -> None:
        cenario = Cenario()

        with pytest.raises(ValidationError, match="precisa de texto"):
            await cenario.gravar(
                AnswerCreate(question_id=cenario.descritiva.id, value=value)
            )

    async def test_pergunta_ja_respondida_vira_conflict_sem_gravar_de_novo(
        self,
    ) -> None:
        """P-032: uma resposta por pergunta, sem edição."""
        cenario = Cenario()
        primeira = await cenario.gravar(
            AnswerCreate(question_id=cenario.descritiva.id, value="primeira")
        )

        with pytest.raises(ConflictError, match="já foi respondida"):
            await cenario.gravar(
                AnswerCreate(question_id=cenario.descritiva.id, value="segunda")
            )

        assert cenario.answers.itens == [primeira]


class TestListarAnswers:
    async def test_devolve_as_respostas_da_resposta_de_formulario(self) -> None:
        cenario = Cenario()
        gravada = await cenario.gravar(
            AnswerCreate(question_id=cenario.descritiva.id, value="texto")
        )

        resultado = await cenario.service.list_for_form_response(
            cenario.form_response.id, link_id=cenario.link_id
        )

        assert resultado == [gravada]

    async def test_depois_do_envio_o_dono_ainda_le(self) -> None:
        cenario = Cenario(status=FormResponseStatus.SUBMITTED)

        resultado = await cenario.service.list_for_form_response(
            cenario.form_response.id, link_id=cenario.link_id
        )

        assert resultado == []

    async def test_de_outro_vinculo_vira_forbidden(self) -> None:
        cenario = Cenario()

        with pytest.raises(ForbiddenError):
            await cenario.service.list_for_form_response(
                cenario.form_response.id, link_id=uuid.uuid4()
            )

    async def test_resposta_de_formulario_inexistente_vira_not_found(self) -> None:
        cenario = Cenario()

        with pytest.raises(NotFoundError):
            await cenario.service.list_for_form_response(
                uuid.uuid4(), link_id=cenario.link_id
            )


class TestGetAnswer:
    async def test_inexistente_vira_not_found(self) -> None:
        """Quando a busca volta vazia, é a camada de regra que recusa."""
        with pytest.raises(NotFoundError):
            await Cenario().service.get(uuid.uuid4())

    async def test_repository_devolve_none_sem_levantar(self) -> None:
        """A camada de banco não decide: devolve nada e deixa a regra decidir."""
        repository = FakeAnswerRepository()

        assert await repository.get_by_id(uuid.uuid4()) is None
