"""Endpoints HTTP do domínio participants (ADR-0004).

Camada fina: recebe, valida via Pydantic, delega ao service e devolve. Nenhuma
regra de negócio aqui, e nenhum import de `models`.

🟡 Premissa P-015 — só `admin` cadastra e consulta participante nesta entrega.
Confirmar na próxima reunião.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.domains.participants.dependencies import ServiceDep
from app.domains.participants.schemas import ParticipantCreate, ParticipantResponse
from app.shared.authorization import require_role
from app.shared.exceptions import ConflictError, NotFoundError, ValidationError
from app.shared.schemas import ErrorResponse

router = APIRouter(prefix="/participants", tags=["participants"])

# 401 e 403 vêm da guarda `require_role`, igual nas duas rotas.
_AUTH_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Token ausente, inválido ou expirado.",
        "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
    },
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": "O usuário autenticado não tem o papel admin.",
        "content": {
            "application/json": {"example": {"detail": "Cargo insuficiente para acessar"}}
        },
    },
}


@router.post(
    "",
    response_model=ParticipantResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("admin"))],
    summary="Cadastrar participante",
    description=(
        "Cadastra uma pessoa na plataforma. O participante nasce ativo. "
        "O documento é opcional; se vier, precisa já existir e não pode estar "
        "ligado a outro participante. Exige o papel admin."
    ),
    response_description="Participante cadastrado.",
    operation_id="create_participant",
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "O documento informado já pertence a outro participante.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "O documento 3b2f8c1a-6d4e-4f7a-9c5b-1e0d2a8f6b94 "
                            "já pertence a outro participante"
                        )
                    }
                }
            },
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": (
                "Nome inválido, `document_id` malformado ou documento inexistente."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Documento 3b2f8c1a-6d4e-4f7a-9c5b-1e0d2a8f6b94 "
                            "não encontrado"
                        )
                    }
                }
            },
        },
    },
)
async def create_participant(
    dados: ParticipantCreate, service: ServiceDep
) -> ParticipantResponse:
    try:
        return ParticipantResponse.de_model(await service.create_participant(dados))
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc


@router.get(
    "/{participant_id}",
    response_model=ParticipantResponse,
    dependencies=[Depends(require_role("admin"))],
    summary="Consultar participante",
    description="Devolve um participante pelo identificador. Exige o papel admin.",
    response_description="Participante encontrado.",
    operation_id="get_participant",
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Participante não encontrado.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Participante 7f9c2b1e-4a3d-4c8e-9b6f-2d1e0a5c8b73 "
                            "não encontrado"
                        )
                    }
                }
            },
        },
    },
)
async def get_participant(
    participant_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador do participante.",
            examples=["7f9c2b1e-4a3d-4c8e-9b6f-2d1e0a5c8b73"],
        ),
    ],
    service: ServiceDep,
) -> ParticipantResponse:
    try:
        return ParticipantResponse.de_model(await service.get_participant(participant_id))
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
