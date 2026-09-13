"""Testes do model do domínio documentos.

Sem banco: valida a definição do model e o enum. A criação da tabela em
si é coberta pela migration, aplicada e conferida no Postgres local.
"""

from app.domains.documentos.models import Documento, TipoDocumento


class TestTipoDocumento:
    def test_contem_os_sete_tipos_da_especificacao(self) -> None:
        esperados = {
            "CPF",
            "CNPJ",
            "NIF",
            "NIPC",
            "PASSAPORTE",
            "VAT_EU",
            "OUTRO",
        }
        assert {tipo.name for tipo in TipoDocumento} == esperados

    def test_valor_igual_ao_nome(self) -> None:
        for tipo in TipoDocumento:
            assert tipo.value == tipo.name


class TestDocumento:
    def test_nome_da_tabela(self) -> None:
        assert Documento.__tablename__ == "documentos"

    def test_colunas_esperadas(self) -> None:
        esperadas = {"id", "usuario_id", "tipo", "valor", "pais_emissor"}
        assert set(Documento.__table__.columns.keys()) == esperadas
