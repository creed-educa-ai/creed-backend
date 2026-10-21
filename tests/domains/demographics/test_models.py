"""Testes do model do domínio demographics.

Sem banco: lê as tabelas direto do metadata do SQLAlchemy — o mesmo que
`\\d demographics` mostraria no psql. Prova a forma das tabelas (colunas,
nulabilidade, FK, unique, checks, enums); o comportamento real no Postgres é a
migration.
"""

import enum
from typing import cast

import pytest
import sqlalchemy as sa

from app.domains.demographics.models import (
    AgeRange,
    BrazilState,
    Demographic,
    DemographicEthnicity,
    DemographicReligion,
    Ethnicity,
    Gender,
    Nationality,
    PortugalRegion,
    Religion,
)

# `__table__` é tipado como `FromClause` (a base genérica); o cast dá acesso a
# `.constraints`, que só existe em `Table`.
TABLE = cast(sa.Table, Demographic.__table__)
ETHNICITIES_TABLE = cast(sa.Table, DemographicEthnicity.__table__)
RELIGIONS_TABLE = cast(sa.Table, DemographicReligion.__table__)


def _foreign_keys(table: sa.Table) -> dict[str, tuple[str, str | None, str | None]]:
    return {
        fk.parent.name: (fk.target_fullname, fk.name, fk.ondelete)
        for fk in table.foreign_keys
    }


def _check_constraints(table: sa.Table) -> dict[str, str]:
    return {
        str(constraint.name): str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }


def test_table_names() -> None:
    assert Demographic.__tablename__ == "demographics"
    assert DemographicEthnicity.__tablename__ == "demographic_ethnicities"
    assert DemographicReligion.__tablename__ == "demographic_religions"


def test_demographics_columns() -> None:
    columns = {column.name for column in TABLE.columns}
    assert columns == {
        "id",
        "participant_id",
        "gender",
        "age_range",
        "nationality",
        "brazil_state",
        "portugal_region",
        "other_nationality",
        "created_at",
        "updated_at",
    }


def test_only_identity_and_creation_are_required() -> None:
    """Todo dado do perfil é opcional: a pessoa pode não responder nada."""
    required = {column.name for column in TABLE.columns if not column.nullable}
    assert required == {"id", "participant_id", "created_at"}


def test_other_nationality_is_limited_to_100_characters() -> None:
    column_type = TABLE.columns["other_nationality"].type
    assert isinstance(column_type, sa.String)
    assert column_type.length == 100


def test_timestamps_follow_participants() -> None:
    assert TABLE.columns["created_at"].server_default is not None
    assert TABLE.columns["updated_at"].onupdate is not None


def test_the_only_foreign_key_is_participant_id() -> None:
    assert _foreign_keys(TABLE) == {
        "participant_id": (
            "participants.id",
            "fk_demographics_participant_id_participants",
            None,
        )
    }


