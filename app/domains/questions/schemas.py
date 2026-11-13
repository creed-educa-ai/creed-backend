"""Schemas Pydantic do dominio questions.

Separados por direcao (ADR-002, secao 2.3): entrada e saida nao se
contaminam. A montagem da saida a partir do model mora aqui, em `de_model()`,
e nao no router (mesmo padrao de app/domains/users/schemas.py).

Reexporta QuestionSection: a terceira entrega (router) precisa do tipo para
o filtro `?section=`, e a rota nao pode importar de models.py.

Idiomas: `Question.text` e `QuestionOption.label` sao sempre PT (português por padrão). Em
`de_model(..., lang=...)` o texto sai traduzido se existir traducão,
caso não exista, cai no PT. Na leitura, o `?lang=` usa `QuestionLangQuery`, que
aceita também `pt`/`pt-BR`; na escrita de tradução, `QuestionLang` só tem EN e ES.
"""

import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.questions.models import (
    Question,
    QuestionLang,
    QuestionOption,
    QuestionOptionTranslation,
    QuestionSection,
    QuestionTranslation,
    QuestionType,
)
from app.shared.enums import Dimension, Prisma

__all__ = [
    "Dimension",
    "Prisma",
    "QuestionCreate",
    "QuestionLang",
    "QuestionLangQuery",
    "QuestionOptionCreate",
    "QuestionOptionResponse",
    "QuestionOptionTranslationCreate",
    "QuestionOptionTranslationResponse",
    "QuestionResponse",
    "QuestionSection",
    "QuestionTranslationCreate",
    "QuestionTranslationResponse",
    "QuestionType",
    "QuestionWithOptionsResponse",
]


class QuestionLangQuery(enum.Enum):
    """Idioma pedido na leitura (`?lang=`). Diferente de `QuestionLang`, aceita o PT,
    para o front mandar sempre o idioma da interface."""

    PT = "pt"
    PT_BR = "pt-BR"
    EN = "en"
    ES = "es"

    @property
    def translation_lang(self) -> QuestionLang | None:
        """Idioma de tradução a carregar; `None` no PT, que é o texto original."""
        if self in (QuestionLangQuery.PT, QuestionLangQuery.PT_BR):
            return None
        return QuestionLang(self.value)


class QuestionBase(BaseModel):
    instrument_id: uuid.UUID = Field(
        description="Identificador do instrumento ao qual a pergunta pertence.",
        examples=["00000000-0000-0000-0000-00000000c4ed"],
    )
    text: str = Field(
        min_length=1,
        description="Enunciado da pergunta (em PT, o idioma padrão).",
        examples=["Como você avalia sua adaptabilidade?"],
    )
    order_index: int = Field(
        ge=0,
        description="Posição da pergunta no instrumento, começando em 0.",
        examples=[0],
    )
    type: QuestionType = Field(description="Tipo de resposta esperado pela pergunta.")
    section: QuestionSection = Field(
        description="Seção do formulário original; o front desenha uma aba por seção."
    )


