"""Testes do realm versionado (`docker/keycloak/realm-creed.json`).

O realm é arquivo, não clique na UI — é o item que impede dev e produção de
divergirem sem ninguém perceber (spec da CREED-23, seção Riscos). Arquivo JSON,
porém, não tem comentário e não tem compilador: um `directAccessGrantsEnabled`
que vira `false` numa edição só aparece quando o login inteiro para de funcionar.

Estes testes são a leitura de review desse arquivo, em forma de CI. Eles não
sobem o Keycloak: leem o JSON e conferem o que a spec e o contrato decidiram.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings

REALM = json.loads(
    (
        Path(__file__).resolve().parents[1] / "docker" / "keycloak" / "realm-creed.json"
    ).read_text(encoding="utf-8")
)

PAPEIS = {"admin", "gestor", "respondente"}


@pytest.fixture
def client() -> dict[str, Any]:
    """O client confidencial do backend — o único que fala com este realm."""
    return next(c for c in REALM["clients"] if c["clientId"] == "creed-backend")


def test_realm_e_client_batem_com_os_defaults_da_settings(
    monkeypatch: pytest.MonkeyPatch, client: dict[str, Any]
) -> None:
    """Se o arquivo e a Settings divergirem, o setup do time quebra no primeiro login."""
    monkeypatch.setenv("POSTGRES_PASSWORD", "irrelevante")
    monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "irrelevante")
    settings = Settings(_env_file=None)

    assert REALM["realm"] == settings.KEYCLOAK_REALM
    assert client["clientId"] == settings.KEYCLOAK_CLIENT_ID


def test_client_e_confidencial_com_direct_access_grant(
    client: dict[str, Any],
) -> None:
    """Decisão D1: o backend intermedeia o login como confidential client."""
    assert client["publicClient"] is False
    assert client["directAccessGrantsEnabled"] is True


def test_segredo_e_ssl_chegam_pelo_ambiente(client: dict[str, Any]) -> None:
    """O arquivo é público e é o mesmo que a produção importa (ADR-0007).

    Um export feito pela UI devolve o segredo em texto puro e `sslRequired: none` —
    e aí a credencial do service account (que cria usuário pela Admin API) vai
    parar no GitHub, e a produção aceita login sem HTTPS. Os valores locais
    estão no `docker-compose.yml`.
    """
    # S105: é o nome da variável, não uma senha — justamente o que o teste garante.
    assert client["secret"] == "${CREED_BACKEND_CLIENT_SECRET}"  # noqa: S105
    assert REALM["sslRequired"] == "${CREED_REALM_SSL_REQUIRED}"


def test_smtp_chega_pelo_ambiente() -> None:
    """ADR-0006, item 3: a forma do SMTP mora aqui, os valores vêm do ambiente.

    O local manda para o Mailpit, e a produção pelo Gmail do projeto. A senha de
    produção é a senha de app desse Gmail: escrita aqui, ela iria para o GitHub. Os
    valores locais estão no `docker-compose.yml`.

    A sintaxe é `${VARIAVEL}`, sem `env.`: com `${env.X}` o Keycloak importa o realm
    sem trocar o valor, e o erro só aparece na hora do envio.
    """
    smtp = REALM["smtpServer"]

    # S105: é o nome da variável, não uma senha — justamente o que o teste garante.
    assert smtp["password"] == "${SMTP_PASSWORD}"  # noqa: S105
    assert smtp["user"] == "${SMTP_USER}"
    assert smtp["host"] == "${SMTP_HOST}"
    assert smtp["port"] == "${SMTP_PORT}"
    assert smtp["from"] == "${SMTP_FROM}"
    assert smtp["auth"] == "${SMTP_AUTH}"


def test_smtp_liga_o_tls_pelo_ambiente() -> None:
    """O Gmail de produção só aceita a porta 587 com STARTTLS (adendo do ADR-0006).

    O bloco do ADR-0006 não tinha `starttls` nem `ssl`, e chave que falta fica com o
    padrão do Keycloak, desligado: o envio de produção sairia sem TLS e o Google
    recusaria. O Mailpit local não tem TLS, então os dois chegam pelo ambiente.
    """
    smtp = REALM["smtpServer"]

    assert smtp["starttls"] == "${SMTP_STARTTLS}"
    assert smtp["ssl"] == "${SMTP_SSL}"


def test_paginas_e_email_em_portugues_da_premissa_p050() -> None:
    """P-050: o texto padrão do Keycloak em português, com inglês e espanhol.

    Sem `internationalizationEnabled`, o Keycloak ignora a lista e fala inglês. O
    `defaultLocale` vale quando nem a pessoa nem o navegador pedem outro idioma, que
    é o caso do e-mail: ele sai de uma chamada do back à Admin API.
    """
    assert REALM["internationalizationEnabled"] is True
    assert REALM["defaultLocale"] == "pt-BR"
    assert set(REALM["supportedLocales"]) == {"pt-BR", "en", "es"}


def test_senha_tem_no_minimo_8_caracteres_da_premissa_p004() -> None:
    """P-004 de 07/09: no mínimo 8 caracteres, sem regra de complexidade.

    A regra mora no realm porque quem recebe a senha nova é a página do Keycloak,
    aberta pelo link do convite, e não o front. Regra a mais aqui é premissa nova.
    """
    assert REALM["passwordPolicy"] == "length(8)"


def test_redirect_do_client_chega_pelo_ambiente(client: dict[str, Any]) -> None:
    """P-051: o link "voltar" da página do convite leva ao front.

    O front muda por ambiente: `http://localhost:5173` no local, o Amplify em
    produção. Sem o endereço nesta lista, o Keycloak recusa o `redirect_uri` do
    convite (`Invalid redirect uri`), e pela D7 o convite inteiro falha.

    A lista não liga o login pelo navegador: o fluxo continua desligado (decisão D1).
    """
    assert client["redirectUris"] == ["${CREED_FRONTEND_URL}/*"]
    assert client["standardFlowEnabled"] is False


def test_papeis_do_realm_sao_os_da_premissa_p006() -> None:
    nomes = {papel["name"] for papel in REALM["roles"]["realm"]}

    assert nomes == PAPEIS


def test_realm_nao_traz_usuario_de_pessoa() -> None:
    """A produção importa este mesmo arquivo (ADR-0007), e ele é público.

    Usuário de pessoa aqui é conta com senha conhecida em produção. O de teste
    do ambiente local nasce pelo `scripts/seed_local.py`; o arquivo só traz o
    service account do backend.
    """
    assert all("serviceAccountClientId" in u for u in REALM["users"])


def test_realm_nao_liga_acao_obrigatoria_por_padrao() -> None:
    """A mesma armadilha do teste acima, mas pela porta do realm.

    `verifyEmail` ou reset de senha ligados anexam ação obrigatória a todo usuário
    novo, e aí `temporary: false` no provisionamento (entrega 3) não salva ninguém.
    Item de review nomeado no `contrato-api.md`; aqui ele para de depender de memória.
    """
    assert REALM["verifyEmail"] is False
    assert REALM["resetPasswordAllowed"] is False
    assert REALM["registrationAllowed"] is False


def test_perfil_nao_exige_nome_para_provisionar() -> None:
    """A armadilha que custou mais caro achar, e que nenhum outro teste pegava.

    O `UserCreate` do contrato manda `{vinculo_id, email, initial_password}` — sem
    nome. O user profile declarativo do Keycloak, porém, nasce exigindo `firstName`
    e `lastName`, e um perfil incompleto dispara `VERIFY_PROFILE` **no login**,
    não na criação. O Direct Access Grant (decisão D1) então responde
    `invalid_grant: "Account is not fully set up"` — que na tela vira "senha
    inválida" para um usuário recém-criado cuja senha está certa.

    Verificado contra o Keycloak 26.0.8: com o perfil padrão, todo usuário
    provisionado só com e-mail fica trancado fora. Quem tem o nome da pessoa é o
    `Participant` no nosso banco; aqui o Keycloak guarda credencial, não cadastro.
    """
    perfil = json.loads(
        REALM["components"]["org.keycloak.userprofile.UserProfileProvider"][0]["config"][
            "kc.user.profile.config"
        ][0]
    )
    obrigatorios = {a["name"] for a in perfil["attributes"] if "required" in a}

    assert "firstName" not in obrigatorios
    assert "lastName" not in obrigatorios


def test_email_so_o_admin_edita() -> None:
    """Decisão D12 da CREED-23.8: a pessoa não troca o próprio e-mail.

    O link do convite leva a pessoa às páginas do Keycloak, e o console de conta
    passa pelo Caddy. Lá ela poderia trocar o e-mail sem verificação e perderia o
    acesso, porque o login e a guarda procuram o usuário pelo e-mail.
    """
    perfil = json.loads(
        REALM["components"]["org.keycloak.userprofile.UserProfileProvider"][0]["config"][
            "kc.user.profile.config"
        ][0]
    )
    email = next(a for a in perfil["attributes"] if a["name"] == "email")

    assert email["permissions"]["edit"] == ["admin"]


def test_service_account_tem_o_minimo_verificado() -> None:
    """As duas roles que o provisionamento da entrega 3 (decisão D4) exige.

    Verificado contra o Keycloak 26.0.8, tirando uma role por vez do conjunto:

    - `manage-users` — criar e apagar usuário (a compensação da D4). Sem ela,
      `POST /admin/realms/creed/users` responde 403.
    - `view-realm` — **ler a realm role** antes de atribuí-la. Sem ela,
      `GET /admin/realms/creed/roles/gestor` responde 403 e o espelhamento de
      papel morre no meio do provisionamento, com o usuário já criado.

    `view-users` e `query-users` são dispensáveis: `manage-users` já dá leitura,
    e `view-users` é composta — traz `query-users` e `query-groups` de brinde.
    Papel a mais aqui é permissão de admin que ninguém pediu.
    """
    sa = next(
        u for u in REALM["users"] if u.get("serviceAccountClientId") == "creed-backend"
    )

    assert set(sa["clientRoles"]["realm-management"]) == {"manage-users", "view-realm"}


def test_login_por_senha_tem_protecao_contra_forca_bruta() -> None:
    """O back não limita tentativas de login: quem conta os erros é o Keycloak.

    Sem isto, dá para testar senhas sem limite pelo `/api/v1/authentication/login`.
    O bloqueio é temporário de propósito: o permanente deixaria qualquer um trancar
    a conta de outra pessoa errando a senha dela de propósito.
    """
    assert REALM["bruteForceProtected"] is True
    assert REALM["permanentLockout"] is False


def test_sessao_segue_os_tempos_da_premissa_p010() -> None:
    """P-010: access token de 15 min, refresh de 8 h."""
    assert REALM["accessTokenLifespan"] == 15 * 60
    assert REALM["ssoSessionMaxLifespan"] == 8 * 60 * 60


def test_client_carimba_a_propria_audiencia_no_access_token(
    client: dict[str, Any],
) -> None:
    """Sem este mapper, o Direct Access Grant emite `aud: ["account"]`.

    O backend valida `aud` (entrega 23.4). Com `account` no lugar do client, ou
    a conferência falha e ninguém entra, ou é afrouxada — e aí deixa de dizer
    qualquer coisa sobre para quem o token foi emitido.
    """
    mapper = next(
        m
        for m in client.get("protocolMappers", [])
        if m["protocolMapper"] == "oidc-audience-mapper"
    )

    assert mapper["config"]["included.client.audience"] == client["clientId"]
    assert mapper["config"]["access.token.claim"] == "true"