def test_one_profile_per_participant() -> None:
    uniques = {
        constraint.name: {column.name for column in constraint.columns}
        for constraint in TABLE.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert uniques == {"uq_demographics_participant_id": {"participant_id"}}


def test_nationality_dependent_fields_have_named_checks() -> None:
    """Os checks comparam com o nome do membro (`'BRASILEIRA'`), que é o que o
    Postgres guarda: com o valor (`'brasileira'`) nunca bateriam."""
    assert _check_constraints(TABLE) == {
        "ck_demographics_brazil_state_requires_brasileira": (
            "brazil_state IS NULL OR nationality IS NOT DISTINCT FROM 'BRASILEIRA'"
        ),
        "ck_demographics_portugal_region_requires_portuguesa": (
            "portugal_region IS NULL OR nationality IS NOT DISTINCT FROM 'PORTUGUESA'"
        ),
        "ck_demographics_other_nationality_requires_outra": (
            "other_nationality IS NULL OR nationality IS NOT DISTINCT FROM 'OUTRA'"
        ),
    }


@pytest.mark.parametrize(
    ("table", "option_column"),
    [(ETHNICITIES_TABLE, "ethnicity"), (RELIGIONS_TABLE, "religion")],
    ids=["ethnicities", "religions"],
)
def test_option_tables_have_composite_primary_key(
    table: sa.Table, option_column: str
) -> None:
    """Sem `id` próprio: o par perfil + opção é a identidade, e é o que impede
    marcar a mesma opção duas vezes."""
    assert {column.name for column in table.columns} == {"demographic_id", option_column}
    assert {column.name for column in table.primary_key.columns} == {
        "demographic_id",
        option_column,
    }


def test_ethnicities_cascade_from_demographics() -> None:
    assert _foreign_keys(ETHNICITIES_TABLE) == {
        "demographic_id": (
            "demographics.id",
            "fk_demographic_ethnicities_demographic_id_demographics",
            "CASCADE",
        )
    }


def test_religions_cascade_from_demographics() -> None:
    assert _foreign_keys(RELIGIONS_TABLE) == {
        "demographic_id": (
            "demographics.id",
            "fk_demographic_religions_demographic_id_demographics",
            "CASCADE",
        )
    }


@pytest.mark.parametrize(
    ("table", "column", "enum_class", "postgres_name"),
    [
        (TABLE, "gender", Gender, "gender"),
        (TABLE, "age_range", AgeRange, "agerange"),
        (TABLE, "nationality", Nationality, "nationality"),
        (TABLE, "brazil_state", BrazilState, "brazilstate"),
        (TABLE, "portugal_region", PortugalRegion, "portugalregion"),
        (ETHNICITIES_TABLE, "ethnicity", Ethnicity, "ethnicity"),
        (RELIGIONS_TABLE, "religion", Religion, "religion"),
    ],
    ids=[
        "gender",
        "age_range",
        "nationality",
        "brazil_state",
        "portugal_region",
        "ethnicity",
        "religion",
    ],
)
def test_enum_columns_use_explicit_postgres_types(
    table: sa.Table, column: str, enum_class: type[enum.Enum], postgres_name: str
) -> None:
    column_type = table.columns[column].type
    assert isinstance(column_type, sa.Enum)
    assert column_type.enum_class is enum_class
    assert column_type.name == postgres_name


def test_gender_matches_the_frontend() -> None:
    assert [item.value for item in Gender] == [
        "feminino",
        "masculino",
        "nao_binario",
        "prefiro_nao_informar",
    ]


def test_age_range_matches_the_frontend() -> None:
    assert [item.value for item in AgeRange] == [
        "18_25",
        "26_35",
        "36_45",
        "46_55",
        "56_65",
        "65_mais",
        "prefiro_nao_informar",
    ]


def test_ethnicity_matches_the_frontend() -> None:
    assert [item.value for item in Ethnicity] == [
        "africana_afrodescendente",
        "indigena_amerindia",
        "europeia",
        "asiatica",
        "arabe_medio_oriente",
        "latino_americana",
        "romani_cigana",
        "multipla_hibrida",
        "prefiro_nao_responder",
    ]


def test_religion_matches_the_frontend() -> None:
    assert [item.value for item in Religion] == [
        "crista",
        "judaica",
        "islamica",
        "matriz_africana",
        "espiritismo",
        "budismo",
        "sem_religiao",
        "outra",
        "prefiro_nao_responder",
    ]


def test_nationality_matches_the_frontend() -> None:
    assert [item.value for item in Nationality] == ["brasileira", "portuguesa", "outra"]


def test_brazil_state_matches_the_frontend() -> None:
    """As 27 UFs na ordem do front: alfabética pelo nome do estado, não pela sigla."""
    assert [item.value for item in BrazilState] == [
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
        "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
        "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
    ]  # fmt: skip


def test_portugal_region_matches_the_frontend() -> None:
    assert [item.value for item in PortugalRegion] == [
        "norte",
        "centro",
        "area_metropolitana_lisboa",
        "alentejo",
        "algarve",
        "acores",
        "madeira",
    ]
