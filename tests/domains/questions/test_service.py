"""Testes do service do dominio questions.

Sem banco e sem HTTP: o repository e o `FormService` sao substituidos por
dubles em memoria. O que se prova aqui e a regra de negocio — o formulario
precisa existir, conflito de posicao repetida e que a secao pedida chega ate
a camada de banco.

⚠️ Este teste NAO prova ordenacao nem filtro por secao de verdade: o duble
filtra em memoria, sem rodar consulta nenhuma. Ordenacao e filtro reais sao
provados pela CREED-353, de ponta a ponta, com banco.
"""

import re
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.domains.questions.models import Question, QuestionSection, QuestionType
from app.domains.questions.schemas import QuestionCreate
from app.domains.questions.service import QuestionService
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")


class FakeQuestionRepository:
    """Duble do repository: guarda em lista, nao decide nada."""

    def __init__(
        self,
        existentes: list[Question] | None = None,
        recusar_insert: bool = False,
    ) -> None:
        self.itens: list[Question] = list(existentes or [])
        self.secao_pedida: QuestionSection | str | None = "nao chamado"
        self.tipo_pedido: QuestionType | None = None
        self.recusar_insert = recusar_insert

    async def insert(self, question: Question) -> Question | None:
        if self.recusar_insert:
            return None
        self.itens.append(question)
        return question

    async def get_by_id(self, question_id: uuid.UUID) -> Question | None:
        return next((q for q in self.itens if q.id == question_id), None)

    async def list_required_by_type(
        self, form_id: uuid.UUID, question_type: QuestionType
    ) -> list[Question]:
        self.tipo_pedido = question_type
        return [q for q in self.itens if q.form_id == form_id]

    async def list_by_form(
        self, form_id: uuid.UUID, section: QuestionSection | None = None
    ) -> list[Question]:
        self.secao_pedida = section
        return [q for q in self.itens if q.form_id == form_id]

    async def get_by_form_and_order(
        self, form_id: uuid.UUID, order_index: int
    ) -> Question | None:
        return next(
            (
                q
                for q in self.itens
                if q.form_id == form_id and q.order_index == order_index
            ),
            None,
        )


def uma_question(**campos: object) -> Question:
    """Question montada a mao.

    Todo campo vai explicito: `default` e `server_default` so sao aplicados
    no INSERT, entao uma Question que nunca passou pela sessao tem `None`
    neles.
    """
    padrao: dict[str, object] = {
        "id": uuid.uuid4(),
        "form_id": uuid.uuid4(),
        "text": "Como voce avalia sua adaptabilidade?",
        "order_index": 0,
        "type": QuestionType.OBJECTIVE,
        "section": QuestionSection.ASSESSMENT,
        "required": True,
        "prisma": None,
        "created_at": datetime(2026, 9, 22, tzinfo=UTC),
    }
    return Question(**{**padrao, **campos})


class FakeFormService:
    """Duble do `FormService`: responde "existe?" e a conferencia de organizacao.

    `existe=False` faz toda consulta levantar `NotFoundError`; `proibido=True` faz
    a conferencia levantar `ForbiddenError`, como o service real faz para outra
    organizacao. A regra em si (P-033) e provada em tests/domains/forms.
    """

    def __init__(self, *, existe: bool = True, proibido: bool = False) -> None:
        self.existe = existe
        self.proibido = proibido

    async def get(self, form_id: uuid.UUID) -> SimpleNamespace:
        if not self.existe:
            raise NotFoundError(f"Formulário {form_id} não encontrado")
        return SimpleNamespace(id=form_id, organization_id=ORG)

    async def get_for_user(
        self, form_id: uuid.UUID, *, role: str, organization_id: uuid.UUID
    ) -> SimpleNamespace:
        form = await self.get(form_id)
        self.check_organization(
            form.organization_id, role=role, organization_id=organization_id
        )
        return form

    def check_organization(
        self,
        form_organization_id: uuid.UUID,
        *,
        role: str,
        organization_id: uuid.UUID,
    ) -> None:
        if self.proibido:
            raise ForbiddenError("Sem acesso a formulário de outra organização")


