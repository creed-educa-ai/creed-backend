"""Cliente da Admin API do Keycloak (CREED-23.8, decisão D9).

É por aqui que o back cria o acesso no realm, dá o papel, manda o e-mail de convite
e apaga o acesso. Quem fala com a Admin API é o service account do próprio client
(`creed-backend`), que o realm já deixa `manage-users` e `view-realm`.

Cada função pública é uma operação: abre um cliente HTTP, pede um token do service
account e faz as chamadas que a operação precisa com ele. Não há cache de token
entre operações: o volume de convites não justifica guardar estado (spec, D9).

Como em `client.py`, este módulo não conhece regra de negócio nem status da nossa
API. Ele só distingue três saídas: deu certo, "já existe" (`KeycloakConflictError`)
e "o Keycloak não fez o que pedimos" (`KeycloakUnavailableError`). O service decide
o que cada uma vira.
"""

import logging
import uuid
from typing import Any

import httpx

from app.core.config import settings
from app.external_services.keycloak.client import KeycloakUnavailableError

logger = logging.getLogger(__name__)


class KeycloakConflictError(Exception):
    """Já existe usuário no realm com este e-mail."""


def build_http_client() -> httpx.AsyncClient:
    """Ponto de troca nos testes — em produção é sempre um cliente de verdade."""
    return httpx.AsyncClient(timeout=settings.KEYCLOAK_TIMEOUT_SECONDS)


def _admin_url() -> str:
    base = settings.KEYCLOAK_SERVER_URL.rstrip("/")
    return f"{base}/admin/realms/{settings.KEYCLOAK_REALM}"


def _token_endpoint() -> str:
    base = settings.KEYCLOAK_SERVER_URL.rstrip("/")
    return f"{base}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"


def _unexpected(action: str, response: httpx.Response) -> KeycloakUnavailableError:
    """Resposta fora da esperada. O corpo vai para o log, nunca para o usuário."""
    detail = f"{action}: {response.status_code} {response.text[:200]}"
    logger.error("Admin API do Keycloak recusou %s", detail)
    return KeycloakUnavailableError(detail)


async def _send(
    http: httpx.AsyncClient, method: str, url: str, **kwargs: Any
) -> httpx.Response:
    """Uma requisição ao Keycloak. Sem resposta, é indisponível."""
    try:
        return await http.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        # Timeout, DNS, recusa de conexão: o Keycloak não respondeu. O `repr` guarda
        # o tipo do erro, porque o texto de um timeout do httpx vem vazio.
        detail = f"{method} {url}: {exc!r}"
        logger.error("Admin API do Keycloak não respondeu: %s", detail)
        raise KeycloakUnavailableError(detail) from exc


