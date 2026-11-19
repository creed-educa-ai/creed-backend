"""Testes de scripts/seed_demonstracao.py: a empresa de demonstração que roda em
produção.

Sem banco e sem Keycloak. O que se prova é o que o script decide: quem entra com
senha (só a gestora), que nada colide com o que já existe e que nada é escrito sem
`--confirmo`. Que os INSERT e os DELETE passam no Postgres, só rodando no banco local.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.shared.enums import Dimension, Roles
from scripts import seed_demonstracao
from scripts.convidar_primeiro_admin import (
    CREED_ORGANIZATION_DOCUMENT_ID,
    CREED_ORGANIZATION_ID,
)
from scripts.demonstracao_comum import (
    EMPRESA,
    ORGANIZACOES,
    PERIODOS_DE_DEMONSTRACAO,
    PESSOAS,
    PessoaDeTeste,
    SeedError,
    nota_de_demonstracao,
)
from scripts.seed_demonstracao import (
    AUSENTE,
    DEMONSTRACAO,
    DOMINIO,
    EQUIPE,
    GESTORA,
    PERIODOS,
    _origem,
    main,
    usuario_do_realm,
    validar_senha,
)

# A organização provisória que contas antigas de produção podem usar (README da EC2).
ORGANIZACAO_PROVISORIA = uuid.UUID("00000000-0000-0000-0000-000000000001")


class TestEquipe:
    def test_mais_de_sete_pessoas_com_setor_em_tres_setores(self) -> None:
        com_setor = [p for p in EQUIPE if p.department is not None]

        assert len(com_setor) > 7
        assert len({p.department for p in com_setor}) == 3
        assert any(p.department is None for p in EQUIPE)

    def test_uma_gestora_e_o_resto_respondente(self) -> None:
        assert [p for p in EQUIPE if p.role is Roles.GESTOR] == [GESTORA]
        assert all(p.role is Roles.RESPONDENTE for p in EQUIPE if p is not GESTORA)
        assert not any(p.role is Roles.ADMIN for p in EQUIPE)

    def test_todos_na_empresa_de_demonstracao_com_email_de_demonstracao(self) -> None:
        assert all(p.organization_id == DEMONSTRACAO.id for p in EQUIPE)
        assert all(p.email.endswith(f"@{DOMINIO}") for p in EQUIPE)
        assert DEMONSTRACAO.name.startswith("[Demonstração]")

    def test_emails_e_participantes_nao_se_repetem(self) -> None:
        assert len({p.email for p in EQUIPE}) == len(EQUIPE)
        assert len({p.participant_id for p in EQUIPE}) == len(EQUIPE)

    def test_nomes_sem_o_prefixo_de_demonstracao(self) -> None:
        """Os nomes aparecem nos filtros e no mapa de setores da apresentação."""
        assert not any("[" in p.name for p in EQUIPE)

    @pytest.mark.parametrize("pessoa", EQUIPE, ids=lambda p: p.email)
    def test_herda_setor_e_notas_de_uma_pessoa_do_seed_local(
        self, pessoa: PessoaDeTeste
    ) -> None:
        origem = _origem(pessoa.email)

        assert origem in PESSOAS
        assert origem.organization_id == EMPRESA.id
        assert origem.department is pessoa.department
        assert origem.role is pessoa.role
        nota_de_demonstracao(origem, Dimension.S2, 0, melhora=False)


class TestIdsNaoColidem:
    """O `--remover` apaga pelos ids: nenhum pode ser de algo que já existe."""

    def test_organizacao_e_documento_proprios(self) -> None:
        outros = {
            ORGANIZACAO_PROVISORIA,
            CREED_ORGANIZATION_ID,
            CREED_ORGANIZATION_DOCUMENT_ID,
            *(o.id for o in ORGANIZACOES),
            *(o.document_id for o in ORGANIZACOES),
        }

        assert DEMONSTRACAO.id not in outros
        assert DEMONSTRACAO.document_id not in outros

    def test_participantes_e_periodos_proprios(self) -> None:
        do_seed_local = {p.participant_id for p in PESSOAS} | {
            p.id for p in PERIODOS_DE_DEMONSTRACAO
        }
        nossos = [p.participant_id for p in EQUIPE] + [p.id for p in PERIODOS]

        assert not do_seed_local & set(nossos)
        assert len(set(nossos)) == len(nossos)


class TestPeriodos:
    def test_dois_periodos_encerrados_sem_sobreposicao(self) -> None:
        primeiro, segundo = PERIODOS

        assert segundo.closes_at < datetime.now(UTC)
        assert primeiro.closes_at <= segundo.opens_at
        assert all(p.organization_id == DEMONSTRACAO.id for p in PERIODOS)
        assert all(p.individual_de is None for p in PERIODOS)

    def test_respondentes_sao_da_equipe_e_alguem_falta_no_segundo(self) -> None:
        emails = {p.email for p in EQUIPE}
        primeiro, segundo = PERIODOS

        assert set(primeiro.respondentes) <= emails
        assert set(segundo.respondentes) <= emails
        assert AUSENTE in primeiro.respondentes
        assert AUSENTE not in segundo.respondentes
        assert segundo.melhora


class TestContaNoRealm:
    def test_sem_senha_ninguem_entra(self) -> None:
        usuario = usuario_do_realm(EQUIPE[1], None)

        assert "credentials" not in usuario
        assert usuario["username"] == usuario["email"] == EQUIPE[1].email

    def test_com_senha_entra_pelo_login(self) -> None:
        """Sem `requiredActions` vazia e `temporary: False`, o login responde
        "Account is not fully set up", que na tela parece senha errada."""
        usuario = usuario_do_realm(GESTORA, "senha-de-teste")

        assert usuario["enabled"] is True
        assert usuario["requiredActions"] == []
        assert usuario["credentials"] == [
            {"type": "password", "value": "senha-de-teste", "temporary": False}
        ]

    def test_nome_do_realm_sem_colchetes(self) -> None:
        """O realm recusa colchetes no nome."""
        assert all("[" not in usuario_do_realm(p, None)["firstName"] for p in EQUIPE)


class TestSenha:
    def test_aceita_senha_igual_e_longa(self) -> None:
        validar_senha("12345678", "12345678")

    def test_recusa_confirmacao_diferente(self) -> None:
        with pytest.raises(SeedError, match="diferentes"):
            validar_senha("12345678", "12345679")

    def test_recusa_senha_curta(self) -> None:
        """A política do realm é `length(8)`: recusar antes de qualquer escrita."""
        with pytest.raises(SeedError, match="8 caracteres"):
            validar_senha("1234567", "1234567")


class FakeRealm:
    """O que o script usa da Admin API, em memória."""

    def __init__(self, existentes: set[str] = frozenset()) -> None:  # type: ignore[assignment]
        self.contas: dict[str, uuid.UUID] = {e: uuid.uuid4() for e in existentes}
        self.criados: dict[str, dict[str, Any]] = {}
        self.senhas_trocadas: list[str] = []

    async def token(self, http: object) -> str:
        return "token"

    async def buscar(
        self, http: object, token: str, pessoa: PessoaDeTeste
    ) -> uuid.UUID | None:
        return self.contas.get(pessoa.email)

    async def criar(
        self, http: object, token: str, pessoa: PessoaDeTeste, usuario: dict[str, Any]
    ) -> uuid.UUID:
        self.criados[pessoa.email] = usuario
        self.contas[pessoa.email] = uuid.uuid4()
        return self.contas[pessoa.email]

    async def redefinir(
        self, http: object, token: str, keycloak_id: uuid.UUID, senha: str
    ) -> None:
        self.senhas_trocadas.append(senha)


@pytest.fixture
def realm(monkeypatch: pytest.MonkeyPatch) -> FakeRealm:
    fake = FakeRealm()
    monkeypatch.setattr(seed_demonstracao, "_service_account_token", fake.token)
    monkeypatch.setattr(seed_demonstracao, "_buscar_no_realm", fake.buscar)
    monkeypatch.setattr(seed_demonstracao, "_criar_no_realm", fake.criar)
    monkeypatch.setattr(seed_demonstracao, "_redefinir_senha", fake.redefinir)
    return fake


@pytest.fixture
def senhas(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """As senhas digitadas, na ordem em que o script pergunta."""
    digitadas: list[str] = []
    monkeypatch.setattr(seed_demonstracao.getpass, "getpass", lambda _: digitadas.pop(0))
    return digitadas


class TestContasNoRealm:
    async def test_primeira_vez_so_a_gestora_ganha_senha(
        self, realm: FakeRealm, senhas: list[str]
    ) -> None:
        senhas.extend(["senha-forte", "senha-forte"])

        ids = await seed_demonstracao._contas_no_realm(redefinir_senha=False)

        assert set(ids) == {p.email for p in EQUIPE}
        assert realm.criados[GESTORA.email]["credentials"][0]["value"] == "senha-forte"
        sem_senha = [e for e, u in realm.criados.items() if "credentials" not in u]
        assert len(sem_senha) == len(EQUIPE) - 1
        assert not senhas

    async def test_rodar_de_novo_nao_pergunta_senha_nem_cria_nada(
        self, realm: FakeRealm, senhas: list[str]
    ) -> None:
        realm.contas = {p.email: uuid.uuid4() for p in EQUIPE}

        await seed_demonstracao._contas_no_realm(redefinir_senha=False)

        assert realm.criados == {}
        assert realm.senhas_trocadas == []

    async def test_redefinir_senha_troca_a_da_gestora(
        self, realm: FakeRealm, senhas: list[str]
    ) -> None:
        realm.contas = {p.email: uuid.uuid4() for p in EQUIPE}
        senhas.extend(["senha-nova-1", "senha-nova-1"])

        await seed_demonstracao._contas_no_realm(redefinir_senha=True)

        assert realm.senhas_trocadas == ["senha-nova-1"]
        assert realm.criados == {}

    async def test_senha_errada_nao_cria_conta_nenhuma(
        self, realm: FakeRealm, senhas: list[str]
    ) -> None:
        senhas.extend(["senha-forte", "outra-coisa"])

        with pytest.raises(SeedError):
            await seed_demonstracao._contas_no_realm(redefinir_senha=False)

        assert realm.criados == {}


class TestLinhaDeComando:
    def test_sem_confirmo_nao_faz_nada(self, monkeypatch: pytest.MonkeyPatch) -> None:
        chamadas: list[str] = []
        monkeypatch.setattr(seed_demonstracao, "semear", lambda **_: chamadas.append("s"))
        monkeypatch.setattr(seed_demonstracao, "remover", lambda: chamadas.append("r"))

        for argv in ([], ["--remover"], ["--redefinir-senha"]):
            with pytest.raises(SystemExit) as saida:
                main(argv)
            assert saida.value.code == 2

        assert chamadas == []

    def test_remover_e_redefinir_senha_nao_andam_juntos(self) -> None:
        with pytest.raises(SystemExit):
            main(["--confirmo", "--remover", "--redefinir-senha"])
