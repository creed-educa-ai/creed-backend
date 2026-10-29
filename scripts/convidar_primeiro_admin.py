"""Convida o primeiro admin de um ambiente, inclusive produção (CREED-23.8, P-052).

Por que isto existe: o seed (`scripts/seed_local.py`) só roda com `ENVIRONMENT=local`
e cria usuário com senha conhecida. Em produção não existe usuário nenhum, e ninguém
pode nascer com senha conhecida. Este script roda em qualquer ambiente e nunca define
senha: a pessoa recebe o convite por e-mail e define a senha pelo link.

O que ele faz, e pode rodar de novo sem duplicar nada:

1. garante a organização da própria CREED, com id fixo, e o documento dela;
2. se o e-mail já tem acesso ativo, só reenvia o convite;
3. senão, convida como `admin` na organização da CREED, pelo mesmo `MemberService`
   da rota de membros: participante, vínculo e acesso, tudo ou nada (D7).

A transação é do script, como no seed: o commit sai no fim, e só se tudo deu certo.

    python -m scripts.convidar_primeiro_admin --email <e-mail> --nome "<nome>"

Na EC2, em `/opt/creed/creed-infrastructure/ec2`, depois do release e da consolidação
das migrations (CREED-57), por quem tem acesso a ela (ver o README):

    docker compose run --rm --no-deps back python -m scripts.convidar_primeiro_admin \\
        --email <e-mail> --nome "<nome>"
"""

import argparse
import asyncio
import sys
import uuid

import pydantic
from sqlalchemy.ext.asyncio import AsyncSession

from app import models  # noqa: F401  (registra todas as tabelas; ver app/models.py)
from app.core.database import AsyncSessionLocal
from app.domains.documents.models import DocType, Document
from app.domains.documents.repository import DocumentRepository
from app.domains.documents.service import DocumentService
from app.domains.links.repository import LinkRepository
from app.domains.links.service import LinkService
from app.domains.organizacoes.models import Organization
from app.domains.organizacoes.repository import OrganizationRepository
from app.domains.organizacoes.service import OrganizationService
from app.domains.participants.repository import ParticipantRepository
from app.domains.participants.service import ParticipantService
from app.domains.users.repository import UserRepository
from app.domains.users.schemas import MemberInvite
from app.domains.users.service import MemberService, UserService
from app.shared.enums import RecordStatus, Roles
from app.shared.exceptions import ConflictError, DomainError

# 🟡 Premissa P-048 — o admin da plataforma tem o vínculo dele na organização da
# própria CREED, criada uma vez por ambiente, com documento `other` e valor sintético
# até a cliente informar outro. Confirmar na próxima reunião.
# Ids fixos, e não aleatórios, para o script continuar idempotente. Fora da faixa
# dos ids do seed (`...-000000000001` a `...-000000000004`): no ambiente local, as
# duas organizações convivem.
CREED_ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0001-000000000001")
CREED_ORGANIZATION_DOCUMENT_ID = uuid.UUID("00000000-0000-0000-0001-000000000002")
# 🟡 Premissa P-059 — nome e endereço da organização da CREED até a cliente informar
# os dela. O admin corrige pelo `PATCH /organizations/{organization_id}`.
CREED_ORGANIZATION_NAME = "CREED.ai Educa"
CREED_ORGANIZATION_ADDRESS = "[A informar] Endereço da CREED"
# Valor sintético de propósito, com tipo `other`: não pode parecer um CNPJ real.
CREED_ORGANIZATION_DOCUMENT_VALUE = "CREED-ORG-0001"

# Campo do `MemberInvite` -> argumento da linha de comando, para a mensagem de erro.
ARGUMENTS = {"name": "--nome", "email": "--email"}

SPAM_WARNING = (
    "Em produção, avise a pessoa para olhar também a caixa de spam: a conta do Gmail "
    "do projeto é nova, e o primeiro e-mail de teste caiu lá."
)


