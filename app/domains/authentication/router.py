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

router = APIRouter(prefix="/authentication", tags=["authentication"])


@router.post("/login", response_model=SessionResponse)
async def login(data: LoginRequest, service: ServiceDep) -> SessionResponse:
    try:
        return await service.login(data)
    except AuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.message) from exc


@router.post("/renew", response_model=SessionResponse)
async def renew(data: RefreshRequest, service: ServiceDep) -> SessionResponse:
    try:
        return await service.refresh(data.refresh_token)
    except AuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.message) from exc


@router.get("/session", response_model=UserSessionResponse)
async def session(user: CurrentUserDep) -> UserSessionResponse:
    return UserSessionResponse(
        id=user.sub,
        email=user.email or "",
        role=user.roles[0] if user.roles else None,
    )
