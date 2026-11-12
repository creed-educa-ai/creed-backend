"""Endpoints HTTP do domínio authentication"""

from fastapi import APIRouter, HTTPException, status

from app.domains.authentication.dependencies import ServiceDep
from app.domains.authentication.schemas import (
    LoginRequest,
    PasswordResetRequest,
    RefreshRequest,
    SessionResponse,
    UserSessionResponse,
)
from app.shared.authorization import CurrentUserDep
from app.shared.exceptions import AuthenticationError, ServiceUnavailableError
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
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": "O provedor de identidade não respondeu.",
            "content": {
                "application/json": {
                    "example": {"detail": "Não foi possível autenticar agora"}
                }
            },
        },
    },
)
async def login(data: LoginRequest, service: ServiceDep) -> SessionResponse:
    try:
        return await service.login(data)
    except AuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.message) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, exc.message) from exc


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
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": "O provedor de identidade não respondeu.",
            "content": {
                "application/json": {
                    "example": {"detail": "Não foi possível renovar a sessão agora"}
                }
            },
        },
    },
)
async def renew(data: RefreshRequest, service: ServiceDep) -> SessionResponse:
    try:
        return await service.refresh(data.refresh_token)
    except AuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.message) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, exc.message) from exc


@router.post(
    "/password-reset",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Pedir redefinição de senha",
    description=(
        "Se o e-mail tem acesso ativo, envia para ele o e-mail com o link para "
        "definir uma senha nova, o mesmo do convite. Para e-mail sem acesso, ou de "
        "acesso inativo, não envia nada, e o status e o corpo da resposta são os "
        "mesmos: a resposta não revela quem tem cadastro. O e-mail é comparado sem "
        "distinguir maiúsculas. Não exige login."
    ),
    response_description=(
        "Pedido recebido; a resposta não possui corpo e é a mesma para qualquer e-mail."
    ),
    operation_id="request_password_reset",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": (
                "O provedor de identidade ou o envio de e-mail não respondeu. Se o "
                "provedor demorar, o e-mail pode ter saído mesmo assim."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Não foi possível enviar o e-mail de redefinição agora. "
                            "Tente de novo."
                        )
                    }
                }
            },
        },
    },
)
async def password_reset(data: PasswordResetRequest, service: ServiceDep) -> None:
    try:
        await service.request_password_reset(data.email)
    except ServiceUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, exc.message) from exc


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
        link_id=user.link_id,
        organization_id=user.organization_id,
    )
