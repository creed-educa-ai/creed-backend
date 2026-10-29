"""consolida as tabelas da sprint 3

Revision ID: c6625156d816
Revises: d53324b9b5a2
Create Date: 2026-10-29 01:35:06.717426

Consolidação da sprint 3 (ADR-0009), primeira de duas revisões. Esta leva o que é
**estrutura nova**: tabelas, tipos e uma coluna nulável. A seguinte
(`liga as tabelas da sprint 3`) leva as FKs sobre colunas que já têm linhas, que é o
que pode falhar num banco com dados. Separadas, quem cai na conferência da segunda
consegue subir até esta, criar o que falta e seguir (ver a docstring dela).

O que entra, com o PR que pediu na seção "Banco":

- `organizations` (#44), `departments` (#36), `question_options` (#43),
  `dashboards` (#34), `insights` (#33), `insight_prismas` (#39) e `demographics`,
  `demographic_ethnicities` e `demographic_religions` (#46);
- `questions.dimensao`, nulável, com o tipo novo `dimension` (#38);
- o tipo `prisma` trocado pelos cinco valores do material do produto (#39).

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
[x] Autogenerate foi lido linha a linha. Ajustes à mão, todos pedidos nas seções
    "Banco" dos PRs:
    - `organizations.status` usa o tipo `recordstatus`, que já existe (`user` e
      `participants`): `create_type=False`, senão o `CREATE TABLE` tenta recriá-lo
      e o `upgrade` quebra (#44).
    - `questions.dimensao`: o `add_column` não cria tipo enum, então `dimension` é
      criado antes, explicitamente (#44, "fora deste PR").
    - `prisma`: o autogenerate não compara valores de enum e não viu a troca. O
      tipo antigo é renomeado, o novo é criado, `questions.prisma` passa para o
      novo e o antigo sai. `insight_prismas` usa o novo com `create_type=False`
      (#39).
    - As quatro FKs sobre `links`, `form` e `answer` saíram daqui para a revisão
      seguinte. Foram reagrupadas, sem mudar nenhuma.
    - O `downgrade` apaga os tipos criados aqui, que o `drop_table` deixa para trás,
      e devolve o `prisma` antigo.
[x] Renomeação virou drop+create? Não há renomeação de coluna. O tipo `prisma` é
    trocado, e não renomeado valor a valor: não há correspondência definida entre os
    valores antigos e os novos (decisão do Luís em 2026-10-29).
[x] Mudança destrutiva foi dividida em passos? A única é a troca de `prisma`, e ela
    só roda com `questions.prisma` vazio: a conferência abaixo para a revisão se
    houver pergunta classificada, em vez de apagar a classificação em silêncio.
[x] `alembic heads` conferido antes de abrir o PR: uma head só, a revisão seguinte.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c6625156d816"
down_revision: str | None = "d53324b9b5a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Os valores são os nomes dos membros: é o que o `Enum` do SQLAlchemy grava.
PRISMA_ANTIGO = (
    "HUMAN_PLASTICITY",
    "ENTREPRENEURSHIP",
    "MULTICULTURALISM",
    "NEUROINNOVATION",
    "DECISION_MAKING",
)
PRISMA_NOVO = (
    "SEGURANCA_PSICOLOGICA",
    "LIDERANCA_ADAPTATIVA",
    "CULTURA_EMPREENDEDORA",
    "ADAPTABILIDADE_COGNITIVA",
    "NEUROINOVACAO_PRISMA",
)

# Criados pelo `CREATE TABLE` (ou à mão, `dimension`) e apagados no `downgrade`.
TIPOS_NOVOS = (
    "dimension",
    "department_type",
    "gender",
    "agerange",
    "nationality",
    "brazilstate",
    "portugalregion",
    "ethnicity",
    "religion",
)


def upgrade() -> None:
    _troca_o_tipo_prisma(para=PRISMA_NOVO)

    postgresql.ENUM("S2", "S4", "S5A", "S5B", "S6", "S7", "S8", name="dimension").create(
        op.get_bind(), checkfirst=True
    )
    op.add_column(
        "questions",
        sa.Column(
            "dimensao",
            postgresql.ENUM(name="dimension", create_type=False),
            nullable=True,
        ),
    )

    op.create_table(
        "organizations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("ACTIVE", "INACTIVE", name="recordstatus", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_organizations_document_id_documents",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_organizations_document_id"),
    )

    op.create_table(
        "departments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "MARKETING",
                "FINANCEIRO",
                "ADMINISTRATIVO",
                "RECURSOS_HUMANOS",
                "TECNOLOGIA_INFORMACAO",
                name="department_type",
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_departments_organization_id_organizations",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "type", name="uq_departments_organization_type"
        ),
    )

    op.create_table(
        "question_options",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("question_id", sa.UUID(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.id"],
            name="fk_question_options_question_id_questions",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_id",
            "order_index",
            name="uq_question_options_question_id_order_index",
        ),
    )
    op.create_index(
        op.f("ix_question_options_question_id"),
        "question_options",
        ["question_id"],
        unique=False,
    )

    op.create_table(
        "dashboards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("form_id", sa.UUID(), nullable=False),
        sa.Column("is_private", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["form_id"],
            ["form_responses.id"],
            name="fk_dashboard_form_id_form_responses",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="fk_dashboard_user_id_user"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_dashboards_form_id"), "dashboards", ["form_id"], unique=False
    )
    op.create_index(
        op.f("ix_dashboards_user_id"), "dashboards", ["user_id"], unique=False
    )

    op.create_table(
        "insights",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("form_response_id", sa.UUID(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["form_response_id"],
            ["form_responses.id"],
            name="fk_insights_form_response_id_form_responses",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_insights_form_response_id"),
        "insights",
        ["form_response_id"],
        unique=False,
    )

    op.create_table(
        "insight_prismas",
        sa.Column("insight_id", sa.UUID(), nullable=False),
        sa.Column(
            "prisma",
            postgresql.ENUM(name="prisma", create_type=False),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["insight_id"],
            ["insights.id"],
            name="fk_insight_prismas_insight_id_insights",
        ),
        sa.PrimaryKeyConstraint("insight_id", "prisma"),
    )

    op.create_table(
        "demographics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("participant_id", sa.UUID(), nullable=False),
        sa.Column(
            "gender",
            sa.Enum(
                "FEMININO",
                "MASCULINO",
                "NAO_BINARIO",
                "PREFIRO_NAO_INFORMAR",
                name="gender",
            ),
            nullable=True,
        ),
        sa.Column(
            "age_range",
            sa.Enum(
                "AGE_18_25",
                "AGE_26_35",
                "AGE_36_45",
                "AGE_46_55",
                "AGE_56_65",
                "AGE_65_MAIS",
                "PREFIRO_NAO_INFORMAR",
                name="agerange",
            ),
            nullable=True,
        ),
        sa.Column(
            "nationality",
            sa.Enum("BRASILEIRA", "PORTUGUESA", "OUTRA", name="nationality"),
            nullable=True,
        ),
        sa.Column(
            "brazil_state",
            sa.Enum(
                "AC",
                "AL",
                "AP",
                "AM",
                "BA",
                "CE",
                "DF",
                "ES",
                "GO",
                "MA",
                "MT",
                "MS",
                "MG",
                "PA",
                "PB",
                "PR",
                "PE",
                "PI",
                "RJ",
                "RN",
                "RS",
                "RO",
                "RR",
                "SC",
                "SP",
                "SE",
                "TO",
                name="brazilstate",
            ),
            nullable=True,
        ),
        sa.Column(
            "portugal_region",
            sa.Enum(
                "NORTE",
                "CENTRO",
                "AREA_METROPOLITANA_LISBOA",
                "ALENTEJO",
                "ALGARVE",
                "ACORES",
                "MADEIRA",
                name="portugalregion",
            ),
            nullable=True,
        ),
        sa.Column("other_nationality", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "brazil_state IS NULL OR nationality IS NOT DISTINCT FROM 'BRASILEIRA'",
            name="ck_demographics_brazil_state_requires_brasileira",
        ),
        sa.CheckConstraint(
            "other_nationality IS NULL OR nationality IS NOT DISTINCT FROM 'OUTRA'",
            name="ck_demographics_other_nationality_requires_outra",
        ),
        sa.CheckConstraint(
            "portugal_region IS NULL OR nationality IS NOT DISTINCT FROM 'PORTUGUESA'",
            name="ck_demographics_portugal_region_requires_portuguesa",
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participants.id"],
            name="fk_demographics_participant_id_participants",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("participant_id", name="uq_demographics_participant_id"),
    )
    op.create_table(
        "demographic_ethnicities",
        sa.Column("demographic_id", sa.UUID(), nullable=False),
        sa.Column(
            "ethnicity",
            sa.Enum(
                "AFRICANA_AFRODESCENDENTE",
                "INDIGENA_AMERINDIA",
                "EUROPEIA",
                "ASIATICA",
                "ARABE_MEDIO_ORIENTE",
                "LATINO_AMERICANA",
                "ROMANI_CIGANA",
                "MULTIPLA_HIBRIDA",
                "PREFIRO_NAO_RESPONDER",
                name="ethnicity",
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["demographic_id"],
            ["demographics.id"],
            name="fk_demographic_ethnicities_demographic_id_demographics",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("demographic_id", "ethnicity"),
    )
    op.create_table(
        "demographic_religions",
        sa.Column("demographic_id", sa.UUID(), nullable=False),
        sa.Column(
            "religion",
            sa.Enum(
                "CRISTA",
                "JUDAICA",
                "ISLAMICA",
                "MATRIZ_AFRICANA",
                "ESPIRITISMO",
                "BUDISMO",
                "SEM_RELIGIAO",
                "OUTRA",
                "PREFIRO_NAO_RESPONDER",
                name="religion",
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["demographic_id"],
            ["demographics.id"],
            name="fk_demographic_religions_demographic_id_demographics",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("demographic_id", "religion"),
    )


def downgrade() -> None:
    op.drop_table("demographic_religions")
    op.drop_table("demographic_ethnicities")
    op.drop_table("demographics")
    op.drop_table("insight_prismas")
    op.drop_index(op.f("ix_insights_form_response_id"), table_name="insights")
    op.drop_table("insights")
    op.drop_index(op.f("ix_dashboards_user_id"), table_name="dashboards")
    op.drop_index(op.f("ix_dashboards_form_id"), table_name="dashboards")
    op.drop_table("dashboards")
    op.drop_index(op.f("ix_question_options_question_id"), table_name="question_options")
    op.drop_table("question_options")
    op.drop_table("departments")
    op.drop_table("organizations")
    op.drop_column("questions", "dimensao")

    for tipo in TIPOS_NOVOS:
        sa.Enum(name=tipo).drop(op.get_bind(), checkfirst=True)

    _troca_o_tipo_prisma(para=PRISMA_ANTIGO)


def _troca_o_tipo_prisma(*, para: tuple[str, ...]) -> None:
    """Troca os valores do tipo `prisma`, que só `questions.prisma` usa aqui.

    A conferência roda no Postgres, e não num `SELECT` lido pelo Python: assim ela
    também entra no script de `alembic upgrade --sql`. Dentro do `RAISE`, a mensagem
    não pode ter aspas simples nem `%`. Com a coluna vazia, o `USING` só converte
    nulos.
    """
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM questions WHERE prisma IS NOT NULL) THEN
                RAISE EXCEPTION 'Há pergunta(s) em questions com prisma preenchido, e a revisão c6625156d816 troca os cinco valores do tipo prisma (os antigos, de HUMAN_PLASTICITY a DECISION_MAKING, pelos do material do produto, de SEGURANCA_PSICOLOGICA a NEUROINOVACAO_PRISMA). Não há correspondência definida entre os valores antigos e os novos, e a revisão não apaga a classificação em silêncio. Decida o que fazer com essas perguntas (por exemplo, zerar com `UPDATE questions SET prisma = NULL WHERE prisma IS NOT NULL`) e rode a migração de novo.';
            END IF;
        END $$
        """
    )
    op.execute("ALTER TYPE prisma RENAME TO prisma_anterior")
    postgresql.ENUM(*para, name="prisma").create(op.get_bind())
    op.execute(
        "ALTER TABLE questions ALTER COLUMN prisma TYPE prisma USING prisma::text::prisma"
    )
    op.execute("DROP TYPE prisma_anterior")
