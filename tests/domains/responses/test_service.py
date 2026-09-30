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
    """Dublê do repository: não decide nada, não toca no banco."""

    def __init__(self, existente: Answer | None = None) -> None:
        self.existente = existente

    async def get_by_id(self, answer_id: uuid.UUID) -> Answer | None:
        if self.existente is not None and self.existente.id == answer_id:
            return self.existente
        return None

    async def insert(self, answer: Answer) -> Answer:
        """O id e o created_at seriam preenchidos pelo banco."""
        answer.id = uuid.uuid4()
        answer.created_at = datetime.now(UTC)
        return answer


def servico_answer(repository: FakeAnswerRepository) -> AnswerService:
    return AnswerService(repository)  # type: ignore[arg-type]


class TestRecordAnswer:
    async def test_aceita_resposta_objetiva(self) -> None:
        """Pergunta objetiva responde marcando alternativa, sem texto."""
        dados = AnswerCreate(question_id=uuid.uuid4(), option_id=uuid.uuid4())

        resultado = await servico_answer(FakeAnswerRepository()).record(dados)

        assert resultado.option_id == dados.option_id
        assert resultado.value is None
        assert resultado.id is not None
        assert resultado.created_at is not None

    async def test_aceita_resposta_descritiva(self) -> None:
        """Pergunta descritiva responde com texto, sem alternativa."""
        dados = AnswerCreate(question_id=uuid.uuid4(), value="minha resposta")

        resultado = await servico_answer(FakeAnswerRepository()).record(dados)

        assert resultado.value == "minha resposta"
        assert resultado.option_id is None
        assert resultado.id is not None
        assert resultado.created_at is not None

    async def test_as_duas_formas_vazias_vira_validation_error(self) -> None:
        """Linha sem alternativa e sem texto é registro sem significado."""
        dados = AnswerCreate(question_id=uuid.uuid4())

        with pytest.raises(ValidationError):
            await servico_answer(FakeAnswerRepository()).record(dados)

    async def test_texto_so_com_espaco_vira_validation_error(self) -> None:
        """Texto em branco não é resposta descritiva."""
        dados = AnswerCreate(question_id=uuid.uuid4(), value="   ")

        with pytest.raises(ValidationError):
            await servico_answer(FakeAnswerRepository()).record(dados)

    async def test_as_duas_formas_preenchidas_vira_validation_error(self) -> None:
        """Uma resposta é objetiva ou descritiva, nunca as duas."""
        dados = AnswerCreate(
            question_id=uuid.uuid4(),
            option_id=uuid.uuid4(),
            value="texto",
        )

        with pytest.raises(ValidationError):
            await servico_answer(FakeAnswerRepository()).record(dados)


class TestGetAnswer:
    async def test_inexistente_vira_not_found(self) -> None:
        """Quando a busca volta vazia, é a camada de regra que recusa."""
        with pytest.raises(NotFoundError):
            await servico_answer(FakeAnswerRepository()).get(uuid.uuid4())

    async def test_repository_devolve_none_sem_levantar(self) -> None:
        """A camada de banco não decide: devolve nada e deixa a regra decidir."""
        repository = FakeAnswerRepository()

        assert await repository.get_by_id(uuid.uuid4()) is None
