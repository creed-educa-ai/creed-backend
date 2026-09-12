import uuid

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    """Representação de criação de User."""

    email: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=2, max_length=200)


class UserResponse(BaseModel):
    """Representação de saída de User."""

    id: uuid.UUID
    # link_id: uuid.UUID
    email: str = Field(min_length=2, max_length=200)
    status: bool


class UserDelete(BaseModel):
    """Representação de delete de User."""

    id: uuid.UUID
