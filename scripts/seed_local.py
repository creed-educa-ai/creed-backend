"""Seed do ambiente local: cria o usuário de teste no realm (se faltar) e na tabela
`user`, e um formulário de demonstração para ele responder.

Por que isto existe: depois de o Keycloak aprovar a senha, o login ainda lê o
usuário no **nosso** banco (decisão D2). Realm com usuário e banco vazio dá 401
com a senha certa — que na tela aparece como "e-mail ou senha inválidos" e manda
o time procurar um bug de senha que não existe.

O usuário de teste **não** vem do `realm-creed.json`: o arquivo é público e é o
mesmo que a produção importa (ADR-0007), e lá não pode existir um admin com senha
conhecida. Quem o cria é este seed, que só roda com `ENVIRONMENT=local`.

O `sub` é perguntado ao Keycloak **a cada execução**, nunca fixado aqui: quem
roda `docker compose down -v` ganha um usuário novo no realm (ver README).

    python scripts/seed_local.py
"""

import asyncio
import sys
import uuid
from typing import Any

import httpx

from app import models  # noqa: F401  (registra todas as tabelas; ver app/models.py)
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.domains.forms.models import Form, FormStatus
from app.domains.forms.repository import FormRepository
from app.domains.links.models import Link, LinkType, Roles
from app.domains.links.repository import LinkRepository
from app.domains.participants.models import Participant
from app.domains.participants.repository import ParticipantRepository
from app.domains.questions.models import Question, QuestionSection, QuestionType
from app.domains.questions.repository import QuestionRepository
from app.domains.users.models import User
from app.domains.users.repository import UserRepository
from app.shared.enums import RecordStatus

EMAIL = "dev@creed.example.com"
NAME = "Dev CREED"
# Senha pública de propósito: este usuário só existe no ambiente local.
PASSWORD = "dev"  # noqa: S105

# O papel de acesso é o do vínculo (CREED-32): `user` não guarda papel.
LINK_ROLE = Roles.ADMIN

# Fixos, e não aleatórios, para o seed continuar idempotente. O participante é
# criado por este seed, porque `links.participant_id` tem FK desde a CREED-47. A
# organização segue órfã até `Organization` ter tabela: a CREED-38 precisa criá-la
# com este mesmo id, senão a FK dela não sobe.
PARTICIPANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Formulário de demonstração (CREED-47), na organização do vínculo de dev: é o que
# o `dev` abre, responde e envia. Fica em rascunho, que já pode ser respondido
# (P-030). Id fixo pelo mesmo motivo do participante; as perguntas se reconhecem
# por (formulário, posição), que já é único.
DEMO_FORM_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")
DEMO_FORM_NAME = "[Demonstração] Formulário de teste"

# Texto sintético de propósito: o conteúdo do instrumento é da cliente. Uma por
# seção (P-020), todas descritivas (a objetiva espera a CREED-37). Duas
# obrigatórias e uma opcional, para o envio ser barrado e depois aceito.
# A posição é o índice na lista.
DEMO_QUESTIONS = [
    (
        QuestionSection.PROFILE,
        "[Demonstração] Pergunta de perfil, obrigatória. Escreva qualquer texto.",
        True,
    ),
    (
        QuestionSection.ASSESSMENT,
        "[Demonstração] Pergunta de avaliação, obrigatória. Escreva qualquer texto.",
        True,
    ),
    (
        QuestionSection.CLOSING,
        "[Demonstração] Pergunta de encerramento, opcional. Pode ficar em branco.",
        False,
    ),
]


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
    """O `sub` do usuário de teste, criando-o no realm na primeira vez."""
    keycloak_id = await _buscar_no_realm(http, token)
    if keycloak_id is None:
        keycloak_id = await _criar_no_realm(http, token)
    return keycloak_id


async def _buscar_no_realm(http: httpx.AsyncClient, token: str) -> uuid.UUID | None:
    response = await http.get(
        f"{_admin_url()}/users",
        params={"email": EMAIL, "exact": "true"},
        headers={"Authorization": f"Bearer {token}"},
    )
    if not response.is_success:
        raise SeedError(f"Admin API recusou a consulta: {response.text[:200]}")

    encontrados = response.json()
    if not encontrados:
        return None
    return uuid.UUID(encontrados[0]["id"])


