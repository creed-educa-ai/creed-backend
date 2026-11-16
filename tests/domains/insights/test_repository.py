"""Testes dos repositories do domínio insights.

Sem banco: a sessão é um dublê que simula as operações
de persistência e consulta do repository. O SQL de verdade (o JOIN que acha a
organização e o período, as restrições da tabela) roda em
`test_insights_postgres.py`.
"""

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.domains.insights.models import Insight, InsightPrisma
from app.domains.insights.repository import (
    DescriptiveAnswer,
    FormScope,
    InsightPrismaRepository,
    InsightRepository,
    ResponseOwner,
)
from app.domains.questions.models import QuestionSection
from app.shared.enums import LinkType, Prisma


class _SessaoFalsa:
    """Sessão falsa para testar o repository sem acessar o banco."""

    def __init__(
        self,
        resultado: object | None = None,
        lista: list[InsightPrisma] | None = None,
        erro_no_flush: Exception | None = None,
        linha: object | None = None,
        linhas: list[object] | None = None,
    ) -> None:
        self.resultado = resultado
        self.lista = lista or []
        self.linha = linha
        self.linhas = linhas or []
        self.add = MagicMock()
        self.flush = AsyncMock(side_effect=erro_no_flush)
        self.refresh = AsyncMock()
        self.delete = AsyncMock()

    async def execute(self, query: Any) -> MagicMock:
        resultado = MagicMock()
        resultado.scalar_one_or_none.return_value = self.resultado
        resultado.scalars.return_value.all.return_value = self.lista
        resultado.one_or_none.return_value = self.linha
        resultado.all.return_value = self.linhas
        return resultado


async def test_inserir_associacao() -> None:
    sessao = _SessaoFalsa()
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    associacao = InsightPrisma(
        insight_id=uuid.uuid4(), prisma=Prisma.SEGURANCA_PSICOLOGICA
    )

    resultado = await repository.insert(associacao)

    sessao.add.assert_called_once_with(associacao)
    sessao.flush.assert_awaited_once()
    sessao.refresh.assert_awaited_once_with(associacao)
    assert resultado is associacao


async def test_buscar_associacao_pelo_par() -> None:
    associacao = InsightPrisma(
        insight_id=uuid.uuid4(), prisma=Prisma.LIDERANCA_ADAPTATIVA
    )
    sessao = _SessaoFalsa(resultado=associacao)
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    resultado = await repository.get(associacao.insight_id, Prisma.LIDERANCA_ADAPTATIVA)

    assert resultado is associacao


async def test_buscar_associacao_inexistente_devolve_none() -> None:
    """A camada de banco não decide: devolve nada e deixa a regra decidir."""
    sessao = _SessaoFalsa(resultado=None)
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    resultado = await repository.get(uuid.uuid4(), Prisma.CULTURA_EMPREENDEDORA)

    assert resultado is None


async def test_listar_prismas_de_um_insight() -> None:
    insight_id = uuid.uuid4()
    associacoes = [
        InsightPrisma(insight_id=insight_id, prisma=Prisma.SEGURANCA_PSICOLOGICA),
        InsightPrisma(insight_id=insight_id, prisma=Prisma.NEUROINOVACAO_PRISMA),
    ]
    sessao = _SessaoFalsa(lista=associacoes)
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    resultado = await repository.list_by_insight(insight_id)

    assert resultado == associacoes


async def test_listar_de_insight_sem_prismas_devolve_lista_vazia() -> None:
    sessao = _SessaoFalsa(lista=[])
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    resultado = await repository.list_by_insight(uuid.uuid4())

    assert resultado == []


async def test_remover_associacao() -> None:
    sessao = _SessaoFalsa()
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    associacao = InsightPrisma(
        insight_id=uuid.uuid4(), prisma=Prisma.ADAPTABILIDADE_COGNITIVA
    )

    await repository.delete(associacao)

    sessao.delete.assert_awaited_once_with(associacao)
    sessao.flush.assert_awaited_once()


def _erro_de_integridade(detalhe: str) -> IntegrityError:
    """IntegrityError como o psycopg o entrega, com o nome da constraint."""
    return IntegrityError("INSERT ...", {}, Exception(detalhe))


async def test_colisao_na_chave_primaria_devolve_none() -> None:
    """Corrida: o par foi gravado entre a checagem do service e este flush."""
    sessao = _SessaoFalsa(
        erro_no_flush=_erro_de_integridade(
            'duplicate key value violates unique constraint "insight_prismas_pkey"'
        )
    )
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    resultado = await repository.insert(
        InsightPrisma(insight_id=uuid.uuid4(), prisma=Prisma.SEGURANCA_PSICOLOGICA)
    )

    assert resultado is None
    sessao.refresh.assert_not_awaited()


async def test_outro_erro_de_integridade_e_propagado() -> None:
    """Só a violação da chave da associação vira `None`; o resto sobe."""
    sessao = _SessaoFalsa(
        erro_no_flush=_erro_de_integridade(
            "insert or update violates foreign key constraint "
            '"fk_insight_prismas_insight_id_insights"'
        )
    )
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    with pytest.raises(IntegrityError):
        await repository.insert(
            InsightPrisma(insight_id=uuid.uuid4(), prisma=Prisma.LIDERANCA_ADAPTATIVA)
        )


async def test_buscar_insight_que_a_associacao_referencia() -> None:
    """Sustenta a validação de existência que o service exige."""
    insight = Insight(
        id=uuid.uuid4(),
        form_response_id=uuid.uuid4(),
        content="texto da analise",
    )
    sessao = _SessaoFalsa(resultado=insight)
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    resultado = await repository.get_insight(insight.id)

    assert resultado is insight


