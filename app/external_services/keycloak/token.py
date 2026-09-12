"""Validação de access token do Keycloak - TODO"""

from typing import Any


class InvalidTokenError(Exception):
    """Token inválido"""


async def validate_token(token: str) -> dict[str, Any]:
    """Decodifica e valida um access token"""
    raise NotImplementedError