def servico(
    repository: FakeQuestionRepository, forms: FakeFormService | None = None
) -> QuestionService:
    return QuestionService(
        repository,  # type: ignore[arg-type]
        forms or FakeFormService(),  # type: ignore[arg-type]
    )


class TestCriarQuestion:
    async def test_formulario_inexistente_vira_validation_error_sem_gravar(
        self,
    ) -> None:
        """O formulario veio no corpo: inexistente e 422, nao 404 (CREED-47)."""
        repository = FakeQuestionRepository()
        form_id = uuid.uuid4()

        with pytest.raises(ValidationError, match=re.escape(str(form_id))):
            await servico(repository, FakeFormService(existe=False)).create(
                QuestionCreate(
                    form_id=form_id,
                    text="Pergunta de formulario que nao existe",
                    order_index=0,
                    type=QuestionType.DESCRIPTIVE,
                    section=QuestionSection.PROFILE,
                ),
                role="gestor",
                organization_id=ORG,
            )

        assert repository.itens == []

    async def test_corrida_na_gravacao_vira_conflito_sem_gravar(self) -> None:
        form_id = uuid.uuid4()
        repository = FakeQuestionRepository(recusar_insert=True)

        with pytest.raises(ConflictError, match=re.escape(str(form_id))):
            await servico(repository).create(
                QuestionCreate(
                    form_id=form_id,
                    text="Pergunta que perde a corrida",
                    order_index=0,
                    type=QuestionType.OBJECTIVE,
                    section=QuestionSection.ASSESSMENT,
                ),
                role="gestor",
                organization_id=ORG,
            )

        assert repository.itens == []

    async def test_persiste_os_campos_do_payload(self) -> None:
        repository = FakeQuestionRepository()
        form_id = uuid.uuid4()

        criada = await servico(repository).create(
            QuestionCreate(
                form_id=form_id,
                text="Como voce avalia sua adaptabilidade?",
                order_index=0,
                type=QuestionType.OBJECTIVE,
                section=QuestionSection.ASSESSMENT,
            ),
            role="gestor",
            organization_id=ORG,
        )

        assert criada.form_id == form_id
        assert criada.text == "Como voce avalia sua adaptabilidade?"
        assert criada.section is QuestionSection.ASSESSMENT
        assert repository.itens == [criada]

    async def test_nasce_required_e_sem_prisma_quando_omitidos(self) -> None:
        repository = FakeQuestionRepository()

        criada = await servico(repository).create(
            QuestionCreate(
                form_id=uuid.uuid4(),
                text="Pergunta sem required nem prisma",
                order_index=0,
                type=QuestionType.DESCRIPTIVE,
                section=QuestionSection.PROFILE,
            ),
            role="gestor",
            organization_id=ORG,
        )

        assert criada.required is True
        assert criada.prisma is None

    async def test_posicao_repetida_no_mesmo_formulario_vira_conflito(self) -> None:
        form_id = uuid.uuid4()
        repository = FakeQuestionRepository(
            [uma_question(form_id=form_id, order_index=2)]
        )

        with pytest.raises(ConflictError, match=re.escape(str(form_id))):
            await servico(repository).create(
                QuestionCreate(
                    form_id=form_id,
                    text="Outra pergunta, outra secao",
                    order_index=2,
                    type=QuestionType.OBJECTIVE,
                    section=QuestionSection.CLOSING,
                ),
                role="gestor",
                organization_id=ORG,
            )

        assert len(repository.itens) == 1

    async def test_mesma_posicao_em_outro_formulario_e_aceita(self) -> None:
        repository = FakeQuestionRepository(
            [uma_question(form_id=uuid.uuid4(), order_index=2)]
        )

        criada = await servico(repository).create(
            QuestionCreate(
                form_id=uuid.uuid4(),
                text="Pergunta em outro formulario",
                order_index=2,
                type=QuestionType.OBJECTIVE,
                section=QuestionSection.ASSESSMENT,
            ),
            role="gestor",
            organization_id=ORG,
        )

        assert len(repository.itens) == 2
        assert criada.order_index == 2

    async def test_formulario_de_outra_organizacao_vira_forbidden_sem_gravar(
        self,
    ) -> None:
        """A regra (P-033) e do FormService; aqui se prova que ela e pedida."""
        repository = FakeQuestionRepository()

        with pytest.raises(ForbiddenError):
            await servico(repository, FakeFormService(proibido=True)).create(
                QuestionCreate(
                    form_id=uuid.uuid4(),
                    text="Pergunta em formulario alheio",
                    order_index=0,
                    type=QuestionType.DESCRIPTIVE,
                    section=QuestionSection.PROFILE,
                ),
                role="gestor",
                organization_id=uuid.uuid4(),
            )

        assert repository.itens == []


