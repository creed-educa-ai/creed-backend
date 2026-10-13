"""Testes do model do domínio insights.

Sem banco: lê a tabela direto do metadata do SQLAlchemy — o mesmo que `\\d insights`
mostraria no psql. Prova a forma da tabela (colunas, nulabilidade, FK, índice); o
comportamento real no Postgres é a migration.
"""

from typing import cast

import sqlalchemy as sa

from app.domains.insights.models import Insight, InsightPrisma, Prisma

# `Insight.__table__` é tipado como `FromClause` (a base genérica); o cast dá acesso
# a `.indexes`/`.constraints`, que só existem em `Table`.
TABELA = cast(sa.Table, Insight.__table__)
TABELA_PRISMAS = cast(sa.Table, InsightPrisma.__table__)


def test_nome_da_tabela_no_plural() -> None:
    assert Insight.__tablename__ == "insights"


def test_tabela_tem_as_quatro_colunas_da_spec() -> None:
    colunas = {coluna.name for coluna in TABELA.columns}
    assert colunas == {"id", "form_response_id", "content", "created_at"}


def test_nenhuma_coluna_aceita_vazio() -> None:
    for coluna in TABELA.columns:
        assert not coluna.nullable, f"coluna {coluna.name} não deveria aceitar vazio"


def test_content_e_texto_livre() -> None:
    """O tamanho do insight varia conforme o relatório gerado."""
    assert isinstance(TABELA.columns["content"].type, sa.Text)


def test_a_unica_chave_estrangeira_e_form_response_id() -> None:
    fks = {fk.parent.name: (fk.target_fullname, fk.name) for fk in TABELA.foreign_keys}

    assert fks == {
        "form_response_id": (
            "form_responses.id",
            "fk_insights_form_response_id_form_responses",
        )
    }


def test_indice_existe_so_em_form_response_id() -> None:
    colunas_indexadas = {
        coluna.name for indice in TABELA.indexes for coluna in indice.columns
    }
    assert colunas_indexadas == {"form_response_id"}


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


def test_tipo_do_enum_nao_colide_com_o_de_questions() -> None:
    """Nome próprio no Postgres: o enum `Prisma` de questions usa outro
    conjunto de valores e já ocupa o tipo `prisma`."""
    tipo = TABELA_PRISMAS.columns["prisma"].type
    assert isinstance(tipo, sa.Enum)
    assert tipo.name == "insight_prisma"
