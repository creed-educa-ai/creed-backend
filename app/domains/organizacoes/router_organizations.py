"""Endpoints HTTP do ciclo da empresa em `/organizations` (CREED-69, E-2 e E-6).

Segundo router do domínio, como `links/router_members.py` é o de `links`. Existe
porque as rotas novas de organização usam o prefixo em inglês, que o ADR-0005 manda
para todo identificador novo, e o `router.py` responde em `/organizacoes`, contrato
que o front já consome e que o ADR-0005 não renomeia. A aprovação de empresa entra
neste mesmo arquivo.

O cadastro (`/sign-up`) é público, como o login: não tem `require_role` e não olha
o token.

A exclusão (`DELETE /{organization_id}`) delega ao `OrganizationRemovalService`, de
`users`, e não ao `OrganizationService`: ela apaga também os membros e os logins
deles, e quem compõe com `users` sem import circular é o próprio `users` (ver a
docstring de `users/service.py`). É o caminho da exclusão de membro em
`links/router_members.py`.

Camada fina de propósito: recebe, valida via Pydantic, delega ao service e devolve.
Nenhuma regra de negócio aqui, e nenhum import de `models` — a resposta é a mesma
`OrganizationResponse` do `router.py`, com o documento juntado por
`service.with_documents`.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.domains.organizacoes.dependencies import ServiceDep
from app.domains.organizacoes.schemas import OrganizationResponse, OrganizationSignUp
from app.domains.organizacoes.service import OrganizationWithDocument
from app.domains.users.dependencies import OrganizationRemovalServiceDep
from app.shared.authorization import AuthenticatedUser, require_role
from app.shared.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.shared.schemas import ErrorResponse, ValidationErrorResponse

router = APIRouter(prefix="/organizations", tags=["organizacoes"])

# 🟡 Premissa P-079 — excluir empresa é só do `admin`. Esta guarda é o único 403 da
# rota: o service não confere o papel.
AdminDep = Annotated[AuthenticatedUser, Depends(require_role("admin"))]


def _response(item: OrganizationWithDocument) -> OrganizationResponse:
    return OrganizationResponse.de_model(
        item.organization, item.document_type, item.document_value
    )


@router.post(
    "/sign-up",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastrar a própria empresa",
    description=(
        "Cadastro público, sem login: cria o documento e a organização numa chamada "
        "só. A organização nasce `pending`, com o endereço `[A informar]`, e espera a "
        "aprovação da administradora. O documento chega com ou sem pontuação e é "
        "guardado só com os dígitos: 11 é CPF, 14 é CNPJ. O e-mail é gravado em "
        "minúsculas. Se qualquer gravação falhar, nada é criado."
    ),
    response_description="Empresa cadastrada, pendente de aprovação.",
    operation_id="sign_up_organization",
    responses={
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": (
                "Já existe documento com o mesmo tipo e número, com ou sem pontuação "
                "no pedido. Nada é criado."
            ),
            "content": {
                "application/json": {
                    "example": {"detail": "Já existe um cadastro com este documento"}
                }
            },
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ValidationErrorResponse,
            "description": (
                "Campo ausente, vazio ou longo demais, caractere de controle no nome, "
                "no responsável ou no telefone, e-mail mal formado, responsável com "
                "menos de 2 caracteres, ou documento que não tem 11 nem 14 dígitos. "
                "`detail` é uma lista, um item por campo recusado."
            ),
        },
    },
)
async def sign_up_organization(
    dados: OrganizationSignUp, service: ServiceDep
) -> OrganizationResponse:
    try:
        organization = await service.sign_up(dados)
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    (item,) = await service.with_documents([organization])
    return _response(item)


_DELETE_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Token ausente, inválido ou expirado.",
        "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
    },
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": (
            "O usuário autenticado não tem o papel admin. Conferido antes da busca: "
            "a resposta não revela se a organização existe."
        ),
        "content": {
            "application/json": {"example": {"detail": "Cargo insuficiente para acessar"}}
        },
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "Organização não encontrada.",
        "content": {
            "application/json": {
                "example": {
                    "detail": (
                        "Organização 8f14e45f-ceea-467e-adde-3f81905dbc1c não encontrada"
                    )
                }
            }
        },
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": (
            "A organização é a do próprio vínculo de quem pede: ninguém exclui a "
            "própria organização. Nada é apagado."
        ),
        "content": {
            "application/json": {
                "example": {"detail": "Não é possível excluir a própria organização"}
            }
        },
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": (
            "O Keycloak não respondeu ao apagar os logins dos membros. Nada foi "
            "apagado no banco, e a mesma chamada pode ser repetida."
        ),
        "content": {
            "application/json": {
                "example": {
                    "detail": "Não foi possível remover o acesso agora. Tente de novo."
                }
            }
        },
    },
}


@router.delete(
    "/{organization_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Excluir ou rejeitar uma empresa",
    description=(
        "Exclui a empresa de vez, e não há como desfazer. Saem cada membro, como na "
        "exclusão de membro (respostas, questionários individuais, vínculo e, sem "
        "vínculo com outra organização, o participante), os questionários da "
        "organização com as respostas, os setores, a organização, o documento dela "
        "(se nenhum participante usar o mesmo) e, por último, os logins dos membros "
        "no Keycloak. Rejeitar um cadastro `pending` é esta mesma rota: sem membros, "
        "saem só a organização e o documento, que pode se cadastrar de novo. Exige o "
        "papel admin, que não exclui a organização do próprio vínculo."
    ),
    response_description="Empresa excluída; a resposta não possui corpo.",
    operation_id="delete_organization",
    responses=_DELETE_ERRORS,
)
async def delete_organization(
    organization_id: Annotated[
        uuid.UUID,
        Path(
            description="Organização a excluir.",
            examples=["8f14e45f-ceea-467e-adde-3f81905dbc1c"],
        ),
    ],
    service: OrganizationRemovalServiceDep,
    user: AdminDep,
) -> None:
    try:
        await service.remove_organization(
            organization_id, own_organization_id=user.organization_uuid
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, exc.message) from exc
