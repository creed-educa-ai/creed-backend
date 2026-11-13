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
estão os mentorandos (P-048), e as empresas com os seus membros. **Nenhum período
aberto** nasce aqui: quem abre é o gestor ou a admin, pelo painel, como em produção.
As perguntas também não: são do instrumento CREED, que entra por migration de dados.

Para os dashboards terem o que mostrar, o seed grava **períodos já encerrados e
respondidos**: dois na empresa de demonstração, para comparar um com o outro, e um
individual do mentorando 1. As notas saem de uma fórmula fixa
(`nota_de_demonstracao`), sem sorteio: rodar de novo dá sempre o mesmo resultado.

O `sub` é perguntado ao Keycloak **a cada execução**, nunca fixado aqui: quem
roda `docker compose down -v` ganha usuários novos no realm (ver README).

    python scripts/seed_local.py
"""

import asyncio
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models  # noqa: F401  (registra todas as tabelas; ver app/models.py)
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.domains.department.models import Department
from app.domains.documents.models import DocType, Document
from app.domains.forms.models import Form, FormStatus
from app.domains.links.models import Link
from app.domains.links.repository import LinkRepository
from app.domains.organizacoes.models import Organization, OrganizationStatus
from app.domains.organizacoes.repository import OrganizationRepository
from app.domains.participants.models import Participant
from app.domains.participants.repository import ParticipantRepository
from app.domains.questions.models import Question
from app.domains.responses.models import Answer, FormResponse, FormResponseStatus
from app.domains.users.models import User
from app.domains.users.repository import UserRepository
from app.shared.enums import DepartmentType, Dimension, LinkType, RecordStatus, Roles
from app.shared.instrument import CREED_INSTRUMENT_ID

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
    # O setor do vínculo. O seed cria o setor na organização, se faltar.
    department: DepartmentType | None = None


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
        department=DepartmentType.MARKETING,
    ),
    # A equipe da empresa de demonstração, para o alinhamento e o mapa de setores:
    # três setores e uma pessoa sem setor.
    PessoaDeTeste(
        email="ana.marketing@creed.example.com",
        name="[Demonstração] Ana Lima",
        role=Roles.RESPONDENTE,
        type=LinkType.EMPREGO,
        organization_id=EMPRESA.id,
        participant_id=uuid.UUID("00000000-0000-0000-0002-000000000006"),
        department=DepartmentType.MARKETING,
    ),
    PessoaDeTeste(
        email="bruno.marketing@creed.example.com",
        name="[Demonstração] Bruno Costa",
        role=Roles.RESPONDENTE,
        type=LinkType.EMPREGO,
        organization_id=EMPRESA.id,
        participant_id=uuid.UUID("00000000-0000-0000-0002-000000000007"),
        department=DepartmentType.MARKETING,
    ),
    PessoaDeTeste(
        email="carla.financeiro@creed.example.com",
        name="[Demonstração] Carla Souza",
        role=Roles.RESPONDENTE,
        type=LinkType.EMPREGO,
        organization_id=EMPRESA.id,
        participant_id=uuid.UUID("00000000-0000-0000-0002-000000000008"),
        department=DepartmentType.FINANCEIRO,
    ),
    PessoaDeTeste(
        email="diego.financeiro@creed.example.com",
        name="[Demonstração] Diego Alves",
        role=Roles.RESPONDENTE,
        type=LinkType.EMPREGO,
        organization_id=EMPRESA.id,
        participant_id=uuid.UUID("00000000-0000-0000-0002-000000000009"),
        department=DepartmentType.FINANCEIRO,
    ),
    PessoaDeTeste(
        email="elisa.ti@creed.example.com",
        name="[Demonstração] Elisa Rocha",
        role=Roles.RESPONDENTE,
        type=LinkType.EMPREGO,
        organization_id=EMPRESA.id,
        participant_id=uuid.UUID("00000000-0000-0000-0002-000000000010"),
        department=DepartmentType.TECNOLOGIA_INFORMACAO,
    ),
    PessoaDeTeste(
        email="fabio.ti@creed.example.com",
        name="[Demonstração] Fábio Nunes",
        role=Roles.RESPONDENTE,
        type=LinkType.EMPREGO,
        organization_id=EMPRESA.id,
        participant_id=uuid.UUID("00000000-0000-0000-0002-000000000011"),
        department=DepartmentType.TECNOLOGIA_INFORMACAO,
    ),
    PessoaDeTeste(
        email="gabriela.ti@creed.example.com",
        name="[Demonstração] Gabriela Dias",
        role=Roles.RESPONDENTE,
        type=LinkType.EMPREGO,
        organization_id=EMPRESA.id,
        participant_id=uuid.UUID("00000000-0000-0000-0002-000000000012"),
        department=DepartmentType.TECNOLOGIA_INFORMACAO,
    ),
    PessoaDeTeste(
        email="helena@creed.example.com",
        name="[Demonstração] Helena Prado",
        role=Roles.RESPONDENTE,
        type=LinkType.EMPREGO,
        organization_id=EMPRESA.id,
        participant_id=uuid.UUID("00000000-0000-0000-0002-000000000013"),
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


def _pessoa(email: str) -> PessoaDeTeste:
    return next(pessoa for pessoa in PESSOAS if pessoa.email == email)


@dataclass(frozen=True)
class PeriodoDeDemonstracao:
    """Um período já encerrado, com as respostas enviadas de quem está na lista."""

    id: uuid.UUID
    organization_id: uuid.UUID
    opens_at: datetime
    closes_at: datetime
    respondentes: tuple[str, ...]
    # O mentorando do período individual; nulo é o período "para todos".
    individual_de: str | None = None
    # O período mais recente da empresa: as notas sobem um pouco em relação ao
    # anterior, para a comparação entre períodos ter o que mostrar.
    melhora: bool = False


# A gestora também responde: o dashboard da empresa mostra a ela o próprio
# resultado, e só o dela.
RESPONDENTES_DA_EMPRESA = tuple(
    pessoa.email
    for pessoa in PESSOAS
    if pessoa.organization_id == EMPRESA.id
    and pessoa.role in (Roles.RESPONDENTE, Roles.GESTOR)
)
# Quem não responde o segundo período: a taxa de conclusão não fica em 100%.
AUSENTE_NO_SEGUNDO_PERIODO = "gabriela.ti@creed.example.com"

# Ids fixos para o seed continuar idempotente, numa faixa só dos períodos.
PERIODOS_DE_DEMONSTRACAO = (
    PeriodoDeDemonstracao(
        id=uuid.UUID("00000000-0000-0000-0003-000000000001"),
        organization_id=EMPRESA.id,
        opens_at=datetime(2026, 9, 1, 12, tzinfo=UTC),
        closes_at=datetime(2026, 9, 15, 12, tzinfo=UTC),
        respondentes=RESPONDENTES_DA_EMPRESA,
    ),
    PeriodoDeDemonstracao(
        id=uuid.UUID("00000000-0000-0000-0003-000000000002"),
        organization_id=EMPRESA.id,
        opens_at=datetime(2026, 10, 1, 12, tzinfo=UTC),
        closes_at=datetime(2026, 10, 15, 12, tzinfo=UTC),
        respondentes=tuple(
            email
            for email in RESPONDENTES_DA_EMPRESA
            if email != AUSENTE_NO_SEGUNDO_PERIODO
        ),
        melhora=True,
    ),
    PeriodoDeDemonstracao(
        id=uuid.UUID("00000000-0000-0000-0003-000000000003"),
        organization_id=CREED.id,
        opens_at=datetime(2026, 10, 1, 12, tzinfo=UTC),
        closes_at=datetime(2026, 10, 15, 12, tzinfo=UTC),
        respondentes=("mentorando1@creed.example.com",),
        individual_de="mentorando1@creed.example.com",
    ),
)

# Cada setor puxa umas dimensões para cima e outras para baixo: o mapa de setores
# e o recorte por setor mostram números diferentes. Quem não tem setor fica na
# média.
PERFIL_DO_SETOR: dict[DepartmentType, dict[Dimension, int]] = {
    DepartmentType.MARKETING: {Dimension.S2: 1, Dimension.S5A: 1, Dimension.S7: -1},
    DepartmentType.FINANCEIRO: {Dimension.S6: 1, Dimension.S8: 1, Dimension.S4: -1},
    DepartmentType.TECNOLOGIA_INFORMACAO: {
        Dimension.S5B: 1,
        Dimension.S2: -1,
        Dimension.S8: -1,
    },
}

RESPOSTA_ABERTA = "[Demonstração] Resposta aberta de teste."

# Os vínculos das pessoas de teste começam antes do primeiro período de
# demonstração. O resumo da empresa só conta quem já estava na organização quando
# o período fechou (`links.created_at` e `start_at`): com a data de hoje, os
# períodos de setembro e outubro ficariam sem convidados e sem respostas.
INICIO_DOS_VINCULOS = datetime(2026, 8, 1, 12, tzinfo=UTC)


def nota_de_demonstracao(
    pessoa: PessoaDeTeste, dimensao: Dimension, posicao: int, *, melhora: bool
) -> int:
    """A alternativa (1 a 5) que a pessoa escolhe numa pergunta. Sem sorteio.

    Parte do meio da escala (3), soma o perfil do setor, desloca cada pessoa um
    pouco para cima ou para baixo (pelo índice dela em `PESSOAS`) e varia de
    pergunta para pergunta dentro da dimensão (pela `posicao`). No período com
    `melhora`, uma pergunta a cada três sobe um ponto.
    """
    indice = PESSOAS.index(pessoa)
    nota = 3
    if pessoa.department is not None:
        nota += PERFIL_DO_SETOR.get(pessoa.department, {}).get(dimensao, 0)
    nota += indice % 3 - 1
    nota += (posicao + indice) % 3 - 1
    if melhora and posicao % 3 == 0:
        nota += 1
    return max(1, min(5, nota))


def respostas_de_demonstracao(
    form_response_id: uuid.UUID,
    perguntas: list[Question],
    pessoa: PessoaDeTeste,
    *,
    melhora: bool,
) -> list[Answer]:
    """Uma resposta por pergunta do instrumento: a alternativa nas objetivas, um
    texto curto nas abertas."""
    respostas = []
    for pergunta in perguntas:
        if pergunta.dimensao is None:
            respostas.append(
                Answer(
                    form_response_id=form_response_id,
                    question_id=pergunta.id,
                    value=RESPOSTA_ABERTA,
                )
            )
            continue
        valor = str(
            nota_de_demonstracao(
                pessoa, pergunta.dimensao, pergunta.order_index, melhora=melhora
            )
        )
        alternativa = next(option for option in pergunta.options if option.value == valor)
        respostas.append(
            Answer(
                form_response_id=form_response_id,
                question_id=pergunta.id,
                option_id=alternativa.id,
            )
        )
    return respostas


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
        setores = await _ensure_departments(session)
        await session.commit()

        link_ids: dict[str, uuid.UUID] = {}
        for pessoa in PESSOAS:
            department_id = (
                setores[(pessoa.organization_id, pessoa.department)]
                if pessoa.department is not None
                else None
            )
            link_ids[pessoa.email] = await _ensure_pessoa(
                session, pessoa, keycloak_ids[pessoa.email], department_id
            )
            await session.commit()

        perguntas = await _perguntas_do_instrumento(session)
        for periodo in PERIODOS_DE_DEMONSTRACAO:
            await _ensure_periodo(session, periodo, link_ids, perguntas)
            await session.commit()

    print(f"Pronto. Todas as pessoas de teste entram com a senha {PASSWORD!r}.")


async def _ensure_pessoa(
    session: AsyncSession,
    pessoa: PessoaDeTeste,
    keycloak_id: uuid.UUID,
    department_id: uuid.UUID | None,
) -> uuid.UUID:
    """Participante, vínculo e acesso da pessoa, o que faltar. Devolve o vínculo."""
    users = UserRepository(session)
    links = LinkRepository(session)

    await _ensure_participant(ParticipantRepository(session), pessoa)
    existente = await users.get_user_by_email(pessoa.email)

    if existente is None:
        link = await links.insert(_new_link(pessoa, department_id))
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
        return link.id

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

    if vinculo.start_at > INICIO_DOS_VINCULOS or vinculo.created_at > INICIO_DOS_VINCULOS:
        print(f"{pessoa.email}: vínculo {vinculo.id} passa a começar antes dos períodos.")
        vinculo.start_at = INICIO_DOS_VINCULOS
        vinculo.created_at = INICIO_DOS_VINCULOS

    # O setor é o do seed: os dashboards de demonstração contam com ele.
    if vinculo.department_id != department_id:
        print(f"{pessoa.email}: setor do vínculo {vinculo.id} volta a ser o do seed.")
        vinculo.department_id = department_id

    print(f"{pessoa.email} já estava no banco, com o vínculo {vinculo.id}.")
    return vinculo.id


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


async def _ensure_departments(
    session: AsyncSession,
) -> dict[tuple[uuid.UUID, DepartmentType], uuid.UUID]:
    """Os setores que as pessoas de teste usam, criando os que faltam.

    Um setor por organização e tipo (`uq_departments_organization_type`).
    """
    setores: dict[tuple[uuid.UUID, DepartmentType], uuid.UUID] = {}
    for organization_id, tipo in sorted(
        {(p.organization_id, p.department) for p in PESSOAS if p.department},
        key=lambda par: (str(par[0]), par[1].value),
    ):
        department_id = await session.scalar(
            select(Department.id).where(
                Department.organization_id == organization_id, Department.type == tipo
            )
        )
        if department_id is None:
            department = Department(organization_id=organization_id, type=tipo)
            session.add(department)
            await session.flush()
            department_id = department.id
            print(f"setor {tipo.value} criado na organização {organization_id}.")
        setores[(organization_id, tipo)] = department_id
    return setores


async def _perguntas_do_instrumento(session: AsyncSession) -> list[Question]:
    """As perguntas do instrumento CREED, com as alternativas, na ordem da tela."""
    result = await session.execute(
        select(Question)
        .where(Question.instrument_id == CREED_INSTRUMENT_ID)
        .options(selectinload(Question.options))
        .order_by(Question.order_index)
    )
    perguntas = list(result.scalars().all())
    if not perguntas:
        raise SeedError(
            "O instrumento CREED está sem perguntas: rode `alembic upgrade head` "
            "antes do seed."
        )
    return perguntas


async def _ensure_periodo(
    session: AsyncSession,
    periodo: PeriodoDeDemonstracao,
    link_ids: dict[str, uuid.UUID],
    perguntas: list[Question],
) -> None:
    """O período e as respostas enviadas de quem está na lista, o que faltar.

    Resposta que já existe não é tocada: o seed não reescreve o que alguém
    respondeu à mão num período de demonstração.
    """
    if await session.get(Form, periodo.id) is None:
        session.add(
            Form(
                id=periodo.id,
                # O mesmo nome que a abertura de período pelo painel dá.
                name=(
                    f"Questionário {periodo.opens_at:%Y-%m-%d} a "
                    f"{periodo.closes_at:%Y-%m-%d}"
                ),
                organization_id=periodo.organization_id,
                status=FormStatus.DRAFT,
                opens_at=periodo.opens_at,
                closes_at=periodo.closes_at,
                link_id=(
                    link_ids[periodo.individual_de] if periodo.individual_de else None
                ),
            )
        )
        await session.flush()
        print(f"período de demonstração {periodo.id} criado.")

    novas = 0
    for indice, email in enumerate(periodo.respondentes):
        link_id = link_ids[email]
        existente = await session.scalar(
            select(FormResponse.id).where(
                FormResponse.form_id == periodo.id, FormResponse.vinculo_id == link_id
            )
        )
        if existente is not None:
            continue

        # Dentro do período, uma pessoa por hora a partir do segundo dia.
        enviada_em = periodo.opens_at + timedelta(days=1, hours=indice)
        resposta = FormResponse(
            form_id=periodo.id,
            vinculo_id=link_id,
            status=FormResponseStatus.SUBMITTED,
            started_at=enviada_em - timedelta(minutes=40),
            submitted_at=enviada_em,
        )
        session.add(resposta)
        await session.flush()
        session.add_all(
            respostas_de_demonstracao(
                resposta.id, perguntas, _pessoa(email), melhora=periodo.melhora
            )
        )
        novas += 1

    print(
        f"período {periodo.id}: {novas} resposta(s) nova(s), "
        f"{len(periodo.respondentes)} no total."
    )


def _new_link(pessoa: PessoaDeTeste, department_id: uuid.UUID | None = None) -> Link:
    return Link(
        participant_id=pessoa.participant_id,
        organization_id=pessoa.organization_id,
        department_id=department_id,
        type=pessoa.type,
        role=pessoa.role,
        start_at=INICIO_DOS_VINCULOS,
        created_at=INICIO_DOS_VINCULOS,
    )


if __name__ == "__main__":
    try:
        asyncio.run(semear())
    except SeedError as exc:
        print(f"seed: {exc}", file=sys.stderr)
        sys.exit(1)
