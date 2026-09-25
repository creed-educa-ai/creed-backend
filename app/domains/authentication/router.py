"""Endpoints HTTP do domínio authentication"""

from fastapi import APIRouter, HTTPException, status

from app.domains.authentication.dependencies import ServiceDep
from app.domains.authentication.schemas import (
    LoginRequest,
    RefreshRequest,
    SessionResponse,
    UserSessionResponse,
)
from app.shared.authorization import CurrentUserDep
from app.shared.exceptions import AuthenticationError
from app.shared.schemas import ErrorResponse

router = APIRouter(prefix="/authentication", tags=["authentication"])


@router.post(
    "/login",
    response_model=SessionResponse,
    summary="Iniciar sessão",
    description=(
        "Valida e-mail e senha no provedor de identidade e retorna os tokens "
        "necessários para usar a API."
    ),
    response_description="Sessão criada com os tokens e o usuário autenticado.",
    operation_id="login",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "E-mail ou senha inválidos.",
            "content": {
                "application/json": {"example": {"detail": "E-mail ou senha inválidos"}}
            },
        }
    },
)
async def login(data: LoginRequest, service: ServiceDep) -> SessionResponse:
    try:
        return await service.login(data)
    except AuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.message) from exc


@router.post(
    "/renew",
    response_model=SessionResponse,
    summary="Renovar a sessão",
    description=(
        "Troca um refresh token válido por um novo par de tokens sem exigir "
        "as credenciais novamente."
    ),
    response_description="Sessão renovada com um novo par de tokens.",
    operation_id="renew_session",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Refresh token inválido ou expirado.",
            "content": {
                "application/json": {
                    "example": {"detail": "Sessão expirada, faça login novamente"}
                }
            },
        }
    },
)
async def renew(data: RefreshRequest, service: ServiceDep) -> SessionResponse:
    try:
        return await service.refresh(data.refresh_token)
    except AuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.message) from exc


@router.get(
    "/session",
    response_model=UserSessionResponse,
    summary="Consultar a sessão atual",
    description=(
        "Valida o token Bearer, confere o usuário ativo no banco e devolve "
        "a identidade usada pela aplicação."
    ),
    response_description="Dados do usuário autenticado.",
    operation_id="get_current_session",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Token ausente, inválido, expirado ou usuário inativo.",
            "content": {"application/json": {"example": {"detail": "Não autenticado"}}},
        }
    },
)
async def session(user: CurrentUserDep) -> UserSessionResponse:
    return UserSessionResponse(
        id=user.sub,
        email=user.email or "",
        role=user.roles[0] if user.roles else None,
    )
