"""Endpoints HTTP do domínio forms (ADR-002, secao 2.2).

Esta camada é fina de propósito: recebe, valida via Pydantic, delega ao
service e devolve. Nenhuma regra de negócio aqui, e nenhum import de `models` —
a montagem da resposta é `FormRead.de_model()`, em `schemas.py`.

A guarda decide o papel (`admin` e `gestor` cadastram; qualquer papel lê). A
organização é regra do service (P-033), que recebe de quem pede só o papel e a
organização do vínculo.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.domains.forms.dependencies import ServiceDep
from app.domains.forms.schemas import FormCreate, FormRead
from app.shared.authorization import AuthenticatedUser, CurrentUserDep, require_role
from app.shared.exceptions import ForbiddenError, NotFoundError
from app.shared.schemas import ErrorResponse

router = APIRouter(prefix="/forms", tags=["forms"])

EditorDep = Annotated[AuthenticatedUser, Depends(require_role("admin", "gestor"))]

_UNAUTHORIZED: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Token ausente, inválido ou expirado.",
        "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
    },
}


def _forbidden(description: str) -> dict[int | str, dict[str, Any]]:
    return {
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": description,
            "content": {
                "application/json": {
                    "example": {"detail": "Sem acesso a formulário de outra organização"}
                }
            },
        },
    }


@router.post(
    "",
    response_model=FormRead,
    status_code=status.HTTP_201_CREATED,
    summary="Criar formulário",
    description=(
        "Cria um formulário. O estado inicial é sempre rascunho. Exige o papel "
        "admin ou gestor; o gestor só cadastra na própria organização."
    ),
    response_description="Formulário criado, em rascunho.",
    operation_id="create_form",
    responses={
        **_UNAUTHORIZED,
        **_forbidden(
            "Papel sem permissão para cadastrar, ou gestor cadastrando em outra "
            "organização."
        ),
    },
)
async def create_form(
    dados: FormCreate, service: ServiceDep, user: EditorDep
) -> FormRead:
    try:
        form = await service.create(
            dados, role=user.role, organization_id=user.organization_uuid
        )
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
    return FormRead.de_model(form)


@router.get(
    "/{form_id}",
    response_model=FormRead,
    status_code=status.HTTP_200_OK,
    summary="Consultar formulário",
    description=(
        "Consulta um formulário pelo identificador. Qualquer papel lê os "
        "formulários da própria organização; o admin lê de qualquer uma."
    ),
    response_description="Formulário encontrado.",
    operation_id="get_form",
    responses={
        **_UNAUTHORIZED,
        **_forbidden("O formulário é de outra organização."),
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Formulário não encontrado.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Formulário d40b7a55-b9cc-4b78-ae5d-ab325fd655e2 "
                            "não encontrado"
                        )
                    }
                }
            },
        },
    },
)
async def get_form(
    form_id: Annotated[
        uuid.UUID,
        Path(
            description="Identificador do formulário.",
            examples=["d40b7a55-b9cc-4b78-ae5d-ab325fd655e2"],
        ),
    ],
    service: ServiceDep,
    user: CurrentUserDep,
) -> FormRead:
    try:
        form = await service.get_for_user(
            form_id, role=user.role, organization_id=user.organization_uuid
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message) from exc
    return FormRead.de_model(form)
