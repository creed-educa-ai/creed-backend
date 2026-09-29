"""Testes do model Forms.

Sem banco: lê a descrição da tabela direto do código. Trava o que é
fácil de desfazer sem perceber.
"""

from app.domains.forms.models import Form


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
        assert {c.name: c.nullable for c in Form.__table__.columns} == expected

    def test_foreign_keys(self) -> None:
        """A tabela de Vínculo ainda não existe."""
        assert Form.__table__.foreign_keys == set()
