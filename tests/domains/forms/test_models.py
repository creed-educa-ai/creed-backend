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

    def test_organization_id_tem_fk_para_organizations(self) -> None:
        """A CREED-47 deixou esta FK para quando `organizations` existisse (D1)."""
        fks = {fk.parent.name: fk.target_fullname for fk in Form.__table__.foreign_keys}

        assert fks == {"organization_id": "organizations.id"}

    def test_fk_de_organizacao_tem_o_nome_que_a_migration_usa(self) -> None:
        fk = next(iter(Form.__table__.c.organization_id.foreign_keys))

        assert fk.name == "fk_form_organization_id_organizations"
