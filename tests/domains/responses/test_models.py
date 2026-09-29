"""Testes do model Answer.

Sem banco: lê a descrição da tabela direto do código. Trava o que é
fácil de desfazer sem perceber — uma chave estrangeira acrescentada
antes da tarefa de amarração, ou uma das duas colunas de resposta
virando obrigatória.
"""

from typing import cast

from sqlalchemy import Table

from app.domains.responses.models import Answer


class TestAnswer:
    def test_nome_da_tabela(self) -> None:
        assert Answer.__tablename__ == "answer"

    def test_colunas_e_obrigatoriedade(self) -> None:
        """As duas formas de resposta aceitam vazio: cada tipo de pergunta
        preenche uma delas."""
        esperado = {
            "id": False,
            "question_id": False,
            "option_id": True,
            "value": True,
            "created_at": False,
        }
        assert {c.name: c.nullable for c in Answer.__table__.columns} == esperado

    def test_nao_tem_chave_estrangeira(self) -> None:
        """As tabelas de pergunta e alternativa ainda não existem; as ligações
        entram na tarefa de amarração."""
        assert Answer.__table__.foreign_keys == set()

    def test_tem_indice_em_question_id(self) -> None:
        tabela = cast(Table, Answer.__table__)
        colunas_indexadas = {
            coluna.name for indice in tabela.indexes for coluna in indice.columns
        }
        assert "question_id" in colunas_indexadas
