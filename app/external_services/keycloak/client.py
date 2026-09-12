"""Cliente do endpoint de token do Keycloak - TODO"""

from typing import Any


class KeycloakUnavailableError(Exception):
    """Keycloak não respondeu, ou respondeu com erro que não é credencial errada."""


class InvalidCredentialsError(Exception):
    """Usuário/senha errados"""


async def login(email: str, password: str) -> dict[str, Any]:
    """Troca e-mail e senha por um par de tokens"""
    raise NotImplementedError


async def refresh(refresh_token: str) -> dict[str, Any]:
    """Troca um refresh token por uma sessão nova"""
    raise NotImplementedError
