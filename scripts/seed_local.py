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
    QuestionLang,
    QuestionOption,
    QuestionSection,
    QuestionTranslation,
    QuestionType,
)
from app.domains.questions.repository import (
    QuestionOptionRepository,
    QuestionRepository,
    QuestionTranslationRepository,
)
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

# (dimensão, texto, traduções); a posição é o índice na lista (0 = item 12 do
# formulário). `traduções` é {idioma: texto}; o PT não entra nela, é o `texto`.
INVENTORY_QUESTIONS = [
    # S2: itens 12 a 19 do formulário
    (
        Dimension.S2,
        "Já fui fundador(a) ou sócio(a) de um negócio.",
        {
            QuestionLang.ES: "He sido fundador(a) o socio(a) de un negocio.",
            QuestionLang.EN: "I have been a founder or partner in a business.",
        },
    ),
    (
        Dimension.S2,
        "Já atuei como intraempreendedor(a) dentro de uma organização.",
        {
            QuestionLang.ES: (
                "He actuado como intraemprendedor(a) dentro de una organización."
            ),
            QuestionLang.EN: "I have worked as an intrapreneur within an organization.",
        },
    ),
    (
        Dimension.S2,
        "Participei do desenvolvimento de novos produtos, serviços ou negócios.",
        {
            QuestionLang.ES: (
                "He participado en el desarrollo de nuevos productos, servicios o "
                "negocios."
            ),
            QuestionLang.EN: (
                "I have taken part in developing new products, services, or businesses."
            ),
        },
    ),
    (
        Dimension.S2,
        (
            "Atuei como mentor(a), avaliador(a) ou conselheiro(a) em iniciativas "
            "empreendedoras."
        ),
        {
            QuestionLang.ES: (
                "He actuado como mentor(a), evaluador(a) o consejero(a) en "
                "iniciativas emprendedoras."
            ),
            QuestionLang.EN: (
                "I have acted as a mentor, evaluator, or advisor in entrepreneurial "
                "initiatives."
            ),
        },
    ),
    (
        Dimension.S2,
        "Tenho conexões com ecossistemas de empreendedorismo e inovação.",
        {
            QuestionLang.ES: (
                "Tengo conexiones con ecosistemas de emprendimiento e innovación."
            ),
            QuestionLang.EN: (
                "I have connections with entrepreneurship and innovation ecosystems."
            ),
        },
    ),
    (
        Dimension.S2,
        (
            "Sou incentivado(a) a identificar oportunidades a partir de problemas "
            "sociais e culturais."
        ),
        {
            QuestionLang.ES: (
                "Se me incentiva a identificar oportunidades a partir de problemas "
                "sociales y culturales."
            ),
            QuestionLang.EN: (
                "I am encouraged to identify opportunities arising from social and "
                "cultural problems."
            ),
        },
    ),
    (
        Dimension.S2,
        (
            "Tomo decisões com segurança mesmo em situações incertas e com recursos"
            " limitados."
        ),
        {
            QuestionLang.ES: (
                "Tomo decisiones con seguridad incluso en situaciones de "
                "incertidumbre y con recursos limitados."
            ),
            QuestionLang.EN: (
                "I make decisions confidently, even in uncertain situations with limited "
                "resources."
            ),
        },
    ),
    (
        Dimension.S2,
        "Persisto diante dos obstáculos e adapto minha abordagem ao longo do processo.",
        {
            QuestionLang.ES: (
                "Persisto ante los obstáculos y adapto mi enfoque a lo largo del proceso."
            ),
            QuestionLang.EN: (
                "I persist in the face of obstacles and adapt my approach throughout the "
                "process."
            ),
        },
    ),
    # S4: itens 20 a 25 do formulário
    (
        Dimension.S4,
        "A diversidade cultural é valorizada nas práticas da organização em que atuo.",
        {
            QuestionLang.ES: (
                "La diversidad cultural es valorada en las prácticas de la "
                "organización en la que trabajo."
            ),
            QuestionLang.EN: (
                "Cultural diversity is valued in the practices of the organization where "
                "I work."
            ),
        },
    ),
    (
        Dimension.S4,
        "A organização integra conteúdos e perspetivas de diferentes culturas.",
        {
            QuestionLang.ES: (
                "La organización integra contenidos y perspectivas de diferentes "
                "culturas."
            ),
            QuestionLang.EN: (
                "The organization integrates content and perspectives from different "
                "cultures."
            ),
        },
    ),
    (
        Dimension.S4,
        (
            "As práticas da organização em que atuo contribuem para a redução de "
            "preconceitos."
        ),
        {
            QuestionLang.ES: (
                "Las prácticas de la organización en la que trabajo contribuyen a la "
                "reducción de prejuicios."
            ),
            QuestionLang.EN: (
                "The practices of the organization where I work contribute to reducing "
                "prejudice."
            ),
        },
    ),
    (
        Dimension.S4,
        "Diferenças culturais são tratadas como fonte de aprendizagem.",
        {
            QuestionLang.ES: (
                "Las diferencias culturales se tratan como fuente de aprendizaje."
            ),
            QuestionLang.EN: "Cultural differences are treated as a source of learning.",
        },
    ),
    (
        Dimension.S4,
        "A organização em que atuo promove justiça social, equidade e inclusão.",
        {
            QuestionLang.ES: (
                "La organización en la que trabajo promueve la justicia social, la "
                "equidad y la inclusión."
            ),
            QuestionLang.EN: (
                "The organization where I work promotes social justice, equity, and "
                "inclusion."
            ),
        },
    ),
    (
        Dimension.S4,
        (
            "Demonstro empatia e abertura ao interagir com pessoas de culturas e "
            "contextos diferentes."
        ),
        {
            QuestionLang.ES: (
                "Demuestro empatía y apertura al interactuar con personas de "
                "culturas y contextos diferentes."
            ),
            QuestionLang.EN: (
                "I show empathy and openness when interacting with people from different "
                "cultures and backgrounds."
            ),
        },
    ),
    # S5A: itens 26 a 32 do formulário
    (
        Dimension.S5A,
        (
            "Compreendo metodologias ativas como Design Thinking, Lean Startup e "
            "Effectuation."
        ),
        {
            QuestionLang.ES: (
                "Comprendo metodologías activas como Design Thinking, Lean Startup y "
                "Effectuation."
            ),
            QuestionLang.EN: (
                "I understand active methodologies such as Design Thinking, Lean "
                "Startup, and Effectuation."
            ),
        },
    ),
    (
        Dimension.S5A,
        "Vivencio e utilizo metodologias ativas na minha instituição ou organização.",
        {
            QuestionLang.ES: (
                "Vivencio y utilizo metodologías activas en mi institución u "
                "organización."
            ),
            QuestionLang.EN: (
                "I experience and use active methodologies in my institution or "
                "organization."
            ),
        },
    ),
    (
        Dimension.S5A,
        "Utilizo tecnologias digitais para ensinar ou aprender.",
        {
            QuestionLang.ES: "Utilizo tecnologías digitales para enseñar o aprender.",
            QuestionLang.EN: "I use digital technologies to teach or learn.",
        },
    ),
    (
        Dimension.S5A,
        "As metodologias utilizadas são culturalmente acessíveis.",
        {
            QuestionLang.ES: "Las metodologías utilizadas son culturalmente accesibles.",
            QuestionLang.EN: "The methodologies used are culturally accessible.",
        },
    ),
    (
        Dimension.S5A,
        "Jogos, simulações e desafios consideram a diversidade cultural.",
        {
            QuestionLang.ES: (
                "Los juegos, simulaciones y desafíos consideran la diversidad cultural."
            ),
            QuestionLang.EN: (
                "Games, simulations, and challenges take cultural diversity into account."
            ),
        },
    ),
    (
        Dimension.S5A,
        "Desenvolvo criatividade para propor soluções inovadoras.",
        {
            QuestionLang.ES: (
                "Desarrollo creatividad para proponer soluciones innovadoras."
            ),
            QuestionLang.EN: "I develop creativity to propose innovative solutions.",
        },
    ),
    (
        Dimension.S5A,
        "Aprendo a transformar ideias em ações empreendedoras concretas.",
        {
            QuestionLang.ES: (
                "Aprendo a transformar ideas en acciones emprendedoras concretas."
            ),
            QuestionLang.EN: (
                "I learn to turn ideas into concrete entrepreneurial actions."
            ),
        },
    ),
    # S5B: itens 33 a 40 do formulário
    (
        Dimension.S5B,
        "Prefiro aprender de forma autónoma e ao meu próprio ritmo.",
        {
            QuestionLang.ES: "Prefiero aprender de forma autónoma y a mi propio ritmo.",
            QuestionLang.EN: "I prefer to learn autonomously and at my own pace.",
        },
    ),
    (
        Dimension.S5B,
        (
            "Aprendo melhor em contextos colaborativos, com troca de experiências "
            "entre pares."
        ),
        {
            QuestionLang.ES: (
                "Aprendo mejor en contextos colaborativos, con intercambio de "
                "experiencias entre pares."
            ),
            QuestionLang.EN: (
                "I learn best in collaborative contexts, with an exchange of experiences "
                "among peers."
            ),
        },
    ),
    (
        Dimension.S5B,
        (
            "Integro critérios de sustentabilidade e impacto social nas "
            "metodologias que aplico."
        ),
        {
            QuestionLang.ES: (
                "Integro criterios de sostenibilidad e impacto social en las "
                "metodologías que aplico."
            ),
            QuestionLang.EN: (
                "I integrate sustainability and social impact criteria into the "
                "methodologies I apply."
            ),
        },
    ),
    (
        Dimension.S5B,
        (
            "Reconheço meus próprios padrões de aprendizagem e ajusto estratégias "
            "para aprender com mais eficácia."
        ),
        {
            QuestionLang.ES: (
                "Reconozco mis propios patrones de aprendizaje y ajusto mis "
                "estrategias para aprender con mayor eficacia."
            ),
            QuestionLang.EN: (
                "I recognize my own learning patterns and adjust my strategies to learn "
                "more effectively."
            ),
        },
    ),
    (
        Dimension.S5B,
        (
            "Aprendo com os erros e utilizo o feedback como oportunidade de "
            "reorganização e crescimento mental."
        ),
        {
            QuestionLang.ES: (
                "Aprendo de los errores y utilizo la retroalimentación como "
                "oportunidad de reorganización y crecimiento mental."
            ),
            QuestionLang.EN: (
                "I learn from mistakes and use feedback as an opportunity for "
                "reorganization and mental growth."
            ),
        },
    ),
    (
        Dimension.S5B,
        (
            "Compreendo que a prática deliberada e a repetição fortalecem conexões "
            "neurais e consolidam novos saberes."
        ),
        {
            QuestionLang.ES: (
                "Comprendo que la práctica deliberada y la repetición fortalecen las "
                "conexiones neuronales y consolidan nuevos saberes."
            ),
            QuestionLang.EN: (
                "I understand that deliberate practice and repetition strengthen neural "
                "connections and consolidate new knowledge."
            ),
        },
    ),
    (
        Dimension.S5B,
        (
            "Desenvolvo aprendizagens significativas mesmo em contextos sem acesso "
            "a tecnologia."
        ),
        {
            QuestionLang.ES: (
                "Desarrollo aprendizajes significativos incluso en contextos sin "
                "acceso a tecnología."
            ),
            QuestionLang.EN: (
                "I develop meaningful learning even in contexts without access to "
                "technology."
            ),
        },
    ),
    (
        Dimension.S5B,
        (
            "Reconheço meu próprio perfil de aprendizagem — individual ou coletivo,"
            " digital ou presencial — e uso esse autoconhecimento a meu favor."
        ),
        {
            QuestionLang.ES: (
                "Reconozco mi propio perfil de aprendizaje (individual o colectivo, "
                "digital o presencial) y uso ese autoconocimiento a mi favor."
            ),
            QuestionLang.EN: (
                "I recognize my own learning profile (individual or collective, digital "
                "or in-person) and use this self-knowledge to my advantage."
            ),
        },
    ),
    # S6: itens 41 a 46 do formulário
    (
        Dimension.S6,
        "Adapto minhas práticas às necessidades culturais de cada contexto.",
        {
            QuestionLang.ES: (
                "Adapto mis prácticas a las necesidades culturales de cada contexto."
            ),
            QuestionLang.EN: (
                "I adapt my practices to the cultural needs of each context."
            ),
        },
    ),
    (
        Dimension.S6,
        "Reconheço como a cultura influencia os processos de inovação e criação.",
        {
            QuestionLang.ES: (
                "Reconozco cómo la cultura influye en los procesos de innovación y "
                "creación."
            ),
            QuestionLang.EN: (
                "I recognize how culture influences innovation and creation processes."
            ),
        },
    ),
    (
        Dimension.S6,
        "Crio ambientes inclusivos onde perspectivas diversas são valorizadas.",
        {
            QuestionLang.ES: (
                "Creo ambientes inclusivos donde se valoran las perspectivas diversas."
            ),
            QuestionLang.EN: (
                "I create inclusive environments where diverse perspectives are valued."
            ),
        },
    ),
    (
        Dimension.S6,
        "Desenvolvo práticas que respeitam e celebram a diversidade cultural.",
        {
            QuestionLang.ES: (
                "Desarrollo prácticas que respetan y celebran la diversidad cultural."
            ),
            QuestionLang.EN: (
                "I develop practices that respect and celebrate cultural diversity."
            ),
        },
    ),
    (
        Dimension.S6,
        "Promovo equidade no acesso a oportunidades de inovação e desenvolvimento.",
        {
            QuestionLang.ES: (
                "Promuevo la equidad en el acceso a oportunidades de innovación y "
                "desarrollo."
            ),
            QuestionLang.EN: (
                "I promote equity in access to innovation and development opportunities."
            ),
        },
    ),
    (
        Dimension.S6,
        (
            "Sinto-me seguro(a) para expressar perspectivas diferentes e "
            "experimentar novas abordagens."
        ),
        {
            QuestionLang.ES: (
                "Me siento seguro(a) para expresar perspectivas diferentes y "
                "experimentar nuevos enfoques."
            ),
            QuestionLang.EN: (
                "I feel safe expressing different perspectives and trying new approaches."
            ),
        },
    ),
    # S7: itens 47 a 52 do formulário
    (
        Dimension.S7,
        (
            "Possuo consciência profunda sobre minha própria identidade e bagagem "
            "cultural."
        ),
        {
            QuestionLang.ES: (
                "Tengo una conciencia profunda de mi propia identidad y bagaje cultural."
            ),
            QuestionLang.EN: (
                "I have a deep awareness of my own identity and cultural background."
            ),
        },
    ),
    (
        Dimension.S7,
        "Navego com eficácia entre diferentes sistemas de valores e crenças.",
        {
            QuestionLang.ES: (
                "Me desenvuelvo con eficacia entre diferentes sistemas de valores y "
                "creencias."
            ),
            QuestionLang.EN: (
                "I navigate effectively between different value and belief systems."
            ),
        },
    ),
    (
        Dimension.S7,
        "Transformo tensões e conflitos culturais em oportunidades de cocriação.",
        {
            QuestionLang.ES: (
                "Transformo tensiones y conflictos culturales en oportunidades de "
                "cocreación."
            ),
            QuestionLang.EN: (
                "I turn cultural tensions and conflicts into opportunities for "
                "co-creation."
            ),
        },
    ),
    (
        Dimension.S7,
        (
            "Contribuo para a construção de culturas organizacionais mais "
            "inovadoras e inclusivas."
        ),
        {
            QuestionLang.ES: (
                "Contribuyo a la construcción de culturas organizacionales más "
                "innovadoras e inclusivas."
            ),
            QuestionLang.EN: (
                "I contribute to building more innovative and inclusive organizational "
                "cultures."
            ),
        },
    ),
    (
        Dimension.S7,
        (
            "Lidero com inteligência cultural em contextos de alta complexidade e "
            "diversidade."
        ),
        {
            QuestionLang.ES: (
                "Lidero con inteligencia cultural en contextos de alta complejidad y "
                "diversidad."
            ),
            QuestionLang.EN: (
                "I lead with cultural intelligence in highly complex and diverse "
                "contexts."
            ),
        },
    ),
    (
        Dimension.S7,
        (
            "Identifico oportunidades de inovação a partir da diversidade de "
            "contextos e perspectivas."
        ),
        {
            QuestionLang.ES: (
                "Identifico oportunidades de innovación a partir de la diversidad de "
                "contextos y perspectivas."
            ),
            QuestionLang.EN: (
                "I identify innovation opportunities from the diversity of contexts and "
                "perspectives."
            ),
        },
    ),
    # S8: itens 53 a 58 do formulário
    (
        Dimension.S8,
        (
            "Oriento meus projetos e iniciativas para gerar impacto social positivo"
            " e duradouro."
        ),
        {
            QuestionLang.ES: (
                "Oriento mis proyectos e iniciativas para generar un impacto social "
                "positivo y duradero."
            ),
            QuestionLang.EN: (
                "I guide my projects and initiatives to generate positive and lasting "
                "social impact."
            ),
        },
    ),
    (
        Dimension.S8,
        "Considero implicações éticas na criação e aplicação de inovações.",
        {
            QuestionLang.ES: (
                "Considero las implicaciones éticas en la creación y aplicación de "
                "innovaciones."
            ),
            QuestionLang.EN: (
                "I consider ethical implications in the creation and application of "
                "innovations."
            ),
        },
    ),
    (
        Dimension.S8,
        "Desenvolvo soluções que endereçam desafios sistêmicos e estruturais.",
        {
            QuestionLang.ES: (
                "Desarrollo soluciones que abordan desafíos sistémicos y estructurales."
            ),
            QuestionLang.EN: (
                "I develop solutions that address systemic and structural challenges."
            ),
        },
    ),
    (
        Dimension.S8,
        "Meço e comunico o impacto concreto das minhas contribuições.",
        {
            QuestionLang.ES: "Mido y comunico el impacto concreto de mis contribuciones.",
            QuestionLang.EN: (
                "I measure and communicate the concrete impact of my contributions."
            ),
        },
    ),
    (
        Dimension.S8,
        (
            "Construo legados que transcendem meu contexto e beneficiam comunidades"
            " mais amplas."
        ),
        {
            QuestionLang.ES: (
                "Construyo legados que trascienden mi contexto y benefician a "
                "comunidades más amplias."
            ),
            QuestionLang.EN: (
                "I build legacies that transcend my context and benefit broader "
                "communities."
            ),
        },
    ),
    (
        Dimension.S8,
        (
            "Incorporo princípios de responsabilidade social e governança nas "
            "minhas iniciativas de inovação."
        ),
        {
            QuestionLang.ES: (
                "Incorporo principios de responsabilidad social y gobernanza en mis "
                "iniciativas de innovación."
            ),
            QuestionLang.EN: (
                "I incorporate principles of social responsibility and governance into "
                "my innovation initiatives."
            ),
        },
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
            QuestionTranslationRepository(session),
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
    translations: QuestionTranslationRepository,
) -> bool:
    """Cria o formulário do inventário, as perguntas, as alternativas e as traduções
    que faltam.

    Idempotente: cada pergunta e cada alternativa só entra se a posição dela ainda
    estiver vazia, e cada tradução só se a pergunta ainda não tiver aquele idioma,
    então rodar de novo não duplica nada. Diz se criou.
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

    for order_index, (dimensao, text, traducoes) in enumerate(INVENTORY_QUESTIONS):
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

        for lang, traducao in traducoes.items():
            if await translations.get_by_question_and_lang(question.id, lang) is not None:
                continue
            await translations.insert(
                QuestionTranslation(question_id=question.id, lang=lang, text=traducao)
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
