"""Seed do ambiente local: as organizações e as pessoas de teste, no realm (se
faltarem) e no nosso banco.

Por que isto existe: depois de o Keycloak aprovar a senha, o login ainda lê o
usuário no **nosso** banco (decisão D2). Realm com usuário e banco vazio dá 401
com a senha certa — que na tela aparece como "e-mail ou senha inválidos" e manda
o time procurar um bug de senha que não existe.

As pessoas de teste **não** vêm do `realm-creed.json`: o arquivo é público e é o
mesmo que a produção importa (ADR-0007), e lá não pode existir um admin com senha
conhecida. Quem as cria é este seed, que só roda com `ENVIRONMENT=local`.

O ambiente fica como o de produção: a admin na organização da CREED, onde também
estão os mentorandos (P-048), e as empresas com os seus membros. **Nenhum período**
nasce aqui: quem abre é o gestor ou a admin, pelo painel, como em produção. As
perguntas também não: são do instrumento CREED, que entra por migration de dados.

O `sub` é perguntado ao Keycloak **a cada execução**, nunca fixado aqui: quem
roda `docker compose down -v` ganha usuários novos no realm (ver README).

    python scripts/seed_local.py
"""

import asyncio
import sys
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models  # noqa: F401  (registra todas as tabelas; ver app/models.py)
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.domains.documents.models import DocType, Document
from app.domains.forms.models import Form
from app.domains.links.models import Link
from app.domains.links.repository import LinkRepository
from app.domains.organizacoes.models import Organization, OrganizationStatus
from app.domains.organizacoes.repository import OrganizationRepository
from app.domains.participants.models import Participant
from app.domains.participants.repository import ParticipantRepository
from app.domains.responses.models import Answer, FormResponse
from app.domains.users.models import User
from app.domains.users.repository import UserRepository
from app.shared.enums import LinkType, RecordStatus, Roles

# Senha pública de propósito, a mesma para todas as pessoas de teste: elas só
# existem no ambiente local. Tem 8 caracteres ou mais porque a política do realm
# (`length(8)`, P-004 de 07/09) faz a Admin API recusar a criação com senha mais curta.
PASSWORD = "dev-creed"  # noqa: S105


@dataclass(frozen=True)
class OrganizacaoDeTeste:
    id: uuid.UUID
    document_id: uuid.UUID
    # Valor sintético de propósito, com tipo `other`: não pode parecer um CNPJ real.
    document_value: str
    name: str
    address: str


@dataclass(frozen=True)
class PessoaDeTeste:
    email: str
    name: str
    # O papel de acesso é o do vínculo (CREED-32): `user` não guarda papel.
    role: Roles
    type: LinkType
    organization_id: uuid.UUID
    participant_id: uuid.UUID


# Os mesmos ids do `scripts/convidar_primeiro_admin.py`, que cria esta organização
# nos outros ambientes: no local, a admin do seed fica onde a de produção fica.
CREED = OrganizacaoDeTeste(
    id=uuid.UUID("00000000-0000-0000-0001-000000000001"),
    document_id=uuid.UUID("00000000-0000-0000-0001-000000000002"),
    document_value="CREED-ORG-0001",
    name="CREED.ai Educa",
    address="[A informar] Endereço da CREED",
)

# Ids fixos, e não aleatórios, para o seed continuar idempotente. A empresa de
# demonstração mantém os ids de antes, para bancos já semeados.
EMPRESA = OrganizacaoDeTeste(
    id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
    document_id=uuid.UUID("00000000-0000-0000-0000-000000000004"),
    document_value="DEMO-ORG-0001",
    name="[Demonstração] Organização de dev",
    address="[Demonstração] Endereço de teste",
)
# Uma segunda empresa, para conferir que uma não vê o período da outra.
OUTRA_EMPRESA = OrganizacaoDeTeste(
    id=uuid.UUID("00000000-0000-0000-0000-000000000005"),
    document_id=uuid.UUID("00000000-0000-0000-0000-000000000006"),
    document_value="DEMO-ORG-0002",
    name="[Demonstração] Outra empresa",
    address="[Demonstração] Endereço de teste",
)
ORGANIZACOES = (CREED, EMPRESA, OUTRA_EMPRESA)