async def invite_first_admin(
    session: AsyncSession,
    organizations: OrganizationRepository,
    users: UserService,
    members: MemberService,
    invite: MemberInvite,
) -> bool:
    """Convida, ou reenvia o convite. Diz se criou um acesso novo.

    Se algo falha (e-mail no realm sem linha no banco, Keycloak ou SMTP fora do ar),
    o erro sobe sem commit, e o banco volta inteiro, organização inclusive. O que foi
    criado no Keycloak, o `create_user_service` já apagou (D7).
    """
    await _ensure_creed_organization(session, organizations)

    # O banco guarda o e-mail em minúsculas desde o cadastro, e a consulta é exata.
    # Quem digita "Pessoa@..." precisa cair no reenvio, não num 409 do Keycloak.
    email = invite.email.lower()
    access = await users.get_active_user_access_by_email(email)

    if access is not None:
        # 🟡 Premissa P-060 — quem já tem acesso só recebe o convite de novo: o script
        # não muda papel, organização nem status. Acesso inativo não cai aqui, e o
        # convite para no 409 do `create_user_service`. Confirmar na próxima reunião.
        await users.resend_invitation_service(
            access.id, role=Roles.ADMIN.value, own_organization_id=CREED_ORGANIZATION_ID
        )
        await session.commit()
        print(
            f"{email} já tinha acesso, papel {access.role}: convite reenviado, "
            "sem mudar nada no acesso."
        )
        print(SPAM_WARNING)
        return False

    # Quem roda o script age como admin da organização da CREED: o `MemberService`
    # é o da rota de membros, com a mesma regra e o mesmo tudo ou nada.
    created = await members.invite_member_service(
        CREED_ORGANIZATION_ID,
        invite,
        role=Roles.ADMIN.value,
        own_organization_id=CREED_ORGANIZATION_ID,
    )
    await session.commit()
    print(
        f"{created.user.email} criado como {created.role} na organização da CREED: "
        "convite enviado."
    )
    print(SPAM_WARNING)
    return True


async def _ensure_creed_organization(
    session: AsyncSession, organizations: OrganizationRepository
) -> bool:
    """Cria a organização da CREED e o documento dela, o que faltar. Diz se criou.

    A mesma forma do `_ensure_organization` do seed, com outros ids. O documento vai
    direto pela sessão, sem repository: `documents` não tem `create`, porque nenhuma
    rota cria documento (P-022).
    """
    created = False

    if await session.get(Document, CREED_ORGANIZATION_DOCUMENT_ID) is None:
        session.add(
            Document(
                id=CREED_ORGANIZATION_DOCUMENT_ID,
                type=DocType.OTHER,
                value=CREED_ORGANIZATION_DOCUMENT_VALUE,
            )
        )
        await session.flush()
        created = True

    if await organizations.get_by_id(CREED_ORGANIZATION_ID) is None:
        organization = await organizations.create(
            Organization(
                id=CREED_ORGANIZATION_ID,
                name=CREED_ORGANIZATION_NAME,
                address=CREED_ORGANIZATION_ADDRESS,
                document_id=CREED_ORGANIZATION_DOCUMENT_ID,
                status=RecordStatus.ACTIVE,
            )
        )
        # `None`: o documento da CREED já está ligado a outra organização
        # (`uq_organizations_document_id`). O erro sobe antes de qualquer commit e
        # antes do Keycloak, então nada fica gravado.
        if organization is None:
            raise ConflictError(
                f"O documento {CREED_ORGANIZATION_DOCUMENT_ID} da organização da CREED "
                "já pertence a outra organização. Nada foi gravado."
            )
        created = True

    situation = "criada" if created else "já estava no banco"
    print(f"organização da CREED {CREED_ORGANIZATION_ID} {situation}.")
    return created


def parse_invite(argv: list[str]) -> MemberInvite:
    """Lê `--email` e `--nome` e valida como o convite da rota de membros.

    Nenhum dado de pessoa fica no código: e-mail e nome vêm de quem roda o script.
    O papel é sempre `admin`, e o vínculo, `emprego` (P-047).
    """
    parser = argparse.ArgumentParser(
        prog="python -m scripts.convidar_primeiro_admin",
        description="Convida o primeiro admin do ambiente, na organização da CREED.",
    )
    parser.add_argument(
        "--email", required=True, metavar="EMAIL", help="e-mail que recebe o convite"
    )
    parser.add_argument(
        "--nome", required=True, dest="name", metavar="NOME", help="nome da pessoa"
    )
    args = parser.parse_args(argv)

    return MemberInvite(name=args.name, email=args.email, role=Roles.ADMIN)


async def main(invite: MemberInvite) -> None:
    """A mesma cadeia de `dependencies.py`, montada à mão: aqui não há requisição."""
    async with AsyncSessionLocal() as session:
        documents = DocumentService(DocumentRepository(session))
        participants = ParticipantService(ParticipantRepository(session), documents)
        links = LinkService(LinkRepository(session), participants)
        users = UserService(UserRepository(session), links)
        organizations = OrganizationRepository(session)
        members = MemberService(
            users, participants, links, OrganizationService(organizations, documents)
        )

        await invite_first_admin(session, organizations, users, members, invite)


if __name__ == "__main__":
    try:
        invite = parse_invite(sys.argv[1:])
    except pydantic.ValidationError as exc:
        for error in exc.errors():
            # O erro fala do campo do schema; quem roda conhece o argumento.
            field = str(error["loc"][0])
            argument = ARGUMENTS.get(field, field)
            print(f"convidar_primeiro_admin: {argument}: {error['msg']}", file=sys.stderr)
        sys.exit(1)

    try:
        asyncio.run(main(invite))
    except DomainError as exc:
        print(f"convidar_primeiro_admin: {exc.message}", file=sys.stderr)
        sys.exit(1)
