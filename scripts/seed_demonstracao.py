"""Empresa de demonstração, com equipe e períodos já respondidos, em qualquer ambiente
— inclusive produção. Feito para apresentar o dashboard à cliente.

Por que não o `scripts/seed_local.py`: ele cria todo mundo com a senha pública
`dev-creed`, inclusive uma admin, e o repositório é público. Em produção, isso é uma
conta de admin que qualquer leitor do código abre — por isso ele nem entra na imagem.
Este script reaproveita, de `scripts/demonstracao_comum.py`, a mesma equipe, os
setores, a fórmula das notas e os períodos do seed local, e muda o que é perigoso:

- cria **só a empresa de demonstração**: nada de admin, mentorandos ou outra empresa;
- a **gestora** entra com a senha que quem roda digita na hora (sem eco, sem ficar no
  histórico do terminal, nunca gravada no código nem no banco);
- os **funcionários** nascem no realm **sem senha**: ninguém entra com eles. O
  dashboard conta as pessoas pelo vínculo, não pelo login;
- a empresa tem **id próprio**, fora da faixa do seed local. O id da empresa do seed
  local (`...0000-000000000001`) é o da organização provisória que contas antigas de
  produção podem usar (README da EC2), e o `--remover` não pode chegar perto dela.

Tudo o que ele cria fica na organização `[Demonstração] Empresa Exemplo`, com e-mails
em `@demo.creed.example.com`. O `--remover` apaga essa organização e tudo o que
aponta para ela — inclusive período aberto ou resposta feita à mão durante a
apresentação — e as contas dela no realm.

Pode rodar de novo sem duplicar nada. A senha só é perguntada quando a gestora ainda
não existe no realm; para trocá-la, `--redefinir-senha`.

    python -m scripts.seed_demonstracao --confirmo
    python -m scripts.seed_demonstracao --confirmo --redefinir-senha
    python -m scripts.seed_demonstracao --confirmo --remover

Na EC2, em `/opt/creed/creed-infrastructure/ec2`:

    docker compose run --rm --no-deps back python -m scripts.seed_demonstracao --confirmo
"""

import argparse
import asyncio
import getpass
import sys
import uuid
from dataclasses import dataclass, replace
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models  # noqa: F401  (registra todas as tabelas; ver app/models.py)
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.domains.dashboards.models import Dashboard
from app.domains.demographics.models import Demographic
from app.domains.department.models import Department
from app.domains.documents.models import Document
from app.domains.forms.models import Form
from app.domains.insights.models import Insight, InsightPrisma
from app.domains.links.models import Link
from app.domains.organizacoes.models import Organization
from app.domains.organizacoes.repository import OrganizationRepository
from app.domains.participants.models import Participant
from app.domains.responses.models import Answer, FormResponse
from app.domains.users.models import User
from app.shared.enums import Roles
from scripts.demonstracao_comum import (
    AUSENTE_NO_SEGUNDO_PERIODO,
    EMPRESA,
    PERIODOS_DE_DEMONSTRACAO,
    PESSOAS,
    OrganizacaoDeTeste,
    PeriodoDeDemonstracao,
    PessoaDeTeste,
    SeedError,
    _admin_url,
    _buscar_no_realm,
    _criar_no_realm,
    _ensure_departments,
    _ensure_organization,
    _ensure_periodo,
    _ensure_pessoa,
    _perguntas_do_instrumento,
    _service_account_token,
)

# A política do realm (`length(8)`, P-004 de 07/09). Conferida aqui antes de qualquer
# escrita: a Admin API recusaria depois, com o banco já pela metade.
TAMANHO_MINIMO_DA_SENHA = 8

DOMINIO = "demo.creed.example.com"

