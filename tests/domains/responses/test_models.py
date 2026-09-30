"""Testes dos models do domínio responses.

Sem banco: lê a descrição da tabela direto do código. Trava o que é
fácil de desfazer sem perceber — uma das duas colunas de resposta
virando obrigatória, ou uma FK sumindo ou ganhando outro nome, que
deixaria o model diferente da migration `d53324b9b5a2`.
"""

from typing import cast

from sqlalchemy import Table

from app.domains.responses.models import Answer, FormResponse


def _fks(tabela: Table) -> dict[str, tuple[str, object]]:
    """Coluna -> (alvo, nome da constraint)."""
    return {fk.parent.name: (fk.target_fullname, fk.name) for fk in tabela.foreign_keys}


class TestAnswer:
    def test_nome_da_tabela(self) -> None:
        assert Answer.__tablename__ == "answer"

    def test_colunas_e_obrigatoriedade(self) -> None:
        """As duas formas de resposta aceitam vazio: cada tipo de pergunta
        preenche uma delas. A resposta de formulário é obrigatória."""
        esperado = {
            "id": False,
            "form_response_id": False,
            "question_id": False,
            "option_id": True,
            "value": True,
            "created_at": False,
        }
        assert {c.name: c.nullable for c in Answer.__table__.columns} == esperado

    def test_chaves_estrangeiras(self) -> None:
        """`option_id` fica sem FK até a tabela de alternativas (CREED-37)."""
        assert _fks(cast(Table, Answer.__table__)) == {
            "form_response_id": (
                "form_responses.id",
                "fk_answer_form_response_id_form_responses",
            ),
            "question_id": ("questions.id", "fk_answer_question_id_questions"),
        }

    def test_tem_indice_em_form_response_id(self) -> None:
        tabela = cast(Table, Answer.__table__)
        colunas_indexadas = {
            coluna.name for indice in tabela.indexes for coluna in indice.columns
        }
        assert "form_response_id" in colunas_indexadas

    def test_tem_indice_em_question_id(self) -> None:
        tabela = cast(Table, Answer.__table__)
        colunas_indexadas = {
            coluna.name for indice in tabela.indexes for coluna in indice.columns
        }
        assert "question_id" in colunas_indexadas


class TestFormResponse:
    def test_chaves_estrangeiras(self) -> None:
        """`vinculo_id` aponta para `links`: o nome antigo fica até ter migration
        própria de rename."""
        assert _fks(cast(Table, FormResponse.__table__)) == {
            "form_id": ("form.id", "fk_form_responses_form_id_form"),
            "vinculo_id": ("links.id", "fk_form_responses_vinculo_id_links"),
        }
