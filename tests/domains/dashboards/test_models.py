"""Testes dos models do domínio dashboards.

Sem banco: lê a descrição da tabela direto do código.
Verifica o nome da tabela, as colunas, a obrigatoriedade,
as chaves estrangeiras e os índices previstos para dashboards.
"""

from typing import cast

from sqlalchemy import Table

from app.domains.dashboards.models import Dashboard


def _fks(tabela: Table) -> dict[str, tuple[str, object]]:
    """Coluna -> (alvo, nome da constraint)."""
    return {fk.parent.name: (fk.target_fullname, fk.name) for fk in tabela.foreign_keys}


class TestDashboard:
    def test_nome_da_tabela(self) -> None:
        assert Dashboard.__tablename__ == "dashboards"

    def test_colunas_e_obrigatoriedade(self) -> None:
        esperado = {
            "id": False,
            "user_id": False,
            "form_id": False,
            "is_private": False,
            "created_at": False,
        }

        assert {
            coluna.name: coluna.nullable for coluna in Dashboard.__table__.columns
        } == esperado

    def test_chaves_estrangeiras(self) -> None:
        assert _fks(cast(Table, Dashboard.__table__)) == {
            "user_id": (
                "user.id",
                "fk_dashboard_user_id_user",
            ),
            "form_id": (
                "form_responses.id",
                "fk_dashboard_form_id_form_responses",
            ),
        }

    def test_tem_indice_em_user_id(self) -> None:
        tabela = cast(Table, Dashboard.__table__)

        colunas_indexadas = {
            coluna.name for indice in tabela.indexes for coluna in indice.columns
        }

        assert "user_id" in colunas_indexadas

    def test_tem_indice_em_form_id(self) -> None:
        tabela = cast(Table, Dashboard.__table__)

        colunas_indexadas = {
            coluna.name for indice in tabela.indexes for coluna in indice.columns
        }

        assert "form_id" in colunas_indexadas
