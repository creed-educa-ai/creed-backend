"""Testes de scripts/seed_local.py: o usuário de teste e o formulário de
demonstração (CREED-47).

Sem banco e sem Keycloak: os repositories são dublês em memória. O que se prova é o
que o seed decide — o que cria, com que conteúdo e que não duplica. Que o INSERT
passa no Postgres, só rodando o seed no banco local.
"""

import uuid

import pytest

from app.domains.forms.models import Form
from app.domains.questions.models import Question, QuestionSection, QuestionType
from scripts.seed_local import (
    DEMO_FORM_ID,
    EMAIL,
    LINK_ROLE,
    ORGANIZATION_ID,
    _ensure_demo_form,
    _usuario_de_teste,
)

PAPEIS = {"admin", "gestor", "respondente"}


class TestUsuarioDeTeste:
    """O que o seed manda à Admin API para criar o usuário de teste no realm."""

    def test_entra_pelo_token_endpoint(self) -> None:
        """O `curl` do README e o login local dependem deste usuário.

        Sem `requiredActions` vazia e sem `temporary: False`, o Direct Access Grant
        responde `invalid_grant: "Account is not fully set up"` — que na tela vira
        "senha inválida" e manda o time procurar um bug que não existe.
        """
        usuario = _usuario_de_teste()

        assert usuario["username"] == usuario["email"] == EMAIL
        assert usuario["enabled"] is True
        assert usuario["requiredActions"] == []
        assert usuario["credentials"][0]["temporary"] is False

    def test_papel_do_realm_e_um_da_premissa_p006(self) -> None:
        """O papel dado no realm é o do vínculo, e precisa existir no realm."""
        assert LINK_ROLE.value in PAPEIS


class FakeFormRepository:
    def __init__(self) -> None:
        self.itens: list[Form] = []

    async def get_by_id(self, form_id: uuid.UUID) -> Form | None:
        return next((f for f in self.itens if f.id == form_id), None)

    async def create(self, form: Form) -> Form:
        self.itens.append(form)
        return form


class FakeQuestionRepository:
    def __init__(self) -> None:
        self.itens: list[Question] = []

    async def get_by_form_and_order(
        self, form_id: uuid.UUID, order_index: int
    ) -> Question | None:
        return next(
            (
                q
                for q in self.itens
                if q.form_id == form_id and q.order_index == order_index
            ),
            None,
        )

    async def insert(self, question: Question) -> Question | None:
        self.itens.append(question)
        return question


@pytest.fixture
def forms() -> FakeFormRepository:
    return FakeFormRepository()


@pytest.fixture
def questions() -> FakeQuestionRepository:
    return FakeQuestionRepository()


async def semear(forms: FakeFormRepository, questions: FakeQuestionRepository) -> bool:
    return await _ensure_demo_form(forms, questions)  # type: ignore[arg-type]


class TestFormularioDeDemonstracao:
    async def test_cria_o_formulario_na_organizacao_do_vinculo_de_dev(
        self, forms: FakeFormRepository, questions: FakeQuestionRepository
    ) -> None:
        assert await semear(forms, questions)

        [form] = forms.itens
        assert form.id == DEMO_FORM_ID
        assert form.organization_id == ORGANIZATION_ID

    async def test_tres_descritivas_uma_por_secao_em_ordem(
        self, forms: FakeFormRepository, questions: FakeQuestionRepository
    ) -> None:
        await semear(forms, questions)

        assert [q.order_index for q in questions.itens] == [0, 1, 2]
        assert [q.section for q in questions.itens] == [
            QuestionSection.PROFILE,
            QuestionSection.ASSESSMENT,
            QuestionSection.CLOSING,
        ]
        assert all(q.type is QuestionType.DESCRIPTIVE for q in questions.itens)
        assert all(q.form_id == DEMO_FORM_ID for q in questions.itens)

    async def test_duas_obrigatorias_e_uma_opcional(
        self, forms: FakeFormRepository, questions: FakeQuestionRepository
    ) -> None:
        """Para a demonstração mostrar o envio barrado e depois aceito (task 6)."""
        await semear(forms, questions)

        assert [q.required for q in questions.itens] == [True, True, False]

    async def test_texto_se_identifica_como_demonstracao(
        self, forms: FakeFormRepository, questions: FakeQuestionRepository
    ) -> None:
        """O conteúdo do instrumento é da cliente: nada pode parecer pergunta real."""
        await semear(forms, questions)

        assert forms.itens[0].name.startswith("[Demonstração]")
        assert all(q.text.startswith("[Demonstração]") for q in questions.itens)

    async def test_rodar_de_novo_nao_cria_nada(
        self, forms: FakeFormRepository, questions: FakeQuestionRepository
    ) -> None:
        await semear(forms, questions)

        assert not await semear(forms, questions)
        assert len(forms.itens) == 1
        assert len(questions.itens) == 3

    async def test_completa_so_a_pergunta_que_falta(
        self, forms: FakeFormRepository, questions: FakeQuestionRepository
    ) -> None:
        """Banco com o formulário e parte das perguntas: cria só a posição vazia."""
        await semear(forms, questions)
        questions.itens = [q for q in questions.itens if q.order_index != 1]

        assert await semear(forms, questions)
        assert len(forms.itens) == 1
        assert sorted(q.order_index for q in questions.itens) == [0, 1, 2]
