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

from app import models  # noqa: F401  (registra todas as tabelas; ver app/models.py)
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.domains.links.models import Link, LinkType, Roles
from app.domains.links.repository import LinkRepository
from app.domains.users.models import User
from app.domains.users.repository import UserRepository
from app.shared.enums import RecordStatus

EMAIL = "dev@creed.example.com"
NAME = "Dev CREED"

# O papel de acesso é o do vínculo (CREED-32): `user` não guarda papel.
LINK_ROLE = Roles.ADMIN

# Órfãos até a amarração: `Organization` ainda não tem tabela, e `participants`
# tem, mas `links.participant_id` ainda não tem FK para ela. A amarração deve criar
# as duas linhas com estes mesmos ids (spec da CREED-32, "Abordagem técnica",
# item 13). Fixos, e não aleatórios, para o seed continuar idempotente.
PARTICIPANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


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
        users = UserRepository(session)
        links = LinkRepository(session)
        existente = await users.get_user_by_email(EMAIL)

        if existente is not None:
            # Com `user.link_id` NOT NULL o vínculo sempre existe — mas num banco
            # ainda em `87beb54d929a`, que é onde a revisão `28e9a13197f4` para, o
            # usuário pode estar sem ele. O seed não liga mais usuário a vínculo,
            # então falha em vez de dizer que está tudo certo.
            if await links.get_by_id(existente.link_id) is None:
                raise SeedError(
                    f"{EMAIL} está no banco sem vínculo: o schema ainda é o de antes "
                    "da CREED-32/task 6. Rode `alembic upgrade head`, siga a "
                    "mensagem dela e depois rode este seed de novo."
                )

            # Idempotente: rodar de novo depois de um `down -v` só reata o
            # usuário ao `sub` novo, em vez de estourar na constraint única.
            if existente.keycloak_id != keycloak_id:
                print(f"keycloak_id mudou: {existente.keycloak_id} -> {keycloak_id}")
                existente.keycloak_id = keycloak_id
                await session.commit()

            print(f"{EMAIL} já estava no banco, com o vínculo {existente.link_id}.")
            return

        link = await links.insert(_new_link())
        await users.create(
            User(
                keycloak_id=keycloak_id,
                name=NAME,
                email=EMAIL,
                status=RecordStatus.ACTIVE,
                link_id=link.id,
            )
        )
        await session.commit()
        print(
            f"{EMAIL} criado, keycloak_id={keycloak_id}, "
            f"vínculo {link.id} ({LINK_ROLE.value})."
        )


def _new_link() -> Link:
    return Link(
        participant_id=PARTICIPANT_ID,
        organization_id=ORGANIZATION_ID,
        type=LinkType.EMPREGO,
        role=LINK_ROLE,
    )


if __name__ == "__main__":
    try:
        asyncio.run(semear())
    except SeedError as exc:
        print(f"seed: {exc}", file=sys.stderr)
        sys.exit(1)
