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
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app import models  # noqa: F401  (registra todas as tabelas; ver app/models.py)
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.domains.documents.models import DocType, Document
from app.domains.forms.models import Form, FormStatus
from app.domains.forms.repository import FormRepository
from app.domains.links.models import Link
from app.domains.links.repository import LinkRepository
from app.domains.organizacoes.models import Organization, OrganizationStatus
from app.domains.organizacoes.repository import OrganizationRepository
from app.domains.participants.models import Participant
from app.domains.participants.repository import ParticipantRepository
from app.domains.questions.models import (
    Question,
    QuestionOption,
    QuestionSection,
    QuestionType,
)
from app.domains.questions.repository import QuestionOptionRepository, QuestionRepository
from app.domains.users.models import User
from app.domains.users.repository import UserRepository
from app.shared.enums import Dimension, LinkType, RecordStatus, Roles

EMAIL = "dev@creed.example.com"
NAME = "Dev CREED"
# Senha pública de propósito: este usuário só existe no ambiente local. Tem 8
# caracteres ou mais porque a política do realm (`length(8)`, P-004 de 07/09) faz a
# Admin API recusar a criação do usuário com senha mais curta.
PASSWORD = "dev-creed"  # noqa: S105

# O papel de acesso é o do vínculo (CREED-32): `user` não guarda papel.
LINK_ROLE = Roles.ADMIN

# Fixos, e não aleatórios, para o seed continuar idempotente. O participante e a
# organização são criados por este seed, porque `links` tem FK para os dois
# (CREED-47 e CREED-38). A organização precisa de um documento (`document_id` é
# obrigatório) e não há endpoint para criá-lo (P-022): o seed cria um sintético.
PARTICIPANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
ORGANIZATION_DOCUMENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000004")
ORGANIZATION_NAME = "[Demonstração] Organização de dev"
ORGANIZATION_ADDRESS = "[Demonstração] Endereço de teste"
# Valor sintético de propósito, com tipo `other`: não pode parecer um CNPJ real.
ORGANIZATION_DOCUMENT_VALUE = "DEMO-ORG-0001"

# Formulário de demonstração (CREED-47), na organização do vínculo de dev: é o que
# o `dev` abre, responde e envia. Fica em rascunho, que já pode ser respondido
# (P-030). Id fixo pelo mesmo motivo do participante; as perguntas se reconhecem
# por (formulário, posição), que já é único.
DEMO_FORM_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")
DEMO_FORM_NAME = "[Demonstração] Formulário de teste"
# Período longo, porque o back só aceita resposta dentro dele. Provisório: sai
# quando o seed da Q-0 abrir o período com as perguntas do instrumento.
DEMO_OPENS_AT = datetime(2026, 1, 1, tzinfo=UTC)
DEMO_CLOSES_AT = datetime(2031, 1, 1, tzinfo=UTC)

# Texto sintético de propósito: o conteúdo do instrumento é da cliente. Uma por
# seção (P-020), todas descritivas: o back já aceita a objetiva, mas o front
# ainda a pula no envio e não recebe as alternativas, e uma objetiva obrigatória
# aqui travaria o envio da demonstração. Duas obrigatórias e uma opcional, para o
# envio ser barrado e depois aceito.
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

# Inventário CREED (CREED-61): as 47 afirmações Likert do formulário "Linguagem
# melhorada", em PT, que é o idioma padrão (EN/ES vão para as tabelas de tradução).
# Formulário próprio, separado do de demonstração, na mesma organização de dev.
# Id fixo e perguntas reconhecidas por (formulário, posição), como no de demonstração.
# `prisma` fica vazio: os prismas são médias das dimensões, não das perguntas.
INVENTORY_FORM_ID = uuid.UUID("00000000-0000-0000-0000-000000000005")
INVENTORY_FORM_NAME = "Inventário CREED"