# Faixa própria de ids, longe das do seed local (0000 a 0003) e da organização
# provisória: o `--remover` apaga por estes ids.
DEMONSTRACAO = OrganizacaoDeTeste(
    id=uuid.UUID("00000000-0000-0000-0004-000000000001"),
    document_id=uuid.UUID("00000000-0000-0000-0004-000000000002"),
    # Valor sintético de propósito, com tipo `other`: não pode parecer um CNPJ real.
    document_value="DEMO-ORG-0003",
    name="[Demonstração] Empresa Exemplo",
    address="[Demonstração] Endereço de exemplo",
)

# Nome e e-mail de quem, no seed local, tem nome genérico demais para a apresentação.
NOVOS_NOMES = {
    "gestora@creed.example.com": ("Marina Teixeira", "gestora"),
    "funcionario@creed.example.com": ("Rafael Mendes", "rafael.marketing"),
}


@dataclass(frozen=True)
class Participante:
    """A pessoa da demonstração e a do seed local de quem ela herda setor e notas."""

    pessoa: PessoaDeTeste
    origem: PessoaDeTeste


def _participante(indice: int, origem: PessoaDeTeste) -> Participante:
    nome, usuario = NOVOS_NOMES.get(
        origem.email,
        (origem.name.removeprefix("[Demonstração] "), origem.email.split("@")[0]),
    )
    pessoa = replace(
        origem,
        email=f"{usuario}@{DOMINIO}",
        name=nome,
        organization_id=DEMONSTRACAO.id,
        participant_id=uuid.UUID(f"00000000-0000-0000-0005-{indice:012d}"),
    )
    return Participante(pessoa=pessoa, origem=origem)


# A mesma equipe da empresa do seed local: gestora, oito pessoas em três setores e uma
# sem setor.
PARTICIPANTES = tuple(
    _participante(indice, origem)
    for indice, origem in enumerate(
        (p for p in PESSOAS if p.organization_id == EMPRESA.id), start=1
    )
)
EQUIPE = tuple(p.pessoa for p in PARTICIPANTES)
GESTORA = next(p for p in EQUIPE if p.role is Roles.GESTOR)
_ORIGEM_POR_EMAIL = {p.pessoa.email: p.origem for p in PARTICIPANTES}
_EMAIL_POR_ORIGEM = {p.origem.email: p.pessoa.email for p in PARTICIPANTES}


def _periodo(indice: int, origem: PeriodoDeDemonstracao) -> PeriodoDeDemonstracao:
    return replace(
        origem,
        id=uuid.UUID(f"00000000-0000-0000-0006-{indice:012d}"),
        organization_id=DEMONSTRACAO.id,
        respondentes=tuple(_EMAIL_POR_ORIGEM[email] for email in origem.respondentes),
    )


# Os dois períodos encerrados da empresa do seed local (setembro e outubro de 2026),
# com a ausência no segundo e a melhora de um para o outro.
PERIODOS = tuple(
    _periodo(indice, origem)
    for indice, origem in enumerate(
        (p for p in PERIODOS_DE_DEMONSTRACAO if p.organization_id == EMPRESA.id),
        start=1,
    )
)
AUSENTE = _EMAIL_POR_ORIGEM[AUSENTE_NO_SEGUNDO_PERIODO]


def _origem(email: str) -> PessoaDeTeste:
    """A pessoa do seed local de quem a da demonstração herda as notas."""
    return _ORIGEM_POR_EMAIL[email]


def usuario_do_realm(pessoa: PessoaDeTeste, senha: str | None) -> dict[str, Any]:
    """A pessoa no formato da Admin API. Sem senha, ninguém entra com ela.

    Com senha, sem `requiredActions` e com `temporary: False`: senão o login responde
    "Account is not fully set up", que na tela parece senha errada.
    """
    usuario: dict[str, Any] = {
        "username": pessoa.email,
        "email": pessoa.email,
        "firstName": pessoa.name,
        "lastName": "Demonstração",
        "enabled": True,
        "emailVerified": True,
        "requiredActions": [],
    }
    if senha is not None:
        usuario["credentials"] = [
            {"type": "password", "value": senha, "temporary": False}
        ]
    return usuario


