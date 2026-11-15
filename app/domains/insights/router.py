"""Endpoints HTTP do domínio insights (ADR-002, secao 2.2).

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao service e
devolve. Duas rotas: a volta do N8N, que a assinatura protege, e a leitura do estado
do insight, que o login protege (CREED-805).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.core.security import verify_n8n_callback
from app.domains.insights.dependencies import MaxAttemptsDep, ServiceDep
from app.domains.insights.schemas import InsightCallback, InsightStatusRead
from app.shared.authorization import CurrentUserDep
from app.shared.exceptions import ForbiddenError, NotFoundError
from app.shared.schemas import ErrorResponse, ValidationErrorResponse

router = APIRouter(tags=["insights"])


@router.post(
    "/insights/callback",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Receber o insight do N8N",
    description=(
        "Rota de volta da esteira de IA: o N8N entrega aqui o texto do insight, ou "
        "avisa que não conseguiu gerá-lo. Não usa o login do Keycloak: quem protege "
        "a rota é a assinatura HMAC-SHA256 do corpo, calculada sobre "
        "`{timestamp}.{corpo}` e enviada nos cabeçalhos `X-Creed-Timestamp` e "
        "`X-Creed-Signature`. O mesmo callback pode ser reenviado sem efeito: o "
        "primeiro texto pronto vence."
    ),
    response_description="Callback aceito; a resposta não possui corpo.",
    operation_id="receive_insight_callback",
    dependencies=[Depends(verify_n8n_callback)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": (
                "Assinatura ausente ou errada, ou timestamp a mais de 5 minutos do "
                "horário do servidor."
            ),
            "content": {
                "application/json": {"example": {"detail": "Assinatura inválida"}}
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "O `insight_id` não é de nenhum insight.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Insight 0b4e1f2a-9c3d-4a5b-8e6f-7d8c9b0a1e2f não encontrado"
                        )
                    }
                }
            },
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ValidationErrorResponse,
            "description": (
                "Corpo fora do contrato `insight-v1`, inclusive um `content` fora do "
                "formato do texto. O insight não muda."
            ),
        },
    },
)
async def receive_insight_callback(
    callback: InsightCallback,
    service: ServiceDep,
    max_attempts: MaxAttemptsDep,
) -> None:
    try:
        await service.complete(callback, max_attempts)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc


@router.get(
    "/form-responses/{form_response_id}/insight",
    response_model=InsightStatusRead,
    summary="Consultar o estado do insight de uma resposta",
    description=(
        "Devolve o estado do insight gerado para uma resposta enviada: `pending` "
        "enquanto o texto está em preparo, `done` com o texto e a data quando ele "
        "fica pronto, e `failed` quando as tentativas se esgotam. Serve ao "
        "polling da tela. Lê o dono da resposta, ou a administradora quando a "
        "resposta é de um mentorando; a gestora não lê o insight individual de "
        "ninguém."
    ),
    response_description="Estado do insight, com o texto quando estiver pronto.",
    operation_id="get_form_response_insight",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Token ausente, inválido ou expirado.",
            "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "A resposta é de outro vínculo, e quem pede não pode lê-la.",
            "content": {
                "application/json": {
                    "example": {"detail": "Sem acesso ao insight de outro respondente"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "A resposta não existe ou ainda não tem insight.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Resposta de formulário 1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed "
                            "não encontrada"
                        )
                    }
                }
            },
        },
    },
)
async def get_form_response_insight(
    form_response_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador da resposta do formulário.",
            examples=["1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed"],
        ),
    ],
    service: ServiceDep,
    user: CurrentUserDep,
) -> InsightStatusRead:
    try:
        return await service.get_status(form_response_id, user=user)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
