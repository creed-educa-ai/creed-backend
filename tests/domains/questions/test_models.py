"""Testes do model do domínio questions.

Sem banco: lê a tabela direto do metadata do SQLAlchemy — o mesmo que `\\d questions`
mostraria no psql. Prova a forma da tabela (colunas, tipo, índice, constraint); o
comportamento real no Postgres é a migration (task 2).
"""

from typing import cast

import sqlalchemy as sa

from app.domains.questions.models import Question, QuestionSection, QuestionType
from app.shared.enums import Dimension, Prisma

# `Question.__table__` é tipado como `FromClause` (a base genérica); o cast dá acesso
# a `.indexes`/`.constraints`, que só existem em `Table`.
TABELA = cast(sa.Table, Question.__table__)

COLUNAS_OBRIGATORIAS = {
    "id",
    "form_id",
    "text",
    "order_index",
    "type",
    "section",
    "required",
    "created_at",
}


def test_tabela_tem_as_colunas_da_spec() -> None:
    colunas = {coluna.name for coluna in TABELA.columns}
    assert colunas == COLUNAS_OBRIGATORIAS | {"prisma", "dimensao"}


def test_prisma_e_dimensao_aceitam_vazio() -> None:
    for coluna in TABELA.columns:
        esperado = coluna.name in {"prisma", "dimensao"}
        assert coluna.nullable == esperado, (
            f"coluna {coluna.name}: nullable={coluna.nullable}, esperado {esperado}"
        )


def test_section_nao_tem_valor_padrao() -> None:
    coluna = TABELA.columns["section"]
    assert coluna.default is None
    assert coluna.server_default is None


def test_section_tem_so_os_tres_valores_provisorios() -> None:
    assert [item.value for item in QuestionSection] == [
        "profile",
        "assessment",
        "closing",
    ]


def test_type_tem_objetiva_e_descritiva() -> None:
    assert [item.value for item in QuestionType] == ["objective", "descriptive"]


def test_prisma_tem_as_cinco_dimensoes_do_material_do_produto() -> None:
    assert [item.value for item in Prisma] == [
        "seguranca_psicologica",
        "lideranca_adaptativa",
        "cultura_empreendedora",
        "adaptabilidade_cognitiva",
        "neuroinovacao_prisma",
    ]


def test_dimension_tem_as_sete_dimensoes_da_matriz() -> None:
    assert [item.value for item in Dimension] == [
        "S2",
        "S4",
        "S5A",
        "S5B",
        "S6",
        "S7",
        "S8",
    ]


def test_a_unica_chave_estrangeira_e_form_id() -> None:
    fks = {fk.parent.name: (fk.target_fullname, fk.name) for fk in TABELA.foreign_keys}

    assert fks == {"form_id": ("form.id", "fk_questions_form_id_form")}


def test_indice_existe_so_em_form_id() -> None:
    colunas_indexadas = {
        coluna.name for indice in TABELA.indexes for coluna in indice.columns
    }
    assert colunas_indexadas == {"form_id"}


def test_restricao_unica_em_form_id_e_order_index() -> None:
    restricoes = [
        constraint
        for constraint in TABELA.constraints
        if isinstance(constraint, sa.UniqueConstraint)
        and constraint.name == "uq_questions_form_id_order_index"
    ]
    assert len(restricoes) == 1
    assert {coluna.name for coluna in restricoes[0].columns} == {
        "form_id",
        "order_index",
    }
