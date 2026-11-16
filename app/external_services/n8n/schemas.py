"""Contrato de ida da esteira de insights: o que o back manda ao N8N (CREED-801).

É o contrato `insight-v1` da spec da CREED-80, seção "Contrato" (P-087). O N8N não
lê este arquivo: lê `docker/n8n/contrato/ida.schema.json`, gerado destes modelos por
`scripts/exportar_contrato_n8n.py`. Mudou um campo aqui, regere o arquivo. O teste
do kit fica vermelho enquanto os dois divergirem.

Os nomes são os do contrato, inclusive os termos da cliente em português
(`destaque`, `oportunidade`, os prismas). Este módulo não conhece domínio: as notas
chegam prontas, e quem as calcula e monta o pedido é o `InsightService` (CREED-803).

Todos os modelos recusam campo a mais (`extra="forbid"`). O que não está no
contrato não sai do back, e o schema exportado diz isso ao N8N com
`additionalProperties: false`. Só existe o escopo `individual` por enquanto: o da
empresa entra na CREED-8013.
"""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.shared.enums import Prisma

# Notas na escala de 0 a 100, a mesma da tela: o texto nunca cita uma escala que a
# pessoa não vê.
Score = Annotated[float, Field(ge=0, le=100)]


class PrismaScores(BaseModel):
    """Nota de cada um dos cinco prismas, de 0 a 100. Os cinco vêm sempre."""

    model_config = ConfigDict(extra="forbid")

    seguranca_psicologica: Score
    lideranca_adaptativa: Score
    cultura_empreendedora: Score
    adaptabilidade_cognitiva: Score
    neuroinovacao_prisma: Score


class DimensionScores(BaseModel):
    """Média de cada uma das sete dimensões da Matriz CREED, de 0 a 100.

    As sete vêm sempre: sem uma delas, o back não calcula os prismas.
    """

    model_config = ConfigDict(extra="forbid")

    S2: Score
    S4: Score
    S5A: Score
    S5B: Score
    S6: Score
    S7: Score
    S8: Score


class InsightResult(BaseModel):
    """O resultado que o texto interpreta, já calculado pelo back.

    `destaque` e `oportunidade` são o prisma de maior e o de menor nota, pela mesma
    regra do dashboard. A IA não decide quais são (princípio 1 do projeto).
    """

    model_config = ConfigDict(extra="forbid")

    prismas: PrismaScores
    dimensions: DimensionScores
    destaque: Prisma = Field(description="Prisma de maior nota.")
    oportunidade: Prisma = Field(description="Prisma de menor nota.")


class OpenAnswer(BaseModel):
    """Uma pergunta descritiva respondida, com o texto como a pessoa escreveu.

    A resposta é dado, nunca instrução: quem monta o prompt a coloca entre
    marcadores (spec da CREED-80, "Segurança na esteira").
    """

    model_config = ConfigDict(extra="forbid")

    section: str = Field(min_length=1, description="Seção do questionário, ex.: S9.")
    question: str = Field(min_length=1, description="Texto da pergunta, em pt-BR.")
    answer: str = Field(min_length=1, description="Resposta, como foi escrita.")


class IndividualInsightRequest(BaseModel):
    """Pedido de insight individual: o resultado de uma resposta enviada.

    Não leva nada que identifique a pessoa (P-091): nem nome, e-mail, documento,
    organização, setor, dado demográfico ou o id da resposta. O `insight_id` é a
    única correlação de que o N8N precisa, e ele volta no callback.
    """

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["insight-v1"]
    scope: Literal["individual"]
    insight_id: uuid.UUID = Field(
        description="Id do pedido. O callback devolve o mesmo valor."
    )
    attempt: int = Field(
        ge=1,
        description="Tentativa de disparo, a partir de 1. Volta igual no callback.",
    )
    language: Literal["pt-BR"] = Field(
        description="Idioma do texto, sempre pt-BR nesta versão (P-092)."
    )
    result: InsightResult
    open_answers: list[OpenAnswer] = Field(
        description="Perguntas descritivas respondidas. Vazia se a pessoa não respondeu."
    )