ADMIN = PessoaDeTeste(
    email="dev@creed.example.com",
    name="Dev CREED",
    role=Roles.ADMIN,
    type=LinkType.EMPREGO,
    organization_id=CREED.id,
    participant_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
)
PESSOAS = (
    ADMIN,
    PessoaDeTeste(
        email="gestora@creed.example.com",
        name="[Demonstração] Gestora",
        role=Roles.GESTOR,
        type=LinkType.EMPREGO,
        organization_id=EMPRESA.id,
        participant_id=uuid.UUID("00000000-0000-0000-0002-000000000001"),
    ),
    PessoaDeTeste(
        email="funcionario@creed.example.com",
        name="[Demonstração] Funcionário",
        role=Roles.RESPONDENTE,
        type=LinkType.EMPREGO,
        organization_id=EMPRESA.id,
        participant_id=uuid.UUID("00000000-0000-0000-0002-000000000002"),
    ),
    PessoaDeTeste(
        email="funcionario.outra@creed.example.com",
        name="[Demonstração] Funcionário da outra empresa",
        role=Roles.RESPONDENTE,
        type=LinkType.EMPREGO,
        organization_id=OUTRA_EMPRESA.id,
        participant_id=uuid.UUID("00000000-0000-0000-0002-000000000003"),
    ),
    PessoaDeTeste(
        email="mentorando1@creed.example.com",
        name="[Demonstração] Mentorando 1",
        role=Roles.RESPONDENTE,
        type=LinkType.MENTORIA,
        organization_id=CREED.id,
        participant_id=uuid.UUID("00000000-0000-0000-0002-000000000004"),
    ),
    PessoaDeTeste(
        email="mentorando2@creed.example.com",
        name="[Demonstração] Mentorando 2",
        role=Roles.RESPONDENTE,
        type=LinkType.MENTORIA,
        organization_id=CREED.id,
        participant_id=uuid.UUID("00000000-0000-0000-0002-000000000005"),
    ),
)

# O formulário de demonstração que versões anteriores deste seed criavam, aberto
# até 2031 para a organização de dev. Ele fazia a admin e os mentorandos caírem
# num questionário que em produção não existe: o seed agora o apaga.
OLD_DEMO_FORM_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


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


async def _keycloak_id(
    http: httpx.AsyncClient, token: str, pessoa: PessoaDeTeste
) -> uuid.UUID:
    """O `sub` da pessoa, criando-a no realm na primeira vez."""
    keycloak_id = await _buscar_no_realm(http, token, pessoa)
    if keycloak_id is None:
        keycloak_id = await _criar_no_realm(http, token, pessoa)
    return keycloak_id


async def _buscar_no_realm(
    http: httpx.AsyncClient, token: str, pessoa: PessoaDeTeste
) -> uuid.UUID | None:
    response = await http.get(
        f"{_admin_url()}/users",
        params={"email": pessoa.email, "exact": "true"},
        headers={"Authorization": f"Bearer {token}"},
    )
    if not response.is_success:
        raise SeedError(f"Admin API recusou a consulta: {response.text[:200]}")

    encontrados = response.json()
    if not encontrados:
        return None
    return uuid.UUID(encontrados[0]["id"])


async def _criar_no_realm(
    http: httpx.AsyncClient, token: str, pessoa: PessoaDeTeste
) -> uuid.UUID:
    headers = {"Authorization": f"Bearer {token}"}

    response = await http.post(
        f"{_admin_url()}/users", json=_usuario_de_teste(pessoa), headers=headers
    )
    if not response.is_success:
        raise SeedError(f"Admin API recusou criar {pessoa.email}: {response.text[:200]}")
    # A Admin API devolve o id do usuário criado só no cabeçalho Location.
    keycloak_id = uuid.UUID(response.headers["Location"].rsplit("/", 1)[-1])

    # O papel vai numa chamada à parte: o POST de usuário ignora `realmRoles`.
    # É a cópia do papel do vínculo (decisão D4).
    papel = await http.get(f"{_admin_url()}/roles/{pessoa.role.value}", headers=headers)
    if not papel.is_success:
        raise SeedError(f"Admin API recusou ler o papel: {papel.text[:200]}")
    response = await http.post(
        f"{_admin_url()}/users/{keycloak_id}/role-mappings/realm",
        json=[papel.json()],
        headers=headers,
    )
    if not response.is_success:
        raise SeedError(f"Admin API recusou dar o papel: {response.text[:200]}")

    print(f"{pessoa.email} criado no realm, papel {pessoa.role.value}.")
    return keycloak_id