def validar_senha(senha: str, confirmacao: str) -> None:
    if senha != confirmacao:
        raise SeedError("as duas senhas digitadas são diferentes.")
    if len(senha) < TAMANHO_MINIMO_DA_SENHA:
        raise SeedError(
            f"a senha precisa ter {TAMANHO_MINIMO_DA_SENHA} caracteres ou mais "
            "(política do realm)."
        )


def _perguntar_senha() -> str:
    print(f"Senha da gestora de demonstração ({GESTORA.email}).")
    senha = getpass.getpass("Senha: ")
    validar_senha(senha, getpass.getpass("De novo: "))
    return senha


async def _redefinir_senha(
    http: httpx.AsyncClient, token: str, keycloak_id: uuid.UUID, senha: str
) -> None:
    response = await http.put(
        f"{_admin_url()}/users/{keycloak_id}/reset-password",
        json={"type": "password", "value": senha, "temporary": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    if not response.is_success:
        raise SeedError(f"Admin API recusou trocar a senha: {response.text[:200]}")
    print(f"senha de {GESTORA.email} trocada.")


async def _contas_no_realm(*, redefinir_senha: bool) -> dict[str, uuid.UUID]:
    """O `sub` de cada pessoa da equipe, criando no realm quem falta.

    A senha é perguntada antes de criar qualquer conta: um erro de digitação não deixa
    o realm pela metade.
    """
    async with httpx.AsyncClient(timeout=settings.KEYCLOAK_TIMEOUT_SECONDS) as http:
        token = await _service_account_token(http)
        existentes = {p.email: await _buscar_no_realm(http, token, p) for p in EQUIPE}

        gestora_existe = existentes[GESTORA.email] is not None
        senha = _perguntar_senha() if redefinir_senha or not gestora_existe else None

        keycloak_ids: dict[str, uuid.UUID] = {}
        for pessoa in EQUIPE:
            keycloak_id = existentes[pessoa.email]
            if keycloak_id is None:
                senha_da_pessoa = senha if pessoa is GESTORA else None
                keycloak_id = await _criar_no_realm(
                    http, token, pessoa, usuario_do_realm(pessoa, senha_da_pessoa)
                )
            elif pessoa is GESTORA and senha is not None:
                await _redefinir_senha(http, token, keycloak_id, senha)
            keycloak_ids[pessoa.email] = keycloak_id
        return keycloak_ids


async def semear(*, redefinir_senha: bool) -> None:
    keycloak_ids = await _contas_no_realm(redefinir_senha=redefinir_senha)

    async with AsyncSessionLocal() as session:
        # Antes das pessoas: a FK de `links` recusa vínculo sem organização.
        await _ensure_organization(session, OrganizationRepository(session), DEMONSTRACAO)
        setores = await _ensure_departments(session, EQUIPE)
        await session.commit()

        link_ids: dict[str, uuid.UUID] = {}
        for pessoa in EQUIPE:
            department_id = (
                setores[(pessoa.organization_id, pessoa.department)]
                if pessoa.department is not None
                else None
            )
            link_ids[pessoa.email] = await _ensure_pessoa(
                session, pessoa, keycloak_ids[pessoa.email], department_id
            )
            await session.commit()

        perguntas = await _perguntas_do_instrumento(session)
        for periodo in PERIODOS:
            await _ensure_periodo(session, periodo, link_ids, perguntas, _origem)
            await session.commit()

    print(
        f"Pronto. Entre como {GESTORA.email}, com a senha digitada. Os funcionários "
        "não têm senha: só aparecem no dashboard."
    )


async def _apagar_do_banco(session: AsyncSession) -> None:
    """Tudo o que aponta para a organização de demonstração, das folhas para a raiz.

    Pela organização, e não pelos ids dos períodos: o que alguém criar à mão nela
    durante a apresentação (um período aberto, uma resposta) sai junto.
    """
    org = DEMONSTRACAO.id
    links = select(Link.id).where(Link.organization_id == org)
    forms = select(Form.id).where(Form.organization_id == org)
    respostas = select(FormResponse.id).where(
        FormResponse.form_id.in_(forms) | FormResponse.vinculo_id.in_(links)
    )
    usuarios = select(User.id).where(User.link_id.in_(links))
    insights = select(Insight.id).where(
        (Insight.organization_id == org)
        | Insight.form_id.in_(forms)
        | Insight.form_response_id.in_(respostas)
    )
    participantes = [p.participant_id for p in EQUIPE]

    # A ordem é a das FKs: cada `delete` só apaga o que ninguém mais referencia.
    await session.execute(
        delete(InsightPrisma).where(InsightPrisma.insight_id.in_(insights))
    )
    await session.execute(delete(Insight).where(Insight.id.in_(insights)))
    await session.execute(
        delete(Dashboard).where(
            Dashboard.user_id.in_(usuarios) | Dashboard.form_id.in_(respostas)
        )
    )
    await session.execute(delete(Answer).where(Answer.form_response_id.in_(respostas)))
    await session.execute(delete(FormResponse).where(FormResponse.id.in_(respostas)))
    await session.execute(delete(Form).where(Form.organization_id == org))
    await session.execute(delete(User).where(User.link_id.in_(links)))
    await session.execute(
        delete(Demographic).where(Demographic.participant_id.in_(participantes))
    )
    await session.execute(delete(Link).where(Link.organization_id == org))
    await session.execute(delete(Participant).where(Participant.id.in_(participantes)))
    await session.execute(delete(Department).where(Department.organization_id == org))
    await session.execute(delete(Organization).where(Organization.id == org))
    await session.execute(delete(Document).where(Document.id == DEMONSTRACAO.document_id))


async def _apagar_do_realm() -> None:
    async with httpx.AsyncClient(timeout=settings.KEYCLOAK_TIMEOUT_SECONDS) as http:
        token = await _service_account_token(http)
        for pessoa in EQUIPE:
            keycloak_id = await _buscar_no_realm(http, token, pessoa)
            if keycloak_id is None:
                continue
            response = await http.delete(
                f"{_admin_url()}/users/{keycloak_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if not response.is_success:
                raise SeedError(
                    f"Admin API recusou apagar {pessoa.email}: {response.text[:200]}"
                )
            print(f"{pessoa.email} apagado do realm.")


async def remover() -> None:
    # Banco primeiro, numa transação só: se falhar, nada sai, e as contas do realm
    # continuam batendo com o banco.
    async with AsyncSessionLocal() as session:
        await _apagar_do_banco(session)
        await session.commit()
    print(f"organização {DEMONSTRACAO.name} apagada do banco, com tudo o que era dela.")
    await _apagar_do_realm()
    print("Pronto. Nada da demonstração ficou no ambiente.")


def _argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Empresa de demonstração para apresentar o dashboard."
    )
    parser.add_argument(
        "--confirmo",
        action="store_true",
        help="obrigatório: confirma que é para escrever neste ambiente",
    )
    acao = parser.add_mutually_exclusive_group()
    acao.add_argument(
        "--redefinir-senha",
        action="store_true",
        help="pergunta uma senha nova para a gestora, mesmo que ela já exista",
    )
    acao.add_argument(
        "--remover",
        action="store_true",
        help="apaga a empresa de demonstração e tudo o que é dela",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _argumentos(argv)
    acao = "APAGAR" if args.remover else "criar ou completar"
    print(
        f"Ambiente {settings.ENVIRONMENT}, banco {settings.POSTGRES_HOST}: "
        f"{acao} a organização {DEMONSTRACAO.name} ({DEMONSTRACAO.id})."
    )
    if not args.confirmo:
        print("Nada foi feito. Rode de novo com --confirmo.", file=sys.stderr)
        sys.exit(2)

    try:
        if args.remover:
            asyncio.run(remover())
        else:
            asyncio.run(semear(redefinir_senha=args.redefinir_senha))
    except SeedError as exc:
        print(f"seed de demonstração: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
