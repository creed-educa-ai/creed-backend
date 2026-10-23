"""Testes do model de Sector."""

from sqlalchemy import Enum
from sqlalchemy.dialects.postgresql import UUID

from app.domains.sector.models import Sector, SectorType


class TestSector:
    def test_table_name(self) -> None:
        assert Sector.__tablename__ == "sector"

    def test_columns(self) -> None:
        assert Sector.__table__.c.id.nullable is False
        assert Sector.__table__.c.type.nullable is False

    def test_id_is_uuid_primary_key(self) -> None:
        column = Sector.__table__.c.id

        assert isinstance(column.type, UUID)
        assert column.primary_key is True

    def test_type_is_enum(self) -> None:
        column = Sector.__table__.c.type

        assert isinstance(column.type, Enum)
        assert column.type.name == "sector_type"

    def test_sector_type_values(self) -> None:
        assert {sector.value for sector in SectorType} == {
            "marketing",
            "financial",
            "administrative",
            "human_resources",
            "technology",
        }

    def test_foreign_keys(self) -> None:
        assert Sector.__table__.foreign_keys == set()
