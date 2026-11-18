"""Testes do model do domínio insights.

Sem banco: lê a tabela direto do metadata do SQLAlchemy — o mesmo que `\\d insights`
mostraria no psql. Prova a forma da tabela (colunas, nulabilidade, FK, restrições,
índices); o comportamento real no Postgres está em `test_insights_postgres.py`.
"""

from typing import cast

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from app.domains.insights.models import Insight, InsightPrisma, InsightStatus
from app.domains.questions import models as questions_models
from app.shared.enums import Prisma

# `Insight.__table__` é tipado como `FromClause` (a base genérica); o cast dá acesso
# a `.indexes`/`.constraints`, que só existem em `Table`.
TABELA = cast(sa.Table, Insight.__table__)
TABELA_PRISMAS = cast(sa.Table, InsightPrisma.__table__)


def test_nome_da_tabela_no_plural() -> None:
    assert Insight.__tablename__ == "insights"


OBRIGATORIAS = {
    "id",
    "organization_id",
    "form_id",
    "status",
    "language",
    "attempts",
    "next_attempt_at",
    "created_at",
}
# Preenchidas só quando a esteira avança. `form_response_id` nulo é o insight da
# empresa (CREED-8013).
OPCIONAIS = {
    "form_response_id",
    "dispatched_at",
    "last_error",
    "content",
    "model_id",
    "prompt_version",
    "completed_at",
}


def test_tabela_tem_as_colunas_da_spec() -> None:
    colunas = {coluna.name for coluna in TABELA.columns}
    assert colunas == OBRIGATORIAS | OPCIONAIS


def test_so_as_colunas_da_esteira_aceitam_vazio() -> None:
    aceitam_vazio = {coluna.name for coluna in TABELA.columns if coluna.nullable}
    assert aceitam_vazio == OPCIONAIS


def test_content_e_jsonb() -> None:
    """O `InsightContent` validado: análise, um texto por prisma e recomendação."""
    assert isinstance(TABELA.columns["content"].type, JSONB)


def test_content_none_vira_null_do_banco() -> None:
    """Sem `none_as_null`, `content=None` vai como o JSON `null`, que o banco não
    vê como NULL: o CHECK recusaria o pedido pendente e aceitaria um `done` sem
    texto. Foi o teste Postgres que pegou; este guarda o conserto no CI comum,
    onde o teste Postgres fica de fora."""
    tipo = TABELA.columns["content"].type
    assert isinstance(tipo, JSONB)
    assert tipo.none_as_null is True


def test_status_tem_os_quatro_estados_da_esteira() -> None:
    assert [estado.value for estado in InsightStatus] == [
        "pending",
        "dispatched",
        "done",
        "failed",
    ]


def test_status_e_um_enum_do_postgres_com_o_nome_da_spec() -> None:
    tipo = TABELA.columns["status"].type
    assert isinstance(tipo, sa.Enum)
    assert tipo.enum_class is InsightStatus
    assert tipo.name == "insightstatus"


def test_pedido_novo_nasce_pending_sem_tentativa() -> None:
    """O padrão vale no Python e no banco: o INSERT direto também nasce `pending`."""
    status = TABELA.columns["status"]
    assert isinstance(status.default, sa.ColumnDefault)
    # Como `object`, porque o mypy tipa o `arg` como um callable e recusaria a
    # comparação com o membro do enum.
    status_padrao: object = status.default.arg
    assert status_padrao is InsightStatus.PENDING
    # O banco grava o NOME do membro, por isso 'PENDING' e não 'pending'.
    assert isinstance(status.server_default, sa.DefaultClause)
    assert str(status.server_default.arg) == "PENDING"

    tentativas = TABELA.columns["attempts"]
    assert isinstance(tentativas.default, sa.ColumnDefault)
    tentativas_padrao: object = tentativas.default.arg
    assert tentativas_padrao == 0
    assert isinstance(tentativas.server_default, sa.DefaultClause)
    assert str(tentativas.server_default.arg) == "0"


def test_chaves_estrangeiras_da_organizacao_do_periodo_e_da_resposta() -> None:
    fks = {fk.parent.name: (fk.target_fullname, fk.name) for fk in TABELA.foreign_keys}

    assert fks == {
        "organization_id": (
            "organizations.id",
            "fk_insights_organization_id_organizations",
        ),
        "form_id": ("form.id", "fk_insights_form_id_form"),
        "form_response_id": (
            "form_responses.id",
            "fk_insights_form_response_id_form_responses",
        ),
    }


