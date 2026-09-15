"""Testes do model do domínio documents.

Sem banco: valida a definição do model, o enum e as decisões de
modelagem que a tabela precisa preservar.
"""

from typing import cast

from sqlalchemy import Table, UniqueConstraint

from app.domains.documents.models import DocType, Document


class TestDocType:
    def test_contem_os_sete_tipos_da_especificacao(self) -> None:
        esperados = {
            "CPF",
            "CNPJ",
            "NIF",
            "NIPC",
            "PASSPORT",
            "VAT_EU",
            "OTHER",
        }
        assert {tipo.name for tipo in DocType} == esperados

    def test_valor_e_o_nome_em_minusculo(self) -> None:
        """Padrão de users (RecordStatus, UserRole): o .value sai na API."""
        for tipo in DocType:
            assert tipo.value == tipo.name.lower()


class TestDocument:
    def test_nome_da_tabela(self) -> None:
        assert Document.__tablename__ == "documents"

    def test_nao_tem_coluna_de_dono(self) -> None:
        """[C3]: quem aponta é o dono. Coluna de dono aqui é regressão."""
        colunas = set(Document.__table__.columns.keys())
        assert (
            not {
                "user_id",
                "usuario_id",
                "participant_id",
                "organization_id",
            }
            & colunas
        )

    def test_tipo_e_valor_sao_unicos_juntos(self) -> None:
        tabela = cast(Table, Document.__table__)
        uniques = {
            tuple(sorted(c.name for c in constraint.columns))
            for constraint in tabela.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert ("type", "value") in uniques
