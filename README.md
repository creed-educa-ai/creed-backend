# CREED.ai Educa — Backend

API em FastAPI. Decisões registradas nos **ADR-001** (stack) e **ADR-002**
(organização interna e migrations).

Antes do primeiro PR, leia a [cartilha de contribuição](CONTRIBUTING.md) —
fluxo de branches, padrão de nome e de commit.

## Estrutura

Organização **por domínio** (ADR-002, secao 2.1). Cada domínio em
`app/domains/<nome>/` contém as próprias camadas:

| Arquivo | Responsabilidade | Não faz |
|---|---|---|
| `router.py` | HTTP: recebe, valida, delega | Regra de negócio |
| `service.py` | Regra de negócio | Não conhece HTTP nem ORM |
| `repository.py` | Queries e agregações | Regra de negócio |
| `schemas.py` | Pydantic, separado por direção | — |
| `models.py` | Tabelas SQLAlchemy | — |

`app/domains/users/` é o **domínio-exemplo completo** — use como molde. Tem as cinco
camadas da tabela acima mais `dependencies.py`, e está no idioma decidido pelo ADR-0005
(inglês em todo identificador).

## Setup local

No Windows:
```
.\venv\Scripts\activate
```

- No macOS/Linux:
```
source venv/bin/activate
```