class TestListarQuestionsDoFormulario:
    async def test_repassa_a_secao_pedida_para_o_repository(self) -> None:
        """Prova so o repasse — quem prova o filtro de verdade e a CREED-353."""
        form_id = uuid.uuid4()
        repository = FakeQuestionRepository([uma_question(form_id=form_id)])

        await servico(repository).list_for_form(
            form_id, QuestionSection.PROFILE, role="gestor", organization_id=ORG
        )

        assert repository.secao_pedida is QuestionSection.PROFILE

    async def test_sem_secao_repassa_none(self) -> None:
        form_id = uuid.uuid4()
        repository = FakeQuestionRepository([uma_question(form_id=form_id)])

        await servico(repository).list_for_form(
            form_id, role="gestor", organization_id=ORG
        )

        assert repository.secao_pedida is None

    async def test_formulario_sem_pergunta_devolve_lista_vazia(self) -> None:
        repository = FakeQuestionRepository()

        resultado = await servico(repository).list_for_form(
            uuid.uuid4(), role="gestor", organization_id=ORG
        )

        assert resultado == []

    async def test_formulario_inexistente_vira_not_found(self) -> None:
        """Antes da CREED-47, devolvia lista vazia, igual a formulario sem pergunta."""
        repository = FakeQuestionRepository()

        with pytest.raises(NotFoundError):
            await servico(repository, FakeFormService(existe=False)).list_for_form(
                uuid.uuid4(), role="gestor", organization_id=ORG
            )

        assert repository.secao_pedida == "nao chamado"

    async def test_formulario_de_outra_organizacao_vira_forbidden(self) -> None:
        repository = FakeQuestionRepository()

        with pytest.raises(ForbiddenError):
            await servico(repository, FakeFormService(proibido=True)).list_for_form(
                uuid.uuid4(), role="respondente", organization_id=uuid.uuid4()
            )

        assert repository.secao_pedida == "nao chamado"


class TestBuscarQuestion:
    async def test_devolve_a_pergunta_encontrada(self) -> None:
        question = uma_question()

        encontrada = await servico(FakeQuestionRepository([question])).get(question.id)

        assert encontrada is question

    async def test_inexistente_vira_not_found(self) -> None:
        question_id = uuid.uuid4()

        with pytest.raises(NotFoundError, match=re.escape(str(question_id))):
            await servico(FakeQuestionRepository()).get(question_id)


class TestObrigatoriasDoEnvio:
    async def test_pede_ao_banco_so_as_descritivas(self) -> None:
        """A objetiva não conta até a CREED-37 (D2). O filtro de `required` e de
        tipo é SQL, no repository: este teste só prova qual tipo é pedido."""
        form_id = uuid.uuid4()
        question = uma_question(form_id=form_id, type=QuestionType.DESCRIPTIVE)
        repository = FakeQuestionRepository([question])

        resultado = await servico(repository).list_required_descriptive(form_id)

        assert resultado == [question]
        assert repository.tipo_pedido is QuestionType.DESCRIPTIVE


class TestPerguntaDescritiva:
    def test_descritiva(self) -> None:
        question = uma_question(type=QuestionType.DESCRIPTIVE)

        assert servico(FakeQuestionRepository()).is_descriptive(question)

    def test_objetiva_nao_e_descritiva(self) -> None:
        question = uma_question(type=QuestionType.OBJECTIVE)

        assert not servico(FakeQuestionRepository()).is_descriptive(question)
