"""Schemas compartilhados pelos contratos HTTP da API."""

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    """Erro HTTP com mensagem legível para quem consome a API."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"detail": "Recurso não encontrado"}]}
    )

    detail: str = Field(description="Motivo pelo qual a requisição não foi atendida.")


class ValidationErrorItem(BaseModel):
    """Um campo recusado pela validação do Pydantic."""

    loc: list[str | int] = Field(description="Caminho até o campo recusado.")
    msg: str = Field(description="Motivo da recusa.")
    type: str = Field(description="Código do erro de validação.")


class ValidationErrorResponse(BaseModel):
    """422 gerado pelo FastAPI quando o corpo não passa na validação do schema.

    Mesmo formato do `HTTPValidationError` padrão. Existe para a rota que também
    devolve 422 com `detail` em texto (regra do service) poder documentar os dois
    formatos: `ErrorResponse | ValidationErrorResponse`.
    """

    detail: list[ValidationErrorItem] = Field(description="Um item por campo recusado.")


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
