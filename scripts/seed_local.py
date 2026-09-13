"""Seed do ambiente local: põe o usuário de teste do realm na tabela `user`.

Por que isto existe: depois de o Keycloak aprovar a senha, o login ainda lê o
usuário no **nosso** banco (decisão D2). Realm com usuário e banco vazio dá 401
com a senha certa — que na tela aparece como "e-mail ou senha inválidos" e manda
o time procurar um bug de senha que não existe.

O `sub` é perguntado ao Keycloak **a cada execução**, nunca fixado aqui: quem
roda `docker compose down -v` ganha um usuário novo no realm (ver README).

    python scripts/seed_local.py
"""

import asyncio
import sys
import uuid

import httpx

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.domains.users.models import RecordStatus, User, UserRole
from app.domains.users.repository import UserRepository

EMAIL = "dev@creed.example.com"
NAME = "Dev CREED"
ROLE = UserRole.ADMIN


class SeedError(Exception):
    """Faltou algo no ambiente para o seed poder rodar."""


async def _service_account_token(http: httpx.AsyncClient) -> str:
    """Token do próprio backend. O realm já dá `manage-users` a ele (entrega 2)."""
    base = settings.KEYCLOAK_SERVER_URL.rstrip("/")
    response = await http.post(
        f"{base}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token",
        data={
            "client_id": settings.KEYCLOAK_CLIENT_ID,
            "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
    )
    if not response.is_success:
        raise SeedError(f"Keycloak recusou o service account: {response.text[:200]}")
    return str(response.json()["access_token"])


async def _keycloak_id(http: httpx.AsyncClient, token: str) -> uuid.UUID:
    base = settings.KEYCLOAK_SERVER_URL.rstrip("/")
    response = await http.get(
        f"{base}/admin/realms/{settings.KEYCLOAK_REALM}/users",
        params={"email": EMAIL, "exact": "true"},
        headers={"Authorization": f"Bearer {token}"},
    )
    if not response.is_success:
        raise SeedError(f"Admin API recusou a consulta: {response.text[:200]}")

    encontrados = response.json()
    if not encontrados:
        raise SeedError(
            f"{EMAIL} não existe no realm '{settings.KEYCLOAK_REALM}'. "
            "O realm subiu a partir de docker/keycloak/realm-creed.json?"
        )
    return uuid.UUID(encontrados[0]["id"])


async def semear() -> None:
    if settings.ENVIRONMENT != "local":
        raise SeedError(
            f"ENVIRONMENT={settings.ENVIRONMENT}. Este seed é só do ambiente local."
        )

    async with httpx.AsyncClient(timeout=settings.KEYCLOAK_TIMEOUT_SECONDS) as http:
        token = await _service_account_token(http)
        keycloak_id = await _keycloak_id(http, token)

    async with AsyncSessionLocal() as session:
        repository = UserRepository(session)
        existente = await repository.get_user_by_email(EMAIL)

        if existente is not None:
            # Idempotente: rodar de novo depois de um `down -v` só reata o
            # usuário ao `sub` novo, em vez de estourar na constraint única.
            if existente.keycloak_id != keycloak_id:
                print(f"keycloak_id mudou: {existente.keycloak_id} -> {keycloak_id}")
                existente.keycloak_id = keycloak_id
                await session.commit()
            print(f"{EMAIL} já estava no banco ({existente.role.value}).")
            return

        await repository.create(
            User(
                keycloak_id=keycloak_id,
                name=NAME,
                email=EMAIL,
                status=RecordStatus.ACTIVE,
                role=ROLE,
            )
        )
        await session.commit()
        print(f"{EMAIL} criado ({ROLE.value}), keycloak_id={keycloak_id}.")


if __name__ == "__main__":
    try:
        asyncio.run(semear())
    except SeedError as exc:
        print(f"seed: {exc}", file=sys.stderr)
        sys.exit(1)
