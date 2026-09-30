"""Testes de forma dos models do domínio links.

Sem banco: lê `Link.__table__` e `User.__table__` direto, então não precisa do
`docker compose up -d db`. O que se prova é a forma da tabela — nulabilidade, índice e
FK —, não uma regra de negócio (isso ainda não existe: a task 1 só prepara o banco).
"""

from sqlalchemy import Table, UniqueConstraint

from app.domains.links.models import Link, LinkType, Roles
from app.domains.users.models import User

NULLABLE_COLUMNS = {"department_id", "end_at", "updated_at"}


class TestLinksTable:
    def test_has_ten_columns_with_expected_nullability(self) -> None:
        columns = Link.__table__.columns

        names = {
            "id",
            "participant_id",
            "organization_id",
            "department_id",
            "type",
            "role",
            "start_at",
            "end_at",
            "created_at",
            "updated_at",
        }
        assert {c.name for c in columns} == names

        for column in columns:
            expected_nullable = column.name in NULLABLE_COLUMNS
            assert column.nullable is expected_nullable, (
                f"{column.name}: nullable={column.nullable}, esperado {expected_nullable}"
            )

    def test_has_no_foreign_key(self) -> None:
        """Participant, Organization e Department ainda não têm tabela."""
        assert Link.__table__.foreign_keys == set()

    def test_has_index_on_the_three_reference_columns(self) -> None:
        indexed_columns = {c.name for c in Link.__table__.columns if c.index}

        assert indexed_columns == {"participant_id", "organization_id", "department_id"}

    def test_has_no_unique_constraint(self) -> None:
        """O `.dbml` não define uma (spec, "Abordagem técnica", item 6)."""
        # `__table__` é tipado como FromClause; `.constraints` só existe em Table.
        table = Link.__table__
        assert isinstance(table, Table)

        uniques = [
            constraint
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        ]

        assert uniques == []

    def test_link_type_has_exactly_four_values(self) -> None:
        assert {link_type.value for link_type in LinkType} == {
            "emprego",
            "mentoria",
            "academico",
            "pessoal",
        }

    def test_roles_has_exactly_the_three_roles_from_p006(self) -> None:
        assert {role.value for role in Roles} == {"admin", "gestor", "respondente"}


class TestUserLinkIdColumn:
    def test_is_nullable(self) -> None:
        assert User.__table__.c.link_id.nullable is True

    def test_is_unique(self) -> None:
        assert User.__table__.c.link_id.unique is True

    def test_has_fk_to_links(self) -> None:
        fks = User.__table__.c.link_id.foreign_keys
        assert len(fks) == 1
        assert next(iter(fks)).target_fullname == "links.id"