async def test_buscar_insight_inexistente_devolve_none() -> None:
    sessao = _SessaoFalsa(resultado=None)
    repository = InsightPrismaRepository(sessao)  # type: ignore[arg-type]

    resultado = await repository.get_insight(uuid.uuid4())

    assert resultado is None


# --- InsightRepository: o pedido de insight que o envio grava (CREED-802) ------


def _um_pedido() -> Insight:
    return Insight(
        organization_id=uuid.uuid4(),
        form_id=uuid.uuid4(),
        form_response_id=uuid.uuid4(),
    )


async def test_escopo_da_resposta_traz_organizacao_e_formulario() -> None:
    organizacao, formulario = uuid.uuid4(), uuid.uuid4()
    sessao = _SessaoFalsa(
        linha=SimpleNamespace(organization_id=organizacao, form_id=formulario)
    )
    repository = InsightRepository(sessao)  # type: ignore[arg-type]

    escopo = await repository.get_form_scope(uuid.uuid4())

    assert escopo == FormScope(organization_id=organizacao, form_id=formulario)


async def test_escopo_de_resposta_inexistente_devolve_none() -> None:
    """A camada de banco não decide: devolve nada e o service levanta o 404."""
    repository = InsightRepository(_SessaoFalsa(linha=None))  # type: ignore[arg-type]

    assert await repository.get_form_scope(uuid.uuid4()) is None


async def test_criar_pedido_grava_e_traz_o_que_o_banco_preenche() -> None:
    sessao = _SessaoFalsa()
    repository = InsightRepository(sessao)  # type: ignore[arg-type]
    pedido = _um_pedido()

    resultado = await repository.create(pedido)

    sessao.add.assert_called_once_with(pedido)
    sessao.flush.assert_awaited_once()
    sessao.refresh.assert_awaited_once_with(pedido)
    assert resultado is pedido


async def test_segundo_pedido_da_mesma_resposta_devolve_none() -> None:
    """Corrida: dois envios passam juntos pela checagem e só se esbarram no banco."""
    sessao = _SessaoFalsa(
        erro_no_flush=_erro_de_integridade(
            "duplicate key value violates unique constraint "
            '"uq_insights_form_response_id"'
        )
    )
    repository = InsightRepository(sessao)  # type: ignore[arg-type]

    resultado = await repository.create(_um_pedido())

    assert resultado is None
    sessao.refresh.assert_not_awaited()


async def test_outra_violacao_ao_criar_o_pedido_sobe() -> None:
    """Só o `unique` da resposta vira `None`. Organização inexistente, por exemplo,
    é erro de verdade e não pode ser tratado como "já tem insight"."""
    sessao = _SessaoFalsa(
        erro_no_flush=_erro_de_integridade(
            "insert or update violates foreign key constraint "
            '"fk_insights_organization_id_organizations"'
        )
    )
    repository = InsightRepository(sessao)  # type: ignore[arg-type]

    with pytest.raises(IntegrityError):
        await repository.create(_um_pedido())


# --- Respostas descritivas do pedido de insight (CREED-803) ---------------------
# O JOIN e o filtro por tipo só se provam com banco: test_insights_postgres.py.


async def test_descritivas_viram_secao_em_texto_pergunta_e_resposta() -> None:
    sessao = _SessaoFalsa(
        linhas=[
            SimpleNamespace(
                section=QuestionSection.S9, text="Outras sugestões.", value="Mais trocas."
            ),
            SimpleNamespace(section=QuestionSection.S9, text="Em branco", value=None),
        ]
    )
    repository = InsightRepository(sessao)  # type: ignore[arg-type]

    respostas = await repository.list_descriptive_answers(uuid.uuid4())

    # A resposta nula vem junto: quem decide o que conta como respondida é o service.
    assert respostas == [
        DescriptiveAnswer(
            section="S9", question="Outras sugestões.", answer="Mais trocas."
        ),
        DescriptiveAnswer(section="S9", question="Em branco", answer=None),
    ]


async def test_resposta_sem_descritiva_devolve_lista_vazia() -> None:
    repository = InsightRepository(_SessaoFalsa())  # type: ignore[arg-type]

    assert await repository.list_descriptive_answers(uuid.uuid4()) == []


# --- A leitura do estado (CREED-805) ----------------------------------------------


async def test_dono_da_resposta_traz_vinculo_tipo_e_organizacao() -> None:
    vinculo, organizacao = uuid.uuid4(), uuid.uuid4()
    sessao = _SessaoFalsa(
        linha=SimpleNamespace(
            id=vinculo, type=LinkType.MENTORIA, organization_id=organizacao
        )
    )
    repository = InsightRepository(sessao)  # type: ignore[arg-type]

    dono = await repository.get_response_owner(uuid.uuid4())

    assert dono == ResponseOwner(
        link_id=vinculo, link_type=LinkType.MENTORIA, organization_id=organizacao
    )


async def test_dono_de_resposta_inexistente_devolve_none() -> None:
    """A camada de banco não decide: devolve nada e o service levanta o 404."""
    repository = InsightRepository(_SessaoFalsa(linha=None))  # type: ignore[arg-type]

    assert await repository.get_response_owner(uuid.uuid4()) is None


async def test_insight_da_resposta_devolve_o_que_o_banco_achou() -> None:
    insight = _um_pedido()
    repository = InsightRepository(_SessaoFalsa(resultado=insight))  # type: ignore[arg-type]

    assert await repository.get_by_form_response(uuid.uuid4()) is insight


async def test_resposta_sem_insight_devolve_none() -> None:
    repository = InsightRepository(_SessaoFalsa())  # type: ignore[arg-type]

    assert await repository.get_by_form_response(uuid.uuid4()) is None
