"""Testes do `de_model` de app/domains/questions/schemas.py por idioma.

Sem banco: as relações (`translations`, `options`) são preenchidas à mão, que é o
que o selectinload do repository entrega.
"""

import uuid
from datetime import UTC, datetime

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
    QuestionOptionResponse,
    QuestionResponse,
    QuestionWithOptionsResponse,
)


def uma_question(**campos: object) -> Question:
    padrao: dict[str, object] = {
        "id": uuid.uuid4(),
        "instrument_id": uuid.uuid4(),
        "text": "Você se adapta bem?",
        "order_index": 0,
        "type": QuestionType.OBJECTIVE,
        "section": QuestionSection.S2,
        "required": True,
        "dimensao": None,
        "prisma": None,
        "created_at": datetime(2026, 9, 22, tzinfo=UTC),
        "translations": [
            QuestionTranslation(lang=QuestionLang.EN, text="Do you adapt well?")
        ],
    }
    return Question(**{**padrao, **campos})


def uma_option(**campos: object) -> QuestionOption:
    padrao: dict[str, object] = {
        "id": uuid.uuid4(),
        "question_id": uuid.uuid4(),
        "label": "Sim",
        "value": "sim",
        "order_index": 0,
        "created_at": datetime(2026, 10, 14, tzinfo=UTC),
        "translations": [QuestionOptionTranslation(lang=QuestionLang.EN, label="Yes")],
    }
    return QuestionOption(**{**padrao, **campos})


class TestQuestionResponseDeModel:
    def test_com_traducao_no_idioma_devolve_a_traducao(self) -> None:
        resposta = QuestionResponse.de_model(uma_question(), lang=QuestionLang.EN)

        assert resposta.text == "Do you adapt well?"

    def test_sem_traducao_no_idioma_devolve_o_pt(self) -> None:
        resposta = QuestionResponse.de_model(uma_question(), lang=QuestionLang.ES)

        assert resposta.text == "Você se adapta bem?"

    def test_sem_lang_devolve_o_pt(self) -> None:
        resposta = QuestionResponse.de_model(uma_question())

        assert resposta.text == "Você se adapta bem?"


class TestQuestionOptionResponseDeModel:
    def test_com_traducao_no_idioma_devolve_a_traducao(self) -> None:
        resposta = QuestionOptionResponse.de_model(uma_option(), lang=QuestionLang.EN)

        assert (resposta.label, resposta.value) == ("Yes", "sim")

    def test_sem_traducao_no_idioma_devolve_o_pt(self) -> None:
        resposta = QuestionOptionResponse.de_model(uma_option(), lang=QuestionLang.ES)

        assert resposta.label == "Sim"

    def test_sem_lang_devolve_o_pt(self) -> None:
        resposta = QuestionOptionResponse.de_model(uma_option())

        assert resposta.label == "Sim"


class TestQuestionWithOptionsResponseDeModel:
    def test_traduz_pergunta_e_alternativas_item_a_item(self) -> None:
        question = uma_question(
            options=[
                uma_option(),
                uma_option(label="Não", value="nao", order_index=1, translations=[]),
            ]
        )

        resposta = QuestionWithOptionsResponse.de_model(question, lang=QuestionLang.EN)

        assert resposta.text == "Do you adapt well?"
        assert [option.label for option in resposta.options] == ["Yes", "Não"]
