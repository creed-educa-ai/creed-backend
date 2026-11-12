"""Testes do model do domínio organizacoes.

Sem banco: valida a definição do model e as decisões de modelagem que a
tabela precisa preservar.
"""

from typing import cast

from sqlalchemy import Table, UniqueConstraint

from app.domains.organizacoes.models import Organization, OrganizationStatus
from app.domains.participants.models import Participant
from app.domains.users.models import User
from app.shared.enums import RecordStatus


class TestOrganization:
    def test_nome_da_tabela(self) -> None:
        """`links.organization_id` vai apontar para `organizations.id`."""
        assert Organization.__tablename__ == "organizations"

    def test_documento_aponta_para_documents(self) -> None:
        """[C3]: quem aponta é o dono."""
        coluna = Organization.__table__.columns["document_id"]
        alvos = {fk.target_fullname for fk in coluna.foreign_keys}
        assert alvos == {"documents.id"}
        assert not coluna.nullable

    def test_fk_do_documento_tem_o_nome_que_a_migration_usa(self) -> None:
        fk = next(iter(Organization.__table__.c.document_id.foreign_keys))
        assert fk.name == "fk_organizations_document_id_documents"

    def test_documento_e_unico_com_nome_explicito(self) -> None:
        """O repository reconhece a constraint pelo nome no IntegrityError."""
        tabela = cast(Table, Organization.__table__)
        uniques = {
            constraint.name: tuple(c.name for c in constraint.columns)
            for constraint in tabela.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert uniques.get("uq_organizations_document_id") == ("document_id",)

    def test_status_usa_o_enum_proprio_e_nasce_ativo(self) -> None:
        coluna = Organization.__table__.columns["status"]
        assert coluna.type.enum_class is OrganizationStatus  # type: ignore[attr-defined]
        assert coluna.type.name == "organization_status"  # type: ignore[attr-defined]
        assert not coluna.nullable
        assert coluna.default is not None
        assert coluna.default.arg is OrganizationStatus.ACTIVE

    def test_pendente_e_valor_so_da_organizacao(self) -> None:
        """`pending` não vaza para login e participante, que seguem no `recordstatus`."""
        assert OrganizationStatus("pending") is OrganizationStatus.PENDING
        for tabela in (User.__table__, Participant.__table__):
            coluna = tabela.columns["status"]
            assert coluna.type.enum_class is RecordStatus  # type: ignore[attr-defined]
        assert "pending" not in {membro.value for membro in RecordStatus}

    def test_dados_de_contato_sao_opcionais(self) -> None:
        """Só o cadastro público os preenche; o `POST /organizacoes` não os pede."""
        colunas = Organization.__table__.columns
        tamanhos = {"email": 320, "contact_name": 200, "phone": 30}
        for nome, tamanho in tamanhos.items():
            assert colunas[nome].nullable
            assert colunas[nome].type.length == tamanho  # type: ignore[attr-defined]

    def test_nome_e_endereco_sao_obrigatorios(self) -> None:
        colunas = Organization.__table__.columns
        assert not colunas["name"].nullable
        assert not colunas["address"].nullable
