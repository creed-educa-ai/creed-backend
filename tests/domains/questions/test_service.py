"""Testes do service do dominio questions.

Sem banco e sem HTTP: o repository e substituido por um duble em memoria.
O que se prova aqui e a regra de negocio — conflito de posicao repetida e
que a secao pedida chega ate a camada de banco.

⚠️ Este teste NAO prova ordenacao nem filtro por secao de verdade: o duble
filtra em memoria, sem rodar consulta nenhuma. Ordenacao e filtro reais sao
provados pela CREED-353, de ponta a ponta, com banco.
"""

import re
import uuid
from datetime import UTC, datetime

import pytest

from app.domains.questions.models import Question, QuestionSection, QuestionType
from app.domains.questions.schemas import QuestionCreate
from app.domains.questions.service import QuestionService
from app.shared.exceptions import ConflictError


class FakeQuestionRepository:
    """Duble do repository: guarda em lista, nao decide nada."""

    def __init__(self, existentes: list[Question] | None = None) -> None:
        self.itens: list[Question] = list(existentes or [])
        self.secao_pedida: QuestionSection | str | None = "nao chamado"

    async def insert(self, question: Question) -> Question:
        self.itens.append(question)
        return question

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


def servico(repository: FakeQuestionRepository) -> QuestionService:
    return QuestionService(repository)  # type: ignore[arg-type]


class TestCriarQuestion:
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
            )
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
            )
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
                )
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
            )
        )

        assert len(repository.itens) == 2
        assert criada.order_index == 2


class TestListarQuestionsDoFormulario:
    async def test_repassa_a_secao_pedida_para_o_repository(self) -> None:
        """Prova so o repasse — quem prova o filtro de verdade e a CREED-353."""
        form_id = uuid.uuid4()
        repository = FakeQuestionRepository([uma_question(form_id=form_id)])

        await servico(repository).list_for_form(form_id, QuestionSection.PROFILE)

        assert repository.secao_pedida is QuestionSection.PROFILE

    async def test_sem_secao_repassa_none(self) -> None:
        form_id = uuid.uuid4()
        repository = FakeQuestionRepository([uma_question(form_id=form_id)])

        await servico(repository).list_for_form(form_id)

        assert repository.secao_pedida is None

    async def test_formulario_sem_pergunta_devolve_lista_vazia(self) -> None:
        repository = FakeQuestionRepository()

        resultado = await servico(repository).list_for_form(uuid.uuid4())

        assert resultado == []
