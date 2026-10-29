"""Cliente do token endpoint do Keycloak (CREED-23, decisão D1).

O backend é um confidential client e **intermedeia** o login: o front nunca fala
com o Keycloak. Toda troca acontece aqui, por Direct Access Grant — que é o que
a D1 escolheu e o que o realm habilita (`directAccessGrantsEnabled`).

Este módulo não conhece HTTP status da nossa API nem regra de negócio: ele só
sabe distinguir "credencial recusada" de "Keycloak fora do ar". Quem traduz para
401 ou 503 é o service, e depois o router.
"""

from typing import Any

import httpx

from app.core.config import settings


class KeycloakUnavailableError(Exception):
    """Keycloak não respondeu, ou respondeu com erro que não é credencial errada."""


class InvalidCredentialsError(Exception):
    """Usuário/senha errados"""


def _token_endpoint() -> str:
    base = settings.KEYCLOAK_SERVER_URL.rstrip("/")
    return f"{base}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"


def build_http_client() -> httpx.AsyncClient:
    """Ponto de troca nos testes — em produção é sempre um cliente de verdade."""
    return httpx.AsyncClient(timeout=settings.KEYCLOAK_TIMEOUT_SECONDS)


async def _post_token(form: dict[str, str]) -> dict[str, Any]:
    payload = {
        "client_id": settings.KEYCLOAK_CLIENT_ID,
        "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
        **form,
    }

    try:
        async with build_http_client() as http:
            response = await http.post(_token_endpoint(), data=payload)
    except httpx.HTTPError as exc:
        # Timeout, DNS, recusa de conexão: o Keycloak não respondeu.
        raise KeycloakUnavailableError(str(exc)) from exc

    # O token endpoint responde 400 `invalid_grant` para senha errada, usuário
    # inexistente, refresh token expirado e conta desabilitada — todos são
    # "credencial não serve", e o service devolve a MESMA mensagem para os
    # quatro, para não vazar se o e-mail existe (critério de aceite da 23.4).
    if response.status_code in (400, 401):
        raise InvalidCredentialsError(_describe(response))

    if not response.is_success:
        raise KeycloakUnavailableError(_describe(response))

    return dict(response.json())


def _describe(response: httpx.Response) -> str:
    """Mensagem para log. Nunca chega ao usuário: o service usa texto fixo."""
    return f"{response.status_code} {response.text[:200]}"


async def login(email: str, password: str) -> dict[str, Any]:
    """Troca e-mail e senha por um par de tokens"""
    return await _post_token(
        {
            "grant_type": "password",
            "username": email,
            "password": password,
            "scope": "openid",
        }
    )


async def refresh(refresh_token: str) -> dict[str, Any]:
    """Troca um refresh token por uma sessão nova"""
    return await _post_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    )