class QuestionCreate(QuestionBase):
    """Payload de criacao.

    `required` nasce true e `prisma` nasce vazio quando omitidos — mesma
    forma que o model, mas explicito aqui porque e o service quem decide
    (ADR-0004: o que muda se o produto mudar de ideia mora no service, mas
    o *default de payload* e contrato de entrada, entao mora no schema).

    O texto aqui e sempre o PT. Traducoes entram por
    `QuestionTranslationCreate`, em outra chamada.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "instrument_id": "00000000-0000-0000-0000-00000000c4ed",
                    "text": "Como você avalia sua adaptabilidade?",
                    "order_index": 0,
                    "type": "objective",
                    "section": "S2",
                    "dimensao": "S2",
                }
            ]
        }
    )

    required: bool = Field(
        default=True,
        description="Se a pergunta exige resposta para submeter o formulário.",
    )
    dimensao: Dimension | None = Field(
        default=None,
        description="Dimensão da Matriz CREED associada à pergunta, quando houver.",
    )
    prisma: Prisma | None = Field(
        default=None,
        description="Dimensão de análise associada à pergunta, quando houver.",
    )


class QuestionResponse(QuestionBase):
    """Representação de saída.

    text vem no idioma pedido em `de_model(lang=...)`, com fallback pro PT.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "7ae21494-975f-46ab-97cc-4c42b5ae7aaa",
                    "instrument_id": "00000000-0000-0000-0000-00000000c4ed",
                    "text": "Como você avalia sua adaptabilidade?",
                    "order_index": 0,
                    "type": "objective",
                    "section": "S2",
                    "required": True,
                    "dimensao": "S2",
                    "prisma": "seguranca_psicologica",
                    "created_at": "2026-09-22T14:00:00Z",
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador da pergunta.")
    required: bool = Field(
        description="Se a pergunta exige resposta para submeter o formulário."
    )
    dimensao: Dimension | None = Field(
        description="Dimensão da Matriz CREED associada à pergunta, quando houver."
    )
    prisma: Prisma | None = Field(
        description="Dimensão de análise associada à pergunta, quando houver."
    )
    created_at: datetime = Field(description="Data e hora de criação da pergunta.")

    @classmethod
    def de_model(
        cls, question: Question, lang: QuestionLang | None = None
    ) -> "QuestionResponse":
        """Monta a saida a partir do model.

        Com `lang`, exige `question.translations` carregado (selectinload no
        repository); sem traducao pro idioma, mantem o texto PT.
        """
        resposta = cls.model_validate(question)
        if lang is None:
            return resposta
        for traducao in question.translations:
            if traducao.lang == lang:
                return resposta.model_copy(update={"text": traducao.text})
        return resposta


class QuestionTranslationCreate(BaseModel):
    """Payload de criação de tradução.

    A pergunta vem do caminho da URL (`/questions/{question_id}/translations`).
    `QuestionLang` só tem EN e ES, então tentar mandar "pt" é rejeitado na
    validação: o PT vive em `Question.text`.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"lang": "en", "text": "How do you rate your adaptability?"}]
        }
    )

    lang: QuestionLang = Field(description="Idioma da tradução (en ou es).")
    text: str = Field(
        min_length=1,
        description="Enunciado da pergunta no idioma informado.",
        examples=["How do you rate your adaptability?"],
    )


class QuestionTranslationResponse(BaseModel):
    """Representação de saída da tradução de uma pergunta."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "7ae21494-975f-46ab-97cc-4c42b5ae7aac",
                    "question_id": "7ae21494-975f-46ab-97cc-4c42b5ae7aaa",
                    "lang": "en",
                    "text": "How do you rate your adaptability?",
                    "created_at": "2026-11-07T14:00:00Z",
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador da tradução.")
    question_id: uuid.UUID = Field(description="Identificador da pergunta traduzida.")
    lang: QuestionLang = Field(description="Idioma da tradução.")
    text: str = Field(description="Enunciado da pergunta no idioma informado.")
    created_at: datetime = Field(description="Data e hora de criação da tradução.")

    @classmethod
    def de_model(cls, translation: QuestionTranslation) -> "QuestionTranslationResponse":
        """Monta a saída a partir do model."""
        return cls.model_validate(translation)


class QuestionOptionBase(BaseModel):
    label: str = Field(
        min_length=1,
        description="Texto da alternativa em PT, como aparece para quem responde.",
        examples=["Sim"],
    )
    value: str = Field(
        min_length=1,
        description="Valor gravado quando a alternativa é escolhida. Não é traduzido.",
        examples=["sim"],
    )
    order_index: int = Field(
        ge=0,
        description="Posição da alternativa na pergunta, começando em 0.",
        examples=[0],
    )