pip install -e ".[dev]"
cp .env.example .env
pre-commit install --hook-type pre-commit --hook-type pre-push
```

O `--hook-type pre-push` instala a verificação do nome da branch
([cartilha](CONTRIBUTING.md)); sem ele, o erro só aparece no PR.

Subir o banco e aplicar migrations:

```bash
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
```

> **Já tem um PostgreSQL instalado na máquina?** Ele ocupa a 5432 e o container fica
> à sombra dele: o sintoma é `autenticação do tipo senha falhou para o usuário "creed"`,
> com o container saudável. Confira com `netstat -ano | findstr :5432` — duas linhas
> LISTENING é o sinal. Ou pare o serviço local, ou publique o container em outra porta
> e ajuste `POSTGRES_PORT` no `.env`.

Docs da API: http://localhost:8000/api/v1/docs

## Autenticação local (Keycloak)

O Keycloak sobe pelo mesmo `docker-compose`, com o realm **importado de arquivo**
(`docker/keycloak/realm-creed.json`). Nada aqui se configura clicando na UI: realm
clicado é dev e produção divergindo sem ninguém perceber.

```bash
docker compose up -d db keycloak mailpit
```

> Quem já tinha o volume `pgdata` antes desta mudança precisa de um
> `docker compose down -v` uma vez: o schema `keycloak` é criado pelo script de
> init do Postgres, que só roda com o volume vazio.

O `mailpit` é o e-mail do ambiente local (ADR-0006). Quem manda e-mail é o Keycloak,
nunca o back, e no local ele manda para o Mailpit, que não entrega a ninguém: as
mensagens aparecem em http://localhost:8025. Sem o `mailpit` de pé, todo envio falha.

> ⚠️ **O realm só é importado quando nasce.** Mudou o `realm-creed.json`, inclusive
> num `git pull`? O Keycloak não relê o arquivo: rode `docker compose down -v`, suba de
> novo e rode `alembic upgrade head` e o seed. O `down -v` **apaga também o banco
> local**, porque o realm mora no schema `keycloak` do mesmo Postgres, e os workflows
> do N8N local.

O usuário de teste **não** vem do realm: o arquivo é o mesmo que a produção importa,
e lá não pode existir admin com senha conhecida. Quem o cria — no Keycloak e no
**nosso** banco — é o seed, que só roda com `ENVIRONMENT=local` e é idempotente:

```bash
alembic upgrade head
python scripts/seed_local.py
```

Existir no realm não bastaria: depois de o Keycloak aprovar a senha, o login ainda lê
o usuário no nosso banco (decisão D2), e com o banco vazio a senha certa devolve 401 —
que na tela vira "e-mail ou senha inválidos". Por isso o seed faz os dois lados.

Conferir que o login funciona (depois do seed):

```bash
curl -s -X POST http://localhost:8080/realms/creed/protocol/openid-connect/token -d grant_type=password -d client_id=creed-backend -d client_secret=creed-local-secret -d username=dev@creed.example.com -d password=dev-creed
```

| Onde | Valor |
|---|---|
| Console do Keycloak | http://localhost:8080 — `admin` / `admin` |
| Usuário de teste (criado pelo seed) | `dev@creed.example.com` / `dev-creed`, papel `admin` |
| E-mails do Keycloak (Mailpit) | http://localhost:8025 |

A senha tem 8 caracteres ou mais porque o realm recusa senha mais curta
(`passwordPolicy`), inclusive na criação do usuário pelo seed.

Rode o seed de novo depois de todo `docker compose down -v`: ele recria o usuário no
realm e reata a tabela `user` ao `sub` novo, em vez de estourar na constraint única.

> ⚠️ **O papel de acesso vem do vínculo (CREED-32)**, e todo usuário precisa de um:
> `user.link_id` é obrigatório. Se o `alembic upgrade head` parar dizendo que há
> usuário sem vínculo, siga a mensagem: ela manda apagar esses usuários locais e rodar
> o seed de novo, que recria o de dev já com vínculo.

**O que muda no realm, muda no arquivo.** Alterou pela UI para testar? Ou refaça no
JSON, ou perca a alteração no próximo `down -v` — e é assim de propósito.

> ⚠️ **O segredo do client e o `sslRequired` não ficam escritos no arquivo.** O repo é
> público e a produção importa este mesmo realm, então os dois são placeholders
> (`${CREED_BACKEND_CLIENT_SECRET}` e `${CREED_REALM_SSL_REQUIRED}`) que o Keycloak
> troca pelo ambiente ao importar — os valores locais estão no `docker-compose.yml`.
> O mesmo vale para o SMTP (`${SMTP_HOST}`, `${SMTP_PASSWORD}` e as outras `SMTP_*`) e
> para o endereço do front no redirect do client (`${CREED_FRONTEND_URL}`). Escreva
> `${VARIAVEL}`, **sem** o prefixo `env.`: com `${env.X}` o Keycloak não troca o valor,
> e o erro só aparece na hora do envio (ADR-0006).
> Exportou o realm pela UI? O export volta com o segredo em texto puro: recoloque os
> placeholders antes de commitar (o `test_realm_keycloak.py` acusa se esquecer).

> ⚠️ **O `sub` do usuário de teste muda a cada `down -v`.** O seed fixa e-mail, senha e
> papel, não o id: quem recria o ambiente ganha um `sub` novo. Nenhum seed pode gravar
> `User.keycloak_id` com o `sub` do `dev@creed.example.com` lido uma vez — o seed tem que
> perguntar ao Keycloak a cada execução.

## Primeiro admin de um ambiente novo

Um ambiente novo não tem usuário nenhum, e em produção ninguém pode nascer com senha
conhecida (P-052). O primeiro admin nasce por **convite**: o script cria o acesso sem
senha, e a pessoa define a senha pelo link do e-mail. Ele roda em qualquer ambiente.

```bash
python -m scripts.convidar_primeiro_admin --email <e-mail> --nome "<nome>"
```

Na EC2, por quem tem acesso a ela, no diretório do compose de produção (é onde está o
link para o `/opt/creed/.env`). O `--no-deps` é o mesmo do `ec2/deploy.sh`: o comando
nunca sobe outro serviço do compose, nem se o `back` passar a depender de algum.

```bash
cd /opt/creed/creed-infrastructure/ec2
docker compose run --rm --no-deps back python -m scripts.convidar_primeiro_admin --email <e-mail> --nome "<nome>"
```

> ⚠️ **Só depois de duas coisas:** o release que leva o script à imagem e a
> consolidação das migrations (CREED-57). O script precisa da tabela `organizations`,
> que hoje nenhuma revision cria, nem num banco limpo nem em produção. Sem ela, o
> comando para com traceback do banco, sem gravar nada.

O que ele faz, e pode rodar de novo sem duplicar nada:

1. garante a organização da própria CREED e o documento dela, com ids fixos (P-048);
2. se o e-mail já tem acesso ativo, **só reenvia o convite**, sem mudar papel nem
   organização (P-060). Se o e-mail é, por exemplo, de uma gestora, o script sai com
   sucesso, reenvia o convite e **ela não vira admin**: a mensagem diz o papel dela;
3. senão, cria participante, vínculo `admin` na organização da CREED e o acesso, e manda
   o convite. É o mesmo convite da rota de membros, tudo ou nada: se o e-mail não sai,
   o banco volta e o usuário criado no Keycloak é apagado.

Duas falhas escapam desse tudo ou nada: o commit que falha depois do e-mail enviado e o
Keycloak que cai entre criar o usuário e apagá-lo (fica só no log). Nas duas, a próxima
execução dá "Já existe acesso com o e-mail …", e a correção é apagar o usuário no
console do Keycloak, pelo túnel SSH (README do `creed-infrastructure/ec2`, "Console de
admin do Keycloak").

No local, o convite aparece no Mailpit (http://localhost:8025). Em produção ele sai do
Gmail do projeto, uma conta nova: **avise a pessoa para olhar também o spam**.

## Qualidade

```bash
ruff check . && ruff format --check .
ruff format .
mypy app
pytest
```

## Migrations (ADR-002, secao 2.4 · ADR-0009)

**PR de tarefa sobe sem migration.** Desde a retrospectiva da sprint 2, cada PR com
a sua própria revisão do Alembic gerava conflito de heads com os PRs paralelos.
Agora você gera a migration só para testar local, e um AGES III consolida as
mudanças de banco da sprint numa revisão só. O CI recusa PR de tarefa com arquivo
em `alembic/versions/`.

Na sua tarefa:

```bash
alembic heads                                     # anote: é o head da dev
alembic revision --autogenerate -m "descricao"   # temporária, SEMPRE revisar
alembic upgrade head                              # testar
# antes de abrir o PR — primeiro desce, depois apaga:
alembic downgrade <head-da-dev>
rm alembic/versions/<arquivo-temporario>.py
alembic current                                   # tem que bater com alembic heads
```

E preencha a seção **"Banco"** do PR: o que mudou no schema e todo ajuste que você
fez à mão na temporária (rename, backfill, `server_default` em tabela com linhas).
O autogenerate da consolidação não sabe disso, e rename vira drop+create e **perde
dados**.

> **Rodando a `dev` entre consolidações?** Ela pode ter model sem tabela. Gere uma
> temporária para subir a aplicação ou o seed, e desfaça do mesmo jeito.

**Consolidação (AGES III):** branch `chore/<id-clickup>-consolidar-migrations`,
a única que o CI deixa trazer migration. Ali o CI aplica tudo num Postgres limpo e
roda `alembic check`. O passo a passo está em
`creed-ai-context/playbooks/criar-migration.md`, fluxo B.

**Regras que valem sempre:**

1. Autogenerate **nunca** vai para o repositório sem leitura linha a linha —
   renomear coluna vira drop+create e **perde dados**.
2. Migration passa por code review, com prioridade (a consolidação é Sensível).
3. Conflito de heads: usar `alembic merge`, nunca editar `down_revision` à revelia.
4. No deploy: **passo dedicado do pipeline**, nunca no startup do container.
5. Rollback: corrigir avançando com nova migration, não com `downgrade` — a
   temporária da sua máquina é a única exceção.
6. Mudança destrutiva: dividir em passos (adicionar → migrar dados → remover), cada
   um numa consolidação.
7. Release `dev` → `main` só depois de consolidar.
