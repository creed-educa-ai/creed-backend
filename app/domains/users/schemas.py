"""Schemas Pydantic do domínio respondentes.

Separados por direção (ADR-002, secao 2.3): entrada e saída não se contaminam.
"""

import uuid

from pydantic import BaseModel, Field


class UserBase(BaseModel):
    """Payload base de User."""

    id: uuid.UUID
    link_id: uuid.UUID
    email: str = Field(min_length=2, max_length=200)
    status: bool


class UserResponse(UserBase):
    """Representação de saída base de User."""

    id: uuid.UUID
    link_id: uuid.UUID
    email: str = Field(min_length=2, max_length=200)
    status: bool


class UserCreate(UserBase):
    """Representação de criação de User."""

    email: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=2, max_length=200)
