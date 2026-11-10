"""liga as tabelas da sprint 3

Revision ID: 41b7cec242e2
Revises: c6625156d816
Create Date: 2026-10-29 01:36:49.055195

Consolidação da sprint 3 (ADR-0009), segunda de duas revisões. As tabelas da sprint
nasceram em paralelo; aqui entram as FKs de colunas que **já existiam e já têm
linhas** para as tabelas novas da revisão anterior:

- `links.organization_id` -> `organizations.id` (#44, CREED-38)
- `form.organization_id`  -> `organizations.id` (integração da sprint 3; a CREED-47
  a deixou para quando a tabela existisse, D1)
- `links.department_id`   -> `departments.id` (integração da sprint 3)
- `answer.option_id`      -> `question_options.id` (#43, "fora desta tarefa")

`organizations` nasce vazia, então todo vínculo e todo formulário que já existe aponta
para uma organização que ainda não está lá. Antes de alterar, a revisão confere os
órfãos. Se houver, ela para com uma mensagem que diz o que fazer, em vez de deixar o
Postgres falhar no `ADD CONSTRAINT` com um erro genérico. Ela não apaga nem insere
nada.

**Por que duas revisões.** O `upgrade` roda numa transação só (alembic/env.py): se a
conferência daqui falhar num `alembic upgrade head` direto, a revisão anterior é
desfeita junto, e o seed fica sem a tabela onde criar a organização. Num banco local
com dados, o caminho é: `alembic upgrade c6625156d816`, depois
`python scripts/seed_local.py` (cria a organização de dev
`00000000-0000-0000-0000-000000000001`, para onde apontam o vínculo e o formulário do
seed), e então `alembic upgrade head`. Num banco limpo, `upgrade head` direto passa.

CHECKLIST DE REVISÃO (ADR-002, secao 2.4):
[x] Autogenerate foi lido linha a linha: as quatro FKs saíram da revisão anterior com
    os nomes que os models dão, sem mudança. Acrescentada à mão a conferência de
    órfãos, que o autogenerate não gera.
[x] Renomeação virou drop+create? Não há renomeação.
[x] Mudança destrutiva foi dividida em passos? Não há mudança destrutiva: só entram
    constraints.
[x] `alembic heads` conferido antes de abrir o PR: uma head só, esta.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "41b7cec242e2"
down_revision: str | None = "c6625156d816"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Mesmo formato da conferência de `d53324b9b5a2`: roda no Postgres, para entrar
    # também no `alembic upgrade --sql`. Dentro do `RAISE`, a mensagem não pode ter
    # aspas simples nem `%`.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM links
                WHERE organization_id NOT IN (SELECT id FROM organizations)
            ) OR EXISTS (
                SELECT 1 FROM form
                WHERE organization_id NOT IN (SELECT id FROM organizations)
            ) THEN
                RAISE EXCEPTION 'Há vínculo(s) em links ou formulário(s) em form apontando para organização que não está em organizations, que nasceu vazia na revisão c6625156d816. Banco local: rode `alembic upgrade c6625156d816`, depois `python scripts/seed_local.py` (cria a organização de dev 00000000-0000-0000-0000-000000000001) e então `alembic upgrade head`; vínculo ou formulário de teste manual de outra organização precisa ser apagado antes. Outro ambiente: suba até c6625156d816 e cadastre em organizations, com o mesmo id, cada organização que links e form já usam, antes de seguir.';
            END IF;

            IF EXISTS (
                SELECT 1 FROM links
                WHERE department_id IS NOT NULL
                  AND department_id NOT IN (SELECT id FROM departments)
            ) THEN
                RAISE EXCEPTION 'Há vínculo(s) em links com department_id apontando para setor que não está em departments, que nasceu vazia na revisão c6625156d816. Zere com `UPDATE links SET department_id = NULL WHERE department_id NOT IN (SELECT id FROM departments)` ou cadastre os setores, e rode `alembic upgrade head` de novo.';
            END IF;

            IF EXISTS (
                SELECT 1 FROM answer
                WHERE option_id IS NOT NULL
                  AND option_id NOT IN (SELECT id FROM question_options)
            ) THEN
                RAISE EXCEPTION 'Há resposta(s) em answer com option_id apontando para alternativa que não está em question_options, que nasceu vazia na revisão c6625156d816. Até aqui nenhuma rota gravava option_id (CREED-47, D2): apague essas linhas e rode `alembic upgrade head` de novo.';
            END IF;
        END $$
        """
    )

    op.create_foreign_key(
        "fk_links_organization_id_organizations",
        "links",
        "organizations",
        ["organization_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_links_department_id_departments",
        "links",
        "departments",
        ["department_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_form_organization_id_organizations",
        "form",
        "organizations",
        ["organization_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_answer_option_id_question_options",
        "answer",
        "question_options",
        ["option_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_answer_option_id_question_options", "answer", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_form_organization_id_organizations", "form", type_="foreignkey"
    )
    op.drop_constraint("fk_links_department_id_departments", "links", type_="foreignkey")
    op.drop_constraint(
        "fk_links_organization_id_organizations", "links", type_="foreignkey"
    )
