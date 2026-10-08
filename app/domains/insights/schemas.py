"""Schemas Pydantic do domínio insights.

Separados por direção (ADR-002, secao 2.3): entrada e saída não se contaminam.

A montagem da saída a partir do model mora aqui, em `de_model()`, e não no
router: o schema já conhece a forma do model (`from_attributes=True`), enquanto o
router não pode conhecer (ADR-0004, item 7).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.insights.models import Insight


class InsightCreate(BaseModel):
    """Payload de criação de um bloco de análise."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "form_response_id": "3b1bb89a-471f-48b0-9025-cfda3b20d240",
                    "content": "O time demonstra alta segurança psicológica...",
                }
            ]
        }
    )

    form_response_id: uuid.UUID = Field(
        description="Identificador do formulário respondido que originou a análise.",
        examples=["3b1bb89a-471f-48b0-9025-cfda3b20d240"],
    )
    content: str = Field(description="Texto da análise gerada.")


class InsightResponse(BaseModel):
    """Representação de saída de um bloco de análise."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "0b4e1f2a-9c3d-4a5b-8e6f-7d8c9b0a1e2f",
                    "form_response_id": "3b1bb89a-471f-48b0-9025-cfda3b20d240",
                    "content": "O time demonstra alta segurança psicológica...",
                    "created_at": "2026-10-08T13:30:00Z",
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador da análise.")
    form_response_id: uuid.UUID = Field(
        description="Identificador do formulário respondido que originou a análise."
    )
    content: str = Field(description="Texto da análise gerada.")
    created_at: datetime = Field(description="Data e hora de geração da análise.")

    @classmethod
    def de_model(cls, insight: Insight) -> "InsightResponse":
        """Monta a saída a partir do model."""
        return cls.model_validate(insight)
