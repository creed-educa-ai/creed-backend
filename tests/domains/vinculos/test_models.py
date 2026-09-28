"""Testes de forma dos models do domínio vinculos.

Sem banco: lê `Vinculo.__table__` e `User.__table__` direto, então não precisa do
`docker compose up -d db`. O que se prova é a forma da tabela — nulabilidade, índice e
FK —, não uma regra de negócio (isso ainda não existe: a task 1 só prepara o banco).
"""

from sqlalchemy import Table, UniqueConstraint

from app.domains.users.models import User
from app.domains.vinculos.models import Roles, VincType, Vinculo

COLUNAS_NULAVEIS = {"setor_id", "end_at", "updated_at"}


class TestTabelaVinculos:
    def test_tem_as_dez_colunas_com_a_nulabilidade_esperada(self) -> None:
        colunas = Vinculo.__table__.columns

        nomes = {
            "id",
            "participant_id",
            "organization_id",
            "setor_id",
            "type",
            "role",
            "start_at",
            "end_at",
            "created_at",
            "updated_at",
        }
        assert {c.name for c in colunas} == nomes

        for coluna in colunas:
            esperado_nulavel = coluna.name in COLUNAS_NULAVEIS
            assert coluna.nullable is esperado_nulavel, (
                f"{coluna.name}: nullable={coluna.nullable}, esperado {esperado_nulavel}"
            )

    def test_nao_tem_foreign_key(self) -> None:
        """Participant, Organization e Setor não têm tabela ainda (fora de escopo)."""
        assert Vinculo.__table__.foreign_keys == set()

    def test_tem_indice_nas_tres_colunas_de_referencia(self) -> None:
        colunas_indexadas = {c.name for c in Vinculo.__table__.columns if c.index}

        assert colunas_indexadas == {"participant_id", "organization_id", "setor_id"}

    def test_nao_tem_unique_constraint(self) -> None:
        """O `.dbml` não define uma (spec, "Abordagem técnica", item 6)."""
        # `__table__` é tipado como FromClause; `.constraints` só existe em Table.
        tabela = Vinculo.__table__
        assert isinstance(tabela, Table)

        uniques = [
            constraint
            for constraint in tabela.constraints
            if isinstance(constraint, UniqueConstraint)
        ]

        assert uniques == []

    def test_vinc_type_tem_exatamente_os_quatro_valores(self) -> None:
        assert {tipo.value for tipo in VincType} == {
            "emprego",
            "mentoria",
            "academico",
            "pessoal",
        }

    def test_roles_tem_exatamente_os_tres_papeis_da_p006(self) -> None:
        assert {papel.value for papel in Roles} == {"admin", "gestor", "respondente"}


class TestColunaVinculoIdEmUser:
    def test_e_nulavel(self) -> None:
        assert User.__table__.c.vinculo_id.nullable is True

    def test_e_unica(self) -> None:
        assert User.__table__.c.vinculo_id.unique is True

    def test_tem_fk_para_vinculos(self) -> None:
        fks = User.__table__.c.vinculo_id.foreign_keys
        assert len(fks) == 1
        assert next(iter(fks)).target_fullname == "vinculos.id"