class QuestionOptionCreate(QuestionOptionBase):
    """Payload de criação.

    A pergunta vem do caminho da URL (`/questions/{question_id}/options`), não do
    corpo: aceitar nos dois lugares deixaria dois valores possíveis para o mesmo dado.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"label": "Sim", "value": "sim", "order_index": 0}]
        }
    )


class QuestionOptionResponse(QuestionOptionBase):
    """Representação de saída.

    `label` vem no idioma pedido em `de_model(lang=...)`, com fallback pro PT.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "7ae21494-975f-46ab-97cc-4c42b5ae7aab",
                    "question_id": "7ae21494-975f-46ab-97cc-4c42b5ae7aaa",
                    "label": "Sim",
                    "value": "sim",
                    "order_index": 0,
                    "created_at": "2026-10-14T14:00:00Z",
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador da alternativa.")
    question_id: uuid.UUID = Field(
        description="Identificador da pergunta a que a alternativa pertence."
    )
    created_at: datetime = Field(description="Data e hora de criação da alternativa.")

    @classmethod
    def de_model(
        cls, option: QuestionOption, lang: QuestionLang | None = None
    ) -> "QuestionOptionResponse":
        """Monta a saída a partir do model.

        Com `lang`, exige `option.translations` carregado (selectinload no
        repository); sem tradução pro idioma, mantém o label PT.
        """
        resposta = cls.model_validate(option)
        if lang is None:
            return resposta
        for traducao in option.translations:
            if traducao.lang == lang:
                return resposta.model_copy(update={"label": traducao.label})
        return resposta


class QuestionWithOptionsResponse(QuestionResponse):
    """Saída da listagem: a pergunta com as alternativas.

    Só a listagem usa este formato: no cadastro (`POST /questions`) a relação
    `options` não está carregada.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "7ae21494-975f-46ab-97cc-4c42b5ae7aaa",
                    "instrument_id": "00000000-0000-0000-0000-00000000c4ed",
                    "text": "Como você avalia sua adaptabilidade?",
                    "order_index": 0,
                    "type": "objective",
                    "section": "S2",
                    "required": True,
                    "dimensao": "S2",
                    "prisma": "seguranca_psicologica",
                    "created_at": "2026-09-22T14:00:00Z",
                    "options": [
                        {
                            "id": "7ae21494-975f-46ab-97cc-4c42b5ae7aab",
                            "question_id": "7ae21494-975f-46ab-97cc-4c42b5ae7aaa",
                            "label": "Sim",
                            "value": "sim",
                            "order_index": 0,
                            "created_at": "2026-10-14T14:00:00Z",
                        }
                    ],
                }
            ]
        },
    )

    options: list[QuestionOptionResponse] = Field(
        description=(
            "Alternativas da pergunta, em ordem de posição, no mesmo idioma do "
            "enunciado. Vazia na pergunta descritiva."
        )
    )

    @classmethod
    def de_model(
        cls, question: Question, lang: QuestionLang | None = None
    ) -> "QuestionWithOptionsResponse":
        """Monta a saída a partir do model.

        Exige `question.options` carregado (selectinload no repository). O
        fallback pro PT vale item a item.
        """
        pergunta = QuestionResponse.de_model(question, lang)
        return cls.model_validate(
            {
                **pergunta.model_dump(),
                "options": [
                    QuestionOptionResponse.de_model(option, lang)
                    for option in question.options
                ],
            }
        )


class QuestionOptionTranslationCreate(BaseModel):
    """Payload de criação de tradução de alternativa.

    A alternativa vem do caminho da URL. Só traduz o `label`: o `value` é estável.
    """

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"lang": "en", "label": "Yes"}]}
    )

    lang: QuestionLang = Field(description="Idioma da tradução (en ou es).")
    label: str = Field(
        min_length=1,
        description="Texto da alternativa no idioma informado.",
        examples=["Yes"],
    )


class QuestionOptionTranslationResponse(BaseModel):
    """Representação de saída da tradução de uma alternativa."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "7ae21494-975f-46ab-97cc-4c42b5ae7aad",
                    "option_id": "7ae21494-975f-46ab-97cc-4c42b5ae7aab",
                    "lang": "en",
                    "label": "Yes",
                    "created_at": "2026-11-07T14:00:00Z",
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador da tradução.")
    option_id: uuid.UUID = Field(description="Identificador da alternativa traduzida.")
    lang: QuestionLang = Field(description="Idioma da tradução.")
    label: str = Field(description="Texto da alternativa no idioma informado.")
    created_at: datetime = Field(description="Data e hora de criação da tradução.")

    @classmethod
    def de_model(
        cls, translation: QuestionOptionTranslation
    ) -> "QuestionOptionTranslationResponse":
        """Monta a saída a partir do model."""
        return cls.model_validate(translation)
