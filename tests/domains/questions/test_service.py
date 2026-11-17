"""Testes do service do dominio questions.

Sem banco e sem HTTP: o repository e o `FormService` sao substituidos por
dubles em memoria. O que se prova aqui e a regra de negocio — o instrumento
precisa existir, conflito de posicao repetida, uma traducao por idioma e que a
secao e o idioma pedidos chegam ate a camada de banco.

⚠️ Este teste NAO prova ordenacao nem filtro por secao de verdade: o duble
filtra em memoria, sem rodar consulta nenhuma. Ordenacao e filtro reais sao
provados pela CREED-353, de ponta a ponta, com banco.
"""

import re
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.domains.questions.models import (
    Question,
    QuestionLang,
    QuestionOption,
    QuestionOptionTranslation,
    QuestionSection,
    QuestionTranslation,
    QuestionType,
)
from app.domains.questions.schemas import (
    QuestionCreate,
    QuestionOptionCreate,
    QuestionOptionTranslationCreate,
    QuestionTranslationCreate,
)
from app.domains.questions.service import (
    QuestionOptionService,
    QuestionOptionTranslationService,
    QuestionService,
    QuestionTranslationService,
)
from app.shared.enums import Dimension
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
        instrumento_existe: bool = True,
    ) -> None:
        self.itens: list[Question] = list(existentes or [])
        self.instrumento_existe = instrumento_existe
        self.secao_pedida: QuestionSection | str | None = "nao chamado"
        self.idioma_pedido: QuestionLang | str | None = "nao chamado"
        self.tipo_pedido: QuestionType | None = None
        self.recusar_insert = recusar_insert

    async def insert(self, question: Question) -> Question | None:
        if self.recusar_insert:
            return None
        self.itens.append(question)
        return question

    async def get_by_id(self, question_id: uuid.UUID) -> Question | None:
        return next((q for q in self.itens if q.id == question_id), None)

    async def instrument_exists(self, instrument_id: uuid.UUID) -> bool:
        return self.instrumento_existe

    async def list_required(self, instrument_id: uuid.UUID) -> list[Question]:
        return [q for q in self.itens if q.instrument_id == instrument_id]

    async def list_by_instrument(
        self,
        instrument_id: uuid.UUID,
        section: QuestionSection | None = None,
        lang: QuestionLang | None = None,
    ) -> list[Question]:
        self.secao_pedida = section
        self.idioma_pedido = lang
        return [q for q in self.itens if q.instrument_id == instrument_id]

    async def get_by_instrument_and_order(
        self, instrument_id: uuid.UUID, order_index: int
    ) -> Question | None:
        return next(
            (
                q
                for q in self.itens
                if q.instrument_id == instrument_id and q.order_index == order_index
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
        "instrument_id": uuid.uuid4(),
        "text": "Como voce avalia sua adaptabilidade?",
        "order_index": 0,
        "type": QuestionType.OBJECTIVE,
        "section": QuestionSection.S4,
        "required": True,
        "dimensao": None,
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
        # O instrumento do duble tem o id do formulario: a pergunta montada com
        # `instrument_id=form_id` e a que o formulario aplica.
        return SimpleNamespace(id=form_id, organization_id=ORG, instrument_id=form_id)

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
    async def test_instrumento_inexistente_vira_validation_error_sem_gravar(
        self,
    ) -> None:
        """O instrumento veio no corpo: inexistente e 422, nao 404 (CREED-47)."""
        repository = FakeQuestionRepository(instrumento_existe=False)
        instrument_id = uuid.uuid4()

        with pytest.raises(ValidationError, match=re.escape(str(instrument_id))):
            await servico(repository).create(
                QuestionCreate(
                    instrument_id=instrument_id,
                    text="Pergunta de instrumento que nao existe",
                    order_index=0,
                    type=QuestionType.DESCRIPTIVE,
                    section=QuestionSection.S2,
                ),
            )

        assert repository.itens == []

    async def test_corrida_na_gravacao_vira_conflito_sem_gravar(self) -> None:
        form_id = uuid.uuid4()
        repository = FakeQuestionRepository(recusar_insert=True)

        with pytest.raises(ConflictError, match=re.escape(str(form_id))):
            await servico(repository).create(
                QuestionCreate(
                    instrument_id=form_id,
                    text="Pergunta que perde a corrida",
                    order_index=0,
                    type=QuestionType.OBJECTIVE,
                    section=QuestionSection.S4,
                ),
            )

        assert repository.itens == []

    async def test_persiste_os_campos_do_payload(self) -> None:
        repository = FakeQuestionRepository()
        form_id = uuid.uuid4()

        criada = await servico(repository).create(
            QuestionCreate(
                instrument_id=form_id,
                text="Como voce avalia sua adaptabilidade?",
                order_index=0,
                type=QuestionType.OBJECTIVE,
                section=QuestionSection.S4,
            ),
        )

        assert criada.instrument_id == form_id
        assert criada.text == "Como voce avalia sua adaptabilidade?"
        assert criada.section is QuestionSection.S4
        assert repository.itens == [criada]

    async def test_persiste_a_dimensao_do_payload(self) -> None:
        repository = FakeQuestionRepository()

        criada = await servico(repository).create(
            QuestionCreate(
                instrument_id=uuid.uuid4(),
                text="Item da dimensão S2",
                order_index=0,
                type=QuestionType.OBJECTIVE,
                section=QuestionSection.S4,
                dimensao=Dimension.S2,
            ),
        )

        assert criada.dimensao is Dimension.S2

    async def test_nasce_required_e_sem_prisma_quando_omitidos(self) -> None:
        repository = FakeQuestionRepository()

        criada = await servico(repository).create(
            QuestionCreate(
                instrument_id=uuid.uuid4(),
                text="Pergunta sem required nem prisma",
                order_index=0,
                type=QuestionType.DESCRIPTIVE,
                section=QuestionSection.S2,
            ),
        )

        assert criada.required is True
        assert criada.prisma is None
        assert criada.dimensao is None

    async def test_posicao_repetida_no_mesmo_instrumento_vira_conflito(self) -> None:
        form_id = uuid.uuid4()
        repository = FakeQuestionRepository(
            [uma_question(instrument_id=form_id, order_index=2)]
        )

        with pytest.raises(ConflictError, match=re.escape(str(form_id))):
            await servico(repository).create(
                QuestionCreate(
                    instrument_id=form_id,
                    text="Outra pergunta, outra secao",
                    order_index=2,
                    type=QuestionType.OBJECTIVE,
                    section=QuestionSection.S9,
                ),
            )

        assert len(repository.itens) == 1

    async def test_mesma_posicao_em_outro_instrumento_e_aceita(self) -> None:
        repository = FakeQuestionRepository(
            [uma_question(instrument_id=uuid.uuid4(), order_index=2)]
        )

        criada = await servico(repository).create(
            QuestionCreate(
                instrument_id=uuid.uuid4(),
                text="Pergunta em outro formulario",
                order_index=2,
                type=QuestionType.OBJECTIVE,
                section=QuestionSection.S4,
            ),
        )

        assert len(repository.itens) == 2
        assert criada.order_index == 2


class TestListarQuestionsDoFormulario:
    async def test_repassa_a_secao_pedida_para_o_repository(self) -> None:
        """Prova so o repasse — quem prova o filtro de verdade e a CREED-353."""
        form_id = uuid.uuid4()
        repository = FakeQuestionRepository([uma_question(instrument_id=form_id)])

        await servico(repository).list_for_form(
            form_id, QuestionSection.S2, role="gestor", organization_id=ORG
        )

        assert repository.secao_pedida is QuestionSection.S2

    async def test_sem_secao_repassa_none(self) -> None:
        form_id = uuid.uuid4()
        repository = FakeQuestionRepository([uma_question(instrument_id=form_id)])

        await servico(repository).list_for_form(
            form_id, role="gestor", organization_id=ORG
        )

        assert repository.secao_pedida is None

    async def test_repassa_o_idioma_pedido_para_o_repository(self) -> None:
        """Carregar so a traducao do idioma e do repository; aqui, so o repasse."""
        form_id = uuid.uuid4()
        repository = FakeQuestionRepository([uma_question(instrument_id=form_id)])

        await servico(repository).list_for_form(
            form_id, None, QuestionLang.ES, role="gestor", organization_id=ORG
        )

        assert repository.idioma_pedido is QuestionLang.ES

    async def test_sem_idioma_repassa_none(self) -> None:
        form_id = uuid.uuid4()
        repository = FakeQuestionRepository([uma_question(instrument_id=form_id)])

        await servico(repository).list_for_form(
            form_id, role="gestor", organization_id=ORG
        )

        assert repository.idioma_pedido is None

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
    async def test_devolve_descritivas_e_objetivas(self) -> None:
        """Com as alternativas da CREED-37, a objetiva conta (fecha o D2 da
        CREED-47). O filtro de `required` é SQL, no repository: este teste só
        prova que o service não descarta nenhum tipo."""
        form_id = uuid.uuid4()
        descritiva = uma_question(instrument_id=form_id, type=QuestionType.DESCRIPTIVE)
        objetiva = uma_question(
            instrument_id=form_id, type=QuestionType.OBJECTIVE, order_index=1
        )
        repository = FakeQuestionRepository([descritiva, objetiva])

        resultado = await servico(repository).list_required(form_id)

        assert resultado == [descritiva, objetiva]


class TestPerguntaDescritiva:
    def test_descritiva(self) -> None:
        question = uma_question(type=QuestionType.DESCRIPTIVE)

        assert servico(FakeQuestionRepository()).is_descriptive(question)

    def test_objetiva_nao_e_descritiva(self) -> None:
        question = uma_question(type=QuestionType.OBJECTIVE)

        assert not servico(FakeQuestionRepository()).is_descriptive(question)


class FakeQuestionOptionRepository:
    """Duble do repository de alternativas: guarda em lista, nao decide nada."""

    def __init__(
        self,
        existing: list[QuestionOption] | None = None,
        refuse_insert: bool = False,
    ) -> None:
        self.items: list[QuestionOption] = list(existing or [])
        self.refuse_insert = refuse_insert

    async def insert(self, option: QuestionOption) -> QuestionOption | None:
        if self.refuse_insert:
            return None
        self.items.append(option)
        return option

    async def get_by_id(self, option_id: uuid.UUID) -> QuestionOption | None:
        return next((o for o in self.items if o.id == option_id), None)

    async def get_by_question_and_order(
        self, question_id: uuid.UUID, order_index: int
    ) -> QuestionOption | None:
        return next(
            (
                o
                for o in self.items
                if o.question_id == question_id and o.order_index == order_index
            ),
            None,
        )


def an_option(**fields: object) -> QuestionOption:
    """QuestionOption montada a mao, com todo campo explicito.

    `default` e `server_default` so valem no INSERT, entao um objeto que nunca
    passou pela sessao teria `None` neles.
    """
    default: dict[str, object] = {
        "id": uuid.uuid4(),
        "question_id": uuid.uuid4(),
        "label": "Sim",
        "value": "sim",
        "order_index": 0,
        "created_at": datetime(2026, 10, 14, tzinfo=UTC),
    }
    return QuestionOption(**{**default, **fields})


def option_service(
    options: FakeQuestionOptionRepository,
    questions: list[Question] | None = None,
    forms: FakeFormService | None = None,
) -> QuestionOptionService:
    """Service real de alternativas, com o `QuestionService` real por baixo.

    So o banco e o `FormService` sao dubles: a pergunta e achada de verdade pelo
    `QuestionService.get`, que e o que o service de alternativas usa.
    """
    form_service = forms or FakeFormService()
    question_service = QuestionService(
        FakeQuestionRepository(questions),  # type: ignore[arg-type]
        form_service,  # type: ignore[arg-type]
    )
    return QuestionOptionService(
        options,  # type: ignore[arg-type]
        question_service,
    )


class TestCreateQuestionOption:
    async def test_persists_the_payload_fields_on_the_question(self) -> None:
        question = uma_question(type=QuestionType.OBJECTIVE)
        options = FakeQuestionOptionRepository()

        created = await option_service(options, [question]).create(
            question.id,
            QuestionOptionCreate(label="Sim", value="sim", order_index=0),
        )

        assert created.question_id == question.id
        assert (created.label, created.value, created.order_index) == ("Sim", "sim", 0)
        assert options.items == [created]

    async def test_unknown_question_raises_not_found_without_saving(self) -> None:
        options = FakeQuestionOptionRepository()
        question_id = uuid.uuid4()

        with pytest.raises(NotFoundError, match=re.escape(str(question_id))):
            await option_service(options).create(
                question_id,
                QuestionOptionCreate(label="Sim", value="sim", order_index=0),
            )

        assert options.items == []

    async def test_descriptive_question_raises_validation_error_without_saving(
        self,
    ) -> None:
        question = uma_question(type=QuestionType.DESCRIPTIVE)
        options = FakeQuestionOptionRepository()

        with pytest.raises(ValidationError, match="descritiva"):
            await option_service(options, [question]).create(
                question.id,
                QuestionOptionCreate(label="Sim", value="sim", order_index=0),
            )

        assert options.items == []

    async def test_occupied_position_raises_conflict_without_saving(self) -> None:
        question = uma_question(type=QuestionType.OBJECTIVE)
        existing = an_option(question_id=question.id, order_index=0)
        options = FakeQuestionOptionRepository([existing])

        with pytest.raises(ConflictError, match=re.escape(str(question.id))):
            await option_service(options, [question]).create(
                question.id,
                QuestionOptionCreate(label="Nao", value="nao", order_index=0),
            )

        assert options.items == [existing]

    async def test_lost_race_on_insert_raises_conflict_without_saving(self) -> None:
        question = uma_question(type=QuestionType.OBJECTIVE)
        options = FakeQuestionOptionRepository(refuse_insert=True)

        with pytest.raises(ConflictError, match=re.escape(str(question.id))):
            await option_service(options, [question]).create(
                question.id,
                QuestionOptionCreate(label="Sim", value="sim", order_index=0),
            )

        assert options.items == []

    async def test_same_position_on_another_question_is_allowed(self) -> None:
        question = uma_question(type=QuestionType.OBJECTIVE)
        other = an_option(question_id=uuid.uuid4(), order_index=0)
        options = FakeQuestionOptionRepository([other])

        created = await option_service(options, [question]).create(
            question.id,
            QuestionOptionCreate(label="Sim", value="sim", order_index=0),
        )

        assert options.items == [other, created]


class TestBuscarQuestionOption:
    """O "existe?" que `responses` usa para conferir a alternativa marcada."""

    async def test_existente_devolve_a_alternativa(self) -> None:
        option = an_option()
        options = FakeQuestionOptionRepository([option])

        assert await option_service(options).get(option.id) is option

    async def test_inexistente_vira_not_found(self) -> None:
        option_id = uuid.uuid4()

        with pytest.raises(NotFoundError, match=re.escape(str(option_id))):
            await option_service(FakeQuestionOptionRepository()).get(option_id)


class FakeQuestionTranslationRepository:
    """Duble do repository de traducoes de pergunta: guarda em lista."""

    def __init__(
        self,
        existentes: list[QuestionTranslation] | None = None,
        recusar_insert: bool = False,
    ) -> None:
        self.itens: list[QuestionTranslation] = list(existentes or [])
        self.recusar_insert = recusar_insert

    async def insert(
        self, translation: QuestionTranslation
    ) -> QuestionTranslation | None:
        if self.recusar_insert:
            return None
        self.itens.append(translation)
        return translation

    async def get_by_question_and_lang(
        self, question_id: uuid.UUID, lang: QuestionLang
    ) -> QuestionTranslation | None:
        return next(
            (t for t in self.itens if t.question_id == question_id and t.lang == lang),
            None,
        )


class FakeQuestionOptionTranslationRepository:
    """Duble do repository de traducoes de alternativa: guarda em lista."""

    def __init__(
        self,
        existentes: list[QuestionOptionTranslation] | None = None,
        recusar_insert: bool = False,
    ) -> None:
        self.itens: list[QuestionOptionTranslation] = list(existentes or [])
        self.recusar_insert = recusar_insert

    async def insert(
        self, translation: QuestionOptionTranslation
    ) -> QuestionOptionTranslation | None:
        if self.recusar_insert:
            return None
        self.itens.append(translation)
        return translation

    async def get_by_option_and_lang(
        self, option_id: uuid.UUID, lang: QuestionLang
    ) -> QuestionOptionTranslation | None:
        return next(
            (t for t in self.itens if t.option_id == option_id and t.lang == lang),
            None,
        )


def servico_de_traducao(
    traducoes: FakeQuestionTranslationRepository,
    perguntas: list[Question] | None = None,
    forms: FakeFormService | None = None,
) -> QuestionTranslationService:
    """Service real de traducao, com o `QuestionService` real por baixo."""
    form_service = forms or FakeFormService()
    question_service = QuestionService(
        FakeQuestionRepository(perguntas),  # type: ignore[arg-type]
        form_service,  # type: ignore[arg-type]
    )
    return QuestionTranslationService(
        traducoes,  # type: ignore[arg-type]
        question_service,
    )


def servico_de_traducao_de_alternativa(
    traducoes: FakeQuestionOptionTranslationRepository,
    alternativas: list[QuestionOption] | None = None,
    perguntas: list[Question] | None = None,
    forms: FakeFormService | None = None,
) -> QuestionOptionTranslationService:
    """Service real de traducao de alternativa, com os services reais por baixo."""
    form_service = forms or FakeFormService()
    question_service = QuestionService(
        FakeQuestionRepository(perguntas),  # type: ignore[arg-type]
        form_service,  # type: ignore[arg-type]
    )
    return QuestionOptionTranslationService(
        traducoes,  # type: ignore[arg-type]
        QuestionOptionService(
            FakeQuestionOptionRepository(alternativas),  # type: ignore[arg-type]
            question_service,
        ),
    )


class TestCriarTraducaoDePergunta:
    async def test_persiste_a_traducao_do_payload(self) -> None:
        question = uma_question()
        traducoes = FakeQuestionTranslationRepository()

        criada = await servico_de_traducao(traducoes, [question]).create(
            question.id,
            QuestionTranslationCreate(lang=QuestionLang.EN, text="Do you adapt well?"),
        )

        assert criada.question_id == question.id
        assert (criada.lang, criada.text) == (QuestionLang.EN, "Do you adapt well?")
        assert traducoes.itens == [criada]

    async def test_pergunta_inexistente_vira_not_found_sem_gravar(self) -> None:
        traducoes = FakeQuestionTranslationRepository()
        question_id = uuid.uuid4()

        with pytest.raises(NotFoundError, match=re.escape(str(question_id))):
            await servico_de_traducao(traducoes).create(
                question_id,
                QuestionTranslationCreate(lang=QuestionLang.EN, text="Text"),
            )

        assert traducoes.itens == []

    async def test_idioma_ja_traduzido_vira_conflito_sem_gravar(self) -> None:
        question = uma_question()
        existente = QuestionTranslation(
            question_id=question.id, lang=QuestionLang.EN, text="Text"
        )
        traducoes = FakeQuestionTranslationRepository([existente])

        with pytest.raises(ConflictError, match=re.escape(str(question.id))):
            await servico_de_traducao(traducoes, [question]).create(
                question.id,
                QuestionTranslationCreate(lang=QuestionLang.EN, text="Other text"),
            )

        assert traducoes.itens == [existente]

    async def test_corrida_na_gravacao_vira_conflito_sem_gravar(self) -> None:
        question = uma_question()
        traducoes = FakeQuestionTranslationRepository(recusar_insert=True)

        with pytest.raises(ConflictError, match=re.escape(str(question.id))):
            await servico_de_traducao(traducoes, [question]).create(
                question.id,
                QuestionTranslationCreate(lang=QuestionLang.EN, text="Text"),
            )

        assert traducoes.itens == []

    async def test_outro_idioma_na_mesma_pergunta_e_aceito(self) -> None:
        question = uma_question()
        existente = QuestionTranslation(
            question_id=question.id, lang=QuestionLang.EN, text="Text"
        )
        traducoes = FakeQuestionTranslationRepository([existente])

        criada = await servico_de_traducao(traducoes, [question]).create(
            question.id,
            QuestionTranslationCreate(lang=QuestionLang.ES, text="Texto"),
        )

        assert traducoes.itens == [existente, criada]


class TestCriarTraducaoDeAlternativa:
    async def test_persiste_a_traducao_do_payload(self) -> None:
        question = uma_question()
        option = an_option(question_id=question.id)
        traducoes = FakeQuestionOptionTranslationRepository()

        criada = await servico_de_traducao_de_alternativa(
            traducoes, [option], [question]
        ).create(
            option.id,
            QuestionOptionTranslationCreate(lang=QuestionLang.ES, label="Sí"),
        )

        assert criada.option_id == option.id
        assert (criada.lang, criada.label) == (QuestionLang.ES, "Sí")
        assert traducoes.itens == [criada]

    async def test_alternativa_inexistente_vira_not_found_sem_gravar(self) -> None:
        traducoes = FakeQuestionOptionTranslationRepository()
        option_id = uuid.uuid4()

        with pytest.raises(NotFoundError, match=re.escape(str(option_id))):
            await servico_de_traducao_de_alternativa(traducoes).create(
                option_id,
                QuestionOptionTranslationCreate(lang=QuestionLang.EN, label="Yes"),
            )

        assert traducoes.itens == []

    async def test_idioma_ja_traduzido_vira_conflito_sem_gravar(self) -> None:
        question = uma_question()
        option = an_option(question_id=question.id)
        existente = QuestionOptionTranslation(
            option_id=option.id, lang=QuestionLang.EN, label="Yes"
        )
        traducoes = FakeQuestionOptionTranslationRepository([existente])

        with pytest.raises(ConflictError, match=re.escape(str(option.id))):
            await servico_de_traducao_de_alternativa(
                traducoes, [option], [question]
            ).create(
                option.id,
                QuestionOptionTranslationCreate(lang=QuestionLang.EN, label="Yeah"),
            )

        assert traducoes.itens == [existente]

    async def test_corrida_na_gravacao_vira_conflito_sem_gravar(self) -> None:
        question = uma_question()
        option = an_option(question_id=question.id)
        traducoes = FakeQuestionOptionTranslationRepository(recusar_insert=True)

        with pytest.raises(ConflictError, match=re.escape(str(option.id))):
            await servico_de_traducao_de_alternativa(
                traducoes, [option], [question]
            ).create(
                option.id,
                QuestionOptionTranslationCreate(lang=QuestionLang.EN, label="Yes"),
            )

        assert traducoes.itens == []
