# POC local da esteira de insights (CREED-55)

Esta pasta guarda a primeira versao executavel do fluxo, separada da integracao
com o backend. O objetivo agora e provar o desenho no n8n e observar seu tempo de
processamento. A decisao entre disparo por submissao e processamento em lote fica
para a etapa seguinte.

O gerador desta beta e deterministico e nao chama um modelo de IA. Isso permite
validar webhook, contrato, ramificacoes, resposta e metricas sem misturar latencia,
credenciais ou custo de um provedor externo. O node `Gerar insight beta` e o ponto
que sera substituido pela geracao real depois da escolha do modelo.

## Fluxo

1. recebe `POST /webhook/creed/insights/beta`;
2. valida e normaliza o contrato `beta-1`;
3. devolve HTTP 422 quando o payload e invalido;
4. agrupa respostas por prisma e gera um resultado deterministico;
5. devolve HTTP 200 com o insight e `n8n_processing_ms`.

O campo `source` identifica quem iniciou a execucao, sem determinar como o fluxo
precisa ser disparado. Hoje o exemplo usa `individual_submission`; um futuro lote
pode usar outro valor ou chamar a mesma sub-esteira para cada item.

## Executar localmente

Suba o Postgres e o n8n:

```bash
docker compose up -d db n8n
```

No primeiro uso, conclua a criacao do usuario local em http://localhost:5678.
Depois importe o workflow versionado:

```bash
docker compose exec -u node n8n n8n import:workflow --input=/workflows/creed-insight-beta.json
```

Abra o workflow `CREED - Geracao de insight (beta local)` e publique-o. O arquivo
fica inativo de proposito para uma importacao nunca expor um webhook sem revisao.

Chame a URL de producao do webhook:

```bash
curl -X POST http://localhost:5678/webhook/creed/insights/beta \
  -H "Content-Type: application/json" \
  --data-binary @docker/n8n/examples/creed-insight-beta-request.json
```

No PowerShell, use `curl.exe` no lugar de `curl`.

Tambem e possivel testar sem publicar: abra o node de webhook, clique em
`Listen for test event` e envie a mesma requisicao para
`http://localhost:5678/webhook-test/creed/insights/beta`.

## Contrato beta

Campos obrigatorios da entrada:

- `contract_version`: por enquanto, exatamente `beta-1`;
- `request_id`: idempotencia e rastreio entre sistemas;
- `form_response_id`: resposta que originou a analise;
- `answers`: lista nao vazia com `question_id`, `prisma` e pelo menos `score`
  numerico ou `answer` textual.

`score`, quando presente, deve estar entre 0 e 5. Os prismas aceitos sao os mesmos
do dominio de perguntas: `plasticidade_humana`, `empreendedorismo`,
`multiculturalismo`, `neuroinovacao` e `tomada_decisao`.

Saida de sucesso:

```json
{
  "status": "completed",
  "contract_version": "beta-1",
  "request_id": "...",
  "form_response_id": "...",
  "source": "individual_submission",
  "insight": {
    "content": "...",
    "prism_scores": [],
    "evidence_summary": {
      "answers_total": 5,
      "numeric_answers": 5,
      "textual_answers": 5
    },
    "generator": "deterministic-beta"
  },
  "metrics": {
    "received_at": "...",
    "finished_at": "...",
    "n8n_processing_ms": 1
  }
}
```

## O que esta POC ainda nao decide

- disparo individual, agendado ou em lote;
- provedor/modelo de IA e prompt final;
- autenticacao do webhook;
- persistencia do insight e callback para o backend;
- retries, fila, idempotencia efetiva e observabilidade de producao;
- infraestrutura e segredos na AWS.

Esses pontos dependem dos tempos observados, do contrato com o backend e do
alinhamento de infraestrutura. Eles nao devem ser confundidos com a validacao do
desenho do workflow desta beta.

## Resultado de referencia

Validacao local executada em 13/10/2026 com n8n 2.42.7, usando 30 requisicoes
sequenciais com o payload de exemplo:

| Medida | minimo | p50 | p95 | maximo |
|---|---:|---:|---:|---:|
| Processamento medido dentro do n8n | 6 ms | 7 ms | 10 ms | 10 ms |
| Ida e volta HTTP local | 32,98 ms | 40,91 ms | 73,18 ms | 135,88 ms |

Isso e uma referencia da orquestracao, nao um SLA. A medicao ainda nao inclui
modelo de IA, chamada ao backend, concorrencia, fila ou rede da AWS.

O n8n 2.42.7 tambem emite um aviso de que Postgres 16 recebe apenas suporte de
compatibilidade. O compose continua em Postgres 16 para nao alterar o banco local
do backend dentro desta POC, mas a versao deve ser alinhada com infraestrutura
antes da implantacao compartilhada.
