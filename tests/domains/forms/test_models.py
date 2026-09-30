"""Testes do model Forms.

Sem banco: lê a descrição da tabela direto do código. Trava o que é
fácil de desfazer sem perceber.
"""

from app.domains.forms.models import Form, FormStatus


class TestForms:
    def test_table_name(self) -> None:
        assert Form.__tablename__ == "form"

    def test_columns(self) -> None:
        expected = {
            "id": False,
            "name": False,
            "organization_id": False,
            "status": False,
            "created_at": False,
        }

        assert {
            column.name: column.nullable for column in Form.__table__.columns
        } == expected

    def test_organization_id_has_index(self) -> None:
        organization_id = Form.__table__.c.organization_id

        assert organization_id.index is True

    def test_status_values(self) -> None:
        assert {status.name for status in FormStatus} == {
            "DRAFT",
            "PUBLISHED",
            "CLOSED",
        }

        assert {status.value for status in FormStatus} == {
            "draft",
            "published",
            "closed",
        }

    def test_foreign_keys(self) -> None:
        """A tabela de Vínculo ainda não existe."""
        assert Form.__table__.foreign_keys == set()
