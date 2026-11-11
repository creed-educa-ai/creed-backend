"""Endpoints HTTP do domínio prismas (ADR-002, secao 2.2).

Esta camada é fina: valida entrada via Pydantic/FastAPI, delega ao service
e devolve o schema correspondente.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, status

from app.domains.prismas.dependencies import ServiceDep
from app.domains.prismas.schemas import FormResponsePrismasRead
from app.shared.authorization import CurrentUserDep
from app.shared.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.shared.schemas import ErrorResponse

router = APIRouter(prefix="/prismas", tags=["prismas"])

_UNAUTHORIZED: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Token ausente, inválido ou expirado.",
        "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
    },
}


@router.get(
    "/responses/{form_response_id}",
    response_model=FormResponsePrismasRead,
    status_code=status.HTTP_200_OK,
    summary="Consultar prismas de uma resposta de formulário",
    description=(
        "Calcula e retorna as pontuações dos 5 prismas da Matriz CREED e as "
        "médias das 7 dimensões para uma resposta de formulário finalizada. "
        "O respondente consulta a sua própria resposta; o gestor consulta as respostas "
        "da sua organização; o admin consulta qualquer resposta."
    ),
    response_description="Pontuações dos prismas e médias das dimensões calculadas.",
    operation_id="get_form_response_prismas",
    responses={
        **_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": (
                "Sem permissão para acessar o resultado de outro respondente ou "
                "organização."
            ),
            "content": {
                "application/json": {
                    "example": {"detail": "Sem acesso a resposta de outro respondente"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Resposta de formulário não encontrada.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Resposta de formulário "
                            "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed não encontrada"
                        )
                    }
                }
            },
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": (
                "Formulário incompleto ou respostas insuficientes para cálculo."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "O formulário precisa estar finalizado para "
                            "calcular os prismas"
                        )
                    }
                }
            },
        },
    },
)
async def get_form_response_prismas(
    form_response_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador da resposta do formulário.",
            examples=["1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed"],
        ),
    ],
    service: ServiceDep,
    user: CurrentUserDep,
) -> FormResponsePrismasRead:
    try:
        return await service.calculate_for_form_response(form_response_id, user=user)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from exc
