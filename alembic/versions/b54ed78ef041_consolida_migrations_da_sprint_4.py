"""consolida as mudanças de banco da sprint 4 e grava o instrumento CREED

Revision ID: b54ed78ef041
Revises: 41b7cec242e2
Create Date: 2026-11-12 23:08:59.235579

Consolidação da sprint 4 (ADR-0009). O que entra, com o PR que pediu na seção "Banco":

- `demographics.perspective`, nulável (#56);
- `form.opens_at`, `form.closes_at` e `form.link_id`, nuláveis, com índice e FK (#57);
- `organizations.email`, `contact_name` e `phone`, nuláveis, e `status` no tipo novo
  `organization_status` (#67);
- `question_translations` e `question_option_translations`, com o tipo
  `translation_lang` (#58);
- o instrumento: tabela `instruments`, `form.instrument_id` e `questions.instrument_id`
  no lugar de `questions.form_id`. A pergunta passa a ser do instrumento, e não do
  formulário, que é um período; todo período aplica as mesmas perguntas;
- `questionsection` com as seções do formulário original (S2 a S9), no lugar dos três
  valores provisórios da P-020;
- os dados do instrumento CREED: as 47 afirmações Likert (S2 a S8), com as cinco
  alternativas de 1 a 5 (o rótulo é o número), e as 3 perguntas abertas da S9, com as traduções ES e EN.

⚠️ Apaga os dados de teste do questionário. As perguntas que existiam eram de
demonstração e pertenciam a um formulário, e não há correspondência entre elas e as
do instrumento. Saem as perguntas e alternativas antigas e, porque apontam para elas,
todas as respostas (`answer`, `form_responses`) e o que aponta para as respostas
(`dashboards`, `insights`, `insight_prismas`). Confirmado pelo Leonardo em 2026-11-12:
nenhum ambiente tem resposta real a preservar.

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
[x] Autogenerate foi lido linha a linha. Ajustes à mão:
    - `organizations.status`: o autogenerate trocava o tipo sem criá-lo e sem
      converter o dado. Criado o tipo e convertido com `USING`, como pede o #67.
    - `form.instrument_id` é NOT NULL em tabela com linhas: entra com
      `server_default` no id do instrumento CREED, que já existe nessa hora, e o
      default sai em seguida (o model tem default só no Python).
    - `questions.instrument_id` é NOT NULL: entra depois de a tabela ser esvaziada.
    - `questionsection`: o autogenerate não compara valores de enum. O tipo é
      trocado com a tabela vazia, sem correspondência entre valores.
    - O `downgrade` apaga os tipos criados aqui e devolve os antigos.
[x] Renomeação virou drop+create? `questions.form_id` sai e `instrument_id` entra,
    mas não é renomeação: o alvo muda de tabela, e as linhas antigas saem antes.
[x] Mudança destrutiva foi dividida em passos? Não: os dados apagados são de teste,
    por decisão registrada acima. Sem dado a migrar, não há passo intermediário.
[x] `alembic heads` conferido antes de abrir o PR.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b54ed78ef041"
down_revision: str | None = "41b7cec242e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# O mesmo de `app/shared/instrument.py`. Copiado, e não importado: a migration não
# pode mudar de comportamento quando o código mudar.
CREED_INSTRUMENT_ID = uuid.UUID("00000000-0000-0000-0000-00000000c4ed")

# Ids das perguntas, alternativas e traduções derivados da posição, para a migration
# gravar sempre os mesmos ids em qualquer banco.
_NAMESPACE = uuid.UUID("5b0f6f3e-3f6a-4c55-9c1e-6b2a0c4ed000")

_OLD_SECTIONS = ("PROFILE", "ASSESSMENT", "CLOSING")
_NEW_SECTIONS = ("S2", "S4", "S5A", "S5B", "S6", "S7", "S8", "S9")

# A escala de 1 a 5 (P-040): o rótulo é o próprio número. O significado das pontas
# ("Discordo totalmente", "Concordo totalmente") é legenda da tela, traduzida no front.
_LIKERT = [("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("5", "5")]

# (seção, dimensão, texto em PT, ES, EN); a posição é o índice na lista.
_QUESTIONS = [
    (
        "S2",
        "S2",
        "Já fui fundador(a) ou sócio(a) de um negócio.",
        "He sido fundador(a) o socio(a) de un negocio.",
        "I have been a founder or partner in a business.",
    ),
    (
        "S2",
        "S2",
        "Já atuei como intraempreendedor(a) dentro de uma organização.",
        "He actuado como intraemprendedor(a) dentro de una organización.",
        "I have worked as an intrapreneur within an organization.",
    ),
    (
        "S2",
        "S2",
        "Participei do desenvolvimento de novos produtos, serviços ou negócios.",
        "He participado en el desarrollo de nuevos productos, servicios o negocios.",
        "I have taken part in developing new products, services, or businesses.",
    ),
    (
        "S2",
        "S2",
        "Atuei como mentor(a), avaliador(a) ou conselheiro(a) em iniciativas empreendedoras.",
        "He actuado como mentor(a), evaluador(a) o consejero(a) en iniciativas emprendedoras.",
        "I have acted as a mentor, evaluator, or advisor in entrepreneurial initiatives.",
    ),
    (
        "S2",
        "S2",
        "Tenho conexões com ecossistemas de empreendedorismo e inovação.",
        "Tengo conexiones con ecosistemas de emprendimiento e innovación.",
        "I have connections with entrepreneurship and innovation ecosystems.",
    ),
    (
        "S2",
        "S2",
        "Sou incentivado(a) a identificar oportunidades a partir de problemas sociais e culturais.",
        "Se me incentiva a identificar oportunidades a partir de problemas sociales y culturales.",
        "I am encouraged to identify opportunities arising from social and cultural problems.",
    ),
    (
        "S2",
        "S2",
        "Tomo decisões com segurança mesmo em situações incertas e com recursos limitados.",
        "Tomo decisiones con seguridad incluso en situaciones de incertidumbre y con recursos limitados.",
        "I make decisions confidently, even in uncertain situations with limited resources.",
    ),
    (
        "S2",
        "S2",
        "Persisto diante dos obstáculos e adapto minha abordagem ao longo do processo.",
        "Persisto ante los obstáculos y adapto mi enfoque a lo largo del proceso.",
        "I persist in the face of obstacles and adapt my approach throughout the process.",
    ),
    (
        "S4",
        "S4",
        "A diversidade cultural é valorizada nas práticas da organização em que atuo.",
        "La diversidad cultural es valorada en las prácticas de la organización en la que trabajo.",
        "Cultural diversity is valued in the practices of the organization where I work.",
    ),
    (
        "S4",
        "S4",
        "A organização integra conteúdos e perspetivas de diferentes culturas.",
        "La organización integra contenidos y perspectivas de diferentes culturas.",
        "The organization integrates content and perspectives from different cultures.",
    ),
    (
        "S4",
        "S4",
        "As práticas da organização em que atuo contribuem para a redução de preconceitos.",
        "Las prácticas de la organización en la que trabajo contribuyen a la reducción de prejuicios.",
        "The practices of the organization where I work contribute to reducing prejudice.",
    ),
    (
        "S4",
        "S4",
        "Diferenças culturais são tratadas como fonte de aprendizagem.",
        "Las diferencias culturales se tratan como fuente de aprendizaje.",
        "Cultural differences are treated as a source of learning.",
    ),
    (
        "S4",
        "S4",
        "A organização em que atuo promove justiça social, equidade e inclusão.",
        "La organización en la que trabajo promueve la justicia social, la equidad y la inclusión.",
        "The organization where I work promotes social justice, equity, and inclusion.",
    ),
    (
        "S4",
        "S4",
        "Demonstro empatia e abertura ao interagir com pessoas de culturas e contextos diferentes.",
        "Demuestro empatía y apertura al interactuar con personas de culturas y contextos diferentes.",
        "I show empathy and openness when interacting with people from different cultures and backgrounds.",
    ),
    (
        "S5A",
        "S5A",
        "Compreendo metodologias ativas como Design Thinking, Lean Startup e Effectuation.",
        "Comprendo metodologías activas como Design Thinking, Lean Startup y Effectuation.",
        "I understand active methodologies such as Design Thinking, Lean Startup, and Effectuation.",
    ),
    (
        "S5A",
        "S5A",
        "Vivencio e utilizo metodologias ativas na minha instituição ou organização.",
        "Vivencio y utilizo metodologías activas en mi institución u organización.",
        "I experience and use active methodologies in my institution or organization.",
    ),
    (
        "S5A",
        "S5A",
        "Utilizo tecnologias digitais para ensinar ou aprender.",
        "Utilizo tecnologías digitales para enseñar o aprender.",
        "I use digital technologies to teach or learn.",
    ),
    (
        "S5A",
        "S5A",
        "As metodologias utilizadas são culturalmente acessíveis.",
        "Las metodologías utilizadas son culturalmente accesibles.",
        "The methodologies used are culturally accessible.",
    ),
    (
        "S5A",
        "S5A",
        "Jogos, simulações e desafios consideram a diversidade cultural.",
        "Los juegos, simulaciones y desafíos consideran la diversidad cultural.",
        "Games, simulations, and challenges take cultural diversity into account.",
    ),
    (
        "S5A",
        "S5A",
        "Desenvolvo criatividade para propor soluções inovadoras.",
        "Desarrollo creatividad para proponer soluciones innovadoras.",
        "I develop creativity to propose innovative solutions.",
    ),
    (
        "S5A",
        "S5A",
        "Aprendo a transformar ideias em ações empreendedoras concretas.",
        "Aprendo a transformar ideas en acciones emprendedoras concretas.",
        "I learn to turn ideas into concrete entrepreneurial actions.",
    ),
    (
        "S5B",
        "S5B",
        "Prefiro aprender de forma autónoma e ao meu próprio ritmo.",
        "Prefiero aprender de forma autónoma y a mi propio ritmo.",
        "I prefer to learn autonomously and at my own pace.",
    ),
    (
        "S5B",
        "S5B",
        "Aprendo melhor em contextos colaborativos, com troca de experiências entre pares.",
        "Aprendo mejor en contextos colaborativos, con intercambio de experiencias entre pares.",
        "I learn best in collaborative contexts, with an exchange of experiences among peers.",
    ),
    (
        "S5B",
        "S5B",
        "Integro critérios de sustentabilidade e impacto social nas metodologias que aplico.",
        "Integro criterios de sostenibilidad e impacto social en las metodologías que aplico.",
        "I integrate sustainability and social impact criteria into the methodologies I apply.",
    ),
    (
        "S5B",
        "S5B",
        "Reconheço meus próprios padrões de aprendizagem e ajusto estratégias para aprender com mais eficácia.",
        "Reconozco mis propios patrones de aprendizaje y ajusto mis estrategias para aprender con mayor eficacia.",
        "I recognize my own learning patterns and adjust my strategies to learn more effectively.",
    ),
    (
        "S5B",
        "S5B",
        "Aprendo com os erros e utilizo o feedback como oportunidade de reorganização e crescimento mental.",
        "Aprendo de los errores y utilizo la retroalimentación como oportunidad de reorganización y crecimiento mental.",
        "I learn from mistakes and use feedback as an opportunity for reorganization and mental growth.",
    ),
    (
        "S5B",
        "S5B",
        "Compreendo que a prática deliberada e a repetição fortalecem conexões neurais e consolidam novos saberes.",
        "Comprendo que la práctica deliberada y la repetición fortalecen las conexiones neuronales y consolidan nuevos saberes.",
        "I understand that deliberate practice and repetition strengthen neural connections and consolidate new knowledge.",
    ),
    (
        "S5B",
        "S5B",
        "Desenvolvo aprendizagens significativas mesmo em contextos sem acesso a tecnologia.",
        "Desarrollo aprendizajes significativos incluso en contextos sin acceso a tecnología.",
        "I develop meaningful learning even in contexts without access to technology.",
    ),
    (
        "S5B",
        "S5B",
        "Reconheço meu próprio perfil de aprendizagem — individual ou coletivo, digital ou presencial — e uso esse autoconhecimento a meu favor.",
        "Reconozco mi propio perfil de aprendizaje (individual o colectivo, digital o presencial) y uso ese autoconocimiento a mi favor.",
        "I recognize my own learning profile (individual or collective, digital or in-person) and use this self-knowledge to my advantage.",
    ),
    (
        "S6",
        "S6",
        "Adapto minhas práticas às necessidades culturais de cada contexto.",
        "Adapto mis prácticas a las necesidades culturales de cada contexto.",
        "I adapt my practices to the cultural needs of each context.",
    ),
    (
        "S6",
        "S6",
        "Reconheço como a cultura influencia os processos de inovação e criação.",
        "Reconozco cómo la cultura influye en los procesos de innovación y creación.",
        "I recognize how culture influences innovation and creation processes.",
    ),
    (
        "S6",
        "S6",
        "Crio ambientes inclusivos onde perspectivas diversas são valorizadas.",
        "Creo ambientes inclusivos donde se valoran las perspectivas diversas.",
        "I create inclusive environments where diverse perspectives are valued.",
    ),
    (
        "S6",
        "S6",
        "Desenvolvo práticas que respeitam e celebram a diversidade cultural.",
        "Desarrollo prácticas que respetan y celebran la diversidad cultural.",
        "I develop practices that respect and celebrate cultural diversity.",
    ),
    (
        "S6",
        "S6",
        "Promovo equidade no acesso a oportunidades de inovação e desenvolvimento.",
        "Promuevo la equidad en el acceso a oportunidades de innovación y desarrollo.",
        "I promote equity in access to innovation and development opportunities.",
    ),
    (
        "S6",
        "S6",
        "Sinto-me seguro(a) para expressar perspectivas diferentes e experimentar novas abordagens.",
        "Me siento seguro(a) para expresar perspectivas diferentes y experimentar nuevos enfoques.",
        "I feel safe expressing different perspectives and trying new approaches.",
    ),
    (
        "S7",
        "S7",
        "Possuo consciência profunda sobre minha própria identidade e bagagem cultural.",
        "Tengo una conciencia profunda de mi propia identidad y bagaje cultural.",
        "I have a deep awareness of my own identity and cultural background.",
    ),
    (
        "S7",
        "S7",
        "Navego com eficácia entre diferentes sistemas de valores e crenças.",
        "Me desenvuelvo con eficacia entre diferentes sistemas de valores y creencias.",
        "I navigate effectively between different value and belief systems.",
    ),
    (
        "S7",
        "S7",
        "Transformo tensões e conflitos culturais em oportunidades de cocriação.",
        "Transformo tensiones y conflictos culturales en oportunidades de cocreación.",
        "I turn cultural tensions and conflicts into opportunities for co-creation.",
    ),
    (
        "S7",
        "S7",
        "Contribuo para a construção de culturas organizacionais mais inovadoras e inclusivas.",
        "Contribuyo a la construcción de culturas organizacionales más innovadoras e inclusivas.",
        "I contribute to building more innovative and inclusive organizational cultures.",
    ),
    (
        "S7",
        "S7",
        "Lidero com inteligência cultural em contextos de alta complexidade e diversidade.",
        "Lidero con inteligencia cultural en contextos de alta complejidad y diversidad.",
        "I lead with cultural intelligence in highly complex and diverse contexts.",
    ),
    (
        "S7",
        "S7",
        "Identifico oportunidades de inovação a partir da diversidade de contextos e perspectivas.",
        "Identifico oportunidades de innovación a partir de la diversidad de contextos y perspectivas.",
        "I identify innovation opportunities from the diversity of contexts and perspectives.",
    ),
    (
        "S8",
        "S8",
        "Oriento meus projetos e iniciativas para gerar impacto social positivo e duradouro.",
        "Oriento mis proyectos e iniciativas para generar un impacto social positivo y duradero.",
        "I guide my projects and initiatives to generate positive and lasting social impact.",
    ),
    (
        "S8",
        "S8",
        "Considero implicações éticas na criação e aplicação de inovações.",
        "Considero las implicaciones éticas en la creación y aplicación de innovaciones.",
        "I consider ethical implications in the creation and application of innovations.",
    ),
    (
        "S8",
        "S8",
        "Desenvolvo soluções que endereçam desafios sistêmicos e estruturais.",
        "Desarrollo soluciones que abordan desafíos sistémicos y estructurales.",
        "I develop solutions that address systemic and structural challenges.",
    ),
    (
        "S8",
        "S8",
        "Meço e comunico o impacto concreto das minhas contribuições.",
        "Mido y comunico el impacto concreto de mis contribuciones.",
        "I measure and communicate the concrete impact of my contributions.",
    ),
    (
        "S8",
        "S8",
        "Construo legados que transcendem meu contexto e beneficiam comunidades mais amplas.",
        "Construyo legados que trascienden mi contexto y benefician a comunidades más amplias.",
        "I build legacies that transcend my context and benefit broader communities.",
    ),
    (
        "S8",
        "S8",
        "Incorporo princípios de responsabilidade social e governança nas minhas iniciativas de inovação.",
        "Incorporo principios de responsabilidad social y gobernanza en mis iniciativas de innovación.",
        "I incorporate principles of social responsibility and governance into my innovation initiatives.",
    ),
    (
        "S9",
        None,
        "Quais práticas multiculturais poderiam ser incorporadas à educação empreendedora?",
        "¿Qué prácticas multiculturales podrían incorporarse a la educación emprendedora?",
        "Which multicultural practices could be incorporated into entrepreneurship education?",
    ),
    (
        "S9",
        None,
        "Quais desafios você observa para trabalhar a interculturalidade nas organizações?",
        "¿Qué desafíos observa para trabajar la interculturalidad en las organizaciones?",
        "What challenges do you see in working on interculturality in organizations?",
    ),
    (
        "S9",
        None,
        "Outras recomendações e sugestões.",
        "Otras recomendaciones y sugerencias.",
        "Other recommendations and suggestions.",
    ),
]


def _id(*parts: object) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, "/".join(str(part) for part in parts))


def upgrade() -> None:
    # Tabelas novas.
    op.create_table(
        "instruments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "question_translations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("question_id", sa.UUID(), nullable=False),
        sa.Column("lang", sa.Enum("EN", "ES", name="translation_lang"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.id"],
            name="fk_question_translations_question_id_questions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_id", "lang", name="uq_question_translations_question_id_lang"
        ),
    )
    op.create_index(
        op.f("ix_question_translations_question_id"),
        "question_translations",
        ["question_id"],
        unique=False,
    )
    op.create_table(
        "question_option_translations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("option_id", sa.UUID(), nullable=False),
        sa.Column(
            "lang",
            postgresql.ENUM("EN", "ES", name="translation_lang", create_type=False),
            nullable=False,
        ),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["option_id"],
            ["question_options.id"],
            name="fk_question_option_translations_option_id_question_options",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "option_id", "lang", name="uq_question_option_translations_option_id_lang"
        ),
    )
    op.create_index(
        op.f("ix_question_option_translations_option_id"),
        "question_option_translations",
        ["option_id"],
        unique=False,
    )

    # #56
    op.add_column(
        "demographics", sa.Column("perspective", sa.String(length=2000), nullable=True)
    )

    # #57
    op.add_column(
        "form", sa.Column("opens_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "form", sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("form", sa.Column("link_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_form_link_id"), "form", ["link_id"], unique=False)
    op.create_foreign_key("fk_form_link_id_links", "form", "links", ["link_id"], ["id"])

    # #67
    op.add_column(
        "organizations", sa.Column("email", sa.String(length=320), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("contact_name", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("phone", sa.String(length=30), nullable=True)
    )
    op.execute(
        "CREATE TYPE organization_status AS ENUM ('PENDING', 'ACTIVE', 'INACTIVE')"
    )
    op.execute(
        "ALTER TABLE organizations ALTER COLUMN status TYPE organization_status "
        "USING status::text::organization_status"
    )

    # Os dados de teste do questionário saem, de quem aponta para quem é apontado.
    op.execute("DELETE FROM insight_prismas")
    op.execute("DELETE FROM insights")
    op.execute("DELETE FROM dashboards")
    op.execute("DELETE FROM answer")
    op.execute("DELETE FROM form_responses")
    op.execute("DELETE FROM question_options")
    op.execute("DELETE FROM questions")

    # O instrumento, antes das colunas que apontam para ele.
    instruments = sa.table(
        "instruments", sa.column("id", sa.UUID()), sa.column("name", sa.Text())
    )
    op.bulk_insert(instruments, [{"id": CREED_INSTRUMENT_ID, "name": "Inventário CREED"}])

    op.add_column(
        "form",
        sa.Column(
            "instrument_id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text(f"'{CREED_INSTRUMENT_ID}'::uuid"),
        ),
    )
    op.alter_column("form", "instrument_id", server_default=None)
    op.create_index(
        op.f("ix_form_instrument_id"), "form", ["instrument_id"], unique=False
    )
    op.create_foreign_key(
        "fk_form_instrument_id_instruments",
        "form",
        "instruments",
        ["instrument_id"],
        ["id"],
    )

    # A pergunta sai do formulário e vai para o instrumento (tabela já vazia).
    op.drop_constraint("fk_questions_form_id_form", "questions", type_="foreignkey")
    op.drop_constraint("uq_questions_form_id_order_index", "questions", type_="unique")
    op.drop_index(op.f("ix_questions_form_id"), table_name="questions")
    op.drop_column("questions", "form_id")
    op.add_column("questions", sa.Column("instrument_id", sa.UUID(), nullable=False))
    op.create_index(
        op.f("ix_questions_instrument_id"), "questions", ["instrument_id"], unique=False
    )
    op.create_unique_constraint(
        "uq_questions_instrument_id_order_index",
        "questions",
        ["instrument_id", "order_index"],
    )
    op.create_foreign_key(
        "fk_questions_instrument_id_instruments",
        "questions",
        "instruments",
        ["instrument_id"],
        ["id"],
    )

    _swap_section_type(_NEW_SECTIONS)
    _insert_creed_instrument()


def downgrade() -> None:
    # Os dados do instrumento saem antes das colunas e tabelas que eles usam. As
    # traduções saem junto, pelo ON DELETE CASCADE.
    op.execute("DELETE FROM answer")
    op.execute("DELETE FROM question_options")
    op.execute("DELETE FROM questions")
    _swap_section_type(_OLD_SECTIONS)

    op.drop_constraint(
        "fk_questions_instrument_id_instruments", "questions", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_questions_instrument_id_order_index", "questions", type_="unique"
    )
    op.drop_index(op.f("ix_questions_instrument_id"), table_name="questions")
    op.drop_column("questions", "instrument_id")
    op.add_column("questions", sa.Column("form_id", sa.UUID(), nullable=False))
    op.create_index(op.f("ix_questions_form_id"), "questions", ["form_id"], unique=False)
    op.create_unique_constraint(
        "uq_questions_form_id_order_index", "questions", ["form_id", "order_index"]
    )
    op.create_foreign_key(
        "fk_questions_form_id_form", "questions", "form", ["form_id"], ["id"]
    )

    op.drop_constraint("fk_form_instrument_id_instruments", "form", type_="foreignkey")
    op.drop_index(op.f("ix_form_instrument_id"), table_name="form")
    op.drop_column("form", "instrument_id")

    # #67, na ordem que o PR pede.
    op.execute("UPDATE organizations SET status = 'INACTIVE' WHERE status = 'PENDING'")
    op.execute(
        "ALTER TABLE organizations ALTER COLUMN status TYPE recordstatus "
        "USING status::text::recordstatus"
    )
    op.execute("DROP TYPE organization_status")
    op.drop_column("organizations", "phone")
    op.drop_column("organizations", "contact_name")
    op.drop_column("organizations", "email")

    op.drop_constraint("fk_form_link_id_links", "form", type_="foreignkey")
    op.drop_index(op.f("ix_form_link_id"), table_name="form")
    op.drop_column("form", "link_id")
    op.drop_column("form", "closes_at")
    op.drop_column("form", "opens_at")

    op.drop_column("demographics", "perspective")

    op.drop_index(
        op.f("ix_question_option_translations_option_id"),
        table_name="question_option_translations",
    )
    op.drop_table("question_option_translations")
    op.drop_index(
        op.f("ix_question_translations_question_id"), table_name="question_translations"
    )
    op.drop_table("question_translations")
    op.execute("DROP TYPE translation_lang")
    op.drop_table("instruments")


def _swap_section_type(labels: tuple[str, ...]) -> None:
    """Troca os valores de `questionsection`. Só roda com `questions` vazia: não há
    correspondência entre os valores antigos e os novos."""
    op.execute("ALTER TYPE questionsection RENAME TO questionsection_old")
    values = ", ".join(f"'{label}'" for label in labels)
    op.execute(f"CREATE TYPE questionsection AS ENUM ({values})")
    op.execute(
        "ALTER TABLE questions ALTER COLUMN section TYPE questionsection "
        "USING section::text::questionsection"
    )
    op.execute("DROP TYPE questionsection_old")


def _insert_creed_instrument() -> None:
    questions = sa.table(
        "questions",
        sa.column("id", sa.UUID()),
        sa.column("instrument_id", sa.UUID()),
        sa.column("text", sa.Text()),
        sa.column("order_index", sa.Integer()),
        sa.column("type", postgresql.ENUM(name="questiontype", create_type=False)),
        sa.column("section", postgresql.ENUM(name="questionsection", create_type=False)),
        sa.column("required", sa.Boolean()),
        sa.column("prisma", postgresql.ENUM(name="prisma", create_type=False)),
        sa.column("dimensao", postgresql.ENUM(name="dimension", create_type=False)),
    )
    options = sa.table(
        "question_options",
        sa.column("id", sa.UUID()),
        sa.column("question_id", sa.UUID()),
        sa.column("label", sa.Text()),
        sa.column("value", sa.Text()),
        sa.column("order_index", sa.Integer()),
    )
    translations = sa.table(
        "question_translations",
        sa.column("id", sa.UUID()),
        sa.column("question_id", sa.UUID()),
        sa.column("lang", postgresql.ENUM(name="translation_lang", create_type=False)),
        sa.column("text", sa.Text()),
    )

    question_rows = []
    option_rows = []
    translation_rows = []
    for order_index, (section, dimension, text, es, en) in enumerate(_QUESTIONS):
        question_id = _id("question", order_index)
        objective = dimension is not None
        question_rows.append(
            {
                "id": question_id,
                "instrument_id": CREED_INSTRUMENT_ID,
                "text": text,
                "order_index": order_index,
                "type": "OBJECTIVE" if objective else "DESCRIPTIVE",
                "section": section,
                # As Likert são obrigatórias; as abertas da S9, opcionais.
                "required": objective,
                "prisma": None,
                "dimensao": dimension,
            }
        )
        for lang, translated in (("ES", es), ("EN", en)):
            translation_rows.append(
                {
                    "id": _id("question", order_index, lang),
                    "question_id": question_id,
                    "lang": lang,
                    "text": translated,
                }
            )
        if objective:
            for option_index, (value, label) in enumerate(_LIKERT):
                option_rows.append(
                    {
                        "id": _id("question", order_index, "option", option_index),
                        "question_id": question_id,
                        "label": label,
                        "value": value,
                        "order_index": option_index,
                    }
                )

    op.bulk_insert(questions, question_rows)
    op.bulk_insert(options, option_rows)
    op.bulk_insert(translations, translation_rows)
