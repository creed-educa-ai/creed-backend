"""Schemas compartilhados pelos contratos HTTP da API."""

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    """Erro HTTP com mensagem legível para quem consome a API."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"detail": "Recurso não encontrado"}]}
    )

    detail: str = Field(description="Motivo pelo qual a requisição não foi atendida.")


class HealthResponse(BaseModel):
    """Estado atual da aplicação e ambiente em execução."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"status": "ok", "environment": "local"}]}
    )

    status: str = Field(description="Estado da aplicação.", examples=["ok"])
    environment: str = Field(
        description="Ambiente em que a aplicação está executando.",
        examples=["local"],
    )
