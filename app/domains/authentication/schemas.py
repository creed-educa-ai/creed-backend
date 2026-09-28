"""Schemas Pydantic do domínio authentication."""

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"email": "usuario@exemplo.com", "password": "senha-exemplo"}]
        }
    )

    email: str = Field(
        min_length=3,
        max_length=320,
        description="E-mail usado para entrar na plataforma.",
        examples=["usuario@exemplo.com"],
    )
    password: str = Field(
        min_length=1,
        description="Senha do usuário no provedor de identidade.",
        examples=["senha-exemplo"],
    )


class RefreshRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"refresh_token": "refresh-token-exemplo"}]}
    )

    refresh_token: str = Field(
        description="Token de renovação retornado no login.",
        examples=["refresh-token-exemplo"],
    )


class UserSessionResponse(BaseModel):
    """Usuário devolvido junto da sessão.

    `vinculo_id`, `organization_id` e `organization_name` ainda não existem. -> None
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "6f8c2e7d-4248-4d30-a8b8-2091c48b06f2",
                    "email": "usuario@exemplo.com",
                    "role": "respondente",
                    "vinculo_id": None,
                    "organization_id": None,
                    "organization_name": None,
                }
            ]
        }
    )

    id: str = Field(description="Identificador interno do usuário.")
    email: str = Field(description="E-mail do usuário autenticado.")
    role: str | None = Field(
        default=None,
        description="Papel efetivo do usuário na plataforma.",
        examples=["respondente"],
    )
    vinculo_id: str | None = Field(
        default=None,
        description="Identificador do vínculo organizacional, quando disponível.",
    )
    organization_id: str | None = Field(
        default=None,
        description="Identificador da organização, quando disponível.",
    )
    organization_name: str | None = Field(
        default=None,
        description="Nome da organização, quando disponível.",
    )


class SessionResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "access_token": "access-token-exemplo",
                    "refresh_token": "refresh-token-exemplo",
                    "expires_in": 900,
                    "user": {
                        "id": "6f8c2e7d-4248-4d30-a8b8-2091c48b06f2",
                        "email": "usuario@exemplo.com",
                        "role": "respondente",
                        "vinculo_id": None,
                        "organization_id": None,
                        "organization_name": None,
                    },
                }
            ]
        }
    )

    access_token: str = Field(
        description="Token JWT usado no cabeçalho Authorization.",
        examples=["access-token-exemplo"],
    )
    refresh_token: str = Field(
        description="Token usado para renovar a sessão.",
        examples=["refresh-token-exemplo"],
    )
    expires_in: int = Field(
        description="Tempo de validade do access token, em segundos.",
        examples=[900],
    )
    user: UserSessionResponse = Field(description="Dados do usuário associados à sessão.")
