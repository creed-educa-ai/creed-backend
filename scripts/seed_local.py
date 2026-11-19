"""Seed do ambiente local: as organizações e as pessoas de teste, no realm (se
faltarem) e no nosso banco.

Por que isto existe: depois de o Keycloak aprovar a senha, o login ainda lê o
usuário no **nosso** banco (decisão D2). Realm com usuário e banco vazio dá 401
com a senha certa — que na tela aparece como "e-mail ou senha inválidos" e manda
o time procurar um bug de senha que não existe.

As pessoas de teste **não** vêm do `realm-creed.json`: o arquivo é público e é o
mesmo que a produção importa (ADR-0007), e lá não pode existir um admin com senha
conhecida. Quem as cria é este seed, que só roda com `ENVIRONMENT=local`.

O ambiente fica como o de produção: a admin na organização da CREED, onde também
estão os mentorandos (P-048), e as empresas com os seus membros. **Nenhum período
aberto** nasce aqui: quem abre é o gestor ou a admin, pelo painel, como em produção.
As perguntas também não: são do instrumento CREED, que entra por migration de dados.

Para os dashboards terem o que mostrar, o seed grava **períodos já encerrados e
respondidos**: dois na empresa de demonstração, para comparar um com o outro, e um
individual do mentorando 1. As notas saem de uma fórmula fixa
(`nota_de_demonstracao`), sem sorteio: rodar de novo dá sempre o mesmo resultado.

O `sub` é perguntado ao Keycloak **a cada execução**, nunca fixado aqui: quem
roda `docker compose down -v` ganha usuários novos no realm (ver README).

A equipe, os períodos, a fórmula e as funções que gravam tudo isso estão em
`scripts/demonstracao_comum.py`, que o seed de demonstração de produção também usa.
Aqui ficam só a senha pública e o que é exclusivo do ambiente local.

    python scripts/seed_local.py
"""

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models  # noqa: F401  (registra todas as tabelas; ver app/models.py)
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.domains.forms.models import Form
from app.domains.organizacoes.repository import OrganizationRepository
from app.domains.responses.models import Answer, FormResponse

# `python scripts/seed_local.py`, o comando de sempre (README), põe a pasta scripts/
# no sys.path, e não a raiz do repositório: sem isto, `scripts.demonstracao_comum` não
# é encontrado. Com `python -m scripts.seed_local` ou pelos testes, não muda nada.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.demonstracao_comum import (
    ORGANIZACOES,
    PERIODOS_DE_DEMONSTRACAO,
    PESSOAS,
    PessoaDeTeste,
    SeedError,
    _buscar_no_realm,
    _criar_no_realm,
    _ensure_departments,
    _ensure_organization,
    _ensure_periodo,
    _ensure_pessoa,
    _perguntas_do_instrumento,
    _service_account_token,
)

# Senha pública de propósito, a mesma para todas as pessoas de teste: elas só
# existem no ambiente local. Tem 8 caracteres ou mais porque a política do realm
# (`length(8)`, P-004 de 07/09) faz a Admin API recusar a criação com senha mais curta.
PASSWORD = "dev-creed"  # noqa: S105

# O formulário de demonstração que versões anteriores deste seed criavam, aberto
# até 2031 para a organização de dev. Ele fazia a admin e os mentorandos caírem
# num questionário que em produção não existe: o seed agora o apaga.
OLD_DEMO_FORM_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


async def _keycloak_id(
    http: httpx.AsyncClient, token: str, pessoa: PessoaDeTeste
) -> uuid.UUID:
    """O `sub` da pessoa, criando-a no realm na primeira vez."""
    keycloak_id = await _buscar_no_realm(http, token, pessoa)
    if keycloak_id is None:
        keycloak_id = await _criar_no_realm(
            http, token, pessoa, _usuario_de_teste(pessoa)
        )
    return keycloak_id


def _usuario_de_teste(pessoa: PessoaDeTeste) -> dict[str, Any]:
    """A pessoa de teste no formato que a Admin API recebe.

    Sem `requiredActions` vazia e sem `temporary: False`, o Direct Access Grant
    responde `invalid_grant: "Account is not fully set up"` — que na tela vira
    "senha inválida" e manda o time procurar um bug que não existe.
    """
    return {
        "username": pessoa.email,
        "email": pessoa.email,
        # O realm recusa colchetes no nome: o "[Demonstração]" fica só no nosso banco.
        "firstName": pessoa.name.removeprefix("[Demonstração] "),
        "lastName": "Local",
        "enabled": True,
        "emailVerified": True,
        "requiredActions": [],
        "credentials": [{"type": "password", "value": PASSWORD, "temporary": False}],
    }


async def semear() -> None:
    if settings.ENVIRONMENT != "local":
        raise SeedError(
            f"ENVIRONMENT={settings.ENVIRONMENT}. Este seed é só do ambiente local."
        )

    async with httpx.AsyncClient(timeout=settings.KEYCLOAK_TIMEOUT_SECONDS) as http:
        token = await _service_account_token(http)
        keycloak_ids = {
            pessoa.email: await _keycloak_id(http, token, pessoa) for pessoa in PESSOAS
        }

    async with AsyncSessionLocal() as session:
        # Antes das pessoas: a FK de `links` recusa vínculo sem participante e sem
        # organização.
        organizations = OrganizationRepository(session)
        for organizacao in ORGANIZACOES:
            await _ensure_organization(session, organizations, organizacao)
        await _remove_old_demo_form(session)
        setores = await _ensure_departments(session)
        await session.commit()

        link_ids: dict[str, uuid.UUID] = {}
        for pessoa in PESSOAS:
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
        for periodo in PERIODOS_DE_DEMONSTRACAO:
            await _ensure_periodo(session, periodo, link_ids, perguntas)
            await session.commit()

    print(f"Pronto. Todas as pessoas de teste entram com a senha {PASSWORD!r}.")


async def _remove_old_demo_form(session: AsyncSession) -> bool:
    """Apaga o formulário de demonstração antigo e as respostas dele. Diz se apagou.

    Só respostas de teste do ambiente local: o formulário nunca existiu fora dele.
    """
    if await session.get(Form, OLD_DEMO_FORM_ID) is None:
        return False

    respostas = select(FormResponse.id).where(FormResponse.form_id == OLD_DEMO_FORM_ID)
    await session.execute(delete(Answer).where(Answer.form_response_id.in_(respostas)))
    await session.execute(
        delete(FormResponse).where(FormResponse.form_id == OLD_DEMO_FORM_ID)
    )
    await session.execute(delete(Form).where(Form.id == OLD_DEMO_FORM_ID))
    print(
        f"formulário de demonstração antigo {OLD_DEMO_FORM_ID} apagado, com as "
        "respostas de teste dele."
    )
    return True


if __name__ == "__main__":
    try:
        asyncio.run(semear())
    except SeedError as exc:
        print(f"seed: {exc}", file=sys.stderr)
        sys.exit(1)
