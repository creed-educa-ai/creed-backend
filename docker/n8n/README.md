# Esteira de insights no N8N (`insight-v1`)

A esteira roda no **N8N da AWS** (EC2, `https://<IP>:5679`), não no N8N do
`docker-compose` local: o local não tem o workflow nem fala com a AWS (spec da CREED-80,
decisões 3 e 4). Esta pasta guarda o **registro** do que está montado lá, e o kit que o
back e o N8N usam como verdade.

| Pasta | O que é |
|---|---|
| `contrato/` | o kit de contrato (CREED-801): schemas da ida e da volta, exemplos, o vetor da assinatura e o `saida-n8n.json`. Ver o README de lá |
| `workflows/` | os workflows exportados do N8N da AWS (CREED-806 e task 15) |

## Os workflows

Três workflows no projeto "Creed Educa", todos publicados:

| Workflow | Arquivo | O que faz |
|---|---|---|
| `insight-v1 entrada` | `insight-v1-entrada.json` | webhook `POST /webhook/creed/insights/v1` com Header Auth; responde `202` na hora e confere o pedido pelo contrato. Pedido válido, individual ou da empresa, vai ao `gerar`; pedido fora do contrato volta `failed` (`invalid_payload`), sem retentativa |
| `insight-v1 gerar` | `insight-v1-gerar.json` | monta o prompt do ramo (individual ou empresa) no idioma do pedido, chama o modelo e transforma a resposta no corpo da volta (`done` ou `failed`) |
| `insight-v1 volta` | `insight-v1-volta.json` | serializa o corpo uma vez, assina `{timestamp}.{corpo}` com HMAC-SHA256 e faz `POST` em `http://back:8000/api/v1/insights/callback` com exatamente a string assinada |

```
back (worker) ──POST + Bearer──▶ entrada ──▶ gerar ──Responses API──▶ GPT-5.6 Terra
                                    │          │                    (bedrock-mantle, Ohio)
                                    └──────────┴──▶ volta ──POST assinado──▶ back
```

Back e N8N estão no mesmo compose da EC2 e se falam pela rede interna, sem passar pelo
Caddy: o back chama `http://n8n:5678/webhook/creed/insights/v1`, e o N8N chama
`http://back:8000/...`.

## Os dois ramos

O `scope` do pedido decide o ramo. O formato do texto que volta é o mesmo nos dois
(`InsightContent`: análise, um texto por prisma, recomendação).

| | Individual | Empresa (task 15) |
|---|---|---|
| Quem lê | a pessoa que respondeu | a gestão |
| O que o pedido traz | notas, destaque, oportunidade e as respostas abertas | notas do grupo, participação, alinhamento por prisma e os setores com 5 ou mais respostas; nenhuma resposta aberta (P-090) |
| `prompt_version` | `individual-v0-provisorio` | `empresa-v0-provisorio` |

## O idioma

O pedido traz `language` (`pt-BR`, `en` ou `es`), o idioma da tela no envio da
resposta, guardado no insight. O `gerar` escreve o texto nele e cita prismas e setores
com os mesmos rótulos da tela (`creed-frontend/src/i18n/locales`). As instruções do
prompt continuam em português; só o texto gerado muda de idioma.

O insight da empresa sai sempre em `pt-BR` por enquanto: o contrato fixa
`Literal["pt-BR"]` no pedido da empresa, porque ele é um só por período e não tem um
idioma de tela que o defina. O workflow já aceita os três.

## O modelo

**GPT-5.6 Terra** (`openai.gpt-5.6-terra`) pela **Responses API do `bedrock-mantle` de
Ohio** (`https://bedrock-mantle.us-east-2.api.aws/openai/v1/responses`), com a
credencial "AWS (IAM) account" do N8N. O usuário IAM (`creed-n8n-bedrock`) tem a
política gerenciada `AmazonBedrockMantleInferenceAccess`.

**Por que o mantle, e não o `bedrock-runtime`:** no runtime, os modelos da OpenAI só
aceitam perfil de inferência `us.` ou `global.`, que espalha as chamadas por outras
regiões, e a conta só tem Ohio liberada: o resultado é `403` do Marketplace. O mantle
roda numa região só, então a chamada fica sempre em Ohio.

O que a chamada leva (nó "Montar chamada ao modelo"):

- `text.format` com `json_schema` `strict`: o schema é o `InsightContent`, mas sem
  `minLength`/`maxLength` nem limite de itens, que o modo strict não aceita. Os limites
  vão no prompt e são conferidos de novo no nó "Interpretar resposta";
- `reasoning.effort: medium` e `max_output_tokens: 16000` (o raciocínio conta nesse
  limite);
- `store: false`: sem ele, o Bedrock guarda pedido e resposta por 30 dias, e o pedido
  individual tem resposta aberta de quem respondeu.

O nó "Chamar modelo" fixa o header `Content-Type: application/json`: a assinatura
SigV4 do N8N não o coloca, e sem ele a Responses API responde `400`.

**Trocar de modelo** é mudar `MODELO` em "Montar chamada ao modelo"; ele vai na
chamada e volta no `model_id`. Outro modelo da OpenAI no mantle funciona igual. Um
modelo fora da OpenAI exige outra API e outro "Interpretar resposta".

