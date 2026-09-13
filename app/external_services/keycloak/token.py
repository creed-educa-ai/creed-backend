"""Validação de access token do Keycloak (CREED-23, entrega 4).

A chave pública do realm (JWKS) é lida uma vez e guardada em memória pelo TTL de
`KEYCLOAK_JWKS_CACHE_SECONDS`. A chave só muda quando o realm roda as chaves, e
reler a cada requisição poria o Keycloak no caminho crítico de **toda** rota
protegida — uma indisponibilidade dele viraria indisponibilidade da API inteira.

Valida assinatura RS256, `iss`, `aud` e `exp`. O `aud` só é conferível porque o
realm tem um audience mapper explícito no client (ver `realm-creed.json`): sem
ele, o Keycloak emite `aud: ["account"]` num Direct Access Grant e a conferência
não diria nada sobre o destinatário do token.
"""

import time
from typing import Any

import httpx
import jwt

from app.core.config import settings


class InvalidTokenError(Exception):
    """Token inválido"""


class JwksUnavailableError(Exception):
    """Não foi possível ler a chave pública do realm."""


_jwks_cache: dict[str, Any] | None = None
_jwks_carregado_em: float = 0.0


def _jwks_endpoint() -> str:
    base = settings.KEYCLOAK_SERVER_URL.rstrip("/")
    return f"{base}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/certs"


def _issuer() -> str:
    base = settings.KEYCLOAK_SERVER_URL.rstrip("/")
    return f"{base}/realms/{settings.KEYCLOAK_REALM}"


def build_http_client() -> httpx.AsyncClient:
    """Ponto de troca nos testes — em produção é sempre um cliente de verdade."""
    return httpx.AsyncClient(timeout=settings.KEYCLOAK_TIMEOUT_SECONDS)


def reset_cache() -> None:
    """Esvazia o cache do JWKS. Existe para os testes não vazarem chave entre si."""
    global _jwks_cache, _jwks_carregado_em
    _jwks_cache = None
    _jwks_carregado_em = 0.0


async def _get_jwks(*, forcar: bool = False) -> dict[str, Any]:
    global _jwks_cache, _jwks_carregado_em

    vencido = (
        time.monotonic() - _jwks_carregado_em >= settings.KEYCLOAK_JWKS_CACHE_SECONDS
    )
    if _jwks_cache is not None and not vencido and not forcar:
        return _jwks_cache

    try:
        async with build_http_client() as http:
            response = await http.get(_jwks_endpoint())
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise JwksUnavailableError(str(exc)) from exc

    _jwks_cache = dict(response.json())
    _jwks_carregado_em = time.monotonic()
    return _jwks_cache


def _find_key(jwks: dict[str, Any], kid: str) -> Any | None:
    for chave in jwks.get("keys", []):
        if chave.get("kid") == kid:
            return jwt.PyJWK(chave).key
    return None


async def validate_token(token: str) -> dict[str, Any]:
    """Decodifica e valida um access token"""
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(f"Cabeçalho ilegível: {exc}") from exc

    if not kid:
        raise InvalidTokenError("Token sem `kid` no cabeçalho")

    chave = _find_key(await _get_jwks(), kid)

    # `kid` desconhecido normalmente é chave nova: o realm rodou as chaves e o
    # cache ficou velho. Vale uma releitura antes de recusar o token.
    if chave is None:
        chave = _find_key(await _get_jwks(forcar=True), kid)

    if chave is None:
        raise InvalidTokenError(f"Chave `{kid}` não está no JWKS do realm")

    try:
        return dict(
            jwt.decode(
                token,
                key=chave,
                algorithms=["RS256"],
                audience=settings.KEYCLOAK_CLIENT_ID,
                issuer=_issuer(),
            )
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
