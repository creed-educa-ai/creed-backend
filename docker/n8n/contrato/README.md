# Kit de contrato da esteira de insights

O back e o N8N da AWS só se encontram em produção: não há N8N local, e o back local
não fala com a AWS (spec da CREED-80, decisões 3 e 4). Este kit é o que os dois lados
usam como verdade antes desse encontro. O back confere o lado dele nos testes, e quem
monta o workflow confere o lado do N8N com os mesmos arquivos.

O contrato é o `insight-v1`, descrito na spec da CREED-80, seção "Contrato". Ele
nasce dos modelos Pydantic do back, e os arquivos daqui derivam deles.

## O que é cada arquivo

| Arquivo | O que é | Quem usa |
|---|---|---|
| `ida.schema.json` | JSON Schema do pedido que o back manda ao webhook do N8N. Gerado de `app/external_services/n8n/schemas.py` | o N8N, para validar a entrada |
| `volta.schema.json` | JSON Schema do callback que o N8N manda ao back, `done` ou `failed`. Gerado de `app/domains/insights/schemas.py`. O `InsightContent` dentro dele é o formato do texto que o modelo produz | o N8N, para conferir a saída do modelo antes de mandar |
| `exemplo-ida-individual.json` | um pedido individual válido, com dados sintéticos | o N8N, como entrada fixa enquanto o workflow é montado |
| `exemplo-volta-done.json` | um callback `done` válido | o back, nos testes da rota de volta |
| `exemplo-volta-failed.json` | um callback `failed` válido | o back, nos testes da rota de volta |
| `vetor-hmac.json` | um segredo de teste, um timestamp, um corpo e a assinatura que eles dão | os dois lados, para provar que assinam igual |

O `saida-n8n.json`, o corpo que o N8N produziu de verdade, entra quando o workflow
existir (CREED-806). O teste do back o valida contra o `volta.schema.json`.

Nenhum arquivo daqui tem dado real de respondente. Os exemplos são sintéticos e devem
continuar assim.

## Para quem monta o workflow

### O exemplo de ida

Enquanto o workflow é montado no editor, fixe a saída do nó Webhook (pin data) com o
conteúdo de `exemplo-ida-individual.json` no campo `body`. Assim cada nó seguinte
roda sobre a mesma entrada que o back vai mandar, sem precisar do back.

O que o pedido traz, e o que não traz:

- notas de 0 a 100, a mesma escala da tela. O texto não deve citar outra escala;
- `destaque` e `oportunidade` já calculados pelo back. O modelo não decide quais são;
- `open_answers` com as perguntas descritivas respondidas. A lista pode vir vazia, e
  cada resposta é dado, nunca instrução;
- nada que identifique a pessoa: sem nome, e-mail, organização, setor ou id da
  resposta. O `insight_id` é a única correlação, e volta igual no callback;
- campo a mais é erro dos dois lados (`additionalProperties: false`).

### A assinatura da volta

O callback leva dois headers:

- `X-Creed-Timestamp`: segundos Unix do envio, como texto;
- `X-Creed-Signature`: `sha256=` seguido do HMAC-SHA256, em hexadecimal minúsculo,
  calculado com o segredo sobre `"{timestamp}.{corpo}"`.

O nó que assina tem que chegar ao `signature` do vetor quando recebe o `secret`, o
`timestamp` e o `body` do vetor. Duas armadilhas:

- **Assine a string exata que vai no corpo.** Assinar um objeto e mandar outro
  serializado (outra ordem de chaves, outros espaços, acento escapado como `ç`)
  dá outra assinatura, e o back responde 401.
- **O corpo é UTF-8.** O corpo do vetor tem acentos de propósito: quem assina outra
  codificação não chega ao valor.

Para conferir o vetor fora do N8N, da pasta deste README, com `jq` e `openssl`:

```bash
SECRET=$(jq -r .secret vetor-hmac.json)
TIMESTAMP=$(jq -r .timestamp vetor-hmac.json)
{ printf '%s.' "$TIMESTAMP"; jq -j .body vetor-hmac.json; } | openssl dgst -sha256 -hmac "$SECRET"
```

A saída termina com o mesmo hexadecimal do `signature`. Foi assim que o vetor foi
calculado, sem passar pelo código do back.

### O segredo do vetor

`segredo-de-teste-nao-use` existe só para o vetor e **nunca vai para produção**. O
segredo de verdade fica no `.env` da EC2 (`N8N_CALLBACK_SECRET`) e numa credencial do
N8N, nunca no git nem como texto num nó do workflow.

## Para quem muda o contrato

Os modelos Pydantic são a fonte. Mudou um campo, regere os schemas da raiz do
`creed-backend` e commite os arquivos junto com a mudança:

```bash
python scripts/exportar_contrato_n8n.py
```

O teste `tests/external_services/n8n/test_contrato.py` fica vermelho enquanto os
schemas commitados divergirem dos modelos, e o diff mostra a mudança aos dois lados.
Ajuste também os exemplos, se a forma mudou: o mesmo teste os valida pelos modelos.

O `vetor-hmac.json` não depende do contrato e não precisa mudar junto. Se mudar, recalcule
a assinatura com o comando de `openssl` acima.