async def _service_account_token(http: httpx.AsyncClient) -> str:
    response = await _send(
        http,
        "POST",
        _token_endpoint(),
        data={
            "client_id": settings.KEYCLOAK_CLIENT_ID,
            "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
    )
    # Segredo errado aqui não é credencial de usuário: é o back mal configurado.
    # Para quem pediu o cadastro, o efeito é o mesmo de o Keycloak estar fora.
    if not response.is_success:
        raise _unexpected("emitir o token do service account", response)

    # Um 200 sem JSON ou sem o token (um proxy no meio, por exemplo) é tão inesperado
    # quanto um 500. Escapar como ValueError ou KeyError trocaria, na compensação do
    # service, o erro original e o id que vai para o log.
    try:
        return str(response.json()["access_token"])
    except (ValueError, KeyError, TypeError) as exc:
        raise _unexpected("ler o token do service account", response) from exc


async def _call(
    http: httpx.AsyncClient, token: str, method: str, path: str, **kwargs: Any
) -> httpx.Response:
    """Uma chamada à Admin API, com o token da operação."""
    return await _send(
        http,
        method,
        f"{_admin_url()}{path}",
        headers={"Authorization": f"Bearer {token}"},
        **kwargs,
    )


async def create_user(email: str) -> uuid.UUID:
    """Cria o usuário sem senha e devolve o id dele no realm (o `sub` do JWT).

    Sem `credentials`: a pessoa define a senha pelo link do convite. Sem nome: o
    Keycloak guarda credencial, não cadastro, e o perfil do realm não exige nome.
    🟡 Premissa P-046 — o Keycloak não recebe nome. Confirmar na próxima reunião.

    `requiredActions` vazia de propósito: a troca de senha é pedida pelo e-mail
    (`send_update_password_email`), não deixada pendente no login.
    """
    async with build_http_client() as http:
        token = await _service_account_token(http)
        response = await _call(
            http,
            token,
            "POST",
            "/users",
            json={
                "username": email,
                "email": email,
                "enabled": True,
                "requiredActions": [],
            },
        )

    if response.status_code == 409:
        raise KeycloakConflictError(f"{response.status_code} {response.text[:200]}")
    if not response.is_success:
        raise _unexpected("criar o usuário", response)

    # A Admin API devolve o id do usuário criado só no cabeçalho Location.
    location = response.headers.get("Location", "")
    try:
        return uuid.UUID(location.rsplit("/", 1)[-1])
    except ValueError as exc:
        raise _unexpected(f"criar o usuário (Location {location!r})", response) from exc


async def assign_realm_role(keycloak_id: uuid.UUID, role: str) -> None:
    """Dá a realm role ao usuário. É a cópia do papel do vínculo que o token carrega.

    São duas chamadas, com o mesmo token, porque o POST de usuário ignora
    `realmRoles`: a Admin API pede a representação inteira do papel, lida antes.
    """
    async with build_http_client() as http:
        token = await _service_account_token(http)

        role_response = await _call(http, token, "GET", f"/roles/{role}")
        if not role_response.is_success:
            raise _unexpected(f"ler o papel {role}", role_response)
        try:
            role_representation = role_response.json()
        except ValueError as exc:
            raise _unexpected(f"ler o papel {role}", role_response) from exc

        response = await _call(
            http,
            token,
            "POST",
            f"/users/{keycloak_id}/role-mappings/realm",
            json=[role_representation],
        )

    if not response.is_success:
        raise _unexpected(f"dar o papel {role}", response)


async def send_update_password_email(keycloak_id: uuid.UUID) -> None:
    """Manda o e-mail com o link para a pessoa definir a senha.

    É o mesmo e-mail no convite e na redefinição de senha. Quem fala SMTP é o
    Keycloak: se o servidor de e-mail falhar, a Admin API responde erro aqui.
    """
    # 🟡 Premissa P-049 — o link vale 72 h. Confirmar na próxima reunião.
    params: dict[str, str | int] = {
        "lifespan": settings.KEYCLOAK_INVITE_LIFESPAN_SECONDS,
    }

    # 🟡 Premissa P-051 — a pessoa volta ao login da plataforma por um link, sem
    # login automático. Confirmar na próxima reunião. `FRONTEND_URL` vazia desliga
    # o link. O `rstrip` evita o "//login" de quem escreve a URL com barra no fim.
    frontend_url = settings.FRONTEND_URL.rstrip("/")
    if frontend_url:
        params["client_id"] = settings.KEYCLOAK_CLIENT_ID
        params["redirect_uri"] = f"{frontend_url}/login"

    async with build_http_client() as http:
        token = await _service_account_token(http)
        response = await _call(
            http,
            token,
            "PUT",
            f"/users/{keycloak_id}/execute-actions-email",
            params=params,
            json=["UPDATE_PASSWORD"],
        )

    if not response.is_success:
        raise _unexpected("mandar o e-mail de definição de senha", response)


async def delete_user(keycloak_id: uuid.UUID) -> None:
    """Apaga o usuário do realm. Já não existir também é sucesso."""
    async with build_http_client() as http:
        token = await _service_account_token(http)
        response = await _call(http, token, "DELETE", f"/users/{keycloak_id}")

    if response.status_code == 404:
        return
    if not response.is_success:
        raise _unexpected("apagar o usuário", response)
