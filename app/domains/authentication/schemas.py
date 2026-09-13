"""Schemas Pydantic do domínio authentication."""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str


class UserSessionResponse(BaseModel):
    """Usuário devolvido junto da sessão.

    `vinculo_id`, `organization_id` e `organization_name` ainda não existem. -> None
    """

    id: str
    email: str
    role: str | None = None
    vinculo_id: str | None = None
    organization_id: str | None = None
    organization_name: str | None = None


class SessionResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    user: UserSessionResponse