def test_uma_resposta_um_insight() -> None:
    """P-042: o `unique` é de `form_response_id`, com nome, para o repository o
    reconhecer na violação."""
    unicas = {
        restricao.name: [coluna.name for coluna in restricao.columns]
        for restricao in TABELA.constraints
        if isinstance(restricao, sa.UniqueConstraint)
    }

    assert unicas == {"uq_insights_form_response_id": ["form_response_id"]}


def test_done_e_content_andam_juntos() -> None:
    checks = {
        restricao.name: str(restricao.sqltext)
        for restricao in TABELA.constraints
        if isinstance(restricao, sa.CheckConstraint)
    }

    # O banco grava o NOME do membro: 'DONE', não 'done'.
    assert checks["ck_insights_done_has_content"] == (
        "(status = 'DONE') = (content IS NOT NULL)"
    )


def test_idioma_so_aceita_os_da_tela_e_nasce_em_pt_br() -> None:
    checks = {
        restricao.name: str(restricao.sqltext)
        for restricao in TABELA.constraints
        if isinstance(restricao, sa.CheckConstraint)
    }
    coluna = TABELA.columns["language"]

    assert checks["ck_insights_language"] == "language IN ('pt-BR', 'en', 'es')"
    assert set(checks) == {"ck_insights_done_has_content", "ck_insights_language"}
    assert isinstance(coluna.server_default, sa.DefaultClause)
    assert coluna.server_default.arg == "pt-BR"


def test_indices_do_worker_do_dashboard_e_da_empresa_pendente() -> None:
    """O índice próprio de `form_response_id` saiu: o `unique` já cria um."""
    indices = {
        indice.name: ([coluna.name for coluna in indice.columns], indice.unique)
        for indice in TABELA.indexes
    }

    assert indices == {
        "ix_insights_status_next_attempt_at": (["status", "next_attempt_at"], False),
        "ix_insights_organization_id_form_id_created_at": (
            ["organization_id", "form_id", "created_at"],
            False,
        ),
        "uq_insights_organization_pending_per_form": (
            ["organization_id", "form_id"],
            True,
        ),
    }


def test_so_um_pedido_da_empresa_espera_por_periodo() -> None:
    """O índice parcial só vale para insight da empresa (sem resposta) pendente."""
    indice = next(
        indice
        for indice in TABELA.indexes
        if indice.name == "uq_insights_organization_pending_per_form"
    )

    onde = str(indice.dialect_options["postgresql"]["where"])

    assert onde == "form_response_id IS NULL AND status = 'PENDING'"


def test_nome_da_tabela_de_prismas() -> None:
    assert InsightPrisma.__tablename__ == "insight_prismas"


def test_tabela_de_prismas_tem_as_duas_colunas() -> None:
    colunas = {coluna.name for coluna in TABELA_PRISMAS.columns}
    assert colunas == {"insight_id", "prisma"}


def test_chave_primaria_e_composta() -> None:
    """Sem coluna `id` própria: o par insight + prisma é a identidade, e é o
    que impede associação duplicada."""
    pk = {coluna.name for coluna in TABELA_PRISMAS.primary_key.columns}
    assert pk == {"insight_id", "prisma"}


def test_a_unica_chave_estrangeira_e_insight_id() -> None:
    fks = {
        fk.parent.name: (fk.target_fullname, fk.name)
        for fk in TABELA_PRISMAS.foreign_keys
    }

    assert fks == {
        "insight_id": ("insights.id", "fk_insight_prismas_insight_id_insights")
    }


def test_prisma_tem_as_cinco_dimensoes_da_task() -> None:
    assert [item.value for item in Prisma] == [
        "seguranca_psicologica",
        "lideranca_adaptativa",
        "cultura_empreendedora",
        "adaptabilidade_cognitiva",
        "neuroinovacao_prisma",
    ]


def test_usa_o_mesmo_tipo_postgres_que_questions() -> None:
    """Uma definição só de `Prisma`, um tipo só no banco: a coluna de
    `questions` e a de `insight_prismas` apontam para `prisma`."""
    tipo = TABELA_PRISMAS.columns["prisma"].type
    assert isinstance(tipo, sa.Enum)
    assert tipo.name == "prisma"

    tabela_questions = cast(sa.Table, questions_models.Question.__table__)
    tipo_questions = tabela_questions.columns["prisma"].type
    assert isinstance(tipo_questions, sa.Enum)
    assert tipo_questions.name == tipo.name


def test_usa_a_mesma_classe_de_enum_que_questions() -> None:
    """Uma definição só: a coluna de `questions` usa a mesma classe."""
    tipo = cast(sa.Table, questions_models.Question.__table__).columns["prisma"].type
    assert isinstance(tipo, sa.Enum)
    assert tipo.enum_class is Prisma