async def _criar_no_realm(http: httpx.AsyncClient, token: str) -> uuid.UUID:
    headers = {"Authorization": f"Bearer {token}"}

    response = await http.post(
        f"{_admin_url()}/users", json=_usuario_de_teste(), headers=headers
    )
    if not response.is_success:
        raise SeedError(f"Admin API recusou criar {EMAIL}: {response.text[:200]}")
    # A Admin API devolve o id do usuário criado só no cabeçalho Location.
    keycloak_id = uuid.UUID(response.headers["Location"].rsplit("/", 1)[-1])

    # O papel vai numa chamada à parte: o POST de usuário ignora `realmRoles`.
    # É a cópia do papel do vínculo (decisão D4) — o mesmo valor do LINK_ROLE.
    papel = await http.get(f"{_admin_url()}/roles/{LINK_ROLE.value}", headers=headers)
    if not papel.is_success:
        raise SeedError(f"Admin API recusou ler o papel: {papel.text[:200]}")
    response = await http.post(
        f"{_admin_url()}/users/{keycloak_id}/role-mappings/realm",
        json=[papel.json()],
        headers=headers,
    )
    if not response.is_success:
        raise SeedError(f"Admin API recusou dar o papel: {response.text[:200]}")

    print(f"{EMAIL} criado no realm, papel {LINK_ROLE.value}.")
    return keycloak_id


def _usuario_de_teste() -> dict[str, Any]:
    """O usuário de teste no formato que a Admin API recebe.

    Sem `requiredActions` vazia e sem `temporary: False`, o Direct Access Grant
    responde `invalid_grant: "Account is not fully set up"` — que na tela vira
    "senha inválida" e manda o time procurar um bug que não existe.
    """
    return {
        "username": EMAIL,
        "email": EMAIL,
        "firstName": "Dev",
        "lastName": "Local",
        "enabled": True,
        "emailVerified": True,
        "requiredActions": [],
        "credentials": [{"type": "password", "value": PASSWORD, "temporary": False}],
    }


def _admin_url() -> str:
    base = settings.KEYCLOAK_SERVER_URL.rstrip("/")
    return f"{base}/admin/realms/{settings.KEYCLOAK_REALM}"


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

        # Antes de tudo, inclusive do `return` abaixo: um banco que já tinha o
        # usuário de dev também precisa do participante, senão a revisão
        # `d53324b9b5a2` recusa o vínculo do seed. E do formulário de demonstração.
        criou_participante = await _ensure_participant(ParticipantRepository(session))
        criou_formulario = await _ensure_demo_form(
            FormRepository(session), QuestionRepository(session)
        )
        if criou_participante or criou_formulario:
            await session.commit()

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


async def _ensure_participant(participants: ParticipantRepository) -> bool:
    """Cria o participante de dev se ele ainda não existe. Diz se criou."""
    if await participants.get_by_id(PARTICIPANT_ID) is not None:
        return False

    await participants.create(
        Participant(id=PARTICIPANT_ID, name=NAME, status=RecordStatus.ACTIVE)
    )
    print(f"participante {PARTICIPANT_ID} criado.")
    return True


async def _ensure_demo_form(forms: FormRepository, questions: QuestionRepository) -> bool:
    """Cria o formulário de demonstração e as perguntas que faltam. Diz se criou."""
    criou = False

    if await forms.get_by_id(DEMO_FORM_ID) is None:
        await forms.create(
            Form(
                id=DEMO_FORM_ID,
                name=DEMO_FORM_NAME,
                organization_id=ORGANIZATION_ID,
                status=FormStatus.DRAFT,
            )
        )
        criou = True

    for order_index, (section, text, required) in enumerate(DEMO_QUESTIONS):
        if await questions.get_by_form_and_order(DEMO_FORM_ID, order_index) is not None:
            continue
        await questions.insert(
            Question(
                form_id=DEMO_FORM_ID,
                text=text,
                order_index=order_index,
                type=QuestionType.DESCRIPTIVE,
                section=section,
                required=required,
                prisma=None,
            )
        )
        criou = True

    situacao = "criado" if criou else "já estava no banco"
    print(f"formulário de demonstração {DEMO_FORM_ID} {situacao}.")
    return criou


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