Histórico: a esteira nasceu com o Nova Lite pela Converse API (2026-11-17), por custo.
O Claude Sonnet 5.5 esbarrou no Marketplace e o GPT-5.6 Terra entrou em 2026-11-18.

| O que a Responses API devolve | Volta |
|---|---|
| `status: completed` com o JSON dentro do contrato | `done`, com `model_id` e `prompt_version` |
| `incomplete` por `content_filter`, ou um `refusal` na mensagem | `failed`, `model_refusal`, `retryable: false` |
| `incomplete` por outro motivo (limite de tokens) | `failed`, `max_tokens`, `retryable: true` |
| outro `status`, sem `output_text` ou JSON inválido | `failed`, `no_structured_output`, `retryable: true` |
| JSON fora dos tamanhos | `failed`, `invalid_content`, `retryable: true` |
| erro HTTP (throttling incluído), depois de 3 tentativas com 5 s | `failed`, `bedrock_error`, `retryable: true` |
| qualquer outro erro dentro do `gerar` | `failed`, `n8n_error`, `retryable: true` |

Os prompts são **provisórios**: os de verdade e o dossiê são da CREED-807 e da
CREED-808. Problemas já vistos, para a 808:

- o modelo só recebe os códigos das dimensões (`S2`…`S8`) e os cita no texto sem saber
  o que são;
- num texto em pt-BR já saiu uma palavra em outro alfabeto no meio de outra
  ("Cultura empreendedora", execução 118). O "Interpretar resposta" não confere o
  alfabeto.

## Segredos

Nenhum segredo fica no workflow nem neste repositório.

| Segredo | No N8N | No back (`.env` da EC2) |
|---|---|---|
| token da ida | credencial Header Auth no nó "Recebe pedido do back": Name `Authorization`, Value `Bearer <token>` | `N8N_WEBHOOK_TOKEN=<token>` (sem o `Bearer `) |
| segredo da volta | data table `segredos-esteira`, linha `nome = N8N_CALLBACK_SECRET`, coluna `valor` | `N8N_CALLBACK_SECRET=<o mesmo valor>` |
| chave da AWS | credencial "AWS (IAM) account" | — |

E no back, `N8N_WEBHOOK_URL=http://n8n:5678/webhook/creed/insights/v1`.

O segredo da volta fica numa data table, e não numa credencial, porque o nó Crypto
recebe o segredo como texto e uma expressão não lê o valor de uma credencial. Como a
saída do nó que lê a tabela tem o segredo, o `insight-v1 volta` não salva dados de
execução (nem de sucesso, nem de erro, nem manual). Gere os dois valores com
`openssl rand -hex 32`.

Os exports trazem as credenciais só por referência (`id` e `name`): importados em outro
N8N, elas precisam ser criadas lá e religadas nos nós.

## Desvios da task 6

- **GPT-5.6 Terra em vez do Opus 5.5** (custo, e o Marketplace bloqueou o Claude), e com
  ele: `text.format` no lugar de `output_config.format`, sem cache de 1 h.
- **Quatro peças, e não três:** a assinatura e o `POST` de volta são um sub-workflow
  próprio (`volta`), usado pela entrada e pelo `gerar`.
- **Sem error workflow:** o error workflow do N8N só recebe o id da execução, não o
  pedido, e só dispara em produção. No lugar dele, a saída de erro do nó "Gerar insight"
  da entrada devolve `failed` (`n8n_error`). Esse caminho está montado, mas não foi
  executado: não houve como provocar um erro real dentro do `gerar`.

## Como foi verificado

- **De ponta a ponta em produção** (2026-11-18): um questionário respondido de verdade
  virou o insight `7c224b9c…`, e o callback foi aceito pelo back (`204`).
- **O `saida-n8n.json`** (2026-11-19, execução 133): a entrada rodou com o
  `contrato/exemplo-ida-individual.json`, o GPT respondeu em ~8 s e o corpo `done`
  gerado é o que está no kit. O teste do back o valida pelo modelo da volta.
- **Idiomas e empresa** (2026-11-18, execuções 120 a 125): pedidos sintéticos da empresa
  em `pt-BR` e `en` e individual em `es` voltaram `done`, no idioma pedido.
- **A assinatura:** o nó Crypto, com a mesma configuração do `volta` e o segredo de
  teste, chegou ao `signature` do `contrato/vetor-hmac.json`.
- **As falhas** (2026-11-17, ainda com o Nova Lite): pedido sem `result` voltou
  `invalid_payload`; as falhas do modelo foram exercitadas com a resposta substituída
  por pin data. Com a troca para a Responses API, o mapeamento foi reescrito e **não foi
  exercitado de novo** caso a caso: só o `done` passou por chamada real.
- **Não exercitados:** o erro HTTP do Bedrock depois das 3 tentativas
  (`bedrock_error`) e a falha inesperada do `gerar` (`n8n_error`). Provocar qualquer um
  exigiria quebrar um workflow publicado.
- No back: `pytest tests/n8n tests/external_services/n8n -q`.

## Como exportar de novo

Mudou um workflow no editor: abra-o, menu `⋯` → **Download**, e salve por cima do
arquivo em `workflows/` com o mesmo nome. Confira se não ficou pin data (o teste
recusa) e rode `pytest tests/n8n -q` antes do commit: ele recusa export com dado de
execução, segredo conhecido ou URL de request diferente das fixas, e confere modelo,
idiomas e ramos.