# As mesmas cinco alternativas em todas as perguntas, mas cada pergunta tem as
# suas linhas: a resposta objetiva aponta para o `option_id` da pergunta.
# (value, label); a posição é o índice na lista.
LIKERT_OPTIONS = [
    ("1", "Discordo totalmente"),
    ("2", "Discordo"),
    ("3", "Nem concordo nem discordo"),
    ("4", "Concordo"),
    ("5", "Concordo totalmente"),
]

# (dimensão, texto); a posição é o índice na lista (0 = item 12 do formulário).
INVENTORY_QUESTIONS = [
    # S2: itens 12 a 19 do formulário
    (Dimension.S2, "Já fui fundador(a) ou sócio(a) de um negócio."),
    (Dimension.S2, "Já atuei como intraempreendedor(a) dentro de uma organização."),
    (
        Dimension.S2,
        "Participei do desenvolvimento de novos produtos, serviços ou negócios.",
    ),
    (
        Dimension.S2,
        (
            "Atuei como mentor(a), avaliador(a) ou conselheiro(a) em iniciativas "
            "empreendedoras."
        ),
    ),
    (Dimension.S2, "Tenho conexões com ecossistemas de empreendedorismo e inovação."),
    (
        Dimension.S2,
        (
            "Sou incentivado(a) a identificar oportunidades a partir de problemas "
            "sociais e culturais."
        ),
    ),
    (
        Dimension.S2,
        (
            "Tomo decisões com segurança mesmo em situações incertas e com recursos"
            " limitados."
        ),
    ),
    (
        Dimension.S2,
        "Persisto diante dos obstáculos e adapto minha abordagem ao longo do processo.",
    ),
    # S4: itens 20 a 25 do formulário
    (
        Dimension.S4,
        "A diversidade cultural é valorizada nas práticas da organização em que atuo.",
    ),
    (
        Dimension.S4,
        "A organização integra conteúdos e perspetivas de diferentes culturas.",
    ),
    (
        Dimension.S4,
        (
            "As práticas da organização em que atuo contribuem para a redução de "
            "preconceitos."
        ),
    ),
    (Dimension.S4, "Diferenças culturais são tratadas como fonte de aprendizagem."),
    (
        Dimension.S4,
        "A organização em que atuo promove justiça social, equidade e inclusão.",
    ),
    (
        Dimension.S4,
        (
            "Demonstro empatia e abertura ao interagir com pessoas de culturas e "
            "contextos diferentes."
        ),
    ),
    # S5A: itens 26 a 32 do formulário
    (
        Dimension.S5A,
        (
            "Compreendo metodologias ativas como Design Thinking, Lean Startup e "
            "Effectuation."
        ),
    ),
    (
        Dimension.S5A,
        "Vivencio e utilizo metodologias ativas na minha instituição ou organização.",
    ),
    (Dimension.S5A, "Utilizo tecnologias digitais para ensinar ou aprender."),
    (Dimension.S5A, "As metodologias utilizadas são culturalmente acessíveis."),
    (Dimension.S5A, "Jogos, simulações e desafios consideram a diversidade cultural."),
    (Dimension.S5A, "Desenvolvo criatividade para propor soluções inovadoras."),
    (Dimension.S5A, "Aprendo a transformar ideias em ações empreendedoras concretas."),
    # S5B: itens 33 a 40 do formulário
    (Dimension.S5B, "Prefiro aprender de forma autónoma e ao meu próprio ritmo."),
    (
        Dimension.S5B,
        (
            "Aprendo melhor em contextos colaborativos, com troca de experiências "
            "entre pares."
        ),
    ),
    (
        Dimension.S5B,
        (
            "Integro critérios de sustentabilidade e impacto social nas "
            "metodologias que aplico."
        ),
    ),
    (
        Dimension.S5B,
        (
            "Reconheço meus próprios padrões de aprendizagem e ajusto estratégias "
            "para aprender com mais eficácia."
        ),
    ),
    (
        Dimension.S5B,
        (
            "Aprendo com os erros e utilizo o feedback como oportunidade de "
            "reorganização e crescimento mental."
        ),
    ),
    (
        Dimension.S5B,
        (
            "Compreendo que a prática deliberada e a repetição fortalecem conexões "
            "neurais e consolidam novos saberes."
        ),
    ),
    (
        Dimension.S5B,
        (
            "Desenvolvo aprendizagens significativas mesmo em contextos sem acesso "
            "a tecnologia."
        ),
    ),
    (
        Dimension.S5B,
        (
            "Reconheço meu próprio perfil de aprendizagem — individual ou coletivo,"
            " digital ou presencial — e uso esse autoconhecimento a meu favor."
        ),
    ),
    # S6: itens 41 a 46 do formulário
    (Dimension.S6, "Adapto minhas práticas às necessidades culturais de cada contexto."),
    (
        Dimension.S6,
        "Reconheço como a cultura influencia os processos de inovação e criação.",
    ),
    (
        Dimension.S6,
        "Crio ambientes inclusivos onde perspectivas diversas são valorizadas.",
    ),
    (
        Dimension.S6,
        "Desenvolvo práticas que respeitam e celebram a diversidade cultural.",
    ),
    (
        Dimension.S6,
        "Promovo equidade no acesso a oportunidades de inovação e desenvolvimento.",
    ),
    (
        Dimension.S6,
        (
            "Sinto-me seguro(a) para expressar perspectivas diferentes e "
            "experimentar novas abordagens."
        ),
    ),
    # S7: itens 47 a 52 do formulário
    (
        Dimension.S7,
        (
            "Possuo consciência profunda sobre minha própria identidade e bagagem "
            "cultural."
        ),
    ),
    (Dimension.S7, "Navego com eficácia entre diferentes sistemas de valores e crenças."),
    (
        Dimension.S7,
        "Transformo tensões e conflitos culturais em oportunidades de cocriação.",
    ),
    (
        Dimension.S7,
        (
            "Contribuo para a construção de culturas organizacionais mais "
            "inovadoras e inclusivas."
        ),
    ),
    (
        Dimension.S7,
        (
            "Lidero com inteligência cultural em contextos de alta complexidade e "
            "diversidade."
        ),
    ),
    (
        Dimension.S7,
        (
            "Identifico oportunidades de inovação a partir da diversidade de "
            "contextos e perspectivas."
        ),
    ),
    # S8: itens 53 a 58 do formulário
    (
        Dimension.S8,
        (
            "Oriento meus projetos e iniciativas para gerar impacto social positivo"
            " e duradouro."
        ),
    ),
    (Dimension.S8, "Considero implicações éticas na criação e aplicação de inovações."),
    (
        Dimension.S8,
        "Desenvolvo soluções que endereçam desafios sistêmicos e estruturais.",
    ),
    (Dimension.S8, "Meço e comunico o impacto concreto das minhas contribuições."),
    (
        Dimension.S8,
        (
            "Construo legados que transcendem meu contexto e beneficiam comunidades"
            " mais amplas."
        ),
    ),
    (
        Dimension.S8,
        (
            "Incorporo princípios de responsabilidade social e governança nas "
            "minhas iniciativas de inovação."
        ),
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
        # usuário de dev também precisa do participante e da organização, senão a
        # FK de `links` recusa o vínculo do seed. E do formulário de demonstração.
        criou_participante = await _ensure_participant(ParticipantRepository(session))
        criou_organizacao = await _ensure_organization(
            session, OrganizationRepository(session)
        )
        criou_formulario = await _ensure_demo_form(
            FormRepository(session), QuestionRepository(session)
        )
        criou_inventario = await _ensure_inventory_form(
            FormRepository(session),
            QuestionRepository(session),
            QuestionOptionRepository(session),
        )
        if (
            criou_participante
            or criou_organizacao
            or criou_formulario
            or criou_inventario
        ):
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


async def _ensure_organization(
    session: AsyncSession, organizations: OrganizationRepository
) -> bool:
    """Cria a organização de dev e o documento dela, o que faltar. Diz se criou.

    O documento vai direto pela sessão, sem repository: `documents` não tem `create`
    porque nenhuma rota cria documento (P-022), e o seed é o único que precisa.
    """
    criou = False

    if await session.get(Document, ORGANIZATION_DOCUMENT_ID) is None:
        session.add(
            Document(
                id=ORGANIZATION_DOCUMENT_ID,
                type=DocType.OTHER,
                value=ORGANIZATION_DOCUMENT_VALUE,
            )
        )
        await session.flush()
        criou = True

    if await organizations.get_by_id(ORGANIZATION_ID) is None:
        await organizations.create(
            Organization(
                id=ORGANIZATION_ID,
                name=ORGANIZATION_NAME,
                address=ORGANIZATION_ADDRESS,
                document_id=ORGANIZATION_DOCUMENT_ID,
                status=OrganizationStatus.ACTIVE,
            )
        )
        criou = True

    situacao = "criada" if criou else "já estava no banco"
    print(f"organização {ORGANIZATION_ID} {situacao}.")
    return criou


async def _ensure_demo_form(forms: FormRepository, questions: QuestionRepository) -> bool:
    """Cria o formulário de demonstração e as perguntas que faltam. Diz se criou."""
    criou = False

    form = await forms.get_by_id(DEMO_FORM_ID)

    if form is None:
        await forms.create(
            Form(
                id=DEMO_FORM_ID,
                name=DEMO_FORM_NAME,
                organization_id=ORGANIZATION_ID,
                status=FormStatus.DRAFT,
                opens_at=DEMO_OPENS_AT,
                closes_at=DEMO_CLOSES_AT,
            )
        )
        criou = True
    elif form.opens_at is None or form.closes_at is None:
        # Banco semeado antes de o período existir: quem grava é o commit do seed.
        form.opens_at = DEMO_OPENS_AT
        form.closes_at = DEMO_CLOSES_AT
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


async def _ensure_inventory_form(
    forms: FormRepository,
    questions: QuestionRepository,
    options: QuestionOptionRepository,
) -> bool:
    """Cria o formulário do inventário, as perguntas e as alternativas que faltam.

    Idempotente: cada pergunta e cada alternativa só entra se a posição dela ainda
    estiver vazia, então rodar de novo não duplica nada. Diz se criou.
    """
    criou = False

    if await forms.get_by_id(INVENTORY_FORM_ID) is None:
        await forms.create(
            Form(
                id=INVENTORY_FORM_ID,
                name=INVENTORY_FORM_NAME,
                organization_id=ORGANIZATION_ID,
                status=FormStatus.DRAFT,
                opens_at=DEMO_OPENS_AT,
                closes_at=DEMO_CLOSES_AT,
            )
        )
        criou = True

    for order_index, (dimensao, text) in enumerate(INVENTORY_QUESTIONS):
        question = await questions.get_by_form_and_order(INVENTORY_FORM_ID, order_index)
        if question is None:
            question = await questions.insert(
                Question(
                    form_id=INVENTORY_FORM_ID,
                    text=text,
                    order_index=order_index,
                    type=QuestionType.OBJECTIVE,
                    section=QuestionSection.ASSESSMENT,
                    required=True,
                    prisma=None,
                    dimensao=dimensao,
                )
            )
            if question is None:
                # Só acontece se outra execução ocupou a posição ao mesmo tempo.
                raise SeedError(f"posição {order_index} do inventário já ocupada.")
            criou = True

        for option_index, (value, label) in enumerate(LIKERT_OPTIONS):
            existente = await options.get_by_question_and_order(question.id, option_index)
            if existente is not None:
                continue
            await options.insert(
                QuestionOption(
                    question_id=question.id,
                    label=label,
                    value=value,
                    order_index=option_index,
                )
            )
            criou = True

    situacao = "criado" if criou else "já estava no banco"
    print(f"inventário {INVENTORY_FORM_ID} {situacao}.")
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