def _usuario_de_teste(pessoa: PessoaDeTeste) -> dict[str, Any]:
    """A pessoa de teste no formato que a Admin API recebe.

    Sem `requiredActions` vazia e sem `temporary: False`, o Direct Access Grant
    responde `invalid_grant: "Account is not fully set up"` — que na tela vira
    "senha inválida" e manda o time procurar um bug que não existe.
    """
    return {
        "username": pessoa.email,
        "email": pessoa.email,
        # O realm recusa colchetes no nome: o "[Demonstração]" fica só no nosso banco.
        "firstName": pessoa.name.removeprefix("[Demonstração] "),
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
        keycloak_ids = {
            pessoa.email: await _keycloak_id(http, token, pessoa) for pessoa in PESSOAS
        }

    async with AsyncSessionLocal() as session:
        # Antes das pessoas: a FK de `links` recusa vínculo sem participante e sem
        # organização.
        organizations = OrganizationRepository(session)
        for organizacao in ORGANIZACOES:
            await _ensure_organization(session, organizations, organizacao)
        await _remove_old_demo_form(session)
        await session.commit()

        for pessoa in PESSOAS:
            await _ensure_pessoa(session, pessoa, keycloak_ids[pessoa.email])
            await session.commit()

    print(f"Pronto. Todas as pessoas de teste entram com a senha {PASSWORD!r}.")


async def _ensure_pessoa(
    session: AsyncSession, pessoa: PessoaDeTeste, keycloak_id: uuid.UUID
) -> None:
    """Participante, vínculo e acesso da pessoa, o que faltar."""
    users = UserRepository(session)
    links = LinkRepository(session)

    await _ensure_participant(ParticipantRepository(session), pessoa)
    existente = await users.get_user_by_email(pessoa.email)

    if existente is None:
        link = await links.insert(_new_link(pessoa))
        await users.create(
            User(
                keycloak_id=keycloak_id,
                name=pessoa.name,
                email=pessoa.email,
                status=RecordStatus.ACTIVE,
                link_id=link.id,
            )
        )
        print(f"{pessoa.email} criado, vínculo {link.id} ({pessoa.role.value}).")
        return

    # Com `user.link_id` NOT NULL o vínculo sempre existe — mas num banco ainda em
    # `87beb54d929a`, que é onde a revisão `28e9a13197f4` para, o usuário pode estar
    # sem ele. O seed não liga usuário a vínculo, então falha em vez de dizer que
    # está tudo certo.
    vinculo = await links.get_by_id(existente.link_id)
    if vinculo is None:
        raise SeedError(
            f"{pessoa.email} está no banco sem vínculo: o schema ainda é o de antes "
            "da CREED-32/task 6. Rode `alembic upgrade head`, siga a mensagem dela e "
            "depois rode este seed de novo."
        )

    # Idempotente: rodar de novo depois de um `down -v` só reata o usuário ao `sub`
    # novo, em vez de estourar na constraint única.
    if existente.keycloak_id != keycloak_id:
        print(f"keycloak_id mudou: {existente.keycloak_id} -> {keycloak_id}")
        existente.keycloak_id = keycloak_id

    # Bancos semeados antes tinham a admin na organização de dev, junto com o
    # formulário de demonstração. Ela muda para a da CREED, como em produção.
    if vinculo.organization_id != pessoa.organization_id:
        print(
            f"{pessoa.email}: vínculo {vinculo.id} mudou de organização, "
            f"{vinculo.organization_id} -> {pessoa.organization_id}."
        )
        vinculo.organization_id = pessoa.organization_id

    print(f"{pessoa.email} já estava no banco, com o vínculo {vinculo.id}.")


async def _ensure_participant(
    participants: ParticipantRepository, pessoa: PessoaDeTeste
) -> bool:
    """Cria o participante da pessoa se ele ainda não existe. Diz se criou."""
    if await participants.get_by_id(pessoa.participant_id) is not None:
        return False

    await participants.create(
        Participant(
            id=pessoa.participant_id, name=pessoa.name, status=RecordStatus.ACTIVE
        )
    )
    print(f"participante {pessoa.participant_id} criado.")
    return True


async def _ensure_organization(
    session: AsyncSession,
    organizations: OrganizationRepository,
    organizacao: OrganizacaoDeTeste,
) -> bool:
    """Cria a organização e o documento dela, o que faltar. Diz se criou.

    O documento vai direto pela sessão, sem repository: `documents` não tem `create`
    porque nenhuma rota cria documento (P-022), e o seed é o único que precisa.
    """
    criou = False

    if await session.get(Document, organizacao.document_id) is None:
        session.add(
            Document(
                id=organizacao.document_id,
                type=DocType.OTHER,
                value=organizacao.document_value,
            )
        )
        await session.flush()
        criou = True

    if await organizations.get_by_id(organizacao.id) is None:
        await organizations.create(
            Organization(
                id=organizacao.id,
                name=organizacao.name,
                address=organizacao.address,
                document_id=organizacao.document_id,
                status=OrganizationStatus.ACTIVE,
            )
        )
        criou = True

    situacao = "criada" if criou else "já estava no banco"
    print(f"organização {organizacao.name} ({organizacao.id}) {situacao}.")
    return criou


async def _remove_old_demo_form(session: AsyncSession) -> bool:
    """Apaga o formulário de demonstração antigo e as respostas dele. Diz se apagou.

    Só respostas de teste do ambiente local: o formulário nunca existiu fora dele.
    """
    if await session.get(Form, OLD_DEMO_FORM_ID) is None:
        return False

    respostas = select(FormResponse.id).where(FormResponse.form_id == OLD_DEMO_FORM_ID)
    await session.execute(delete(Answer).where(Answer.form_response_id.in_(respostas)))
    await session.execute(
        delete(FormResponse).where(FormResponse.form_id == OLD_DEMO_FORM_ID)
    )
    await session.execute(delete(Form).where(Form.id == OLD_DEMO_FORM_ID))
    print(
        f"formulário de demonstração antigo {OLD_DEMO_FORM_ID} apagado, com as "
        "respostas de teste dele."
    )
    return True


def _new_link(pessoa: PessoaDeTeste) -> Link:
    return Link(
        participant_id=pessoa.participant_id,
        organization_id=pessoa.organization_id,
        type=pessoa.type,
        role=pessoa.role,
    )


if __name__ == "__main__":
    try:
        asyncio.run(semear())
    except SeedError as exc:
        print(f"seed: {exc}", file=sys.stderr)
        sys.exit(1)
