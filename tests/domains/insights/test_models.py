"""Testes do model do domínio insights.

Sem banco: lê a tabela direto do metadata do SQLAlchemy — o mesmo que `\\d insights`
mostraria no psql. Prova a forma da tabela (colunas, nulabilidade, FK, índice); o
comportamento real no Postgres é a migration.
"""

from typing import cast

import sqlalchemy as sa

from app.domains.insights.models import Insight

# `Insight.__table__` é tipado como `FromClause` (a base genérica); o cast dá acesso
# a `.indexes`/`.constraints`, que só existem em `Table`.
TABELA = cast(sa.Table, Insight.__table__)


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
