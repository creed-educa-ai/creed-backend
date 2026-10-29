"""Testes do model de Department."""

from sqlalchemy import Enum
from sqlalchemy.dialects.postgresql import UUID

from app.domains.department.models import Department, DepartmentType


def test_table_name() -> None:
    assert Department.__tablename__ == "departments"


def test_columns() -> None:
    assert Department.__table__.c.id.nullable is False
    assert Department.__table__.c.organization_id.nullable is False
    assert Department.__table__.c.type.nullable is False


def test_id_is_uuid_primary_key() -> None:
    column = Department.__table__.c.id

    assert isinstance(column.type, UUID)
    assert column.primary_key is True


def test_type_is_enum() -> None:
    column = Department.__table__.c.type

    assert isinstance(column.type, Enum)
    assert column.type.name == "department_type"


def test_department_type_values() -> None:
    assert {item.value for item in DepartmentType} == {
        "Marketing",
        "Financeiro",
        "Administrativo",
        "RecursosHumanos",
        "TecnologiaInformacao",
    }


def test_foreign_keys() -> None:
    foreign_keys = Department.__table__.c.organization_id.foreign_keys

    assert len(foreign_keys) == 1
    assert next(iter(foreign_keys)).target_fullname == "organizations.id"


def test_organization_fk_has_the_name_the_migration_uses() -> None:
    fk = next(iter(Department.__table__.c.organization_id.foreign_keys))

    assert fk.name == "fk_departments_organization_id_organizations"
